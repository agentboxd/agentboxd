"""AsyncAgentboxd.stream() against a scripted local WebSocket server (needs the websockets extra)."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Optional, Union

import httpx
import pytest

from agentboxd import (
    AsyncAgentboxd,
    AuthenticationError,
    InternalServerError,
    PermissionDeniedError,
    StreamClosedError,
    _stream,
)

websockets = pytest.importorskip("websockets")


class Script:
    """Server side: records subscribe frames; each connection runs ``plans[n]``."""

    def __init__(self) -> None:
        self.subscribes: list[dict[str, Any]] = []
        self.connections = 0
        self.plans: list[Any] = []

    async def handler(self, ws: Any, *_: Any) -> None:
        plan = self.plans[self.connections]
        self.connections += 1
        await ws.send(json.dumps({"type": "hello", "heartbeat_seconds": 30}))
        self.subscribes.append(json.loads(await ws.recv()))
        await plan(ws)


def event(event_id: str) -> str:
    return json.dumps(
        {"type": "event", "event": {"id": event_id, "type": "message.received", "created_at": "", "data": {}}}
    )


async def serve(script: Script) -> tuple[Any, int]:
    server = await websockets.serve(script.handler, "127.0.0.1", 0)
    port = next(iter(server.sockets)).getsockname()[1]
    return server, port


class Sleeps:
    """Stands in for ``asyncio`` in agentboxd._stream: records backoff sleeps without waiting."""

    def __init__(self) -> None:
        self.seconds: list[float] = []

    async def sleep(self, seconds: float) -> None:
        self.seconds.append(seconds)
        await asyncio.sleep(0)

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)


def no_wait(monkeypatch: pytest.MonkeyPatch) -> Sleeps:
    sleeps = Sleeps()
    monkeypatch.setattr(_stream, "asyncio", sleeps)
    monkeypatch.setattr(_stream, "random", SimpleNamespace(random=lambda: 1.0))  # no jitter: sleep == base
    return sleeps


def client(
    port: int, token_status: int = 201, failures: Optional[dict[int, Union[httpx.Response, Exception]]] = None
) -> AsyncAgentboxd:
    """``failures[n]`` answers the n-th token request (from 1) instead of a good token."""
    minted = {"n": 0}

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/stream/token"
        assert request.headers["Authorization"] == "Bearer mr_test"
        minted["n"] += 1
        failure = (failures or {}).get(minted["n"])
        if isinstance(failure, Exception):
            raise failure
        if failure is not None:
            return failure
        if token_status != 201:
            return httpx.Response(
                token_status, json={"error": {"code": "unauthorized", "message": "invalid API key"}}
            )
        url = f"ws://127.0.0.1:{port}/v1/stream?token=st_{minted['n']}"
        return httpx.Response(201, json={"token": f"st_{minted['n']}", "expires_at": "", "url": url})

    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    return AsyncAgentboxd(api_key="mr_test", base_url="http://api.test", http_client=http)


def test_subscribes_yields_and_resumes_with_since() -> None:
    async def main() -> None:
        script = Script()

        async def first(ws: Any) -> None:
            await ws.send(json.dumps({"type": "subscribed", "replayed": 0}))
            await ws.send(event("e1"))
            await ws.close(1001, "server restarting")

        async def second(ws: Any) -> None:
            await ws.send(json.dumps({"type": "subscribed", "replayed": 0, "replay_truncated": True}))
            await ws.send(event("e2"))
            await asyncio.sleep(5)

        script.plans = [first, second]
        server, port = await serve(script)
        mr = client(port)
        stream = mr.stream(inbox_ids=["i1"], event_types=["message.received"], payload="envelope")
        got = []
        async for e in stream:
            got.append(e["id"])
            if len(got) == 2:
                break
        await stream.close()
        server.close()
        assert got == ["e1", "e2"]
        assert script.subscribes[0] == {
            "type": "subscribe",
            "inbox_ids": ["i1"],
            "event_types": ["message.received"],
            "payload": "envelope",
        }
        assert script.subscribes[1]["since"] == "e1"
        assert stream.last_event_id == "e2"
        assert stream.replay_truncated is True
        await mr.close()

    asyncio.run(main())


def test_revoked_key_raises_stream_closed() -> None:
    async def main() -> None:
        script = Script()

        async def revoke(ws: Any) -> None:
            await ws.close(4001, "credential revoked or expired")

        script.plans = [revoke]
        server, port = await serve(script)
        mr = client(port)
        with pytest.raises(StreamClosedError) as info:
            async for _ in mr.stream():
                pass
        assert info.value.close_code == 4001
        assert script.connections == 1
        server.close()
        await mr.close()

    asyncio.run(main())


@pytest.mark.parametrize(("status", "error"), [(401, AuthenticationError), (403, PermissionDeniedError)])
def test_refused_token_raises_authentication_error(status: int, error: type[Exception]) -> None:
    async def main() -> None:
        mr = client(1, token_status=status)
        with pytest.raises(error):
            async for _ in mr.stream():
                pass
        await mr.close()

    asyncio.run(main())


def test_failed_token_requests_are_retried_and_resume_with_since(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = no_wait(monkeypatch)

    async def main() -> None:
        script = Script()

        async def first(ws: Any) -> None:
            await ws.send(json.dumps({"type": "subscribed", "replayed": 0}))
            await ws.send(event("e1"))
            await ws.close(1001, "server restarting")

        async def second(ws: Any) -> None:
            await ws.send(json.dumps({"type": "subscribed", "replayed": 0}))
            await ws.send(event("e2"))
            await asyncio.sleep(5)

        script.plans = [first, second]
        server, port = await serve(script)
        # The API restarts: the next token request gets a 502, then the connection is refused.
        mr = client(
            port,
            failures={
                2: httpx.Response(502, text="Bad Gateway"),
                3: httpx.ConnectError("connection refused"),
            },
        )
        stream = mr.stream()
        got = []
        async for e in stream:
            got.append(e["id"])
            if len(got) == 2:
                break
        await stream.close()
        server.close()
        assert got == ["e1", "e2"]
        assert script.connections == 2
        assert script.subscribes[1]["since"] == "e1"
        assert sleeps.seconds == [1.0, 2.0, 4.0]  # after the close, the 502 and the refused connection
        await mr.close()

    asyncio.run(main())


def test_token_retry_backs_off_to_the_cap_and_honours_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = no_wait(monkeypatch)
    failures: dict[int, Union[httpx.Response, Exception]] = {n: httpx.Response(503) for n in range(1, 8)}
    failures[8] = httpx.Response(
        429, headers={"Retry-After": "45"}, json={"error": {"code": "rate_limited", "message": "slow down"}}
    )
    failures[9] = httpx.Response(401, json={"error": {"code": "unauthorized", "message": "invalid API key"}})

    async def main() -> None:
        mr = client(1, failures=failures)
        with pytest.raises(AuthenticationError):
            async for _ in mr.stream():
                pass
        await mr.close()

    asyncio.run(main())
    assert sleeps.seconds == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 45.0]


def test_failed_token_request_raises_without_reconnect() -> None:
    async def main() -> None:
        mr = client(1, failures={1: httpx.Response(502)})
        with pytest.raises(InternalServerError):
            async for _ in mr.stream(reconnect=False):
                pass
        await mr.close()

    asyncio.run(main())


def test_refused_subscription_ends_the_stream() -> None:
    async def main() -> None:
        script = Script()

        async def refuse(ws: Any) -> None:
            await ws.send(
                json.dumps({"type": "error", "code": "inbox_not_found", "message": "inbox(es) not found: x"})
            )
            await asyncio.sleep(5)

        script.plans = [refuse]
        server, port = await serve(script)
        mr = client(port)
        with pytest.raises(StreamClosedError) as info:
            async for _ in mr.stream(inbox_ids=["x"]):
                pass
        assert info.value.code == "inbox_not_found"
        server.close()
        await mr.close()

    asyncio.run(main())


def test_server_fault_reconnects_and_resumes_with_since(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps = no_wait(monkeypatch)

    async def main() -> None:
        script = Script()

        async def first(ws: Any) -> None:
            await ws.send(json.dumps({"type": "subscribed", "replayed": 0}))
            await ws.send(event("e1"))
            await ws.close(1001, "server restarting")

        async def fault(ws: Any) -> None:
            # Not a refusal: the server's own problem, e.g. a database error during the replay.
            await ws.send(
                json.dumps({"type": "error", "code": "internal_error", "message": "internal error"})
            )
            await asyncio.sleep(5)

        async def third(ws: Any) -> None:
            await ws.send(json.dumps({"type": "subscribed", "replayed": 0}))
            await ws.send(event("e2"))
            await asyncio.sleep(5)

        script.plans = [first, fault, third]
        server, port = await serve(script)
        mr = client(port)
        stream = mr.stream()
        got = []
        async for e in stream:
            got.append(e["id"])
            if len(got) == 2:
                break
        await stream.close()
        server.close()
        assert got == ["e1", "e2"]
        assert script.connections == 3
        assert script.subscribes[1]["since"] == "e1"
        assert script.subscribes[2]["since"] == "e1"
        assert sleeps.seconds == [1.0, 2.0]  # no subscription came between: the backoff grows
        await mr.close()

    asyncio.run(main())
