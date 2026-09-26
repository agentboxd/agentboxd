import base64
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentboxd import (
    DEFAULT_BASE_URL,
    Agentboxd,
    AgentboxdError,
    APIConnectionError,
    AuthenticationError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
    UnprocessableEntityError,
    attachment_from_bytes,
    attachment_from_path,
    iter_all,
)

from .conftest import BASE, KEY, Recorder

# ---------- construction ----------


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in ("AGENTBOXD_API_KEY", "MAILROOM_API_KEY", "AGENTBOXD_BASE_URL", "MAILROOM_URL"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_env_vars(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("AGENTBOXD_API_KEY", "env_key")
    clean_env.setenv("AGENTBOXD_BASE_URL", "http://env.example//")
    with Agentboxd() as mr:
        assert mr.api_key == "env_key"
        assert mr.base_url == "http://env.example"


def test_legacy_env_fallbacks(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("MAILROOM_API_KEY", "old_key")
    clean_env.setenv("MAILROOM_URL", "http://legacy.example/")
    with Agentboxd() as mr:
        assert mr.api_key == "old_key"
        assert mr.base_url == "http://legacy.example"


def test_new_env_names_win_and_blank_falls_through(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("AGENTBOXD_API_KEY", "new_key")
    clean_env.setenv("MAILROOM_API_KEY", "old_key")
    clean_env.setenv("AGENTBOXD_BASE_URL", "  ")
    clean_env.setenv("MAILROOM_URL", "http://legacy.example")
    with Agentboxd() as mr:
        assert mr.api_key == "new_key"
        assert mr.base_url == "http://legacy.example"


def test_default_base_url(clean_env: pytest.MonkeyPatch) -> None:
    with Agentboxd(api_key="k") as mr:
        assert mr.base_url == DEFAULT_BASE_URL == "https://api.agentboxd.com"


def test_pre_rename_aliases() -> None:
    import agentboxd

    assert agentboxd.MailroomError is AgentboxdError  # deprecated alias, same class


def test_missing_api_key(clean_env: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="AGENTBOXD_API_KEY"):
        Agentboxd()


def test_context_manager_does_not_close_user_client(rec: Recorder) -> None:
    http = httpx.Client(transport=httpx.MockTransport(rec))
    with Agentboxd(api_key=KEY, http_client=http):
        pass
    assert not http.is_closed


# ---------- headers ----------


def test_auth_and_json_headers(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"id": "ibx_1"})
    client.inboxes.create(client_id="agent")
    req = rec.last
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert req.headers["content-type"] == "application/json"
    assert req.headers["user-agent"].startswith("agentboxd-python/")
    assert "idempotency-key" not in req.headers


def test_get_has_no_body_or_content_type(client: Agentboxd, rec: Recorder) -> None:
    client.inboxes.get("ibx_1")
    assert rec.last.content == b""
    assert "content-type" not in rec.last.headers


# ---------- inboxes ----------


def test_inboxes(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"id": "ibx_1", "address": "a@x"})
    inbox = client.inboxes.create(username="alice", display_name="Alice", client_id="c1")
    assert inbox["id"] == "ibx_1"
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/inboxes")
    assert rec.last_json() == {"username": "alice", "display_name": "Alice", "client_id": "c1"}

    client.inboxes.create()
    assert rec.last_json() == {}

    rec.reply({"data": [], "next_cursor": None})
    client.inboxes.list(cursor="c", limit=10)
    assert rec.last.method == "GET" and rec.last.url.path == "/v1/inboxes"
    assert rec.last_params() == {"cursor": "c", "limit": "10"}

    client.inboxes.list()
    assert rec.last_params() == {}

    client.inboxes.get("ibx_1")
    assert (rec.last.method, str(rec.last.url)) == ("GET", f"{BASE}/v1/inboxes/ibx_1")

    rec.reply(status=204)
    client.inboxes.delete("ibx_1")
    assert (rec.last.method, rec.last.url.path) == ("DELETE", "/v1/inboxes/ibx_1")


def test_path_segments_are_escaped(client: Agentboxd, rec: Recorder) -> None:
    client.messages.get("../inboxes")
    assert rec.last.url.raw_path == b"/v1/messages/..%2Finboxes"


# ---------- messages ----------


def test_send(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"id": "msg_1", "status": "queued"}, status=202)
    att = attachment_from_bytes("a.txt", b"hi", "text/plain")
    msg = client.messages.send(
        "ibx_1",
        to=["a@x.com", "b@x.com"],
        subject="Hello",
        text="Hi",
        cc="c@x.com",
        attachments=[att],
        labels=("l1",),
        idempotency_key="idem-1",
    )
    assert msg["status"] == "queued"
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/inboxes/ibx_1/messages/send")
    assert rec.last.headers["idempotency-key"] == "idem-1"
    assert rec.last_json() == {
        "to": ["a@x.com", "b@x.com"],
        "cc": "c@x.com",
        "subject": "Hello",
        "text": "Hi",
        "attachments": [{"filename": "a.txt", "content_type": "text/plain", "content_base64": "aGk="}],
        "labels": ["l1"],
    }


def test_send_minimal_body(client: Agentboxd, rec: Recorder) -> None:
    client.messages.send("ibx_1", "a@x.com", "S", html="<p>x</p>")
    assert rec.last_json() == {"to": "a@x.com", "subject": "S", "html": "<p>x</p>"}


def test_reply(client: Agentboxd, rec: Recorder) -> None:
    client.messages.reply("ibx_1", "msg_1", text="Thanks", reply_all=True, idempotency_key="k2")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/inboxes/ibx_1/messages/msg_1/reply")
    assert rec.last.headers["idempotency-key"] == "k2"
    assert rec.last_json() == {"text": "Thanks", "reply_all": True}


def test_list_messages_query(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"data": [], "next_cursor": None})
    client.messages.list(
        "ibx_1", labels=["a", "b"], is_read=False, direction="inbound", cursor="cur", limit=5
    )
    assert rec.last.url.path == "/v1/inboxes/ibx_1/messages"
    assert rec.last_params() == {
        "labels": "a,b",
        "is_read": "false",
        "direction": "inbound",
        "cursor": "cur",
        "limit": "5",
    }


