import asyncio
import time
from collections.abc import Mapping
from typing import Any, Optional

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

import agentboxd.identity as identity
from agentboxd.identity import (
    AGENT_CLAIM,
    RUNBOXD_CLAIM,
    WORKSPACE_CLAIM,
    AgentIdentityError,
    MemoryReplayCache,
    averify_agent_identity_token,
    verify_agent_identity_token,
)

ISSUER = "https://id.example.test"
AUD = "abxc_app"


def _key(kid: str) -> tuple[Any, dict[str, Any]]:
    private = ec.generate_private_key(ec.SECP256R1())
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update({"kid": kid, "use": "sig", "alg": "ES256"})
    return private, jwk


PRIV, JWK = _key("k1")
JWKS: dict[str, Any] = {"keys": [JWK]}


def _token(
    *, private: Any = PRIV, kid: str = "k1", extra: Optional[Mapping[str, Any]] = None, **over: object
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "sub": "pairwise-sub",
        "aud": AUD,
        "iat": now,
        "exp": now + 300,
        "jti": f"jti-{time.time_ns()}",
        "email": "agent@example.test",
        "email_verified": True,
        "preferred_username": "agent",
        AGENT_CLAIM: True,
    }
    changes = {**over, **(extra or {})}
    claims.update(changes)
    for k in [k for k, v in changes.items() if v is None]:
        del claims[k]
    return jwt.encode(claims, private, algorithm="ES256", headers={"kid": kid, "typ": "JWT"})


def test_verifies_a_good_token_and_returns_the_identity() -> None:
    out = verify_agent_identity_token(_token(), audience=AUD, issuer=ISSUER, jwks=JWKS)
    assert out["sub"] == "pairwise-sub"
    assert out["email"] == "agent@example.test"
    assert out["email_verified"] is True
    assert out["username"] == "agent"
    assert out["is_agent"] is True
    assert out["mailbox"] is True
    assert out["workspace"] is None
    assert out["runboxd"] is None
    assert out["audience"] == AUD
    assert out["expires_at"] - out["issued_at"] == 300


def test_reads_the_workspace_and_runboxd_claims() -> None:
    runboxd = {
        "v": 1,
        "workspace": "w1",
        "plan": "scale",
        "computers": None,
        "computer_hours": None,
        "memory_mb": None,
        "vcpus": None,
    }
    token = _token(extra={WORKSPACE_CLAIM: {"id": "w1", "name": "Acme"}, RUNBOXD_CLAIM: runboxd})
    out = verify_agent_identity_token(token, audience=AUD, issuer=ISSUER, jwks=JWKS)
    assert out["workspace"] == {"id": "w1", "name": "Acme"}
    assert out["runboxd"] == runboxd


@pytest.mark.parametrize(
    ("token", "kwargs", "code"),
    [
        (lambda: _token(aud="abxc_other"), {}, "invalid_token"),
        (lambda: _token(iss="https://evil.example"), {}, "invalid_token"),
        (lambda: _token(iat=int(time.time()) - 400, exp=int(time.time()) - 100), {}, "token_expired"),
        (lambda: _token(iat=int(time.time()), exp=int(time.time()) + 3600), {}, "invalid_token"),
        (lambda: _token(nonce="n1"), {"nonce": "n2"}, "nonce_mismatch"),
        (lambda: _token(extra={AGENT_CLAIM: None}), {}, "not_agent"),
        (lambda: _token(jti=None), {}, "invalid_token"),
        (lambda: _token(private=_key("k1")[0]), {}, "invalid_token"),
        (lambda: _token(kid="unknown"), {}, "invalid_token"),
    ],
)
def test_refuses_bad_tokens(token: Any, kwargs: Mapping[str, Any], code: str) -> None:
    with pytest.raises(AgentIdentityError) as err:
        verify_agent_identity_token(token(), audience=AUD, issuer=ISSUER, jwks=JWKS, **kwargs)
    assert err.value.code == code


def test_refuses_other_algorithms() -> None:
    hs = jwt.encode({"iss": ISSUER, "aud": AUD}, "x" * 32, algorithm="HS256", headers={"kid": "k1"})
    with pytest.raises(AgentIdentityError) as err:
        verify_agent_identity_token(hs, audience=AUD, issuer=ISSUER, jwks=JWKS)
    assert err.value.code == "invalid_token"


def test_single_use_with_a_replay_cache() -> None:
    cache = MemoryReplayCache()
    token = _token()
    verify_agent_identity_token(token, audience=AUD, issuer=ISSUER, jwks=JWKS, replay_cache=cache)
    with pytest.raises(AgentIdentityError) as err:
        verify_agent_identity_token(token, audience=AUD, issuer=ISSUER, jwks=JWKS, replay_cache=cache)
    assert err.value.code == "token_replayed"
    assert len(cache) == 1


