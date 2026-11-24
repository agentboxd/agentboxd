"""Agent memory and recall: memories.list / create / get / update / delete and the top-level recall."""

import asyncio
import inspect
from typing import get_args

import pytest

from agentboxd import (
    Agentboxd,
    AsyncAgentboxd,
    Memory,
    NotFoundError,
    RecallAnswer,
    RecallMode,
    RecallResult,
    RecallResultSource,
    RecallSource,
    SavedMemory,
)

from .conftest import Recorder, make_async

MEMORY: Memory = {
    "id": "mem_1",
    "inbox_id": None,
    "content": "Acme pays in US dollars, net 45 days.",
    "key": "customer:acme:billing",
    "tags": ["customer"],
    "contact_id": None,
    "thread_id": None,
    "message_id": None,
    "created_by": {"type": "api_key", "id": "key_1"},
    "created_at": "2026-11-14T10:00:00.000Z",
    "updated_at": "2026-11-14T10:00:00.000Z",
    "expires_at": None,
    "last_recalled_at": None,
    "recall_count": 0,
}


def test_memories_create(client: Agentboxd, rec: Recorder) -> None:
    rec.reply(
        {**MEMORY, "similar": [{"id": "mem_0", "content": "Acme pays in dollars.", "similarity": 0.95}]}
    )
    saved = client.memories.create("Acme pays in US dollars, net 45 days.")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/memories")
    # Arguments left out are not sent.
    assert rec.last_json() == {"content": "Acme pays in US dollars, net 45 days."}
    assert saved["id"] == "mem_1" and saved["similar"][0]["similarity"] == 0.95

    client.memories.create(
        "Prefers a call before noon.",
        inbox_id="ibx_1",
        key="customer:acme:contact",
        tags=("customer", "phone"),
        contact_id="c_1",
        thread_id="thr_1",
        message_id="msg_1",
        ttl_seconds=3600,
    )
    assert rec.last_json() == {
        "content": "Prefers a call before noon.",
        "inbox_id": "ibx_1",
        "key": "customer:acme:contact",
        "tags": ["customer", "phone"],
        "contact_id": "c_1",
        "thread_id": "thr_1",
        "message_id": "msg_1",
        "ttl_seconds": 3600,
    }

    client.memories.create("Trial ends soon.", expires_at="2027-01-01T00:00:00Z")
    assert rec.last_json() == {"content": "Trial ends soon.", "expires_at": "2027-01-01T00:00:00Z"}


def test_memories_list_and_get(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"data": [MEMORY], "next_cursor": "cur_2"})
    page = client.memories.list(
        inbox_id="ibx_1",
        key="customer:acme:billing",
        tag="customer",
        contact_id="c_1",
        thread_id="thr_1",
        cursor="cur_1",
        limit=5,
    )
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/memories")
    assert rec.last_params() == {
        "inbox_id": "ibx_1",
        "key": "customer:acme:billing",
        "tag": "customer",
        "contact_id": "c_1",
        "thread_id": "thr_1",
        "cursor": "cur_1",
        "limit": "5",
    }
    assert page["data"][0]["key"] == "customer:acme:billing" and page["next_cursor"] == "cur_2"

    client.memories.list()
    assert rec.last_params() == {}

    rec.reply(MEMORY)
    memory = client.memories.get("mem_1")
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/memories/mem_1")
    assert rec.last.content == b""
    assert memory["recall_count"] == 0

    rec.reply({"error": {"code": "not_found", "message": "memory not found"}}, status=404)
    with pytest.raises(NotFoundError):
        client.memories.get("mem_gone")


