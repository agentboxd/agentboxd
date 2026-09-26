/**
 * Agentboxd TypeScript client (npm package `agentboxd`). Zero dependencies (uses global fetch +
 * node:crypto), Node 20+. `Mailroom`, `MailroomError` and `MailroomOptions` remain exported as deprecated
 * aliases of `Agentboxd`, `AgentboxdError` and `AgentboxdOptions`.
 *
 *   const mr = new Agentboxd(); // reads AGENTBOXD_API_KEY (and AGENTBOXD_BASE_URL, default https://api.agentboxd.com)
 *   const inbox = await mr.inboxes.create({ client_id: 'support-agent' });
 *   await mr.messages.send(inbox.id, { to: 'someone@example.com', subject: 'Hi', text: 'Hello!' });
 */
import { createHash, createHmac, timingSafeEqual } from 'node:crypto';
import { EventStream, type StreamOptions } from './stream.js';

export { EventStream, StreamClosedError } from './stream.js';
export type { StreamEvent, StreamOptions, WebSocketConstructor, WebSocketLike } from './stream.js';
// Relying-party token verification lives in `agentboxd/identity` (src/identity.ts), not here: it loads
// the optional `jose` package, and keeping it out of the main entry means bundlers never look for jose
// unless you import that subpath.

// ---------- types ----------

/** Custom key/value data on inboxes, threads and contacts: ≤ 50 keys, string values ≤ 1,000 chars. */
export type MetadataValue = string | number | boolean | null;
export type Metadata = Record<string, MetadataValue>;
/**
 * A metadata change: given keys are set, a `null` value deletes the key, other keys are kept.
 * Keys match `^[a-zA-Z0-9_.-]{1,64}$`.
 */
export type MetadataPatch = Record<string, MetadataValue>;

export interface Inbox {
  id: string;
  /**
   * `mailbox`: an email inbox. `identity`: an identity-only agent (no mail; see `identities`). Identity
   * ids only reach you through per-id inbox routes (`get`, `pause`), never through `inboxes.list`.
   * Optional for older servers.
   */
  kind?: 'mailbox' | 'identity';
  address: string;
  username: string;
  display_name: string | null;
  client_id: string | null;
  daily_send_limit: number;
  /** Custom metadata (always present on servers with Phase 2b; optional for older servers and fixtures). */
  metadata?: Metadata;
  /** Temporary (receive-only, self-deleting) inbox. Optional for older servers. */
  temporary?: boolean;
  /** When a temporary inbox is wiped (ISO 8601); null for permanent inboxes. Optional for older servers. */
  expires_at?: string | null;
  /** `paused`: sends are refused (423 inbox_paused) and inbound events are held until resume. Optional for older servers. */
  status?: 'active' | 'paused';
  paused_at?: string | null;
  paused_reason?: string | null;
  created_at: string;
}

export type DomainStatus = 'pending' | 'verified' | 'failed' | 'disabled';

/** One DNS record to publish for a custom domain, with the result of the last check. */
export interface DomainRecord {
  /** `dkim_next` / `dkim_previous` only appear during a DKIM key rotation (never required). */
  key: 'verification' | 'mx' | 'spf' | 'dkim' | 'dmarc' | 'dkim_next' | 'dkim_previous';
  type: 'TXT' | 'MX';
  name: string;
  value: string;
  required: boolean;
  status: 'ok' | 'missing' | 'mismatch';
  /** What was found in DNS when it didn't match (or was found). */
  found?: string[];
}

/** A workspace's own domain (e.g. mail.acme.com): inboxes on it send DKIM-signed with its own key. */
export interface Domain {
  id: string;
  domain: string;
  status: DomainStatus;
  receiving: boolean;
  records: DomainRecord[];
  /** DKIM key rotation state. Optional for older servers. */
  dkim?: DomainDkim;
  verified_at: string | null;
  last_checked_at: string | null;
  created_at: string;
}

export interface DomainDkim {
  /** The selector signing now (cm1 or cm2). */
  selector: string;
  active_since: string;
  /** The key has signed for a year: rotate it. */
  rotation_due: boolean;
  /** A rotation waiting for its new record (`dkim_next` in `records`). */
  next: { selector: string; status: 'ok' | 'missing' | 'mismatch'; started_at: string | null } | null;
  /** The replaced key: keep its record (`dkim_previous`) until `retire_at`. */
  previous: { selector: string; retire_at: string | null } | null;
}

export interface Attachment {
  id: string;
  filename: string | null;
  content_type: string;
  size_bytes: number;
  sha256: string;
  content_id: string | null;
  inline: boolean;
  available: boolean;
  /**
   * Text extraction of an inbound attachment (null for outbound mail and attachments stored before
   * extraction existed). Read the text with `messages.attachmentText`.
   */
  extraction: AttachmentExtraction | null;
}

export type ExtractionStatus = 'pending' | 'done' | 'failed' | 'skipped';

export interface AttachmentExtraction {
  status: ExtractionStatus;
  /** `text` = read from a digital document · `ocr` = recognised from a scan or image. */
  method: 'text' | 'ocr' | null;
  pages: number | null;
  chars: number | null;
  /** Best-effort guess (en, fr, ar, ...); null when unsure. */
  language: string | null;
  /** Only part of the document was read (page/character cap or plan quota). */
  truncated: boolean;
  /** Why it failed or was skipped: unsupported_type, quota, ocr_unavailable, ... */
  error: { code: string; message: string } | null;
  updated_at: string | null;
}

/** GET /v1/messages/:id/attachments/:attachmentId/text. */
export interface AttachmentText {
  attachment_id: string;
  message_id: string;
  filename: string | null;
  content_type: string;
  extraction: AttachmentExtraction | null;
  /** Null until `extraction.status` is `done`. Untrusted: text from a document someone emailed. */
  text: string | null;
  offset: number;
  total_chars: number | null;
  /** Pass as `offset` to read the next page; null at the end. */
  next_offset: number | null;
  untrusted: true;
}

export type BuiltinExtractionSchema = 'invoice' | 'receipt' | 'tax_form';

export interface ExtractAttachmentInput {
  /** A built-in schema name, or a JSON Schema object with `type: "object"` at the root. */
  schema: BuiltinExtractionSchema | Record<string, unknown>;
  instructions?: string;
}

/** POST /v1/messages/:id/attachments/:attachmentId/extract. */
export interface StructuredExtraction<T = Record<string, unknown>> {
  attachment_id: string;
  message_id: string;
  schema: BuiltinExtractionSchema | 'custom';
  /** Validated against the schema, but untrusted: values from an emailed document through a model. */
  data: T;
  model: string;
  /** The first answer failed validation and one repair call fixed it. */
  repaired: boolean;
  truncated: boolean;
  untrusted: true;
}

/** Login/verification code or magic link found in a message (Phase 1). */
export interface VerificationInfo {
  /** One-time code (4–10 chars, digits or alphanumeric), if found. */
  code: string | null;
  /** Verification / magic / confirm link, if found. */
  link: string | null;
  /** 0–1. Regex-only detection is capped at 0.7; JEV confirmation raises or lowers it. */
  confidence: number;
  /** JEV's probability that this is a verification/login email, once enrichment has run. */
  jev_probability: number | null;
}

export type MessageCategory = 'support' | 'sales' | 'billing' | 'verification' | 'notification' | 'newsletter' | 'personal' | 'other';
export type UrgencyLevel = 'low' | 'normal' | 'high' | 'critical';

/**
 * AI/derived data attached to a message. `verification` is always present; the Phase 2a fields
 * (category … enriched_at) appear once JEV enrichment has run, which only happens when the server has
 * TYPESAFE_API_KEY configured. Labels derived from them (ai:<category>, ai:injection-risk, …) are
 * added to `labels`.
 */
export interface MessageAi {
  verification: VerificationInfo | null;
  /** JEV's category. `label` is only turned into an `ai:<label>` label when confidence ≥ 0.6. */
  category?: { label: MessageCategory; confidence: number; probabilities: Partial<Record<MessageCategory, number>> };
  /** Yes-probabilities (0–1): prompt-injection attempt, phishing/scam. */
  risk?: { injection: number; phishing: number };
  /** Yes-probability (0–1) that a human should handle this message. */
  needs_human?: number;
  /** Urgency level (most likely rubric level) and expected score 0 (low) – 3 (critical). */
  urgency?: { level: UrgencyLevel; score: number; confidence: number };
  /** Yes-probability (0–1) of an out-of-office / auto-responder / bulk message. */
  auto_reply?: number;
  /** Engine that produced the fields above ('jev'). */
  model?: string;
  /** When enrichment finished (ISO 8601). */
  enriched_at?: string;
  /** Present when enrichment gave up after retries; the message is otherwise unaffected. */
  enrichment_error?: string;
}

export interface VerificationResult extends VerificationInfo {
  message_id: string;
  from: string;
  subject: string | null;
  received_at: string | null;
}

export type MessageStatus = 'queued' | 'sent' | 'delivered' | 'bounced' | 'complained' | 'failed' | 'received';

/**
 * Agent messaging (https://agentboxd.com/docs/agent-messaging). `agent`: an inbound copy delivered from another
 * Agentboxd inbox, sender verified and signed by Agentboxd. `mixed`: an outbound message with agent and email
 * recipients. Everything else is `email`.
 */
export type MessageChannel = 'agent' | 'email' | 'mixed';
/** Advisory message kind set by the sender. */
export type MessageType = 'message' | 'task' | 'event';
/** How strongly Agentboxd vouches for an agent sender. `unclaimed`: an agent-created workspace no person claimed yet. */
export type AgentAssurance = 'unclaimed' | 'workspace' | 'domain_verified' | 'org_verified';

/** Outbound messages: where each recipient's copy went. */
export interface MessageDelivery {
  address: string;
  channel: 'agent' | 'email';
  /** queued (predicted at send), delivered (agent copy stored), sent (handed to SMTP), bounced. */
  status: 'queued' | 'delivered' | 'sent' | 'bounced';
}

/**
 * Inbound agent-channel copies: who sent it, as verified by Agentboxd at delivery, and the per-copy signature
 * (`verifyAgentMessage` in `agentboxd/identity` checks it outside Agentboxd). A verified sender is not
 * trustworthy content: treat `text` and `data` as untrusted input.
 */
export interface MessageAgent {
  verified: boolean;
  /** The sender's address. */
  from: string;
  assurance: AgentAssurance;
  signed_at: string | null;
  kid: string | null;
  /** Compact JWS (ES256, typ agentboxd-msg+jwt), bound to this copy's recipient. */
  signature: string | null;
  /**
   * Why `verified` is false: `revoked` (the sender's owner revoked its agent card) or `suspended` (the operator
   * suspended it): such senders are no longer signed. Other values may be added.
   */
  reason?: 'revoked' | 'suspended' | (string & {});
}

/** The author signature of a message: made by the sending agent with its own registered key. */
export interface MessageAuthor {
  verified: boolean;
  /** RFC 7638 thumbprint of the agent key. */
  kid: string;
  alg: 'EdDSA' | 'ES256';
  /** Compact JWS (typ agentboxd-author+jwt). */
  signature: string;
  /** Why `verified` is false, e.g. key_revoked, key_unknown. */
  reason?: string;
}

