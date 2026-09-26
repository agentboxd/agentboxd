"""Trust layer T1: emergency stop, human on call (escalation), AI disclosure on messages."""

import asyncio

from agentboxd import Agentboxd, Message

from .conftest import Recorder, make_async


def test_emergency_stop(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"org": {"id": "o_1", "emergency_stopped_at": "2026-09-26T10:00:00.000Z"}})
    out = client.emergency_stop(reason="reply loop")
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/emergency-stop")
    assert rec.last_json() == {"reason": "reply loop"}
    assert out["org"]["emergency_stopped_at"]
    client.emergency_stop()
    assert rec.last_json() == {}


def test_escalation_get_and_update(client: Agentboxd, rec: Recorder) -> None:
    client.escalation.get()
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/escalation")

    client.escalation.update(contacts=("ops@example.com",), triggers={"blocked": True}, quiet_hours=None)
    assert (rec.last.method, rec.last.url.path) == ("PUT", "/v1/escalation")
    # Left-out arguments are not sent; quiet_hours=None is (it clears them).
    expected = {"contacts": ["ops@example.com"], "triggers": {"blocked": True}, "quiet_hours": None}
    assert rec.last_json() == expected

    client.escalation.update(delivery="digest", max_per_hour=5, include_excerpt=True)
    assert rec.last_json() == {"delivery": "digest", "max_per_hour": 5, "include_excerpt": True}


def test_inbox_escalation(client: Agentboxd, rec: Recorder) -> None:
    client.escalation.get_inbox("i_1")
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/inboxes/i_1/escalation")
    client.escalation.update_inbox("i_1", override=True, contacts=["a@example.com"], triggers=None)
    assert (rec.last.method, rec.last.url.path) == ("PUT", "/v1/inboxes/i_1/escalation")
    assert rec.last_json() == {"override": True, "contacts": ["a@example.com"], "triggers": None}


def test_async_trust() -> None:
    rec = Recorder()
    client = make_async(rec)

    async def run() -> None:
        await client.emergency_stop("x")
        assert rec.last_json() == {"reason": "x"}
        await client.escalation.update(contacts=[])
        assert rec.last_json() == {"contacts": []}
        await client.escalation.update_inbox("i_1", override=False)
        assert rec.last.url.path == "/v1/inboxes/i_1/escalation"
        await client.close()

    asyncio.run(run())


def test_message_ai_disclosure_type() -> None:
    m: Message = {"ai_disclosure": None}  # type: ignore[typeddict-item]
    assert m["ai_disclosure"] is None
