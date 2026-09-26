"""``inboxes.consume()``: a crash-safe consumer loop over the claim/ack lease queue (sync and async).

Claims messages, runs the handler for each (up to ``concurrency`` at once), extends the lease while the
handler runs, acks when it returns and nacks with exponential backoff when it raises. Delivery is
at-least-once: a consumer that dies mid-task leaves its lease to run out, and the message comes back.
"""

import asyncio
import contextlib
import inspect
import logging
import threading
from collections.abc import Awaitable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor
from concurrent.futures import wait as wait_futures
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

from ._errors import (
    AgentboxdError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
)
from ._types import ExtendResult, Lease, LeaseClaim, Message

if TYPE_CHECKING:
    from ._client import AsyncMessages, Messages

__all__ = ["ConsumeContext", "consume_retry_delay"]

log = logging.getLogger("agentboxd")

DEFAULT_LEASE_SECONDS = 300
DEFAULT_WAIT = 20.0
_FATAL = (AuthenticationError, PermissionDeniedError, NotFoundError, BadRequestError)
"""Wrong key, missing permission, unknown inbox or a bad option: retrying won't help, so the loop raises."""


def consume_retry_delay(delivery_count: int, base: float = 5, cap: float = 300) -> int:
    """Nack delay (seconds) after the handler failed on its ``delivery_count``-th delivery."""
    return int(min(cap, round(base * 2 ** max(0, delivery_count - 1))))


@dataclass
class ConsumeContext:
    """What a two-argument handler gets next to the message."""

    lease_id: str
    delivery_count: int
    lost: Union[threading.Event, asyncio.Event]
    """Set when the lease is lost (it ran out and the message was claimed again, or it was deleted)."""
    extend: Callable[..., Any]
    """Extends the lease now (the loop already does it in the background): ``extend(lease_seconds=300)``."""


ErrorHandler = Callable[[BaseException, Optional[Lease]], None]
SyncHandler = Union[Callable[[Message], Any], Callable[[Message, ConsumeContext], Any]]
AsyncHandler = Union[Callable[[Message], Awaitable[Any]], Callable[[Message, ConsumeContext], Awaitable[Any]]]


def _default_on_error(err: BaseException, lease: Optional[Lease]) -> None:
    mid = lease["message"]["id"] if lease else None
    log.warning("agentboxd consume: %s (message %s)", err, mid)


@dataclass
class ConsumeOptions:
    concurrency: int = 1
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    wait: float = DEFAULT_WAIT
    consumer: Optional[str] = None
    enriched: Optional[bool] = None
    retry_delay_seconds: float = 5
    max_retry_delay_seconds: float = 300
    paused_poll_seconds: float = 10
    on_error: Optional[ErrorHandler] = field(default=None)

    @property
    def report(self) -> ErrorHandler:
        return self.on_error or _default_on_error

    @property
    def heartbeat_seconds(self) -> float:
        return max(1.0, self.lease_seconds / 3)


def _wants_context(handler: Callable[..., Any]) -> bool:
    """True when the handler takes a second positional argument (the ConsumeContext)."""
    try:
        params = list(inspect.signature(handler).parameters.values())
    except (TypeError, ValueError):
        return False
    positional = [p for p in params if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
    return len(positional) >= 2 or any(p.kind is p.VAR_POSITIONAL for p in params)


def _backoff(failures: int) -> float:
    return float(min(30, 2 ** min(failures, 5)))


# ---------- sync ----------


def consume_sync(
    messages: "Messages",
    inbox_id: str,
    handler: SyncHandler,
    opts: ConsumeOptions,
    stop: Optional[threading.Event],
) -> None:
    stop = stop or threading.Event()
    concurrency = max(1, int(opts.concurrency))
    with_ctx = _wants_context(handler)
    call: Callable[..., Any] = handler

    def work(lease: Lease) -> None:
        mid = lease["message"]["id"]
        lost = threading.Event()
        done = threading.Event()

        def extend(lease_seconds: int = opts.lease_seconds) -> ExtendResult:
            res = messages.extend(mid, lease["lease_id"], lease_seconds=lease_seconds)
            if res.get("gone"):
                lost.set()
            return res

        def heartbeat() -> None:
            while not done.wait(opts.heartbeat_seconds):
                try:
                    extend()
                except AgentboxdError as err:
                    if err.status == 409:
                        lost.set()
                    opts.report(err, lease)
                except Exception as err:
                    opts.report(err, lease)

        beat = threading.Thread(target=heartbeat, name=f"agentboxd-lease-{mid}", daemon=True)
        beat.start()
        try:
            if with_ctx:
                call(
                    lease["message"], ConsumeContext(lease["lease_id"], lease["delivery_count"], lost, extend)
                )
            else:
                call(lease["message"])
        except Exception as err:
            done.set()
            opts.report(err, lease)
            delay = consume_retry_delay(
                lease["delivery_count"], opts.retry_delay_seconds, opts.max_retry_delay_seconds
            )
            try:
                messages.nack(mid, lease["lease_id"], delay_seconds=delay)
            except Exception as nack_err:
                opts.report(nack_err, lease)
            return
        finally:
            done.set()
        try:
            messages.ack(mid, lease["lease_id"])
        except Exception as ack_err:
            opts.report(ack_err, lease)

    failures = 0
    running: set[Future[None]] = set()
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="agentboxd-consume") as pool:
        while not stop.is_set():
            running = {f for f in running if not f.done()}
            if len(running) >= concurrency:
                wait_futures(running, timeout=1.0, return_when=FIRST_COMPLETED)
                continue
            try:
                claimed: LeaseClaim = messages.claim(
                    inbox_id,
                    limit=concurrency - len(running),
                    lease_seconds=opts.lease_seconds,
                    wait=opts.wait,
                    consumer=opts.consumer,
                    enriched=opts.enriched,
                )
                failures = 0
            except _FATAL:
                wait_futures(running)
                raise
            except Exception as err:
                opts.report(err, None)
                failures += 1
                stop.wait(_backoff(failures))
                continue
            if claimed.get("paused"):
                stop.wait(opts.paused_poll_seconds)
                continue
            for lease in claimed.get("data", []):
                running.add(pool.submit(work, lease))
            if not claimed.get("data") and not opts.wait:
                stop.wait(1.0)  # no long-poll and nothing to do: don't spin
        wait_futures(running)


