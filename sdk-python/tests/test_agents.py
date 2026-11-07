"""Agent-to-agent messaging: send/reply/draft payloads, filters, types, and ``verify_agent_message``
against the shared server-produced vectors (test/fixtures/agent-messages/vectors.json at the repo root)."""

import asyncio
import base64
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import agentboxd.identity as identity
from agentboxd import Agentboxd, Message, MessageAgent
from agentboxd.identity import (
    AgentMessageVerificationError,
    MemoryReplayCache,
    RevocationCheck,
    averify_agent_message,
    verify_agent_message,
)

from .conftest import Recorder, make_async

VECTORS = Path(__file__).resolve().parents[2] / "test" / "fixtures" / "agent-messages" / "vectors.json"
needs_vectors = pytest.mark.skipif(not VECTORS.is_file(), reason="shared vectors live in the repository")
FIXTURE: dict[str, Any] = json.loads(VECTORS.read_text(encoding="utf-8")) if VECTORS.is_file() else {}


def _code(fn: Any) -> str:
    try:
        fn()
    except AgentMessageVerificationError as err:
        return err.code
    return "valid"


def _verify(vector: dict[str, Any], **overrides: Any) -> Any:
    message = overrides.pop("message", vector["message"])
    opts: dict[str, Any] = {
        "recipient": vector["recipient"],
        "issuer": FIXTURE["issuer"],
        "keys": FIXTURE["keys"],
        "now": vector["claims"]["iat"] + 60,
    }
    opts.update(overrides)
    return verify_agent_message(message, **opts)


# ---------- client ----------


def test_send_and_reply_carry_data_and_type(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"id": "m1", "channel": "agent", "type": "task", "data": {"sku": "SKU-42"}}, status=202)
    sent = client.messages.send(
        "inb_1", to="b@homingbox.net", subject="Quote", data={"sku": "SKU-42"}, type="task"
    )
    assert rec.last_json() == {
        "to": "b@homingbox.net",
        "subject": "Quote",
        "data": {"sku": "SKU-42"},
        "type": "task",
    }
    assert sent.get("channel") == "agent"
    client.messages.reply("inb_1", "m0", data=[{"status": "done"}], type="event")
    assert rec.last_json() == {"data": [{"status": "done"}], "type": "event"}
    client.messages.send("inb_1", to="b@x.com", subject="Plain", text="hi")
    assert "data" not in rec.last_json() and "type" not in rec.last_json()


def test_filters_and_drafts(client: Agentboxd, rec: Recorder) -> None:
    rec.default = {"data": [], "next_cursor": None}
    client.messages.list("inb_1", channel="agent", type="task")
    assert rec.last_params() == {"channel": "agent", "type": "task"}
    rec.default = {"data": None}
    client.messages.wait("inb_1", timeout=5, type="task")
    assert rec.last_params()["type"] == "task"
    rec.default = {"data": [], "next_cursor": None}
    client.search("invoice", channel="email")
    assert rec.last_params()["channel"] == "email"
    rec.default = {}
    client.drafts.create("inb_1", to="b@x.com", data={"a": 1}, type="task")
    assert rec.last_json()["data"] == {"a": 1} and rec.last_json()["type"] == "task"
    client.drafts.update("inb_1", "d1", data=None)
    assert rec.last_json() == {"data": None}
    client.drafts.update("inb_1", "d1", subject="x")
    assert "data" not in rec.last_json()
    rec.default = {"data": [], "paused": False}
    client.messages.claim("inb_1", type="task", channel="agent")
    assert rec.last_json() == {"type": "task", "channel": "agent"}


def test_async_send_with_data(rec: Recorder) -> None:
    rec.reply({"id": "m1"}, status=202)

    async def main() -> None:
        async with make_async(rec) as client:
            await client.messages.send(
                "inb_1", to="b@homingbox.net", subject="T", data={"x": 1}, type="event"
            )

    asyncio.run(main())
    assert rec.last_json()["type"] == "event"


def test_message_types_accept_agent_fields() -> None:
    agent: MessageAgent = {
        "verified": True,
        "from": "a@homingbox.net",
        "assurance": "workspace",
        "signed_at": "2026-09-25T09:14:03.000Z",
        "kid": "k1",
        "signature": "a.b.c",
    }
    partial: Message = {
        "channel": "agent",
        "type": "task",
        "data": {"a": 1},
        "agent": agent,
        "delivery": None,
    }  # type: ignore[typeddict-item]
    assert partial["agent"] is not None and partial["agent"]["from"] == "a@homingbox.net"


