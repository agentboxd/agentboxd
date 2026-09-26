"""Identity-only agents: ``client.identities`` and ``identity.token(identity_id=...)``."""

import asyncio
import hashlib
import json

import httpx
import pytest

from agentboxd import Agentboxd, AsyncAgentboxd, Identity
from agentboxd._signup import leading_zero_bits

from .conftest import BASE, Recorder, make_async

IDENTITY: Identity = {
    "id": "id1",
    "kind": "identity",
    "address": "sharp-otter-1@agents.test",
    "username": "sharp-otter-1",
    "display_name": "Researcher",
    "client_id": None,
    "metadata": {},
    "identity_enabled": True,
    "status": "active",
    "paused_at": None,
    "paused_reason": None,
    "created_at": "2026-09-26T08:00:00.000Z",
}


def test_identities_crud(client: Agentboxd, rec: Recorder) -> None:
    rec.reply(IDENTITY, status=201)
    out = client.identities.create(display_name="Researcher", client_id="r1", metadata={"team": "research"})
    assert out["kind"] == "identity"
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/identities")
    assert rec.last_json() == {
        "display_name": "Researcher",
        "client_id": "r1",
        "metadata": {"team": "research"},
    }

    rec.reply({"data": [IDENTITY], "next_cursor": None})
    assert client.identities.list(limit=5, metadata={"team": "research"})["data"][0]["id"] == "id1"
    assert rec.last.url.path == "/v1/identities"
    assert rec.last_params() == {"limit": "5", "metadata.team": "research"}

    client.identities.get("id1")
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/identities/id1")
    client.identities.update("id1", display_name=None)
    assert (rec.last.method, rec.last.url.path) == ("PATCH", "/v1/identities/id1")
    assert rec.last_json() == {"display_name": None}
    client.identities.pause("id1", reason="audit")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/inboxes/id1/pause")
    client.identities.resume("id1")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/inboxes/id1/resume")
    rec.reply(status=204)
    client.identities.delete("id1")
    assert (rec.last.method, rec.last.url.path) == ("DELETE", "/v1/identities/id1")


def test_token_for_an_identity(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"id_token": "x", "scope": "openid"}, status=201)
    client.identity.token(identity_id="id1", audience="abxc_1")
    assert str(rec.last.url) == f"{BASE}/v1/inboxes/id1/identity-token"
    assert rec.last_json() == {"audience": "abxc_1"}
    with pytest.raises(TypeError):
        client.identity.token("i1", audience="abxc_1", identity_id="id1")
    with pytest.raises(TypeError):
        client.identity.token(audience="abxc_1")
    with pytest.raises(TypeError):
        client.identity.token(identity_id="id1")


def test_async_identities(rec: Recorder) -> None:
    async def run() -> None:
        async with make_async(rec) as mr:
            rec.reply(IDENTITY, status=201)
            assert (await mr.identities.create(username="sharp-otter-1"))["id"] == "id1"
            assert rec.last_json() == {"username": "sharp-otter-1"}
            await mr.identities.list(cursor="c")
            assert rec.last_params() == {"cursor": "c"}
            await mr.identity.token(identity_id="id1", audience="abxc_1")
            assert rec.last.url.path == "/v1/inboxes/id1/identity-token"

    asyncio.run(run())


def test_signup_kind_identity() -> None:
    def api(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/signup/challenge":
            return httpx.Response(200, json={"challenge": "c", "difficulty": 1})
        body = json.loads(request.content)
        assert body["kind"] == "identity"
        assert leading_zero_bits(hashlib.sha256(f"c:{body['solution']}".encode()).digest()) >= 1
        return httpx.Response(
            201,
            json={
                "api_key": "mr_new",
                "kind": "identity",
                "workspace": {"id": "w1"},
                "identity": IDENTITY,
                "inbox": None,
                "claim": {"status": "not_requested", "email": None},
                "restrictions": {"identities": 1, "identity_tokens": False},
                "docs_url": "",
                "next_steps": [],
            },
        )

    s = Agentboxd.signup(
        base_url=BASE, kind="identity", http_client=httpx.Client(transport=httpx.MockTransport(api))
    )
    assert s.identity is not None and s.identity["id"] == "id1"
    assert s.result["kind"] == "identity"

    async def run() -> None:
        http = httpx.AsyncClient(transport=httpx.MockTransport(api))
        a = await AsyncAgentboxd.signup(base_url=BASE, kind="identity", http_client=http)
        assert a.identity is not None

    asyncio.run(run())
