import asyncio
import builtins
import json as _json
import os
import threading
from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Any, Literal, Optional, TypeVar, Union, cast

import httpx

from . import _consume
from . import _requests as r
from ._errors import APIConnectionError, error_for_status
from ._requests import (
    NOT_GIVEN,
    DraftStatuses,
    InboxIds,
    MetadataFilter,
    MetadataPatch,
    NotGiven,
    Nullable,
    NullableSendAt,
    NullableText,
    Recipients,
    Request,
    SendAt,
)
from ._signup import Signup, solve_signup_challenge
from ._stream import EventStream
from ._types import (
    Account,
    AckResult,
    AgentBundle,
    AgentCard,
    AgentCardInput,
    AgentCardVisibility,
    AgentKey,
    AgentKeyList,
    AttachmentInput,
    AttachmentText,
    BuiltinExtractionSchema,
    ClaimRequestResult,
    Contact,
    ContactWithThreads,
    DeliverabilitySummary,
    Direction,
    DirectoryReportReason,
    DirectoryReportResult,
    DirectoryVerifyResult,
    Domain,
    Draft,
    DraftKeep,
    DraftReply,
    DraftSendResult,
    EmergencyStopResult,
    EscalationSettings,
    ExtendResult,
    IdentityClient,
    IdentityClientType,
    IdentityClientWithSecret,
    IdentityScope,
    IdentitySignIn,
    IdentitySubjectType,
    IdentityToken,
    Inbox,
    InboxEscalation,
    InboxIdentity,
    KnowledgeDoc,
    KnowledgeListItem,
    KnowledgeSearchResults,
    LeaseClaim,
    ListDirection,
    ListEntries,
    ListEntry,
    ListKind,
    Message,
    MessageChannel,
    MessageType,
    Metrics,
    MetricsBucket,
    NackResult,
    Page,
    PublicAgent,
    PublicAgentCard,
    PublicAgentKeys,
    PublicHandle,
    QuietHours,
    ResolvedAgent,
    ResumedInbox,
    SearchResult,
    SignupChallenge,
    SignupResult,
    StreamToken,
    StructuredExtraction,
    Thread,
    ThreadWithMessages,
    VerificationResult,
    Webhook,
    WebhookCatalogEntry,
    WebhookEventType,
    WebhookPayload,
    WebhookTestResult,
    WorkspaceHandle,
)
from ._types import (
    Identity as IdentityRecord,
)
from ._version import __version__

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_TIMEOUT",
    "Agentboxd",
    "AsyncAgentboxd",
]

DEFAULT_BASE_URL = "https://api.agentboxd.com"
DEFAULT_TIMEOUT = 30.0
DEFAULT_TEMPORARY_TTL = 900
"""Default lifetime (seconds) of a temporary inbox."""
WAIT_TIMEOUT_MARGIN = 10.0
"""Extra seconds added to the HTTP read timeout on long-poll (wait) requests."""

API_KEY_ENV_VARS = ("AGENTBOXD_API_KEY", "MAILROOM_API_KEY")
"""Environment variables read for the API key, in priority order (MAILROOM_* is the legacy name)."""
BASE_URL_ENV_VARS = ("AGENTBOXD_BASE_URL", "MAILROOM_URL")
"""Environment variables read for the base URL, in priority order (MAILROOM_* is the legacy name)."""


