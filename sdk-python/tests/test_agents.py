"""Agent-to-agent messaging: send/reply/draft payloads, filters, types, and ``verify_agent_message``
against the shared server-produced vectors (test/fixtures/agent-messages/vectors.json at the repo root)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from agentboxd import Agentboxd, Message, MessageAgent
from agentboxd.identity import (
    AgentMessageVerificationError,
    MemoryReplayCache,
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
        "inb_1", to="b@agentboxd.com", subject="Quote", data={"sku": "SKU-42"}, type="task"
    )
    assert rec.last_json() == {
        "to": "b@agentboxd.com",
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
                "inb_1", to="b@agentboxd.com", subject="T", data={"x": 1}, type="event"
            )

    asyncio.run(main())
    assert rec.last_json()["type"] == "event"


def test_message_types_accept_agent_fields() -> None:
    agent: MessageAgent = {
        "verified": True,
        "from": "a@agentboxd.com",
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
    assert partial["agent"] is not None and partial["agent"]["from"] == "a@agentboxd.com"


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
