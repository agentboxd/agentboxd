# Changelog

All notable changes to the `agentboxd` npm package. This project follows
[Semantic Versioning](https://semver.org/); while the version is 0.x, minor releases may contain
breaking changes, which are always listed here.

## 0.3.1 (2026-11-07)

- `verifyAgentIdentityToken`: the replay cache keeps a `jti` until `exp` plus the clock tolerance (the time the token
  still verifies), not until `exp`. A token captured in its last 30 s could be used a second time.
- `verifyAgentMessage` with a `replayCache`:
  - the nonce is kept until `iat + maxAgeSeconds` plus the clock tolerance;
  - the nonce is recorded last, after `checkRevocation` passed. A directory that couldn't be reached used to turn
    every retry into `replayed`;
  - a signature older than a day is refused (`too_old`) even without a freshness window (plain `message` type, or
    `maxAgeSeconds: null`): its nonce is kept for a day, so after that the same signature verified again. Without a
    replay cache nothing changes.
- `verifyAgentMessage` and `verifyAuthorSignature`: a `revoked` key without a readable `revoked_at` is revoked for
  every signature (`key_revoked`). It used to verify.
- `verifyAuthorSignature` no longer trusts the signer's `iat` alone (a stolen key could backdate it past the
  revocation):
  - with the message's `created_at` (`AuthoredMessageLike.created_at`, Agentboxd's time), a revoked key fails when
    `iat` or `created_at` is at or after `revoked_at`. Without `created_at`, nothing but the signer's claim dates the
    signature, so a revoked key's signature fails (`key_revoked`) whatever its `iat`;
  - a `retired` key fails when `iat` is at or after `retired_at`, with the new code `key_retired`. Old signatures
    stay valid, as the contract says, also on a copy delivered after the rotation;
  - an `iat` in the future, or more than 60 s after `created_at`, fails with the new code `issued_in_future`. New
    options `clockTolerance` (default 30 s) and `currentDate` (`VerifyAuthorSignatureOptions`).
- `verifyAuthorSignature`, `signAgentMessage` and `agentSigner`: `to` and `cc` are one statement of who the message
  goes to. Given either, the signer signs both (the one left out as `[]`), and once either is signed the verifier
  checks both, the one left out meaning none: a cc added to a signed `to` fails with `content_mismatch`. The server
  and the Python SDK do the same.
- `DirectoryVerifyResult` for an author signature: a revoked key's signature is never `valid` now, whatever its `iat`,
  and `reasons` may say `key_retired` (signed at or after `retired_at`) or `issued_in_future` (an `iat` more than
  60 s ahead). `key_revoked_at` stays.
- CLI `wait-code --from` takes a sender address (`no-reply@github.com`, exact) or a domain (`github.com`, that domain
  or a subdomain), matched against the sender's address. It was a substring of the whole From header, so
  `"github.com" <x@evil.example>` matched `--from github.com`. Codes from other senders are skipped. A value that is
  neither (e.g. `--from github`) is a usage error now.
- CLI `wait-code` prints the message's labels and the `warning:` line of `messages get` (failed SPF/DMARC, phishing,
  prompt injection) on stderr next to the code; `--json` adds `labels` to the result.
- `verifyAgentMessage` refuses a copy whose delivery signature names an author signature (`agent_sig`) when the
  message no longer carries it: `content_mismatch` (`author`), as for a different one. Until now the check ran only
  when both were there, so a message with its `author` block removed still verified.
- `verifyAgentMessage`: an `agent-keys.json` answer that isn't a key set (an error page served with 200, JSON without
  a `keys` list) fails with `AgentMessageVerificationError` code `unknown_key` and isn't cached, so the next call
  fetches again. It used to throw a plain `SyntaxError` or `TypeError` and keep a broken body cached for 5 minutes.
  Key entries that aren't objects are skipped.
- `stream()` ends on an `error` frame only when it refuses the subscription (`invalid_json`, `invalid_message`,
  `invalid_subscription`, `inbox_not_found`, `rate_limited`). Any other code, such as a database error on the server
  during the replay, closes the connection and reconnects with backoff and `since`; the `error` event then gets a
  plain `Error`, not a `StreamClosedError`. It used to stop.
- `AgentboxdError.docsUrl`: for a refused send, where its fix is documented (`docs_url` in the error body, e.g.
  `https://agentboxd.com/docs/send-refusals#sending_paused`). `Account.workspace` gains `sending_paused_at` and
  `sending_paused_reason` (sends answer `403 sending_paused` while set).
