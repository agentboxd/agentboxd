"""aSIM agent cards and the directory (docs/asim-directory-contract.md): request shapes (sync + async) and
``check_revocation`` on ``verify_agent_message`` against the shared vectors."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentboxd import Agentboxd
from agentboxd.identity import (
    AgentMessageVerificationError,
    RevocationCheck,
    averify_agent_message,
    verify_agent_message,
)

from .conftest import Recorder, make_async

VECTORS = Path(__file__).resolve().parents[2] / "test" / "fixtures" / "agent-messages" / "vectors.json"
needs_vectors = pytest.mark.skipif(not VECTORS.is_file(), reason="shared vectors live in the repository")
FIXTURE: dict[str, Any] = json.loads(VECTORS.read_text(encoding="utf-8")) if VECTORS.is_file() else {}


def _calls(rec: Recorder) -> list[tuple[str, str, dict[str, str], Any]]:
    return [
        (q.method, q.url.path, dict(q.url.params), json.loads(q.content) if q.content else None)
        for q in rec.requests
    ]


def test_agents(client: Agentboxd, rec: Recorder) -> None:
    rec.default = {"status": "active", "card": {"name": "Billing"}}
    assert client.agents.get("i1")["status"] == "active"
    client.agents.update(
        "i1", name="Billing", visibility="workspace", capabilities={"accepts_types": ["task"]}
    )
    client.agents.update("i1", description=None, documentation_url=None)
    client.agents.revoke("i1", reason="key leak")
    client.agents.revoke("i1")
    client.agents.restore("i1")
    rec.reply(status=204)
    client.agents.delete("i1")
    assert _calls(rec) == [
        ("GET", "/v1/inboxes/i1/agent", {}, None),
        (
            "PATCH",
            "/v1/inboxes/i1/agent",
            {},
            {"name": "Billing", "visibility": "workspace", "capabilities": {"accepts_types": ["task"]}},
        ),
        ("PATCH", "/v1/inboxes/i1/agent", {}, {"description": None, "documentation_url": None}),
        ("POST", "/v1/inboxes/i1/agent/revoke", {}, {"reason": "key leak"}),
        ("POST", "/v1/inboxes/i1/agent/revoke", {}, {}),
        ("POST", "/v1/inboxes/i1/agent/restore", {}, None),
        ("DELETE", "/v1/inboxes/i1/agent", {}, None),
    ]


def test_card_on_create(client: Agentboxd, rec: Recorder) -> None:
    rec.default = {"id": "i1"}
    client.inboxes.create(username="billing", card={"name": "Billing"})
    client.identities.create(card={"name": "Research", "visibility": "private"})
    client.inboxes.create(username="plain")
    assert [(c[1], c[3]) for c in _calls(rec)] == [
        ("/v1/inboxes", {"username": "billing", "card": {"name": "Billing"}}),
        ("/v1/identities", {"card": {"name": "Research", "visibility": "private"}}),
        ("/v1/inboxes", {"username": "plain"}),
    ]


def test_directory(client: Agentboxd, rec: Recorder) -> None:
    client.directory.resolve("a@homingbox.net")
    client.directory.verify(signature="jws")
    client.directory.verify(address="a@homingbox.net")
    client.directory.search(q="billing", type="task", limit=10)
    client.directory.search()
    client.directory.report("a@homingbox.net", "spam", message_id="m1")
    assert _calls(rec) == [
        ("GET", "/v1/directory/resolve", {"address": "a@homingbox.net"}, None),
        ("POST", "/v1/directory/verify", {}, {"signature": "jws"}),
        ("POST", "/v1/directory/verify", {}, {"address": "a@homingbox.net"}),
        ("GET", "/v1/directory/search", {"q": "billing", "type": "task", "limit": "10"}, None),
        ("GET", "/v1/directory/search", {}, None),
        (
            "POST",
            "/v1/directory/reports",
            {},
            {"address": "a@homingbox.net", "reason": "spam", "message_id": "m1"},
        ),
    ]
    with pytest.raises(ValueError):
        client.directory.verify()


def test_async_agents_and_directory(rec: Recorder) -> None:
    async def run() -> None:
        async with make_async(rec) as mr:
            await mr.agents.get("i1")
            await mr.agents.update("i1", name="Billing")
            await mr.agents.revoke("i1")
            await mr.agents.restore("i1")
            await mr.directory.resolve("a@homingbox.net")
            await mr.directory.verify(signature="jws")
            await mr.directory.search(capability="invoice-lookup")
            await mr.directory.report("a@homingbox.net", "impersonation", details="fake support")
            await mr.identities.create(card={"name": "Research"})
            rec.reply(status=204)
            await mr.agents.delete("i1")

    asyncio.run(run())
    assert [(c[0], c[1]) for c in _calls(rec)] == [
        ("GET", "/v1/inboxes/i1/agent"),
        ("PATCH", "/v1/inboxes/i1/agent"),
        ("POST", "/v1/inboxes/i1/agent/revoke"),
        ("POST", "/v1/inboxes/i1/agent/restore"),
        ("GET", "/v1/directory/resolve"),
        ("POST", "/v1/directory/verify"),
        ("GET", "/v1/directory/search"),
        ("POST", "/v1/directory/reports"),
        ("POST", "/v1/identities"),
        ("DELETE", "/v1/inboxes/i1/agent"),
    ]


# ---------- check_revocation ----------


def _valid() -> dict[str, Any]:
    return next(v for v in FIXTURE["vectors"] if v["expect"] == "valid")


def _opts(v: dict[str, Any]) -> dict[str, Any]:
    return {
        "recipient": v["recipient"],
        "issuer": FIXTURE["issuer"],
        "keys": FIXTURE["keys"],
        "max_age_seconds": None,
    }


def _directory(
    answer: Any, status: int = 200, seen: "list[httpx.Request] | None" = None
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=answer)

    return httpx.MockTransport(handler)


def _code(fn: Any) -> str:
    try:
        fn()
    except AgentMessageVerificationError as err:
        return err.code
    return "valid"


@needs_vectors
def test_check_revocation_active() -> None:
    v = _valid()
    seen: list[httpx.Request] = []
    http = httpx.Client(transport=_directory({"valid": True, "status": "active", "reasons": []}, seen=seen))
    res = verify_agent_message(
        v["message"],
        **_opts(v),
        check_revocation={"api_key": "mr_k", "base_url": "http://api.test/", "http_client": http},
    )
    assert res["from"] == v["claims"]["from"]
    assert str(seen[0].url) == "http://api.test/v1/directory/verify"
    assert seen[0].headers["authorization"] == "Bearer mr_k"
    assert json.loads(seen[0].content) == {"signature": v["message"]["agent"]["signature"]}


@needs_vectors
@pytest.mark.parametrize("status", ["revoked", "suspended", "deleted"])
def test_check_revocation_refuses(status: str) -> None:
    v = _valid()
    http = httpx.Client(
        transport=_directory({"valid": False, "status": status, "reasons": [f"agent_{status}"]})
    )
    check: RevocationCheck = {"api_key": "mr_k", "http_client": http}
    assert (
        _code(lambda check=check: verify_agent_message(v["message"], **_opts(v), check_revocation=check))
        == f"agent_{status}"
    )


@needs_vectors
def test_check_revocation_fails_closed() -> None:
    v = _valid()
    down = httpx.Client(transport=_directory({"error": {"code": "directory_disabled"}}, 503))
    unsure = httpx.Client(transport=_directory({"valid": False, "status": None, "reasons": ["unknown_key"]}))
    for http in (down, unsure):
        check: RevocationCheck = {"api_key": "mr_k", "http_client": http}
        assert (
            _code(lambda check=check: verify_agent_message(v["message"], **_opts(v), check_revocation=check))
            == "revocation_check_failed"
        )


@needs_vectors
def test_async_check_revocation() -> None:
    v = _valid()

    async def run() -> str:
        async with httpx.AsyncClient(transport=_directory({"status": "revoked", "reasons": []})) as http:
            try:
                await averify_agent_message(
                    v["message"], **_opts(v), check_revocation={"api_key": "mr_k", "http_client": http}
                )
            except AgentMessageVerificationError as err:
                return err.code
        return "valid"

    assert asyncio.run(run()) == "agent_revoked"
