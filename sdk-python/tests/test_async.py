import asyncio
import inspect
from collections.abc import Awaitable
from typing import Any, TypeVar

import pytest

from agentboxd import Agentboxd, AsyncAgentboxd, NotFoundError, aiter_all

from .conftest import KEY, Recorder, make_async

T = TypeVar("T")


def run(coro: Awaitable[T]) -> T:
    async def _wrap() -> T:
        return await coro

    return asyncio.run(_wrap())


def test_async_surface_matches_sync() -> None:
    sync = Agentboxd(api_key="k")
    async_ = AsyncAgentboxd(api_key="k")
    for attr in ("inboxes", "messages", "threads", "webhooks", "contacts", "knowledge"):
        s_res, a_res = getattr(sync, attr), getattr(async_, attr)
        names = {m for m in dir(s_res) if not m.startswith("_")}
        assert names == {m for m in dir(a_res) if not m.startswith("_")}, attr
        for name in names:
            s_sig = inspect.signature(getattr(s_res, name))
            a_sig = inspect.signature(getattr(a_res, name))
            assert list(s_sig.parameters) == list(a_sig.parameters), f"{attr}.{name}"
            assert inspect.iscoroutinefunction(getattr(a_res, name)), f"{attr}.{name}"
    assert list(inspect.signature(sync.search).parameters) == list(
        inspect.signature(async_.search).parameters
    )
    sync.close()
    run(async_.close())


def test_async_requests(rec: Recorder) -> None:
    async def main() -> None:
        async with make_async(rec) as mr:
            rec.reply({"id": "ibx_1"})
            inbox = await mr.inboxes.create(client_id="c")
            assert inbox["id"] == "ibx_1"
            assert rec.last.headers["authorization"] == f"Bearer {KEY}"
            assert rec.last_json() == {"client_id": "c"}

            await mr.messages.send("ibx_1", "a@x.com", "S", text="t", idempotency_key="idem")
            assert rec.last.headers["idempotency-key"] == "idem"
            assert rec.last.url.path == "/v1/inboxes/ibx_1/messages/send"

            await mr.messages.list("ibx_1", labels=["a", "b"])
            assert rec.last_params() == {"labels": "a,b"}

            rec.reply({"data": None})
            assert await mr.messages.wait("ibx_1", timeout=5, from_="bob") is None
            assert rec.last_params() == {"timeout": "5", "from": "bob"}
            assert rec.last.extensions["timeout"]["read"] == 15

            rec.reply({"data": {"code": "1234", "from": "x"}})
            v = await mr.messages.wait_for_verification("ibx_1", from_="x")
            assert v is not None and v["code"] == "1234"
            assert rec.last.url.path == "/v1/inboxes/ibx_1/verification"

            await mr.search("hello", inbox_id="ibx_1")
            assert rec.last_params() == {"q": "hello", "inbox_id": "ibx_1"}

            await mr.webhooks.update("wh_1", inbox_ids=None, enabled=True)
            assert rec.last_json() == {"inbox_ids": None, "enabled": True}

            rec.reply(status=204)
            await mr.inboxes.delete("ibx_1")
            assert rec.last.method == "DELETE"

    run(main())


def test_async_errors(rec: Recorder) -> None:
    async def main() -> None:
        async with make_async(rec) as mr:
            rec.reply({"error": {"code": "not_found", "message": "Inbox not found"}}, status=404)
            with pytest.raises(NotFoundError) as info:
                await mr.inboxes.get("nope")
            assert info.value.code == "not_found"

    run(main())


def test_aiter_all(rec: Recorder) -> None:
    rec.reply({"data": [{"id": "t1"}], "next_cursor": "n"})
    rec.reply({"data": [{"id": "t2"}], "next_cursor": None})

    async def main() -> list[Any]:
        async with make_async(rec) as mr:
            return [t["id"] async for t in aiter_all(mr.threads.list, "ibx_1")]

    assert run(main()) == ["t1", "t2"]
    assert dict(rec.requests[1].url.params) == {"cursor": "n"}