def test_get_and_update_message(client: Agentboxd, rec: Recorder) -> None:
    client.messages.get("msg_1")
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/messages/msg_1")

    client.messages.update("msg_1", add_labels=["x"], remove_labels=["y"], is_read=True)
    assert (rec.last.method, rec.last.url.path) == ("PATCH", "/v1/messages/msg_1")
    assert rec.last_json() == {"add_labels": ["x"], "remove_labels": ["y"], "is_read": True}


def test_wait_maps_from_and_extends_read_timeout(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"data": {"id": "msg_9", "subject": "Welcome"}})
    msg = client.messages.wait(
        "ibx_1",
        timeout=45,
        since="2026-09-24T12:00:00Z",
        from_="Bob@X.com",
        subject="welc",
        direction="inbound",
    )
    assert msg is not None and msg["id"] == "msg_9"
    assert rec.last.url.path == "/v1/inboxes/ibx_1/messages/wait"
    assert rec.last_params() == {
        "timeout": "45",
        "since": "2026-09-24T12:00:00Z",
        "from": "Bob@X.com",
        "subject": "welc",
        "direction": "inbound",
    }
    assert "from_" not in rec.last_params()
    assert rec.last.extensions["timeout"]["read"] == 55


def test_wait_returns_none_on_timeout(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"data": None})
    assert client.messages.wait("ibx_1", timeout=1) is None
    assert rec.last_params() == {"timeout": "1"}


def test_regular_requests_use_client_timeout(client: Agentboxd, rec: Recorder) -> None:
    client.messages.get("m")
    assert rec.last.extensions["timeout"]["read"] == 5.0  # httpx.Client default when http_client given


def test_wait_for_verification(client: Agentboxd, rec: Recorder) -> None:
    result: dict[str, Any] = {
        "code": "482913",
        "link": None,
        "confidence": 0.7,
        "jev_probability": None,
        "message_id": "msg_2",
        "from": "no-reply@site.com",
        "subject": "Your code",
        "received_at": "2026-09-24T12:00:01Z",
    }
    rec.reply({"data": result})
    got = client.messages.wait_for_verification("ibx_1", since="2026-09-24T12:00:00Z", from_="site.com")
    assert got == result
    assert rec.last.url.path == "/v1/inboxes/ibx_1/verification"
    assert rec.last_params() == {"timeout": "30", "since": "2026-09-24T12:00:00Z", "from": "site.com"}
    assert rec.last.extensions["timeout"]["read"] == 40

    rec.reply({"data": None})
    assert client.messages.wait_for_verification("ibx_1", timeout=2) is None


# ---------- threads, search ----------


def test_threads_and_search(client: Agentboxd, rec: Recorder) -> None:
    client.threads.list("ibx_1", limit=3)
    assert rec.last.url.path == "/v1/inboxes/ibx_1/threads"
    assert rec.last_params() == {"limit": "3"}

    client.threads.get("thr_1")
    assert rec.last.url.path == "/v1/threads/thr_1"

    client.search('"exact phrase" -spam', inbox_id="ibx_1", limit=20)
    assert rec.last.url.path == "/v1/search"
    assert rec.last_params() == {"q": '"exact phrase" -spam', "inbox_id": "ibx_1", "limit": "20"}