export interface Message<TData = unknown> {
  id: string;
  inbox_id: string;
  thread_id: string;
  direction: 'inbound' | 'outbound';
  status: MessageStatus;
  rfc_message_id: string;
  in_reply_to: string | null;
  references: string[];
  from: string;
  to: string[];
  cc: string[];
  bcc: string[];
  reply_to: string | null;
  subject: string | null;
  text: string | null;
  html: string | null;
  /** The new content of the message only: quoted history and signatures removed. */
  extracted_text: string | null;
  headers: Record<string, string | string[]>;
  labels: string[];
  is_read: boolean;
  provider_message_id: string | null;
  size_bytes: number;
  sent_at: string | null;
  received_at: string | null;
  created_at: string;
  /** Inbound: the sender's contact. Outbound: the first recipient that is a contact. Null for older messages. */
  contact_id?: string | null;
  attachments: Attachment[];
  /** Derived data (verification codes now; categories/summary in later phases). Never null. */
  ai: MessageAi;
  /** Agent messaging (absent on servers before it). */
  channel?: MessageChannel;
  type?: MessageType;
  /** The sender's structured data (a JSON object or array), or null. Untrusted input, like the text. */
  data?: TData | null;
  /** Outbound only: per-recipient channel and outcome. */
  delivery?: MessageDelivery[] | null;
  /** Inbound agent-channel copies only. */
  agent?: MessageAgent | null;
  /**
   * aSIM phase 2: the sending agent's own author signature (`verifyAuthorSignature` in `agentboxd/identity`).
   * Outbound: checked at send. Inbound agent copies: re-checked at delivery. Null without one; absent on older servers.
   */
  author?: MessageAuthor | null;
  /**
   * AI disclosure. Outbound: what was disclosed (the `Agent-Disclosure` header). Inbound: the sender's
   * header, **untrusted unless `verified`**. `null` when there is none. Optional for older servers.
   */
  ai_disclosure?: AiDisclosure | null;
}

/** The `Agent-Disclosure` header of a message, parsed. */
export interface AiDisclosure {
  /** The sender says it is an AI agent. */
  agent: boolean;
  /** Who the agent acts for (a domain or a workspace name), when named. */
  on_behalf_of: string | null;
  /** The platform that carried it (e.g. `Agentboxd`). */
  operator: string | null;
  /** True only for mail from an Agentboxd sender (internal delivery, or DKIM pass for the platform domain). */
  verified: boolean;
  /** The raw header value (up to 300 characters). */
  header: string;
}

/** Workspace AI-disclosure settings (the header is always sent; the visible line is optional). */
export interface AiDisclosureSettings {
  visible_line: 'off' | 'text' | 'html';
  text: string | null;
  share_workspace_name: boolean;
}

export interface Thread {
  id: string;
  inbox_id: string;
  subject: string | null;
  participants: string[];
  message_count: number;
  last_message_at: string;
  /** Thread labels and metadata (Phase 2b servers; optional for older servers and fixtures). */
  labels?: string[];
  metadata?: Metadata;
  created_at: string;
}

export interface ThreadWithMessages extends Thread {
  messages: Message[];
}

export interface SearchResult extends Message {
  rank: number;
  snippet: string;
}

/** An external address the workspace has exchanged mail with (created automatically). */
export interface Contact {
  id: string;
  /** Lower-case bare address. */
  address: string;
  name: string | null;
  notes: string | null;
  metadata: Metadata;
  labels: string[];
  message_count: number;
  first_seen_at: string;
  last_seen_at: string;
  created_at: string;
}

export interface ContactWithThreads extends Contact {
  /** Up to 10 newest threads (all inboxes) with this address. */
  recent_threads: Thread[];
}

export interface ContactUpdate {
  name?: string | null;
  /** ≤ 10,000 chars; null clears. */
  notes?: string | null;
  metadata?: MetadataPatch;
  add_labels?: string[];
  remove_labels?: string[];
}

/** Reference text for reply drafts. `inbox_id` null = every inbox of the workspace. */
export interface KnowledgeDoc {
  id: string;
  inbox_id: string | null;
  title: string;
  /** Plain text or markdown, ≤ 200,000 chars. */
  body: string;
  created_at: string;
  updated_at: string;
}

/** List item: no body, a ≤ 200-char excerpt instead. */
export interface KnowledgeListItem extends Omit<KnowledgeDoc, 'body'> {
  excerpt: string;
}

export interface KnowledgeSearchResult {
  id: string;
  title: string;
  inbox_id: string | null;
  rank: number;
  snippet: string;
}

/** A reply draft. Nothing is sent: review it, then call messages.reply (or drafts.send when saved). */
export interface DraftReply {
  text: string;
  citations: { knowledge_id: string; title: string }[];
  model: string;
  /** Present when called with `save: true`: the stored Draft replying to the message. */
  draft?: Draft;
}

// ---------- drafts (human-in-the-loop, scheduled send) ----------

export type DraftStatus = 'draft' | 'scheduled' | 'sending' | 'sent' | 'failed' | 'cancelled';

export interface DraftAttachment {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
}

/** A message waiting for review, approval or its `send_at`. Once sent, text/html/attachments are cleared: read `sent_message_id`. */
export interface Draft {
  id: string;
  inbox_id: string;
  status: DraftStatus;
  reply_to_message_id: string | null;
  thread_id: string | null;
  reply_all: boolean;
  to: string[];
  cc: string[];
  bcc: string[];
  subject: string | null;
  text: string | null;
  html: string | null;
  attachments: DraftAttachment[];
  metadata: Metadata;
  labels: string[];
  /** `ai` when saved by messages.draftReply with `save: true`. */
  source: 'api' | 'ai';
  send_at: string | null;
  sent_at: string | null;
  sent_message_id: string | null;
  /** Why the last send attempt was refused (API error code and message). */
  error: { code: string; message: string } | null;
  /** Agent messaging: sent as the message's type and data. */
  type?: MessageType;
  data?: unknown;
  created_at: string;
  updated_at: string;
}

/** Everything is optional: a draft may be incomplete until it is sent. */
export interface DraftCreateInput {
  to?: string | string[];
  cc?: string | string[];
  bcc?: string | string[];
  subject?: string;
  text?: string;
  html?: string;
  attachments?: AttachmentInput[];
  metadata?: MetadataPatch;
  labels?: string[];
  /** Reply to this message of the inbox (recipients, subject and threading are filled in). */
  reply_to_message_id?: string;
  /** Reply to the latest message of this thread. */
  thread_id?: string;
  reply_all?: boolean;
  /** Schedule it: ISO time (or Date) at least 1 minute and at most 30 days ahead. */
  send_at?: string | Date;
  /** Structured data (a JSON object or array, at most 64 KB) and message type, sent with the message. */
  data?: unknown;
  type?: MessageType;
}

export interface DraftUpdateInput {
  to?: string | string[];
  cc?: string | string[];
  bcc?: string | string[];
  subject?: string | null;
  text?: string | null;
  html?: string | null;
  /** Replaces the list; `{ id }` keeps an attachment already on the draft. */
  attachments?: (AttachmentInput | { id: string })[];
  /** Merged (null deletes a key). */
  metadata?: MetadataPatch;
  labels?: string[];
  /** Reschedule; `null` unschedules (back to `draft`). */
  send_at?: string | Date | null;
  /** `null` removes the data. */
  data?: unknown;
  type?: MessageType;
}

export interface DraftListQuery {
  /** One status or several (`['draft', 'scheduled']`). */
  status?: DraftStatus | DraftStatus[];
  thread_id?: string;
  cursor?: string;
  limit?: number;
}

const isoTime = (v: string | Date) => (v instanceof Date ? v.toISOString() : v);

function withIsoSendAt<T extends { send_at?: string | Date | null }>(input: T): T {
  return input.send_at instanceof Date ? { ...input, send_at: input.send_at.toISOString() } : input;
}

function draftListQuery(q: DraftListQuery & { inbox_id?: string }): Query {
  return { ...q, status: Array.isArray(q.status) ? q.status.join(',') : q.status };
}

export type AiProcessing = 'off' | 'categorize' | 'full';

export interface Page<T> {
  data: T[];
  next_cursor: string | null;
}

export type WebhookEventType =
  | 'message.received'
  | 'message.sent'
  | 'message.delivered'
  | 'message.bounced'
  | 'message.complained'
  | 'message.enriched'
  /** A temporary inbox expired and was wiped. `data` is `{ inbox }`. */
  | 'inbox.expired'
  /** Inbound mail stopped by an allow/block list (stored with label `blocked`, hidden by default). */
  | 'message.received.blocked'
  /** Drafts: `data` is `{ inbox, draft }` (`draft.sent` adds `message`). */
  | 'draft.created'
  | 'draft.updated'
  | 'draft.sent'
  | 'draft.failed'
  | 'draft.cancelled'
  /** Sign in with Agentboxd: `data` is `{ inbox, client, flow, jti, sub, expires_at? }`. */
  | 'identity.token_issued'
  | 'identity.signed_in'
  /** Agent self-signup: `data` is `{ workspace, inbox, claim_requested }` / `{ workspace, inbox }`. */
  | 'signup.created'
  | 'signup.claimed'
  /** Attachment extraction: `data` is `{ inbox, thread_id, message_id, attachment }` (never the text). */
  | 'attachment.extracted'
  | 'attachment.extraction_failed'
  /** An inbox was paused (`data`: `{ inbox, reason }`) or resumed (`{ inbox, held_events }`). */
  | 'inbox.paused'
  | 'inbox.resumed'
  /** Custom-domain DKIM rotation: `data` is `{ domain: { id, domain, status, dkim } }`. */
  | 'domain.dkim_rotated'
  | 'domain.dkim_rotation_due'
  /** Hosted MCP connector: `data` is `{ connector }` (+ `reason` for revoked). */
  | 'connector.authorized'
  | 'connector.revoked'
  /** Emergency stop of the whole workspace: `data` is `{ workspace, reason, actor }` / `{ workspace, stopped_at, actor }`. */
  | 'workspace.stopped'
  | 'workspace.resumed'
  /** Human on call: escalation email(s) went out. `data` is `{ trigger, mode, inbox, message_id, draft_id, recipients, items }`. */
  | 'escalation.sent'
  /**
   * Agent cards (directory): `data` is `{ inbox, card }` for updated (created, changed, restored), `{ inbox, card,
   * reason }` for revoked (by the owner, or suspended by the operator), `{ inbox }` for deleted and `{ inbox, reason }`
   * for reported (never who reported).
   */
  | 'agent.updated'
  | 'agent.revoked'
  | 'agent.deleted'
  | 'agent.reported';

/** `full` = the whole message (default) · `envelope` = ids, addresses, subject and labels only. */
export type WebhookPayload = 'full' | 'envelope';

export interface WebhookStats {
  deliveries_24h: number;
  failed_24h: number;
  error_rate_24h: number;
  last_success_at: string | null;
  last_failure_at: string | null;
}

export interface Webhook {
  id: string;
  url: string;
  events: WebhookEventType[];
  inbox_ids: string[] | null;
  enabled: boolean;
  created_at: string;
  /** Optional for older servers. */
  payload?: WebhookPayload;
  /** Delivery stats over the last 24 h (optional for older servers). */
  stats?: WebhookStats;
  secret?: string;
  secret_hint?: string;
}

/** `data` of an event delivered to a webhook with `payload: 'envelope'`. Fetch the message with messages.get. */
export interface EnvelopeEventData {
  inbox_id: string | null;
  thread_id: string | null;
  message_id: string | null;
  from: string | null;
  to: string[];
  subject: string | null;
  labels: string[];
  received_at: string | null;
}

/** GET /v1/webhooks/events: the event catalog. */
export interface WebhookCatalogEntry {
  type: WebhookEventType | 'webhook.test';
  description: string;
  example: WebhookEvent<unknown>;
  envelope_example: WebhookEvent<unknown>;
}

// ---------- identity-only agents ----------

/**
 * An identity-only agent: an Agentboxd identity (sign in to apps) without a mailbox. `address` is a
 * stable handle on the agent domain; nothing is delivered to it and tokens never carry it as `email`.
 */
export interface Identity {
  id: string;
  kind: 'identity';
  address: string;
  username: string;
  display_name: string | null;
  client_id: string | null;
  metadata: Metadata;
  /** Sign in with Agentboxd switch (`identity.inbox.update(id, { enabled })`). */
  identity_enabled: boolean;
  status: 'active' | 'paused';
  paused_at: string | null;
  paused_reason: string | null;
  created_at: string;
}

export interface IdentityCreateInput {
  /** The handle's local part (default: a random one). Same rules as inbox usernames. */
  username?: string;
  /** Shown to apps as the `name` claim (scope profile). */
  display_name?: string;
  /** Idempotency key: the same client_id returns the existing identity (200). */
  client_id?: string;
  metadata?: MetadataPatch;
  /** Also create the identity's agent card (needs directory:write). */
  card?: AgentCardInput;
}

// ---------- agent cards and the directory (aSIM) ----------