- `webhooks.deliveries(id, { status?, cursor?, limit? })`: the delivery log with status code, response time
  (`last_response_ms`), error, attempt number and next retry (`WebhookDelivery`). `webhooks.redeliver(id, deliveryId)`
  or `webhooks.redeliver(id, { eventId })` sends one again: the same payload with a fresh timestamp.
- `suppressions.list()` / `suppressions.remove(address, { confirm })`: the workspace's own suppression list
  (`Suppression`). `WebhookEventType` gains `suppression.removed`; `member.removed` can have reason `account_deleted`.
- `WebhookEventType` gains the team events `member.invited`, `member.invite_revoked`, `member.joined`,
  `member.role_changed` and `member.removed` (the workspace's record of who joins, leaves and changes role).
- `messages.listAll(q)`: messages of every inbox the key can see, newest first (`GET /v1/messages`), with the filters
  of `messages.list` except `promotions`. The CLI's `messages list` lists every inbox when no inbox is given.
- `account.addAgent({ expires_at })`: the new key stops working at that time; `AddAgentResult.api_key_expires_at`.
  An expired key gets `401 api_key_expired` (`AgentboxdError.code`); the CLI says to create a new key.
- `VerificationInfo.auth_failed`: the sender failed authentication (DMARC, or SPF without an aligned DKIM pass), so
  the code may be spoofed. `messages.waitForVerification` skips such codes unless you pass
  `include_unauthenticated: true` (new `VerificationQuery` type).
- `Inbox` gains `pending_draft_count`, `needs_human_count` and `recent_bounce_count`; `messages.list` takes `status`
  (e.g. `bounced` with `direction: 'outbound'`). `EscalationTrigger` gains `draft_created` (a draft waits for
  approval; off by default).

- Screening: messages carry `screening` (`MessageScreening`: `state` `screened | pending | held | released`, `reason`,
  `released_at`). When the workspace screens agent mail (the default for new workspaces), `messages.claim`,
  `inboxes.consume` and `messages.wait` return only screened and released mail; `include_unscreened` and
  `include_held` opt in. `messages.list` filters with `screening`. New `messages.release(id)` (permission
  `messages:release`) and webhook event type `message.released`. `MessageAi` gains `released_at` / `released_by`.
- In a workspace that screens agent mail, an API key gets held and unscreened messages without their content:
  `Message.withheld` says so. `messages.get`, `messages.list` and `messages.batchGet` take `include_unscreened` /
  `include_held` (`ScreeningOptIn`; `include_held` needs `messages:release`, which is in no preset). `Inbox` gains
  `held_count`; `EscalationTrigger` gains `held`.
- Messages carry `auto_reply`: `true` on a received automatic reply (out of office, vacation responder), from its
  `Auto-Submitted`, `X-Autoreply`, `X-Autorespond` or `Precedence` header or the `ai:auto-reply` label. Don't answer
  those. `messages.update` and `messages.batchUpdate` already set `is_read`; reading a message never does.
- Contacts v2: `Contact` gains `kind` (`ContactKind`: `person`, `automated`, `sales`, `unknown`), `kind_source`,
  `name_source`, `domain` and `last_subject`. `contacts.list` takes `kind` (one or a comma-separated list) and
  `domain`; `contacts.update` takes `kind` (set by hand, never changed by later mail); `contacts.delete(id, { forget })`
  stops mail from the address creating it again; new `contacts.deleteMany({ kind, domain, forget, dry_run })` (type
  `ContactBulkDeleteResult`) and `contacts.domains({ kind, limit })` (type `ContactDomain`). Automated senders no
  longer become contacts, and inbound To/Cc addresses do.
- `domains.zoneFile(id)` returns a custom domain's DNS records as a BIND zone file (`{ filename, content }`, type
  `DomainZoneFile`), for DNS providers that import one.
- New webhook event types `domain.verified` and `domain.failed`: a custom domain passed its required DNS records
  (first time, or again after failing), or a verified domain failed them 3 checks in a row and sending from it is
  paused. `data` is `{ domain, previous_status }`.
- Messages carry `analysis` (`MessageAnalysis`: `state`, `coverage`, `reason`): whether a received message was
  checked for prompt injection and phishing, and how much of it. `messages.claim` and `inboxes.consume` take
  `analysis: 'completed'` to get only checked messages. `MessageAi` gains `analysis_coverage` and more
  `enrichment_skipped` values.
- Every request path is checked before it is sent: a `.` or `..` segment (also percent-encoded), a `?`, a `#` or a
  backslash in it is refused with `AgentboxdError` code `invalid_argument` and no request is made. Ids and names
  never contain these, but a crafted id (for example a tool argument from a prompt-injected model) could otherwise
  reach a different API route with the same method. `assertSafePath` is exported.