def test_fetches_the_key_set_again_for_an_unknown_kid(monkeypatch: pytest.MonkeyPatch) -> None:
    new_priv, new_jwk = _key("k2")
    calls: list[bool] = []

    def fake_fetch(uri: str, fresh: bool) -> Mapping[str, Any]:
        calls.append(fresh)
        assert uri == f"{ISSUER}/.well-known/jwks.json"
        return {"keys": [JWK, new_jwk]} if fresh else JWKS

    monkeypatch.setattr(identity, "_fetch_keys", fake_fetch)
    out = verify_agent_identity_token(_token(private=new_priv, kid="k2"), audience=AUD, issuer=ISSUER)
    assert out["sub"] == "pairwise-sub"
    assert calls == [False, True]


def test_unknown_kids_refetch_the_key_set_at_most_once_per_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    new_priv, new_jwk = _key("k2")
    served: list[dict[str, Any]] = [JWKS]
    fetches: list[Any] = []

    def fake_get(uri: str, **kwargs: Any) -> httpx.Response:
        assert uri == f"{ISSUER}/.well-known/jwks.json"
        fetches.append(kwargs["timeout"])
        return httpx.Response(200, json=served[0])

    monkeypatch.setattr(identity, "_key_cache", {})
    monkeypatch.setattr(identity, "_key_fetched_at", {})
    monkeypatch.setattr(httpx, "get", fake_get)
    for i in range(20):
        with pytest.raises(AgentIdentityError) as err:
            verify_agent_identity_token(_token(kid=f"junk-{i}"), audience=AUD, issuer=ISSUER)
        assert err.value.code == "invalid_token"
    assert fetches == [10]  # the first lookup; refetches for unknown kids wait for the cooldown

    # After the cooldown, a rotated key is fetched and accepted.
    served[0] = {"keys": [JWK, new_jwk]}
    monkeypatch.setattr(identity, "_KEY_REFETCH_COOLDOWN_SECONDS", 0.0)
    out = verify_agent_identity_token(_token(private=new_priv, kid="k2"), audience=AUD, issuer=ISSUER)
    assert out["sub"] == "pairwise-sub"
    assert len(fetches) == 2


def test_async_unknown_kids_refetch_at_most_once_per_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    fetches: list[str] = []
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        fetches.append(str(request.url))
        return httpx.Response(200, json=JWKS)

    def client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["timeout"] == 10
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(identity, "_key_cache", {})
    monkeypatch.setattr(identity, "_key_fetched_at", {})
    monkeypatch.setattr(httpx, "AsyncClient", client)

    async def main() -> None:
        for i in range(10):
            with pytest.raises(AgentIdentityError):
                await averify_agent_identity_token(_token(kid=f"junk-{i}"), audience=AUD, issuer=ISSUER)

    asyncio.run(main())
    assert fetches == [f"{ISSUER}/.well-known/jwks.json"]


def test_an_answer_that_is_not_a_key_set_is_an_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(uri: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(200, text="<html>Down for maintenance</html>")

    monkeypatch.setattr(identity, "_key_cache", {})
    monkeypatch.setattr(identity, "_key_fetched_at", {})
    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(AgentIdentityError) as err:
        verify_agent_identity_token(_token(), audience=AUD, issuer=ISSUER)
    assert err.value.code == "invalid_token"


def test_async_form(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_afetch(uri: str, fresh: bool) -> Mapping[str, Any]:
        return JWKS

    monkeypatch.setattr(identity, "_afetch_keys", fake_afetch)
    out = asyncio.run(averify_agent_identity_token(_token(), audience=AUD, issuer=ISSUER))
    assert out["is_agent"] is True


def test_requires_an_audience() -> None:
    with pytest.raises(TypeError):
        verify_agent_identity_token(_token(), audience="", issuer=ISSUER, jwks=JWKS)


def test_the_replay_cache_keeps_the_jti_until_exp_plus_the_clock_tolerance() -> None:
    seen: list[float] = []

    class Spy:
        def use(self, nonce: str, expires_at: float) -> bool:
            seen.append(expires_at)
            return True

    now = int(time.time())
    for tolerance in (30, 5):
        verify_agent_identity_token(
            _token(iat=now, exp=now + 300),
            audience=AUD,
            issuer=ISSUER,
            jwks=JWKS,
            replay_cache=Spy(),
            clock_tolerance=tolerance,
        )
    assert seen == [now + 330, now + 305]

    # Expired 10 s ago but inside the tolerance: still accepted, so a replay must still be caught.
    cache = MemoryReplayCache()
    late = _token(iat=now - 310, exp=now - 10)
    verify_agent_identity_token(late, audience=AUD, issuer=ISSUER, jwks=JWKS, replay_cache=cache)
    with pytest.raises(AgentIdentityError) as err:
        verify_agent_identity_token(late, audience=AUD, issuer=ISSUER, jwks=JWKS, replay_cache=cache)
    assert err.value.code == "token_replayed"