export type AgentCardVisibility = 'private' | 'workspace' | 'public';
export type AgentCardStatus = 'active' | 'revoked' | 'suspended';

export interface AgentCardSkill {
  id: string;
  name: string;
  description: string;
  tags: string[];
  /** Optional OASF class id. */
  oasf: string | null;
}

/** Badges a card can carry. `domain_verified`: the address is on a custom domain its (claimed) workspace verified. */
export type AgentBadge = 'domain_verified';

/**
 * One agent-held public key as cards publish it (aSIM phase 2): a JWK plus its lifecycle. `retired` keys no longer
 * sign but old signatures stay valid; `revoked` keys invalidate signatures made at or after `revoked_at`.
 */
export interface PublishedAgentKey {
  kty: 'OKP' | 'EC' | (string & {});
  crv: 'Ed25519' | 'P-256' | (string & {});
  x: string;
  y?: string;
  kid: string;
  alg: 'EdDSA' | 'ES256' | (string & {});
  use: 'sig';
  status: AgentKeyStatus;
  created_at: string;
  retired_at: string | null;
  revoked_at: string | null;
}

export type AgentKeyStatus = 'active' | 'retired' | 'revoked';

/** An agent-held key as the key routes return it (`agents.keys`). */
export interface AgentKey {
  kid: string;
  alg: 'EdDSA' | 'ES256';
  status: AgentKeyStatus;
  public_jwk: Record<string, string>;
  created_at: string;
  retired_at: string | null;
  revoked_at: string | null;
  revocation_reason: string | null;
  last_used_at: string | null;
}

/** The public listing state of a `public` card (owner view). */
export interface AgentListing {
  state: 'pending' | 'listed' | 'hidden';
  /** Why it is hidden: listing_check, reports, operator… */
  reason: string | null;
  listed_at: string | null;
}

/** A card as the agent's own workspace sees it (bundle, search, events). */
export interface AgentCard {
  format_version: string;
  address: string;
  /** `@workspace/agent`, or null (absent on older servers). */
  handle?: string | null;
  name: string;
  description: string;
  status: AgentCardStatus;
  revoked_at?: string | null;
  assurance: AgentAssurance;
  badges: (AgentBadge | (string & {}))[];
  /** The verified custom domain behind the domain-verified badge, or null. */
  domain?: string | null;
  visibility: AgentCardVisibility;
  /** Public cards only: pending → listed | hidden. Null otherwise. */
  listing?: AgentListing | null;
  /** The public page may be indexed by search engines. */
  indexable?: boolean;
  channels: { relay: { address: string }; a2a: string | null };
  routing: 'relay' | 'direct_preferred';
  accepts: { types: MessageType[]; languages: string[]; input_modes: string[] };
  skills: AgentCardSkill[];
  documentation_url: string | null;
  keys: { server: string; agent: PublishedAgentKey[] };
  minimal: false;
  updated_at: string;
}

/** A publicly listed card: everyone sees it, with its public URLs (no listing state). */
export interface PublicAgentCard extends Omit<AgentCard, 'listing' | 'indexable'> {
  /** The owner allows search engines to index its public page. */
  indexable: boolean;
  urls: { page: string; a2a: string; oasf: string; keys: string };
}

/** What another workspace sees when it resolves a card: only what a signed message already reveals, plus the name. */
export interface MinimalAgentCard {
  format_version: string;
  address: string;
  name: string;
  status: AgentCardStatus;
  revoked_at?: string | null;
  assurance: AgentAssurance;
  badges?: (AgentBadge | (string & {}))[];
  accepts: { types: MessageType[] };
  keys: { server: string; agent: PublishedAgentKey[] };
  minimal: true;
}

/** An OASF record (schema 0.7.0 shape) generated from a card. */
export interface OasfRecord {
  schema_version: string;
  name: string;
  version: string;
  description: string;
  authors: string[];
  created_at: string;
  skills: ({ id: number } | { name: string })[];
  domains: unknown[];
  locators: { type: string; url: string }[];
  modules: unknown[];
  annotations: Record<string, string>;
}

/** The workspace handle (`@acme`) and its earlier names that still redirect. */
export interface WorkspaceHandle {
  handle: string | null;
  previous: { handle: string; redirect_until: string }[];
}

/**
 * Create or edit a card (`agents.update`, or `card` on `inboxes.create` / `identities.create`). New cards are
 * `private`: resolvable by exact address, never listed. `workspace` lists it in your workspace's directory.
 * Card text can't contain HTML, links (use `documentation_url`) or email addresses.
 */
export interface AgentCardInput {
  name?: string;
  /** null resets to empty. */
  description?: string | null;
  /** Replaces all capabilities when given. */
  capabilities?: {
    skills?: { id: string; name: string; description?: string; tags?: string[]; oasf?: string | null }[];
    accepts_types?: MessageType[];
    languages?: string[];
    input_modes?: string[];
  };
  /** https only; null removes it. */
  documentation_url?: string | null;
  /**
   * `public` lists the agent in the public directory: needs a claimed workspace, an org-scoped key and a free
   * `public_listings` slot of the plan (422 visibility_unavailable while the server hasn't enabled it).
   */
  visibility?: AgentCardVisibility;
  /** `direct_preferred` is not available yet (422 routing_unavailable). */
  routing?: 'relay' | 'direct_preferred';
  /** The agent part of the handle (`billing` in `@acme/billing`; needs a workspace handle), or null to clear it. */
  handle?: string | null;
  /** The public page may be indexed by search engines and listed in the sitemap (opt-in on top of `public`). */
  indexable?: boolean;
}

/** GET /v1/inboxes/:id/agent: everything that makes the inbox an agent. */
export interface AgentBundle {
  inbox: Inbox;
  identity: { enabled: boolean; sign_in_ready: boolean };
  card: AgentCard | null;
  keys: { server: { kid: string | null; jwks_uri: string }; agent: PublishedAgentKey[] };
  routing: 'relay' | 'direct_preferred';
  visibility: AgentCardVisibility;
  status: 'no_card' | AgentCardStatus;
  assurance: AgentAssurance;
  badges: (AgentBadge | (string & {}))[];
  domain?: string | null;
  handle?: string | null;
}

export type AgentStatus = 'active' | 'revoked' | 'suspended' | 'deleted';

/** POST /v1/directory/verify. */
export interface DirectoryVerifyResult {
  /** The signature is ours and the sender is active now (or, for an address, the agent is active). */
  valid: boolean;
  status: AgentStatus | null;
  from: string | null;
  assurance: string | null;
  kid: string | null;
  signed_at: string | null;
  card: boolean;
  /** Who made the signature: Agentboxd's delivery signature or the agent's own author signature (absent on older servers). */
  signer?: 'server' | 'agent' | null;
  /** e.g. bad_signature, unknown_key, key_revoked, wrong_issuer, wrong_type, malformed, agent_revoked, agent_suspended, agent_deleted. */
  reasons: string[];
}

export interface DirectorySearchQuery {
  /** `workspace` (default): your workspace's listed agents. `public`: the public directory. */
  scope?: 'workspace' | 'public';
  /** Substring of name, description, skill names and tags. */
  q?: string;
  /** Exact skill id, tag or OASF id. */
  capability?: string;
  /** Accepted message type. */
  type?: MessageType;
  /** 1–50 (default 20). */
  limit?: number;
  cursor?: string;
}

export type DirectoryReportReason = 'spam' | 'impersonation' | 'malicious' | 'illegal' | 'other';

export interface DirectoryReportInput {
  address: string;
  reason: DirectoryReportReason;
  details?: string;
  /** Evidence: a message your workspace received from that agent. */
  message_id?: string;
}

// ---------- agent identity (Sign in with Agentboxd) ----------

export type IdentityScope = 'openid' | 'email' | 'profile' | 'workspace';
/**
 * `confidential`: has a client secret (browser flow + JWT bearer grant) · `public`: no secret, PKCE ·
 * `verify_only`: only receives headless identity tokens and verifies them against the JWKS.
 */
export type IdentityClientType = 'confidential' | 'public' | 'verify_only';
export type IdentitySubjectType = 'pairwise' | 'public';