- Every id placed in a request path is percent-encoded, as the Python SDK already did: an id with `/`, `?` or `#`
  stays one segment of the route it was given to (the API answers 404) instead of reaching a sibling route.
  `assertSafePath` remains the second check, for `.` and `..`, which encoding leaves as they are.
- Drafts carry `approved_by` (`{ type: 'user' | 'api_key' | 'connector' | 'policy', id, label }`), `approved_at`
  and `approved_content_sha256`: who approved the send, when, and the content it covered. `policy` is a code-level
  approval policy, not a person or a key (`label` names it, e.g. `Inbox Heist vault policy`). Outbound messages sent
  from a draft carry `approval` (`MessageApproval`), which stays after the draft is deleted. New types
  `DraftApprover` and `MessageApproval`.
- **Behaviour change:** editing what a scheduled draft sends (recipients, subject, body, files, type or data) now
  puts it back to `draft`, unapproved. To keep it scheduled, pass `send_at` in the same `drafts.update` (that needs
  `messages:send`, as for any scheduling).
- Internal names now use Agentboxd: `Agentboxd`, `AgentboxdError` and `AgentboxdOptions` are the primary
  declarations. `Mailroom`, `MailroomError` and `MailroomOptions` remain as deprecated aliases of the same
  class/type (`instanceof MailroomError` still works; `err.name` is unchanged). No behaviour change.
- `contacts.delete(id)` (`DELETE /v1/contacts/:id`): deletes a contact's name, notes, labels and metadata; its
  messages stay. Needs a workspace-wide key.
- `DirectoryVerifyResult.key_revoked_at`: for an author signature, when the agent key was revoked (or null).
- `webhooks.rotateSecret(id, { secret? })` (`POST /v1/webhooks/:id/rotate-secret`): replaces a webhook's signing
  secret (yours, or a generated one) and returns it once. `secret_hint` now shows only the last 4 characters.
- CLI: control characters in mail (sender, subject, body, file names, `tail` lines) are printed as visible
  `\uXXXX` escapes, so a message can't move the cursor, erase the warning or write the clipboard. `messages get`
  repeats the warning line after the body. `--json` output is unchanged.
- `verifyAgentMessage` fetches agent-keys.json again for an unknown `kid` at most once a minute per URL; inside that
  minute an unknown `kid` fails from the cache. Each fetch times out after 10 seconds.
- Meetings (beta): `calendar.list(inboxId, q)` / `calendar.listAll(q)` (filters `from`, `to`, `status`, `role`,
  `response`, `message_id`, the screening opt-ins, `cursor`, `limit`; `Date`s are sent as ISO times),
  `calendar.get(eventId)`, `calendar.respond(eventId, { response, comment?, propose? })` (the answer goes to the
  organizer only), `calendar.create(inboxId, input)`, `calendar.update(eventId, patch)` and
  `calendar.cancel(eventId, { message? })`; respond, create, update and cancel take `{ idempotencyKey }`. Types
  `CalendarEvent`, `CalendarEventListQuery`, `CalendarRespondInput`, `CalendarEventCreateInput`,
  `CalendarEventUpdateInput`, `CalendarEventResult`, `CalendarEventData` and their parts. Every id is one encoded path
  segment. Outside the beta the API answers `404 calendar_not_enabled`.
