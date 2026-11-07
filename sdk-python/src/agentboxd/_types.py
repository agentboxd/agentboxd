"""Response and input types. All are TypedDicts: API JSON is returned as plain dicts."""

import sys
from typing import TYPE_CHECKING, Any, Generic, Literal, Optional, TypedDict, TypeVar, Union

__all__ = [
    "Account",
    "AccountClaim",
    "AckResult",
    "AddAgentResult",
    "AgentAssurance",
    "AgentBundle",
    "AgentCard",
    "AgentCardInput",
    "AgentCardListing",
    "AgentCardSkill",
    "AgentCardStatus",
    "AgentCardVisibility",
    "AgentKey",
    "AgentKeyJwk",
    "AgentKeyList",
    "AgentMessaging",
    "AgentStatus",
    "AiDisclosure",
    "AiProcessing",
    "Attachment",
    "AttachmentExtraction",
    "AttachmentInput",
    "AttachmentText",
    "BounceReason",
    "BuiltinExtractionSchema",
    "BusiestDay",
    "CalendarAnswer",
    "CalendarAttendee",
    "CalendarAttendeeInput",
    "CalendarCancelDraftResult",
    "CalendarCancelResult",
    "CalendarConference",
    "CalendarDraftResult",
    "CalendarEvent",
    "CalendarEventPage",
    "CalendarEventResult",
    "CalendarEventRole",
    "CalendarEventStatus",
    "CalendarMethod",
    "CalendarPartstat",
    "CalendarPerson",
    "CalendarProposal",
    "CalendarRecurrence",
    "CalendarResponse",
    "CalendarWithheld",
    "ClaimRequestResult",
    "Contact",
    "ContactWithThreads",
    "Deliverability",
    "Direction",
    "DirectoryReportReason",
    "DirectoryReportResult",
    "DirectoryVerifyResult",
    "Domain",
    "DomainRecord",
    "DomainRecordKey",
    "DomainStatus",
    "DomainZoneFile",
    "Draft",
    "DraftApprover",
    "DraftAttachment",
    "DraftCalendar",
    "DraftCitation",
    "DraftError",
    "DraftKeep",
    "DraftReply",
    "DraftSendResult",
    "DraftStatus",
    "EmergencyStopResult",
    "EnvelopeEventData",
    "EscalationContact",
    "EscalationSettings",
    "EscalationTrigger",
    "ExtendResult",
    "ExtractionError",
    "ExtractionMethod",
    "ExtractionStatus",
    "HeatmapDay",
    "IdentityClient",
    "IdentityClientType",
    "IdentityClientWithSecret",
    "IdentityFlow",
    "IdentityScope",
    "IdentitySignIn",
    "IdentitySubjectType",
    "IdentityToken",
    "InboundQuality",
    "Inbox",
    "InboxEscalation",
    "InboxIdentity",
    "InboxIdentityApp",
    "KnowledgeDoc",
    "KnowledgeListItem",
    "KnowledgeSearchResult",
    "KnowledgeSearchResults",
    "Lease",
    "LeaseClaim",
    "ListDirection",
    "ListEntries",
    "ListEntry",
    "ListKind",
    "Message",
    "MessageAgent",
    "MessageAi",
    "MessageAnalysis",
    "MessageApproval",
    "MessageAuthor",
    "MessageCalendar",
    "MessageCategory",
    "MessageCategoryInfo",
    "MessageChannel",
    "MessageDelivery",
    "MessageEventData",
    "MessageRisk",
    "MessageScreening",
    "MessageStatus",
    "MessageType",
    "MessageUrgency",
    "MessageWithheld",
    "Metadata",
    "MetadataValue",
    "MetricCounts",
    "Metrics",
    "MetricsBucket",
    "MetricsPoint",
    "MinimalAgentCard",
    "NackResult",
    "Page",
    "PublicAgent",
    "PublicAgentCard",
    "PublicAgentKeys",
    "PublicCardUrls",
    "PublicHandle",
    "QueueMetrics",
    "QuietHours",
    "ResolvedAgent",
    "Resources",
    "ScreeningReason",
    "ScreeningState",
    "SearchResult",
    "SignupChallenge",
    "SignupClaim",
    "SignupResult",
    "SignupWorkspace",
    "Streak",
    "StreamEvent",
    "StreamToken",
    "StructuredExtraction",
    "Suppression",
    "SuppressionReason",
    "Thread",
    "ThreadWithMessages",
    "UnclaimedRestrictions",
    "UrgencyLevel",
    "VerificationInfo",
    "VerificationResult",
    "Webhook",
    "WebhookCatalogEntry",
    "WebhookDelivery",
    "WebhookDeliveryStatus",
    "WebhookEvent",
    "WebhookEventType",
    "WebhookPayload",
    "WebhookStats",
    "WebhookTestResult",
    "WorkspaceHandle",
]

_T = TypeVar("_T")

Direction = Literal["inbound", "outbound"]

MessageStatus = Literal["queued", "sent", "delivered", "bounced", "complained", "failed", "received"]
MessageChannel = Literal["agent", "email", "mixed"]
"""``agent``: an inbound copy from another Agentboxd inbox, sender verified and signed. ``mixed``: an
outbound message with agent and email recipients. Everything else is ``email``."""
MessageType = Literal["message", "task", "event"]
"""Advisory message kind set by the sender."""
AgentAssurance = Literal["unclaimed", "workspace", "domain_verified", "org_verified"]
"""How strongly Agentboxd vouches for an agent sender (``unclaimed``: an agent-created workspace no person
claimed yet)."""

WebhookEventType = Literal[
    "message.received",
    "message.sent",
    "message.delivered",
    "message.bounced",
    "message.complained",
    "message.enriched",
    "message.released",
    "inbox.expired",
    "message.received.blocked",
    "draft.created",
    "draft.updated",
    "draft.sent",
    "draft.failed",
    "draft.cancelled",
    "identity.token_issued",
    "identity.signed_in",
    "signup.created",
    "signup.claimed",
    "attachment.extracted",
    "attachment.extraction_failed",
    "inbox.paused",
    "inbox.resumed",
    "domain.dkim_rotated",
    "domain.dkim_rotation_due",
    "domain.verified",
    "domain.failed",
    "connector.authorized",
    "connector.revoked",
    "workspace.stopped",
    "workspace.resumed",
    "escalation.sent",
    "agent.updated",
    "agent.revoked",
    "agent.deleted",
    "agent.reported",
    "member.invited",
    "member.invite_revoked",
    "member.joined",
    "member.role_changed",
    "member.removed",
    "suppression.removed",
    "calendar.invite.received",
    "calendar.event.created",
    "calendar.event.updated",
    "calendar.event.cancelled",
    "calendar.response.received",
]

WebhookPayload = Literal["full", "envelope"]
"""``full`` = the whole message (default) · ``envelope`` = ids, addresses, subject and labels only."""

ListDirection = Literal["receive", "send", "reply"]
ListKind = Literal["allow", "block"]
MetricsBucket = Literal["hour", "day"]

MessageCategory = Literal[
    "support", "sales", "billing", "verification", "notification", "newsletter", "personal", "other"
]

UrgencyLevel = Literal["low", "normal", "high", "critical"]

AiProcessing = Literal["off", "categorize", "full"]
"""Workspace AI switch: ``off`` (nothing leaves the server), ``categorize`` (JEV), ``full`` (+ drafts)."""

MetadataValue = Union[str, int, float, bool, None]
Metadata = dict[str, MetadataValue]
"""Custom key/value data: at most 50 keys (``^[a-zA-Z0-9_.-]{1,64}$``), string values up to 1,000 chars.

In updates the object is merged: given keys are set and a ``None`` value deletes the key."""


class _InboxBase(TypedDict):
    id: str
    address: str
    username: str
    display_name: Optional[str]
    client_id: Optional[str]
    daily_send_limit: int
    created_at: str