def _env(names: tuple[str, ...]) -> Optional[str]:
    """First non-blank value among the named environment variables."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def _retry_after(response: httpx.Response, details: Any) -> Optional[float]:
    """Seconds to wait: the ``Retry-After`` header, else ``details.retry_after_seconds``."""
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    value = details.get("retry_after_seconds") if isinstance(details, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _signup_base_url(base_url: Optional[str]) -> str:
    return (base_url or _env(BASE_URL_ENV_VARS) or DEFAULT_BASE_URL).rstrip("/")


def _public_kwargs(base_url: str, req: Request) -> dict[str, Any]:
    """A request without an API key (the public signup routes)."""
    headers = {"Accept": "application/json", "User-Agent": f"agentboxd-python/{__version__}"}
    kwargs: dict[str, Any] = {"method": req.method, "url": base_url + req.path, "headers": headers}
    if req.has_body:
        headers["Content-Type"] = "application/json"
        kwargs["content"] = _json.dumps(req.json).encode("utf-8")
    return kwargs


_SelfT = TypeVar("_SelfT", bound="_BaseClient")


class _BaseClient:
    def __init__(self, api_key: Optional[str], base_url: Optional[str], timeout: float) -> None:
        key = api_key if api_key is not None else _env(API_KEY_ENV_VARS)
        if not key:
            raise ValueError(
                "No API key: pass api_key=... or set the AGENTBOXD_API_KEY environment variable."
            )
        self.api_key = key
        self.base_url = (base_url or _env(BASE_URL_ENV_VARS) or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout

    def _build(self, req: Request) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": f"agentboxd-python/{__version__}",
        }
        kwargs: dict[str, Any] = {"method": req.method, "url": self.base_url + req.path, "headers": headers}
        if req.params:
            kwargs["params"] = req.params
        if req.has_body:
            headers["Content-Type"] = "application/json"
            kwargs["content"] = _json.dumps(req.json).encode("utf-8")
        if req.idempotency_key:
            headers["Idempotency-Key"] = req.idempotency_key
        if req.wait_seconds is not None:
            kwargs["timeout"] = httpx.Timeout(self.timeout, read=req.wait_seconds + WAIT_TIMEOUT_MARGIN)
        return kwargs

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        if response.status_code == 204:
            return None
        try:
            payload: Any = response.json() if response.content else {}
        except ValueError:
            payload = {}
        if not response.is_success:
            err = payload.get("error") if isinstance(payload, dict) else None
            err = err if isinstance(err, dict) else {}
            code = err.get("code")
            message = err.get("message")
            details = err.get("details")
            raise error_for_status(
                response.status_code,
                code if isinstance(code, str) else None,
                message if isinstance(message, str) else (response.reason_phrase or None),
                details,
                _retry_after(response, details),
            )
        return payload


# =====================================================================
# sync
# =====================================================================


class Inboxes:
    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def create(
        self,
        *,
        username: Optional[str] = None,
        display_name: Optional[str] = None,
        client_id: Optional[str] = None,
        metadata: Optional[MetadataPatch] = None,
        domain: Optional[str] = None,
        card: Optional[AgentCardInput] = None,
    ) -> Inbox:
        """Create an inbox. Idempotent on ``client_id`` (returns the existing inbox).

        ``domain``: a verified custom domain of the workspace (default: the server's agent domain).
        ``card``: also create its agent card (needs ``directory:write``); the response then has ``card``."""
        req = r.inbox_create(username, display_name, client_id, metadata, domain, card=card)
        return cast(Inbox, self._c._send(req))

    def create_temporary(
        self,
        *,
        ttl_seconds: int = DEFAULT_TEMPORARY_TTL,
        display_name: Optional[str] = None,
        metadata: Optional[MetadataPatch] = None,
    ) -> Inbox:
        """Create a temporary, receive-only inbox (random address on the temporary domain).

        It and all its mail are wiped at ``expires_at``; ``ttl_seconds`` is 60 to 86400."""
        req = r.inbox_create(None, display_name, None, metadata, None, ttl_seconds)
        return cast(Inbox, self._c._send(req))

    def list(
        self,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        metadata: Optional[MetadataFilter] = None,
        include_temporary: Optional[bool] = None,
        temporary: Optional[bool] = None,
    ) -> Page[Inbox]:
        """List inboxes, newest first. ``metadata`` filters by exact value, e.g. ``{"team": "billing"}``.

        Temporary inboxes are excluded unless ``include_temporary=True``;
        ``temporary=True`` lists only them."""
        req = r.inbox_list(cursor, limit, metadata, include_temporary, temporary)
        return cast("Page[Inbox]", self._c._send(req))

    def get(self, inbox_id: str) -> Inbox:
        return cast(Inbox, self._c._send(r.inbox_get(inbox_id)))

    def update(
        self,
        inbox_id: str,
        *,
        display_name: Nullable = NOT_GIVEN,
        metadata: Optional[MetadataPatch] = None,
        ttl_seconds: Optional[int] = None,
    ) -> Inbox:
        """Change the display name (``None`` clears it) or metadata (merged; ``None`` deletes a key).

        ``ttl_seconds`` extends a temporary inbox from now (at most 24 h after its creation)."""
        return cast(Inbox, self._c._send(r.inbox_update(inbox_id, display_name, metadata, ttl_seconds)))

    def delete(self, inbox_id: str) -> None:
        """Soft-delete an inbox (its address is never reused). A temporary inbox is wiped at once."""
        self._c._send(r.inbox_delete(inbox_id))

    def pause(self, inbox_id: str, *, reason: Optional[str] = None) -> Inbox:
        """Kill switch: every send from the inbox is refused (423 ``inbox_paused``) until ``resume``.

        Inbound mail is still stored; its events and AI categorisation are held until then."""
        return cast(Inbox, self._c._send(r.inbox_pause(inbox_id, reason)))

    def resume(self, inbox_id: str) -> ResumedInbox:
        """Sending works again; held inbound events are emitted in arrival order (``released_events``)."""
        return cast(ResumedInbox, self._c._send(r.inbox_resume(inbox_id)))

    def consume(
        self,
        inbox_id: str,
        handler: "_consume.SyncHandler",
        *,
        concurrency: int = 1,
        lease_seconds: int = _consume.DEFAULT_LEASE_SECONDS,
        wait: float = _consume.DEFAULT_WAIT,
        consumer: Optional[str] = None,
        enriched: Optional[bool] = None,
        stop: "Optional[threading.Event]" = None,
        retry_delay_seconds: float = 5,
        max_retry_delay_seconds: float = 300,
        paused_poll_seconds: float = 10,
        on_error: "Optional[_consume.ErrorHandler]" = None,
    ) -> None:
        """Crash-safe consumer loop over the claim/ack queue.

        Claims messages and calls ``handler(message)`` (or ``handler(message, ctx)``) for each, up to
        ``concurrency`` at once in threads. The lease is extended while the handler runs; the message
        is acked when it returns and nacked with backoff (``retry_delay_seconds`` doubling per
        delivery, capped) when it raises. Delivery is at-least-once: make the handler idempotent.
        Runs until ``stop`` (a ``threading.Event``) is set; running handlers finish first."""
        _consume.consume_sync(
            self._c.messages,
            inbox_id,
            handler,
            _consume.ConsumeOptions(
                concurrency=concurrency,
                lease_seconds=lease_seconds,
                wait=wait,
                consumer=consumer,
                enriched=enriched,
                retry_delay_seconds=retry_delay_seconds,
                max_retry_delay_seconds=max_retry_delay_seconds,
                paused_poll_seconds=paused_poll_seconds,
                on_error=on_error,
            ),
            stop,
        )


class Domains:
    """Custom domains: connect a domain you own, publish its ``records``, then ``verify``."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def create(self, domain: str, *, receiving: Optional[bool] = None) -> Domain:
        return cast(Domain, self._c._send(r.domain_create(domain, receiving)))

    def list(self) -> Page[Domain]:
        return cast("Page[Domain]", self._c._send(r.domain_list()))

    def get(self, domain_id: str) -> Domain:
        return cast(Domain, self._c._send(r.domain_get(domain_id)))

    def verify(self, domain_id: str) -> Domain:
        """Check the DNS records now (at most once per 10 s per domain)."""
        return cast(Domain, self._c._send(r.domain_verify(domain_id)))

    def update(self, domain_id: str, *, receiving: Optional[bool] = None) -> Domain:
        return cast(Domain, self._c._send(r.domain_update(domain_id, receiving)))

    def delete(self, domain_id: str, *, force: bool = False) -> None:
        """409 ``domain_in_use`` while live inboxes use it, unless ``force`` (which deletes those inboxes)."""
        self._c._send(r.domain_delete(domain_id, force))

    def rotate_dkim(self, domain_id: str) -> Domain:
        """Start a DKIM key rotation: a new key on the other selector (``dkim_next`` in ``records``).

        Publish it next to the current record; signing switches as soon as it is seen."""
        return cast(Domain, self._c._send(r.domain_dkim_rotate(domain_id)))

    def activate_dkim(self, domain_id: str) -> Domain:
        """Check DNS now and switch signing to the new key (409 ``dkim_record_not_found`` until published)."""
        return cast(Domain, self._c._send(r.domain_dkim_activate(domain_id)))


class Messages:
    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def send(
        self,
        inbox_id: str,
        to: Recipients,
        subject: str,
        text: Optional[str] = None,
        html: Optional[str] = None,
        cc: Optional[Recipients] = None,
        bcc: Optional[Recipients] = None,
        attachments: Optional[Sequence[AttachmentInput]] = None,
        labels: Optional[Sequence[str]] = None,
        idempotency_key: Optional[str] = None,
        data: Any = None,
        type: Optional[MessageType] = None,
        agent_signature: Optional[str] = None,
    ) -> Message:
        """Send from ``inbox_id``. Returns the message with ``status: "queued"``.

        ``data`` (a JSON object or list, at most 64 KB) and ``type`` (``message``, ``task``, ``event``) make
        it a structured agent message: Agentboxd recipients get it natively (``channel: "agent"``, see
        ``delivery``), everyone else by email with the data attached. ``text``, ``html`` or ``data`` is
        required.

        ``agent_signature`` (aSIM phase 2): an author signature made with the agent's own registered key
        (``agentboxd.identity.sign_agent_message``) over exactly what is sent; the message then goes out
        exactly as signed."""
        req = r.message_send(
            inbox_id,
            to,
            subject,
            text,
            html,
            cc,
            bcc,
            attachments,
            labels,
            idempotency_key,
            data,
            type,
            agent_signature,
        )
        return cast(Message, self._c._send(req))

    def reply(
        self,
        inbox_id: str,
        message_id: str,
        text: Optional[str] = None,
        html: Optional[str] = None,
        attachments: Optional[Sequence[AttachmentInput]] = None,
        reply_all: Optional[bool] = None,
        labels: Optional[Sequence[str]] = None,
        idempotency_key: Optional[str] = None,
        data: Any = None,
        type: Optional[MessageType] = None,
        agent_signature: Optional[str] = None,
    ) -> Message:
        """Reply in-thread (sets In-Reply-To/References and a ``Re:`` subject), optionally with ``data`` and
        ``type`` like :meth:`send`."""
        req = r.message_reply(
            inbox_id,
            message_id,
            text,
            html,
            attachments,
            reply_all,
            labels,
            idempotency_key,
            data,
            type,
            agent_signature,
        )
        return cast(Message, self._c._send(req))

    def list(
        self,
        inbox_id: str,
        labels: Optional[Sequence[str]] = None,
        is_read: Optional[bool] = None,
        direction: Optional[Direction] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        include_blocked: Optional[bool] = None,
        channel: Optional[MessageChannel] = None,
        type: Optional[MessageType] = None,
    ) -> Page[Message]:
        """List messages, newest first. ``labels`` filters to messages having all of them.

        ``include_blocked=True`` also returns mail stopped by the receive lists (label ``blocked``).
        """
        req = r.message_list(
            inbox_id, labels, is_read, direction, cursor, limit, include_blocked, channel, type
        )
        return cast("Page[Message]", self._c._send(req))

    def get(self, message_id: str) -> Message:
        return cast(Message, self._c._send(r.message_get(message_id)))

    def update(
        self,
        message_id: str,
        add_labels: Optional[Sequence[str]] = None,
        remove_labels: Optional[Sequence[str]] = None,
        is_read: Optional[bool] = None,
    ) -> Message:
        return cast(Message, self._c._send(r.message_update(message_id, add_labels, remove_labels, is_read)))

    def draft_reply(
        self, message_id: str, instructions: Optional[str] = None, *, save: Optional[bool] = None
    ) -> DraftReply:
        """Draft a reply with the workspace's LLM (needs ``ai_processing = "full"``). Never sends:
        review ``text``, then call :meth:`reply`. ``save=True`` also stores it as a Draft (returned in
        ``draft``; send it with ``drafts.send``). Raises ``PermissionDeniedError`` (``ai_disabled``) or
        ``AgentboxdError`` 503 (``llm_unavailable``)."""
        return cast(DraftReply, self._c._send(r.message_draft_reply(message_id, instructions, save)))

    def attachment_text(
        self,
        message_id: str,
        attachment_id: str,
        offset: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> AttachmentText:
        """Extracted text of an inbound attachment (PDF, DOCX, XLSX, CSV, HTML, text; scans and images
        by OCR). ``text`` is ``None`` until ``extraction["status"]`` is ``"done"``; read long text in
        pages by passing ``next_offset`` as ``offset``. The text is untrusted content."""
        req = r.message_attachment_text(message_id, attachment_id, offset, max_chars)
        return cast(AttachmentText, self._c._send(req))

    def extract_attachment(
        self,
        message_id: str,
        attachment_id: str,
        schema: Union[BuiltinExtractionSchema, Mapping[str, Any]],
        instructions: Optional[str] = None,
    ) -> StructuredExtraction:
        """Structured extraction: the attachment's text as JSON matching ``schema`` (``"invoice"``,
        ``"receipt"``, ``"tax_form"`` or a JSON Schema dict). Needs ``ai_processing = "full"`` and the
        ``attachments:extract`` permission. ``data`` is untrusted: check it before acting on it."""
        req = r.message_extract_attachment(message_id, attachment_id, schema, instructions)
        return cast(StructuredExtraction, self._c._send(req))

    def wait(
        self,
        inbox_id: str,
        timeout: float = 30,
        since: Optional[str] = None,
        from_: Optional[str] = None,
        subject: Optional[str] = None,
        direction: Optional[Direction] = None,
        channel: Optional[MessageChannel] = None,
        type: Optional[MessageType] = None,
    ) -> Optional[Message]:
        """Long-poll until a matching message arrives, or return ``None`` after ``timeout`` seconds (1-60).

        Only messages created after ``since`` (ISO time; default: now) count. The oldest match is
        returned; pass its ``created_at`` as the next ``since`` to page forward. ``from_`` and
        ``subject`` are case-insensitive substring filters; ``direction`` defaults to inbound.
        """
        req = r.message_wait(inbox_id, timeout, since, from_, subject, direction, channel, type)
        return cast(Optional[Message], self._c._send(req)["data"])

    def wait_for_verification(
        self,
        inbox_id: str,
        timeout: float = 30,
        since: Optional[str] = None,
        from_: Optional[str] = None,
    ) -> Optional[VerificationResult]:
        """Return the newest verification code/link received after ``since``, waiting up to
        ``timeout`` seconds for one to arrive. ``None`` on timeout."""
        req = r.message_wait_for_verification(inbox_id, timeout, since, from_)
        return cast(Optional[VerificationResult], self._c._send(req)["data"])

    def claim(
        self,
        inbox_id: str,
        *,
        limit: Optional[int] = None,
        lease_seconds: Optional[int] = None,
        consumer: Optional[str] = None,
        wait: Optional[float] = None,
        enriched: Optional[bool] = None,
        since: Optional[str] = None,
        type: Optional[MessageType] = None,
        channel: Optional[MessageChannel] = None,
    ) -> LeaseClaim:
        """Claim/ack queue: lease up to ``limit`` (1-50, default 10) inbound messages, oldest first.

        Each is hidden from other claims for ``lease_seconds`` (30-3600, default 300); ``ack`` it when
        the work is done, or it comes back (at-least-once). ``wait`` long-polls up to 30 s. The first
        claim starts the queue: older mail is not claimable unless you pass ``since``. A paused inbox
        returns ``{"data": [], "paused": True}``. ``enriched=True`` waits for AI categorisation."""
        req = r.message_claim(inbox_id, limit, lease_seconds, consumer, wait, enriched, since, type, channel)
        return cast(LeaseClaim, self._c._send(req))

    def ack(self, message_id: str, lease_id: str, *, mark_read: Optional[bool] = None) -> AckResult:
        """Done: never claimed again. Idempotent. ``AgentboxdError`` 409 ``lease_expired`` if the lease is
        no longer current; ``{"gone": True}`` if the message was deleted meanwhile."""
        return cast(AckResult, self._c._send(r.message_ack(message_id, lease_id, mark_read)))

    def nack(self, message_id: str, lease_id: str, *, delay_seconds: Optional[int] = None) -> NackResult:
        """Give the message back now, or after ``delay_seconds`` (0-3600). The 10th delivery nacked is
        dead-lettered (label ``queue:dead-letter``)."""
        return cast(NackResult, self._c._send(r.message_nack(message_id, lease_id, delay_seconds)))

    def extend(self, message_id: str, lease_id: str, *, lease_seconds: Optional[int] = None) -> ExtendResult:
        """Heartbeat: the lease then runs until now + ``lease_seconds`` (30-3600, default 300)."""
        return cast(ExtendResult, self._c._send(r.message_extend(message_id, lease_id, lease_seconds)))


class Drafts:
    """Drafts: store an email for review, edit it, then ``send`` it now or ``schedule`` it.

    Sending goes through every check a normal send does (allow/block lists, suppressions, plan quota,
    daily caps, the 5-minute burst limit). Permissions: ``drafts:read`` / ``drafts:write``; ``send`` and
    ``schedule`` also need ``messages:send``.
    """

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def create(
        self,
        inbox_id: str,
        *,
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
    ) -> Draft:
        """Create a draft (nothing is sent). Everything is optional until it is sent.

        ``reply_to_message_id`` (or ``thread_id``) makes it a reply: recipients, ``Re:`` subject and
        threading are filled in. ``send_at`` (1 minute to 30 days ahead) schedules it."""
        req = r.draft_create(
            inbox_id,
            to,
            subject,
            text,
            html,
            cc,
            bcc,
            attachments,
            labels,
            metadata,
            reply_to_message_id,
            thread_id,
            reply_all,
            send_at,
            idempotency_key,
            data,
            type,
        )
        return cast(Draft, self._c._send(req))

    def list(
        self,
        inbox_id: str,
        *,
        status: Optional[DraftStatuses] = None,
        thread_id: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Page[Draft]:
        """Drafts of one inbox, newest first. ``status``: one or several (``["draft", "scheduled"]``)."""
        return cast("Page[Draft]", self._c._send(r.draft_list(inbox_id, status, thread_id, cursor, limit)))

    def list_all(
        self,
        *,
        inbox_id: Optional[str] = None,
        status: Optional[DraftStatuses] = None,
        thread_id: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Page[Draft]:
        """Drafts of every inbox of the workspace (``GET /v1/drafts``), optionally filtered."""
        req = r.draft_list_all(inbox_id, status, thread_id, cursor, limit)
        return cast("Page[Draft]", self._c._send(req))

    def get(self, inbox_id: str, draft_id: str) -> Draft:
        return cast(Draft, self._c._send(r.draft_get(inbox_id, draft_id)))

    def update(
        self,
        inbox_id: str,
        draft_id: str,
        *,
        to: Optional[Recipients] = None,
        subject: NullableText = NOT_GIVEN,
        text: NullableText = NOT_GIVEN,
        html: NullableText = NOT_GIVEN,
        cc: Optional[Recipients] = None,
        bcc: Optional[Recipients] = None,
        attachments: Optional[Sequence[Union[AttachmentInput, DraftKeep]]] = None,
        labels: Optional[Sequence[str]] = None,
        metadata: Optional[MetadataPatch] = None,
        send_at: NullableSendAt = NOT_GIVEN,
        data: Any = NOT_GIVEN,
        type: Optional[MessageType] = None,
    ) -> Draft:
        """Edit a ``draft`` or ``scheduled`` draft (else ``409 draft_not_editable``).

        ``subject``/``text``/``html=None`` clear them; ``attachments`` replaces the list (``{"id": ...}``
        keeps one already on the draft); ``send_at`` reschedules and ``send_at=None`` unschedules."""
        req = r.draft_update(
            inbox_id,
            draft_id,
            to,
            subject,
            text,
            html,
            cc,
            bcc,
            attachments,
            labels,
            metadata,
            send_at,
            data,
            type,
        )
        return cast(Draft, self._c._send(req))

    def delete(self, inbox_id: str, draft_id: str) -> None:
        self._c._send(r.draft_delete(inbox_id, draft_id))

    def send(self, inbox_id: str, draft_id: str, *, idempotency_key: Optional[str] = None) -> DraftSendResult:
        """Send now. A refused send raises the API error and leaves the draft as it was (``error`` set)."""
        return cast(DraftSendResult, self._c._send(r.draft_send(inbox_id, draft_id, idempotency_key)))

    def schedule(self, inbox_id: str, draft_id: str, send_at: SendAt) -> Draft:
        """Send automatically at ``send_at`` (1 minute to 30 days ahead; ``400 invalid_send_at``)."""
        return cast(Draft, self._c._send(r.draft_schedule(inbox_id, draft_id, send_at)))

    def cancel(self, inbox_id: str, draft_id: str) -> Draft:
        """Cancel a draft or its scheduled send (terminal)."""
        return cast(Draft, self._c._send(r.draft_cancel(inbox_id, draft_id)))


class Threads:
    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def list(self, inbox_id: str, cursor: Optional[str] = None, limit: Optional[int] = None) -> Page[Thread]:
        return cast("Page[Thread]", self._c._send(r.thread_list(inbox_id, cursor, limit)))

    def get(self, thread_id: str) -> ThreadWithMessages:
        """A thread plus its messages in order."""
        return cast(ThreadWithMessages, self._c._send(r.thread_get(thread_id)))

    def update(
        self,
        thread_id: str,
        metadata: Optional[MetadataPatch] = None,
        add_labels: Optional[Sequence[str]] = None,
        remove_labels: Optional[Sequence[str]] = None,
    ) -> Thread:
        """Set thread labels and metadata (merged: a ``None`` value deletes a key). Returns the thread."""
        return cast(Thread, self._c._send(r.thread_update(thread_id, metadata, add_labels, remove_labels)))


class Webhooks:
    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def create(
        self,
        url: str,
        events: Optional[Sequence[WebhookEventType]] = None,
        inbox_ids: InboxIds = NOT_GIVEN,
        secret: Optional[str] = None,
        payload: Optional[WebhookPayload] = None,
    ) -> Webhook:
        """Create a webhook. The returned ``secret`` is only shown here: store it.

        ``payload="envelope"`` sends ids, addresses, subject and labels only (no bodies).
        """
        return cast(Webhook, self._c._send(r.webhook_create(url, events, inbox_ids, secret, payload)))

    def list(self) -> Page[Webhook]:
        return cast("Page[Webhook]", self._c._send(r.webhook_list()))

    def get(self, webhook_id: str) -> Webhook:
        return cast(Webhook, self._c._send(r.webhook_get(webhook_id)))

    def update(
        self,
        webhook_id: str,
        url: Optional[str] = None,
        events: Optional[Sequence[WebhookEventType]] = None,
        inbox_ids: InboxIds = NOT_GIVEN,
        enabled: Optional[bool] = None,
        payload: Optional[WebhookPayload] = None,
    ) -> Webhook:
        """Update a webhook. Pass ``inbox_ids=None`` explicitly to subscribe to all inboxes."""
        req = r.webhook_update(webhook_id, url, events, inbox_ids, enabled, payload)
        return cast(Webhook, self._c._send(req))

    def delete(self, webhook_id: str) -> None:
        self._c._send(r.webhook_delete(webhook_id))

    def test(self, webhook_id: str) -> WebhookTestResult:
        """Send a ``webhook.test`` event."""
        return cast(WebhookTestResult, self._c._send(r.webhook_test(webhook_id)))

    def events(self) -> builtins.list[WebhookCatalogEntry]:
        """The event catalog: every event type with a description and example bodies."""
        return cast("builtins.list[WebhookCatalogEntry]", self._c._send(r.webhook_events())["data"])


class Lists:
    """Allow/block lists for receiving, sending and replying (permission ``lists:manage``)."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def list(
        self,
        inbox_id: Optional[str] = None,
        direction: Optional[ListDirection] = None,
        kind: Optional[ListKind] = None,
    ) -> ListEntries:
        return cast(ListEntries, self._c._send(r.list_entries(inbox_id, direction, kind)))

    def create(
        self, direction: ListDirection, kind: ListKind, pattern: str, inbox_id: Optional[str] = None
    ) -> ListEntry:
        """Add ``a@b.com`` or a domain (``b.com``, subdomains included). No ``inbox_id`` = workspace-wide."""
        return cast(ListEntry, self._c._send(r.list_create(direction, kind, pattern, inbox_id)))

    def delete(self, entry_id: str) -> None:
        self._c._send(r.list_delete(entry_id))


class Contacts:
    """Contacts: external addresses the workspace has exchanged mail with (created automatically)."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def list(
        self,
        q: Optional[str] = None,
        label: Optional[str] = None,
        metadata: Optional[MetadataFilter] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Page[Contact]:
        """Newest activity first. ``q`` matches address/name; ``metadata`` filters by exact value."""
        req = r.contact_list(q, label, metadata, cursor, limit)
        return cast("Page[Contact]", self._c._send(req))

    def get(self, contact_id: str) -> ContactWithThreads:
        """A contact plus its 10 most recent threads."""
        return cast(ContactWithThreads, self._c._send(r.contact_get(contact_id)))

    def by_address(self, address: str) -> ContactWithThreads:
        """Look a contact up by address. ``NotFoundError`` if the workspace never exchanged mail with it."""
        return cast(ContactWithThreads, self._c._send(r.contact_by_address(address)))

    def update(
        self,
        contact_id: str,
        name: Nullable = NOT_GIVEN,
        notes: Nullable = NOT_GIVEN,
        metadata: Optional[MetadataPatch] = None,
        add_labels: Optional[Sequence[str]] = None,
        remove_labels: Optional[Sequence[str]] = None,
    ) -> Contact:
        """Update notes (up to 10,000 chars; ``None`` clears), name, labels or metadata.

        Metadata is merged: given keys are set, a ``None`` value deletes the key.
        """
        req = r.contact_update(contact_id, name, notes, metadata, add_labels, remove_labels)
        return cast(Contact, self._c._send(req))


class Knowledge:
    """Knowledge documents used as context for reply drafts (per inbox, or workspace-wide)."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def list(
        self, inbox_id: Optional[str] = None, cursor: Optional[str] = None, limit: Optional[int] = None
    ) -> Page[KnowledgeListItem]:
        """Documents without bodies (each has an ``excerpt``). ``inbox_id``: one inbox's documents."""
        return cast("Page[KnowledgeListItem]", self._c._send(r.knowledge_list(inbox_id, cursor, limit)))

    def create(self, title: str, body: str, inbox_id: Optional[str] = None) -> KnowledgeDoc:
        """Create a document. Without ``inbox_id`` it applies to every inbox of the workspace."""
        return cast(KnowledgeDoc, self._c._send(r.knowledge_create(title, body, inbox_id)))

    def get(self, doc_id: str) -> KnowledgeDoc:
        return cast(KnowledgeDoc, self._c._send(r.knowledge_get(doc_id)))

    def update(
        self,
        doc_id: str,
        title: Optional[str] = None,
        body: Optional[str] = None,
        inbox_id: Nullable = NOT_GIVEN,
    ) -> KnowledgeDoc:
        """Update a document. Pass ``inbox_id=None`` explicitly to make it workspace-wide."""
        return cast(KnowledgeDoc, self._c._send(r.knowledge_update(doc_id, title, body, inbox_id)))

    def delete(self, doc_id: str) -> None:
        self._c._send(r.knowledge_delete(doc_id))

    def search(
        self, q: str, inbox_id: Optional[str] = None, limit: Optional[int] = None
    ) -> KnowledgeSearchResults:
        """Ranked full-text search. With ``inbox_id``, workspace-wide documents are included too."""
        return cast(KnowledgeSearchResults, self._c._send(r.knowledge_search(q, inbox_id, limit)))


class IdentityClients:
    """Apps ("relying parties") the workspace registered for Sign in with Agentboxd (``identity:manage``)."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def list(self) -> Page[IdentityClient]:
        return cast("Page[IdentityClient]", self._c._send(r.identity_client_list()))

    def create(
        self,
        name: str,
        type: IdentityClientType,
        redirect_uris: Optional[Sequence[str]] = None,
        allowed_scopes: Optional[Sequence[IdentityScope]] = None,
        subject_type: Optional[IdentitySubjectType] = None,
        homepage_url: Optional[str] = None,
    ) -> IdentityClientWithSecret:
        """Register an app. ``client_secret`` (confidential clients) is only returned here: store it.

        ``redirect_uris`` is required for ``confidential``/``public`` clients, forbidden for ``verify_only``.
        """
        req = r.identity_client_create(name, type, redirect_uris, allowed_scopes, subject_type, homepage_url)
        return cast(IdentityClientWithSecret, self._c._send(req))

    def get(self, client_id: str) -> IdentityClient:
        """``client_id`` is the client's ``id`` (UUID)."""
        return cast(IdentityClient, self._c._send(r.identity_client_get(client_id)))

    def update(
        self,
        client_id: str,
        name: Optional[str] = None,
        redirect_uris: Optional[Sequence[str]] = None,
        allowed_scopes: Optional[Sequence[IdentityScope]] = None,
        homepage_url: Nullable = NOT_GIVEN,
        enabled: Optional[bool] = None,
    ) -> IdentityClient:
        """Pass ``homepage_url=None`` explicitly to clear it."""
        req = r.identity_client_update(client_id, name, redirect_uris, allowed_scopes, homepage_url, enabled)
        return cast(IdentityClient, self._c._send(req))

    def delete(self, client_id: str) -> None:
        """Permanent: the client's tokens stop being accepted at the token and userinfo endpoints."""
        self._c._send(r.identity_client_delete(client_id))

    def rotate_secret(self, client_id: str) -> IdentityClientWithSecret:
        """A new secret, shown once; the old one stops working."""
        return cast(IdentityClientWithSecret, self._c._send(r.identity_client_rotate_secret(client_id)))


class InboxIdentities:
    """The per-inbox Sign in with Agentboxd switch and sign-in history."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def get(self, inbox_id: str) -> InboxIdentity:
        return cast(InboxIdentity, self._c._send(r.inbox_identity_get(inbox_id)))

    def update(self, inbox_id: str, enabled: bool) -> InboxIdentity:
        """``enabled=False`` immediately refuses new tokens, sign-ins and userinfo (``identity:manage``)."""
        return cast(InboxIdentity, self._c._send(r.inbox_identity_update(inbox_id, enabled)))

    def sign_ins(
        self, inbox_id: str, cursor: Optional[str] = None, limit: Optional[int] = None
    ) -> Page[IdentitySignIn]:
        """Newest first."""
        return cast("Page[IdentitySignIn]", self._c._send(r.inbox_identity_sign_ins(inbox_id, cursor, limit)))


class Identities:
    """Identity-only agents: an Agentboxd identity without a mailbox (sign in to apps, no mail).

    They count toward the plan's ``identities`` limit, not ``inboxes``. Mint tokens with
    ``client.identity.token(identity_id=..., audience=...)``."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def create(
        self,
        *,
        username: Optional[str] = None,
        display_name: Optional[str] = None,
        client_id: Optional[str] = None,
        metadata: Optional[MetadataPatch] = None,
        card: Optional[AgentCardInput] = None,
    ) -> IdentityRecord:
        """Create an identity-only agent. Idempotent on ``client_id`` (returns the existing one).
        ``card``: also create its agent card (needs ``directory:write``)."""
        return cast(
            IdentityRecord,
            self._c._send(r.identity_create(username, display_name, client_id, metadata, card=card)),
        )

    def list(
        self,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        metadata: Optional[MetadataFilter] = None,
    ) -> "Page[IdentityRecord]":
        """Newest first. ``metadata`` filters by exact value, e.g. ``{"team": "research"}``."""
        return cast("Page[IdentityRecord]", self._c._send(r.identity_list(cursor, limit, metadata)))

    def get(self, identity_id: str) -> IdentityRecord:
        return cast(IdentityRecord, self._c._send(r.identity_get(identity_id)))

    def update(
        self,
        identity_id: str,
        *,
        display_name: Nullable = NOT_GIVEN,
        metadata: Optional[MetadataPatch] = None,
    ) -> IdentityRecord:
        """Change the display name (``None`` clears it) or metadata (merged; ``None`` deletes a key)."""
        return cast(IdentityRecord, self._c._send(r.identity_update(identity_id, display_name, metadata)))

    def delete(self, identity_id: str) -> None:
        """Soft delete: the handle is never reissued; tokens and sign-ins stop at once."""
        self._c._send(r.identity_delete(identity_id))

    def pause(self, identity_id: str, *, reason: Optional[str] = None) -> Inbox:
        """Kill switch: identity tokens, approvals and exchanges are refused until ``resume``."""
        return cast(Inbox, self._c._send(r.inbox_pause(identity_id, reason)))

    def resume(self, identity_id: str) -> ResumedInbox:
        return cast(ResumedInbox, self._c._send(r.inbox_resume(identity_id)))


class Identity:
    """Sign in with Agentboxd: the agent's identity (an inbox or an identity-only agent), OpenID Connect."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client
        self.clients = IdentityClients(client)
        self.inbox = InboxIdentities(client)

    def token(
        self,
        inbox_id: Optional[str] = None,
        audience: Optional[str] = None,
        nonce: Optional[str] = None,
        scope: Optional[Union[str, Sequence[IdentityScope]]] = None,
        expires_in: Optional[int] = None,
        *,
        identity_id: Optional[str] = None,
    ) -> IdentityToken:
        """Mint a short-lived (at most 5 minutes), single-use ID token for the relying party ``audience``
        (its ``client_id``). Needs the ``identity:sign`` permission. ``scope`` defaults to ``openid email``.

        Pass ``inbox_id`` for an inbox or ``identity_id`` for an identity-only agent (which never gets
        the ``email`` scope: it has no mailbox).
        """
        req = r.identity_token(inbox_id, audience, nonce, scope, expires_in, identity_id)
        return cast(IdentityToken, self._c._send(req))


def _card_body(
    name: Optional[str],
    description: Nullable,
    capabilities: Optional[Mapping[str, Any]],
    documentation_url: Nullable,
    visibility: Optional[str],
    routing: Optional[str],
    handle: Nullable = NOT_GIVEN,
    indexable: Optional[bool] = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if not isinstance(description, NotGiven):
        body["description"] = description
    if capabilities is not None:
        body["capabilities"] = dict(capabilities)
    if not isinstance(documentation_url, NotGiven):
        body["documentation_url"] = documentation_url
    if visibility is not None:
        body["visibility"] = visibility
    if routing is not None:
        body["routing"] = routing
    if not isinstance(handle, NotGiven):
        body["handle"] = handle
    if indexable is not None:
        body["indexable"] = indexable
    return body


def _escalation_body(
    contacts: Union[Sequence[str], NotGiven],
    triggers: Union[Mapping[str, bool], NotGiven],
    delivery: Union[str, NotGiven],
    max_per_hour: Union[int, NotGiven],
    quiet_hours: Union[QuietHours, NotGiven, None],
    include_excerpt: Union[bool, NotGiven],
) -> dict[str, Any]:
    return {
        "contacts": contacts if isinstance(contacts, NotGiven) else list(contacts),
        "triggers": triggers if isinstance(triggers, NotGiven) else dict(triggers),
        "delivery": delivery,
        "max_per_hour": max_per_hour,
        "quiet_hours": quiet_hours,
        "include_excerpt": include_excerpt,
    }


def _inbox_escalation_body(
    override: Union[bool, NotGiven],
    contacts: Union[Sequence[str], NotGiven],
    triggers: Union[Mapping[str, bool], NotGiven, None],
) -> dict[str, Any]:
    return {
        "override": override,
        "contacts": contacts if isinstance(contacts, NotGiven) else list(contacts),
        "triggers": triggers if triggers is None or isinstance(triggers, NotGiven) else dict(triggers),
    }


class Agents:
    """aSIM bundle and agent card of an inbox or identity-only agent (``inbox_id`` is either id).

    Reading needs ``inboxes:read``; changes need ``directory:write``. Inbox-scoped keys manage their own
    card."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client
        self.keys = AgentKeys(client)

    def get(self, inbox_id: str) -> AgentBundle:
        return cast(AgentBundle, self._c._send(r.agent_get(inbox_id)))

    def update(
        self,
        inbox_id: str,
        *,
        name: Optional[str] = None,
        description: Nullable = NOT_GIVEN,
        capabilities: Optional[Mapping[str, Any]] = None,
        documentation_url: Nullable = NOT_GIVEN,
        visibility: Optional[AgentCardVisibility] = None,
        routing: Optional[Literal["relay", "direct_preferred"]] = None,
        handle: Nullable = NOT_GIVEN,
        indexable: Optional[bool] = None,
    ) -> AgentBundle:
        """Create the card (private by default) or update it.

        ``None`` for ``description`` / ``documentation_url`` / ``handle`` clears them. ``visibility="public"``
        lists the agent in the public directory (claimed workspace, org-scoped key, plan limit
        ``public_listings``); ``indexable=True`` lets search engines index its public page; ``handle`` is the
        agent part of ``@workspace/agent``."""
        body = _card_body(
            name, description, capabilities, documentation_url, visibility, routing, handle, indexable
        )
        return cast(AgentBundle, self._c._send(r.agent_update(inbox_id, body)))

    def delete(self, inbox_id: str) -> None:
        """Delete the card: the agent leaves the directory at once. The inbox is unchanged."""
        self._c._send(r.agent_delete(inbox_id))

    def revoke(self, inbox_id: str, *, reason: Optional[str] = None) -> AgentBundle:
        """The agent stops signing; directory verify answers ``revoked``. Mail keeps flowing."""
        return cast(AgentBundle, self._c._send(r.agent_revoke(inbox_id, reason)))

    def restore(self, inbox_id: str) -> AgentBundle:
        """Undo a revoke (not an operator suspension: 403 ``agent_suspended``)."""
        return cast(AgentBundle, self._c._send(r.agent_restore(inbox_id)))

    def oasf(self, inbox_id: str) -> dict[str, Any]:
        """The card as an OASF record (``GET /v1/inboxes/:id/agent/oasf``)."""
        return cast(dict[str, Any], self._c._send(r.agent_oasf(inbox_id)))


class AgentKeys:
    """Agent-held signing keys (aSIM phase 2): list needs ``inboxes:read``, changes ``identity:manage``.

    The private key never leaves the agent: generate it with ``agentboxd.identity.generate_agent_key`` and
    register the public key with a proof (``agentboxd.identity.create_key_proof``)."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def list(self, inbox_id: str) -> AgentKeyList:
        return cast(AgentKeyList, self._c._send(r.agent_keys_list(inbox_id)))

    def register(self, inbox_id: str, *, public_jwk: Mapping[str, Any], proof: str) -> AgentKey:
        """Register a public key (Ed25519 or P-256) with its proof of possession. At most 3 active."""
        return cast(AgentKey, self._c._send(r.agent_keys_register(inbox_id, public_jwk, proof)))

    def retire(self, inbox_id: str, kid: str) -> AgentKey:
        """Rotation: no new signatures with it; old ones stay valid."""
        return cast(AgentKey, self._c._send(r.agent_keys_retire(inbox_id, kid)))

    def revoke(
        self, inbox_id: str, kid: str, *, reason: Optional[str] = None, since: Optional[str] = None
    ) -> AgentKey:
        """Compromise: signatures made at or after ``since`` (ISO time, default now) no longer verify."""
        return cast(AgentKey, self._c._send(r.agent_keys_revoke(inbox_id, kid, reason, since)))


class Directory:
    """The agent directory (permission ``directory:read``): resolve, verify, search, report. Rate limited; 503
    ``directory_disabled`` when the server hasn't enabled it."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def resolve(self, address: Optional[str] = None, *, handle: Optional[str] = None) -> ResolvedAgent:
        """Your workspace sees the full card, a publicly listed card is public for everyone, others see the
        minimal card. Pass an ``address`` or a ``handle`` (``@acme/billing``). 404 ``agent_not_found`` on a
        miss."""
        return cast(ResolvedAgent, self._c._send(r.directory_resolve(address, handle)))

    def verify(
        self, *, signature: Optional[str] = None, address: Optional[str] = None
    ) -> DirectoryVerifyResult:
        """Pass a message's ``agent["signature"]`` (signature + sender's current status) or an ``address``."""
        return cast(DirectoryVerifyResult, self._c._send(r.directory_verify(signature, address)))

    def search(
        self,
        *,
        q: Optional[str] = None,
        capability: Optional[str] = None,
        type: Optional[MessageType] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        scope: Optional[Literal["workspace", "public"]] = None,
    ) -> "Page[AgentCard]":
        """Active cards with ``workspace`` visibility in your workspace, or with ``scope="public"`` the public
        directory (publicly listed cards of every workspace)."""
        req = r.directory_search(q, capability, type, limit, cursor, scope)
        return cast("Page[AgentCard]", self._c._send(req))

    def get_handle(self) -> WorkspaceHandle:
        """The workspace handle (``@acme``) and previous ones that still redirect."""
        return cast(WorkspaceHandle, self._c._send(r.directory_handle_get()))

    def set_handle(self, handle: str) -> WorkspaceHandle:
        """Claim or rename the workspace handle (org-scoped key; the old one redirects for 90 days)."""
        return cast(WorkspaceHandle, self._c._send(r.directory_handle_set(handle)))

    def release_handle(self) -> WorkspaceHandle:
        """Release the workspace handle. It can never be claimed again."""
        return cast(WorkspaceHandle, self._c._send(r.directory_handle_release()))

    def report(
        self,
        address: str,
        reason: DirectoryReportReason,
        *,
        details: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> DirectoryReportResult:
        """At most 10 per workspace per day; the agent's owner learns the reason, never who reported."""
        return cast(
            DirectoryReportResult, self._c._send(r.directory_report(address, reason, details, message_id))
        )


class PublicDirectory:
    """The public agent directory (``/v1/public/*``, aSIM phase 2): publicly listed agents, no permission
    needed. Rate limited per IP; 503 ``public_directory_disabled`` when the server hasn't enabled it."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def search(
        self,
        *,
        q: Optional[str] = None,
        capability: Optional[str] = None,
        type: Optional[MessageType] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> "Page[PublicAgentCard]":
        req = r.public_agents_search(q, capability, type, limit, cursor)
        return cast("Page[PublicAgentCard]", self._c._send(req))

    def get(self, address: str) -> PublicAgent:
        return cast(PublicAgent, self._c._send(r.public_agent(address)))

    def a2a_card(self, address: str) -> dict[str, Any]:
        """The A2A agent card (signed by Agentboxd when agent messaging is on)."""
        return cast(dict[str, Any], self._c._send(r.public_agent(address, "agent-card.json")))

    def oasf(self, address: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._c._send(r.public_agent(address, "oasf.json")))

    def keys(self, address: str) -> PublicAgentKeys:
        """The agent's own public keys, for ``agentboxd.identity.verify_author_signature``."""
        return cast(PublicAgentKeys, self._c._send(r.public_agent(address, "keys.json")))

    def handle(self, workspace: str, agent: str) -> PublicHandle:
        """``@workspace/agent`` → the agent (follows renames within their 90-day redirect)."""
        return cast(PublicHandle, self._c._send(r.public_handle(workspace, agent)))


class AccountApi:
    """The workspace behind the key (``GET /v1/account``) and claim requests for agent-created workspaces."""

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def get(self) -> Account:
        """Claim status, effective limits and (unclaimed workspaces) today's recipient count."""
        return cast(Account, self._c._send(r.account_get()))

    def request_claim(self, email: str) -> ClaimRequestResult:
        """Email ``email`` a single-use link to claim this agent-created workspace (at most 3 a day)."""
        return cast(ClaimRequestResult, self._c._send(r.signup_claim(email)))


class EscalationApi:
    """Human on call (permission ``escalation:manage``): who is emailed when an agent's mail needs a person.

    New contacts get a confirmation email and receive nothing until they confirm.
    """

    def __init__(self, client: "Agentboxd") -> None:
        self._c = client

    def get(self) -> EscalationSettings:
        """Workspace contacts, triggers, delivery (immediate or digest), hourly limit, quiet hours."""
        return cast(EscalationSettings, self._c._send(r.escalation_get()))

    def update(
        self,
        *,
        contacts: Union[Sequence[str], NotGiven] = NOT_GIVEN,
        triggers: Union[Mapping[str, bool], NotGiven] = NOT_GIVEN,
        delivery: Union[Literal["immediate", "digest"], NotGiven] = NOT_GIVEN,
        max_per_hour: Union[int, NotGiven] = NOT_GIVEN,
        quiet_hours: Union[QuietHours, NotGiven, None] = NOT_GIVEN,
        include_excerpt: Union[bool, NotGiven] = NOT_GIVEN,
    ) -> EscalationSettings:
        """Arguments left out keep their value; ``contacts`` (at most 5) replaces the list;
        ``quiet_hours=None`` removes the quiet hours."""
        req = r.escalation_update(
            _escalation_body(contacts, triggers, delivery, max_per_hour, quiet_hours, include_excerpt)
        )
        return cast(EscalationSettings, self._c._send(req))

    def get_inbox(self, inbox_id: str) -> InboxEscalation:
        """The inbox's override: its own contacts (and triggers) instead of the workspace's."""
        return cast(InboxEscalation, self._c._send(r.inbox_escalation_get(inbox_id)))

    def update_inbox(
        self,
        inbox_id: str,
        *,
        override: Union[bool, NotGiven] = NOT_GIVEN,
        contacts: Union[Sequence[str], NotGiven] = NOT_GIVEN,
        triggers: Union[Mapping[str, bool], NotGiven, None] = NOT_GIVEN,
    ) -> InboxEscalation:
        """``override=True`` sends this inbox's escalations to its own ``contacts``.

        ``triggers=None`` uses the workspace triggers."""
        req = r.inbox_escalation_update(inbox_id, _inbox_escalation_body(override, contacts, triggers))
        return cast(InboxEscalation, self._c._send(req))


class Agentboxd(_BaseClient):
    """Synchronous Agentboxd client.

    >>> mr = Agentboxd()  # reads AGENTBOXD_API_KEY / AGENTBOXD_BASE_URL
    >>> inbox = mr.inboxes.create(client_id="support-agent")
    >>> mr.messages.send(inbox["id"], to="someone@example.com", subject="Hi", text="Hello!")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout)
        self._owns_http = http_client is None
        self._http = http_client if http_client is not None else httpx.Client(timeout=timeout)
        self.inboxes = Inboxes(self)
        self.domains = Domains(self)
        self.messages = Messages(self)
        self.drafts = Drafts(self)
        self.threads = Threads(self)
        self.webhooks = Webhooks(self)
        self.contacts = Contacts(self)
        self.knowledge = Knowledge(self)
        self.lists = Lists(self)
        self.identity = Identity(self)
        self.identities = Identities(self)
        self.account = AccountApi(self)
        self.escalation = EscalationApi(self)
        self.agents = Agents(self)
        self.directory = Directory(self)
        self.public_directory = PublicDirectory(self)

    @classmethod
    def signup(
        cls,
        *,
        agent_name: Optional[str] = None,
        owner_email: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: Optional[httpx.Client] = None,
        max_iterations: int = 2**32,
        kind: Optional[str] = None,
    ) -> "Signup[Agentboxd]":
        """Agent self-signup, no API key needed.

        Fetches a proof-of-work challenge, solves it (a few seconds of CPU) and creates an unclaimed
        workspace with one inbox. Returns a ready client plus the API's answer; ``api_key`` is shown only
        once, so store it. Until a human claims the workspace (``owner_email`` here, or
        ``client.account.request_claim(email)`` later) sending is limited and webhooks are off.

        >>> s = Agentboxd.signup(agent_name="research-agent", owner_email="me@example.com")
        >>> s.api_key, s.inbox["address"]

        ``kind="identity"`` creates an identity-only agent (sign in to apps, no mailbox) instead of an
        inbox: ``s.identity`` is set and ``s.inbox`` is ``None``. It can mint identity tokens once a human
        has claimed the workspace.
        """
        url = _signup_base_url(base_url)
        http = http_client if http_client is not None else httpx.Client(timeout=timeout)
        try:
            try:
                ch = cast(
                    SignupChallenge, cls._parse(http.request(**_public_kwargs(url, r.signup_challenge())))
                )
                solution = solve_signup_challenge(ch["challenge"], int(ch["difficulty"]), max_iterations)
                req = r.signup_create(ch["challenge"], solution, agent_name, owner_email, kind)
                result = cast(SignupResult, cls._parse(http.request(**_public_kwargs(url, req))))
            except httpx.TimeoutException as exc:
                raise APIConnectionError(f"Request timed out: {exc}", code="timeout") from exc
            except httpx.TransportError as exc:
                raise APIConnectionError(f"Connection error: {exc}") from exc
        finally:
            if http_client is None:
                http.close()
        client = cls(api_key=result["api_key"], base_url=url, timeout=timeout, http_client=http_client)
        return Signup(client=client, result=result)

    def search(
        self,
        q: str,
        inbox_id: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        channel: Optional[MessageChannel] = None,
        type: Optional[MessageType] = None,
    ) -> Page[SearchResult]:
        """Full-text search (web-search syntax: ``"exact phrase"``, ``-exclude``, ``or``)."""
        return cast("Page[SearchResult]", self._send(r.search(q, inbox_id, cursor, limit, channel, type)))

    def metrics(
        self,
        from_: Optional[str] = None,
        to: Optional[str] = None,
        tz: Optional[str] = None,
        inbox_id: Optional[str] = None,
        bucket: Optional[MetricsBucket] = None,
    ) -> Metrics:
        """Sent/received/delivery counts bucketed in ``tz`` (IANA), a 30-day heatmap and resources.

        ``from_``/``to``: ISO timestamps or dates (default: the last 30 days, at most 90).
        """
        return cast(Metrics, self._send(r.metrics(from_, to, tz, inbox_id, bucket)))

    def emergency_stop(self, reason: Optional[str] = None) -> EmergencyStopResult:
        """Emergency stop (permission ``workspace:emergency``, workspace keys): every inbox and identity of
        the workspace stops sending (423 ``workspace_stopped``), minting identity tokens and sending
        scheduled drafts. Reads keep working. Only a workspace owner can resume, in the dashboard."""
        return cast(EmergencyStopResult, self._send(r.emergency_stop(reason)))

    def deliverability(self) -> DeliverabilitySummary:
        """Bounce and complaint rates (7 and 30 days), suppressed contacts, your domains' SPF/DKIM/DMARC
        and the shared IP's blocklist status (permission ``metrics:read``, workspace keys)."""
        return cast(DeliverabilitySummary, self._send(r.deliverability()))

    def stream_token(self) -> StreamToken:
        """A single-use, 60-second WebSocket URL for ``GET /v1/stream`` (any WebSocket client).

        For a ready-made client with reconnect and resume, use :meth:`AsyncAgentboxd.stream`.
        """
        return cast(StreamToken, self._send(r.stream_token()))

    def _send(self, req: Request) -> Any:
        try:
            response = self._http.request(**self._build(req))
        except httpx.TimeoutException as exc:
            raise APIConnectionError(f"Request timed out: {exc}", code="timeout") from exc
        except httpx.TransportError as exc:
            raise APIConnectionError(f"Connection error: {exc}") from exc
        return self._parse(response)

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self: _SelfT) -> _SelfT:
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()


# =====================================================================
# async
# =====================================================================


class AsyncInboxes:
    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def create(
        self,
        *,
        username: Optional[str] = None,
        display_name: Optional[str] = None,
        client_id: Optional[str] = None,
        metadata: Optional[MetadataPatch] = None,
        domain: Optional[str] = None,
        card: Optional[AgentCardInput] = None,
    ) -> Inbox:
        """Create an inbox. Idempotent on ``client_id`` (returns the existing inbox).

        ``domain``: a verified custom domain of the workspace (default: the server's agent domain).
        ``card``: also create its agent card (needs ``directory:write``); the response then has ``card``."""
        req = r.inbox_create(username, display_name, client_id, metadata, domain, card=card)
        return cast(Inbox, await self._c._send(req))

    async def create_temporary(
        self,
        *,
        ttl_seconds: int = DEFAULT_TEMPORARY_TTL,
        display_name: Optional[str] = None,
        metadata: Optional[MetadataPatch] = None,
    ) -> Inbox:
        """Create a temporary, receive-only inbox (random address on the temporary domain).

        It and all its mail are wiped at ``expires_at``; ``ttl_seconds`` is 60 to 86400."""
        req = r.inbox_create(None, display_name, None, metadata, None, ttl_seconds)
        return cast(Inbox, await self._c._send(req))

    async def list(
        self,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        metadata: Optional[MetadataFilter] = None,
        include_temporary: Optional[bool] = None,
        temporary: Optional[bool] = None,
    ) -> Page[Inbox]:
        """List inboxes, newest first. ``metadata`` filters by exact value, e.g. ``{"team": "billing"}``.

        Temporary inboxes are excluded unless ``include_temporary=True``;
        ``temporary=True`` lists only them."""
        req = r.inbox_list(cursor, limit, metadata, include_temporary, temporary)
        return cast("Page[Inbox]", await self._c._send(req))

    async def get(self, inbox_id: str) -> Inbox:
        return cast(Inbox, await self._c._send(r.inbox_get(inbox_id)))

    async def update(
        self,
        inbox_id: str,
        *,
        display_name: Nullable = NOT_GIVEN,
        metadata: Optional[MetadataPatch] = None,
        ttl_seconds: Optional[int] = None,
    ) -> Inbox:
        """Change the display name (``None`` clears it) or metadata (merged; ``None`` deletes a key).

        ``ttl_seconds`` extends a temporary inbox from now (at most 24 h after its creation)."""
        return cast(Inbox, await self._c._send(r.inbox_update(inbox_id, display_name, metadata, ttl_seconds)))

    async def delete(self, inbox_id: str) -> None:
        """Soft-delete an inbox (its address is never reused). A temporary inbox is wiped at once."""
        await self._c._send(r.inbox_delete(inbox_id))

    async def pause(self, inbox_id: str, *, reason: Optional[str] = None) -> Inbox:
        """Kill switch: every send from the inbox is refused (423 ``inbox_paused``) until ``resume``.

        Inbound mail is still stored; its events and AI categorisation are held until then."""
        return cast(Inbox, await self._c._send(r.inbox_pause(inbox_id, reason)))

    async def resume(self, inbox_id: str) -> ResumedInbox:
        """Sending works again; held inbound events are emitted in arrival order (``released_events``)."""
        return cast(ResumedInbox, await self._c._send(r.inbox_resume(inbox_id)))

    async def consume(
        self,
        inbox_id: str,
        handler: "_consume.AsyncHandler",
        *,
        concurrency: int = 1,
        lease_seconds: int = _consume.DEFAULT_LEASE_SECONDS,
        wait: float = _consume.DEFAULT_WAIT,
        consumer: Optional[str] = None,
        enriched: Optional[bool] = None,
        stop: "Optional[asyncio.Event]" = None,
        retry_delay_seconds: float = 5,
        max_retry_delay_seconds: float = 300,
        paused_poll_seconds: float = 10,
        on_error: "Optional[_consume.ErrorHandler]" = None,
    ) -> None:
        """Crash-safe consumer loop over the claim/ack queue (async handler). See :meth:`Inboxes.consume`.

        Runs until ``stop`` (an ``asyncio.Event``) is set; running handlers finish first."""
        await _consume.consume_async(
            self._c.messages,
            inbox_id,
            handler,
            _consume.ConsumeOptions(
                concurrency=concurrency,
                lease_seconds=lease_seconds,
                wait=wait,
                consumer=consumer,
                enriched=enriched,
                retry_delay_seconds=retry_delay_seconds,
                max_retry_delay_seconds=max_retry_delay_seconds,
                paused_poll_seconds=paused_poll_seconds,
                on_error=on_error,
            ),
            stop,
        )


class AsyncDomains:
    """Custom domains: connect a domain you own, publish its ``records``, then ``verify``."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def create(self, domain: str, *, receiving: Optional[bool] = None) -> Domain:
        return cast(Domain, await self._c._send(r.domain_create(domain, receiving)))

    async def list(self) -> Page[Domain]:
        return cast("Page[Domain]", await self._c._send(r.domain_list()))

    async def get(self, domain_id: str) -> Domain:
        return cast(Domain, await self._c._send(r.domain_get(domain_id)))

    async def verify(self, domain_id: str) -> Domain:
        """Check the DNS records now (at most once per 10 s per domain)."""
        return cast(Domain, await self._c._send(r.domain_verify(domain_id)))

    async def update(self, domain_id: str, *, receiving: Optional[bool] = None) -> Domain:
        return cast(Domain, await self._c._send(r.domain_update(domain_id, receiving)))

    async def delete(self, domain_id: str, *, force: bool = False) -> None:
        """409 ``domain_in_use`` while live inboxes use it, unless ``force`` (which deletes those inboxes)."""
        await self._c._send(r.domain_delete(domain_id, force))

    async def rotate_dkim(self, domain_id: str) -> Domain:
        """Start a DKIM key rotation: a new key on the other selector (``dkim_next`` in ``records``).

        Publish it next to the current record; signing switches as soon as it is seen."""
        return cast(Domain, await self._c._send(r.domain_dkim_rotate(domain_id)))

    async def activate_dkim(self, domain_id: str) -> Domain:
        """Check DNS now and switch signing to the new key (409 ``dkim_record_not_found`` until published)."""
        return cast(Domain, await self._c._send(r.domain_dkim_activate(domain_id)))


class AsyncMessages:
    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def send(
        self,
        inbox_id: str,
        to: Recipients,
        subject: str,
        text: Optional[str] = None,
        html: Optional[str] = None,
        cc: Optional[Recipients] = None,
        bcc: Optional[Recipients] = None,
        attachments: Optional[Sequence[AttachmentInput]] = None,
        labels: Optional[Sequence[str]] = None,
        idempotency_key: Optional[str] = None,
        data: Any = None,
        type: Optional[MessageType] = None,
        agent_signature: Optional[str] = None,
    ) -> Message:
        """Send from ``inbox_id``. Returns the message with ``status: "queued"``.

        ``data`` (a JSON object or list, at most 64 KB) and ``type`` (``message``, ``task``, ``event``) make
        it a structured agent message: Agentboxd recipients get it natively (``channel: "agent"``, see
        ``delivery``), everyone else by email with the data attached. ``text``, ``html`` or ``data`` is
        required."""
        req = r.message_send(
            inbox_id,
            to,
            subject,
            text,
            html,
            cc,
            bcc,
            attachments,
            labels,
            idempotency_key,
            data,
            type,
            agent_signature,
        )
        return cast(Message, await self._c._send(req))

    async def reply(
        self,
        inbox_id: str,
        message_id: str,
        text: Optional[str] = None,
        html: Optional[str] = None,
        attachments: Optional[Sequence[AttachmentInput]] = None,
        reply_all: Optional[bool] = None,
        labels: Optional[Sequence[str]] = None,
        idempotency_key: Optional[str] = None,
        data: Any = None,
        type: Optional[MessageType] = None,
        agent_signature: Optional[str] = None,
    ) -> Message:
        """Reply in-thread (sets In-Reply-To/References and a ``Re:`` subject), optionally with ``data`` and
        ``type`` like :meth:`send`."""
        req = r.message_reply(
            inbox_id,
            message_id,
            text,
            html,
            attachments,
            reply_all,
            labels,
            idempotency_key,
            data,
            type,
            agent_signature,
        )
        return cast(Message, await self._c._send(req))

    async def list(
        self,
        inbox_id: str,
        labels: Optional[Sequence[str]] = None,
        is_read: Optional[bool] = None,
        direction: Optional[Direction] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        include_blocked: Optional[bool] = None,
        channel: Optional[MessageChannel] = None,
        type: Optional[MessageType] = None,
    ) -> Page[Message]:
        """List messages, newest first. ``labels`` filters to messages having all of them.

        ``include_blocked=True`` also returns mail stopped by the receive lists (label ``blocked``).
        """
        req = r.message_list(
            inbox_id, labels, is_read, direction, cursor, limit, include_blocked, channel, type
        )
        return cast("Page[Message]", await self._c._send(req))

    async def get(self, message_id: str) -> Message:
        return cast(Message, await self._c._send(r.message_get(message_id)))

    async def update(
        self,
        message_id: str,
        add_labels: Optional[Sequence[str]] = None,
        remove_labels: Optional[Sequence[str]] = None,
        is_read: Optional[bool] = None,
    ) -> Message:
        req = r.message_update(message_id, add_labels, remove_labels, is_read)
        return cast(Message, await self._c._send(req))

    async def draft_reply(
        self, message_id: str, instructions: Optional[str] = None, *, save: Optional[bool] = None
    ) -> DraftReply:
        """Draft a reply (needs ``ai_processing = "full"``). Never sends. See :meth:`Messages.draft_reply`."""
        return cast(DraftReply, await self._c._send(r.message_draft_reply(message_id, instructions, save)))

    async def attachment_text(
        self,
        message_id: str,
        attachment_id: str,
        offset: Optional[int] = None,
        max_chars: Optional[int] = None,
    ) -> AttachmentText:
        """Extracted text of an inbound attachment. See :meth:`Messages.attachment_text`."""
        req = r.message_attachment_text(message_id, attachment_id, offset, max_chars)
        return cast(AttachmentText, await self._c._send(req))

    async def extract_attachment(
        self,
        message_id: str,
        attachment_id: str,
        schema: Union[BuiltinExtractionSchema, Mapping[str, Any]],
        instructions: Optional[str] = None,
    ) -> StructuredExtraction:
        """Structured extraction with a schema. See :meth:`Messages.extract_attachment`."""
        req = r.message_extract_attachment(message_id, attachment_id, schema, instructions)
        return cast(StructuredExtraction, await self._c._send(req))

    async def wait(
        self,
        inbox_id: str,
        timeout: float = 30,
        since: Optional[str] = None,
        from_: Optional[str] = None,
        subject: Optional[str] = None,
        direction: Optional[Direction] = None,
        channel: Optional[MessageChannel] = None,
        type: Optional[MessageType] = None,
    ) -> Optional[Message]:
        """Long-poll until a matching message arrives, or return ``None`` after ``timeout`` seconds.

        See :meth:`Messages.wait`.
        """
        req = r.message_wait(inbox_id, timeout, since, from_, subject, direction, channel, type)
        return cast(Optional[Message], (await self._c._send(req))["data"])

    async def wait_for_verification(
        self,
        inbox_id: str,
        timeout: float = 30,
        since: Optional[str] = None,
        from_: Optional[str] = None,
    ) -> Optional[VerificationResult]:
        """Newest verification code/link after ``since``, waiting up to ``timeout`` s. ``None`` on timeout."""
        req = r.message_wait_for_verification(inbox_id, timeout, since, from_)
        return cast(Optional[VerificationResult], (await self._c._send(req))["data"])

    async def claim(
        self,
        inbox_id: str,
        *,
        limit: Optional[int] = None,
        lease_seconds: Optional[int] = None,
        consumer: Optional[str] = None,
        wait: Optional[float] = None,
        enriched: Optional[bool] = None,
        since: Optional[str] = None,
        type: Optional[MessageType] = None,
        channel: Optional[MessageChannel] = None,
    ) -> LeaseClaim:
        """Claim/ack queue: lease inbound messages. See :meth:`Messages.claim`."""
        req = r.message_claim(inbox_id, limit, lease_seconds, consumer, wait, enriched, since, type, channel)
        return cast(LeaseClaim, await self._c._send(req))

    async def ack(self, message_id: str, lease_id: str, *, mark_read: Optional[bool] = None) -> AckResult:
        """Done: never claimed again. Idempotent. See :meth:`Messages.ack`."""
        return cast(AckResult, await self._c._send(r.message_ack(message_id, lease_id, mark_read)))

    async def nack(
        self, message_id: str, lease_id: str, *, delay_seconds: Optional[int] = None
    ) -> NackResult:
        """Give the message back now or after ``delay_seconds``. See :meth:`Messages.nack`."""
        return cast(NackResult, await self._c._send(r.message_nack(message_id, lease_id, delay_seconds)))

    async def extend(
        self, message_id: str, lease_id: str, *, lease_seconds: Optional[int] = None
    ) -> ExtendResult:
        """Heartbeat for long tasks. See :meth:`Messages.extend`."""
        return cast(ExtendResult, await self._c._send(r.message_extend(message_id, lease_id, lease_seconds)))


class AsyncDrafts:
    """Drafts: store an email for review, edit it, then ``send`` it now or ``schedule`` it.

    Sending goes through every check a normal send does (allow/block lists, suppressions, plan quota,
    daily caps, the 5-minute burst limit). Permissions: ``drafts:read`` / ``drafts:write``; ``send`` and
    ``schedule`` also need ``messages:send``.
    """

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def create(
        self,
        inbox_id: str,
        *,
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
    ) -> Draft:
        """Create a draft (nothing is sent). Everything is optional until it is sent.

        ``reply_to_message_id`` (or ``thread_id``) makes it a reply: recipients, ``Re:`` subject and
        threading are filled in. ``send_at`` (1 minute to 30 days ahead) schedules it."""
        req = r.draft_create(
            inbox_id,
            to,
            subject,
            text,
            html,
            cc,
            bcc,
            attachments,
            labels,
            metadata,
            reply_to_message_id,
            thread_id,
            reply_all,
            send_at,
            idempotency_key,
            data,
            type,
        )
        return cast(Draft, await self._c._send(req))

    async def list(
        self,
        inbox_id: str,
        *,
        status: Optional[DraftStatuses] = None,
        thread_id: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Page[Draft]:
        """Drafts of one inbox, newest first. ``status``: one or several (``["draft", "scheduled"]``)."""
        return cast(
            "Page[Draft]", await self._c._send(r.draft_list(inbox_id, status, thread_id, cursor, limit))
        )

    async def list_all(
        self,
        *,
        inbox_id: Optional[str] = None,
        status: Optional[DraftStatuses] = None,
        thread_id: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Page[Draft]:
        """Drafts of every inbox of the workspace (``GET /v1/drafts``), optionally filtered."""
        req = r.draft_list_all(inbox_id, status, thread_id, cursor, limit)
        return cast("Page[Draft]", await self._c._send(req))

    async def get(self, inbox_id: str, draft_id: str) -> Draft:
        return cast(Draft, await self._c._send(r.draft_get(inbox_id, draft_id)))

    async def update(
        self,
        inbox_id: str,
        draft_id: str,
        *,
        to: Optional[Recipients] = None,
        subject: NullableText = NOT_GIVEN,
        text: NullableText = NOT_GIVEN,
        html: NullableText = NOT_GIVEN,
        cc: Optional[Recipients] = None,
        bcc: Optional[Recipients] = None,
        attachments: Optional[Sequence[Union[AttachmentInput, DraftKeep]]] = None,
        labels: Optional[Sequence[str]] = None,
        metadata: Optional[MetadataPatch] = None,
        send_at: NullableSendAt = NOT_GIVEN,
        data: Any = NOT_GIVEN,
        type: Optional[MessageType] = None,
    ) -> Draft:
        """Edit a ``draft`` or ``scheduled`` draft (else ``409 draft_not_editable``).

        ``subject``/``text``/``html=None`` clear them; ``attachments`` replaces the list (``{"id": ...}``
        keeps one already on the draft); ``send_at`` reschedules and ``send_at=None`` unschedules."""
        req = r.draft_update(
            inbox_id,
            draft_id,
            to,
            subject,
            text,
            html,
            cc,
            bcc,
            attachments,
            labels,
            metadata,
            send_at,
            data,
            type,
        )
        return cast(Draft, await self._c._send(req))

    async def delete(self, inbox_id: str, draft_id: str) -> None:
        await self._c._send(r.draft_delete(inbox_id, draft_id))

    async def send(
        self, inbox_id: str, draft_id: str, *, idempotency_key: Optional[str] = None
    ) -> DraftSendResult:
        """Send now. A refused send raises the API error and leaves the draft as it was (``error`` set)."""
        return cast(DraftSendResult, await self._c._send(r.draft_send(inbox_id, draft_id, idempotency_key)))

    async def schedule(self, inbox_id: str, draft_id: str, send_at: SendAt) -> Draft:
        """Send automatically at ``send_at`` (1 minute to 30 days ahead; ``400 invalid_send_at``)."""
        return cast(Draft, await self._c._send(r.draft_schedule(inbox_id, draft_id, send_at)))

    async def cancel(self, inbox_id: str, draft_id: str) -> Draft:
        """Cancel a draft or its scheduled send (terminal)."""
        return cast(Draft, await self._c._send(r.draft_cancel(inbox_id, draft_id)))


class AsyncThreads:
    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def list(
        self, inbox_id: str, cursor: Optional[str] = None, limit: Optional[int] = None
    ) -> Page[Thread]:
        return cast("Page[Thread]", await self._c._send(r.thread_list(inbox_id, cursor, limit)))

    async def get(self, thread_id: str) -> ThreadWithMessages:
        """A thread plus its messages in order."""
        return cast(ThreadWithMessages, await self._c._send(r.thread_get(thread_id)))

    async def update(
        self,
        thread_id: str,
        metadata: Optional[MetadataPatch] = None,
        add_labels: Optional[Sequence[str]] = None,
        remove_labels: Optional[Sequence[str]] = None,
    ) -> Thread:
        """Set thread labels and metadata (merged: a ``None`` value deletes a key). Returns the thread."""
        return cast(
            Thread, await self._c._send(r.thread_update(thread_id, metadata, add_labels, remove_labels))
        )


class AsyncWebhooks:
    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def create(
        self,
        url: str,
        events: Optional[Sequence[WebhookEventType]] = None,
        inbox_ids: InboxIds = NOT_GIVEN,
        secret: Optional[str] = None,
        payload: Optional[WebhookPayload] = None,
    ) -> Webhook:
        """Create a webhook. The returned ``secret`` is only shown here: store it.

        ``payload="envelope"`` sends ids, addresses, subject and labels only (no bodies).
        """
        req = r.webhook_create(url, events, inbox_ids, secret, payload)
        return cast(Webhook, await self._c._send(req))

    async def list(self) -> Page[Webhook]:
        return cast("Page[Webhook]", await self._c._send(r.webhook_list()))

    async def get(self, webhook_id: str) -> Webhook:
        return cast(Webhook, await self._c._send(r.webhook_get(webhook_id)))

    async def update(
        self,
        webhook_id: str,
        url: Optional[str] = None,
        events: Optional[Sequence[WebhookEventType]] = None,
        inbox_ids: InboxIds = NOT_GIVEN,
        enabled: Optional[bool] = None,
        payload: Optional[WebhookPayload] = None,
    ) -> Webhook:
        """Update a webhook. Pass ``inbox_ids=None`` explicitly to subscribe to all inboxes."""
        req = r.webhook_update(webhook_id, url, events, inbox_ids, enabled, payload)
        return cast(Webhook, await self._c._send(req))

    async def delete(self, webhook_id: str) -> None:
        await self._c._send(r.webhook_delete(webhook_id))

    async def test(self, webhook_id: str) -> WebhookTestResult:
        """Send a ``webhook.test`` event."""
        return cast(WebhookTestResult, await self._c._send(r.webhook_test(webhook_id)))

    async def events(self) -> builtins.list[WebhookCatalogEntry]:
        """The event catalog: every event type with a description and example bodies."""
        return cast("builtins.list[WebhookCatalogEntry]", (await self._c._send(r.webhook_events()))["data"])


class AsyncLists:
    """Allow/block lists for receiving, sending and replying (permission ``lists:manage``)."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def list(
        self,
        inbox_id: Optional[str] = None,
        direction: Optional[ListDirection] = None,
        kind: Optional[ListKind] = None,
    ) -> ListEntries:
        return cast(ListEntries, await self._c._send(r.list_entries(inbox_id, direction, kind)))

    async def create(
        self, direction: ListDirection, kind: ListKind, pattern: str, inbox_id: Optional[str] = None
    ) -> ListEntry:
        """Add ``a@b.com`` or a domain (``b.com``, subdomains included). No ``inbox_id`` = workspace-wide."""
        return cast(ListEntry, await self._c._send(r.list_create(direction, kind, pattern, inbox_id)))

    async def delete(self, entry_id: str) -> None:
        await self._c._send(r.list_delete(entry_id))


class AsyncContacts:
    """Contacts: external addresses the workspace has exchanged mail with (created automatically)."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def list(
        self,
        q: Optional[str] = None,
        label: Optional[str] = None,
        metadata: Optional[MetadataFilter] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Page[Contact]:
        """Newest activity first. ``q`` matches address/name; ``metadata`` filters by exact value."""
        req = r.contact_list(q, label, metadata, cursor, limit)
        return cast("Page[Contact]", await self._c._send(req))

    async def get(self, contact_id: str) -> ContactWithThreads:
        """A contact plus its 10 most recent threads."""
        return cast(ContactWithThreads, await self._c._send(r.contact_get(contact_id)))

    async def by_address(self, address: str) -> ContactWithThreads:
        """Look a contact up by address. ``NotFoundError`` if the workspace never exchanged mail with it."""
        return cast(ContactWithThreads, await self._c._send(r.contact_by_address(address)))

    async def update(
        self,
        contact_id: str,
        name: Nullable = NOT_GIVEN,
        notes: Nullable = NOT_GIVEN,
        metadata: Optional[MetadataPatch] = None,
        add_labels: Optional[Sequence[str]] = None,
        remove_labels: Optional[Sequence[str]] = None,
    ) -> Contact:
        """Update notes (up to 10,000 chars; ``None`` clears), name, labels or metadata.

        Metadata is merged: given keys are set, a ``None`` value deletes the key.
        """
        req = r.contact_update(contact_id, name, notes, metadata, add_labels, remove_labels)
        return cast(Contact, await self._c._send(req))


class AsyncKnowledge:
    """Knowledge documents used as context for reply drafts (per inbox, or workspace-wide)."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def list(
        self, inbox_id: Optional[str] = None, cursor: Optional[str] = None, limit: Optional[int] = None
    ) -> Page[KnowledgeListItem]:
        """Documents without bodies (each has an ``excerpt``). ``inbox_id``: one inbox's documents."""
        return cast("Page[KnowledgeListItem]", await self._c._send(r.knowledge_list(inbox_id, cursor, limit)))

    async def create(self, title: str, body: str, inbox_id: Optional[str] = None) -> KnowledgeDoc:
        """Create a document. Without ``inbox_id`` it applies to every inbox of the workspace."""
        return cast(KnowledgeDoc, await self._c._send(r.knowledge_create(title, body, inbox_id)))

    async def get(self, doc_id: str) -> KnowledgeDoc:
        return cast(KnowledgeDoc, await self._c._send(r.knowledge_get(doc_id)))

    async def update(
        self,
        doc_id: str,
        title: Optional[str] = None,
        body: Optional[str] = None,
        inbox_id: Nullable = NOT_GIVEN,
    ) -> KnowledgeDoc:
        """Update a document. Pass ``inbox_id=None`` explicitly to make it workspace-wide."""
        return cast(KnowledgeDoc, await self._c._send(r.knowledge_update(doc_id, title, body, inbox_id)))

    async def delete(self, doc_id: str) -> None:
        await self._c._send(r.knowledge_delete(doc_id))

    async def search(
        self, q: str, inbox_id: Optional[str] = None, limit: Optional[int] = None
    ) -> KnowledgeSearchResults:
        """Ranked full-text search. With ``inbox_id``, workspace-wide documents are included too."""
        return cast(KnowledgeSearchResults, await self._c._send(r.knowledge_search(q, inbox_id, limit)))


class AsyncIdentityClients:
    """Apps ("relying parties") the workspace registered for Sign in with Agentboxd (``identity:manage``)."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def list(self) -> Page[IdentityClient]:
        return cast("Page[IdentityClient]", await self._c._send(r.identity_client_list()))

    async def create(
        self,
        name: str,
        type: IdentityClientType,
        redirect_uris: Optional[Sequence[str]] = None,
        allowed_scopes: Optional[Sequence[IdentityScope]] = None,
        subject_type: Optional[IdentitySubjectType] = None,
        homepage_url: Optional[str] = None,
    ) -> IdentityClientWithSecret:
        """Register an app. ``client_secret`` (confidential clients) is only returned here: store it."""
        req = r.identity_client_create(name, type, redirect_uris, allowed_scopes, subject_type, homepage_url)
        return cast(IdentityClientWithSecret, await self._c._send(req))

    async def get(self, client_id: str) -> IdentityClient:
        return cast(IdentityClient, await self._c._send(r.identity_client_get(client_id)))

    async def update(
        self,
        client_id: str,
        name: Optional[str] = None,
        redirect_uris: Optional[Sequence[str]] = None,
        allowed_scopes: Optional[Sequence[IdentityScope]] = None,
        homepage_url: Nullable = NOT_GIVEN,
        enabled: Optional[bool] = None,
    ) -> IdentityClient:
        req = r.identity_client_update(client_id, name, redirect_uris, allowed_scopes, homepage_url, enabled)
        return cast(IdentityClient, await self._c._send(req))

    async def delete(self, client_id: str) -> None:
        await self._c._send(r.identity_client_delete(client_id))

    async def rotate_secret(self, client_id: str) -> IdentityClientWithSecret:
        return cast(IdentityClientWithSecret, await self._c._send(r.identity_client_rotate_secret(client_id)))


class AsyncInboxIdentities:
    """The per-inbox Sign in with Agentboxd switch and sign-in history."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def get(self, inbox_id: str) -> InboxIdentity:
        return cast(InboxIdentity, await self._c._send(r.inbox_identity_get(inbox_id)))

    async def update(self, inbox_id: str, enabled: bool) -> InboxIdentity:
        return cast(InboxIdentity, await self._c._send(r.inbox_identity_update(inbox_id, enabled)))

    async def sign_ins(
        self, inbox_id: str, cursor: Optional[str] = None, limit: Optional[int] = None
    ) -> Page[IdentitySignIn]:
        return cast(
            "Page[IdentitySignIn]", await self._c._send(r.inbox_identity_sign_ins(inbox_id, cursor, limit))
        )


class AsyncIdentities:
    """Async :class:`Identities`."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def create(
        self,
        *,
        username: Optional[str] = None,
        display_name: Optional[str] = None,
        client_id: Optional[str] = None,
        metadata: Optional[MetadataPatch] = None,
        card: Optional[AgentCardInput] = None,
    ) -> IdentityRecord:
        req = r.identity_create(username, display_name, client_id, metadata, card=card)
        return cast(IdentityRecord, await self._c._send(req))

    async def list(
        self,
        *,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        metadata: Optional[MetadataFilter] = None,
    ) -> "Page[IdentityRecord]":
        return cast("Page[IdentityRecord]", await self._c._send(r.identity_list(cursor, limit, metadata)))

    async def get(self, identity_id: str) -> IdentityRecord:
        return cast(IdentityRecord, await self._c._send(r.identity_get(identity_id)))

    async def update(
        self,
        identity_id: str,
        *,
        display_name: Nullable = NOT_GIVEN,
        metadata: Optional[MetadataPatch] = None,
    ) -> IdentityRecord:
        return cast(
            IdentityRecord, await self._c._send(r.identity_update(identity_id, display_name, metadata))
        )

    async def delete(self, identity_id: str) -> None:
        await self._c._send(r.identity_delete(identity_id))

    async def pause(self, identity_id: str, *, reason: Optional[str] = None) -> Inbox:
        return cast(Inbox, await self._c._send(r.inbox_pause(identity_id, reason)))

    async def resume(self, identity_id: str) -> ResumedInbox:
        return cast(ResumedInbox, await self._c._send(r.inbox_resume(identity_id)))


class AsyncIdentity:
    """Sign in with Agentboxd: the agent's identity (an inbox or an identity-only agent), OpenID Connect."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client
        self.clients = AsyncIdentityClients(client)
        self.inbox = AsyncInboxIdentities(client)

    async def token(
        self,
        inbox_id: Optional[str] = None,
        audience: Optional[str] = None,
        nonce: Optional[str] = None,
        scope: Optional[Union[str, Sequence[IdentityScope]]] = None,
        expires_in: Optional[int] = None,
        *,
        identity_id: Optional[str] = None,
    ) -> IdentityToken:
        """Mint a short-lived, single-use ID token for the relying party ``audience`` (``identity:sign``).

        Pass ``inbox_id`` for an inbox or ``identity_id`` for an identity-only agent."""
        req = r.identity_token(inbox_id, audience, nonce, scope, expires_in, identity_id)
        return cast(IdentityToken, await self._c._send(req))


class AsyncAgents:
    """Async :class:`Agents`."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client
        self.keys = AsyncAgentKeys(client)

    async def get(self, inbox_id: str) -> AgentBundle:
        return cast(AgentBundle, await self._c._send(r.agent_get(inbox_id)))

    async def update(
        self,
        inbox_id: str,
        *,
        name: Optional[str] = None,
        description: Nullable = NOT_GIVEN,
        capabilities: Optional[Mapping[str, Any]] = None,
        documentation_url: Nullable = NOT_GIVEN,
        visibility: Optional[AgentCardVisibility] = None,
        routing: Optional[Literal["relay", "direct_preferred"]] = None,
        handle: Nullable = NOT_GIVEN,
        indexable: Optional[bool] = None,
    ) -> AgentBundle:
        body = _card_body(
            name, description, capabilities, documentation_url, visibility, routing, handle, indexable
        )
        return cast(AgentBundle, await self._c._send(r.agent_update(inbox_id, body)))

    async def delete(self, inbox_id: str) -> None:
        await self._c._send(r.agent_delete(inbox_id))

    async def revoke(self, inbox_id: str, *, reason: Optional[str] = None) -> AgentBundle:
        return cast(AgentBundle, await self._c._send(r.agent_revoke(inbox_id, reason)))

    async def restore(self, inbox_id: str) -> AgentBundle:
        return cast(AgentBundle, await self._c._send(r.agent_restore(inbox_id)))

    async def oasf(self, inbox_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._c._send(r.agent_oasf(inbox_id)))


class AsyncAgentKeys:
    """Async :class:`AgentKeys`."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def list(self, inbox_id: str) -> AgentKeyList:
        return cast(AgentKeyList, await self._c._send(r.agent_keys_list(inbox_id)))

    async def register(self, inbox_id: str, *, public_jwk: Mapping[str, Any], proof: str) -> AgentKey:
        return cast(AgentKey, await self._c._send(r.agent_keys_register(inbox_id, public_jwk, proof)))

    async def retire(self, inbox_id: str, kid: str) -> AgentKey:
        return cast(AgentKey, await self._c._send(r.agent_keys_retire(inbox_id, kid)))

    async def revoke(
        self, inbox_id: str, kid: str, *, reason: Optional[str] = None, since: Optional[str] = None
    ) -> AgentKey:
        return cast(AgentKey, await self._c._send(r.agent_keys_revoke(inbox_id, kid, reason, since)))


class AsyncDirectory:
    """Async :class:`Directory`."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def resolve(self, address: Optional[str] = None, *, handle: Optional[str] = None) -> ResolvedAgent:
        return cast(ResolvedAgent, await self._c._send(r.directory_resolve(address, handle)))

    async def verify(
        self, *, signature: Optional[str] = None, address: Optional[str] = None
    ) -> DirectoryVerifyResult:
        return cast(DirectoryVerifyResult, await self._c._send(r.directory_verify(signature, address)))

    async def search(
        self,
        *,
        q: Optional[str] = None,
        capability: Optional[str] = None,
        type: Optional[MessageType] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        scope: Optional[Literal["workspace", "public"]] = None,
    ) -> "Page[AgentCard]":
        req = r.directory_search(q, capability, type, limit, cursor, scope)
        return cast("Page[AgentCard]", await self._c._send(req))

    async def get_handle(self) -> WorkspaceHandle:
        return cast(WorkspaceHandle, await self._c._send(r.directory_handle_get()))

    async def set_handle(self, handle: str) -> WorkspaceHandle:
        return cast(WorkspaceHandle, await self._c._send(r.directory_handle_set(handle)))

    async def release_handle(self) -> WorkspaceHandle:
        return cast(WorkspaceHandle, await self._c._send(r.directory_handle_release()))

    async def report(
        self,
        address: str,
        reason: DirectoryReportReason,
        *,
        details: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> DirectoryReportResult:
        return cast(
            DirectoryReportResult,
            await self._c._send(r.directory_report(address, reason, details, message_id)),
        )


class AsyncPublicDirectory:
    """Async :class:`PublicDirectory`."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def search(
        self,
        *,
        q: Optional[str] = None,
        capability: Optional[str] = None,
        type: Optional[MessageType] = None,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
    ) -> "Page[PublicAgentCard]":
        req = r.public_agents_search(q, capability, type, limit, cursor)
        return cast("Page[PublicAgentCard]", await self._c._send(req))

    async def get(self, address: str) -> PublicAgent:
        return cast(PublicAgent, await self._c._send(r.public_agent(address)))

    async def a2a_card(self, address: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._c._send(r.public_agent(address, "agent-card.json")))

    async def oasf(self, address: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._c._send(r.public_agent(address, "oasf.json")))

    async def keys(self, address: str) -> PublicAgentKeys:
        return cast(PublicAgentKeys, await self._c._send(r.public_agent(address, "keys.json")))

    async def handle(self, workspace: str, agent: str) -> PublicHandle:
        return cast(PublicHandle, await self._c._send(r.public_handle(workspace, agent)))