/** An app ("relying party") registered by your workspace. `client_id` is public: it is the tokens' `aud`. */
export interface IdentityClient {
  id: string;
  client_id: string;
  name: string;
  type: IdentityClientType;
  redirect_uris: string[];
  allowed_scopes: IdentityScope[];
  subject_type: IdentitySubjectType;
  homepage_url: string | null;
  /** First characters of the secret (confidential clients), for telling secrets apart. */
  secret_prefix: string | null;
  enabled: boolean;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface IdentityClientCreateInput {
  name: string;
  type: IdentityClientType;
  /** Required (1–10) for confidential/public clients, forbidden for verify_only. Exact https URLs (http on localhost). */
  redirect_uris?: string[];
  /** Must contain `openid`. Default openid, email, profile. */
  allowed_scopes?: IdentityScope[];
  /** Default `pairwise`. Fixed at creation. */
  subject_type?: IdentitySubjectType;
  homepage_url?: string | null;
}

export interface IdentityClientUpdateInput {
  name?: string;
  redirect_uris?: string[];
  allowed_scopes?: IdentityScope[];
  homepage_url?: string | null;
  enabled?: boolean;
}

/** Create and secret rotation: `client_secret` is returned only here, once (confidential clients). */
export interface IdentityClientWithSecret {
  client: IdentityClient;
  client_secret?: string | null;
}

/** Pass `inboxId` for an inbox or `identityId` for an identity-only agent. */
export type IdentityTokenInput = IdentityTokenOptions & ({ inboxId: string; identityId?: never } | { identityId: string; inboxId?: never });

export interface IdentityTokenOptions {
  /** The relying party's `client_id`. */
  audience: string;
  /** Echoed in the token; pass the one the relying party gave you. */
  nonce?: string;
  /** Default `openid email`; `openid` is always added. */
  scope?: string | IdentityScope[];
  /** 30–300 seconds (default 300). */
  expiresIn?: number;
}

/** A short-lived (≤ 5 min), single-use ID token proving the agent owns the inbox, for one relying party. */
export interface IdentityToken {
  id_token: string;
  token_type: 'id_token';
  issuer: string;
  audience: string;
  sub: string;
  jti: string;
  scope: string;
  expires_in: number;
  expires_at: string;
}

export interface InboxIdentityApp {
  client_id: string;
  name: string;
  homepage_url: string | null;
  last_signed_in_at: string;
  sign_ins: number;
}

/** Per-inbox "Sign in with Agentboxd" switch and the apps the inbox signed into. */
export interface InboxIdentity {
  inbox_id: string;
  /** `identity` for an identity-only agent. Optional for older servers. */
  kind?: 'mailbox' | 'identity';
  enabled: boolean;
  apps: InboxIdentityApp[];
}

export interface IdentitySignIn {
  id: string;
  inbox_id: string;
  client_id: string;
  client_name: string;
  event: 'token_issued' | 'signed_in';
  flow: 'headless' | 'authorization_code' | 'jwt_bearer';
  jti: string;
  ip: string | null;
  created_at: string;
}

// ---------- allow / block lists ----------

export type ListDirection = 'receive' | 'send' | 'reply';
export type ListKind = 'allow' | 'block';

export interface ListEntry {
  id: string;
  /** null = the whole workspace. */
  inbox_id: string | null;
  direction: ListDirection;
  kind: ListKind;
  /**
   * `a@b.com` (exact address), `b.com` (the domain and its subdomains), or on receive lists a token:
   * `agents:any`, `agents:verified` (signed agent with an active card, claimed workspace), `workspace:self`.
   */
  pattern: string;
  type: 'address' | 'domain' | 'token';
  created_at: string;
}

// ---------- deliverability ----------

export interface DeliverabilityWindow {
  sent: number;
  bounced: number;
  complained: number;
  bounce_rate: number;
  complaint_rate: number;
}

export type RecordCheck = 'ok' | 'missing' | 'mismatch';

export interface DeliverabilitySummary {
  rates: { last_7_days: DeliverabilityWindow; last_30_days: DeliverabilityWindow };
  /** Sending is suspended above these rates over 7 days (with at least `min_sent` sends). */
  thresholds: { bounce_rate: number; complaint_rate: number; min_sent: number };
  /** Your contacts whose address is suppressed (hard bounce or complaint). */
  suppressed_contacts: number;
  domains: { id: string; domain: string; status: DomainStatus; spf: RecordCheck; dkim: RecordCheck; dmarc: RecordCheck; dkim_rotation_due: boolean }[];
  shared: {
    sending_domain: string;
    ip_reputation: {
      status: 'clean' | 'listed' | 'partial' | 'unknown' | 'stale' | 'not_checked';
      checked_at: string | null;
      lists: { name: string; status: 'clean' | 'listed' | 'unknown' | 'skipped'; codes?: string[] }[];
    };
  };
}

// ---------- metrics ----------

export interface MetricCounts {
  sent: number;
  received: number;
  delivered: number;
  bounced: number;
  complained: number;
  blocked: number;
}

export interface Metrics {
  from: string;
  to: string;
  tz: string;
  bucket: 'hour' | 'day';
  inbox_id: string | null;
  series: ({ t: string } & MetricCounts)[];
  totals: MetricCounts;
  deliverability: {
    delivered_rate: number;
    bounce_rate: number;
    complaint_rate: number;
    bounce_reasons: { status: string; count: number }[];
  };
  inbound: { spam: number; blocked: number; unauthenticated: number };
  heatmap: { date: string; sent: number; received: number }[];
  streak: { longest_days: number; busiest_day: { date: string; count: number } | null };
  resources: { inboxes: number; domains: number; threads: number; messages: number; storage_bytes: number };
  /** Claim/ack queue, per inbox that uses it (current state, not bounded by from/to). */
  queue: QueueMetrics[];
}

export interface QueueMetrics {
  inbox_id: string;
  address: string;
  started_at: string;
  /** Waiting: not acked, not in flight, not dead-lettered (nacked messages in their delay included). */
  depth: number;
  /** Live leases. */
  in_flight: number;
  dead_letters: number;
  oldest_waiting_at: string | null;
}

export interface MetricsQuery {
  /** ISO timestamp, or a date (YYYY-MM-DD = local midnight in `tz`). Default: 30 days before `to`. */
  from?: string;
  /** ISO timestamp, or a date (inclusive). Default: now. At most 90 days after `from`. */
  to?: string;
  /** IANA time zone for the buckets (default UTC). */
  tz?: string;
  inbox_id?: string;
  bucket?: 'hour' | 'day';
}

/** Body of every webhook POST. */
export interface WebhookEvent<T = MessageEventData> {
  id: string;
  type: WebhookEventType | 'webhook.test';
  created_at: string;
  data: T;
}

export interface MessageEventData {
  inbox: Inbox;
  thread_id: string;
  message: Message;
  bounce?: unknown;
  complaint?: unknown;
}

/** `data` of draft.* events. */
export interface DraftEventData {
  inbox: Inbox;
  draft: Draft;
  /** draft.sent only: the queued message. */
  message?: Message;
}

export interface AttachmentInput {
  filename: string;
  content_type: string;
  content_base64: string;
}

/** `text`, `html` or `data` is required. */
export interface SendInput<TData = unknown> {
  to: string | string[];
  cc?: string | string[];
  bcc?: string | string[];
  subject: string;
  text?: string;
  html?: string;
  attachments?: AttachmentInput[];
  labels?: string[];
  /**
   * Structured data: a JSON object or array, at most 64 KB serialized. Hosted recipients get it as
   * `message.data` (agent channel); email recipients get an `agentboxd-data.json` attachment.
   */
  data?: TData;
  /** Advisory message kind (default `message`). */
  type?: MessageType;
  /**
   * The agent's own author signature over exactly this content (`signAgentMessage` in `agentboxd/identity`, or use
   * `messages.sendSigned`). A signed message goes out exactly as signed. Not with `send_at`.
   */
  agent_signature?: string;
}

/** `text`, `html` or `data` is required. */
export interface ReplyInput<TData = unknown> {
  text?: string;
  html?: string;
  attachments?: AttachmentInput[];
  reply_all?: boolean;
  labels?: string[];
  data?: TData;
  type?: MessageType;
  /** The agent's own author signature (see `SendInput.agent_signature`). */
  agent_signature?: string;
}

export interface WaitQuery {
  /** Seconds to wait, 1–60 (default 30). */
  timeout?: number;
  /** ISO timestamp; only messages created after it count. Default: when the request arrives. */
  since?: string;
  /** Case-insensitive substring match on the From header. */
  from?: string;
  /** Case-insensitive substring match on the subject. */
  subject?: string;
  /** Default: inbound. */
  direction?: 'inbound' | 'outbound';
  /** Only agent-channel (or email) messages. */
  channel?: MessageChannel;
  /** Only this message type, e.g. `task`. */
  type?: MessageType;
}

// ---------- claim/ack lease queue ----------

/** POST /v1/inboxes/:id/messages/claim. */
export interface ClaimInput {
  /** Messages per claim, 1–50 (default 10). */
  limit?: number;
  /** How long the lease hides each message from other claims, 30–3600 s (default 300). */
  lease_seconds?: number;
  /** Free-form consumer name stored with the lease (≤ 100 characters), for debugging. */
  consumer?: string;
  /** Long-poll: wait up to this many seconds (0–30, default 0) for something to claim. */
  wait?: number;
  /** Only messages whose AI categorisation is done, skipped or failed (so the injection score is there). */
  enriched?: boolean;
  /** First claim only: where the queue starts (ISO time). Default: now, so the history is not claimable. */
  since?: string;
  /** Only this message type, e.g. `task` (agent messaging). */
  type?: MessageType;
  /** Only messages from other Agentboxd agents (`agent`) or only email. */
  channel?: 'agent' | 'email';
}

/** One claimed message. Present `lease_id` to ack, nack or extend. */
export interface Lease {
  lease_id: string;
  lease_until: string;
  /** 1 on the first delivery; higher means a redelivery (a lease ran out or was nacked). */
  delivery_count: number;
  message: Message;
}

export interface ClaimResult {
  data: Lease[];
  /** True when the inbox is paused: nothing is claimable until it is resumed. */
  paused: boolean;
}

/** `gone: true` when the message was deleted meanwhile (retention, inbox deleted). */
export type AckResult = { id: string; acked_at: string; gone?: undefined } | { id: string; gone: true };
export type NackResult =
  | { id: string; delivery_count: number; available_at: string; dead_letter: boolean; gone?: undefined }
  | { id: string; gone: true };
export type ExtendResult = { id: string; lease_id: string; lease_until: string; gone?: undefined } | { id: string; gone: true };

/** What a `consume()` handler gets next to the message. */
export interface ConsumeContext {
  leaseId: string;
  deliveryCount: number;
  /** Aborted when the lease is lost (it ran out and someone else claimed the message, or it was deleted). */
  signal: AbortSignal;
  /** Extends the lease now (the helper already does it in the background). */
  extend: (leaseSeconds?: number) => Promise<ExtendResult>;
}

export interface ConsumeOptions {
  /** Handlers running at once (default 1). */
  concurrency?: number;
  /** Lease per message (default 300 s). The lease is extended every third of it while the handler runs. */
  leaseSeconds?: number;
  /** Long-poll seconds per claim (default 20). */
  wait?: number;
  consumer?: string;
  enriched?: boolean;
  /** Stops the loop: no new claims, running handlers finish (and are acked or nacked). */
  signal?: AbortSignal;
  /** Nack delay after a failed handler: min(maxRetryDelaySeconds, retryDelaySeconds × 2^(delivery_count − 1)). Defaults 5 and 300. */
  retryDelaySeconds?: number;
  maxRetryDelaySeconds?: number;
  /** Seconds to wait before claiming again while the inbox is paused (default 10). */
  pausedPollSeconds?: number;
  /** Errors the loop survives (a failed handler, a lost lease, a network error while claiming). Default: console.error. */
  onError?: (err: unknown, lease?: Lease) => void;
}

/** Waits `ms`, or less when `signal` aborts. */
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal?.aborted) return resolve();
    const t = setTimeout(done, ms);
    function done() {
      clearTimeout(t);
      signal?.removeEventListener('abort', done);
      resolve();
    }
    signal?.addEventListener('abort', done, { once: true });
  });
}

/** Nack delay after the handler failed on its `deliveryCount`-th delivery. */
export function consumeRetryDelay(deliveryCount: number, base = 5, max = 300): number {
  return Math.min(max, Math.round(base * 2 ** Math.max(0, deliveryCount - 1)));
}

export interface RequestOptions {
  idempotencyKey?: string;
}

// ---------- agent self-signup ----------

/** GET /v1/signup/challenge. */
export interface SignupChallenge {
  challenge: string;
  algorithm: 'sha256';
  /** Leading zero bits SHA-256(`${challenge}:${solution}`) must have. */
  difficulty: number;
  expires_at: string;
  instructions: string;
  terms: string;
  terms_url: string;
}

/** An agent-created workspace (signup response, signup.* events). */
export interface SignupWorkspace {
  id: string;
  name: string;
  status: 'unclaimed' | 'claimed';
  created_at: string;
  claimed_at: string | null;
}

/** What an unclaimed workspace may do. */
export interface UnclaimedRestrictions {
  /** Distinct recipients per UTC day (429 unclaimed_recipient_limit past it). */
  recipients_per_day: number;
  /** Replies in threads that started with an inbound email, to people already in them, are not counted. */
  replies_to_inbound_threads: 'unlimited';
  inboxes: number;
  /** Identity-only agents (optional for older servers). */
  identities?: number;
  /** false until a human claims the workspace: identity tokens are refused (optional for older servers). */
  identity_tokens?: false;
  webhooks: false;
  custom_domains: false;
  event_stream: true;
  expires_after_inactive_days: number;
  /** GET /v1/account only. */
  recipients_today?: number;
}

/** POST /v1/signup (201). `api_key` is shown only here. */
export interface SignupResult {
  api_key: string;
  /** Optional for older servers. */
  kind?: 'mailbox';
  workspace: SignupWorkspace;
  inbox: Inbox;
  identity?: null;
  claim: { status: 'email_sent' | 'not_requested' | 'email_failed'; email: string | null };
  restrictions: UnclaimedRestrictions;
  docs_url: string;
  next_steps: string[];
}

/** POST /v1/signup with `kind: 'identity'`: an identity-only agent instead of an inbox. */
export interface IdentitySignupResult extends Omit<SignupResult, 'kind' | 'inbox' | 'identity'> {
  kind: 'identity';
  identity: Identity;
  inbox: null;
}

export interface SignupOptions {
  /** A label for the workspace ("<agentName>'s workspace"). Never used in any email. */
  agentName?: string;
  /** A human who can claim the workspace: Agentboxd emails them a claim link. */
  ownerEmail?: string;
  /** Default: `AGENTBOXD_BASE_URL` (legacy `MAILROOM_URL`), else https://api.agentboxd.com. */
  baseUrl?: string;
  fetch?: typeof fetch;
  /** Give up solving after this many hashes (default 2^32). */
  maxIterations?: number;
  /** `identity`: an identity-only agent (sign in to apps, no mailbox) instead of an inbox. Default `mailbox`. */
  kind?: 'mailbox' | 'identity';
}

/** GET /v1/account: workspace, claim status and limits. */
export interface Account {
  workspace: {
    id: string;
    name: string;
    plan: string;
    status: 'active' | 'suspended';
    /** Set while the workspace is under an emergency stop (sends and identity tokens answer 423 workspace_stopped). */
    emergency_stopped_at?: string | null;
    emergency_stop_reason?: string | null;
    ai_disclosure?: AiDisclosureSettings;
    created_at: string;
  };
  claim: {
    /** `not_applicable`: the workspace was created by a person, not by an agent. */
    status: 'unclaimed' | 'claimed' | 'not_applicable';
    claimed_at: string | null;
    /** Masked address of a claim link that is still valid. */
    pending_email: string | null;
    /** Unclaimed only: when the workspace is deleted if nothing happens before. */
    expires_at: string | null;
  };
  /** Effective limits (plan, overrides and the unclaimed overlay). `null` = unlimited. */
  limits: Record<string, number | null>;
  restrictions: UnclaimedRestrictions | null;
  /** Launch switches (absent on servers before agent messaging). */
  agent_messaging?: { enabled: boolean; directory_enabled: boolean; agent_keys_enabled?: boolean; public_directory_enabled?: boolean };
}