class Inbox(_InboxBase, total=False):
    kind: Literal["mailbox", "identity"]
    """``identity``: an identity-only agent (no mail, see ``client.identities``). Identity ids only reach you
    through per-id inbox routes (``get``, ``pause``), never through ``inboxes.list``."""
    metadata: Metadata
    """Custom metadata (always present on servers with Phase 2b)."""
    temporary: bool
    """Temporary (receive-only, self-deleting) inbox."""
    expires_at: Optional[str]
    """When a temporary inbox is wiped (ISO 8601); ``None`` for permanent inboxes."""
    status: Literal["active", "paused"]
    """``paused``: sends are refused (423 ``inbox_paused``) and inbound events are held until resume."""
    paused_at: Optional[str]
    paused_reason: Optional[str]
    promotions_filter: bool
    """Promotions & spam view: the dashboard shows mail labelled ``ai:sales`` or ``local:spam`` apart. On by
    default for role addresses (hello@, support@, security@, ...)."""
    held_count: int
    """Screening: held mail nobody has opened yet."""
    pending_draft_count: int
    """Drafts waiting for a person: to approve (``draft``) or refused at their send time (``failed``)."""
    needs_human_count: int
    """Unread received mail labelled ``ai:needs-human``."""
    recent_bounce_count: int
    """Sent messages that bounced in the last 7 days."""


class ResumedInbox(Inbox, total=False):
    """``inboxes.resume()``: the inbox plus how many held events were released."""

    released_events: int


DomainStatus = Literal["pending", "verified", "failed", "disabled"]

DomainRecordKey = Literal["verification", "mx", "spf", "dkim", "dmarc", "dkim_next", "dkim_previous"]
"""``dkim_next`` / ``dkim_previous`` only appear during a DKIM key rotation (never required)."""


class _DomainRecordBase(TypedDict):
    key: DomainRecordKey
    type: Literal["TXT", "MX"]
    name: str
    value: str
    required: bool
    status: Literal["ok", "missing", "mismatch"]


class DomainRecord(_DomainRecordBase, total=False):
    """One DNS record to publish for a custom domain, with the result of the last check."""

    found: list[str]
    """What was found in DNS for this name."""
    host: str
    """The part of ``name`` to type at DNS providers that add the zone themselves (``@`` = the zone)."""
    hint: Literal["full_name_in_host"]
    """Missing, but published at ``<name>.<zone>``: the full name went into a host field.
    Rename it to ``host``."""


class InboxForward(TypedDict):
    """An automatic forwarding address of an inbox. Nothing is forwarded until it confirms by email."""

    id: str
    inbox_id: str
    address: str
    status: Literal["pending", "confirmed"]
    skip_flagged: bool
    """Skip mail flagged as phishing, prompt injection or failing DMARC (default True)."""
    confirmed_at: Optional[str]
    confirmation_sent_at: Optional[str]
    last_forwarded_at: Optional[str]
    forwarded_count: int
    created_at: str


class DomainDnsProvider(TypedDict):
    id: str
    name: str


class DomainDns(TypedDict):
    """Where a custom domain's DNS is hosted, from its NS records."""

    zone: str
    nameservers: list[str]
    provider: Optional[DomainDnsProvider]
    """A known DNS provider (``cloudflare``, ``godaddy``, ``route53``, ...), or None."""
    checked_at: str


class DkimNext(TypedDict):
    selector: str
    status: Literal["ok", "missing", "mismatch"]
    started_at: Optional[str]


class DkimPrevious(TypedDict):
    selector: str
    retire_at: Optional[str]


class DomainDkim(TypedDict):
    """DKIM key rotation state of a custom domain."""

    selector: str
    active_since: str
    rotation_due: bool
    """The active key has signed for a year: rotate it."""
    next: Optional[DkimNext]
    """A rotation waiting for its new record (``dkim_next`` in ``records``)."""
    previous: Optional[DkimPrevious]
    """The replaced key: keep its record (``dkim_previous``) until ``retire_at``."""


class _DomainBase(TypedDict):
    id: str
    domain: str
    status: DomainStatus
    receiving: bool
    records: list[DomainRecord]
    verified_at: Optional[str]
    last_checked_at: Optional[str]
    created_at: str


class Domain(_DomainBase, total=False):
    """A workspace's own domain: inboxes on it send DKIM-signed with its own key."""

    dkim: DomainDkim
    """DKIM key rotation state (optional for older servers)."""
    dns: Optional[DomainDns]
    """Where the domain's DNS is hosted; None until found (optional for older servers)."""


class DomainZoneFile(TypedDict):
    """A domain's DNS records as a BIND zone file, for DNS providers that import one."""

    filename: str
    """Suggested file name, e.g. ``mail.acme.com.zone.txt``."""
    content: str
    """The zone-file text: one line per record to publish, with fully qualified names."""


ExtractionStatus = Literal["pending", "done", "failed", "skipped"]
ExtractionMethod = Literal["text", "ocr"]
BuiltinExtractionSchema = Literal["invoice", "receipt", "tax_form"]


class ExtractionError(TypedDict):
    code: str
    """unsupported_type, quota, ocr_unavailable, ocr_error, timeout, parse_error, ..."""
    message: str


class AttachmentExtraction(TypedDict):
    """Text extraction of an inbound attachment. Read the text with ``messages.attachment_text``."""

    status: ExtractionStatus
    method: Optional[ExtractionMethod]
    pages: Optional[int]
    chars: Optional[int]
    language: Optional[str]
    truncated: bool
    error: Optional[ExtractionError]
    updated_at: Optional[str]


class _AttachmentBase(TypedDict):
    id: str
    filename: Optional[str]
    content_type: str
    size_bytes: int
    sha256: str
    content_id: Optional[str]
    inline: bool
    available: bool


class Attachment(_AttachmentBase, total=False):
    extraction: Optional[AttachmentExtraction]
    """``None`` for outbound mail and attachments stored before extraction existed."""


class AttachmentText(TypedDict):
    """``messages.attachment_text``: ``text`` is ``None`` until ``extraction.status`` is ``done``.

    The text is untrusted: it comes from a document someone emailed."""

    attachment_id: str
    message_id: str
    filename: Optional[str]
    content_type: str
    extraction: Optional[AttachmentExtraction]
    text: Optional[str]
    offset: int
    total_chars: Optional[int]
    next_offset: Optional[int]
    """Pass as ``offset`` to read the next page; ``None`` at the end."""
    untrusted: bool


class StructuredExtraction(TypedDict):
    """``messages.extract_attachment``: ``data`` validates against the schema but is untrusted."""

    attachment_id: str
    message_id: str
    schema: str
    data: dict[str, Any]
    model: str
    repaired: bool
    truncated: bool
    untrusted: bool


class AttachmentInput(TypedDict):
    """An attachment to send. Build one with ``attachment_from_path`` / ``attachment_from_bytes``."""

    filename: str
    content_type: str
    content_base64: str


class _VerificationInfoBase(TypedDict):
    code: Optional[str]
    """One-time code (4-10 chars, digits or alphanumeric), if found."""
    link: Optional[str]
    """Verification / magic / confirm link, if found."""
    confidence: float
    """0-1. Regex-only detection is capped at 0.7; JEV confirmation raises or lowers it."""
    jev_probability: Optional[float]
    """JEV's probability that this is a verification/login email, once enrichment has run."""


class VerificationInfo(_VerificationInfoBase, total=False):
    """Login/verification code or magic link found in a message."""

    auth_failed: bool
    """The sender failed authentication (DMARC, or SPF without aligned DKIM): the code may come from a
    spoofer. Don't use it unless you just asked for one. Absent on older servers."""


class MessageCategoryInfo(TypedDict):
    """JEV's category for a message."""

    label: MessageCategory
    confidence: float
    """0-1. ``label`` becomes an ``ai:<label>`` label only at 0.6 or more (else ``ai:uncertain``)."""
    probabilities: dict[MessageCategory, float]
    """Probability of each category JEV returned (not necessarily all eight)."""


class MessageRisk(TypedDict):
    """Yes-probabilities (0-1). ``ai:injection-risk`` / ``ai:phishing`` are added at 0.8 or more."""

    injection: float
    """The message tries to instruct an AI (ignore rules, reveal data, act for the sender)."""
    phishing: float
    """Credential harvesting, scam or impersonation."""