# ---------- verify_agent_message ----------


@needs_vectors
@pytest.mark.parametrize("index", range(len(FIXTURE.get("vectors", []))))
def test_shared_vectors(index: int) -> None:
    vector = FIXTURE["vectors"][index]
    assert _code(lambda: _verify(vector)) == vector["expect"], vector["name"]


@needs_vectors
def test_result_and_recipient_forms() -> None:
    v = FIXTURE["vectors"][0]
    r = _verify(v)
    assert r["from"] == "buyer@agents.agentboxd.test"
    assert r["type"] == "task" and r["assurance"] == "workspace" and r["iat"] == v["claims"]["iat"]
    folded = "\r\n ".join(v["message"]["agent"]["signature"][i : i + 76] for i in range(0, 2000, 76))
    assert (
        _code(lambda: _verify(v, recipient=f"Supplier <{v['recipient'].upper()}>", signature=folded))
        == "valid"
    )
    assert _verify(FIXTURE["vectors"][1])["assurance"] == "unclaimed"


@needs_vectors
def test_every_covered_field_is_checked() -> None:
    v = FIXTURE["vectors"][0]
    m = v["message"]
    patches: list[dict[str, Any]] = [
        {"html": "<p>x</p>"},
        {"subject": "other"},
        {"attachments": m["attachments"][1:]},
        {"type": "event"},
        {"cc": []},
        {"in_reply_to": "<x@y>"},
        {"rfc_message_id": "<o@x>"},
        {"data": None},
    ]
    for patch in patches:
        assert _code(lambda patch=patch: _verify(v, message={**m, **patch})) == "content_mismatch", patch
    # Order of attachments and data keys, and CRLF vs LF in the text, don't matter.
    assert (
        _code(lambda: _verify(v, message={**m, "attachments": list(reversed(m["attachments"]))})) == "valid"
    )
    assert (
        _code(lambda: _verify(v, message={**m, "data": dict(reversed(list(m["data"].items())))})) == "valid"
    )
    assert _code(lambda: _verify(v, message={**m, "text": m["text"].replace("\r\n", "\n")})) == "valid"


@needs_vectors
def test_header_key_and_issuer_failures() -> None:
    v = FIXTURE["vectors"][0]
    sig: str = v["message"]["agent"]["signature"]
    head, payload, s = sig.split(".")

    def with_header(**h: Any) -> str:
        import base64

        raw = json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))
        raw.update(h)
        enc = base64.urlsafe_b64encode(json.dumps(raw).encode()).rstrip(b"=").decode()
        return f"{enc}.{payload}.{s}"

    assert _code(lambda: _verify(v, message={**v["message"], "agent": None})) == "no_signature"
    assert _code(lambda: _verify(v, signature=with_header(alg="none"))) == "invalid_signature"
    assert _code(lambda: _verify(v, signature=with_header(alg="HS256"))) == "invalid_signature"
    assert _code(lambda: _verify(v, signature=with_header(typ="JWT"))) == "invalid_signature"
    assert _code(lambda: _verify(v, signature=with_header(kid="nope"))) == "unknown_key"
    other = FIXTURE["keys"]["keys"][1]["kid"]
    assert _code(lambda: _verify(v, signature=with_header(kid=other))) == "invalid_signature"
    assert _code(lambda: _verify(v, issuer="https://id.example.org")) == "wrong_issuer"


@needs_vectors
def test_unknown_kids_fetch_the_key_set_at_most_once_per_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    v = FIXTURE["vectors"][0]
    head, payload, s = v["message"]["agent"]["signature"].split(".")
    uri = "https://keys.example.test/agent-keys.json"
    served: list[Any] = [{"keys": []}]
    fetches: list[Any] = []

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        assert url == uri
        fetches.append(kwargs["timeout"])
        return httpx.Response(200, json=served[0])

    def junk(i: int) -> str:
        raw = json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))
        raw["kid"] = f"junk-{i}"
        return base64.urlsafe_b64encode(json.dumps(raw).encode()).rstrip(b"=").decode() + f".{payload}.{s}"

    monkeypatch.setattr(identity, "_key_cache", {})
    monkeypatch.setattr(identity, "_key_fetched_at", {})
    monkeypatch.setattr(httpx, "get", fake_get)
    for i in range(20):
        assert _code(lambda i=i: _verify(v, keys=None, keys_uri=uri, signature=junk(i))) == "unknown_key"
    assert fetches == [10]  # the first lookup; refetches for unknown kids wait for the cooldown

    # After the cooldown, a key published since the last fetch is found.
    served[0] = FIXTURE["keys"]
    monkeypatch.setattr(identity, "_KEY_REFETCH_COOLDOWN_SECONDS", 0.0)
    assert _code(lambda: _verify(v, keys=None, keys_uri=uri)) == "valid"
    assert len(fetches) == 2


