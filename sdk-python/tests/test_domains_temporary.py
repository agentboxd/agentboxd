"""Custom domains and temporary inboxes."""

import asyncio
import inspect

import pytest

from agentboxd import Agentboxd, AsyncAgentboxd, Domain, Inbox, PermissionDeniedError

from .conftest import Recorder, make_async

DOMAIN: Domain = {
    "id": "d_1",
    "domain": "mail.acme.com",
    "status": "pending",
    "receiving": True,
    "records": [
        {
            "key": "verification",
            "type": "TXT",
            "name": "_agentboxd.mail.acme.com",
            "value": "agentboxd-verify=abc",
            "required": True,
            "status": "missing",
        },
        {
            "key": "mx",
            "type": "MX",
            "name": "mail.acme.com",
            "value": "10 mx.agentboxd.com",
            "required": True,
            "status": "mismatch",
            "found": ["10 aspmx.l.google.com"],
        },
    ],
    "verified_at": None,
    "last_checked_at": None,
    "created_at": "2026-01-01T00:00:00.000Z",
}


def test_domains_requests(client: Agentboxd, rec: Recorder) -> None:
    rec.reply(DOMAIN, status=201)
    d = client.domains.create("mail.acme.com")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/domains")
    assert rec.last_json() == {"domain": "mail.acme.com"}
    assert d["records"][1]["found"] == ["10 aspmx.l.google.com"]

    client.domains.create("mail.acme.com", receiving=False)
    assert rec.last_json() == {"domain": "mail.acme.com", "receiving": False}

    client.domains.list()
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/domains")

    client.domains.get("d_1")
    assert rec.last.url.path == "/v1/domains/d_1"

    client.domains.verify("d_1")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/domains/d_1/verify")

    client.domains.update("d_1", receiving=False)
    assert (rec.last.method, rec.last_json()) == ("PATCH", {"receiving": False})

    rec.reply(status=204)
    client.domains.delete("d_1")
    assert rec.last.method == "DELETE"
    assert rec.last_params() == {}

    rec.reply(status=204)
    client.domains.delete("d_1", force=True)
    assert rec.last_params() == {"force": "true"}


def test_inbox_on_custom_domain(client: Agentboxd, rec: Recorder) -> None:
    client.inboxes.create(username="postmaster", domain="mail.acme.com")
    assert rec.last_json() == {"username": "postmaster", "domain": "mail.acme.com"}


def test_temporary_inboxes(client: Agentboxd, rec: Recorder) -> None:
    tmp: Inbox = {
        "id": "i_1",
        "address": "k3j9x0a8b7c6@tmp.agentboxd.com",
        "username": "k3j9x0a8b7c6",
        "display_name": None,
        "client_id": None,
        "daily_send_limit": 0,
        "temporary": True,
        "expires_at": "2026-01-01T00:15:00.000Z",
        "created_at": "2026-01-01T00:00:00.000Z",
    }
    rec.reply(tmp, status=201)
    got = client.inboxes.create_temporary()
    assert rec.last_json() == {"ttl_seconds": 900}
    assert got["temporary"] is True

    client.inboxes.create_temporary(ttl_seconds=120, display_name="Sign-up")
    assert rec.last_json() == {"ttl_seconds": 120, "display_name": "Sign-up"}

    client.inboxes.list(temporary=True)
    assert rec.last_params() == {"temporary": "true"}
    client.inboxes.list(include_temporary=True, limit=5)
    assert rec.last_params() == {"include_temporary": "true", "limit": "5"}
    client.inboxes.list()
    assert rec.last_params() == {}

    client.inboxes.update("i_1", ttl_seconds=3600)
    assert (rec.last.method, rec.last_json()) == ("PATCH", {"ttl_seconds": 3600})


def test_receive_only_error(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"error": {"code": "temporary_inbox_receive_only", "message": "receive-only"}}, status=403)
    with pytest.raises(PermissionDeniedError) as exc:
        client.messages.send("i_1", to="a@example.com", subject="x", text="x")
    assert exc.value.code == "temporary_inbox_receive_only"


def test_async_domains_and_temporary(rec: Recorder) -> None:
    async def go() -> None:
        async with make_async(rec) as client:
            await client.inboxes.create_temporary(ttl_seconds=300)
            assert rec.last_json() == {"ttl_seconds": 300}
            await client.domains.verify("d_1")
            assert rec.last.url.path == "/v1/domains/d_1/verify"
            rec.reply(status=204)
            await client.domains.delete("d_1", force=True)
            assert rec.last_params() == {"force": "true"}

    asyncio.run(go())


def test_async_domains_surface_matches_sync() -> None:
    sync = Agentboxd(api_key="k")
    async_ = AsyncAgentboxd(api_key="k")
    names = {m for m in dir(sync.domains) if not m.startswith("_")}
    assert names == {m for m in dir(async_.domains) if not m.startswith("_")}
    for name in names:
        assert list(inspect.signature(getattr(sync.domains, name)).parameters) == list(
            inspect.signature(getattr(async_.domains, name)).parameters
        )
    assert "create_temporary" in dir(async_.inboxes)
    sync.close()
    asyncio.run(async_.close())
