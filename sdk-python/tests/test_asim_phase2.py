"""aSIM phase 2 (docs/asim-phase2-contract.md): agent-held keys, author signatures (against the shared
vectors in test/fixtures/agent-messages/author-vectors.json), handles, the public directory and OASF."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from agentboxd import Agentboxd, Message
from agentboxd.identity import (
    AUTHOR_JWS_TYP,
    AuthorSignatureVerificationError,
    create_key_proof,
    generate_agent_key,
    jwk_thumbprint,
    sign_agent_message,
    verify_agent_message,
    verify_author_signature,
)

from .conftest import Recorder, make_async

VECTORS = Path(__file__).resolve().parents[2] / "test" / "fixtures" / "agent-messages" / "author-vectors.json"
needs_vectors = pytest.mark.skipif(not VECTORS.is_file(), reason="shared vectors live in the repository")
FIXTURE: dict[str, Any] = json.loads(VECTORS.read_text(encoding="utf-8")) if VECTORS.is_file() else {}


def _calls(rec: Recorder) -> list[tuple[str, str, dict[str, str], Any]]:
    return [
        (
            q.method,
            q.url.raw_path.decode().split("?")[0],
            dict(q.url.params),
            json.loads(q.content) if q.content else None,
        )
        for q in rec.requests
    ]


# ---------- shared vectors ----------


@needs_vectors
@pytest.mark.parametrize("vector", FIXTURE.get("vectors", []), ids=lambda v: str(v["name"]))
def test_author_vectors(vector: dict[str, Any]) -> None:
    message = vector["message"]
    if vector["expect"] == "valid":
        out = verify_author_signature(message, keys=FIXTURE["keys"])
        assert out["kid"] == message["author"]["kid"]
        if "covered" in vector:
            assert dict(out["covered"]) == vector["covered"]
    else:
        with pytest.raises(AuthorSignatureVerificationError) as err:
            verify_author_signature(message, keys=FIXTURE["keys"])
        assert err.value.code == vector["expect"]


@needs_vectors
def test_key_proof_vector() -> None:
    proof = FIXTURE["proof"]
    assert jwk_thumbprint(proof["public_jwk"]) == proof["kid"]
    import jwt

    header = jwt.get_unverified_header(proof["proof"])
    assert header["typ"] == "agentboxd-key-proof+jwt"
    key = jwt.PyJWK(proof["public_jwk"], algorithm="EdDSA").key
    claims = json.loads(jwt.api_jws.decode(proof["proof"], key=key, algorithms=["EdDSA"]))
    assert claims["sub"] == proof["address"]
    assert claims["jkt"] == proof["kid"]
    assert claims["iat"] == proof["iat"]


# ---------- round trips ----------


@pytest.mark.parametrize("alg", ["EdDSA", "ES256"])
def test_generate_proof_sign_verify(alg: Any) -> None:
    key = generate_agent_key(alg)
    assert key["alg"] == alg and key["kid"] == jwk_thumbprint(key["public_jwk"])
    assert "d" not in key["public_jwk"]
    proof = create_key_proof(key, "Buyer@Acme.example")
    import jwt

    pub = jwt.PyJWK(key["public_jwk"], algorithm=alg).key
    claims = json.loads(jwt.api_jws.decode(proof, key=pub, algorithms=[alg]))
    assert claims["sub"] == "buyer@acme.example" and claims["aud"] == "agentboxd:agent-key"
    assert len(claims["nonce"]) >= 16

    data = {"sku": "A-40", "qty": 40}
    sig = sign_agent_message(
        key,
        from_="buyer@acme.example",
        subject="Quote",
        text="Hi\r\nthere",
        data=data,
        attachments=[b"spec bytes"],
        type="task",
        to=["Supplier <supplier@agentboxd.test>"],
        cc=[],
    )
    assert jwt.get_unverified_header(sig)["typ"] == AUTHOR_JWS_TYP
    import hashlib

    message: dict[str, Any] = {
        "from": "Buyer <buyer@acme.example>",
        "to": ["supplier@agentboxd.test"],
        "cc": [],
        "subject": "Quote",
        "text": "Hi\nthere",
        "html": None,
        "data": data,
        "type": "task",
        "in_reply_to": None,
        "attachments": [{"sha256": hashlib.sha256(b"spec bytes").hexdigest()}],
        "author": {"signature": sig, "kid": key["kid"], "alg": alg, "verified": True},
    }
    keys = {"keys": [{**key["public_jwk"], "kid": key["kid"], "alg": alg, "status": "active"}]}
    out = verify_author_signature(message, keys=keys)
    assert out["covered"]["text"] and out["covered"]["recipients"] and not out["covered"]["html"]
    with pytest.raises(AuthorSignatureVerificationError) as err:
        verify_author_signature({**message, "data": {"sku": "A-40", "qty": 41}}, keys=keys)
    assert err.value.code == "content_mismatch"
    with pytest.raises(AuthorSignatureVerificationError) as err:
        verify_author_signature({**message, "author": None}, keys=keys)
    assert err.value.code == "no_signature"


def test_delivery_signature_binds_the_author_signature() -> None:
    # verify_agent_message flags an author signature that isn't the one agent_sig names (content_mismatch).
    vectors = json.loads(
        (VECTORS.parent / "vectors.json").read_text(encoding="utf-8") if VECTORS.is_file() else "{}"
    )
    if not vectors:
        pytest.skip("shared vectors live in the repository")
    valid = next(v for v in vectors["vectors"] if v["expect"] == "valid")
    message = dict(valid["message"])
    now = float(valid["claims"]["iat"])
    kwargs: dict[str, Any] = {
        "recipient": valid["recipient"],
        "issuer": vectors["issuer"],
        "keys": vectors["keys"],
        "now": now,
        "max_age_seconds": None,
    }
    # No agent_sig claim in Track A vectors: an author block alone changes nothing.
    message["author"] = {"signature": "a.b.c"}
    assert verify_agent_message(message, **kwargs)["from"]

    # Re-sign the vector's claims with agent_sig, as a phase 2 delivery signature would carry it.
    import base64
    import hashlib

    import jwt

    server = generate_agent_key("ES256")
    author_jws = "x.y.z"
    digest = base64.urlsafe_b64encode(hashlib.sha256(author_jws.encode()).digest()).rstrip(b"=").decode()
    claims = {**valid["claims"], "agent_sig": {"kid": "k", "jws_sha256": digest}}
    delivery = jwt.api_jws.encode(
        json.dumps(claims).encode(),
        server["private_key"],
        algorithm="ES256",
        headers={"kid": server["kid"], "typ": "agentboxd-msg+jwt"},
    )
    keys = {"keys": [{**server["public_jwk"], "kid": server["kid"], "alg": "ES256", "status": "active"}]}
    signed = {**valid["message"], "agent": {"signature": delivery}}
    kwargs["keys"] = keys
    assert verify_agent_message({**signed, "author": {"signature": author_jws}}, **kwargs)["from"]
    with pytest.raises(Exception) as err:
        verify_agent_message({**signed, "author": {"signature": "other.author.jws"}}, **kwargs)
    assert getattr(err.value, "code", None) == "content_mismatch"


# ---------- client ----------


def test_agent_keys_and_oasf(client: Agentboxd, rec: Recorder) -> None:
    rec.default = {"data": []}
    client.agents.keys.list("i1")
    client.agents.keys.register("i1", public_jwk={"kty": "OKP", "crv": "Ed25519", "x": "x"}, proof="p.r.f")
    client.agents.keys.retire("i1", "kid-1")
    client.agents.keys.revoke("i1", "kid-1", reason="leak", since="2026-09-27T09:00:00Z")
    client.agents.keys.revoke("i1", "kid-2")
    client.agents.oasf("i1")
    client.agents.update("i1", visibility="public", handle="billing", indexable=True)
    client.agents.update("i1", handle=None)
    assert _calls(rec) == [
        ("GET", "/v1/inboxes/i1/agent/keys", {}, None),
        (
            "POST",
            "/v1/inboxes/i1/agent/keys",
            {},
            {"public_jwk": {"kty": "OKP", "crv": "Ed25519", "x": "x"}, "proof": "p.r.f"},
        ),
        ("POST", "/v1/inboxes/i1/agent/keys/kid-1/retire", {}, None),
        (
            "POST",
            "/v1/inboxes/i1/agent/keys/kid-1/revoke",
            {},
            {"reason": "leak", "since": "2026-09-27T09:00:00Z"},
        ),
        ("POST", "/v1/inboxes/i1/agent/keys/kid-2/revoke", {}, {}),
        ("GET", "/v1/inboxes/i1/agent/oasf", {}, None),
        (
            "PATCH",
            "/v1/inboxes/i1/agent",
            {},
            {"visibility": "public", "handle": "billing", "indexable": True},
        ),
        ("PATCH", "/v1/inboxes/i1/agent", {}, {"handle": None}),
    ]


def test_directory_handles_and_public_search(client: Agentboxd, rec: Recorder) -> None:
    rec.default = {"handle": "@acme", "previous": []}
    client.directory.resolve(handle="@acme/billing")
    client.directory.resolve("billing@acme.example")
    client.directory.search(q="invoice", scope="public")
    assert client.directory.get_handle()["handle"] == "@acme"
    client.directory.set_handle("acme")
    client.directory.release_handle()
    with pytest.raises(ValueError):
        client.directory.resolve()
    assert _calls(rec) == [
        ("GET", "/v1/directory/resolve", {"handle": "@acme/billing"}, None),
        ("GET", "/v1/directory/resolve", {"address": "billing@acme.example"}, None),
        ("GET", "/v1/directory/search", {"q": "invoice", "scope": "public"}, None),
        ("GET", "/v1/directory/handle", {}, None),
        ("PUT", "/v1/directory/handle", {}, {"handle": "acme"}),
        ("DELETE", "/v1/directory/handle", {}, None),
    ]


def test_public_directory(client: Agentboxd, rec: Recorder) -> None:
    rec.default = {"data": [], "next_cursor": None}
    client.public_directory.search(capability="invoice-lookup", limit=5)
    client.public_directory.get("billing@acme.example")
    client.public_directory.a2a_card("billing@acme.example")
    client.public_directory.oasf("billing@acme.example")
    client.public_directory.keys("billing@acme.example")
    client.public_directory.handle("@acme", "billing")
    base = "/v1/public/agents/billing%40acme.example"
    assert _calls(rec) == [
        ("GET", "/v1/public/agents", {"capability": "invoice-lookup", "limit": "5"}, None),
        ("GET", base, {}, None),
        ("GET", f"{base}/agent-card.json", {}, None),
        ("GET", f"{base}/oasf.json", {}, None),
        ("GET", f"{base}/keys.json", {}, None),
        ("GET", "/v1/public/handles/acme/billing", {}, None),
    ]


def test_send_and_reply_carry_the_agent_signature(client: Agentboxd, rec: Recorder) -> None:
    rec.default = {"id": "m1"}
    client.messages.send("i1", to="@acme/billing", subject="Quote", text="Hi", agent_signature="a.b.c")
    assert rec.last_json() == {
        "to": "@acme/billing",
        "subject": "Quote",
        "text": "Hi",
        "agent_signature": "a.b.c",
    }
    client.messages.reply("i1", "m0", text="Yes", agent_signature="d.e.f")
    assert rec.last_json() == {"text": "Yes", "agent_signature": "d.e.f"}


def test_message_author_type() -> None:
    m: Message = {"author": {"verified": True, "kid": "k", "alg": "EdDSA", "signature": "a.b.c"}}  # type: ignore[typeddict-item]
    assert m["author"] is not None and m["author"]["alg"] == "EdDSA"


def test_async_phase2(rec: Recorder) -> None:
    async def run() -> None:
        c = make_async(rec)
        await c.agents.keys.list("i1")
        await c.agents.keys.register("i1", public_jwk={"kty": "OKP"}, proof="p")
        await c.agents.keys.retire("i1", "k")
        await c.agents.keys.revoke("i1", "k", reason="r")
        await c.agents.oasf("i1")
        await c.directory.resolve(handle="@acme/billing")
        await c.directory.search(scope="public")
        await c.directory.get_handle()
        await c.directory.set_handle("acme")
        await c.directory.release_handle()
        await c.public_directory.search(q="x")
        await c.public_directory.get("a@b.example")
        await c.public_directory.a2a_card("a@b.example")
        await c.public_directory.oasf("a@b.example")
        await c.public_directory.keys("a@b.example")
        await c.public_directory.handle("acme", "billing")
        await c.messages.send("i1", to="x@y.example", subject="s", text="t", agent_signature="a.b.c")
        await c.close()

    asyncio.run(run())
    paths = [c[1] for c in _calls(rec)]
    assert paths == [
        "/v1/inboxes/i1/agent/keys",
        "/v1/inboxes/i1/agent/keys",
        "/v1/inboxes/i1/agent/keys/k/retire",
        "/v1/inboxes/i1/agent/keys/k/revoke",
        "/v1/inboxes/i1/agent/oasf",
        "/v1/directory/resolve",
        "/v1/directory/search",
        "/v1/directory/handle",
        "/v1/directory/handle",
        "/v1/directory/handle",
        "/v1/public/agents",
        "/v1/public/agents/a%40b.example",
        "/v1/public/agents/a%40b.example/agent-card.json",
        "/v1/public/agents/a%40b.example/oasf.json",
        "/v1/public/agents/a%40b.example/keys.json",
        "/v1/public/handles/acme/billing",
        "/v1/inboxes/i1/messages/send",
    ]
    assert json.loads(rec.last.content)["agent_signature"] == "a.b.c"