# ---------- webhooks ----------


def test_webhooks(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"id": "wh_1", "secret": "whsec_x"})
    wh = client.webhooks.create("https://h.example/x", events=["message.received"], secret="whsec_x")
    assert wh.get("secret") == "whsec_x"
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/webhooks")
    assert rec.last_json() == {
        "url": "https://h.example/x",
        "events": ["message.received"],
        "secret": "whsec_x",
    }

    client.webhooks.create("https://h.example/x", inbox_ids=["ibx_1"])
    assert rec.last_json() == {"url": "https://h.example/x", "inbox_ids": ["ibx_1"]}

    client.webhooks.list()
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/webhooks")

    client.webhooks.get("wh_1")
    assert rec.last.url.path == "/v1/webhooks/wh_1"

    client.webhooks.update("wh_1", enabled=False)
    assert (rec.last.method, rec.last.url.path) == ("PATCH", "/v1/webhooks/wh_1")
    assert rec.last_json() == {"enabled": False}

    client.webhooks.update("wh_1", inbox_ids=None)
    assert rec.last_json() == {"inbox_ids": None}

    rec.reply({"event_id": "evt_1", "delivery_id": "dlv_1"})
    assert client.webhooks.test("wh_1") == {"event_id": "evt_1", "delivery_id": "dlv_1"}
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/webhooks/wh_1/test")
    assert rec.last.content == b""

    rec.reply(status=204)
    client.webhooks.delete("wh_1")
    assert rec.last.method == "DELETE"


# ---------- errors ----------


@pytest.mark.parametrize(
    ("status", "cls"),
    [
        (401, AuthenticationError),
        (404, NotFoundError),
        (422, UnprocessableEntityError),
        (429, RateLimitError),
        (503, InternalServerError),
        (409, AgentboxdError),
    ],
)
def test_error_mapping(client: Agentboxd, rec: Recorder, status: int, cls: type) -> None:
    rec.reply({"error": {"code": "some_code", "message": "Something broke"}}, status=status)
    with pytest.raises(AgentboxdError) as info:
        client.inboxes.get("ibx_1")
    err = info.value
    assert type(err) is cls
    assert (err.status, err.code, err.message) == (status, "some_code", "Something broke")


def test_error_without_json_body(client: Agentboxd, rec: Recorder) -> None:
    rec.queue.append(httpx.Response(502, content=b"<html>bad gateway</html>"))
    with pytest.raises(InternalServerError) as info:
        client.inboxes.get("x")
    assert info.value.status == 502
    assert info.value.code == "http_error"
    assert info.value.message == "Bad Gateway"


def test_connection_error(rec: Recorder) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    http = httpx.Client(transport=httpx.MockTransport(boom))
    mr = Agentboxd(api_key=KEY, base_url=BASE, http_client=http)
    with pytest.raises(APIConnectionError) as info:
        mr.inboxes.list()
    assert info.value.status == 0


# ---------- pagination ----------


def test_iter_all_follows_cursor(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"data": [{"id": "m1"}, {"id": "m2"}], "next_cursor": "c2"})
    rec.reply({"data": [{"id": "m3"}], "next_cursor": "c3"})
    rec.reply({"data": [], "next_cursor": None})
    ids = [m["id"] for m in iter_all(client.messages.list, "ibx_1", is_read=False, limit=2)]
    assert ids == ["m1", "m2", "m3"]
    cursors: list[Any] = [dict(r.url.params).get("cursor") for r in rec.requests]
    assert cursors == [None, "c2", "c3"]
    assert all(dict(r.url.params)["is_read"] == "false" for r in rec.requests)


def test_iter_all_is_lazy(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"data": [{"id": "i1"}], "next_cursor": "more"})
    it = iter_all(client.inboxes.list)
    assert next(it)["id"] == "i1"
    assert len(rec.requests) == 1


# ---------- attachments ----------


def test_attachment_from_path(tmp_path: Path) -> None:
    p = tmp_path / "report.pdf"
    p.write_bytes(b"%PDF-1.4 data")
    att = attachment_from_path(p)
    assert att["filename"] == "report.pdf"
    assert att["content_type"] == "application/pdf"
    assert base64.b64decode(att["content_base64"]) == b"%PDF-1.4 data"

    assert attachment_from_path(str(p), "application/x-custom")["content_type"] == "application/x-custom"


def test_attachment_from_bytes_default_type() -> None:
    assert attachment_from_bytes("blob.unknownext", b"\x00")["content_type"] == "application/octet-stream"