# ---------- async ----------


async def _sleep_or_stop(stop: asyncio.Event, seconds: float) -> None:
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def consume_async(
    messages: "AsyncMessages",
    inbox_id: str,
    handler: AsyncHandler,
    opts: ConsumeOptions,
    stop: Optional[asyncio.Event],
) -> None:
    stop = stop or asyncio.Event()
    concurrency = max(1, int(opts.concurrency))
    with_ctx = _wants_context(handler)
    call: Callable[..., Awaitable[Any]] = handler

    async def work(lease: Lease) -> None:
        mid = lease["message"]["id"]
        lost = asyncio.Event()

        async def extend(lease_seconds: int = opts.lease_seconds) -> ExtendResult:
            res = await messages.extend(mid, lease["lease_id"], lease_seconds=lease_seconds)
            if res.get("gone"):
                lost.set()
            return res

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(opts.heartbeat_seconds)
                try:
                    await extend()
                except AgentboxdError as err:
                    if err.status == 409:
                        lost.set()
                    opts.report(err, lease)
                except Exception as err:
                    opts.report(err, lease)

        beat = asyncio.ensure_future(heartbeat())
        try:
            if with_ctx:
                await call(
                    lease["message"], ConsumeContext(lease["lease_id"], lease["delivery_count"], lost, extend)
                )
            else:
                await call(lease["message"])
        except Exception as err:
            beat.cancel()
            opts.report(err, lease)
            delay = consume_retry_delay(
                lease["delivery_count"], opts.retry_delay_seconds, opts.max_retry_delay_seconds
            )
            try:
                await messages.nack(mid, lease["lease_id"], delay_seconds=delay)
            except Exception as nack_err:
                opts.report(nack_err, lease)
            return
        finally:
            beat.cancel()
        try:
            await messages.ack(mid, lease["lease_id"])
        except Exception as ack_err:
            opts.report(ack_err, lease)

    failures = 0
    running: set[asyncio.Task[None]] = set()
    while not stop.is_set():
        running = {t for t in running if not t.done()}
        if len(running) >= concurrency:
            await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            continue
        try:
            claimed: LeaseClaim = await messages.claim(
                inbox_id,
                limit=concurrency - len(running),
                lease_seconds=opts.lease_seconds,
                wait=opts.wait,
                consumer=opts.consumer,
                enriched=opts.enriched,
            )
            failures = 0
        except _FATAL:
            if running:
                await asyncio.gather(*running, return_exceptions=True)
            raise
        except Exception as err:
            opts.report(err, None)
            failures += 1
            await _sleep_or_stop(stop, _backoff(failures))
            continue
        if claimed.get("paused"):
            await _sleep_or_stop(stop, opts.paused_poll_seconds)
            continue
        for lease in claimed.get("data", []):
            running.add(asyncio.ensure_future(work(lease)))
        if not claimed.get("data") and not opts.wait:
            await _sleep_or_stop(stop, 1.0)  # no long-poll and nothing to do: don't spin
    if running:
        await asyncio.gather(*running, return_exceptions=True)
