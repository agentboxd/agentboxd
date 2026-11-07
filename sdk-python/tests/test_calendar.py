"""Meetings (calendar, beta): list, get, respond, create, update and cancel (sync and async)."""

import asyncio
import inspect
from datetime import date, datetime, timezone
from typing import Any, Union

import pytest

from agentboxd import (
    Agentboxd,
    AgentboxdError,
    AsyncAgentboxd,
    CalendarCancelDraftResult,
    CalendarCancelResult,
    CalendarDraftResult,
    CalendarEvent,
    CalendarEventPage,
    CalendarEventResult,
    DraftCalendar,
    Message,
    NotFoundError,
    UnprocessableEntityError,
)

from .conftest import Recorder, make_async

EVENT_ID = "9d7b5f3e-1c0a-4e8d-b6f4-2a0c8e6d4b13"


def event(**over: Any) -> dict[str, Any]:
    e: dict[str, Any] = {
        "id": EVENT_ID,
        "inbox_id": "ibx_1",
        "uid": "abc@google.com",
        "recurrence_id": None,
        "sequence": 0,
        "role": "attendee",
        "status": "confirmed",
        "response": "needs_action",
        "responded_at": None,
        "reply_expected": True,
        "title": "Onboarding plan sync",
        "description": "Agenda in the shared doc.",
        "location": None,
        "url": None,
        "conference": {"provider": "google_meet", "url": "https://meet.google.com/abc-defg-hij"},
        "start": "2026-11-10T15:00:00.000Z",
        "end": "2026-11-10T15:30:00.000Z",
        "all_day": False,
        "time_zone": None,
        "floating": False,
        "recurrence": None,
        "organizer": {"email": "alex@example.com", "name": "Alex Example"},
        "organizer_verified": True,
        "attendees": [],
        "proposals": [],
        "source": "invite",
        "message_id": "msg_1",
        "screening": {"state": "screened", "reason": None, "released_at": None},
        "created_at": "2026-11-04T10:00:00.000Z",
        "updated_at": "2026-11-04T10:00:00.000Z",
    }
    e.update(over)
    return e


SENT = {"id": "msg_out", "direction": "outbound", "status": "queued"}


def test_list_one_inbox_and_every_inbox(client: Agentboxd, rec: Recorder) -> None:
    rec.default = {"data": [event()], "next_cursor": None}
    page = client.calendar.list(
        "ibx_1",
        from_=datetime(2026, 11, 1, tzinfo=timezone.utc),
        to="2026-12-01T00:00:00Z",
        role="attendee",
        response="needs_action",
        status="confirmed",
        limit=10,
    )
    first: CalendarEvent = page["data"][0]
    assert first["title"] == "Onboarding plan sync"
    assert (rec.last.method, rec.last.url.path) == ("GET", "/v1/inboxes/ibx_1/calendar/events")
    assert rec.last_params() == {
        "from": "2026-11-01T00:00:00Z",
        "to": "2026-12-01T00:00:00Z",
        "role": "attendee",
        "response": "needs_action",
        "status": "confirmed",
        "limit": "10",
    }

    client.calendar.list_all(message_id="msg_1", include_unscreened=True)
    assert rec.last.url.path == "/v1/calendar/events"
    assert rec.last_params() == {"message_id": "msg_1", "include_unscreened": "true"}


def test_get_with_screening_opt_in(client: Agentboxd, rec: Recorder) -> None:
    rec.default = event()
    assert client.calendar.get(EVENT_ID)["organizer_verified"] is True
    assert (rec.last.method, rec.last.url.path) == ("GET", f"/v1/calendar/events/{EVENT_ID}")
    assert rec.last_params() == {}
    client.calendar.get(EVENT_ID, include_held=True)
    assert rec.last_params() == {"include_held": "true"}


def test_respond_answers_the_organizer_or_proposes_a_time(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"event": event(response="accepted"), "message": SENT}, status=202)
    r: CalendarEventResult = client.calendar.respond(
        EVENT_ID, "accepted", comment="See you there", idempotency_key="r-1"
    )
    assert r["event"]["response"] == "accepted"
    assert (rec.last.method, rec.last.url.path) == ("POST", f"/v1/calendar/events/{EVENT_ID}/respond")
    assert rec.last.headers["Idempotency-Key"] == "r-1"
    assert rec.last_json() == {"response": "accepted", "comment": "See you there"}
    assert rec.last_params() == {}

    client.calendar.respond(
        EVENT_ID,
        "tentative",
        propose={"start": datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc), "end": "2026-11-11T09:30:00Z"},
    )
    assert rec.last_json() == {
        "response": "tentative",
        "propose": {"start": "2026-11-11T09:00:00Z", "end": "2026-11-11T09:30:00Z"},
    }
    assert "Idempotency-Key" not in rec.last.headers


