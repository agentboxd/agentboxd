import asyncio
from typing import get_args

import pytest

from agentboxd import Agentboxd, SuppressionReason, WebhookDeliveryStatus, WebhookEventType

from .conftest import BASE, Recorder, make_async

DELIVERY = {
    "id": "d1",
    "webhook_id": "w1",
    "event_id": "e1",
    "event_type": "message.received",
    "status": "pending",
    "attempts": 3,
    "last_status_code": 500,
    "last_error": "HTTP 500",
    "last_response_ms": 182,
    "next_attempt_at": None,
    "last_attempt_at": "2026-10-05T10:00:00.000Z",
    "redelivered_at": "2026-10-05T10:05:00.000Z",
    "created_at": "2026-10-05T09:00:00.000Z",
}


def test_webhook_deliveries_and_redeliver(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"data": [DELIVERY], "next_cursor": "c2"})
    page = client.webhooks.deliveries("w1", status="failed", limit=10)
    assert page["data"][0]["last_response_ms"] == 182
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/webhooks/w1/deliveries")
    assert rec.last_params() == {"status": "failed", "limit": "10"}

    rec.reply(DELIVERY, status=202)
    out = client.webhooks.redeliver("w1", "d1")
    assert out["id"] == "d1"
    assert (rec.last.method, str(rec.last.url)) == ("POST", f"{BASE}/v1/webhooks/w1/deliveries/d1/redeliver")

    client.webhooks.redeliver("w1", event_id="e1")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/webhooks/w1/redeliver")
    assert rec.last_json() == {"event_id": "e1"}

    with pytest.raises(ValueError):
        client.webhooks.redeliver("w1")
    with pytest.raises(ValueError):
        client.webhooks.redeliver("w1", "d1", event_id="e1")


def test_suppressions(client: Agentboxd, rec: Recorder) -> None:
    row = {
        "address": "gone@example.org",
        "reason": "bounce",
        "created_at": "2026-10-01T00:00:00.000Z",
        "expires_at": None,
    }
    rec.reply({"data": [row], "next_cursor": None})
    page = client.suppressions.list(reason="bounce", q="gone")
    assert page["data"][0]["address"] == "gone@example.org"
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/suppressions")
    assert rec.last_params() == {"reason": "bounce", "q": "gone"}

    rec.reply(row)
    client.suppressions.remove("gone@example.org")
    assert rec.last.method == "DELETE"
    assert str(rec.last.url) == f"{BASE}/v1/suppressions/gone%40example.org"
    assert rec.last_params() == {}
    client.suppressions.remove("gone@example.org", confirm=True)
    assert rec.last_params() == {"confirm": "true"}


def test_async_deliveries_and_suppressions(rec: Recorder) -> None:
    async def run() -> None:
        async with make_async(rec) as mr:
            rec.reply({"data": [DELIVERY], "next_cursor": None})
            await mr.webhooks.deliveries("w1", cursor="c1")
            assert rec.last_params() == {"cursor": "c1"}
            rec.reply(DELIVERY, status=202)
            await mr.webhooks.redeliver("w1", "d1")
            assert rec.last.url.path == "/v1/webhooks/w1/deliveries/d1/redeliver"
            rec.reply({"data": [], "next_cursor": None})
            await mr.suppressions.list()
            assert rec.last.url.path == "/v1/suppressions"
            rec.reply(
                {"address": "a@b.example", "reason": "complaint", "created_at": "x", "expires_at": None}
            )
            await mr.suppressions.remove("a@b.example", confirm=True)
            assert (rec.last.method, rec.last_params()) == ("DELETE", {"confirm": "true"})

    asyncio.run(run())


def test_literals() -> None:
    assert set(get_args(WebhookDeliveryStatus)) == {"pending", "succeeded", "failed"}
    assert set(get_args(SuppressionReason)) == {"bounce", "complaint", "manual"}
    assert "suppression.removed" in get_args(WebhookEventType)