class MessageUrgency(TypedDict):
    level: UrgencyLevel
    """Most likely level. ``high`` and ``critical`` add the ``ai:urgent`` label."""
    score: float
    """Expected score from 0 (low) to 3 (critical); may fall between levels."""
    confidence: float


class _MessageAiBase(TypedDict):
    verification: Optional[VerificationInfo]


class MessageAi(_MessageAiBase, total=False):
    """AI/derived data attached to a message.

    ``verification`` is always present. The other keys appear only once JEV enrichment has run
    (the server needs ``TYPESAFE_API_KEY``), so read them with ``.get()``. A ``message.enriched``
    webhook fires when they are added.
    """

    category: MessageCategoryInfo
    risk: MessageRisk
    needs_human: float
    """Yes-probability (0-1) that a person should handle it. ``ai:needs-human`` at 0.7 or more."""
    urgency: MessageUrgency
    auto_reply: float
    """Yes-probability (0-1) of an out-of-office / auto-responder / bulk mail. ``ai:auto-reply`` at 0.8."""
    model: str
    """Engine that produced the fields above (``"jev"``)."""
    enriched_at: str
    """When enrichment finished (ISO 8601)."""
    analysis_coverage: Literal["full", "partial"]
    """Whether enrichment read the whole message. Prefer ``message["analysis"]``."""
    enrichment_error: str
    """Set when enrichment gave up after retries; the message is otherwise unaffected."""
    enrichment_skipped: Literal["quota", "ai_off", "not_available"]
    """Why enrichment didn't run. Prefer ``message["analysis"]``."""
    local_screen: "LocalScreen"
    """The local injection check (no AI, every received message since Screening v2)."""
    local_spam: "LocalSpam"
    """Why the message got ``local:spam``."""
    released_at: str
    """A held message released to agents: when. Prefer ``message["screening"]``."""
    released_by: str
    """Who released it: ``user:<id>`` or ``key:<id>``."""


ScreeningState = Literal["screened", "pending", "held", "released"]
ScreeningReason = Literal[
    "ai_off",
    "not_applicable",
    "not_available",
    "injection_risk",
    "phishing",
    "check_failed",
    "quota",
    "check_timed_out",
    "blocked",
    "partially_screened",
]


class MessageScreening(TypedDict):
    """Whether agents get a received message.

    When the workspace screens agent mail (the default for new workspaces), claim and ``wait`` return
    only ``screened`` and ``released`` mail unless you pass ``include_unscreened`` / ``include_held``.
    """

    state: ScreeningState
    reason: Optional[ScreeningReason]
    """Why it is held, or why it counts as screened without a check (``ai_off``, ``not_available``,
    ``not_applicable``)."""
    released_at: Optional[str]


class MessageWithheld(TypedDict):
    """What was left out of a withheld message."""

    state: ScreeningState
    reason: Optional[ScreeningReason]
    attachments: int


class LocalScreenReason(TypedDict, total=False):
    code: str
    weight: float
    where: Literal["visible", "hidden", "beyond_window", "attachment"]
    detail: str


class LocalScreen(TypedDict):
    """The local injection check: no AI, run on every received message. It reads the whole message,
    including HTML text hidden from a human reader. At ``score`` 0.6 or more the message gets
    ``local:injection-risk``."""

    score: float
    flagged: bool
    reasons: list[LocalScreenReason]
    hidden_chars: int
    """Characters of HTML text hidden from a sighted reader."""
    complete: bool
    """False when some text was too long to scan in full."""
    version: int


class LocalSpam(TypedDict):
    reasons: list[str]


class MessageAnalysis(TypedDict):
    """Whether a received message was checked for prompt injection and phishing, and how much of it.

    A message without an ``ai:injection-risk`` or ``ai:phishing`` label is only known to be clean when
    ``state`` is ``"completed"`` and ``coverage`` is ``"full"``.
    """

    state: Literal["pending", "completed", "skipped", "failed"]
    coverage: Optional[Literal["full", "partial"]]
    """Completed only. ``partial``: some of the message wasn't read (a long body or data, attachment text
    cut or not extracted)."""
    reason: Optional[Literal["quota", "ai_off", "not_available", "blocked", "not_applicable"]]
    """Skipped only."""


# ``from`` is a Python keyword, so these use the functional TypedDict syntax.
_VerificationResultBase = TypedDict(
    "_VerificationResultBase",
    {
        "code": Optional[str],
        "link": Optional[str],
        "confidence": float,
        "jev_probability": Optional[float],
        "message_id": str,
        "from": str,
        "subject": Optional[str],
        "received_at": Optional[str],
    },
)


class VerificationResult(_VerificationResultBase, total=False):
    """``GET /v1/inboxes/{id}/verification``: the newest code or link and the message it came from."""

    auth_failed: bool
    """Only ``True`` with ``include_unauthenticated=True``: the sender failed authentication."""


_MessageBase = TypedDict(
    "_MessageBase",
    {
        "id": str,
        "inbox_id": str,
        "thread_id": str,
        "direction": Direction,
        "status": MessageStatus,
        "rfc_message_id": str,
        "in_reply_to": Optional[str],
        "references": list[str],
        "from": str,
        "to": list[str],
        "cc": list[str],
        "bcc": list[str],
        "reply_to": Optional[str],
        "subject": Optional[str],
        "text": Optional[str],
        "html": Optional[str],
        # The new content of the message only: quoted history and signatures removed.
        "extracted_text": Optional[str],
        # text, html and extracted_text were cut (a list, search, thread, claim or batch-get):
        # messages.get() has all of it.
        "body_truncated": bool,
        "headers": dict[str, Union[str, list[str]]],
        "labels": list[str],
        "is_read": bool,
        "provider_message_id": Optional[str],
        "size_bytes": int,
        "sent_at": Optional[str],
        "received_at": Optional[str],
        "created_at": str,
        "attachments": list[Attachment],
        # Derived data: verification codes, plus JEV categories and risk scores once enriched. Never null.
        "ai": MessageAi,
    },
)


class MessageDelivery(TypedDict):
    """Outbound messages: where one recipient's copy went."""

    address: str
    channel: Literal["agent", "email"]
    status: Literal["queued", "delivered", "sent", "bounced"]


_MessageAgentBase = TypedDict(
    "_MessageAgentBase",
    {
        "verified": bool,
        # The sender's address, as verified by Agentboxd at delivery.
        "from": str,
        "assurance": AgentAssurance,
        "signed_at": Optional[str],
        "kid": Optional[str],
        # Compact JWS (ES256, typ agentboxd-msg+jwt), bound to this copy's recipient.
        "signature": Optional[str],
    },
)


class MessageAgent(_MessageAgentBase, total=False):
    """Inbound agent-channel copies: the sender verified at delivery and the per-copy signature
    (``agentboxd.identity.verify_agent_message`` checks it outside Agentboxd). A verified sender is not
    trustworthy content."""

    reason: str
    """Why ``verified`` is false: ``revoked`` (the owner revoked its agent card) or ``suspended`` (the
    operator suspended it); such senders are no longer signed."""


class _MessageAuthorBase(TypedDict):
    verified: bool
    kid: str
    """The RFC 7638 thumbprint of the agent's own key."""
    alg: Literal["EdDSA", "ES256"]
    signature: str
    """Compact JWS (typ ``agentboxd-author+jwt``) made by the sending agent with its own key."""


class MessageAuthor(_MessageAuthorBase, total=False):
    """aSIM phase 2: the sending agent's own author signature, checked by Agentboxd at send and re-checked at
    delivery. ``agentboxd.identity.verify_author_signature`` checks it outside Agentboxd."""

    reason: str
    """Why ``verified`` is false: ``key_revoked`` or ``key_unknown``."""


class AiDisclosure(TypedDict):
    """The ``Agent-Disclosure`` header of a message, parsed. Inbound: untrusted unless ``verified``."""

    agent: bool
    on_behalf_of: Optional[str]
    operator: Optional[str]
    verified: bool
    """True only for mail from an Agentboxd sender (internal delivery, or a DKIM pass for its domain)."""
    header: str