def test_respond_to_a_held_invite_raises(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"error": {"code": "message_withheld", "message": "held"}}, status=409)
    with pytest.raises(AgentboxdError) as exc:
        client.calendar.respond(EVENT_ID, "accepted")
    assert (exc.value.status, exc.value.code) == (409, "message_withheld")

    rec.reply({"error": {"code": "calendar_not_enabled", "message": "beta"}}, status=404)
    with pytest.raises(NotFoundError):
        client.calendar.list_all()


def test_create_update_cancel(client: Agentboxd, rec: Recorder) -> None:
    own = event(role="organizer", response=None, source="agent", message_id=None, screening=None)
    rec.reply({"event": own, "message": SENT}, status=201)
    created = client.calendar.create(
        "ibx_1",
        title="Kickoff",
        start=datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc),
        duration_minutes=45,
        time_zone="Europe/Paris",
        attendees=[
            {"email": "dana@example.com", "name": "Dana"},
            {"email": "sam@example.com", "optional": True},
        ],
        rrule="FREQ=WEEKLY;COUNT=4",
        idempotency_key="c-1",
    )
    assert created["event"]["role"] == "organizer"
    assert (rec.last.method, rec.last.url.path) == ("POST", "/v1/inboxes/ibx_1/calendar/events")
    assert rec.last.headers["Idempotency-Key"] == "c-1"
    assert rec.last_json() == {
        "title": "Kickoff",
        "start": "2026-11-12T14:00:00Z",
        "duration_minutes": 45,
        "time_zone": "Europe/Paris",
        "attendees": [
            {"email": "dana@example.com", "name": "Dana"},
            {"email": "sam@example.com", "optional": True},
        ],
        "recurrence": {"rrule": "FREQ=WEEKLY;COUNT=4"},
    }

    # All-day: dates stay dates.
    client.calendar.create(
        "ibx_1", title="Offsite", start=date(2026, 12, 1), end=date(2026, 12, 3), all_day=True, attendees=[]
    )
    assert rec.last_json()["start"] == "2026-12-01"
    assert rec.last_json()["end"] == "2026-12-03"

    client.calendar.update(EVENT_ID, start="2026-11-12T15:00:00Z", location=None, message="Moved by an hour")
    assert (rec.last.method, rec.last.url.path) == ("PATCH", f"/v1/calendar/events/{EVENT_ID}")
    assert rec.last_json() == {
        "start": "2026-11-12T15:00:00Z",
        "location": None,
        "message": "Moved by an hour",
    }
    client.calendar.update(EVENT_ID, title="Kickoff (v2)")
    assert rec.last_json() == {"title": "Kickoff (v2)"}

    rec.reply({"event": {**own, "status": "cancelled"}, "message": None})
    cancelled: CalendarCancelResult = client.calendar.cancel(EVENT_ID, message="Sorry")
    assert cancelled["message"] is None
    assert (rec.last.method, rec.last.url.path) == ("POST", f"/v1/calendar/events/{EVENT_ID}/cancel")
    assert rec.last_json() == {"message": "Sorry"}
    client.calendar.cancel(EVENT_ID)
    assert rec.last_json() == {}

    rec.reply({"error": {"code": "calendar_not_organizer", "message": "only the organizer"}}, status=422)
    with pytest.raises(UnprocessableEntityError):
        client.calendar.cancel("evt_invite")


def test_ids_are_path_segments(client: Agentboxd, rec: Recorder) -> None:
    rec.default = event()
    client.calendar.get("../inboxes")
    assert rec.last.url.raw_path == b"/v1/calendar/events/..%2Finboxes"
    rec.default = {"data": [], "next_cursor": None}
    client.calendar.list("a/b")
    assert rec.last.url.raw_path == b"/v1/inboxes/a%2Fb/calendar/events"
    for bad in (".", ".."):
        with pytest.raises(ValueError):
            client.calendar.respond(bad, "accepted")
        with pytest.raises(ValueError):
            client.calendar.cancel(bad)
    assert len(rec.requests) == 2