def test_memories_update_sends_nulls_and_skips_omitted(client: Agentboxd, rec: Recorder) -> None:
    client.memories.update("mem_1", content="Acme pays in euros.")
    assert (rec.last.method, rec.last.url.path) == ("PATCH", "/v1/memories/mem_1")
    assert rec.last_json() == {"content": "Acme pays in euros."}

    # None clears a field: it is sent as JSON null.
    client.memories.update(
        "mem_1", inbox_id=None, key=None, contact_id=None, thread_id=None, message_id=None, expires_at=None
    )
    assert rec.last_json() == {
        "inbox_id": None,
        "key": None,
        "contact_id": None,
        "thread_id": None,
        "message_id": None,
        "expires_at": None,
    }

    client.memories.update("mem_1", key=None)
    assert rec.last_json() == {"key": None}

    client.memories.update(
        "mem_1",
        inbox_id="ibx_2",
        key="customer:acme:currency",
        tags=["customer", "billing"],
        contact_id="c_2",
        thread_id="thr_2",
        message_id="msg_2",
        expires_at="2027-01-01T00:00:00Z",
    )
    assert rec.last_json() == {
        "inbox_id": "ibx_2",
        "key": "customer:acme:currency",
        "tags": ["customer", "billing"],
        "contact_id": "c_2",
        "thread_id": "thr_2",
        "message_id": "msg_2",
        "expires_at": "2027-01-01T00:00:00Z",
    }

    # An empty list removes every tag; leaving ``tags`` out keeps them.
    client.memories.update("mem_1", tags=[], ttl_seconds=60)
    assert rec.last_json() == {"tags": [], "ttl_seconds": 60}

    client.memories.update("mem_1")
    assert rec.last_json() == {}


def test_memories_delete(client: Agentboxd, rec: Recorder) -> None:
    rec.reply(status=204)
    client.memories.delete("mem_1")
    assert (rec.last.method, rec.last.url.path) == ("DELETE", "/v1/memories/mem_1")
    assert rec.last.content == b""


def test_memory_ids_are_path_escaped(client: Agentboxd, rec: Recorder) -> None:
    client.memories.get("a/b c")
    assert rec.last.url.raw_path == b"/v1/memories/a%2Fb%20c"
    client.memories.update("../inboxes", content="x")
    assert rec.last.url.raw_path == b"/v1/memories/..%2Finboxes"
    rec.reply(status=204)
    client.memories.delete("mem?x=1#y")
    assert rec.last.url.raw_path == b"/v1/memories/mem%3Fx%3D1%23y"

    sent = len(rec.requests)
    for bad in ("", ".", ".."):
        with pytest.raises(ValueError):
            client.memories.get(bad)
        with pytest.raises(ValueError):
            client.memories.update(bad, content="x")
        with pytest.raises(ValueError):
            client.memories.delete(bad)
    assert len(rec.requests) == sent


def test_recall(client: Agentboxd, rec: Recorder) -> None:
    answer: RecallAnswer = {
        "mode": "hybrid",
        "sources": ["memories", "knowledge", "messages"],
        "data": [
            {
                "source": "memory",
                "score": 1,
                "similarity": 0.883,
                "matched": ["meaning", "keyword"],
                "text": "Acme pays in US dollars, net 45 days.",
                "untrusted": False,
                "memory": MEMORY,
            },
            {
                "source": "message",
                "score": 0.75,
                "similarity": None,
                "matched": ["keyword"],
                "text": "Two of the six pallets were crushed on one side.",
                "untrusted": True,
                "message": {
                    "id": "msg_1",
                    "thread_id": "thr_1",
                    "inbox_id": "ibx_1",
                    "direction": "inbound",
                    "from": "dana@example.com",
                    "to": ["support@agentboxd.test"],
                    "subject": "Pallets damaged in Rotterdam",
                    "created_at": "2026-11-10T08:00:00.000Z",
                },
                "attachment": {"id": "att_1", "filename": "delivery-note.pdf"},
            },
            {
                "source": "knowledge",
                "score": 0.6,
                "similarity": 0.902,
                "matched": ["meaning"],
                "text": "Customers may return any item within 30 days of delivery.",
                "untrusted": False,
                "knowledge": {"id": "k_1", "inbox_id": None, "title": "Returns policy"},
            },
        ],
    }
    rec.reply(answer)
    out = client.recall("which currency does Acme pay in?")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/recall")
    # Only the question is sent: the server's defaults apply to everything left out.
    assert rec.last_json() == {"query": "which currency does Acme pay in?"}
    assert rec.last_params() == {}
    assert out["mode"] == "hybrid" and out["sources"] == ["memories", "knowledge", "messages"]
    first, second, third = out["data"]
    assert first["text"] == "Acme pays in US dollars, net 45 days." and first["untrusted"] is False
    assert first["memory"]["key"] == "customer:acme:billing"
    assert second["untrusted"] is True and second["similarity"] is None
    assert second["message"]["from"] == "dana@example.com"
    assert second["attachment"]["filename"] == "delivery-note.pdf"
    assert third["knowledge"]["title"] == "Returns policy" and "memory" not in third

    client.recall(
        "damaged pallets",
        inbox_id="ibx_1",
        sources=("memories", "messages"),
        limit=5,
        mode="semantic",
        tags=("customer",),
        contact_id="c_1",
        thread_id="thr_1",
        since="2026-11-01T00:00:00Z",
        until="2026-11-14T00:00:00Z",
        min_similarity=0.8,
    )
    assert rec.last_json() == {
        "query": "damaged pallets",
        "inbox_id": "ibx_1",
        "sources": ["memories", "messages"],
        "limit": 5,
        "mode": "semantic",
        "tags": ["customer"],
        "contact_id": "c_1",
        "thread_id": "thr_1",
        "since": "2026-11-01T00:00:00Z",
        "until": "2026-11-14T00:00:00Z",
        "min_similarity": 0.8,
    }

    # 0 is a value, not "left out".
    client.recall("x", mode="keyword", min_similarity=0)
    assert rec.last_json() == {"query": "x", "mode": "keyword", "min_similarity": 0}