CalendarMethod = Literal[
    "REQUEST", "CANCEL", "REPLY", "COUNTER", "DECLINECOUNTER", "PUBLISH", "REFRESH", "ADD"
]
"""iTIP methods (RFC 5546) a calendar message can carry."""


class MessageCalendar(TypedDict):
    """Meetings: the meeting a message's invite, update, answer or cancellation is about."""

    event_id: Optional[str]
    """The meeting the message created or changed: read it with ``calendar.get(event_id)``. None when it
    changed none (an older version of the invite, or a sender who can't speak for the organizer)."""
    method: CalendarMethod


class Message(_MessageBase, total=False):
    contact_id: Optional[str]
    """Inbound: the sender's contact. Outbound: the first recipient that is a contact."""
    channel: MessageChannel
    """Agent messaging (absent on servers before it)."""
    type: MessageType
    data: Any
    """The sender's structured data (a JSON object or array), or None. Untrusted input, like the text."""
    delivery: Optional[list[MessageDelivery]]
    """Outbound only: per-recipient channel and outcome."""
    agent: Optional[MessageAgent]
    """Inbound agent-channel copies only."""
    author: Optional[MessageAuthor]
    """The agent's own author signature (outbound rows and inbound agent copies), or None."""
    approval: Optional["MessageApproval"]
    """Sent from a draft: who approved it, when, and the content hash it covered.
    Kept after the draft is deleted."""
    ai_disclosure: Optional[AiDisclosure]
    """AI disclosure: what was disclosed (outbound) or the sender's header (inbound). None when absent."""
    analysis: Optional[MessageAnalysis]
    """Received mail: whether it was checked for prompt injection and phishing. None for sent mail."""
    screening: Optional["MessageScreening"]
    """Received mail: whether agents get it (screened, pending, held, released). None for sent mail."""
    withheld: "MessageWithheld"
    """Set when the content was withheld from this key (held or not screened yet): subject, text, html,
    headers, attachments, data and the detected code are left out unless you opt in."""
    auto_reply: bool
    """Received mail: an automatic reply (out of office and the like), from its headers or the
    ``ai:auto-reply`` label. Don't answer it. False for sent mail."""
    calendar: Optional[MessageCalendar]
    """Meetings: set on a message that carries a meeting: an invite once it is read, and every
    answer, invitation, change and cancellation the inbox sends. None for other messages, for an invite not
    read yet (so None in ``message.received``; ``calendar.invite.received`` follows) and while the message
    is withheld. Absent on older servers."""


# ---------- meetings (calendar, beta) ----------

CalendarEventRole = Literal["attendee", "organizer"]
"""``attendee``: the inbox was invited (read from an invite it received). ``organizer``: the inbox sent it."""
CalendarEventStatus = Literal["tentative", "confirmed", "cancelled"]
CalendarResponse = Literal["needs_action", "accepted", "declined", "tentative"]
"""The inbox's own answer to an invite (attendee events)."""
CalendarAnswer = Literal["accepted", "declined", "tentative"]
"""What ``calendar.respond`` sends."""
CalendarPartstat = Literal["needs_action", "accepted", "declined", "tentative", "delegated"]


class CalendarPerson(TypedDict):
    email: str
    name: Optional[str]
    """None when the invite gave none, or while the invite is withheld."""


class _CalendarAttendeeBase(TypedDict):
    email: str
    name: Optional[str]
    role: Optional[str]
    """``req_participant``, ``opt_participant``, ``chair``, ``non_participant``, or None."""
    partstat: CalendarPartstat
    rsvp: bool


class CalendarAttendee(_CalendarAttendeeBase, total=False):
    responded_at: Optional[str]
    """Organizer events: when this attendee's last answer was applied."""


CalendarProposal = TypedDict(
    "CalendarProposal",
    {"from": str, "start": str, "end": str, "message_id": str, "received_at": str},
)
"""A new time an attendee proposed (an iTIP COUNTER) for one of the inbox's own meetings."""


class CalendarConference(TypedDict):
    """A join link, only for links on known video meeting hosts."""

    provider: str
    url: str


class CalendarRecurrence(TypedDict):
    """A series: its RRULE (None when it only has extra dates), extra dates and left-out dates.
    ``calendar.list(..., expand="occurrences")`` lists the occurrences."""

    rrule: Optional[str]
    rdates: list[str]
    exdates: list[str]


class CalendarWithheld(TypedDict):
    """Why an event's content was left out (its invite is held or not screened yet)."""

    state: ScreeningState
    reason: Optional[ScreeningReason]


class _CalendarEventBase(TypedDict):
    id: str
    inbox_id: str
    uid: str
    recurrence_id: Optional[str]
    sequence: int
    role: CalendarEventRole
    status: CalendarEventStatus
    response: Optional[CalendarResponse]
    """The inbox's answer (attendee events); None for its own meetings."""
    responded_at: Optional[str]
    reply_expected: bool
    """False for a published calendar entry (nothing to answer)."""
    title: Optional[str]
    description: Optional[str]
    location: Optional[str]
    url: Optional[str]
    conference: Optional[CalendarConference]
    start: str
    """UTC."""
    end: str
    all_day: bool
    time_zone: Optional[str]
    floating: bool
    """The invite's times had no usable time zone and were read as UTC."""
    recurrence: Optional[CalendarRecurrence]
    organizer: CalendarPerson
    organizer_verified: bool
    """An authenticated sender vouches for the organizer (DMARC pass and a matching domain or a calendar
    service)."""
    attendees: list[CalendarAttendee]
    proposals: list[CalendarProposal]
    source: str
    """``invite`` (read from mail) or ``agent`` (the inbox created it)."""
    message_id: Optional[str]
    """The invite message the content came from; None for the inbox's own meetings."""
    screening: Optional[MessageScreening]
    created_at: str
    updated_at: str


class CalendarEvent(_CalendarEventBase, total=False):
    """A meeting known to an inbox. An invite is untrusted input like the email it came in: title,
    description, location and names are written by its sender."""

    withheld: CalendarWithheld
    """Set when the content was withheld from this key (the invite is held or not screened yet): it can't
    be answered until a person releases the invite."""
    series_id: Optional[str]
    """Only in a list with ``expand="occurrences"``: the series this occurrence belongs to (None for a
    single meeting). An occurrence keeps the series' ``id`` (respond, update and cancel act on the whole
    series) and has its own ``start``, ``end`` and ``recurrence_id``."""


class _CalendarEventPageBase(TypedDict):
    data: list[CalendarEvent]
    next_cursor: Optional[str]


class CalendarEventPage(_CalendarEventPageBase, total=False):
    """A page of ``calendar.list`` / ``calendar.list_all``. Pass ``next_cursor`` as ``cursor`` to continue."""

    truncated: bool
    """With ``expand="occurrences"`` only: True when a series had more occurrences in the window than one
    list gives (500), or a rule too costly to follow. Ask for a shorter window."""


class _CalendarAttendeeInputBase(TypedDict):
    email: str


class CalendarAttendeeInput(_CalendarAttendeeInputBase, total=False):
    name: str
    optional: bool
    """An optional guest."""


class _CalendarEventResultBase(TypedDict):
    event: CalendarEvent
    message: Message


class CalendarEventResult(_CalendarEventResultBase, total=False):
    """What ``respond``, ``create`` and ``update`` return: the event as it now is and the email sent."""

    draft: None
    """None: nothing was drafted (absent on older servers)."""


class CalendarDraftResult(TypedDict):
    """What ``respond``, ``create`` and ``update`` return with ``draft=True``: nothing was sent, and
    ``draft`` waits for a person (``draft["calendar"]`` says what sending it does). ``event`` is the meeting
    as it still is; None for a new meeting, which exists once the draft is sent (under
    ``draft["calendar"]["event_id"]``)."""

    event: Optional[CalendarEvent]
    message: None
    draft: "Draft"


class _CalendarCancelResultBase(TypedDict):
    event: CalendarEvent
    message: Optional[Message]
    """None when the meeting was already cancelled (nothing is sent)."""


class CalendarCancelResult(_CalendarCancelResultBase, total=False):
    draft: None