@needs_vectors
def test_an_answer_that_is_not_a_key_set_is_refused_and_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    v = FIXTURE["vectors"][0]
    uri = "https://keys.example.test/malformed/agent-keys.json"
    answers = [
        httpx.Response(200, text="<html>Down for maintenance</html>", headers={"Content-Type": "text/html"}),
        httpx.Response(200, json={}),
        httpx.Response(200, json=[FIXTURE["keys"]]),
        httpx.Response(200, json={"keys": "none"}),
        httpx.Response(200, json={"keys": [None, 7, *FIXTURE["keys"]["keys"]]}),
    ]
    fetches: list[str] = []

    def fake_get(url: str, **kwargs: Any) -> httpx.Response:
        fetches.append(url)
        return answers[min(len(fetches), len(answers)) - 1]

    monkeypatch.setattr(identity, "_key_cache", {})
    monkeypatch.setattr(identity, "_key_fetched_at", {})
    monkeypatch.setattr(httpx, "get", fake_get)
    for _ in range(4):
        assert _code(lambda: _verify(v, keys=None, keys_uri=uri)) == "unknown_key"
    assert len(fetches) == 4  # nothing broken was cached
    # Entries that aren't keys are skipped.
    assert _code(lambda: _verify(v, keys=None, keys_uri=uri)) == "valid"
    assert _code(lambda: _verify(v, keys=None, keys_uri=uri)) == "valid"
    assert len(fetches) == 5  # a real key set is cached

    # The async form reads the answer the same way.
    real_client = httpx.AsyncClient

    def page(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>Down for maintenance</html>")

    def client(**kwargs: Any) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(page), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)

    async def run() -> str:
        try:
            await averify_agent_message(
                v["message"],
                recipient=v["recipient"],
                issuer=FIXTURE["issuer"],
                keys_uri="https://keys.example.test/malformed-async/agent-keys.json",
                now=v["claims"]["iat"] + 60,
            )
        except AgentMessageVerificationError as err:
            return err.code
        return "valid"

    assert asyncio.run(run()) == "unknown_key"


@needs_vectors
def test_freshness_and_replay() -> None:
    v = FIXTURE["vectors"][0]
    iat = v["claims"]["iat"]
    assert _code(lambda: _verify(v, now=iat + 900)) == "valid"
    assert _code(lambda: _verify(v, now=iat + 1000)) == "too_old"
    assert _code(lambda: _verify(v, now=iat + 100_000, max_age_seconds=None)) == "valid"
    assert _code(lambda: _verify(v, now=iat + 120, max_age_seconds=60)) == "too_old"
    assert _code(lambda: _verify(v, now=iat - 120)) == "issued_in_future"
    plain = FIXTURE["vectors"][1]
    assert _code(lambda: _verify(plain, now=plain["claims"]["iat"] + 100_000)) == "valid"

    seen: set[str] = set()

    class Cache:
        def use(self, nonce: str, expires_at: float) -> bool:
            if nonce in seen:
                return False
            seen.add(nonce)
            return True

    assert _code(lambda: _verify(v, replay_cache=Cache())) == "valid"
    assert _code(lambda: _verify(v, replay_cache=Cache())) == "replayed"
    memory = MemoryReplayCache()
    assert memory.use("n", 4_102_444_800) is True
    assert memory.use("n", 4_102_444_800) is False


@needs_vectors
def test_async_variant_with_keys() -> None:
    v = FIXTURE["vectors"][0]
    r = asyncio.run(
        averify_agent_message(
            v["message"],
            recipient=v["recipient"],
            issuer=FIXTURE["issuer"],
            keys=FIXTURE["keys"],
            now=v["claims"]["iat"],
        )
    )
    assert r["msg_id"] == v["message"]["rfc_message_id"]


# ---------- replay: kept as long as the signature verifies, recorded last ----------


class _SetCache:
    def __init__(self) -> None:
        self.seen: dict[str, float] = {}

    def use(self, nonce: str, expires_at: float) -> bool:
        if nonce in self.seen:
            return False
        self.seen[nonce] = expires_at
        return True


def _plain() -> dict[str, Any]:
    return next(v for v in FIXTURE["vectors"] if v["claims"]["type"] == "message" and v["expect"] == "valid")