// ---------- human on call ----------

export type EscalationTrigger = 'needs_human' | 'phishing' | 'blocked' | 'draft_failed' | 'emergency_stop';

export interface EscalationContact {
  email: string;
  /** `pending` until the person clicks the link in the confirmation email; only confirmed contacts get alerts. */
  status: 'pending' | 'confirmed';
  confirmed_at: string | null;
}

export interface QuietHours {
  /** `HH:MM`, 24-hour, in `timezone`. The window may wrap midnight. */
  start: string;
  end: string;
  /** IANA name, e.g. `Europe/Paris`. */
  timezone: string;
}

/** GET/PUT /v1/escalation: who is alerted, for what, and how. */
export interface EscalationSettings {
  contacts: EscalationContact[];
  triggers: Record<EscalationTrigger, boolean>;
  /** `immediate`: one email per escalation (up to `max_per_hour`, the rest in the next digest). `digest`: batched. */
  delivery: 'immediate' | 'digest';
  max_per_hour: number;
  quiet_hours: QuietHours | null;
  /** Adds the first 500 characters of the email (untrusted content) to alerts. Off by default. */
  include_excerpt: boolean;
}

/** PUT /v1/escalation: fields left out keep their value; `contacts` (at most 5) replaces the list. */
export interface EscalationUpdate {
  contacts?: string[];
  triggers?: Partial<Record<EscalationTrigger, boolean>>;
  delivery?: 'immediate' | 'digest';
  max_per_hour?: number;
  quiet_hours?: QuietHours | null;
  include_excerpt?: boolean;
}

/** GET/PUT /v1/inboxes/:id/escalation: an inbox's own contacts (and triggers) instead of the workspace's. */
export interface InboxEscalation {
  override: boolean;
  contacts: EscalationContact[];
  triggers: Record<EscalationTrigger, boolean> | null;
}

export interface InboxEscalationUpdate {
  override?: boolean;
  contacts?: string[];
  triggers?: Partial<Record<EscalationTrigger, boolean>> | null;
}

/** Leading zero bits of a digest. */
function leadingZeroBits(buf: Uint8Array): number {
  let bits = 0;
  for (const byte of buf) {
    if (byte === 0) {
      bits += 8;
      continue;
    }
    return bits + Math.clz32(byte) - 24;
  }
  return bits;
}

/**
 * Solves a signup challenge: the first decimal `solution` (counting up from 0) such that
 * SHA-256(`${challenge}:${solution}`) starts with `difficulty` zero bits. About 2^difficulty hashes
 * (a few seconds at the default); yields to the event loop every 65,536 tries.
 */
export async function solveSignupChallenge(challenge: string, difficulty: number, maxIterations = 2 ** 32): Promise<string> {
  const prefix = createHash('sha256').update(`${challenge}:`, 'utf8');
  for (let i = 0; i < maxIterations; i++) {
    if (leadingZeroBits(prefix.copy().update(String(i), 'utf8').digest()) >= difficulty) return String(i);
    if ((i & 0xffff) === 0xffff) await new Promise((r) => setTimeout(r, 0));
  }
  throw new Error(`no solution found in ${maxIterations} tries`);
}

async function publicRequest<T>(fetchImpl: typeof fetch, baseUrl: string, method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetchImpl(new URL(baseUrl + path), {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = (await res.json().catch(() => ({}))) as { error?: { code: string; message: string; details?: unknown } };
  if (!res.ok) {
    const raw = res.headers?.get?.('retry-after');
    const retryAfter = raw ? Number(raw) : NaN;
    throw new AgentboxdError(
      res.status,
      json.error?.code ?? 'http_error',
      json.error?.message ?? res.statusText,
      json.error?.details,
      Number.isFinite(retryAfter) ? retryAfter : undefined,
    );
  }
  return json as T;
}

/** Default API base URL (the hosted service). Pass `baseUrl` for a self-hosted server, e.g. http://localhost:3000. */
export const DEFAULT_BASE_URL = 'https://api.agentboxd.com';

export class AgentboxdError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    /** The error's `details` object, when the server sent one. */
    public readonly details?: unknown,
    /**
     * Seconds to wait before retrying (a 429's `Retry-After` header, else `details.retry_after_seconds`).
     * Set for the burst send limit (`rate_limited`) and the per-key request rate limit.
     */
    public readonly retryAfter?: number,
  ) {
    super(message);
    // err.name kept as 'MailroomError' for compatibility (it is observable in logs and name checks).
    this.name = 'MailroomError';
  }
}

// ---------- client ----------

export interface AgentboxdOptions {
  /** Default: the `AGENTBOXD_API_KEY` environment variable (legacy fallback: `MAILROOM_API_KEY`). */
  apiKey?: string;
  /** Default: `AGENTBOXD_BASE_URL` (legacy fallback: `MAILROOM_URL`), else https://api.agentboxd.com. */
  baseUrl?: string;
  fetch?: typeof fetch;
}

/** Environment variable names read when `apiKey` / `baseUrl` are not passed, in priority order. */
export const API_KEY_ENV_VARS = ['AGENTBOXD_API_KEY', 'MAILROOM_API_KEY'] as const;
export const BASE_URL_ENV_VARS = ['AGENTBOXD_BASE_URL', 'MAILROOM_URL'] as const;

function readEnv(names: readonly string[]): string | undefined {
  // `process` may not exist (edge runtimes, browsers); treat that as "no env".
  const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env;
  for (const name of names) {
    const v = env?.[name]?.trim();
    if (v) return v;
  }
  return undefined;
}

type Query = Record<string, string | number | boolean | undefined>;

/** `{ plan: 'pro' }` → `{ 'metadata.plan': 'pro' }` (exact string match filters). */
/**
 * What an author signature covers (aSIM phase 2), as `messages.sendSigned` hands it to the signer. `attachments`:
 * the raw bytes (or their SHA-256 hex). `to`/`cc` are left out when a recipient is a handle.
 */
export interface AuthoredMessage {
  from: string;
  subject?: string;
  text?: string;
  html?: string;
  data?: unknown;
  type?: MessageType;
  attachments?: (Uint8Array | string)[];
  to?: string[];
  cc?: string[];
  inReplyTo?: string;
}

/** Signs authored content with the agent's own key: `agentSigner(key)` in `agentboxd/identity`. */
export type AgentMessageSigner = (content: AuthoredMessage) => Promise<string>;

/** `Name <a@b.com>` → `a@b.com`, lowercase. */
function bareAddressOf(raw: string): string {
  const m = /<([^>]+)>\s*$/.exec(raw);
  return (m ? m[1]! : raw).trim().toLowerCase();
}

function base64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64.replace(/\s+/g, ''));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

function metadataQuery(filter: Record<string, string | number | boolean> | undefined): Query {
  const out: Query = {};
  for (const [k, v] of Object.entries(filter ?? {})) out[`metadata.${k}`] = String(v);
  return out;
}

