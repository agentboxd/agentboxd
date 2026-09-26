"""Dashboard v2: allow/block lists, metrics, envelope webhooks and the event catalog."""

import asyncio

from agentboxd import Agentboxd, ListEntry, Metrics, UnprocessableEntityError, Webhook

from .conftest import Recorder, make_async


def test_lists_requests(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"data": []})
    assert client.lists.list(inbox_id="in_1", direction="receive", kind="block") == {"data": []}
    assert rec.last.method == "GET"
    assert rec.last.url.path == "/v1/lists"
    assert rec.last_params() == {"inbox_id": "in_1", "direction": "receive", "kind": "block"}

    client.lists.list()
    assert rec.last_params() == {}

    entry: ListEntry = {
        "id": "l_1",
        "inbox_id": None,
        "direction": "send",
        "kind": "block",
        "pattern": "spam.example",
        "type": "domain",
        "created_at": "2026-09-25T00:00:00.000Z",
    }
    rec.reply(entry, status=201)
    assert client.lists.create("send", "block", "@spam.example") == entry
    assert rec.last.method == "POST"
    assert rec.last_json() == {"direction": "send", "kind": "block", "pattern": "@spam.example"}

    client.lists.create("receive", "allow", "boss@b.com", inbox_id="in_1")
    assert rec.last_json() == {
        "direction": "receive",
        "kind": "allow",
        "pattern": "boss@b.com",
        "inbox_id": "in_1",
    }

    rec.reply(status=204)
    client.lists.delete("l/1")
    assert rec.last.method == "DELETE"
    assert rec.last.url.raw_path == b"/v1/lists/l%2F1"


def test_metrics_request(client: Agentboxd, rec: Recorder) -> None:
    client.metrics(from_="2026-09-01", to="2026-09-25", tz="Europe/Paris", inbox_id="in_1", bucket="hour")
    assert rec.last.url.path == "/v1/metrics"
    assert rec.last_params() == {
        "from": "2026-09-01",
        "to": "2026-09-25",
        "tz": "Europe/Paris",
        "inbox_id": "in_1",
        "bucket": "hour",
    }
    client.metrics()
    assert rec.last_params() == {}


def test_metrics_typed_response(client: Agentboxd, rec: Recorder) -> None:
    counts = {"sent": 1, "received": 2, "delivered": 0, "bounced": 0, "complained": 0, "blocked": 1}
    body: Metrics = {
        "from": "2026-08-26T00:00:00.000Z",
        "to": "2026-09-25T00:00:00.000Z",
        "tz": "UTC",
        "bucket": "day",
        "inbox_id": None,
        "series": [{"t": "2026-09-24T00:00:00.000Z", **counts}],  # type: ignore[typeddict-item]
        "totals": counts,  # type: ignore[typeddict-item]
        "deliverability": {"delivered_rate": 0, "bounce_rate": 0, "complaint_rate": 0, "bounce_reasons": []},
        "inbound": {"spam": 0, "blocked": 1, "unauthenticated": 0},
        "heatmap": [{"date": "2026-09-24", "sent": 1, "received": 2}],
        "streak": {"longest_days": 1, "busiest_day": {"date": "2026-09-24", "count": 3}},
        "resources": {"inboxes": 1, "domains": 1, "threads": 3, "messages": 4, "storage_bytes": 1234},
        "queue": [],
    }
    rec.reply(body)
    m = client.metrics(tz="UTC")
    assert m["totals"]["blocked"] == 1
    assert m["streak"]["busiest_day"] == {"date": "2026-09-24", "count": 3}


def test_webhook_payload_and_catalog(client: Agentboxd, rec: Recorder) -> None:
    client.webhooks.create(
        "https://example.com/hook", events=["message.received.blocked"], payload="envelope"
    )
    assert rec.last_json() == {
        "url": "https://example.com/hook",
        "events": ["message.received.blocked"],
        "payload": "envelope",
    }
    # Unchanged when not given (backward compatible).
    client.webhooks.create("https://example.com/hook")
    assert rec.last_json() == {"url": "https://example.com/hook"}

    client.webhooks.update("w_1", payload="full")
    assert rec.last_json() == {"payload": "full"}

    hook: Webhook = {
        "id": "w_1",
        "url": "https://example.com/hook",
        "events": ["message.received"],
        "inbox_ids": None,
        "enabled": True,
        "created_at": "2026-09-25T00:00:00.000Z",
        "payload": "envelope",
        "stats": {
            "deliveries_24h": 4,
            "failed_24h": 1,
            "error_rate_24h": 0.25,
            "last_success_at": "2026-09-25T00:00:00.000Z",
            "last_failure_at": None,
        },
    }
    rec.reply(hook)
    assert client.webhooks.get("w_1")["stats"]["error_rate_24h"] == 0.25

    rec.reply({"data": [{"type": "webhook.test", "description": "d", "example": {}, "envelope_example": {}}]})
    events = client.webhooks.events()
    assert rec.last.url.path == "/v1/webhooks/events"
    assert [e["type"] for e in events] == ["webhook.test"]


def test_messages_include_blocked(client: Agentboxd, rec: Recorder) -> None:
    client.messages.list("in_1", include_blocked=True)
    assert rec.last_params() == {"include_blocked": "true"}
    client.messages.list("in_1")
    assert rec.last_params() == {}


def test_recipient_blocked_is_422(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"error": {"code": "recipient_blocked", "message": "refused by the send lists"}}, status=422)
    try:
        client.messages.send("in_1", to="nope@example.com", subject="x", text="x")
    except UnprocessableEntityError as err:
        assert err.code == "recipient_blocked"
    else:  # pragma: no cover
        raise AssertionError("expected UnprocessableEntityError")


def test_async_lists_and_metrics() -> None:
    rec = Recorder()

    async def run() -> None:
        async with make_async(rec) as mr:
            await mr.lists.create("reply", "block", "noreply.example")
            assert rec.last_json() == {"direction": "reply", "kind": "block", "pattern": "noreply.example"}
            await mr.lists.list(kind="allow")
            assert rec.last_params() == {"kind": "allow"}
            rec.reply(status=204)
            await mr.lists.delete("l_1")
            await mr.metrics(tz="Asia/Tokyo")
            assert rec.last_params() == {"tz": "Asia/Tokyo"}
            await mr.webhooks.create("https://example.com/h", payload="envelope")
            assert rec.last_json() == {"url": "https://example.com/h", "payload": "envelope"}
            rec.reply({"data": []})
            assert await mr.webhooks.events() == []

    asyncio.run(run())
