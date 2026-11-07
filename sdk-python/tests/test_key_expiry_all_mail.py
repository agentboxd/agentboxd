"""API key expiry (add_agent expires_at, api_key_expired) and messages.list_all (GET /v1/messages)."""

import asyncio

import pytest

from agentboxd import Agentboxd, AuthenticationError

from .conftest import Recorder, make_async


def test_list_all_messages(client: Agentboxd, rec: Recorder) -> None:
    rec.reply(
        {"data": [{"id": "m_1", "inbox_id": "i_1"}, {"id": "m_2", "inbox_id": "i_2"}], "next_cursor": None}
    )
    page = client.messages.list_all(direction="inbound", is_read=False, labels=["ai:needs-human"], limit=50)
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/messages")
    assert rec.last_params() == {
        "direction": "inbound",
        "is_read": "false",
        "labels": "ai:needs-human",
        "limit": "50",
    }
    assert [m["inbox_id"] for m in page["data"]] == ["i_1", "i_2"]

    client.messages.list_all(screening="held", cursor="c_1")
    assert rec.last_params() == {"screening": "held", "cursor": "c_1"}


def test_async_list_all_messages() -> None:
    rec = Recorder()
    rec.default = {"data": [], "next_cursor": None}
    client = make_async(rec)

    async def run() -> None:
        await client.messages.list_all(is_read=False)
        assert rec.last.url.path == "/v1/messages"
        assert rec.last_params() == {"is_read": "false"}
        await client.close()

    asyncio.run(run())


def test_add_agent_with_expiry(client: Agentboxd, rec: Recorder) -> None:
    client.account.add_agent()
    assert rec.last_json() == {}
    rec.reply({"api_key": "mr_x", "api_key_expires_at": "2027-01-01T00:00:00.000Z", "kind": "mailbox"})
    r = client.account.add_agent("mailbox", expires_at="2027-01-01T00:00:00Z")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/signup/agents")
    assert rec.last_json() == {"kind": "mailbox", "expires_at": "2027-01-01T00:00:00Z"}
    assert r["api_key_expires_at"] == "2027-01-01T00:00:00.000Z"


def test_expired_key_is_an_authentication_error(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"error": {"code": "api_key_expired", "message": "this API key expired"}}, status=401)
    with pytest.raises(AuthenticationError) as e:
        client.inboxes.list()
    assert e.value.code == "api_key_expired"