class CalendarCancelDraftResult(TypedDict):
    """What ``cancel`` returns with ``draft=True``. ``draft`` is None when the meeting was already cancelled
    (nothing to draft)."""

    event: CalendarEvent
    message: None
    draft: Optional["Draft"]


class Lease(TypedDict):
    """One claimed message (claim/ack queue). Present ``lease_id`` to ack, nack or extend."""

    lease_id: str
    lease_until: str
    delivery_count: int
    """1 on the first delivery; higher means a redelivery (a lease ran out or was nacked)."""
    message: Message


class LeaseClaim(TypedDict):
    """``messages.claim()``. ``paused`` is true while the inbox is paused (nothing is claimable)."""

    data: list[Lease]
    paused: bool


class AckResult(TypedDict, total=False):
    """``messages.ack()``: ``acked_at``, or ``gone: True`` when the message was deleted meanwhile."""

    id: str
    acked_at: str
    gone: bool


class NackResult(TypedDict, total=False):
    """``messages.nack()``. ``dead_letter`` is true when this was the last allowed delivery."""

    id: str
    delivery_count: int
    available_at: str
    dead_letter: bool
    gone: bool


class ExtendResult(TypedDict, total=False):
    id: str
    lease_id: str
    lease_until: str
    gone: bool


class SearchResult(Message):
    rank: float
    snippet: str


class _ThreadBase(TypedDict):
    id: str
    inbox_id: str
    subject: Optional[str]
    participants: list[str]
    message_count: int
    last_message_at: str
    created_at: str


class Thread(_ThreadBase, total=False):
    labels: list[str]
    metadata: Metadata


class ThreadWithMessages(Thread):
    messages: list[Message]


class DeletedThread(TypedDict):
    """``threads.delete``: what was removed."""

    deleted: bool
    messages: int
    attachments: int


class BatchMessages(TypedDict):
    """``messages.batch_get`` / ``batch_update``: the messages, and ids you can't see."""

    data: list[Message]
    missing: list[str]


ContactKind = Literal["person", "automated", "sales", "unknown"]
"""Who is behind a contact. ``unknown`` until the AI category of their mail sorts it (sales and
newsletters -> ``sales``, notifications and verification codes -> ``automated``, the rest -> ``person``);
writing to an address makes it a ``person``."""


class _ContactBase(TypedDict):
    id: str
    address: str
    name: Optional[str]
    notes: Optional[str]
    metadata: Metadata
    labels: list[str]
    message_count: int
    """Messages involving the address (from it, or to/cc/bcc it)."""
    first_seen_at: str
    last_seen_at: str
    created_at: str


class Contact(_ContactBase, total=False):
    """An external address the workspace has exchanged mail with (created automatically; automated
    senders never are). The keys below are always present on current servers."""

    kind: ContactKind
    kind_source: Literal["auto", "manual"]
    """``manual`` once set with ``update(kind=...)``: later mail never changes it."""
    name_source: Literal["auto", "manual"]
    """``manual`` once set with ``update(name=...)``: mail never replaces it."""
    domain: str
    """The part of the address after the @."""
    last_subject: Optional[str]
    """Subject of the newest message with this contact, without Re:/Fwd:."""


class ContactDomain(TypedDict):
    """``contacts.domains``: contacts per domain (free-mail providers left out)."""

    domain: str
    contacts: int
    last_seen_at: Optional[str]


class ContactDomainList(TypedDict):
    data: list[ContactDomain]


class ContactBulkDeleteResult(TypedDict):
    """``contacts.delete_many``: ``matched`` (dry run: would be deleted), ``deleted``, ``forgotten``, and
    ``has_more`` when more than 1,000 matched (call again)."""

    matched: int
    deleted: int
    forgotten: int
    has_more: bool
    dry_run: bool


class ContactWithThreads(Contact):
    recent_threads: list[Thread]
    """Up to 10 newest threads (all inboxes) with this address."""


class KnowledgeDoc(TypedDict):
    """Reference text for reply drafts. ``inbox_id`` None = every inbox of the workspace."""

    id: str
    inbox_id: Optional[str]
    title: str
    body: str
    created_at: str
    updated_at: str


class KnowledgeListItem(TypedDict):
    id: str
    inbox_id: Optional[str]
    title: str
    excerpt: str
    """First 200 characters of the body (lists never include the body)."""
    created_at: str
    updated_at: str


class KnowledgeSearchResult(TypedDict):
    id: str
    title: str
    inbox_id: Optional[str]
    rank: float
    snippet: str


class KnowledgeSearchResults(TypedDict):
    data: list[KnowledgeSearchResult]


class DraftCitation(TypedDict):
    knowledge_id: str
    title: str


DraftStatus = Literal["draft", "scheduled", "sending", "sent", "failed", "cancelled"]
"""``draft`` → ``scheduled`` → ``sending`` → ``sent`` | ``failed`` | ``cancelled``."""


class DraftAttachment(TypedDict):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str


class DraftError(TypedDict):
    """Why the last send attempt was refused (API error code and message)."""

    code: str
    message: str


class DraftApprover(TypedDict):
    """Who approved a draft's send: a person (``label`` = email), an API key (its name), a connector, or a
    ``policy``: a code-level approval policy, not a person or a key (``label`` names it, e.g. "Inbox Heist
    vault policy")."""

    type: Literal["user", "api_key", "connector", "policy"]
    id: str
    label: str


class MessageApproval(TypedDict):
    """An outbound message's approval, copied from its draft at send time."""

    draft_id: str
    by: DraftApprover
    at: str
    content_sha256: str


class DraftCalendar(TypedDict):
    """``draft["calendar"]``: what sending a meeting draft does. The meeting changes only when the draft is
    sent."""

    action: Literal["respond", "create", "update", "cancel"]
    """``respond``: answer an invite. ``create``: a new meeting. ``update``: change one. ``cancel``: cancel
    one."""
    method: Literal["REQUEST", "CANCEL", "REPLY", "COUNTER"]
    """iTIP method of the calendar file it carries (``COUNTER`` for an answer that proposes another time)."""
    event_id: str
    """The meeting; for ``create``, the id it gets once the draft is sent."""
    removed_attendees: list[str]
    """``update``: attendees the change takes off the meeting (they get a cancellation with it)."""


class _DraftExtras(TypedDict, total=False):
    type: MessageType
    """Agent messaging: sent as the message's type and data."""
    data: Any
    calendar: Optional[DraftCalendar]
    """A meeting draft (made by the ``calendar`` calls with ``draft=True``): what sending it does to which
    meeting. Its recipients come from the meeting (changing ``to``, ``cc``, ``bcc``, ``type`` or ``data`` is
    422 ``calendar_draft_fixed``). None for other drafts; absent on older servers."""


class Draft(_DraftExtras):
    """A message waiting for review, approval or its ``send_at``.

    Once sent, ``text``/``html``/``attachments`` are cleared: read the message ``sent_message_id``.
    """

    id: str
    inbox_id: str
    status: DraftStatus
    reply_to_message_id: Optional[str]
    thread_id: Optional[str]
    reply_all: bool
    to: list[str]
    cc: list[str]
    bcc: list[str]
    subject: Optional[str]
    text: Optional[str]
    html: Optional[str]
    attachments: list[DraftAttachment]
    metadata: Metadata
    labels: list[str]
    source: Literal["api", "ai"]
    """``ai`` when saved by ``messages.draft_reply(..., save=True)``."""
    send_at: Optional[str]
    sent_at: Optional[str]
    sent_message_id: Optional[str]
    approved_by: Optional[DraftApprover]
    """Who sent it, scheduled it, or last changed what it sends while scheduled; ``None`` until then."""
    approved_at: Optional[str]
    approved_content_sha256: Optional[str]
    """SHA-256 of the content the approval covers; a change to what a scheduled draft sends unschedules it."""
    error: Optional[DraftError]
    created_at: str
    updated_at: str


class DraftSendResult(TypedDict):
    """``drafts.send``: the draft (now ``sent``) and the queued message."""

    draft: Draft
    message: "Message"


