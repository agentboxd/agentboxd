"""Drafts (human in the loop), scheduled send and the burst-limit 429."""

import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from agentboxd import Agentboxd, Draft, DraftReply, DraftSendResult, NotFoundError, RateLimitError

from .conftest import Recorder, make_async

BASE_PATH = "/v1/inboxes/ibx_1/drafts"


def test_create_draft(client: Agentboxd, rec: Recorder) -> None:
    client.drafts.create(
        "ibx_1",
        to=["Dana <dana@example.com>"],
        subject="Quote",
        text="Hi",
        labels=["needs-review"],
        metadata={"ticket": "T-1"},
        idempotency_key="k-1",
    )
    assert (rec.last.method, rec.last.url.path) == ("POST", BASE_PATH)
    assert rec.last.headers["Idempotency-Key"] == "k-1"
    assert rec.last_json() == {
        "to": ["Dana <dana@example.com>"],
        "subject": "Quote",
        "text": "Hi",
        "labels": ["needs-review"],
        "metadata": {"ticket": "T-1"},
    }

    client.drafts.create("ibx_1")
    assert rec.last_json() == {}


def test_create_scheduled_reply_converts_datetimes(client: Agentboxd, rec: Recorder) -> None:
    at = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    client.drafts.create("ibx_1", reply_to_message_id="msg_1", reply_all=True, text="Thanks", send_at=at)
    assert rec.last_json() == {
        "reply_to_message_id": "msg_1",
        "reply_all": True,
        "text": "Thanks",
        "send_at": "2026-10-01T09:00:00Z",
    }
    client.drafts.create("ibx_1", thread_id="thr_1", send_at=datetime(2026, 10, 1, 9, 30))
    assert rec.last_json() == {"thread_id": "thr_1", "send_at": "2026-10-01T09:30:00Z"}


def test_list_and_list_all(client: Agentboxd, rec: Recorder) -> None:
    rec.default = {"data": [], "next_cursor": None}
    client.drafts.list("ibx_1", status=["draft", "scheduled"], thread_id="thr_1", limit=5)
    assert rec.last.url.path == BASE_PATH
    assert rec.last_params() == {"status": "draft,scheduled", "thread_id": "thr_1", "limit": "5"}

    client.drafts.list_all(inbox_id="ibx_1", status="failed", cursor="c")
    assert rec.last.url.path == "/v1/drafts"
    assert rec.last_params() == {"inbox_id": "ibx_1", "status": "failed", "cursor": "c"}


def test_get_update_delete(client: Agentboxd, rec: Recorder) -> None:
    client.drafts.get("ibx_1", "drf_1")
    assert (rec.last.method, rec.last.url.path) == ("GET", f"{BASE_PATH}/drf_1")

    client.drafts.update("ibx_1", "drf_1", text="New", subject=None, attachments=[{"id": "att_1"}])
    assert rec.last.method == "PATCH"
    assert rec.last_json() == {"text": "New", "subject": None, "attachments": [{"id": "att_1"}]}

    client.drafts.update("ibx_1", "drf_1", send_at=None)
    assert rec.last_json() == {"send_at": None}

    client.drafts.update("ibx_1", "drf_1", send_at="2026-10-02T08:00:00Z", labels=["ok"])
    assert rec.last_json() == {"send_at": "2026-10-02T08:00:00Z", "labels": ["ok"]}

    rec.reply(status=204)
    client.drafts.delete("ibx_1", "drf_1")
    assert (rec.last.method, rec.last.url.path) == ("DELETE", f"{BASE_PATH}/drf_1")


def test_send_schedule_cancel(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"draft": {"id": "drf_1", "status": "sent"}, "message": {"id": "msg_out"}}, status=202)
    result: DraftSendResult = client.drafts.send("ibx_1", "drf_1", idempotency_key="send-1")
    assert result["message"]["id"] == "msg_out"
    assert (rec.last.method, rec.last.url.path) == ("POST", f"{BASE_PATH}/drf_1/send")
    assert rec.last.headers["Idempotency-Key"] == "send-1"
    assert not rec.last.content

    client.drafts.schedule("ibx_1", "drf_1", datetime(2026, 10, 3, 7, 15, tzinfo=timezone.utc))
    assert rec.last.url.path == f"{BASE_PATH}/drf_1/schedule"
    assert rec.last_json() == {"send_at": "2026-10-03T07:15:00Z"}

    rec.reply({"id": "drf_1", "status": "cancelled"})
    d: Draft = client.drafts.cancel("ibx_1", "drf_1")
    assert d["status"] == "cancelled"
    assert rec.last.url.path == f"{BASE_PATH}/drf_1/cancel"


def test_draft_reply_save(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"text": "Hi", "citations": [], "model": "m", "draft": {"id": "drf_9", "source": "ai"}})
    reply: DraftReply = client.messages.draft_reply("msg_1", save=True)
    assert rec.last_json() == {"save": True}
    assert reply["draft"]["id"] == "drf_9"

    client.messages.draft_reply("msg_1", "be brief")
    assert rec.last_json() == {"instructions": "be brief"}


def test_burst_limit_error_carries_retry_after(client: Agentboxd, rec: Recorder) -> None:
    details = {"limit": "sends_per_5min", "max": 20, "window_seconds": 300, "retry_after_seconds": 42}
    rec.queue.append(
        httpx.Response(
            429,
            json={"error": {"code": "rate_limited", "message": "slow down", "details": details}},
            headers={"Retry-After": "41"},
        )
    )
    with pytest.raises(RateLimitError) as exc:
        client.drafts.send("ibx_1", "drf_1")
    assert exc.value.code == "rate_limited"
    assert exc.value.details == details
    assert exc.value.retry_after == 41.0

    rec.reply(
        {"error": {"code": "rate_limited", "message": "x", "details": {"retry_after_seconds": 7}}}, status=429
    )
    with pytest.raises(RateLimitError) as exc2:
        client.messages.send("ibx_1", to="a@b.com", subject="s", text="t")
    assert exc2.value.retry_after == 7.0

    rec.reply({"error": {"code": "not_found", "message": "x"}}, status=404)
    with pytest.raises(NotFoundError) as exc3:
        client.drafts.get("ibx_1", "nope")
    assert exc3.value.retry_after is None


def test_async_drafts(rec: Recorder) -> None:
    async def main() -> None:
        mr = make_async(rec)
        await mr.drafts.create("ibx_1", to="a@b.com", send_at="2026-10-01T09:00:00Z")
        assert rec.last_json() == {"to": "a@b.com", "send_at": "2026-10-01T09:00:00Z"}
        rec.default = {"data": [], "next_cursor": None}
        await mr.drafts.list("ibx_1", status="draft")
        assert rec.last_params() == {"status": "draft"}
        await mr.drafts.list_all()
        assert rec.last.url.path == "/v1/drafts"
        await mr.drafts.get("ibx_1", "drf_1")
        await mr.drafts.update("ibx_1", "drf_1", html=None)
        assert rec.last_json() == {"html": None}
        await mr.drafts.send("ibx_1", "drf_1")
        await mr.drafts.schedule("ibx_1", "drf_1", "2026-10-01T10:00:00Z")
        await mr.drafts.cancel("ibx_1", "drf_1")
        rec.reply(status=204)
        await mr.drafts.delete("ibx_1", "drf_1")
        await mr.messages.draft_reply("msg_1", save=True)
        assert rec.last_json() == {"save": True}
        await mr.close()

    asyncio.run(main())
