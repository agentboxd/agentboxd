"""Claim/ack lease queue: claim, ack, nack, extend and the consume() loop (sync and async)."""

import asyncio
import json
import threading
from typing import Any

import httpx
import pytest

from agentboxd import Agentboxd, ConsumeContext, Message, NotFoundError, consume_retry_delay

from .conftest import Recorder, make_async


def _lease(mid: str, delivery: int = 1) -> dict[str, Any]:
    return {
        "lease_id": f"lease-{mid}-{delivery}",
        "lease_until": "2026-09-25T12:05:00.000Z",
        "delivery_count": delivery,
        "message": {"id": mid, "subject": f"subject {mid}"},
    }


def test_claim_ack_nack_extend(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"data": [_lease("m_1")], "paused": False})
    claimed = client.messages.claim(
        "i_1",
        limit=5,
        lease_seconds=60,
        consumer="worker-1",
        wait=10,
        enriched=True,
        since="2026-09-01T00:00:00Z",
    )
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/inboxes/i_1/messages/claim")
    assert rec.last_json() == {
        "limit": 5,
        "lease_seconds": 60,
        "consumer": "worker-1",
        "wait": 10,
        "enriched": True,
        "since": "2026-09-01T00:00:00Z",
    }
    lease = claimed["data"][0]
    assert lease["delivery_count"] == 1

    client.messages.claim("i_1")
    assert rec.last_json() == {}

    rec.reply({"id": "m_1", "acked_at": "2026-09-25T12:01:00.000Z"})
    assert client.messages.ack("m_1", lease["lease_id"], mark_read=True)["acked_at"]
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/messages/m_1/ack")
    assert rec.last_json() == {"lease_id": lease["lease_id"], "mark_read": True}

    client.messages.nack("m_1", "l", delay_seconds=30)
    assert (rec.last.url.path, rec.last_json()) == (
        "/v1/messages/m_1/nack",
        {"lease_id": "l", "delay_seconds": 30},
    )
    client.messages.extend("m_1", "l", lease_seconds=600)
    assert (rec.last.url.path, rec.last_json()) == (
        "/v1/messages/m_1/extend",
        {"lease_id": "l", "lease_seconds": 600},
    )
    client.messages.extend("m_1", "l")
    assert rec.last_json() == {"lease_id": "l"}


def test_retry_delay() -> None:
    assert [consume_retry_delay(n) for n in (1, 2, 3, 4)] == [5, 10, 20, 40]
    assert consume_retry_delay(10) == 300
    assert consume_retry_delay(3, base=1, cap=2) == 2


def _router(leases: list[dict[str, Any]], calls: list[tuple[str, Any]]) -> Any:
    """Answers claim with `leases` once (then nothing), and records ack/nack/extend bodies."""
    pending = list(leases)

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        path = request.url.path
        calls.append((path, body))
        if path.endswith("/messages/claim"):
            data = [pending.pop(0)] if pending else []
            return httpx.Response(200, json={"data": data, "paused": False})
        if path.endswith("/ack"):
            return httpx.Response(200, json={"id": path.split("/")[3], "acked_at": "t"})
        return httpx.Response(200, json={"id": path.split("/")[3]})

    return handle


def test_consume_acks_on_success_and_nacks_with_backoff_on_error() -> None:
    calls: list[tuple[str, Any]] = []
    rec = Recorder()
    rec.default = None
    leases = [_lease("m_ok"), _lease("m_fail", delivery=3)]
    handler_router = _router(leases, calls)
    http = httpx.Client(transport=httpx.MockTransport(handler_router))
    client = Agentboxd(api_key="k", base_url="http://agentboxd.test", http_client=http)
    stop = threading.Event()
    seen: list[str] = []
    errors: list[BaseException] = []

    def handler(message: Message) -> None:
        seen.append(message["id"])
        if message["id"] == "m_fail":
            raise RuntimeError("boom")
        if len(seen) >= 2:
            stop.set()

    def on_error(err: BaseException, lease: Any) -> None:
        errors.append(err)
        if len(seen) >= 2:
            stop.set()

    client.inboxes.consume("i_1", handler, wait=0, stop=stop, on_error=on_error)
    assert sorted(seen) == ["m_fail", "m_ok"]
    assert ("/v1/messages/m_ok/ack", {"lease_id": "lease-m_ok-1"}) in calls
    # Third delivery failed: 5 s x 2^2.
    assert ("/v1/messages/m_fail/nack", {"lease_id": "lease-m_fail-3", "delay_seconds": 20}) in calls
    assert any(isinstance(e, RuntimeError) for e in errors)
    claim_bodies = [b for p, b in calls if p.endswith("/claim")]
    assert claim_bodies[0] == {"limit": 1, "lease_seconds": 300, "wait": 0}


