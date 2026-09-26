"""Phase 2b: contacts, metadata, knowledge and reply drafts."""

import asyncio

import pytest

from agentboxd import (
    Agentboxd,
    AgentboxdError,
    Contact,
    DraftReply,
    Inbox,
    KnowledgeDoc,
    PermissionDeniedError,
    Thread,
)

from .conftest import Recorder, make_async


def test_contacts_requests(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"data": [], "next_cursor": None})
    client.contacts.list(q="dana", label="vip", metadata={"tier": "gold", "seats": 5, "vip": True}, limit=10)
    assert rec.last.url.path == "/v1/contacts"
    assert rec.last_params() == {
        "q": "dana",
        "label": "vip",
        "limit": "10",
        "metadata.tier": "gold",
        "metadata.seats": "5",
        "metadata.vip": "true",
    }

    client.contacts.get("c_1")
    assert rec.last.url.path == "/v1/contacts/c_1"

    client.contacts.by_address("Dana+x@example.com")
    assert rec.last.url.raw_path == b"/v1/contacts/by-address/Dana%2Bx%40example.com"


def test_contact_update_merge_and_nulls(client: Agentboxd, rec: Recorder) -> None:
    client.contacts.update("c_1", notes="VIP", metadata={"tier": "gold", "legacy": None}, add_labels=["vip"])
    assert rec.last.method == "PATCH"
    assert rec.last_json() == {
        "notes": "VIP",
        "metadata": {"tier": "gold", "legacy": None},
        "add_labels": ["vip"],
    }

    client.contacts.update("c_1", notes=None, name=None)
    assert rec.last_json() == {"name": None, "notes": None}

    client.contacts.update("c_1", remove_labels=("vip",))
    assert rec.last_json() == {"remove_labels": ["vip"]}


def test_inbox_and_thread_metadata(client: Agentboxd, rec: Recorder) -> None:
    client.inboxes.create(client_id="c", metadata={"team": "billing"})
    assert rec.last_json() == {"client_id": "c", "metadata": {"team": "billing"}}

    client.inboxes.list(limit=5, metadata={"team": "billing"})
    assert rec.last_params() == {"limit": "5", "metadata.team": "billing"}

    client.inboxes.update("ibx_1", metadata={"region": "eu", "team": None})
    assert rec.last.method == "PATCH"
    assert rec.last.url.path == "/v1/inboxes/ibx_1"
    assert rec.last_json() == {"metadata": {"region": "eu", "team": None}}

    client.inboxes.update("ibx_1", display_name=None)
    assert rec.last_json() == {"display_name": None}

    client.threads.update("thr_1", metadata={"ticket": "T-1"}, add_labels=["open"])
    assert rec.last.url.path == "/v1/threads/thr_1"
    assert rec.last_json() == {"metadata": {"ticket": "T-1"}, "add_labels": ["open"]}


def test_knowledge_requests(client: Agentboxd, rec: Recorder) -> None:
    client.knowledge.create("Refunds", "Full refund within 30 days.", inbox_id="ibx_1")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/knowledge")
    assert rec.last_json() == {"title": "Refunds", "body": "Full refund within 30 days.", "inbox_id": "ibx_1"}

    client.knowledge.create("Shipping", "Ships Fridays.")
    assert rec.last_json() == {"title": "Shipping", "body": "Ships Fridays."}

    client.knowledge.list(inbox_id="ibx_1", limit=3)
    assert rec.last_params() == {"inbox_id": "ibx_1", "limit": "3"}

    client.knowledge.update("k_1", title="Refund policy")
    assert rec.last_json() == {"title": "Refund policy"}
    client.knowledge.update("k_1", inbox_id=None)
    assert rec.last_json() == {"inbox_id": None}

    rec.reply(
        {"data": [{"id": "k_1", "title": "Refunds", "inbox_id": None, "rank": 0.5, "snippet": "**refund**"}]}
    )
    hits = client.knowledge.search("refund", inbox_id="ibx_1", limit=5)
    assert hits["data"][0]["snippet"] == "**refund**"
    assert rec.last.url.path == "/v1/knowledge/search"
    assert rec.last_params() == {"q": "refund", "inbox_id": "ibx_1", "limit": "5"}

    rec.reply(status=204)
    client.knowledge.delete("k_1")
    assert rec.last.method == "DELETE"


def test_draft_reply(client: Agentboxd, rec: Recorder) -> None:
    rec.reply(
        {
            "text": "Hi Dana",
            "citations": [{"knowledge_id": "k_1", "title": "Refunds"}],
            "model": "deepseek-flash",
        }
    )
    draft = client.messages.draft_reply("msg_1", instructions="be brief")
    assert draft["citations"][0]["knowledge_id"] == "k_1"
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/messages/msg_1/draft-reply")
    assert rec.last_json() == {"instructions": "be brief"}

    client.messages.draft_reply("msg_1")
    assert rec.last_json() == {}

    rec.reply({"error": {"code": "ai_disabled", "message": "needs full"}}, status=403)
    with pytest.raises(PermissionDeniedError) as denied:
        client.messages.draft_reply("msg_1")
    assert denied.value.code == "ai_disabled"

    rec.reply({"error": {"code": "llm_unavailable", "message": "later"}}, status=503)
    with pytest.raises(AgentboxdError) as unavailable:
        client.messages.draft_reply("msg_1")
    assert unavailable.value.code == "llm_unavailable"


def test_async_phase2b(rec: Recorder) -> None:
    async def main() -> None:
        async with make_async(rec) as mr:
            await mr.contacts.update("c_1", metadata={"a": 1})
            assert rec.last_json() == {"metadata": {"a": 1}}
            await mr.knowledge.search("x")
            assert rec.last_params() == {"q": "x"}
            await mr.messages.draft_reply("m_1")
            assert rec.last.url.path == "/v1/messages/m_1/draft-reply"
            await mr.threads.update("t_1", remove_labels=["x"])
            assert rec.last_json() == {"remove_labels": ["x"]}

    asyncio.run(main())


def test_new_types_are_backward_compatible() -> None:
    # New response fields are optional keys, so older fixtures/servers still type-check.
    assert "metadata" in Inbox.__optional_keys__
    assert {"labels", "metadata"} <= set(Thread.__optional_keys__)
    contact: Contact = {
        "id": "c_1",
        "address": "dana@example.com",
        "name": None,
        "notes": None,
        "metadata": {"tier": "gold", "seats": 5, "vip": True},
        "labels": [],
        "message_count": 1,
        "first_seen_at": "2026-09-25T10:00:00.000Z",
        "last_seen_at": "2026-09-25T10:00:00.000Z",
        "created_at": "2026-09-25T10:00:00.000Z",
    }
    doc: KnowledgeDoc = {
        "id": "k",
        "inbox_id": None,
        "title": "t",
        "body": "b",
        "created_at": "x",
        "updated_at": "x",
    }
    draft: DraftReply = {"text": "hi", "citations": [], "model": "deepseek-flash"}
    assert contact["metadata"]["seats"] == 5 and doc["inbox_id"] is None and draft["model"]