class AsyncAccountApi:
    """Async :class:`AccountApi`."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def get(self) -> Account:
        return cast(Account, await self._c._send(r.account_get()))

    async def request_claim(self, email: str) -> ClaimRequestResult:
        return cast(ClaimRequestResult, await self._c._send(r.signup_claim(email)))


class AsyncEscalationApi:
    """Async :class:`EscalationApi`."""

    def __init__(self, client: "AsyncAgentboxd") -> None:
        self._c = client

    async def get(self) -> EscalationSettings:
        return cast(EscalationSettings, await self._c._send(r.escalation_get()))

    async def update(
        self,
        *,
        contacts: Union[Sequence[str], NotGiven] = NOT_GIVEN,
        triggers: Union[Mapping[str, bool], NotGiven] = NOT_GIVEN,
        delivery: Union[Literal["immediate", "digest"], NotGiven] = NOT_GIVEN,
        max_per_hour: Union[int, NotGiven] = NOT_GIVEN,
        quiet_hours: Union[QuietHours, NotGiven, None] = NOT_GIVEN,
        include_excerpt: Union[bool, NotGiven] = NOT_GIVEN,
    ) -> EscalationSettings:
        req = r.escalation_update(
            _escalation_body(contacts, triggers, delivery, max_per_hour, quiet_hours, include_excerpt)
        )
        return cast(EscalationSettings, await self._c._send(req))

    async def get_inbox(self, inbox_id: str) -> InboxEscalation:
        return cast(InboxEscalation, await self._c._send(r.inbox_escalation_get(inbox_id)))

    async def update_inbox(
        self,
        inbox_id: str,
        *,
        override: Union[bool, NotGiven] = NOT_GIVEN,
        contacts: Union[Sequence[str], NotGiven] = NOT_GIVEN,
        triggers: Union[Mapping[str, bool], NotGiven, None] = NOT_GIVEN,
    ) -> InboxEscalation:
        req = r.inbox_escalation_update(inbox_id, _inbox_escalation_body(override, contacts, triggers))
        return cast(InboxEscalation, await self._c._send(req))


class AsyncAgentboxd(_BaseClient):
    """Asynchronous Agentboxd client with the same surface as :class:`Agentboxd`.

    >>> async with AsyncAgentboxd() as mr:
    ...     inbox = await mr.inboxes.create()
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(api_key, base_url, timeout)
        self._owns_http = http_client is None
        self._http = http_client if http_client is not None else httpx.AsyncClient(timeout=timeout)
        self.inboxes = AsyncInboxes(self)
        self.domains = AsyncDomains(self)
        self.messages = AsyncMessages(self)
        self.drafts = AsyncDrafts(self)
        self.threads = AsyncThreads(self)
        self.webhooks = AsyncWebhooks(self)
        self.contacts = AsyncContacts(self)
        self.knowledge = AsyncKnowledge(self)
        self.lists = AsyncLists(self)
        self.identity = AsyncIdentity(self)
        self.identities = AsyncIdentities(self)
        self.account = AsyncAccountApi(self)
        self.escalation = AsyncEscalationApi(self)
        self.agents = AsyncAgents(self)
        self.directory = AsyncDirectory(self)
        self.public_directory = AsyncPublicDirectory(self)

    @classmethod
    async def signup(
        cls,
        *,
        agent_name: Optional[str] = None,
        owner_email: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: Optional[httpx.AsyncClient] = None,
        max_iterations: int = 2**32,
        kind: Optional[str] = None,
    ) -> "Signup[AsyncAgentboxd]":
        """Async :meth:`Agentboxd.signup` (the proof of work runs in a worker thread)."""
        url = _signup_base_url(base_url)
        http = http_client if http_client is not None else httpx.AsyncClient(timeout=timeout)
        try:
            try:
                ch = cast(
                    SignupChallenge,
                    cls._parse(await http.request(**_public_kwargs(url, r.signup_challenge()))),
                )
                solution = await asyncio.to_thread(
                    solve_signup_challenge, ch["challenge"], int(ch["difficulty"]), max_iterations
                )
                req = r.signup_create(ch["challenge"], solution, agent_name, owner_email, kind)
                result = cast(SignupResult, cls._parse(await http.request(**_public_kwargs(url, req))))
            except httpx.TimeoutException as exc:
                raise APIConnectionError(f"Request timed out: {exc}", code="timeout") from exc
            except httpx.TransportError as exc:
                raise APIConnectionError(f"Connection error: {exc}") from exc
        finally:
            if http_client is None:
                await http.aclose()
        client = cls(api_key=result["api_key"], base_url=url, timeout=timeout, http_client=http_client)
        return Signup(client=client, result=result)

    async def search(
        self,
        q: str,
        inbox_id: Optional[str] = None,
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        channel: Optional[MessageChannel] = None,
        type: Optional[MessageType] = None,
    ) -> Page[SearchResult]:
        """Full-text search (web-search syntax: ``"exact phrase"``, ``-exclude``, ``or``)."""
        return cast(
            "Page[SearchResult]", await self._send(r.search(q, inbox_id, cursor, limit, channel, type))
        )

    async def metrics(
        self,
        from_: Optional[str] = None,
        to: Optional[str] = None,
        tz: Optional[str] = None,
        inbox_id: Optional[str] = None,
        bucket: Optional[MetricsBucket] = None,
    ) -> Metrics:
        """Sent/received/delivery counts bucketed in ``tz`` (IANA), a 30-day heatmap and resources."""
        return cast(Metrics, await self._send(r.metrics(from_, to, tz, inbox_id, bucket)))

    async def emergency_stop(self, reason: Optional[str] = None) -> EmergencyStopResult:
        return cast(EmergencyStopResult, await self._send(r.emergency_stop(reason)))

    async def deliverability(self) -> DeliverabilitySummary:
        """Bounce and complaint rates (7 and 30 days), suppressed contacts, your domains' SPF/DKIM/DMARC
        and the shared IP's blocklist status (permission ``metrics:read``, workspace keys)."""
        return cast(DeliverabilitySummary, await self._send(r.deliverability()))

    async def stream_token(self) -> StreamToken:
        """A single-use, 60-second WebSocket URL for ``GET /v1/stream``."""
        return cast(StreamToken, await self._send(r.stream_token()))

    def stream(
        self,
        inbox_ids: Optional[Sequence[str]] = None,
        event_types: Optional[Sequence[WebhookEventType]] = None,
        payload: Optional[WebhookPayload] = None,
        since: Optional[str] = None,
        reconnect: bool = True,
    ) -> EventStream:
        """Realtime events over a WebSocket (permission ``messages:read``): the same bodies as webhooks.

        Iterate with ``async for``; the stream reconnects and resumes after the last event on its own.
        Needs ``pip install 'agentboxd[stream]'``.

        >>> async for event in mr.stream(event_types=["message.received"]):
        ...     print(event["data"]["message"]["subject"])
        """

        async def mint_url() -> str:
            return (await self.stream_token())["url"]

        return EventStream(
            mint_url,
            inbox_ids=inbox_ids,
            event_types=event_types,
            payload=payload,
            since=since,
            reconnect=reconnect,
        )

    async def _send(self, req: Request) -> Any:
        try:
            response = await self._http.request(**self._build(req))
        except httpx.TimeoutException as exc:
            raise APIConnectionError(f"Request timed out: {exc}", code="timeout") from exc
        except httpx.TransportError as exc:
            raise APIConnectionError(f"Connection error: {exc}") from exc
        return self._parse(response)

    async def close(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self: _SelfT) -> _SelfT:
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        await self.close()