export class Agentboxd {
  /**
   * Agent self-signup, no API key needed: fetches a proof-of-work challenge, solves it (a few seconds of
   * CPU), and creates an unclaimed workspace with one inbox. Returns the one-time `api_key`, the inbox and
   * a ready `client`. Store the key: it is shown only once. Until a human claims the workspace (pass
   * `ownerEmail`, or call `client.account.requestClaim(email)` later) sending is limited and webhooks are off.
   *
   *   const { client, inbox, api_key } = await Agentboxd.signup({ agentName: 'research-agent', ownerEmail: 'me@example.com' });
   *
   * `kind: 'identity'` creates an identity-only agent (sign in to apps, no mailbox) and returns `identity`
   * instead of `inbox`; it can mint identity tokens once a human has claimed the workspace.
   */
  static async signup(opts: SignupOptions & { kind: 'identity' }): Promise<IdentitySignupResult & { client: Agentboxd }>;
  static async signup(opts?: SignupOptions & { kind?: 'mailbox' }): Promise<SignupResult & { client: Agentboxd }>;
  static async signup(opts: SignupOptions = {}): Promise<(SignupResult | IdentitySignupResult) & { client: Agentboxd }> {
    const fetchImpl = opts.fetch ?? fetch;
    const baseUrl = (opts.baseUrl ?? readEnv(BASE_URL_ENV_VARS) ?? DEFAULT_BASE_URL).replace(/\/+$/, '');
    const ch = await publicRequest<SignupChallenge>(fetchImpl, baseUrl, 'GET', '/v1/signup/challenge');
    const solution = await solveSignupChallenge(ch.challenge, ch.difficulty, opts.maxIterations);
    const result = await publicRequest<SignupResult | IdentitySignupResult>(fetchImpl, baseUrl, 'POST', '/v1/signup', {
      challenge: ch.challenge,
      solution,
      ...(opts.agentName !== undefined && { agent_name: opts.agentName }),
      ...(opts.ownerEmail !== undefined && { owner_email: opts.ownerEmail }),
      ...(opts.kind !== undefined && { kind: opts.kind }),
    });
    return { ...result, client: new Agentboxd({ apiKey: result.api_key, baseUrl, fetch: opts.fetch }) };
  }

  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: AgentboxdOptions = {}) {
    const apiKey = opts.apiKey ?? readEnv(API_KEY_ENV_VARS);
    if (!apiKey) {
      throw new Error('No API key: pass { apiKey } or set the AGENTBOXD_API_KEY environment variable.');
    }
    this.apiKey = apiKey;
    this.baseUrl = (opts.baseUrl ?? readEnv(BASE_URL_ENV_VARS) ?? DEFAULT_BASE_URL).replace(/\/+$/, '');
    this.fetchImpl = opts.fetch ?? fetch;
  }

  async request<T>(method: string, path: string, body?: unknown, query?: Query, opts?: RequestOptions): Promise<T> {
    const url = new URL(this.baseUrl + path);
    for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined) url.searchParams.set(k, String(v));
    const headers: Record<string, string> = { Authorization: `Bearer ${this.apiKey}` };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (opts?.idempotencyKey) headers['Idempotency-Key'] = opts.idempotencyKey;
    const res = await this.fetchImpl(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    if (res.status === 204) return undefined as T;
    const json = (await res.json().catch(() => ({}))) as { error?: { code: string; message: string; details?: unknown } };
    if (!res.ok) {
      const details = json.error?.details;
      const raw = res.headers?.get?.('retry-after');
      const header = raw ? Number(raw) : NaN;
      const fromDetails = (details as { retry_after_seconds?: unknown } | undefined)?.retry_after_seconds;
      const retryAfter = Number.isFinite(header) ? header : typeof fromDetails === 'number' ? fromDetails : undefined;
      throw new AgentboxdError(res.status, json.error?.code ?? 'http_error', json.error?.message ?? res.statusText, details, retryAfter);
    }
    return json as T;
  }

  readonly inboxes = {
    /** `domain`: a verified custom domain of the workspace (default: the server's agent domain). */
    create: (
      input: { username?: string; display_name?: string; client_id?: string; metadata?: MetadataPatch; domain?: string; card?: AgentCardInput } = {},
    ) => this.request<Inbox & { card?: AgentCard }>('POST', '/v1/inboxes', input),
    /**
     * Temporary, receive-only inbox with a random address on the server's temporary domain. It (and
     * all its mail) is wiped at `expires_at`. `ttlSeconds`: 60–86 400 (default 900).
     */
    createTemporary: (input: { ttlSeconds?: number; display_name?: string; metadata?: MetadataPatch } = {}) =>
      this.request<Inbox>('POST', '/v1/inboxes', {
        ttl_seconds: input.ttlSeconds ?? 900,
        ...(input.display_name !== undefined && { display_name: input.display_name }),
        ...(input.metadata !== undefined && { metadata: input.metadata }),
      }),
    /**
     * `metadata` filters by exact value: `{ metadata: { team: 'billing' } }`. Temporary inboxes are
     * excluded unless `include_temporary: true`; `temporary: true` lists only them.
     */
    list: ({
      metadata,
      ...q
    }: {
      cursor?: string;
      limit?: number;
      metadata?: Record<string, string | number | boolean>;
      include_temporary?: boolean;
      temporary?: boolean;
    } = {}) => this.request<Page<Inbox>>('GET', '/v1/inboxes', undefined, { ...q, ...metadataQuery(metadata) }),
    get: (id: string) => this.request<Inbox>('GET', `/v1/inboxes/${id}`),
    /** Metadata is merged (null deletes a key). `ttl_seconds` extends a temporary inbox from now (max 24 h after creation). */
    update: (id: string, patch: { display_name?: string | null; metadata?: MetadataPatch; ttl_seconds?: number }) =>
      this.request<Inbox>('PATCH', `/v1/inboxes/${id}`, patch),
    delete: (id: string) => this.request<void>('DELETE', `/v1/inboxes/${id}`),
    /**
     * Kill switch: every send from the inbox is refused (423 `inbox_paused`) until `resume`. Inbound
     * mail is still stored; its events and AI categorisation are held until then.
     */
    pause: (id: string, opts: { reason?: string } = {}) => this.request<Inbox>('POST', `/v1/inboxes/${id}/pause`, opts),
    /** Sending works again; the held inbound events are emitted in arrival order (`released_events`). */
    resume: (id: string) => this.request<Inbox & { released_events: number }>('POST', `/v1/inboxes/${id}/resume`),
    /**
     * Crash-safe consumer loop over the claim/ack queue: claims messages, runs `handler` for each (up
     * to `concurrency` at once), extends the lease while it runs, acks when it returns and nacks with
     * backoff when it throws. Delivery is at-least-once, so make the handler idempotent. Runs until
     * `signal` aborts; resolves once running handlers have finished.
     *
     *   const stop = new AbortController();
     *   await mr.inboxes.consume(inbox.id, async (message) => { await handle(message); }, { signal: stop.signal });
     */
    consume: (inboxId: string, handler: (message: Message, ctx: ConsumeContext) => unknown, opts: ConsumeOptions = {}) =>
      this.consumeLoop(inboxId, handler, opts),
  };

  private async consumeLoop(inboxId: string, handler: (message: Message, ctx: ConsumeContext) => unknown, opts: ConsumeOptions) {
    const concurrency = Math.max(1, Math.floor(opts.concurrency ?? 1));
    const leaseSeconds = opts.leaseSeconds ?? 300;
    const onError = opts.onError ?? ((err: unknown) => console.error('agentboxd consume:', err));
    const running = new Set<Promise<void>>();
    let failures = 0;

    const work = async (lease: Lease) => {
      const lost = new AbortController();
      const extend = async (seconds = leaseSeconds) => {
        const r = await this.messages.extend(lease.message.id, lease.lease_id, { lease_seconds: seconds });
        if (r.gone) lost.abort();
        return r;
      };
      const heartbeat = setInterval(() => {
        extend().catch((err: unknown) => {
          if (err instanceof AgentboxdError && err.status === 409) lost.abort();
          onError(err, lease);
        });
      }, Math.max(1000, (leaseSeconds * 1000) / 3));
      try {
        await handler(lease.message, { leaseId: lease.lease_id, deliveryCount: lease.delivery_count, signal: lost.signal, extend });
      } catch (err) {
        clearInterval(heartbeat);
        onError(err, lease);
        const delay = consumeRetryDelay(lease.delivery_count, opts.retryDelaySeconds ?? 5, opts.maxRetryDelaySeconds ?? 300);
        await this.messages.nack(lease.message.id, lease.lease_id, { delay_seconds: delay }).catch((e: unknown) => onError(e, lease));
        return;
      }
      clearInterval(heartbeat);
      await this.messages.ack(lease.message.id, lease.lease_id).catch((e: unknown) => onError(e, lease));
    };

    while (!opts.signal?.aborted) {
      if (running.size >= concurrency) {
        await Promise.race(running);
        continue;
      }
      let result: ClaimResult;
      try {
        result = await this.messages.claim(inboxId, {
          limit: concurrency - running.size,
          lease_seconds: leaseSeconds,
          wait: opts.wait ?? 20,
          ...(opts.consumer !== undefined && { consumer: opts.consumer }),
          ...(opts.enriched !== undefined && { enriched: opts.enriched }),
        });
        failures = 0;
      } catch (err) {
        // Wrong key, missing permission or unknown inbox: retrying won't help.
        if (err instanceof AgentboxdError && [400, 401, 403, 404].includes(err.status)) {
          await Promise.all(running);
          throw err;
        }
        onError(err);
        failures++;
        await sleep(Math.min(30_000, 1000 * 2 ** Math.min(failures, 5)), opts.signal);
        continue;
      }
      if (result.paused) {
        await sleep((opts.pausedPollSeconds ?? 10) * 1000, opts.signal);
        continue;
      }
      for (const lease of result.data) {
        const p: Promise<void> = work(lease).finally(() => running.delete(p));
        running.add(p);
      }
      // No long-poll (wait: 0) and nothing to do: don't spin.
      if (!result.data.length && !(opts.wait ?? 20)) await sleep(1000, opts.signal);
    }
    await Promise.all(running);
  }

  readonly messages = {
    /** Hosted recipients get an agent-channel copy (see `delivery`), everyone else email. */
    send: <TData = unknown>(inboxId: string, input: SendInput<TData>, opts?: RequestOptions) =>
      this.request<Message<TData>>('POST', `/v1/inboxes/${inboxId}/messages/send`, input, undefined, opts),
    reply: <TData = unknown>(inboxId: string, messageId: string, input: ReplyInput<TData>, opts?: RequestOptions) =>
      this.request<Message<TData>>('POST', `/v1/inboxes/${inboxId}/messages/${messageId}/reply`, input, undefined, opts),
    /**
     * aSIM phase 2: sends a message signed with the agent's own key. `sign` comes from `agentSigner(key)` in
     * `agentboxd/identity` (the private key stays with you). Covers text/html/data/attachments/type as sent, the
     * subject and the to/cc recipients (unless a recipient is a handle, which the server resolves).
     */
    sendSigned: async <TData = unknown>(inboxId: string, input: Omit<SendInput<TData>, 'agent_signature'>, sign: AgentMessageSigner, opts?: RequestOptions) => {
      const inbox = await this.request<Inbox>('GET', `/v1/inboxes/${inboxId}`);
      const list = (v: string | string[] | undefined) => (v === undefined ? [] : Array.isArray(v) ? v : [v]);
      const hasHandle = [...list(input.to), ...list(input.cc)].some((a) => a.trim().startsWith('@'));
      const to = [...new Set(list(input.to).map(bareAddressOf))];
      const cc = [...new Set(list(input.cc).map(bareAddressOf))].filter((a) => !to.includes(a));
      const agent_signature = await sign({
        from: inbox.address,
        subject: input.subject,
        text: input.text,
        html: input.html,
        data: input.data,
        type: input.type ?? 'message',
        attachments: (input.attachments ?? []).map((a) => base64ToBytes(a.content_base64)),
        ...(hasHandle ? {} : { to, cc }),
      });
      return this.request<Message<TData>>('POST', `/v1/inboxes/${inboxId}/messages/send`, { ...input, agent_signature }, undefined, opts);
    },
    /** `include_blocked: true` also returns mail stopped by the receive lists (label `blocked`). */
    list: (
      inboxId: string,
      q: {
        labels?: string[];
        is_read?: boolean;
        direction?: 'inbound' | 'outbound';
        include_blocked?: boolean;
        channel?: MessageChannel;
        type?: MessageType;
        cursor?: string;
        limit?: number;
      } = {},
    ) =>
      this.request<Page<Message>>('GET', `/v1/inboxes/${inboxId}/messages`, undefined, {
        ...q,
        labels: q.labels?.join(','),
      }),
    get: (id: string) => this.request<Message>('GET', `/v1/messages/${id}`),
    /**
     * Long-poll until a matching message arrives (or `timeout` seconds pass → null).
     * Only messages created after `since` (ISO time; default: now) are considered.
     */
    wait: async (inboxId: string, q: WaitQuery = {}) =>
      (await this.request<{ data: Message | null }>('GET', `/v1/inboxes/${inboxId}/messages/wait`, undefined, { ...q }))
        .data,
    /**
     * Returns the newest verification code/link received after `since`, waiting up to `timeout`
     * seconds for one to arrive. Null on timeout.
     */
    waitForVerification: async (inboxId: string, q: Omit<WaitQuery, 'direction' | 'subject'> = {}) =>
      (await this.request<{ data: VerificationResult | null }>('GET', `/v1/inboxes/${inboxId}/verification`, undefined, { ...q }))
        .data,
    update: (id: string, patch: { add_labels?: string[]; remove_labels?: string[]; is_read?: boolean }) =>
      this.request<Message>('PATCH', `/v1/messages/${id}`, patch),
    /**
     * Claim/ack queue: leases up to `limit` inbound messages, oldest first. Each is hidden from other
     * claims until `lease_until`; `ack` it when the work is done, or it comes back (at-least-once). The
     * first claim starts the queue: older mail is not claimable unless you pass `since`. A paused inbox
     * returns `{ data: [], paused: true }`. Permissions: messages:write and messages:read.
     */
    claim: (inboxId: string, input: ClaimInput = {}) =>
      this.request<ClaimResult>('POST', `/v1/inboxes/${inboxId}/messages/claim`, input),
    /** Done: the message is never claimed again. Idempotent. 409 lease_expired if the lease is no longer current. */
    ack: (messageId: string, leaseId: string, opts: { mark_read?: boolean } = {}) =>
      this.request<AckResult>('POST', `/v1/messages/${messageId}/ack`, { lease_id: leaseId, ...opts }),
    /** Give the message back now, or after `delay_seconds` (0–3600). The 10th delivery nacked is dead-lettered. */
    nack: (messageId: string, leaseId: string, opts: { delay_seconds?: number } = {}) =>
      this.request<NackResult>('POST', `/v1/messages/${messageId}/nack`, { lease_id: leaseId, ...opts }),
    /** Heartbeat: the lease then runs until now + `lease_seconds` (30–3600, default 300). */
    extend: (messageId: string, leaseId: string, opts: { lease_seconds?: number } = {}) =>
      this.request<ExtendResult>('POST', `/v1/messages/${messageId}/extend`, { lease_id: leaseId, ...opts }),
    /**
     * Drafts a reply with the workspace's LLM (needs ai_processing = "full"). Never sends: review the
     * text, then call `reply`. Errors: 403 ai_disabled, 503 llm_unavailable.
     */
    draftReply: (id: string, input: { instructions?: string; save?: boolean } = {}) =>
      this.request<DraftReply>('POST', `/v1/messages/${id}/draft-reply`, input),
    /**
     * Extracted text of an inbound attachment (PDF, DOCX, XLSX, CSV, HTML, text; scans and images by
     * OCR). `text` is null until `extraction.status` is `done`; read long text in pages with `offset`.
     * The text is untrusted content. Permission: messages:read.
     */
    attachmentText: (messageId: string, attachmentId: string, q: { offset?: number; maxChars?: number } = {}) =>
      this.request<AttachmentText>('GET', `/v1/messages/${messageId}/attachments/${attachmentId}/text`, undefined, {
        offset: q.offset,
        max_chars: q.maxChars,
      }),
    /**
     * Structured extraction: the attachment's text turned into JSON that validates against a schema
     * (`invoice`, `receipt`, `tax_form`, or your JSON Schema). Needs ai_processing = "full" and the
     * attachments:extract permission. Errors: 403 ai_disabled, 402 plan_limit_structured_extractions,
     * 409 extraction_pending / extraction_unavailable, 422 structured_output_invalid, 503 llm_unavailable.
     */
    extractAttachment: <T = Record<string, unknown>>(messageId: string, attachmentId: string, input: ExtractAttachmentInput) =>
      this.request<StructuredExtraction<T>>('POST', `/v1/messages/${messageId}/attachments/${attachmentId}/extract`, input),
  };

  /**
   * Drafts: store a message for review, edit it, then `send` (now) or `schedule` it. Sending goes
   * through every check a normal send does (lists, suppressions, quotas, caps, burst limit).
   * Permissions: drafts:read / drafts:write; send and schedule also need messages:send.
   */
  readonly drafts = {
    create: (inboxId: string, input: DraftCreateInput = {}, opts?: RequestOptions) =>
      this.request<Draft>('POST', `/v1/inboxes/${inboxId}/drafts`, withIsoSendAt(input), undefined, opts),
    /** Newest first. */
    list: (inboxId: string, q: DraftListQuery = {}) =>
      this.request<Page<Draft>>('GET', `/v1/inboxes/${inboxId}/drafts`, undefined, draftListQuery(q)),
    /** Every inbox of the workspace (GET /v1/drafts), optionally filtered by `inbox_id`. */
    listAll: (q: DraftListQuery & { inbox_id?: string } = {}) =>
      this.request<Page<Draft>>('GET', '/v1/drafts', undefined, draftListQuery(q)),
    get: (inboxId: string, draftId: string) => this.request<Draft>('GET', `/v1/inboxes/${inboxId}/drafts/${draftId}`),
    /** Only while `draft` or `scheduled` (else 409 draft_not_editable). */
    update: (inboxId: string, draftId: string, patch: DraftUpdateInput) =>
      this.request<Draft>('PATCH', `/v1/inboxes/${inboxId}/drafts/${draftId}`, withIsoSendAt(patch)),
    delete: (inboxId: string, draftId: string) => this.request<void>('DELETE', `/v1/inboxes/${inboxId}/drafts/${draftId}`),
    /** Sends now. A refused send throws the API error and leaves the draft as it was (with `error` set). */
    send: (inboxId: string, draftId: string, opts?: RequestOptions) =>
      this.request<{ draft: Draft; message: Message }>('POST', `/v1/inboxes/${inboxId}/drafts/${draftId}/send`, undefined, undefined, opts),
    /** `sendAt`: at least 1 minute and at most 30 days ahead (400 invalid_send_at). */
    schedule: (inboxId: string, draftId: string, sendAt: string | Date) =>
      this.request<Draft>('POST', `/v1/inboxes/${inboxId}/drafts/${draftId}/schedule`, { send_at: isoTime(sendAt) }),
    /** Cancels a draft or a scheduled send (terminal). */
    cancel: (inboxId: string, draftId: string) =>
      this.request<Draft>('POST', `/v1/inboxes/${inboxId}/drafts/${draftId}/cancel`),
  };

  readonly threads = {
    list: (inboxId: string, q: { cursor?: string; limit?: number } = {}) =>
      this.request<Page<Thread>>('GET', `/v1/inboxes/${inboxId}/threads`, undefined, q),
    get: (id: string) => this.request<ThreadWithMessages>('GET', `/v1/threads/${id}`),
    /** Metadata is merged (null deletes a key). Returns the thread without messages. */
    update: (id: string, patch: { metadata?: MetadataPatch; add_labels?: string[]; remove_labels?: string[] }) =>
      this.request<Thread>('PATCH', `/v1/threads/${id}`, patch),
  };

  /** Custom domains: connect a domain you own, publish `records`, then `verify`. */
  readonly domains = {
    create: (input: { domain: string; receiving?: boolean }) => this.request<Domain>('POST', '/v1/domains', input),
    list: () => this.request<Page<Domain>>('GET', '/v1/domains'),
    get: (id: string) => this.request<Domain>('GET', `/v1/domains/${id}`),
    /** Checks DNS now (at most once per 10 s per domain). */
    verify: (id: string) => this.request<Domain>('POST', `/v1/domains/${id}/verify`),
    update: (id: string, patch: { receiving?: boolean }) => this.request<Domain>('PATCH', `/v1/domains/${id}`, patch),
    /** 409 domain_in_use while live inboxes use it, unless `force` (which deletes those inboxes). */
    delete: (id: string, opts: { force?: boolean } = {}) =>
      this.request<void>('DELETE', `/v1/domains/${id}`, undefined, opts.force ? { force: true } : undefined),
    /**
     * DKIM key rotation: a new key on the other selector. Publish its record (`dkim_next` in `records`)
     * next to the current one; signing switches as soon as it is seen (or call `activateDkim`).
     */
    rotateDkim: (id: string) => this.request<Domain>('POST', `/v1/domains/${id}/dkim/rotate`),
    /** Checks DNS now and switches signing to the new key; 409 `dkim_record_not_found` until it is published. */
    activateDkim: (id: string) => this.request<Domain>('POST', `/v1/domains/${id}/dkim/activate`),
  };

  readonly contacts = {
    /** Newest activity first. `q` matches address/name; `metadata` filters by exact value. */
    list: ({
      metadata,
      ...q
    }: { q?: string; label?: string; cursor?: string; limit?: number; metadata?: Record<string, string | number | boolean> } = {}) =>
      this.request<Page<Contact>>('GET', '/v1/contacts', undefined, { ...q, ...metadataQuery(metadata) }),
    get: (id: string) => this.request<ContactWithThreads>('GET', `/v1/contacts/${id}`),
    /** 404 (AgentboxdError code not_found) when the workspace never exchanged mail with it. */
    byAddress: (address: string) =>
      this.request<ContactWithThreads>('GET', `/v1/contacts/by-address/${encodeURIComponent(address)}`),
    update: (id: string, patch: ContactUpdate) => this.request<Contact>('PATCH', `/v1/contacts/${id}`, patch),
  };

  readonly knowledge = {
    list: (q: { inbox_id?: string; cursor?: string; limit?: number } = {}) =>
      this.request<Page<KnowledgeListItem>>('GET', '/v1/knowledge', undefined, q),
    create: (input: { title: string; body: string; inbox_id?: string | null }) =>
      this.request<KnowledgeDoc>('POST', '/v1/knowledge', input),
    get: (id: string) => this.request<KnowledgeDoc>('GET', `/v1/knowledge/${id}`),
    update: (id: string, patch: { title?: string; body?: string; inbox_id?: string | null }) =>
      this.request<KnowledgeDoc>('PATCH', `/v1/knowledge/${id}`, patch),
    delete: (id: string) => this.request<void>('DELETE', `/v1/knowledge/${id}`),
    /** Ranked full-text search. With inbox_id, workspace-wide docs are included too. */
    search: (q: string, opts: { inbox_id?: string; limit?: number } = {}) =>
      this.request<{ data: KnowledgeSearchResult[] }>('GET', '/v1/knowledge/search', undefined, { q, ...opts }),
  };

  search(q: string, opts: { inbox_id?: string; cursor?: string; limit?: number; channel?: MessageChannel; type?: MessageType } = {}) {
    return this.request<Page<SearchResult>>('GET', '/v1/search', undefined, { q, ...opts });
  }

  readonly webhooks = {
    create: (input: {
      url: string;
      events?: WebhookEventType[];
      inbox_ids?: string[] | null;
      secret?: string;
      payload?: WebhookPayload;
    }) => this.request<Webhook>('POST', '/v1/webhooks', input),
    list: () => this.request<Page<Webhook>>('GET', '/v1/webhooks'),
    get: (id: string) => this.request<Webhook>('GET', `/v1/webhooks/${id}`),
    update: (
      id: string,
      patch: { url?: string; events?: WebhookEventType[]; inbox_ids?: string[] | null; enabled?: boolean; payload?: WebhookPayload },
    ) => this.request<Webhook>('PATCH', `/v1/webhooks/${id}`, patch),
    delete: (id: string) => this.request<void>('DELETE', `/v1/webhooks/${id}`),
    test: (id: string) => this.request<{ event_id: string; delivery_id: string }>('POST', `/v1/webhooks/${id}/test`),
    /** Every event type with a description and example bodies (public, no key needed server-side). */
    events: async () => (await this.request<{ data: WebhookCatalogEntry[] }>('GET', '/v1/webhooks/events')).data,
  };

  /** Allow/block lists (permission lists:manage). */
  readonly lists = {
    list: (q: { inbox_id?: string; direction?: ListDirection; kind?: ListKind } = {}) =>
      this.request<{ data: ListEntry[] }>('GET', '/v1/lists', undefined, q),
    /** `inbox_id` omitted/null = workspace-wide. 409 list_entry_exists for a duplicate. */
    create: (input: { direction: ListDirection; kind: ListKind; pattern: string; inbox_id?: string | null }) =>
      this.request<ListEntry>('POST', '/v1/lists', input),
    delete: (id: string) => this.request<void>('DELETE', `/v1/lists/${id}`),
  };

  /**
   * Identity-only agents: an Agentboxd identity without a mailbox (sign in to apps, no mail). They count
   * toward the plan's `identities` limit, not `inboxes`. Mint tokens with
   * `identity.token({ identityId, audience })`; the per-agent switch and history are under `identity.inbox`
   * with the identity's id.
   */
  readonly identities = {
    create: (input: IdentityCreateInput = {}) => this.request<Identity & { card?: AgentCard }>('POST', '/v1/identities', input),
    /** `metadata` filters by exact value: `{ metadata: { team: 'research' } }`. */
    list: ({ metadata, ...q }: { cursor?: string; limit?: number; metadata?: Record<string, string | number | boolean> } = {}) =>
      this.request<Page<Identity>>('GET', '/v1/identities', undefined, { ...q, ...metadataQuery(metadata) }),
    get: (id: string) => this.request<Identity>('GET', `/v1/identities/${id}`),
    /** Metadata is merged (null deletes a key). */
    update: (id: string, patch: { display_name?: string | null; metadata?: MetadataPatch }) =>
      this.request<Identity>('PATCH', `/v1/identities/${id}`, patch),
    /** Soft delete: the handle is never reissued; tokens and sign-ins stop at once. */
    delete: (id: string) => this.request<void>('DELETE', `/v1/identities/${id}`),
    /** Kill switch: identity tokens, approvals and exchanges are refused (423 inbox_paused) until `resume`. */
    pause: (id: string, opts: { reason?: string } = {}) => this.request<Inbox>('POST', `/v1/inboxes/${id}/pause`, opts),
    resume: (id: string) => this.request<Inbox & { released_events: number }>('POST', `/v1/inboxes/${id}/resume`),
  };

  /**
   * Sign in with Agentboxd: the agent's identity (an inbox, or an identity-only agent). `token` mints a
   * short-lived, single-use ID token for one relying party (permission identity:sign); `clients` manages
   * the apps your workspace registered and `inbox` the per-agent switch and sign-in history
   * (identity:manage to change). Relying parties verify tokens with `verifyAgentIdentityToken` from
   * `agentboxd/identity`.
   */
  readonly identity = {
    /** Pass `inboxId` for an inbox or `identityId` for an identity-only agent (same endpoint). */
    token: ({ inboxId, identityId, audience, nonce, scope, expiresIn }: IdentityTokenInput) =>
      this.request<IdentityToken>('POST', `/v1/inboxes/${identityId ?? inboxId}/identity-token`, {
        audience,
        ...(nonce !== undefined && { nonce }),
        ...(scope !== undefined && { scope: Array.isArray(scope) ? scope.join(' ') : scope }),
        ...(expiresIn !== undefined && { expires_in: expiresIn }),
      }),
    clients: {
      list: () => this.request<Page<IdentityClient>>('GET', '/v1/identity/clients'),
      create: (input: IdentityClientCreateInput) =>
        this.request<IdentityClientWithSecret>('POST', '/v1/identity/clients', input),
      get: (id: string) => this.request<IdentityClient>('GET', `/v1/identity/clients/${id}`),
      update: (id: string, patch: IdentityClientUpdateInput) =>
        this.request<IdentityClient>('PATCH', `/v1/identity/clients/${id}`, patch),
      /** Permanent: the client's tokens stop being accepted at the token and userinfo endpoints. */
      delete: (id: string) => this.request<void>('DELETE', `/v1/identity/clients/${id}`),
      /** A new secret, shown once; the old one stops working. */
      rotateSecret: (id: string) =>
        this.request<IdentityClientWithSecret>('POST', `/v1/identity/clients/${id}/secret`),
    },
    inbox: {
      get: (inboxId: string) => this.request<InboxIdentity>('GET', `/v1/inboxes/${inboxId}/identity`),
      /** `enabled: false` immediately refuses new tokens, sign-ins and userinfo for this inbox. */
      update: (inboxId: string, patch: { enabled: boolean }) =>
        this.request<InboxIdentity>('PATCH', `/v1/inboxes/${inboxId}/identity`, patch),
      /** Newest first. */
      signIns: (inboxId: string, q: { cursor?: string; limit?: number } = {}) =>
        this.request<Page<IdentitySignIn>>('GET', `/v1/inboxes/${inboxId}/identity/sign-ins`, undefined, q),
    },
  };

  /**
   * aSIM bundle and agent card of an inbox or identity-only agent (`inboxId` is either id). Reading needs
   * inboxes:read; changes need directory:write. Inbox-scoped keys manage their own card.
   */
  readonly agents = {
    get: (inboxId: string) => this.request<AgentBundle>('GET', `/v1/inboxes/${inboxId}/agent`),
    /** Creates the card (private by default) or updates it. */
    update: (inboxId: string, card: AgentCardInput) => this.request<AgentBundle>('PATCH', `/v1/inboxes/${inboxId}/agent`, card),
    /** Deletes the card: the agent leaves the directory at once. The inbox is unchanged. */
    delete: (inboxId: string) => this.request<void>('DELETE', `/v1/inboxes/${inboxId}/agent`),
    /** The agent stops signing its agent messages and directory verify answers `revoked`; mail keeps flowing. */
    revoke: (inboxId: string, opts: { reason?: string } = {}) => this.request<AgentBundle>('POST', `/v1/inboxes/${inboxId}/agent/revoke`, opts),
    /** Undoes a revoke (not an operator suspension: 403 agent_suspended). */
    restore: (inboxId: string) => this.request<AgentBundle>('POST', `/v1/inboxes/${inboxId}/agent/restore`),
    /** The own card as an OASF record (any visibility; needs inboxes:read). */
    oasf: (inboxId: string) => this.request<OasfRecord>('GET', `/v1/inboxes/${inboxId}/agent/oasf`),
    /**
     * aSIM phase 2: the agent's own signing keys. Generate one locally with `generateAgentKey()` and prove you hold
     * it with `createKeyProof()` (`agentboxd/identity`); only the public key is sent. Writes need identity:manage.
     */
    keys: {
      list: (inboxId: string) => this.request<{ data: AgentKey[] }>('GET', `/v1/inboxes/${inboxId}/agent/keys`),
      /** 201. At most 3 active keys; a key id is never registered twice on one agent. */
      register: (inboxId: string, input: { public_jwk: Record<string, string>; proof: string }) =>
        this.request<AgentKey>('POST', `/v1/inboxes/${inboxId}/agent/keys`, input),
      /** Rotation: no new signatures with it; old ones stay valid. */
      retire: (inboxId: string, kid: string) => this.request<AgentKey>('POST', `/v1/inboxes/${inboxId}/agent/keys/${encodeURIComponent(kid)}/retire`),
      /** Compromise: signatures made at or after `since` (default now) no longer verify. */
      revoke: (inboxId: string, kid: string, opts: { reason?: string; since?: string | Date } = {}) =>
        this.request<AgentKey>('POST', `/v1/inboxes/${inboxId}/agent/keys/${encodeURIComponent(kid)}/revoke`, {
          ...(opts.reason !== undefined && { reason: opts.reason }),
          ...(opts.since !== undefined && { since: isoTime(opts.since) }),
        }),
    },
  };

  /**
   * The agent directory (permission directory:read): resolve an address to its card, check a message signature
   * or an agent's live status, search your workspace's listed agents, report abuse. Rate limited; 503
   * `directory_disabled` when the server hasn't enabled it.
   */
  readonly directory = {
    /**
     * By address, or by handle (`{ handle: '@acme/billing' }`). Your workspace sees the full card, a publicly listed
     * card is seen in full by everyone, others get the minimal card. 404 `agent_not_found` for every miss.
     */
    resolve: (target: string | { address: string } | { handle: string }) =>
      this.request<{ card: AgentCard | PublicAgentCard | MinimalAgentCard; redirected_from?: string }>(
        'GET',
        '/v1/directory/resolve',
        undefined,
        typeof target === 'string' ? { address: target } : { ...target },
      ),
    /**
     * Pass a message's `agent.signature` (Agentboxd's delivery signature) or `author.signature` (the agent's own
     * key), plus the sender's current status; or an `address` (status only).
     */
    verify: (input: { signature: string; address?: never } | { address: string; signature?: never }) =>
      this.request<DirectoryVerifyResult>('POST', '/v1/directory/verify', input),
    /** Active cards with `workspace` visibility in your workspace; `scope: 'public'` searches the public directory. */
    search: (q: DirectorySearchQuery = {}) => this.request<Page<AgentCard | PublicAgentCard>>('GET', '/v1/directory/search', undefined, { ...q }),
    /** 202. At most 10 per workspace per day; the agent's owner learns the reason, never who reported. */
    report: (input: DirectoryReportInput) => this.request<{ received: true }>('POST', '/v1/directory/reports', input),
    /** The workspace handle (`@acme`): claiming and renaming need directory:write and an org-scoped key. */
    handle: {
      get: () => this.request<WorkspaceHandle>('GET', '/v1/directory/handle'),
      /** Claims or renames it; the old name redirects for 90 days. Handles are never reused. */
      set: (handle: string) => this.request<WorkspaceHandle>('PUT', '/v1/directory/handle', { handle }),
      /** Releases it (no redirect; nobody else can ever claim it). */
      release: () => this.request<WorkspaceHandle>('DELETE', '/v1/directory/handle'),
    },
  };

  /**
   * The public agent directory (aSIM phase 2): unauthenticated, cacheable, rate limited per IP. Publicly listed
   * agents only; 503 `public_directory_disabled` when the server hasn't enabled it.
   */
  readonly publicDirectory = {
    search: (q: Omit<DirectorySearchQuery, 'scope'> = {}) => this.request<Page<PublicAgentCard>>('GET', '/v1/public/agents', undefined, { ...q }),
    get: (address: string) => this.request<{ card: PublicAgentCard }>('GET', `/v1/public/agents/${encodeURIComponent(address)}`),
    /** The A2A 1.0 agent card (relay binding), signed by Agentboxd's directory key when agent signing is on. */
    a2aCard: (address: string) => this.request<Record<string, unknown>>('GET', `/v1/public/agents/${encodeURIComponent(address)}/agent-card.json`),
    oasf: (address: string) => this.request<OasfRecord>('GET', `/v1/public/agents/${encodeURIComponent(address)}/oasf.json`),
    /** The agent's own public keys (for `verifyAuthorSignature`). */
    keys: (address: string) => this.request<{ keys: PublishedAgentKey[] }>('GET', `/v1/public/agents/${encodeURIComponent(address)}/keys.json`),
    /** `handle('@acme/billing')`: follows renames within their 90-day redirect. */
    handle: (handle: string) => {
      const m = /^@?([^/]+)\/(.+)$/.exec(handle.trim());
      if (!m) throw new AgentboxdError(400, 'invalid_handle', 'handles look like @workspace/agent');
      return this.request<{ handle: string; address: string; card: PublicAgentCard; redirected_from?: string }>(
        'GET',
        `/v1/public/handles/${encodeURIComponent(m[1]!)}/${encodeURIComponent(m[2]!)}`,
      );
    },
  };

  /** The workspace behind this key: claim status (agent self-signup), effective limits and restrictions. */
  readonly account = {
    get: () => this.request<Account>('GET', '/v1/account'),
    /**
     * Agent-created, unclaimed workspaces: emails `email` a single-use link to claim the workspace (become
     * its owner; the restrictions lift). At most 3 per day. 409 already_claimed / not_claimable otherwise.
     */
    requestClaim: (email: string) =>
      this.request<{ status: 'email_sent'; email: string; expires_at: string }>('POST', '/v1/signup/claim', { email }),
  };
  /**
   * Human on call (permission escalation:manage): named people emailed when mail needs a human, looks like
   * phishing, was blocked, a scheduled send failed, or the workspace was stopped. New contacts confirm by email.
   */
  readonly escalation = {
    get: () => this.request<EscalationSettings>('GET', '/v1/escalation'),
    update: (input: EscalationUpdate) => this.request<EscalationSettings>('PUT', '/v1/escalation', input),
    /** Per-inbox override: its own contacts (and optionally triggers) instead of the workspace's. */
    inbox: {
      get: (inboxId: string) => this.request<InboxEscalation>('GET', `/v1/inboxes/${inboxId}/escalation`),
      update: (inboxId: string, input: InboxEscalationUpdate) =>
        this.request<InboxEscalation>('PUT', `/v1/inboxes/${inboxId}/escalation`, input),
    },
  };

  /**
   * Emergency stop (permission workspace:emergency, workspace keys): every inbox and identity of the
   * workspace stops sending (423 `workspace_stopped`), minting identity tokens and sending scheduled drafts.
   * Reads keep working. There is no API to resume: a workspace owner resumes in the dashboard.
   */
  emergencyStop(opts: { reason?: string } = {}) {
    return this.request<{ org: { id: string; name: string; emergency_stopped_at: string | null; emergency_stop_reason: string | null } }>(
      'POST',
      '/v1/emergency-stop',
      opts,
    );
  }

  /**
   * Deliverability summary (permission metrics:read, workspace keys): 7/30-day bounce and complaint rates,
   * suppressed contacts, your domains' SPF/DKIM/DMARC and the shared IP's blocklist status.
   */
  deliverability() {
    return this.request<DeliverabilitySummary>('GET', '/v1/deliverability');
  }

  /** Sent/received/delivery metrics, heatmap and resources (permission metrics:read). */
  metrics(q: MetricsQuery = {}) {
    return this.request<Metrics>('GET', '/v1/metrics', undefined, { ...q });
  }

  /**
   * Realtime events over a WebSocket (permission `messages:read`): the same bodies as webhooks, with
   * reconnect and resume. Async-iterable, or use `.on('event', …)`; `.close()` to stop.
   *
   *   for await (const e of mr.stream({ eventTypes: ['message.received'] })) console.log(e.data);
   */
  stream(opts: StreamOptions = {}): EventStream {
    return new EventStream(async () => (await this.streamToken()).url, opts);
  }

  /** A single-use, 60-second token for GET /v1/stream (for browsers and clients that can't send headers). */
  streamToken() {
    return this.request<{ token: string; expires_at: string; url: string }>('POST', '/v1/stream/token');
  }
}