def test_messages_carry_the_calendar_link(client: Agentboxd, rec: Recorder) -> None:
    rec.default = {"id": "msg_1", "calendar": {"event_id": EVENT_ID, "method": "REQUEST"}}
    m: Message = client.messages.get("msg_1")
    link = m.get("calendar")
    assert link is not None and link["event_id"] == EVENT_ID
    # An invite that changed no meeting (an older version, a sender who can't speak for the organizer).
    rec.default = {"id": "msg_2", "calendar": {"event_id": None, "method": "PUBLISH"}}
    none = client.messages.get("msg_2").get("calendar")
    assert none is not None and none["event_id"] is None


def test_list_expands_a_series_into_occurrences(client: Agentboxd, rec: Recorder) -> None:
    series = {"rrule": "FREQ=WEEKLY;COUNT=60", "rdates": [], "exdates": []}
    rec.default = {
        "data": [
            event(recurrence=series, start="2026-11-17T09:00:00.000Z", series_id=EVENT_ID),
            event(id="evt_single", series_id=None),
        ],
        "next_cursor": None,
        "truncated": True,
    }
    page: CalendarEventPage = client.calendar.list(
        "ibx_1", expand="occurrences", from_=datetime(2026, 11, 1, tzinfo=timezone.utc)
    )
    assert rec.last_params() == {"expand": "occurrences", "from": "2026-11-01T00:00:00Z"}
    assert page.get("truncated") is True
    assert page["data"][0].get("series_id") == EVENT_ID
    assert page["data"][1].get("series_id") is None
    client.calendar.list_all(expand="occurrences")
    assert rec.last_params() == {"expand": "occurrences"}
    # Without expand nothing changes in the query.
    client.calendar.list("ibx_1")
    assert rec.last_params() == {}


def _meeting_draft(action: str, method: str, removed: Union[list[str], None] = None) -> dict[str, Any]:
    calendar = {"action": action, "method": method, "event_id": EVENT_ID, "removed_attendees": removed or []}
    return {"id": f"drf_{action}", "inbox_id": "ibx_1", "status": "draft", "calendar": calendar}


def test_draft_true_saves_a_draft_for_a_person_to_approve(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"event": event(), "message": None, "draft": _meeting_draft("respond", "REPLY")}, status=201)
    answered: CalendarDraftResult = client.calendar.respond(
        EVENT_ID, "accepted", draft=True, idempotency_key="r-2"
    )
    assert rec.last_json() == {"response": "accepted", "draft": True}
    assert rec.last.headers["Idempotency-Key"] == "r-2"
    assert answered["message"] is None
    meeting: Union[DraftCalendar, None] = answered["draft"].get("calendar")
    assert meeting is not None and meeting["action"] == "respond"

    rec.reply({"event": None, "message": None, "draft": _meeting_draft("create", "REQUEST")}, status=201)
    created: CalendarDraftResult = client.calendar.create(
        "ibx_1",
        title="Kickoff",
        start="2026-11-12T14:00:00Z",
        attendees=[{"email": "dana@example.com"}],
        draft=True,
    )
    assert rec.last_json()["draft"] is True
    assert created["event"] is None

    removed = _meeting_draft("update", "REQUEST", ["sam@example.com"])
    rec.reply({"event": event(role="organizer"), "message": None, "draft": removed}, status=201)
    changed: CalendarDraftResult = client.calendar.update(
        EVENT_ID, attendees=[{"email": "dana@example.com"}], draft=True
    )
    assert rec.last_json() == {"attendees": [{"email": "dana@example.com"}], "draft": True}
    changed_meeting = changed["draft"].get("calendar")
    assert changed_meeting is not None and changed_meeting["removed_attendees"] == ["sam@example.com"]

    cancel_draft = _meeting_draft("cancel", "CANCEL")
    rec.reply({"event": event(role="organizer"), "message": None, "draft": cancel_draft}, status=201)
    cancelled: CalendarCancelDraftResult = client.calendar.cancel(EVENT_ID, message="Moving it", draft=True)
    assert rec.last_json() == {"message": "Moving it", "draft": True}
    assert cancelled["draft"] is not None and cancelled["draft"]["id"] == "drf_cancel"

    # draft=False (the default) sends nothing about it.
    rec.reply({"event": event(), "message": SENT}, status=202)
    sent: CalendarEventResult = client.calendar.respond(EVENT_ID, "declined", draft=False)
    assert rec.last_json() == {"response": "declined"}
    assert sent["message"]["id"] == "msg_out"

    # A bool known only at run time gives either result.
    rec.reply({"event": event(), "message": SENT}, status=202)
    flag = len(rec.requests) < 0
    either: Union[CalendarEventResult, CalendarDraftResult] = client.calendar.respond(
        EVENT_ID, "accepted", draft=flag
    )
    assert either["event"] is not None