class DraftKeep(TypedDict):
    """In ``drafts.update(attachments=...)``: keep an attachment already on the draft."""

    id: str


class _DraftReplyBase(TypedDict):
    text: str
    citations: list[DraftCitation]
    model: str


class DraftReply(_DraftReplyBase, total=False):
    """A reply draft. Nothing is sent: review it, then call ``messages.reply``.

    With ``save=True`` it also carries ``draft``: the stored Draft, to send with ``drafts.send``."""

    draft: Draft


# Generic TypedDicts are only supported at runtime from Python 3.11; type checkers always see
# the generic form, older interpreters get an equivalent plain-dict class.
if TYPE_CHECKING or sys.version_info >= (3, 11):

    class Page(TypedDict, Generic[_T]):
        """One page of a cursor-paginated list. Pass ``next_cursor`` as ``cursor`` to continue."""

        data: list[_T]
        next_cursor: Optional[str]

else:  # pragma: no cover - exercised on Python < 3.11 only

    class Page(dict[str, Any], Generic[_T]):
        """One page of a cursor-paginated list. Pass ``next_cursor`` as ``cursor`` to continue."""


class _WebhookRequired(TypedDict):
    id: str
    url: str
    events: list[WebhookEventType]
    inbox_ids: Optional[list[str]]
    enabled: bool
    created_at: str


class WebhookStats(TypedDict):
    """Delivery stats over the last 24 hours."""

    deliveries_24h: int
    failed_24h: int
    error_rate_24h: float
    last_success_at: Optional[str]
    last_failure_at: Optional[str]


class Webhook(_WebhookRequired, total=False):
    secret: str
    """Only returned by ``webhooks.create``."""
    secret_hint: str
    payload: WebhookPayload
    stats: WebhookStats


_EnvelopeEventDataBase = TypedDict(
    "_EnvelopeEventDataBase",
    {
        "inbox_id": Optional[str],
        "thread_id": Optional[str],
        "message_id": Optional[str],
        "from": Optional[str],
        "to": list[str],
        "subject": Optional[str],
        "labels": list[str],
        "received_at": Optional[str],
    },
)


class EnvelopeEventData(_EnvelopeEventDataBase, total=False):
    """``data`` of an event sent to a webhook with ``payload="envelope"`` (no bodies, no AI content)."""

    channel: MessageChannel
    """Agent messaging (never the data itself)."""
    type: MessageType


class WebhookCatalogEntry(TypedDict):
    """One entry of ``GET /v1/webhooks/events``."""

    type: Union[WebhookEventType, Literal["webhook.test"]]
    description: str
    example: dict[str, Any]
    envelope_example: dict[str, Any]


class ListEntry(TypedDict):
    """An allow/block list entry. ``inbox_id`` None = the whole workspace."""

    id: str
    inbox_id: Optional[str]
    direction: ListDirection
    kind: ListKind
    pattern: str
    """``a@b.com`` (exact address) or ``b.com`` (the domain and its subdomains)."""
    type: Literal["address", "domain", "token"]
    """``token``: a receive-list token (``agents:any``, ``agents:verified``, ``workspace:self``)."""
    created_at: str


class ListEntries(TypedDict):
    data: list[ListEntry]


class MetricCounts(TypedDict):
    sent: int
    received: int
    delivered: int
    bounced: int
    complained: int
    blocked: int


class MetricsPoint(MetricCounts):
    t: str
    """Start of the bucket (ISO 8601, UTC)."""


class BounceReason(TypedDict):
    status: str
    count: int


class Deliverability(TypedDict):
    delivered_rate: float
    bounce_rate: float
    complaint_rate: float
    bounce_reasons: list[BounceReason]


class InboundQuality(TypedDict):
    spam: int
    blocked: int
    unauthenticated: int


class HeatmapDay(TypedDict):
    date: str
    sent: int
    received: int


class BusiestDay(TypedDict):
    date: str
    count: int


class Streak(TypedDict):
    longest_days: int
    busiest_day: Optional[BusiestDay]


class DeliverabilityWindow(TypedDict):
    sent: int
    bounced: int
    complained: int
    bounce_rate: float
    complaint_rate: float


class DeliverabilityRates(TypedDict):
    last_7_days: DeliverabilityWindow
    last_30_days: DeliverabilityWindow


class DeliverabilityThresholds(TypedDict):
    bounce_rate: float
    complaint_rate: float
    min_sent: int


class DomainAuth(TypedDict):
    id: str
    domain: str
    status: DomainStatus
    spf: Literal["ok", "missing", "mismatch"]
    dkim: Literal["ok", "missing", "mismatch"]
    dmarc: Literal["ok", "missing", "mismatch"]
    dkim_rotation_due: bool


class _BlocklistEntryBase(TypedDict):
    name: str
    status: Literal["clean", "listed", "unknown", "skipped"]


class BlocklistEntry(_BlocklistEntryBase, total=False):
    codes: list[str]
    """Return codes when listed (e.g. ``127.0.0.2``)."""


class IpReputation(TypedDict):
    status: Literal["clean", "listed", "partial", "unknown", "stale", "not_checked"]
    checked_at: Optional[str]
    lists: list[BlocklistEntry]


class SharedSending(TypedDict):
    sending_domain: str
    ip_reputation: IpReputation


class DeliverabilitySummary(TypedDict):
    """``deliverability()``: what affects whether your mail reaches the inbox."""

    rates: DeliverabilityRates
    thresholds: DeliverabilityThresholds
    """Sending is suspended above these rates over 7 days (with at least ``min_sent`` sends)."""
    suppressed_contacts: int
    """Your contacts whose address is suppressed (hard bounce or complaint)."""
    domains: list[DomainAuth]
    shared: SharedSending


class Resources(TypedDict):
    inboxes: int
    domains: int
    threads: int
    messages: int
    storage_bytes: int


class QueueMetrics(TypedDict):
    """Claim/ack queue state of one inbox that has used it (``Metrics["queue"]``)."""

    inbox_id: str
    address: str
    started_at: str
    depth: int
    in_flight: int
    dead_letters: int
    oldest_waiting_at: Optional[str]


Metrics = TypedDict(
    "Metrics",
    {
        "from": str,
        "to": str,
        "tz": str,
        "bucket": MetricsBucket,
        "inbox_id": Optional[str],
        "series": list[MetricsPoint],
        "totals": MetricCounts,
        "deliverability": Deliverability,
        "inbound": InboundQuality,
        "heatmap": list[HeatmapDay],
        "streak": Streak,
        "resources": Resources,
        "queue": list[QueueMetrics],
    },
)
"""``GET /v1/metrics``: counts bucketed in ``tz``, a 30-day heatmap and resource totals."""


class WebhookTestResult(TypedDict):
    event_id: str
    delivery_id: str


WebhookDeliveryStatus = Literal["pending", "succeeded", "failed"]


class WebhookDelivery(TypedDict):
    """``GET /v1/webhooks/{id}/deliveries``: one event sent to one webhook, as of its latest attempt.

    ``attempts`` is the attempt number, ``last_*`` its answer (``last_response_ms``: how long it took),
    ``next_attempt_at`` when the next retry is due (``None`` once it succeeded or gave up).
    """

    id: str
    webhook_id: str
    event_id: str
    event_type: str
    status: WebhookDeliveryStatus
    attempts: int
    last_status_code: Optional[int]
    last_error: Optional[str]
    last_response_ms: Optional[int]
    next_attempt_at: Optional[str]
    last_attempt_at: Optional[str]
    redelivered_at: Optional[str]
    created_at: str


SuppressionReason = Literal["bounce", "complaint", "manual"]


class Suppression(TypedDict):
    """An address on the workspace's own suppression list (``GET /v1/suppressions``)."""

    address: str
    reason: SuppressionReason
    created_at: str
    expires_at: Optional[str]


class _MessageEventDataRequired(TypedDict):
    inbox: Inbox
    thread_id: str
    message: Message


class MessageEventData(_MessageEventDataRequired, total=False):
    bounce: Any
    complaint: Any