// ---------- webhook verification ----------

/** @deprecated Use {@link Agentboxd}; `Mailroom` is the same class under its old name. */
export const Mailroom = Agentboxd;
/** @deprecated Use {@link Agentboxd}; `Mailroom` is the same class under its old name. */
export type Mailroom = Agentboxd;
/** @deprecated Use {@link AgentboxdError}; `MailroomError` is the same class, so `instanceof` works with either. */
export const MailroomError = AgentboxdError;
/** @deprecated Use {@link AgentboxdError}; `MailroomError` is the same class, so `instanceof` works with either. */
export type MailroomError = AgentboxdError;
/** @deprecated Use {@link AgentboxdOptions}. */
export type MailroomOptions = AgentboxdOptions;

/**
 * Verifies a webhook delivery. Pass the raw request body exactly as received (not re-serialized JSON),
 * and the X-Mailroom-Signature / X-Mailroom-Timestamp header values (header names kept from the original API).
 */
export function verifyWebhook(
  signature: string,
  timestamp: string,
  body: string | Buffer,
  secret: string,
  opts: { toleranceSeconds?: number } = {},
): boolean {
  const tolerance = opts.toleranceSeconds ?? 300;
  if (!/^\d+$/.test(timestamp) || !/^[0-9a-f]{64}$/i.test(signature)) return false;
  if (tolerance > 0 && Math.abs(Date.now() / 1000 - Number(timestamp)) > tolerance) return false;
  const expected = createHmac('sha256', secret)
    .update(`${timestamp}.`)
    .update(typeof body === 'string' ? Buffer.from(body, 'utf8') : body)
    .digest();
  return timingSafeEqual(expected, Buffer.from(signature, 'hex'));
}