def test_a_meeting_draft_the_meeting_outran_is_refused(client: Agentboxd, rec: Recorder) -> None:
    rec.reply({"error": {"code": "calendar_event_changed", "message": "the meeting changed"}}, status=409)
    with pytest.raises(AgentboxdError) as exc:
        client.drafts.send("ibx_1", "drf_respond")
    assert (exc.value.status, exc.value.code) == (409, "calendar_event_changed")
    rec.reply({"error": {"code": "calendar_draft_fixed", "message": "from the meeting"}}, status=422)
    with pytest.raises(UnprocessableEntityError) as fixed:
        client.drafts.update("ibx_1", "drf_respond", to="someone@example.com")
    assert fixed.value.code == "calendar_draft_fixed"


def test_async_calendar(rec: Recorder) -> None:
    async def main() -> None:
        mr = make_async(rec)
        rec.default = {"data": [], "next_cursor": None}
        await mr.calendar.list("ibx_1", response="needs_action")
        assert rec.last_params() == {"response": "needs_action"}
        await mr.calendar.list_all()
        assert rec.last.url.path == "/v1/calendar/events"
        rec.default = event()
        await mr.calendar.get(EVENT_ID)
        rec.default = {"event": event(), "message": SENT}
        await mr.calendar.respond(EVENT_ID, "declined", comment="Out that week")
        assert rec.last_json() == {"response": "declined", "comment": "Out that week"}
        await mr.calendar.create(
            "ibx_1", title="Sync", start="2026-11-12T14:00:00Z", attendees=[{"email": "a@b.com"}]
        )
        assert rec.last_json()["attendees"] == [{"email": "a@b.com"}]
        await mr.calendar.update(EVENT_ID, conference_url=None)
        assert rec.last_json() == {"conference_url": None}
        await mr.calendar.cancel(EVENT_ID)
        assert rec.last.url.path == f"/v1/calendar/events/{EVENT_ID}/cancel"
        rec.default = {"data": [], "next_cursor": None, "truncated": False}
        page: CalendarEventPage = await mr.calendar.list("ibx_1", expand="occurrences")
        assert rec.last_params() == {"expand": "occurrences"} and page.get("truncated") is False
        rec.default = {"event": None, "message": None, "draft": _meeting_draft("create", "REQUEST")}
        drafted: CalendarDraftResult = await mr.calendar.create(
            "ibx_1", title="Sync", start="2026-11-12T14:00:00Z", attendees=[{"email": "a@b.com"}], draft=True
        )
        assert rec.last_json()["draft"] is True and drafted["event"] is None
        rec.default = {"event": event(), "message": None, "draft": None}
        nothing: CalendarCancelDraftResult = await mr.calendar.cancel(EVENT_ID, draft=True)
        assert rec.last_json() == {"draft": True} and nothing["draft"] is None
        await mr.close()

    asyncio.run(main())


def test_async_calendar_surface_matches_sync() -> None:
    sync = Agentboxd(api_key="k")
    async_ = AsyncAgentboxd(api_key="k")
    names = {m for m in dir(sync.calendar) if not m.startswith("_")}
    assert names == {"list", "list_all", "get", "respond", "create", "update", "cancel"}
    assert names == {m for m in dir(async_.calendar) if not m.startswith("_")}
    for name in names:
        s_sig = inspect.signature(getattr(sync.calendar, name))
        a_sig = inspect.signature(getattr(async_.calendar, name))
        assert list(s_sig.parameters) == list(a_sig.parameters), name
        assert inspect.iscoroutinefunction(getattr(async_.calendar, name)), name
    sync.close()

    async def close() -> None:
        await async_.close()

    asyncio.run(close())
