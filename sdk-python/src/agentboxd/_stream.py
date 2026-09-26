"""Realtime event stream (``GET /v1/stream``) for :class:`AsyncAgentboxd`.

The same event bodies as webhooks, pushed over a WebSocket, with automatic reconnect and resume
(``since`` = the last event id seen). Needs the optional ``websockets`` package::

    pip install 'agentboxd[stream]'

    async with AsyncAgentboxd() as mr:
        async for event in mr.stream(event_types=["message.received"]):
            print(event["type"], event["data"]["message"]["subject"])
"""

import asyncio
import json
import random
from collections.abc import AsyncIterator, Awaitable, Sequence
from types import TracebackType
from typing import Any, Callable, Literal, Optional

from ._errors import AgentboxdError
from ._types import StreamEvent

__all__ = ["EventStream", "StreamClosedError"]

_FATAL_CODES = {4001, 4003, 1009}
_MAX_BACKOFF = 30.0


class StreamClosedError(AgentboxdError):
    """The server ended the stream for good: ``4001`` (credential invalid or revoked), ``4003``
    (missing ``messages:read``), ``1009`` (frame too large), or a subscription the server refused."""

    def __init__(self, close_code: int, reason: str, code: str = "stream_closed") -> None:
        super().__init__(0, code, f"stream closed ({close_code}): {reason}")
        self.close_code = close_code
        self.reason = reason


def _close_code(exc: BaseException) -> tuple[int, str]:
    """(code, reason) of a websockets ConnectionClosed, across websockets versions."""
    rcvd = getattr(exc, "rcvd", None)
    if rcvd is not None:
        return int(rcvd.code), str(rcvd.reason)
    return int(getattr(exc, "code", 1006) or 1006), str(getattr(exc, "reason", "") or "")


class EventStream:
    """Async iterator over stream events. Reconnects and resumes unless ``reconnect=False``.

    ``last_event_id`` is the id of the last event yielded; ``replay_truncated`` is ``True`` after a
    (re)subscribe whose replay may have missed events (resynchronise with the REST API then).
    """

    def __init__(
        self,
        mint_url: Callable[[], Awaitable[str]],
        *,
        inbox_ids: Optional[Sequence[str]] = None,
        event_types: Optional[Sequence[str]] = None,
        payload: Optional[Literal["full", "envelope"]] = None,
        since: Optional[str] = None,
        reconnect: bool = True,
    ) -> None:
        self._mint_url = mint_url
        self._subscribe: dict[str, Any] = {"type": "subscribe"}
        if inbox_ids:
            self._subscribe["inbox_ids"] = list(inbox_ids)
        if event_types:
            self._subscribe["event_types"] = list(event_types)
        if payload:
            self._subscribe["payload"] = payload
        self._reconnect = reconnect
        self._closed = False
        self._ws: Any = None
        self.last_event_id: Optional[str] = since
        self.replay_truncated = False

    def __aiter__(self) -> AsyncIterator[StreamEvent]:
        return self._events()

    async def close(self) -> None:
        """Stop the stream; the iterator ends after the current event."""
        self._closed = True
        if self._ws is not None:
            await self._ws.close()

    async def __aenter__(self) -> "EventStream":
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()

    async def _events(self) -> AsyncIterator[StreamEvent]:
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise ImportError(
                "AsyncAgentboxd.stream() needs the websockets package: pip install 'agentboxd[stream]'"
            ) from exc

        attempt = 0
        while not self._closed:
            # Token errors (bad key, missing permission) propagate: retrying won't help.
            url = await self._mint_url()
            try:
                async with websockets.connect(url, max_size=None) as ws:
                    self._ws = ws
                    async for raw in ws:
                        msg = json.loads(raw)
                        kind = msg.get("type")
                        if kind == "hello":
                            sub = dict(self._subscribe)
                            if self.last_event_id:
                                sub["since"] = self.last_event_id
                            await ws.send(json.dumps(sub))
                        elif kind == "subscribed":
                            attempt = 0
                            self.replay_truncated = bool(msg.get("replay_truncated"))
                        elif kind == "event":
                            event: StreamEvent = msg["event"]
                            self.last_event_id = event["id"]
                            yield event
                        elif kind == "error":
                            # Every error the server sends is about our own subscription.
                            raise StreamClosedError(1008, str(msg.get("message")), str(msg.get("code")))
            except websockets.ConnectionClosed as exc:
                code, reason = _close_code(exc)
                if code in _FATAL_CODES:
                    raise StreamClosedError(code, reason) from exc
            except (OSError, asyncio.TimeoutError, websockets.InvalidHandshake):
                pass  # network trouble: retry below
            finally:
                self._ws = None
            if self._closed or not self._reconnect:
                return
            base = min(_MAX_BACKOFF, 2.0**attempt)
            attempt += 1
            await asyncio.sleep(base / 2 + random.random() * base / 2)