class StreamEvent(TypedDict):
    """One event from :meth:`AsyncAgentboxd.stream`: exactly a webhook body. ``data`` is a
    :class:`MessageEventData` (``payload="full"``), an :class:`EnvelopeEventData` (``payload="envelope"``)
    or ``{"inbox": ...}`` for ``inbox.expired``."""

    id: str
    type: str
    created_at: str
    data: Any


class StreamToken(TypedDict):
    """``POST /v1/stream/token``: a single-use, 60-second URL for ``GET /v1/stream``."""

    token: str
    expires_at: str
    url: str


class WebhookEvent(TypedDict):
    """Body of every webhook POST."""

    id: str
    type: Union[WebhookEventType, Literal["webhook.test"]]
    created_at: str
    data: MessageEventData


# ---------- agent identity (Sign in with Agentboxd) ----------

IdentityScope = Literal["openid", "email", "profile", "workspace"]
IdentityClientType = Literal["confidential", "public", "verify_only"]
"""``confidential``: has a client secret · ``public``: no secret, PKCE · ``verify_only``: only receives
headless identity tokens and verifies them against the JWKS."""
IdentitySubjectType = Literal["pairwise", "public"]
IdentityFlow = Literal["headless", "authorization_code", "jwt_bearer"]


class IdentityClient(TypedDict):
    """An app ("relying party") registered by the workspace. ``client_id`` is public (the tokens' ``aud``)."""

    id: str
    client_id: str
    name: str
    type: IdentityClientType
    redirect_uris: list[str]
    allowed_scopes: list[IdentityScope]
    subject_type: IdentitySubjectType
    homepage_url: Optional[str]
    secret_prefix: Optional[str]
    enabled: bool
    last_used_at: Optional[str]
    created_at: str
    updated_at: str


class _IdentityClientWithSecretBase(TypedDict):
    client: IdentityClient


class IdentityClientWithSecret(_IdentityClientWithSecretBase, total=False):
    """Create and secret rotation. ``client_secret`` is only returned here, once (confidential clients)."""

    client_secret: Optional[str]


class IdentityToken(TypedDict):
    """A short-lived (at most 5 minutes), single-use OpenID Connect ID token for one relying party."""

    id_token: str
    token_type: Literal["id_token"]
    issuer: str
    audience: str
    sub: str
    jti: str
    scope: str
    expires_in: int
    expires_at: str


class InboxIdentityApp(TypedDict):
    client_id: str
    name: str
    homepage_url: Optional[str]
    last_signed_in_at: str
    sign_ins: int


class _InboxIdentityBase(TypedDict):
    inbox_id: str
    enabled: bool
    apps: list[InboxIdentityApp]


class InboxIdentity(_InboxIdentityBase, total=False):
    """The inbox's "Sign in with Agentboxd" switch and the apps it signed into."""

    kind: Literal["mailbox", "identity"]
    """``identity`` for an identity-only agent."""


class Identity(TypedDict):
    """An identity-only agent: an Agentboxd identity (sign in to apps) without a mailbox.

    ``address`` is a stable handle on the agent domain; nothing is delivered to it and tokens never carry
    it as ``email``."""

    id: str
    kind: Literal["identity"]
    address: str
    username: str
    display_name: Optional[str]
    client_id: Optional[str]
    metadata: Metadata
    identity_enabled: bool
    status: Literal["active", "paused"]
    paused_at: Optional[str]
    paused_reason: Optional[str]
    created_at: str


class IdentitySignIn(TypedDict):
    id: str
    inbox_id: str
    client_id: str
    client_name: str
    event: Literal["token_issued", "signed_in"]
    flow: IdentityFlow
    jti: str
    ip: Optional[str]
    created_at: str


# ---------- agent self-signup ----------


class SignupChallenge(TypedDict):
    """``GET /v1/signup/challenge``.

    Find a decimal ``solution`` such that SHA-256(challenge + ":" + solution) starts with ``difficulty``
    zero bits (:func:`agentboxd.solve_signup_challenge`)."""

    challenge: str
    algorithm: Literal["sha256"]
    difficulty: int
    expires_at: str
    instructions: str
    terms: str
    terms_url: str


class SignupWorkspace(TypedDict):
    """An agent-created workspace: ``unclaimed`` until a human claims it."""

    id: str
    name: str
    status: Literal["unclaimed", "claimed"]
    created_at: str
    claimed_at: Optional[str]


class UnclaimedRestrictions(TypedDict, total=False):
    """What an unclaimed workspace may do."""

    recipients_per_day: int
    """Distinct recipients per UTC day (429 ``unclaimed_recipient_limit`` past it)."""
    replies_to_inbound_threads: Literal["unlimited"]
    inboxes: int
    identities: int
    identity_tokens: bool
    """``False`` until a human claims the workspace (identity tokens are refused)."""
    webhooks: bool
    custom_domains: bool
    event_stream: bool
    expires_after_inactive_days: int
    recipients_today: int
    """``GET /v1/account`` only."""


class SignupClaim(TypedDict):
    status: Literal["email_sent", "not_requested", "email_failed"]
    email: Optional[str]
    """Masked, e.g. ``o***@example.com``."""


class _SignupResultBase(TypedDict):
    api_key: str
    workspace: SignupWorkspace
    inbox: Inbox
    """``None`` for ``kind="identity"`` signups (see ``identity``)."""
    claim: SignupClaim
    restrictions: UnclaimedRestrictions
    docs_url: str
    next_steps: list[str]


class SignupResult(_SignupResultBase, total=False):
    """``POST /v1/signup`` (201). ``api_key`` is shown only here."""

    kind: Literal["mailbox", "identity"]
    identity: Optional[Identity]
    """The identity-only agent of a ``kind="identity"`` signup, else ``None``."""


class AccountClaim(TypedDict):
    status: Literal["unclaimed", "claimed", "not_applicable"]
    """``not_applicable``: the workspace was created by a person, not by an agent."""
    claimed_at: Optional[str]
    pending_email: Optional[str]
    expires_at: Optional[str]
    """Unclaimed only: when the workspace is deleted if nothing happens before."""


class _AgentMessagingBase(TypedDict):
    enabled: bool
    directory_enabled: bool


class AgentMessaging(_AgentMessagingBase, total=False):
    """Launch switches of agent messaging and the directory."""

    agent_keys_enabled: bool
    """aSIM phase 2: agents may register their own signing keys and send author-signed messages."""
    public_directory_enabled: bool
    """aSIM phase 2: public cards, handles and the public directory."""


class _AccountExtras(TypedDict, total=False):
    agent_messaging: AgentMessaging
    """Absent on servers before agent messaging."""


class Account(_AccountExtras):
    """``GET /v1/account``: the workspace behind the key, its claim status and effective limits."""

    workspace: dict[str, Any]
    claim: AccountClaim
    limits: dict[str, Optional[int]]
    restrictions: Optional[UnclaimedRestrictions]


# ``draft_created``: a draft is waiting for a person to approve it (off by default).
EscalationTrigger = Literal[
    "needs_human", "phishing", "blocked", "draft_failed", "emergency_stop", "held", "draft_created"
]


class EscalationContact(TypedDict):
    """An on-call contact: ``pending`` until the confirmation link is clicked (only confirmed get alerts)."""

    email: str
    status: Literal["pending", "confirmed"]
    confirmed_at: Optional[str]


class QuietHours(TypedDict):
    """``HH:MM`` start and end (24-hour, may wrap midnight) in an IANA ``timezone``."""

    start: str
    end: str
    timezone: str


class EscalationSettings(TypedDict):
    """``GET/PUT /v1/escalation``: who is alerted, for what, and how (human on call)."""

    contacts: list[EscalationContact]
    triggers: dict[str, bool]
    delivery: Literal["immediate", "digest"]
    max_per_hour: int
    quiet_hours: Optional[QuietHours]
    include_excerpt: bool


class InboxEscalation(TypedDict):
    """``GET/PUT /v1/inboxes/{id}/escalation``: the inbox's own contacts (and triggers) when ``override``."""

    override: bool
    contacts: list[EscalationContact]
    triggers: Optional[dict[str, bool]]


# ---------- agent cards and the directory (aSIM) ----------