def test_async_memory(rec: Recorder) -> None:
    async def main() -> None:
        async with make_async(rec) as mr:
            rec.reply({**MEMORY, "similar": []})
            saved = await mr.memories.create("Acme pays in US dollars.", key="customer:acme:billing")
            assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/memories")
            assert rec.last_json() == {"content": "Acme pays in US dollars.", "key": "customer:acme:billing"}
            assert saved["similar"] == []

            rec.reply({"data": [], "next_cursor": None})
            await mr.memories.list(tag="customer", limit=2)
            assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/memories")
            assert rec.last_params() == {"tag": "customer", "limit": "2"}

            await mr.memories.get("a/b")
            assert rec.last.url.raw_path == b"/v1/memories/a%2Fb"

            await mr.memories.update("mem_1", key=None, expires_at=None, tags=["a"])
            assert (rec.last.method, rec.last.url.path) == ("PATCH", "/v1/memories/mem_1")
            assert rec.last_json() == {"key": None, "tags": ["a"], "expires_at": None}

            rec.reply(status=204)
            await mr.memories.delete("mem_1")
            assert (rec.last.method, rec.last.url.path) == ("DELETE", "/v1/memories/mem_1")

            rec.reply({"data": [], "mode": "keyword", "sources": ["memories"]})
            out = await mr.recall("acme currency", sources=["memories"], limit=3)
            assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/recall")
            assert rec.last_json() == {"query": "acme currency", "sources": ["memories"], "limit": 3}
            assert out["mode"] == "keyword"

    asyncio.run(main())


def test_recall_is_on_both_clients() -> None:
    sync = Agentboxd(api_key="k")
    async_ = AsyncAgentboxd(api_key="k")
    s_sig, a_sig = inspect.signature(sync.recall), inspect.signature(async_.recall)
    assert list(s_sig.parameters) == list(a_sig.parameters)
    assert list(s_sig.parameters) == [
        "query",
        "inbox_id",
        "sources",
        "limit",
        "mode",
        "tags",
        "contact_id",
        "thread_id",
        "since",
        "until",
        "min_similarity",
    ]
    # Everything but the question is keyword-only.
    kinds = {name: p.kind for name, p in s_sig.parameters.items()}
    assert kinds.pop("query") is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert set(kinds.values()) == {inspect.Parameter.KEYWORD_ONLY}
    assert inspect.iscoroutinefunction(async_.recall) and not inspect.iscoroutinefunction(sync.recall)
    sync.close()
    asyncio.run(async_.close())


def test_memory_types() -> None:
    assert get_args(RecallSource) == ("memories", "knowledge", "messages")
    assert get_args(RecallMode) == ("hybrid", "semantic", "keyword")
    assert get_args(RecallResultSource) == ("memory", "knowledge", "message")
    # A result carries one of these, so they are optional keys.
    assert {"memory", "knowledge", "message", "attachment"} == set(RecallResult.__optional_keys__)
    assert {"source", "score", "similarity", "matched", "text", "untrusted"} == set(
        RecallResult.__required_keys__
    )
    assert SavedMemory.__required_keys__ == Memory.__required_keys__ | {"similar"}
    saved: SavedMemory = {**MEMORY, "similar": []}
    result: RecallResult = {
        "source": "memory",
        "score": 1.0,
        "similarity": None,
        "matched": ["keyword"],
        "text": saved["content"],
        "untrusted": False,
        "memory": MEMORY,
    }
    assert result["memory"]["created_by"] == {"type": "api_key", "id": "key_1"}