- `Message.calendar`: `{ event_id, method }` when a message carries an invite, an update, an answer or a cancellation
  (optional: older servers don't send it). `WebhookEventType` gains `calendar.invite.received`,
  `calendar.event.created`, `calendar.event.updated`, `calendar.event.cancelled` and `calendar.response.received`.
- CLI: `events list [<inbox>] [--from] [--until] [--role] [--response] [--status]`, `events get <event-id>` (the
  invite's text under the untrusted banner, and whether an authenticated sender vouches for the organizer) and
  `events respond <event-id> --response accepted|declined|tentative [--comment] [--propose-start --propose-end]`.
  `tail` shows the title and start of calendar events.
- Meetings, recurring series: `expand: 'occurrences'` in `calendar.list` / `calendar.listAll` lists each occurrence
  of a series between `from` and `to` (at most 2 years); each has `series_id` (null for a single meeting) and the
  page `truncated` (new type `CalendarEventPage`). `CalendarEvent.recurrence` is
  `{ rrule: string | null, rdates, exdates }`.
- Meetings, approval drafts: `draft: true` on `calendar.respond`, `create`, `update` and `cancel` saves the message as
  a draft for a person to approve instead of sending it (needs `drafts:write` instead of `messages:send`). The
  return type follows the option: `CalendarDraftResult` (`{ event, message: null, draft }`; `event` is null for a
  new meeting) or `CalendarCancelDraftResult` with `draft: true`, the sent result without it (`CalendarCallResult`).
  New `CalendarCancelInput`, `Draft.calendar` (`DraftCalendar`: `{ action, method, event_id, removed_attendees }`,
  null for other drafts).
- `Message.calendar` is `MessageCalendar`: `event_id` is `string | null` (null when the message changed no meeting)
  and `method` is `CalendarMethod` (which gains `ADD`).
- CLI: `events list --expand` lists each occurrence of a series (a series listed once is marked `(series)`);
  `events respond --draft` saves the answer for a person to approve; `drafts list` marks meeting drafts.

## 0.3.0 (2026-09-26)

aSIM phase 2 (additive; existing calls are unchanged):

- **Agent-held keys** in `agentboxd/identity`: `generateAgentKey({ alg })` (Ed25519 by default, ES256 accepted; the
  private key never leaves you), `createKeyProof()` (proof of possession for registration),
  `signAgentMessage()` / `agentSigner(key)` (the author signature over what the agent wrote) and
  `verifyAuthorSignature(message, { keys })` (returns what the signature covers; throws `AuthorSignatureError`).
  Library: `mr.agents.keys.list/register/retire/revoke(inboxId, …)`, `mr.messages.sendSigned(inboxId, input,
  signer)` and `agent_signature` on `send` / `reply`. Messages carry `author` (`{ verified, kid, alg, signature }`).
  `verifyAgentMessage` checks the delivery signature's `agent_sig` claim against `message.author` when both exist.
- **Public directory:** `mr.publicDirectory.search/get/a2aCard/oasf/keys/handle` (unauthenticated routes),
  `mr.directory.search({ scope: 'public' })`, `visibility: 'public'` and `indexable` on cards (listing state in
  `card.listing`).
- **Handles:** `mr.directory.handle.get/set/release()` for the workspace handle, `handle` on the card input,
  `mr.directory.resolve({ handle: '@acme/billing' })` (the address string form still works), and `@acme/billing`
  as a recipient.
- **Domain-verified badge:** `badges: ['domain_verified']`, `domain` and the `domain_verified` assurance on cards
  and bundles. Cards publish the agent's keys in `keys.agent`.
- **OASF export:** `mr.agents.oasf(inboxId)`.
- `DirectoryVerifyResult.signer` (`server` | `agent`); `Account.agent_messaging` gains `agent_keys_enabled` and
  `public_directory_enabled`.

## 0.2.0 (not published separately; included in 0.3.0)

- **CLI:** the package now has a `bin`, so `npx agentboxd <command>` works without installing (or
  `npm install -g agentboxd`). Commands: `login` / `logout` / `whoami`, `inboxes list|create|pause|resume`,
  `send`, `reply`, `messages list|get`, `wait-code` (prints a verification code or magic link; exit 3 on
  timeout), `tail` (live events over the WebSocket stream), `drafts list|send`. `--json` on every
  command, `--base-url` for a self-hosted server. `login` stores the key in the OS config directory
  (`~/.config/agentboxd/config.json`, `%APPDATA%\agentboxd\config.json` on Windows) readable by the
  user only; `AGENTBOXD_API_KEY` takes precedence. Built on the SDK and `node:util`: still zero runtime
  dependencies. `tail` needs Node 22+ or the `ws` package, like `stream()`.
- Library: identities without a mailbox (Shakehand without an inbox): `mr.identities.create/list/get/
  update/delete/pause/resume`, `mr.identity.token({ identityId, audience })`,
  `Agentboxd.signup({ kind: 'identity' })` (returns `identity` and `inbox: null`), `Inbox.kind`.
  `verifyAgentIdentityToken` returns `mailbox` (false for an identity without a mailbox, whose tokens
  carry no email) and `username` (`preferred_username`). Additive: existing calls are unchanged.
- Agent-to-agent messaging: `messages.send` / `reply` and drafts take structured `data` (typed:
  `send<T>(…, { data: T })` returns `Message<T>`) and a `type` (`message`, `task`, `event`); messages carry
  `channel`, `type`, `data`, `delivery` and the verified-sender `agent` block; `list`, `wait` and `search`
  filter by `channel` and `type`. `verifyAgentMessage()` in `agentboxd/identity` checks a message's delivery
  signature outside Agentboxd (keys from `agent-keys.json`, content hashes, freshness, replay); it uses
  `jose` and, for messages with data, `canonicalize` (both optional peer dependencies).
- Agent cards and the directory (aSIM): `mr.agents.get/update/delete/revoke/restore(inboxId)` for an inbox's or
  identity's card and bundle, `card` on `inboxes.create` / `identities.create`, and `mr.directory.resolve(address)`,
  `verify({ signature } | { address })`, `search({ q, capability, type, limit, cursor })` and `report(...)`.
  `verifyAgentMessage(..., { checkRevocation: { apiKey } })` also asks the directory whether the sender is still
  active (codes `agent_revoked`, `agent_suspended`, `agent_deleted`, `revocation_check_failed`). New types
  (`AgentCard`, `MinimalAgentCard`, `AgentCardInput`, `AgentBundle`, `DirectoryVerifyResult`, …), the `agent.*`
  webhook event types, and list entries of `type: 'token'`.

## 0.1.0 (2026-09-25)

First public release.

- `Agentboxd` client (also exported as `Mailroom`) for the Agentboxd API: inboxes (permanent and
  temporary), messages (send, reply, list, get, update, `wait`, `waitForVerification`, `draftReply`),
  threads, search, contacts, knowledge docs, webhooks, custom domains, allow/block lists and metrics.
- Drafts (`mr.drafts.*`): create, list, get, update, delete, send now, schedule (`send_at`) and cancel;
  `messages.draftReply(id, { save: true })` stores the AI reply as a draft.
- Agent self-signup: `Agentboxd.signup({ agentName?, ownerEmail? })` (static, no key needed) solves the
  API's proof-of-work challenge and returns the one-time `api_key`, the inbox and a ready `client`;
  `solveSignupChallenge()` is exported. `mr.account.get()` (claim status, limits) and
  `mr.account.requestClaim(email)`.
- Attachment extraction: every attachment has an `extraction` block (status, method, pages, ...);
  `messages.attachmentText(messageId, attachmentId, { offset?, maxChars? })` reads the extracted text
  and `messages.extractAttachment(messageId, attachmentId, { schema, instructions? })` returns JSON
  matching a built-in (`invoice`, `receipt`, `tax_form`) or custom JSON Schema. New webhook events
  `attachment.extracted` and `attachment.extraction_failed`.
- `inboxes.pause(id, { reason })` / `inboxes.resume(id)`: the kill switch (sends refused with 423
  `inbox_paused`, inbound events held until resume).
- `domains.rotateDkim(id)` / `domains.activateDkim(id)`: DKIM key rotation for custom domains.
- Claim/ack queue: `messages.claim(inboxId, opts)`, `messages.ack/nack/extend(id, leaseId, opts)` and the
  `inboxes.consume(inboxId, handler, { concurrency, leaseSeconds, signal })` loop (extends the lease while the
  handler runs, acks on success, nacks with backoff on a throw). `Metrics.queue` per inbox.
- `deliverability()`: bounce and complaint rates, suppressed contacts, domain authentication and the shared IP's
  blocklist status.
- `verifyWebhook()` for the HMAC-SHA256 webhook signature.
- Sign in with Agentboxd: `mr.identity.token({ inboxId, audience, nonce?, scope?, expiresIn? })` mints a
  short-lived, single-use identity token; `mr.identity.clients.*` and `mr.identity.inbox.*` manage apps
  and the per-inbox switch and history. `verifyAgentIdentityToken()` and `MemoryReplayCache` from the `agentboxd/identity`
  subpath let relying parties verify tokens; they use `jose`, an optional peer dependency that the main
  entry never loads.
- `mr.stream()`: realtime events over a WebSocket (async iterator or `.on('event')`), with reconnect
  and resume; `mr.streamToken()` for other WebSocket clients. Uses `globalThis.WebSocket`, or the
  optional `ws` package on Node 20.
- `AgentboxdError` (also exported as `MailroomError`) with `status`, `code`, `message`, `details` and
  `retryAfter` (seconds, on 429) for non-2xx responses.
- Reads `AGENTBOXD_API_KEY` and `AGENTBOXD_BASE_URL` from the environment when no options are passed
  (legacy fallbacks: `MAILROOM_API_KEY`, `MAILROOM_URL`). Default base URL: `https://api.agentboxd.com`.
- Trust layer: `Message.ai_disclosure` (the `Agent-Disclosure` header, parsed; untrusted unless `verified`),
  `mr.emergencyStop({ reason })` (stops every send of the workspace; only a person resumes, in the dashboard),
  human on call with `mr.escalation.get()` / `update()` and `mr.escalation.inbox.get(id)` / `update(id, ...)`, and
  the `workspace.stopped`, `workspace.resumed` and `escalation.sent` event types.
- ES module and CommonJS builds with type declarations; zero runtime dependencies; Node 20+.