AgentCardVisibility = Literal["private", "workspace", "public"]
AgentCardStatus = Literal["active", "revoked", "suspended"]
AgentStatus = Literal["active", "revoked", "suspended", "deleted"]
DirectoryReportReason = Literal["spam", "impersonation", "malicious", "illegal", "other"]


class AgentCardSkill(TypedDict):
    id: str
    name: str
    description: str
    tags: list[str]
    oasf: Optional[str]


class _AgentCardBase(TypedDict):
    format_version: str
    address: str
    name: str
    description: str
    status: AgentCardStatus
    assurance: AgentAssurance
    badges: list[str]
    visibility: AgentCardVisibility
    channels: dict[str, Any]
    routing: Literal["relay", "direct_preferred"]
    accepts: dict[str, list[str]]
    skills: list[AgentCardSkill]
    documentation_url: Optional[str]
    keys: dict[str, Any]
    minimal: Literal[False]
    updated_at: str


class AgentCardListing(TypedDict):
    """The public listing of a card (owner view): ``pending`` (listing check) → ``listed`` or ``hidden``."""

    state: Literal["pending", "listed", "hidden"]
    reason: Optional[str]
    """Why it is hidden: ``listing_check``, ``reports`` or ``operator…``."""
    listed_at: Optional[str]


class AgentKeyJwk(TypedDict, total=False):
    """An agent-held public key as cards publish it (a JWK with its lifecycle)."""

    kty: str
    crv: str
    x: str
    y: str
    kid: str
    alg: str
    use: str
    status: Literal["active", "retired", "revoked"]
    created_at: str
    retired_at: Optional[str]
    revoked_at: Optional[str]


class PublicCardUrls(TypedDict):
    page: str
    a2a: str
    oasf: str
    keys: str


class AgentCard(_AgentCardBase, total=False):
    """A card as the agent's own workspace sees it (bundle, search, events)."""

    revoked_at: Optional[str]
    handle: Optional[str]
    """aSIM phase 2: ``@workspace/agent``, or None."""
    domain: Optional[str]
    """The verified custom domain behind the ``domain_verified`` badge, or None."""
    listing: Optional[AgentCardListing]
    """Public cards only (owner view)."""
    indexable: bool
    """The public page may be indexed by search engines and is in the sitemap."""


class PublicAgentCard(_AgentCardBase, total=False):
    """A publicly listed card (everyone sees it): no listing state, plus the public URLs."""

    revoked_at: Optional[str]
    handle: Optional[str]
    domain: Optional[str]
    indexable: bool
    """The owner allows search engines to index the card's public page."""
    urls: PublicCardUrls


class _MinimalAgentCardBase(TypedDict):
    format_version: str
    address: str
    name: str
    status: AgentCardStatus
    assurance: AgentAssurance
    accepts: dict[str, list[str]]
    keys: dict[str, Any]
    minimal: Literal[True]


class MinimalAgentCard(_MinimalAgentCardBase, total=False):
    """What another workspace sees on resolve: what a signed message already reveals, plus the name."""

    revoked_at: Optional[str]
    badges: list[str]


class _AgentKeyBase(TypedDict):
    kid: str
    alg: Literal["EdDSA", "ES256"]
    status: Literal["active", "retired", "revoked"]
    public_jwk: dict[str, str]
    created_at: str
    retired_at: Optional[str]
    revoked_at: Optional[str]
    revocation_reason: Optional[str]
    last_used_at: Optional[str]


class AgentKey(_AgentKeyBase):
    """An agent-held signing key (``/v1/inboxes/:id/agent/keys``): public key only."""


class AgentKeyList(TypedDict):
    data: list[AgentKey]


class WorkspaceHandle(TypedDict):
    """``/v1/directory/handle``: the workspace handle and the previous ones that still redirect."""

    handle: Optional[str]
    previous: list[dict[str, str]]


class PublicAgent(TypedDict):
    """``GET /v1/public/agents/{address}``."""

    card: PublicAgentCard


class _PublicHandleBase(TypedDict):
    handle: str
    address: str
    card: PublicAgentCard


class PublicHandle(_PublicHandleBase, total=False):
    """``GET /v1/public/handles/{workspace}/{agent}``."""

    redirected_from: str


class PublicAgentKeys(TypedDict):
    keys: list[AgentKeyJwk]


class AgentCardInput(TypedDict, total=False):
    """Create or edit a card (``agents.update``, or ``card=`` on ``inboxes.create`` / ``identities.create``).

    New cards are ``private`` (resolvable by exact address, never listed); ``workspace`` lists it in your
    workspace. Card text can't contain HTML, links (use ``documentation_url``) or email addresses."""

    name: str
    description: Optional[str]
    capabilities: dict[str, Any]
    """``skills`` (``id``, ``name``, optional ``description``, ``tags``, ``oasf``), ``accepts_types``,
    ``languages`` and ``input_modes``; replaces all capabilities when given."""
    documentation_url: Optional[str]
    visibility: AgentCardVisibility
    """``public`` needs the public directory, a claimed workspace and an org-scoped key (plan limit
    ``public_listings``)."""
    routing: Literal["relay", "direct_preferred"]
    handle: Optional[str]
    """The agent part of the handle (``billing`` in ``@acme/billing``); None clears it."""
    indexable: bool


class _ResolvedAgentBase(TypedDict):
    card: Union[AgentCard, MinimalAgentCard, PublicAgentCard]


class ResolvedAgent(_ResolvedAgentBase, total=False):
    """``GET /v1/directory/resolve``."""

    redirected_from: str
    """Resolving a renamed handle: the handle asked for."""


class _AgentBundleExtras(TypedDict, total=False):
    domain: Optional[str]
    handle: Optional[str]


class AgentBundle(_AgentBundleExtras):
    """``GET /v1/inboxes/:id/agent``: everything that makes the inbox an agent."""

    inbox: Inbox
    identity: dict[str, bool]
    card: Optional[AgentCard]
    keys: dict[str, Any]
    routing: Literal["relay", "direct_preferred"]
    visibility: AgentCardVisibility
    status: Literal["no_card", "active", "revoked", "suspended"]
    assurance: AgentAssurance
    badges: list[str]


_DirectoryVerifyBase = TypedDict(
    "_DirectoryVerifyBase",
    {
        # The signature is ours and the sender is active now (for an address: the agent is active).
        "valid": bool,
        "status": Optional[AgentStatus],
        "from": Optional[str],
        "assurance": Optional[str],
        "kid": Optional[str],
        "signed_at": Optional[str],
        "card": bool,
        # e.g. bad_signature, unknown_key, key_revoked, key_retired, issued_in_future, agent_revoked,
        # agent_suspended, agent_deleted
        "reasons": list[str],
    },
)


class DirectoryVerifyResult(_DirectoryVerifyBase, total=False):
    """``POST /v1/directory/verify``."""

    signer: Optional[Literal["server", "agent"]]
    """``server`` (Agentboxd's delivery signature) or ``agent`` (an author signature); None for an address."""
    key_revoked_at: Optional[str]
    """Author signatures: when the agent key was revoked, or None. The signer picks ``iat``, so the
    server never counts a revoked key's author signature as valid, whatever its ``iat``; to check one
    sent before the revocation, use ``verify_author_signature`` on the message (it uses ``created_at``)."""


class DirectoryReportResult(TypedDict):
    received: Literal[True]


class EmergencyStopResult(TypedDict):
    """``POST /v1/emergency-stop``: the workspace, now stopped."""

    org: dict[str, Any]


class AddAgentResult(TypedDict):
    """``POST /v1/signup/agents``: another agent in the same unclaimed workspace, with its own key."""

    api_key: str
    api_key_expires_at: Optional[str]
    """When ``api_key`` stops working (401 ``api_key_expired``); None = never."""
    kind: Literal["mailbox", "identity"]
    workspace: dict[str, Any]
    inbox: Optional[dict[str, Any]]
    identity: Optional[dict[str, Any]]
    next_steps: list[str]


class ClaimRequestResult(TypedDict):
    """``POST /v1/signup/claim``."""

    status: Literal["email_sent"]
    email: str
    expires_at: str