def test_consume_passes_context_and_stops_on_fatal_errors() -> None:
    calls: list[tuple[str, Any]] = []
    http = httpx.Client(transport=httpx.MockTransport(_router([_lease("m_1")], calls)))
    client = Agentboxd(api_key="k", base_url="http://agentboxd.test", http_client=http)
    stop = threading.Event()
    got: list[ConsumeContext] = []

    def handler(message: Message, ctx: ConsumeContext) -> None:
        got.append(ctx)
        ctx.extend(lease_seconds=120)
        stop.set()

    client.inboxes.consume("i_1", handler, wait=0, stop=stop, concurrency=2)
    assert got[0].lease_id == "lease-m_1-1" and got[0].delivery_count == 1
    assert ("/v1/messages/m_1/extend", {"lease_id": "lease-m_1-1", "lease_seconds": 120}) in calls
    assert ("/v1/messages/m_1/ack", {"lease_id": "lease-m_1-1"}) in calls

    missing = Recorder()
    missing.reply({"error": {"code": "not_found", "message": "inbox not found"}}, status=404)
    bad = Agentboxd(
        api_key="k",
        base_url="http://agentboxd.test",
        http_client=httpx.Client(transport=httpx.MockTransport(missing)),
    )
    with pytest.raises(NotFoundError):
        bad.inboxes.consume("nope", lambda m: None, wait=0)


def test_consume_waits_while_paused() -> None:
    rec = Recorder()
    rec.reply({"data": [], "paused": True})
    client = Agentboxd(
        api_key="k",
        base_url="http://agentboxd.test",
        http_client=httpx.Client(transport=httpx.MockTransport(rec)),
    )
    stop = threading.Event()
    timer = threading.Timer(0.2, stop.set)
    timer.start()
    client.inboxes.consume("i_1", lambda m: None, wait=0, stop=stop, paused_poll_seconds=5)
    timer.cancel()
    assert len(rec.requests) == 1  # slept on the paused answer until stopped, no busy loop


def test_async_claim_and_consume() -> None:
    calls: list[tuple[str, Any]] = []
    rec = Recorder()

    async def run() -> None:
        client = make_async(rec)
        rec.reply({"data": [_lease("m_1")], "paused": False})
        res = await client.messages.claim("i_1", limit=1)
        assert rec.last_json() == {"limit": 1}
        assert res["data"][0]["lease_id"] == "lease-m_1-1"
        await client.messages.ack("m_1", "l")
        assert rec.last.url.path == "/v1/messages/m_1/ack"
        await client.messages.nack("m_1", "l")
        await client.messages.extend("m_1", "l", lease_seconds=30)
        assert rec.last_json() == {"lease_id": "l", "lease_seconds": 30}
        await client.close()

        http = httpx.AsyncClient(transport=httpx.MockTransport(_router([_lease("a"), _lease("b")], calls)))
        from agentboxd import AsyncAgentboxd

        consumer = AsyncAgentboxd(api_key="k", base_url="http://agentboxd.test", http_client=http)
        stop = asyncio.Event()
        seen: list[str] = []

        async def handler(message: Message) -> None:
            seen.append(message["id"])
            if message["id"] == "b":
                raise ValueError("nope")
            if len(seen) >= 2:
                stop.set()

        def on_error(err: BaseException, lease: Any) -> None:
            stop.set()

        await consumer.inboxes.consume("i_1", handler, wait=0, stop=stop, concurrency=2, on_error=on_error)
        await consumer.close()
        assert sorted(seen) == ["a", "b"]

    asyncio.run(run())
    assert ("/v1/messages/a/ack", {"lease_id": "lease-a-1"}) in calls
    assert ("/v1/messages/b/nack", {"lease_id": "lease-b-1", "delay_seconds": 5}) in calls