@needs_vectors
def test_replay_cache_keeps_the_nonce_until_iat_plus_max_age_plus_tolerance() -> None:
    v = FIXTURE["vectors"][0]
    iat = v["claims"]["iat"]
    cache = _SetCache()
    _verify(v, replay_cache=cache)
    assert cache.seen[v["claims"]["nonce"]] == iat + 900 + 30
    custom = _SetCache()
    _verify(v, replay_cache=custom, max_age_seconds=60, clock_tolerance=5)
    assert custom.seen[v["claims"]["nonce"]] == iat + 60 + 5
    plain = _plain()
    day = _SetCache()
    _verify(plain, replay_cache=day)
    assert day.seen[plain["claims"]["nonce"]] == plain["claims"]["iat"] + 86_400 + 30


@needs_vectors
def test_with_a_replay_cache_a_signature_older_than_a_day_is_too_old() -> None:
    plain = _plain()
    iat = plain["claims"]["iat"]
    # Without a replay cache, plain messages have no age limit (archives, audits).
    assert _code(lambda: _verify(plain, now=iat + 200_000)) == "valid"
    assert _code(lambda: _verify(plain, replay_cache=_SetCache(), now=iat + 86_400)) == "valid"
    # Its nonce is forgotten after a day, so the same signature must not verify again after that.
    assert _code(lambda: _verify(plain, replay_cache=_SetCache(), now=iat + 86_400 + 31)) == "too_old"
    assert (
        _code(lambda: _verify(plain, replay_cache=_SetCache(), max_age_seconds=None, now=iat + 200_000))
        == "too_old"
    )


@needs_vectors
def test_the_nonce_is_recorded_only_after_the_revocation_check_passed() -> None:
    v = FIXTURE["vectors"][0]
    down = [True]

    def handler(request: httpx.Request) -> httpx.Response:
        if down[0]:
            raise httpx.ConnectError("directory unreachable", request=request)
        return httpx.Response(200, json={"valid": True, "status": "active", "reasons": []})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    check: RevocationCheck = {"api_key": "mr_k", "base_url": "http://api.test", "http_client": http}
    cache = _SetCache()
    assert _code(lambda: _verify(v, replay_cache=cache, check_revocation=check)) == "revocation_check_failed"
    assert cache.seen == {}
    down[0] = False
    assert _code(lambda: _verify(v, replay_cache=cache, check_revocation=check)) == "valid"
    assert _code(lambda: _verify(v, replay_cache=cache, check_revocation=check)) == "replayed"

    # A revoked sender doesn't burn the nonce either, also in the async form.
    def revoked(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"valid": False, "status": "revoked", "reasons": []})

    async def run(cache: _SetCache) -> str:
        async with httpx.AsyncClient(transport=httpx.MockTransport(revoked)) as client:
            try:
                await averify_agent_message(
                    v["message"],
                    recipient=v["recipient"],
                    issuer=FIXTURE["issuer"],
                    keys=FIXTURE["keys"],
                    now=v["claims"]["iat"] + 60,
                    replay_cache=cache,
                    check_revocation={"api_key": "mr_k", "http_client": client},
                )
            except AgentMessageVerificationError as err:
                return err.code
        return "valid"

    untouched = _SetCache()
    assert asyncio.run(run(untouched)) == "agent_revoked"
    assert untouched.seen == {}


@needs_vectors
def test_a_revoked_key_without_a_readable_revoked_at_is_revoked() -> None:
    v = FIXTURE["vectors"][0]
    head = v["message"]["agent"]["signature"].split(".")[0]
    kid = json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))["kid"]

    def keys_with(**patch: Any) -> dict[str, Any]:
        return {"keys": [{**k, **patch} if k["kid"] == kid else k for k in FIXTURE["keys"]["keys"]]}

    for revoked_at in (None, "not a time"):
        keys = keys_with(status="revoked", revoked_at=revoked_at)
        assert _code(lambda keys=keys: _verify(v, keys=keys)) == "key_revoked"
    no_time = {
        "keys": [
            {k: x for k, x in key.items() if k != "revoked_at"} for key in keys_with(status="revoked")["keys"]
        ]
    }
    assert _code(lambda: _verify(v, keys=no_time)) == "key_revoked"
    # Retired message keys keep verifying (a rotated-out key signs 6 more minutes).
    retired = keys_with(status="retired", retired_at="2020-01-01T00:00:00.000Z")
    assert _code(lambda: _verify(v, keys=retired)) == "valid"
