"""Transport-independent request descriptions shared by the sync and async clients."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional, Union, cast
from urllib.parse import quote

from ._types import (
    AttachmentInput,
    Direction,
    ListDirection,
    ListKind,
    MessageChannel,
    MessageType,
    MetadataValue,
    MetricsBucket,
    WebhookEventType,
    WebhookPayload,
)

__all__ = ["NOT_GIVEN", "NotGiven", "Request"]


class NotGiven:
    """Sentinel for "argument not passed", used where ``None`` is a meaningful value."""

    _instance: Optional["NotGiven"] = None

    def __new__(cls) -> "NotGiven":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return "NOT_GIVEN"


NOT_GIVEN = NotGiven()

_NO_BODY: Any = NOT_GIVEN

Recipients = Union[str, Sequence[str]]
QueryValue = Union[str, int, float, bool, None]
MetadataPatch = Mapping[str, MetadataValue]
MetadataFilter = Mapping[str, Union[str, int, float, bool]]
Nullable = Union[str, None, NotGiven]


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    params: dict[str, str] = field(default_factory=dict)
    json: Any = _NO_BODY
    idempotency_key: Optional[str] = None
    wait_seconds: Optional[float] = None
    """Server-side long-poll duration; the HTTP read timeout is extended to cover it."""

    @property
    def has_body(self) -> bool:
        return not isinstance(self.json, NotGiven)


def _seg(value: str) -> str:
    """One path segment: "/" is escaped, and "." and ".." are refused (URLs resolve them to another route)."""
    text = str(value)
    if text in (".", ".."):
        raise ValueError(f"{text!r} is not a valid id")
    return quote(text, safe="")


def _query(values: Mapping[str, QueryValue]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        else:
            out[key] = str(value)
    return out


def _body(values: Mapping[str, Any]) -> dict[str, Any]:
    """Drop arguments that were not given (``None`` or ``NOT_GIVEN``)."""
    return {k: v for k, v in values.items() if v is not None and not isinstance(v, NotGiven)}


def _recipients(value: Optional[Recipients]) -> Union[str, list[str], None]:
    if value is None or isinstance(value, str):
        return value
    return list(value)


def _list(value: Optional[Sequence[Any]]) -> Optional[list[Any]]:
    return None if value is None else list(value)


def _metadata(value: Optional[MetadataPatch]) -> Optional[dict[str, MetadataValue]]:
    return None if value is None else dict(value)


def _metadata_query(value: Optional[MetadataFilter]) -> dict[str, str]:
    """``{"plan": "pro"}`` -> ``{"metadata.plan": "pro"}`` (exact match; booleans as ``true``/``false``)."""
    return _query({f"metadata.{k}": v for k, v in (value or {}).items()})


def _patch(values: Mapping[str, Any], nullable: Sequence[str] = ()) -> dict[str, Any]:
    """Like ``_body``, but keys in ``nullable`` are sent as JSON null when passed as ``None``
    (they default to ``NOT_GIVEN``)."""
    body = _body(values)
    for key in nullable:
        if key in values and values[key] is None:
            body[key] = None
    return body


# ---------- inboxes ----------


def inbox_create(
    username: Optional[str],
    display_name: Optional[str],
    client_id: Optional[str],
    metadata: Optional[MetadataPatch] = None,
    domain: Optional[str] = None,
    ttl_seconds: Optional[int] = None,
    card: Optional[Mapping[str, Any]] = None,
) -> Request:
    body = _body(
        {
            "username": username,
            "display_name": display_name,
            "client_id": client_id,
            "metadata": _metadata(metadata),
            "domain": domain,
            "ttl_seconds": ttl_seconds,
            "card": dict(card) if card is not None else None,
        }
    )
    return Request("POST", "/v1/inboxes", json=body)


def inbox_list(
    cursor: Optional[str],
    limit: Optional[int],
    metadata: Optional[MetadataFilter] = None,
    include_temporary: Optional[bool] = None,
    temporary: Optional[bool] = None,
) -> Request:
    params = {
        **_query(
            {"cursor": cursor, "limit": limit, "include_temporary": include_temporary, "temporary": temporary}
        ),
        **_metadata_query(metadata),
    }
    return Request("GET", "/v1/inboxes", params=params)


def inbox_update(
    inbox_id: str,
    display_name: Nullable,
    metadata: Optional[MetadataPatch],
    ttl_seconds: Optional[int] = None,
    promotions_filter: Union[bool, NotGiven, None] = NOT_GIVEN,
) -> Request:
    body = _patch(
        {
            "display_name": display_name,
            "metadata": _metadata(metadata),
            "ttl_seconds": ttl_seconds,
            "promotions_filter": promotions_filter,
        },
        nullable=("display_name", "promotions_filter"),
    )
    return Request("PATCH", f"/v1/inboxes/{_seg(inbox_id)}", json=body)


def inbox_get(inbox_id: str) -> Request:
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}")


def inbox_delete(inbox_id: str) -> Request:
    return Request("DELETE", f"/v1/inboxes/{_seg(inbox_id)}")


def inbox_pause(inbox_id: str, reason: Optional[str] = None) -> Request:
    return Request("POST", f"/v1/inboxes/{_seg(inbox_id)}/pause", json=_body({"reason": reason}))


def inbox_resume(inbox_id: str) -> Request:
    return Request("POST", f"/v1/inboxes/{_seg(inbox_id)}/resume")


# ---------- identity-only agents ----------


def identity_create(
    username: Optional[str],
    display_name: Optional[str],
    client_id: Optional[str],
    metadata: Optional[MetadataPatch] = None,
    card: Optional[Mapping[str, Any]] = None,
) -> Request:
    body = _body(
        {
            "username": username,
            "display_name": display_name,
            "client_id": client_id,
            "metadata": _metadata(metadata),
            "card": dict(card) if card is not None else None,
        }
    )
    return Request("POST", "/v1/identities", json=body)


def identity_list(
    cursor: Optional[str], limit: Optional[int], metadata: Optional[MetadataFilter] = None
) -> Request:
    params = {**_query({"cursor": cursor, "limit": limit}), **_metadata_query(metadata)}
    return Request("GET", "/v1/identities", params=params)


def identity_get(identity_id: str) -> Request:
    return Request("GET", f"/v1/identities/{_seg(identity_id)}")


def identity_update(identity_id: str, display_name: Nullable, metadata: Optional[MetadataPatch]) -> Request:
    body = _patch({"display_name": display_name, "metadata": _metadata(metadata)}, nullable=("display_name",))
    return Request("PATCH", f"/v1/identities/{_seg(identity_id)}", json=body)


def identity_delete(identity_id: str) -> Request:
    return Request("DELETE", f"/v1/identities/{_seg(identity_id)}")


# ---------- agent cards and the directory (aSIM) ----------


def agent_get(inbox_id: str) -> Request:
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}/agent")


def agent_update(inbox_id: str, card: Mapping[str, Any]) -> Request:
    return Request("PATCH", f"/v1/inboxes/{_seg(inbox_id)}/agent", json=dict(card))


def agent_delete(inbox_id: str) -> Request:
    return Request("DELETE", f"/v1/inboxes/{_seg(inbox_id)}/agent")


def agent_revoke(inbox_id: str, reason: Optional[str]) -> Request:
    return Request("POST", f"/v1/inboxes/{_seg(inbox_id)}/agent/revoke", json=_body({"reason": reason}))


def agent_restore(inbox_id: str) -> Request:
    return Request("POST", f"/v1/inboxes/{_seg(inbox_id)}/agent/restore")


def agent_oasf(inbox_id: str) -> Request:
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}/agent/oasf")


def agent_keys_list(inbox_id: str) -> Request:
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}/agent/keys")


def agent_keys_register(inbox_id: str, public_jwk: Mapping[str, Any], proof: str) -> Request:
    return Request(
        "POST",
        f"/v1/inboxes/{_seg(inbox_id)}/agent/keys",
        json={"public_jwk": dict(public_jwk), "proof": proof},
    )


def agent_keys_retire(inbox_id: str, kid: str) -> Request:
    return Request("POST", f"/v1/inboxes/{_seg(inbox_id)}/agent/keys/{_seg(kid)}/retire")


def agent_keys_revoke(inbox_id: str, kid: str, reason: Optional[str], since: Optional[str]) -> Request:
    return Request(
        "POST",
        f"/v1/inboxes/{_seg(inbox_id)}/agent/keys/{_seg(kid)}/revoke",
        json=_body({"reason": reason, "since": since}),
    )


def directory_resolve(address: Optional[str] = None, handle: Optional[str] = None) -> Request:
    if (address is None) == (handle is None):
        raise ValueError("pass exactly one of address or handle")
    params = {"address": address} if address is not None else {"handle": cast(str, handle)}
    return Request("GET", "/v1/directory/resolve", params=params)


def directory_handle_get() -> Request:
    return Request("GET", "/v1/directory/handle")


def directory_handle_set(handle: str) -> Request:
    return Request("PUT", "/v1/directory/handle", json={"handle": handle})


def directory_handle_release() -> Request:
    return Request("DELETE", "/v1/directory/handle")


def public_agents_search(
    q: Optional[str],
    capability: Optional[str],
    type: Optional[MessageType],
    limit: Optional[int],
    cursor: Optional[str],
) -> Request:
    params = _query({"q": q, "capability": capability, "type": type, "limit": limit, "cursor": cursor})
    return Request("GET", "/v1/public/agents", params=params)


def public_agent(address: str, document: str = "") -> Request:
    suffix = f"/{document}" if document else ""
    return Request("GET", f"/v1/public/agents/{_seg(address)}{suffix}")


def public_handle(workspace: str, agent: str) -> Request:
    return Request("GET", f"/v1/public/handles/{_seg(workspace.lstrip('@'))}/{_seg(agent)}")


def directory_verify(signature: Optional[str], address: Optional[str]) -> Request:
    if (signature is None) == (address is None):
        raise ValueError("pass exactly one of signature or address")
    return Request("POST", "/v1/directory/verify", json=_body({"signature": signature, "address": address}))


def directory_search(
    q: Optional[str],
    capability: Optional[str],
    type: Optional[MessageType],
    limit: Optional[int],
    cursor: Optional[str],
    scope: Optional[str] = None,
) -> Request:
    params = _query(
        {"q": q, "capability": capability, "type": type, "limit": limit, "cursor": cursor, "scope": scope}
    )
    return Request("GET", "/v1/directory/search", params=params)


def directory_report(address: str, reason: str, details: Optional[str], message_id: Optional[str]) -> Request:
    body = _body({"address": address, "reason": reason, "details": details, "message_id": message_id})
    return Request("POST", "/v1/directory/reports", json=body)


# ---------- messages ----------


def message_send(
    inbox_id: str,
    to: Recipients,
    subject: str,
    text: Optional[str],
    html: Optional[str],
    cc: Optional[Recipients],
    bcc: Optional[Recipients],
    attachments: Optional[Sequence[AttachmentInput]],
    labels: Optional[Sequence[str]],
    idempotency_key: Optional[str],
    data: Any = None,
    type: Optional[MessageType] = None,
    agent_signature: Optional[str] = None,
) -> Request:
    body = _body(
        {
            "to": _recipients(to),
            "cc": _recipients(cc),
            "bcc": _recipients(bcc),
            "subject": subject,
            "text": text,
            "html": html,
            "attachments": _list(attachments),
            "labels": _list(labels),
            "data": data,
            "type": type,
            "agent_signature": agent_signature,
        }
    )
    return Request(
        "POST", f"/v1/inboxes/{_seg(inbox_id)}/messages/send", json=body, idempotency_key=idempotency_key
    )


def message_reply(
    inbox_id: str,
    message_id: str,
    text: Optional[str],
    html: Optional[str],
    attachments: Optional[Sequence[AttachmentInput]],
    reply_all: Optional[bool],
    labels: Optional[Sequence[str]],
    idempotency_key: Optional[str],
    data: Any = None,
    type: Optional[MessageType] = None,
    agent_signature: Optional[str] = None,
) -> Request:
    body = _body(
        {
            "text": text,
            "html": html,
            "attachments": _list(attachments),
            "reply_all": reply_all,
            "labels": _list(labels),
            "data": data,
            "type": type,
            "agent_signature": agent_signature,
        }
    )
    return Request(
        "POST",
        f"/v1/inboxes/{_seg(inbox_id)}/messages/{_seg(message_id)}/reply",
        json=body,
        idempotency_key=idempotency_key,
    )


def message_list(
    inbox_id: str,
    labels: Optional[Sequence[str]],
    is_read: Optional[bool],
    direction: Optional[Direction],
    cursor: Optional[str],
    limit: Optional[int],
    include_blocked: Optional[bool] = None,
    channel: Optional[MessageChannel] = None,
    type: Optional[MessageType] = None,
    screening: Optional[str] = None,
    include_unscreened: Optional[bool] = None,
    include_held: Optional[bool] = None,
    promotions: Optional[Literal["include", "exclude", "only"]] = None,
    status: Optional[str] = None,
) -> Request:
    params = _query(
        {
            "labels": None if labels is None else ",".join(labels),
            "is_read": is_read,
            "direction": direction,
            "include_blocked": include_blocked,
            "promotions": promotions,
            "channel": channel,
            "type": type,
            "screening": screening,
            "status": status,
            "include_unscreened": include_unscreened,
            "include_held": include_held,
            "cursor": cursor,
            "limit": limit,
        }
    )
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}/messages", params=params)


def message_list_all(
    labels: Optional[Sequence[str]],
    is_read: Optional[bool],
    direction: Optional[Direction],
    cursor: Optional[str],
    limit: Optional[int],
    include_blocked: Optional[bool] = None,
    channel: Optional[MessageChannel] = None,
    type: Optional[MessageType] = None,
    screening: Optional[str] = None,
    include_unscreened: Optional[bool] = None,
    include_held: Optional[bool] = None,
    status: Optional[str] = None,
) -> Request:
    params = _query(
        {
            "labels": None if labels is None else ",".join(labels),
            "is_read": is_read,
            "direction": direction,
            "include_blocked": include_blocked,
            "channel": channel,
            "type": type,
            "screening": screening,
            "status": status,
            "include_unscreened": include_unscreened,
            "include_held": include_held,
            "cursor": cursor,
            "limit": limit,
        }
    )
    return Request("GET", "/v1/messages", params=params)


def message_get(
    message_id: str, include_unscreened: Optional[bool] = None, include_held: Optional[bool] = None
) -> Request:
    params = _query({"include_unscreened": include_unscreened, "include_held": include_held})
    return Request("GET", f"/v1/messages/{_seg(message_id)}", params=params)


def message_update(
    message_id: str,
    add_labels: Optional[Sequence[str]],
    remove_labels: Optional[Sequence[str]],
    is_read: Optional[bool],
) -> Request:
    body = _body({"add_labels": _list(add_labels), "remove_labels": _list(remove_labels), "is_read": is_read})
    return Request("PATCH", f"/v1/messages/{_seg(message_id)}", json=body)


def message_release(message_id: str) -> Request:
    return Request("POST", f"/v1/messages/{_seg(message_id)}/release")


def message_draft_reply(message_id: str, instructions: Optional[str], save: Optional[bool] = None) -> Request:
    return Request(
        "POST",
        f"/v1/messages/{_seg(message_id)}/draft-reply",
        json=_body({"instructions": instructions, "save": save}),
    )


def message_attachment_text(
    message_id: str, attachment_id: str, offset: Optional[int] = None, max_chars: Optional[int] = None
) -> Request:
    params = _query({"offset": offset, "max_chars": max_chars})
    return Request(
        "GET", f"/v1/messages/{_seg(message_id)}/attachments/{_seg(attachment_id)}/text", params=params
    )


def message_extract_attachment(
    message_id: str,
    attachment_id: str,
    schema: Union[str, Mapping[str, Any]],
    instructions: Optional[str] = None,
) -> Request:
    return Request(
        "POST",
        f"/v1/messages/{_seg(message_id)}/attachments/{_seg(attachment_id)}/extract",
        json=_body(
            {"schema": schema if isinstance(schema, str) else dict(schema), "instructions": instructions}
        ),
    )


# ---------- drafts ----------

SendAt = Union[str, datetime]
"""An ISO 8601 string or a timezone-aware ``datetime`` (naive datetimes are treated as UTC)."""
NullableSendAt = Union[str, datetime, None, NotGiven]
NullableText = Union[str, None, NotGiven]
DraftStatuses = Union[str, Sequence[str]]


def _iso(value: SendAt) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    return value


def _statuses(value: Optional[DraftStatuses]) -> Optional[str]:
    if value is None or isinstance(value, str):
        return value
    return ",".join(value)


def _draft_path(inbox_id: str, draft_id: str) -> str:
    return f"/v1/inboxes/{_seg(inbox_id)}/drafts/{_seg(draft_id)}"


def draft_create(
    inbox_id: str,
    to: Optional[Recipients] = None,
    subject: Optional[str] = None,
    text: Optional[str] = None,
    html: Optional[str] = None,
    cc: Optional[Recipients] = None,
    bcc: Optional[Recipients] = None,
    attachments: Optional[Sequence[AttachmentInput]] = None,
    labels: Optional[Sequence[str]] = None,
    metadata: Optional[MetadataPatch] = None,
    reply_to_message_id: Optional[str] = None,
    thread_id: Optional[str] = None,
    reply_all: Optional[bool] = None,
    send_at: Optional[SendAt] = None,
    idempotency_key: Optional[str] = None,
    data: Any = None,
    type: Optional[MessageType] = None,
) -> Request:
    body = _body(
        {
            "to": _recipients(to),
            "cc": _recipients(cc),
            "bcc": _recipients(bcc),
            "subject": subject,
            "text": text,
            "html": html,
            "attachments": _list(attachments),
            "labels": _list(labels),
            "metadata": _metadata(metadata),
            "reply_to_message_id": reply_to_message_id,
            "thread_id": thread_id,
            "reply_all": reply_all,
            "send_at": None if send_at is None else _iso(send_at),
            "data": data,
            "type": type,
        }
    )
    return Request("POST", f"/v1/inboxes/{_seg(inbox_id)}/drafts", json=body, idempotency_key=idempotency_key)


def draft_list(
    inbox_id: str,
    status: Optional[DraftStatuses],
    thread_id: Optional[str],
    cursor: Optional[str],
    limit: Optional[int],
) -> Request:
    params = _query({"status": _statuses(status), "thread_id": thread_id, "cursor": cursor, "limit": limit})
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}/drafts", params=params)


def draft_list_all(
    inbox_id: Optional[str],
    status: Optional[DraftStatuses],
    thread_id: Optional[str],
    cursor: Optional[str],
    limit: Optional[int],
) -> Request:
    """``GET /v1/drafts`` filtered by ``inbox_id`` as a query parameter."""
    params = _query(
        {
            "inbox_id": inbox_id,
            "status": _statuses(status),
            "thread_id": thread_id,
            "cursor": cursor,
            "limit": limit,
        }
    )
    return Request("GET", "/v1/drafts", params=params)


def draft_get(inbox_id: str, draft_id: str) -> Request:
    return Request("GET", _draft_path(inbox_id, draft_id))


def draft_update(
    inbox_id: str,
    draft_id: str,
    to: Optional[Recipients] = None,
    subject: NullableText = NOT_GIVEN,
    text: NullableText = NOT_GIVEN,
    html: NullableText = NOT_GIVEN,
    cc: Optional[Recipients] = None,
    bcc: Optional[Recipients] = None,
    attachments: Optional[Sequence[Mapping[str, Any]]] = None,
    labels: Optional[Sequence[str]] = None,
    metadata: Optional[MetadataPatch] = None,
    send_at: NullableSendAt = NOT_GIVEN,
    data: Any = NOT_GIVEN,
    type: Optional[MessageType] = None,
) -> Request:
    body = _patch(
        {
            "to": _recipients(to),
            "cc": _recipients(cc),
            "bcc": _recipients(bcc),
            "subject": subject,
            "text": text,
            "html": html,
            "attachments": None if attachments is None else [dict(a) for a in attachments],
            "labels": _list(labels),
            "metadata": _metadata(metadata),
            "send_at": _iso(send_at) if isinstance(send_at, (str, datetime)) else send_at,
            "data": data,
            "type": type,
        },
        nullable=("subject", "text", "html", "send_at", "data"),
    )
    return Request("PATCH", _draft_path(inbox_id, draft_id), json=body)


def draft_delete(inbox_id: str, draft_id: str) -> Request:
    return Request("DELETE", _draft_path(inbox_id, draft_id))


def draft_send(inbox_id: str, draft_id: str, idempotency_key: Optional[str] = None) -> Request:
    return Request("POST", f"{_draft_path(inbox_id, draft_id)}/send", idempotency_key=idempotency_key)


def draft_schedule(inbox_id: str, draft_id: str, send_at: SendAt) -> Request:
    return Request("POST", f"{_draft_path(inbox_id, draft_id)}/schedule", json={"send_at": _iso(send_at)})


def draft_cancel(inbox_id: str, draft_id: str) -> Request:
    return Request("POST", f"{_draft_path(inbox_id, draft_id)}/cancel")


# ---------- meetings (calendar, beta) ----------

CalendarTime = Union[str, datetime, date]
"""An ISO 8601 string, a timezone-aware ``datetime`` (naive ones are treated as UTC), or a ``date`` for an
all-day meeting."""


def _when(value: Optional[CalendarTime]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _calendar_filters(
    from_: Optional[CalendarTime],
    to: Optional[CalendarTime],
    status: Optional[str],
    role: Optional[str],
    response: Optional[str],
    message_id: Optional[str],
    include_unscreened: Optional[bool],
    include_held: Optional[bool],
    cursor: Optional[str],
    limit: Optional[int],
    expand: Optional[str] = None,
) -> dict[str, str]:
    return _query(
        {
            "from": _when(from_),
            "to": _when(to),
            "status": status,
            "role": role,
            "response": response,
            "message_id": message_id,
            "expand": expand,
            "include_unscreened": include_unscreened,
            "include_held": include_held,
            "cursor": cursor,
            "limit": limit,
        }
    )


def calendar_list(inbox_id: str, **filters: Any) -> Request:
    return Request(
        "GET", f"/v1/inboxes/{_seg(inbox_id)}/calendar/events", params=_calendar_filters(**filters)
    )


def calendar_list_all(**filters: Any) -> Request:
    return Request("GET", "/v1/calendar/events", params=_calendar_filters(**filters))


def _event_path(event_id: str) -> str:
    return f"/v1/calendar/events/{_seg(event_id)}"


def calendar_get(
    event_id: str, include_unscreened: Optional[bool] = None, include_held: Optional[bool] = None
) -> Request:
    params = _query({"include_unscreened": include_unscreened, "include_held": include_held})
    return Request("GET", _event_path(event_id), params=params)


def calendar_respond(
    event_id: str,
    response: str,
    comment: Optional[str] = None,
    propose: Optional[Mapping[str, CalendarTime]] = None,
    idempotency_key: Optional[str] = None,
    include_unscreened: Optional[bool] = None,
    include_held: Optional[bool] = None,
    draft: Optional[bool] = None,
) -> Request:
    body = _body(
        {
            "response": response,
            "comment": comment,
            "propose": None
            if propose is None
            else {"start": _when(propose.get("start")), "end": _when(propose.get("end"))},
            "draft": draft,
        }
    )
    params = _query({"include_unscreened": include_unscreened, "include_held": include_held})
    return Request(
        "POST", f"{_event_path(event_id)}/respond", params=params, json=body, idempotency_key=idempotency_key
    )


def _attendees(value: Optional[Sequence[Mapping[str, Any]]]) -> Optional[list[dict[str, Any]]]:
    return None if value is None else [dict(a) for a in value]


def calendar_create(
    inbox_id: str,
    title: str,
    start: CalendarTime,
    attendees: Sequence[Mapping[str, Any]],
    end: Optional[CalendarTime] = None,
    duration_minutes: Optional[int] = None,
    all_day: Optional[bool] = None,
    time_zone: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    conference_url: Optional[str] = None,
    rrule: Optional[str] = None,
    message: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    draft: Optional[bool] = None,
) -> Request:
    body = _body(
        {
            "title": title,
            "start": _when(start),
            "end": _when(end),
            "duration_minutes": duration_minutes,
            "all_day": all_day,
            "time_zone": time_zone,
            "attendees": _attendees(attendees),
            "description": description,
            "location": location,
            "conference_url": conference_url,
            "recurrence": None if rrule is None else {"rrule": rrule},
            "message": message,
            "draft": draft,
        }
    )
    return Request(
        "POST", f"/v1/inboxes/{_seg(inbox_id)}/calendar/events", json=body, idempotency_key=idempotency_key
    )


def calendar_update(
    event_id: str,
    title: Optional[str] = None,
    start: Optional[CalendarTime] = None,
    end: Optional[CalendarTime] = None,
    duration_minutes: Optional[int] = None,
    time_zone: Optional[str] = None,
    attendees: Optional[Sequence[Mapping[str, Any]]] = None,
    description: NullableText = NOT_GIVEN,
    location: NullableText = NOT_GIVEN,
    conference_url: NullableText = NOT_GIVEN,
    message: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    draft: Optional[bool] = None,
) -> Request:
    body = _patch(
        {
            "title": title,
            "start": _when(start),
            "end": _when(end),
            "duration_minutes": duration_minutes,
            "time_zone": time_zone,
            "attendees": _attendees(attendees),
            "description": description,
            "location": location,
            "conference_url": conference_url,
            "message": message,
            "draft": draft,
        },
        nullable=("description", "location", "conference_url"),
    )
    return Request("PATCH", _event_path(event_id), json=body, idempotency_key=idempotency_key)


def calendar_cancel(
    event_id: str,
    message: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    draft: Optional[bool] = None,
) -> Request:
    return Request(
        "POST",
        f"{_event_path(event_id)}/cancel",
        json=_body({"message": message, "draft": draft}),
        idempotency_key=idempotency_key,
    )


def message_wait(
    inbox_id: str,
    timeout: float,
    since: Optional[str],
    from_: Optional[str],
    subject: Optional[str],
    direction: Optional[Direction],
    channel: Optional[MessageChannel] = None,
    type: Optional[MessageType] = None,
    include_unscreened: Optional[bool] = None,
    include_held: Optional[bool] = None,
) -> Request:
    params = _query(
        {
            "timeout": _num(timeout),
            "since": since,
            "from": from_,
            "subject": subject,
            "direction": direction,
            "channel": channel,
            "type": type,
            "include_unscreened": include_unscreened,
            "include_held": include_held,
        }
    )
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}/messages/wait", params=params, wait_seconds=timeout)


def message_claim(
    inbox_id: str,
    limit: Optional[int],
    lease_seconds: Optional[int],
    consumer: Optional[str],
    wait: Optional[float],
    enriched: Optional[bool],
    since: Optional[str],
    type: Optional[MessageType] = None,
    channel: Optional[MessageChannel] = None,
    analysis: Optional[str] = None,
    include_unscreened: Optional[bool] = None,
    include_held: Optional[bool] = None,
) -> Request:
    body = _body(
        {
            "limit": limit,
            "lease_seconds": lease_seconds,
            "consumer": consumer,
            "wait": None if wait is None else _num(wait),
            "enriched": enriched,
            "since": since,
            "type": type,
            "channel": channel,
            "analysis": analysis,
            "include_unscreened": include_unscreened,
            "include_held": include_held,
        }
    )
    return Request(
        "POST", f"/v1/inboxes/{_seg(inbox_id)}/messages/claim", json=body, wait_seconds=wait if wait else None
    )


def message_ack(message_id: str, lease_id: str, mark_read: Optional[bool]) -> Request:
    body = _body({"lease_id": lease_id, "mark_read": mark_read})
    return Request("POST", f"/v1/messages/{_seg(message_id)}/ack", json=body)


def message_nack(message_id: str, lease_id: str, delay_seconds: Optional[int]) -> Request:
    body = _body({"lease_id": lease_id, "delay_seconds": delay_seconds})
    return Request("POST", f"/v1/messages/{_seg(message_id)}/nack", json=body)


def message_extend(message_id: str, lease_id: str, lease_seconds: Optional[int]) -> Request:
    body = _body({"lease_id": lease_id, "lease_seconds": lease_seconds})
    return Request("POST", f"/v1/messages/{_seg(message_id)}/extend", json=body)


def message_wait_for_verification(
    inbox_id: str,
    timeout: float,
    since: Optional[str],
    from_: Optional[str],
    include_unauthenticated: Optional[bool] = None,
) -> Request:
    params = _query(
        {
            "timeout": _num(timeout),
            "since": since,
            "from": from_,
            "include_unauthenticated": include_unauthenticated,
        }
    )
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}/verification", params=params, wait_seconds=timeout)


def _num(value: float) -> Union[int, float]:
    return int(value) if float(value).is_integer() else value


# ---------- threads & search ----------


def _thread_filters(
    cursor: Optional[str],
    limit: Optional[int],
    labels: Optional[Sequence[str]] = None,
    before: Optional[str] = None,
    after: Optional[str] = None,
    participant: Optional[str] = None,
    subject: Optional[str] = None,
    ascending: Optional[bool] = None,
    inbox_id: Optional[str] = None,
) -> dict[str, str]:
    return _query(
        {
            "cursor": cursor,
            "limit": limit,
            "labels": ",".join(labels) if labels else None,
            "before": before,
            "after": after,
            "participant": participant,
            "subject": subject,
            "ascending": True if ascending else None,
            "inbox_id": inbox_id,
        }
    )


def thread_list(inbox_id: str, cursor: Optional[str], limit: Optional[int], **filters: Any) -> Request:
    params = _thread_filters(cursor, limit, **filters)
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}/threads", params=params)


def thread_list_all(cursor: Optional[str], limit: Optional[int], **filters: Any) -> Request:
    return Request("GET", "/v1/threads", params=_thread_filters(cursor, limit, **filters))


def thread_delete(thread_id: str) -> Request:
    return Request("DELETE", f"/v1/threads/{_seg(thread_id)}")


def message_forward(
    inbox_id: str,
    message_id: str,
    to: Recipients,
    cc: Optional[Recipients],
    bcc: Optional[Recipients],
    text: Optional[str],
    html: Optional[str],
    include_attachments: Optional[bool],
    labels: Optional[Sequence[str]],
    idempotency_key: Optional[str],
) -> Request:
    body = _body(
        {
            "to": _recipients(to),
            "cc": _recipients(cc),
            "bcc": _recipients(bcc),
            "text": text,
            "html": html,
            "include_attachments": include_attachments,
            "labels": _list(labels),
        }
    )
    return Request(
        "POST",
        f"/v1/inboxes/{_seg(inbox_id)}/messages/{_seg(message_id)}/forward",
        json=body,
        idempotency_key=idempotency_key,
    )


def messages_batch_get(
    ids: Sequence[str], include_unscreened: Optional[bool] = None, include_held: Optional[bool] = None
) -> Request:
    body = _body({"ids": list(ids), "include_unscreened": include_unscreened, "include_held": include_held})
    return Request("POST", "/v1/messages/batch-get", json=body)


def messages_batch_update(
    ids: Sequence[str],
    add_labels: Optional[Sequence[str]],
    remove_labels: Optional[Sequence[str]],
    is_read: Optional[bool],
) -> Request:
    body = _body({"add_labels": _list(add_labels), "remove_labels": _list(remove_labels), "is_read": is_read})
    return Request("POST", "/v1/messages/batch-update", json={"ids": list(ids), **body})


def thread_get(thread_id: str) -> Request:
    return Request("GET", f"/v1/threads/{_seg(thread_id)}")


def thread_update(
    thread_id: str,
    metadata: Optional[MetadataPatch],
    add_labels: Optional[Sequence[str]],
    remove_labels: Optional[Sequence[str]],
) -> Request:
    body = _body(
        {
            "metadata": _metadata(metadata),
            "add_labels": _list(add_labels),
            "remove_labels": _list(remove_labels),
        }
    )
    return Request("PATCH", f"/v1/threads/{_seg(thread_id)}", json=body)


# ---------- contacts ----------


def _kinds(kind: Union[str, Sequence[str], None]) -> Optional[str]:
    if kind is None or isinstance(kind, str):
        return kind
    return ",".join(kind)


def contact_list(
    q: Optional[str],
    label: Optional[str],
    metadata: Optional[MetadataFilter],
    cursor: Optional[str],
    limit: Optional[int],
    kind: Union[str, Sequence[str], None] = None,
    domain: Optional[str] = None,
) -> Request:
    params = {
        **_query(
            {"q": q, "label": label, "kind": _kinds(kind), "domain": domain, "cursor": cursor, "limit": limit}
        ),
        **_metadata_query(metadata),
    }
    return Request("GET", "/v1/contacts", params=params)


def contact_domains(kind: Union[str, Sequence[str], None], limit: Optional[int]) -> Request:
    return Request("GET", "/v1/contacts/domains", params=_query({"kind": _kinds(kind), "limit": limit}))


def contact_get(contact_id: str) -> Request:
    return Request("GET", f"/v1/contacts/{_seg(contact_id)}")


def contact_by_address(address: str) -> Request:
    return Request("GET", f"/v1/contacts/by-address/{_seg(address)}")


def contact_update(
    contact_id: str,
    name: Nullable,
    notes: Nullable,
    metadata: Optional[MetadataPatch],
    add_labels: Optional[Sequence[str]],
    remove_labels: Optional[Sequence[str]],
    kind: Optional[str] = None,
) -> Request:
    body = _patch(
        {
            "name": name,
            "notes": notes,
            "metadata": _metadata(metadata),
            "add_labels": _list(add_labels),
            "remove_labels": _list(remove_labels),
            "kind": kind,
        },
        nullable=("name", "notes"),
    )
    return Request("PATCH", f"/v1/contacts/{_seg(contact_id)}", json=body)


def contact_delete(contact_id: str, forget: bool = False) -> Request:
    return Request("DELETE", f"/v1/contacts/{_seg(contact_id)}", params={"forget": "true"} if forget else {})


def contact_delete_many(
    kind: Optional[Sequence[str]], domain: Optional[str], forget: bool, dry_run: bool
) -> Request:
    body: dict[str, Any] = {}
    if kind is not None:
        body["kind"] = list(kind)
    if domain is not None:
        body["domain"] = domain
    if forget:
        body["forget"] = True
    if dry_run:
        body["dry_run"] = True
    return Request("POST", "/v1/contacts/delete", json=body)


# ---------- knowledge ----------


def knowledge_list(inbox_id: Optional[str], cursor: Optional[str], limit: Optional[int]) -> Request:
    return Request(
        "GET", "/v1/knowledge", params=_query({"inbox_id": inbox_id, "cursor": cursor, "limit": limit})
    )


def knowledge_create(title: str, body: str, inbox_id: Optional[str]) -> Request:
    return Request("POST", "/v1/knowledge", json=_body({"title": title, "body": body, "inbox_id": inbox_id}))


def knowledge_get(doc_id: str) -> Request:
    return Request("GET", f"/v1/knowledge/{_seg(doc_id)}")


def knowledge_update(doc_id: str, title: Optional[str], body: Optional[str], inbox_id: Nullable) -> Request:
    payload = _patch({"title": title, "body": body, "inbox_id": inbox_id}, nullable=("inbox_id",))
    return Request("PATCH", f"/v1/knowledge/{_seg(doc_id)}", json=payload)


def knowledge_delete(doc_id: str) -> Request:
    return Request("DELETE", f"/v1/knowledge/{_seg(doc_id)}")


def knowledge_search(q: str, inbox_id: Optional[str], limit: Optional[int]) -> Request:
    return Request(
        "GET", "/v1/knowledge/search", params=_query({"q": q, "inbox_id": inbox_id, "limit": limit})
    )


def search(
    q: str,
    inbox_id: Optional[str],
    cursor: Optional[str],
    limit: Optional[int],
    channel: Optional[MessageChannel] = None,
    type: Optional[MessageType] = None,
) -> Request:
    params = _query(
        {"q": q, "inbox_id": inbox_id, "cursor": cursor, "limit": limit, "channel": channel, "type": type}
    )
    return Request("GET", "/v1/search", params=params)


# ---------- webhooks ----------

InboxIds = Union[Sequence[str], NotGiven, None]


def _inbox_ids(value: InboxIds) -> Union[list[str], NotGiven, None]:
    if value is None or isinstance(value, NotGiven):
        return value
    return list(value)


def _body_keep_null(values: Mapping[str, Any], nullable: str) -> dict[str, Any]:
    body = _body(values)
    if values.get(nullable, NOT_GIVEN) is None:
        body[nullable] = None
    return body


def webhook_create(
    url: str,
    events: Optional[Sequence[WebhookEventType]],
    inbox_ids: InboxIds,
    secret: Optional[str],
    payload: Optional[WebhookPayload] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> Request:
    body = _body_keep_null(
        {
            "url": url,
            "events": _list(events),
            "inbox_ids": _inbox_ids(inbox_ids),
            "secret": secret,
            "payload": payload,
            "headers": dict(headers) if headers is not None else None,
        },
        "inbox_ids",
    )
    return Request("POST", "/v1/webhooks", json=body)


def webhook_list() -> Request:
    return Request("GET", "/v1/webhooks")


def webhook_get(webhook_id: str) -> Request:
    return Request("GET", f"/v1/webhooks/{_seg(webhook_id)}")


def webhook_update(
    webhook_id: str,
    url: Optional[str],
    events: Optional[Sequence[WebhookEventType]],
    inbox_ids: InboxIds,
    enabled: Optional[bool],
    payload: Optional[WebhookPayload] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> Request:
    body = _body_keep_null(
        {
            "url": url,
            "events": _list(events),
            "inbox_ids": _inbox_ids(inbox_ids),
            "enabled": enabled,
            "payload": payload,
            "headers": dict(headers) if headers is not None else None,
        },
        "inbox_ids",
    )
    return Request("PATCH", f"/v1/webhooks/{_seg(webhook_id)}", json=body)


def webhook_delete(webhook_id: str) -> Request:
    return Request("DELETE", f"/v1/webhooks/{_seg(webhook_id)}")


def webhook_test(webhook_id: str) -> Request:
    return Request("POST", f"/v1/webhooks/{_seg(webhook_id)}/test")


def webhook_rotate_secret(webhook_id: str, secret: Optional[str]) -> Request:
    return Request("POST", f"/v1/webhooks/{_seg(webhook_id)}/rotate-secret", json=_body({"secret": secret}))


def webhook_deliveries(
    webhook_id: str, status: Optional[str], cursor: Optional[str], limit: Optional[int]
) -> Request:
    params = _query({"status": status, "cursor": cursor, "limit": limit})
    return Request("GET", f"/v1/webhooks/{_seg(webhook_id)}/deliveries", params=params)


def webhook_redeliver(webhook_id: str, delivery_id: Optional[str], event_id: Optional[str]) -> Request:
    if (delivery_id is None) == (event_id is None):
        raise ValueError("pass exactly one of delivery_id and event_id")
    if delivery_id is not None:
        return Request("POST", f"/v1/webhooks/{_seg(webhook_id)}/deliveries/{_seg(delivery_id)}/redeliver")
    return Request("POST", f"/v1/webhooks/{_seg(webhook_id)}/redeliver", json={"event_id": event_id})


# ---------- the workspace's suppression list ----------


def suppression_list(
    reason: Optional[str], q: Optional[str], cursor: Optional[str], limit: Optional[int]
) -> Request:
    params = _query({"reason": reason, "q": q, "cursor": cursor, "limit": limit})
    return Request("GET", "/v1/suppressions", params=params)


def suppression_remove(address: str, confirm: bool) -> Request:
    params = _query({"confirm": True}) if confirm else {}
    return Request("DELETE", f"/v1/suppressions/{_seg(address)}", params=params)


# ---------- custom domains ----------


def domain_create(domain: str, receiving: Optional[bool]) -> Request:
    return Request("POST", "/v1/domains", json=_body({"domain": domain, "receiving": receiving}))


def domain_list() -> Request:
    return Request("GET", "/v1/domains")


def domain_get(domain_id: str) -> Request:
    return Request("GET", f"/v1/domains/{_seg(domain_id)}")


def domain_zone_file(domain_id: str) -> Request:
    return Request("GET", f"/v1/domains/{_seg(domain_id)}/zone-file")


def domain_verify(domain_id: str) -> Request:
    return Request("POST", f"/v1/domains/{_seg(domain_id)}/verify")


def domain_update(domain_id: str, receiving: Optional[bool]) -> Request:
    return Request("PATCH", f"/v1/domains/{_seg(domain_id)}", json=_body({"receiving": receiving}))


def domain_dkim_rotate(domain_id: str) -> Request:
    return Request("POST", f"/v1/domains/{_seg(domain_id)}/dkim/rotate")


def domain_dkim_activate(domain_id: str) -> Request:
    return Request("POST", f"/v1/domains/{_seg(domain_id)}/dkim/activate")


def domain_delete(domain_id: str, force: bool) -> Request:
    params = _query({"force": True}) if force else {}
    return Request("DELETE", f"/v1/domains/{_seg(domain_id)}", params=params)


def webhook_events() -> Request:
    return Request("GET", "/v1/webhooks/events")


# ---------- allow / block lists ----------


def list_entries(
    inbox_id: Optional[str], direction: Optional[ListDirection], kind: Optional[ListKind]
) -> Request:
    params = _query({"inbox_id": inbox_id, "direction": direction, "kind": kind})
    return Request("GET", "/v1/lists", params=params)


def list_create(direction: ListDirection, kind: ListKind, pattern: str, inbox_id: Optional[str]) -> Request:
    body = _body({"direction": direction, "kind": kind, "pattern": pattern, "inbox_id": inbox_id})
    return Request("POST", "/v1/lists", json=body)


def list_delete(entry_id: str) -> Request:
    return Request("DELETE", f"/v1/lists/{_seg(entry_id)}")


# ---------- metrics ----------


def deliverability() -> Request:
    return Request("GET", "/v1/deliverability")


def metrics(
    from_: Optional[str],
    to: Optional[str],
    tz: Optional[str],
    inbox_id: Optional[str],
    bucket: Optional[MetricsBucket],
) -> Request:
    params = _query({"from": from_, "to": to, "tz": tz, "inbox_id": inbox_id, "bucket": bucket})
    return Request("GET", "/v1/metrics", params=params)


# ---------- realtime stream ----------


def stream_token() -> Request:
    return Request("POST", "/v1/stream/token")


# ---------- agent self-signup ----------


def signup_challenge() -> Request:
    return Request("GET", "/v1/signup/challenge")


def signup_create(
    challenge: str,
    solution: str,
    agent_name: Optional[str],
    owner_email: Optional[str],
    kind: Optional[str] = None,
) -> Request:
    return Request(
        "POST",
        "/v1/signup",
        json=_body(
            {
                "challenge": challenge,
                "solution": solution,
                "agent_name": agent_name,
                "owner_email": owner_email,
                "kind": kind,
            }
        ),
    )


def account_get() -> Request:
    return Request("GET", "/v1/account")


# ---------- trust layer: emergency stop and human on call ----------


def emergency_stop(reason: Optional[str]) -> Request:
    return Request("POST", "/v1/emergency-stop", json=_body({"reason": reason}))


def forwarding_list(inbox_id: str) -> Request:
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}/forwarding")


def forwarding_add(inbox_id: str, address: str, skip_flagged: Optional[bool]) -> Request:
    return Request(
        "POST",
        f"/v1/inboxes/{_seg(inbox_id)}/forwarding",
        json=_body({"address": address, "skip_flagged": skip_flagged}),
    )


def forwarding_resend(inbox_id: str, forward_id: str) -> Request:
    return Request("POST", f"/v1/inboxes/{_seg(inbox_id)}/forwarding/{_seg(forward_id)}/resend")


def forwarding_remove(inbox_id: str, forward_id: str) -> Request:
    return Request("DELETE", f"/v1/inboxes/{_seg(inbox_id)}/forwarding/{_seg(forward_id)}")


def escalation_get() -> Request:
    return Request("GET", "/v1/escalation")


def _given(values: Mapping[str, Any]) -> dict[str, Any]:
    """Keep every argument that was given, ``None`` included (``quiet_hours=None`` clears them)."""
    return {k: v for k, v in values.items() if not isinstance(v, NotGiven)}


def escalation_update(body: Mapping[str, Any]) -> Request:
    return Request("PUT", "/v1/escalation", json=_given(body))


def inbox_escalation_get(inbox_id: str) -> Request:
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}/escalation")


def inbox_escalation_update(inbox_id: str, body: Mapping[str, Any]) -> Request:
    return Request("PUT", f"/v1/inboxes/{_seg(inbox_id)}/escalation", json=_given(body))


def signup_claim(email: str) -> Request:
    return Request("POST", "/v1/signup/claim", json={"email": email})


def signup_add_agent(kind: Optional[str] = None, expires_at: Optional[str] = None) -> Request:
    return Request("POST", "/v1/signup/agents", json=_body({"kind": kind, "expires_at": expires_at}))


# ---------- agent identity (Sign in with Agentboxd) ----------

IdentityScopes = Union[str, Sequence[str]]


def _scope(value: Optional[IdentityScopes]) -> Optional[str]:
    if value is None or isinstance(value, str):
        return value
    return " ".join(value)


def identity_token(
    inbox_id: Optional[str],
    audience: Optional[str],
    nonce: Optional[str],
    scope: Optional[IdentityScopes],
    expires_in: Optional[int],
    identity_id: Optional[str] = None,
) -> Request:
    """``inbox_id`` for an inbox or ``identity_id`` for an identity-only agent (the same endpoint)."""
    if (inbox_id is None) == (identity_id is None):
        raise TypeError("pass exactly one of inbox_id or identity_id")
    if not audience:
        raise TypeError("audience is required (the relying party's client_id)")
    agent_id = cast(str, identity_id if identity_id is not None else inbox_id)
    body = _body({"audience": audience, "nonce": nonce, "scope": _scope(scope), "expires_in": expires_in})
    return Request("POST", f"/v1/inboxes/{_seg(agent_id)}/identity-token", json=body)


def identity_client_list() -> Request:
    return Request("GET", "/v1/identity/clients")


def identity_client_create(
    name: str,
    type: str,
    redirect_uris: Optional[Sequence[str]],
    allowed_scopes: Optional[Sequence[str]],
    subject_type: Optional[str],
    homepage_url: Optional[str],
) -> Request:
    body = _body(
        {
            "name": name,
            "type": type,
            "redirect_uris": _list(redirect_uris),
            "allowed_scopes": _list(allowed_scopes),
            "subject_type": subject_type,
            "homepage_url": homepage_url,
        }
    )
    return Request("POST", "/v1/identity/clients", json=body)


def identity_client_get(client_id: str) -> Request:
    return Request("GET", f"/v1/identity/clients/{_seg(client_id)}")


def identity_client_update(
    client_id: str,
    name: Optional[str],
    redirect_uris: Optional[Sequence[str]],
    allowed_scopes: Optional[Sequence[str]],
    homepage_url: Nullable,
    enabled: Optional[bool],
) -> Request:
    body = _patch(
        {
            "name": name,
            "redirect_uris": _list(redirect_uris),
            "allowed_scopes": _list(allowed_scopes),
            "homepage_url": homepage_url,
            "enabled": enabled,
        },
        nullable=("homepage_url",),
    )
    return Request("PATCH", f"/v1/identity/clients/{_seg(client_id)}", json=body)


def identity_client_delete(client_id: str) -> Request:
    return Request("DELETE", f"/v1/identity/clients/{_seg(client_id)}")


def identity_client_rotate_secret(client_id: str) -> Request:
    return Request("POST", f"/v1/identity/clients/{_seg(client_id)}/secret")


def inbox_identity_get(inbox_id: str) -> Request:
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}/identity")


def inbox_identity_update(inbox_id: str, enabled: bool) -> Request:
    return Request("PATCH", f"/v1/inboxes/{_seg(inbox_id)}/identity", json={"enabled": enabled})


def inbox_identity_sign_ins(inbox_id: str, cursor: Optional[str], limit: Optional[int]) -> Request:
    params = _query({"cursor": cursor, "limit": limit})
    return Request("GET", f"/v1/inboxes/{_seg(inbox_id)}/identity/sign-ins", params=params)
