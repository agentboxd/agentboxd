import asyncio
from typing import get_args

from agentboxd import Agentboxd, IdentityClientType, WebhookEventType

from .conftest import BASE, Recorder, make_async

TOKEN = {
    "id_token": "eyJ.x.y",
    "token_type": "id_token",
    "issuer": "https://id.agentboxd.com",
    "audience": "abxc_1",
    "sub": "s",
    "jti": "j",
    "scope": "openid email",
    "expires_in": 300,
    "expires_at": "2026-09-25T10:00:00.000Z",
}


def test_token_sends_audience_and_optional_fields(client: Agentboxd, rec: Recorder) -> None:
    rec.reply(TOKEN, status=201)
    out = client.identity.token("inb 1", audience="abxc_1")
    assert out["id_token"] == "eyJ.x.y"
    assert rec.last.method == "POST"
    assert str(rec.last.url) == f"{BASE}/v1/inboxes/inb%201/identity-token"
    assert rec.last_json() == {"audience": "abxc_1"}

    client.identity.token(
        "i1", audience="abxc_1", nonce="n", scope=["openid", "email", "profile"], expires_in=60
    )
    assert rec.last_json() == {
        "audience": "abxc_1",
        "nonce": "n",
        "scope": "openid email profile",
        "expires_in": 60,
    }
    client.identity.token("i1", audience="abxc_1", scope="openid")
    assert rec.last_json()["scope"] == "openid"


def test_clients_crud(client: Agentboxd, rec: Recorder) -> None:
    client.identity.clients.create(
        "Acme CRM",
        "confidential",
        redirect_uris=("https://app.example.com/cb",),
        allowed_scopes=["openid", "email"],
    )
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/identity/clients")
    assert rec.last_json() == {
        "name": "Acme CRM",
        "type": "confidential",
        "redirect_uris": ["https://app.example.com/cb"],
        "allowed_scopes": ["openid", "email"],
    }
    client.identity.clients.create("Headless", "verify_only", subject_type="public")
    assert rec.last_json() == {"name": "Headless", "type": "verify_only", "subject_type": "public"}

    rec.reply({"data": [], "next_cursor": None})
    assert client.identity.clients.list()["data"] == []
    assert rec.last.url.path == "/v1/identity/clients"

    client.identity.clients.get("c1")
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/identity/clients/c1")

    client.identity.clients.update("c1", enabled=False, homepage_url=None)
    assert (rec.last.method, rec.last.url.path) == ("PATCH", "/v1/identity/clients/c1")
    assert rec.last_json() == {"enabled": False, "homepage_url": None}
    client.identity.clients.update("c1", name="New")
    assert rec.last_json() == {"name": "New"}

    client.identity.clients.rotate_secret("c1")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/identity/clients/c1/secret")

    rec.reply(status=204)
    client.identity.clients.delete("c1")
    assert (rec.last.method, rec.last.url.path) == ("DELETE", "/v1/identity/clients/c1")


def test_inbox_identity(client: Agentboxd, rec: Recorder) -> None:
    client.identity.inbox.get("i1")
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/inboxes/i1/identity")
    client.identity.inbox.update("i1", enabled=False)
    assert (rec.last.method, rec.last.url.path) == ("PATCH", "/v1/inboxes/i1/identity")
    assert rec.last_json() == {"enabled": False}
    client.identity.inbox.sign_ins("i1", limit=5)
    assert rec.last.url.path == "/v1/inboxes/i1/identity/sign-ins"
    assert rec.last_params() == {"limit": "5"}


def test_async_identity(rec: Recorder) -> None:
    async def run() -> None:
        async with make_async(rec) as mr:
            rec.reply(TOKEN, status=201)
            out = await mr.identity.token("i1", audience="abxc_1", nonce="n")
            assert out["jti"] == "j"
            assert rec.last_json() == {"audience": "abxc_1", "nonce": "n"}
            await mr.identity.clients.rotate_secret("c1")
            assert rec.last.url.path == "/v1/identity/clients/c1/secret"
            await mr.identity.inbox.sign_ins("i1", cursor="abc")
            assert rec.last_params() == {"cursor": "abc"}

    asyncio.run(run())


def test_identity_literals() -> None:
    assert set(get_args(IdentityClientType)) == {"confidential", "public", "verify_only"}
    assert {"identity.token_issued", "identity.signed_in"} <= set(get_args(WebhookEventType))
