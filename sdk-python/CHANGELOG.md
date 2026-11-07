# Changelog

All notable changes to the `agentboxd` Python package. This project follows
[Semantic Versioning](https://semver.org/); while the version is 0.x, minor releases may contain
breaking changes, which are always listed here.

## 0.1.1 (2026-11-07)

Security fixes in the identity and signature checks (reported privately on 26 Oct), Meetings, and the API added
since 0.1.0.

- `verify_agent_identity_token`: the replay cache keeps a `jti` until `exp` plus `clock_tolerance` (the time the
  token still verifies), not until `exp`. A token captured in its last 30 s could be used a second time.
- `verify_agent_message` / `averify_agent_message` with a `replay_cache`:
  - the nonce is kept until `iat + max_age_seconds` plus `clock_tolerance`;
  - the nonce is recorded last, after `check_revocation` passed. A directory that couldn't be reached used to turn
    every retry into `replayed`;
  - a signature older than a day is refused (`too_old`) even without a freshness window (plain `message` type, or
    `max_age_seconds=None`): its nonce is kept for a day, so after that the same signature verified again. Without a
    replay cache nothing changes.
- `verify_agent_message` and `verify_author_signature`: a `revoked` key without a readable `revoked_at` is revoked
  for every signature (`key_revoked`). It used to verify (or, with an unreadable time, raise `ValueError`).
- `verify_author_signature` no longer trusts the signer's `iat` alone (a stolen key could backdate it past the
  revocation):
  - with the message's `created_at` (Agentboxd's time), a revoked key fails when `iat` or `created_at` is at or
    after `revoked_at`. Without `created_at`, nothing but the signer's claim dates the signature, so a revoked
    key's signature fails (`key_revoked`) whatever its `iat`;
  - a `retired` key fails when `iat` is at or after `retired_at`, with the new code `key_retired`. Old signatures
    stay valid, as the contract says, also on a copy delivered after the rotation;
  - an `iat` in the future, or more than 60 s after `created_at`, fails with the new code `issued_in_future`. New
    arguments `clock_tolerance` (default 30) and `now`.
- `verify_author_signature` and `sign_agent_message`: `to` and `cc` are one statement of who the message goes to.
  Given either, the signer signs both (the one left out as `[]`), and once either is signed the verifier checks both,
  the one left out meaning none: a cc added to a signed `to` fails with `content_mismatch`. It used to check only
  the one that was signed. The server and the TypeScript SDK do the same.
- `DirectoryVerifyResult` for an author signature: a revoked key's signature is never `valid` now, whatever its
  `iat`, and `reasons` may say `key_retired` or `issued_in_future`. `key_revoked_at` stays.
- `verify_agent_message` / `averify_agent_message` refuse a copy whose delivery signature names an author signature
  (`agent_sig`) when the message no longer carries it: `content_mismatch` (`author`), as for a different one.
- An `agent-keys.json` or `jwks.json` answer that isn't a key set (not JSON, or no `keys` list) raises
  `AgentMessageVerificationError` with code `unknown_key` (`AgentIdentityError` `invalid_token` for identity
  tokens) and isn't cached, so the next call fetches again.
- `AgentboxdError.docs_url`: for a refused send, where its fix is documented (e.g.
  `https://agentboxd.com/docs/send-refusals#sending_paused`); `None` for other errors.
- `webhooks.deliveries(webhook_id, status=, cursor=, limit=)`: the delivery log with status code, response time
  (`last_response_ms`), error, attempt number and next retry (`WebhookDelivery`). `webhooks.redeliver(webhook_id,
  delivery_id)` or `webhooks.redeliver(webhook_id, event_id=...)` sends one again with a fresh timestamp.
- `suppressions.list(...)` / `suppressions.remove(address, confirm=True)`: the workspace's own suppression list
  (`Suppression`). `WebhookEventType` includes `suppression.removed`.
- `WebhookEventType` includes the team events `member.invited`, `member.invite_revoked`, `member.joined`,
  `member.role_changed` and `member.removed`.
- `messages.list_all(...)`: messages of every inbox the key can see, newest first (`GET /v1/messages`), with the
  filters of `messages.list` except `promotions`.
- `account.add_agent(kind, expires_at=...)`: the new key stops working at that time; `AddAgentResult` gains
  `api_key_expires_at`. An expired key raises `AuthenticationError` with `code == "api_key_expired"`.
- `AsyncAgentboxd.stream()` raises `StreamClosedError` for an `error` frame only when it refuses the subscription
  (`invalid_json`, `invalid_message`, `invalid_subscription`, `inbox_not_found`, `rate_limited`). Any other code,
  such as a database error on the server during the replay, closes the connection and reconnects with backoff and
  `since`. It used to stop.
- Meetings (beta): `calendar.list(inbox_id, ...)` / `calendar.list_all(...)` (filters `from_`, `to`, `status`,
  `role`, `response`, `message_id`, the screening opt-ins, `cursor`, `limit`; `datetime` and `date` values are sent
  as ISO strings), `calendar.get(event_id)`, `calendar.respond(event_id, "accepted", comment=, propose=)` (the answer
  goes to the organizer only), `calendar.create(inbox_id, title=, start=, attendees=, ...)`,
  `calendar.update(event_id, ...)` (`description`, `location`, `conference_url=None` clear them) and
  `calendar.cancel(event_id, message=)`, sync and async, with `idempotency_key` on the four that send mail. Types
  `CalendarEvent`, `CalendarEventResult`, `CalendarCancelResult`, `CalendarAttendeeInput` and their parts. Ids are
  escaped path segments.
- `Message` gains `calendar` (`MessageCalendar`: `event_id`, `method`) when it carries calendar content.
  `event_id` is None when the message changed no meeting; `method` is `CalendarMethod`.
  `WebhookEventType` includes `calendar.invite.received`, `calendar.event.created`, `calendar.event.updated`,
  `calendar.event.cancelled` and `calendar.response.received`.
- Meetings, recurring series: `expand="occurrences"` on `calendar.list` / `calendar.list_all` lists each occurrence of
  a series between `from_` and `to` (at most 2 years); each has `series_id` (None for a single meeting) and the page
  `truncated` (both return `CalendarEventPage`). `CalendarRecurrence` is `{rrule (or None), rdates, exdates}`.
- Meetings, approval drafts: `draft=True` on `calendar.respond`, `create`, `update` and `cancel` saves the message as
  a draft for a person to approve instead of sending it (needs `drafts:write` instead of `messages:send`). Overloads
  type the result: `CalendarDraftResult` (`event` is None for a new meeting, `message` None, `draft`) or
  `CalendarCancelDraftResult` with `draft=True`, the sent result without it. `Draft` gains `calendar`
  (`DraftCalendar`: `action`, `method`, `event_id`, `removed_attendees`; None for other drafts).
- `MessageApproval.type` is `"user"`, `"api_key"`, `"connector"` or `"policy"` (a code-level approval policy, not a
  person or a key; `label` names it).

## 0.1.0 (2026-10-05)

First public release.

- `VerificationInfo` / `VerificationResult` carry `auth_failed`: the sender failed authentication (DMARC, or SPF
  without an aligned DKIM pass), so the code may be spoofed. `messages.wait_for_verification` skips such codes unless
  `include_unauthenticated=True`.
- `Inbox` gains `pending_draft_count`, `needs_human_count` and `recent_bounce_count`; `messages.list` takes `status`.
  `EscalationTrigger` gains `draft_created` (off by default).
- Contacts v2: `Contact` gains `kind` (`ContactKind`), `kind_source`, `name_source`, `domain` and `last_subject`.
  `contacts.list` takes `kind` (one kind or a list) and `domain`; `contacts.update` takes `kind`;
  `contacts.delete(contact_id, forget=True)` stops mail from the address creating it again; new
  `contacts.delete_many(kind=..., domain=..., forget=..., dry_run=...)` (`ContactBulkDeleteResult`) and
  `contacts.domains(kind=..., limit=...)` (`ContactDomainList`). Async client too.
- Screening: messages carry `screening` (`MessageScreening`: `state` `screened | pending | held | released`,
  `reason`, `released_at`). When the workspace screens agent mail (the default for new workspaces),
  `messages.claim`, `inboxes.consume` and `messages.wait` return only screened and released mail;
  `include_unscreened` and `include_held` opt in. `messages.list(screening=...)` filters by state. New
  `messages.release(message_id)` (permission `messages:release`) and webhook event `message.released`.
- In a workspace that screens agent mail, an API key gets held and unscreened messages without their content:
  `message["withheld"]` says so. `messages.get`, `messages.list` and `messages.batch_get` take `include_unscreened` /
  `include_held` (`include_held` needs `messages:release`, which is in no preset). `Inbox` gains `held_count`;
  `EscalationTrigger` gains `held`.
- `agentboxd.identity.verify_agent_identity_token` (and `averify_agent_identity_token`): verify a "Sign in with
  Agentboxd" ID token in Python, like the TypeScript SDK's `verifyAgentIdentityToken`: ES256 signature against the
  issuer's JWKS (fetched again once for an unknown `kid`), `iss`, `aud`, `exp`/`iat` with 30 s leeway and at most
  300 s of lifetime, `nonce`, the agent claim, and single use through a `ReplayCache` (`MemoryReplayCache` in one
  process). Returns `VerifiedAgentIdentity`, with the `workspace` and `runboxd` claims when present. Needs the
  `identity` extra (`pip install 'agentboxd[identity]'`, PyJWT with cryptography); no new dependency.
- `verify_agent_identity_token` and `verify_agent_message` fetch the key set again for an unknown `kid` at most
  once a minute per URL; inside that minute an unknown `kid` fails from the cache. A sender can no longer make
  every check fetch the keys.
- `domains.zone_file(domain_id)` returns a custom domain's DNS records as a BIND zone file (`DomainZoneFile`:
  `filename`, `content`), for DNS providers that import one.
- Webhook event types `domain.verified` and `domain.failed` (custom-domain status changes; `failed` pauses
  sending from the domain).
- Messages carry `auto_reply`: `True` on a received automatic reply (out of office, vacation responder), from its
  headers or the `ai:auto-reply` label. Don't answer those.
- Messages carry `analysis` (`MessageAnalysis`: `state`, `coverage`, `reason`): whether a received message was
  checked for prompt injection and phishing, and how much of it. `messages.claim` and `inboxes.consume` take
  `analysis="completed"` to get only checked messages.
- An id of `.` or `..` is refused with `ValueError` before any request: URLs resolve them into another route.
  Other characters in ids, `/` included, are escaped as before.

- Internal names now use Agentboxd; `MailroomError` remains importable as a deprecated alias of
  `AgentboxdError` (the same class).
- `contacts.delete(contact_id)` (`DELETE /v1/contacts/:id`): deletes a contact's name, notes, labels and metadata;
  its messages stay. Needs a workspace-wide key.
- `webhooks.rotate_secret(webhook_id, secret=None)` (`POST /v1/webhooks/:id/rotate-secret`): replaces a webhook's
  signing secret (yours, or a generated one) and returns it once.
- Drafts carry `approved_by` (`DraftApprover`: `type`, `id`, `label`), `approved_at` and
  `approved_content_sha256`: who approved the send, when, and the content it covered. Outbound messages sent from a
  draft carry `approval` (`MessageApproval`), which stays after the draft is deleted.
- **Behaviour change:** editing what a scheduled draft sends (recipients, subject, body, files, type or data) now
  puts it back to `draft`, unapproved. To keep it scheduled, pass `send_at` in the same update (that needs
  `messages:send`, as for any scheduling).

- Sync (`Agentboxd`) and async (`AsyncAgentboxd`) clients for the Agentboxd API: inboxes (permanent
  and temporary), messages (send, reply, list, get, update, `wait`, `wait_for_verification`,
  `draft_reply`), threads, search, contacts, knowledge docs, webhooks, custom domains, allow/block
  lists and metrics.
- Drafts (`client.drafts`): create, list, `list_all`, get, update, delete, send now, schedule
  (`send_at`) and cancel; `messages.draft_reply(..., save=True)` stores the AI reply as a draft.
- Attachment extraction: attachments carry an `extraction` block; `messages.attachment_text(...)` reads
  the extracted text (paged with `offset` / `max_chars`) and `messages.extract_attachment(...)` returns
  JSON matching `invoice`, `receipt`, `tax_form` or a custom JSON Schema. New webhook event types
  `attachment.extracted` and `attachment.extraction_failed`.
- `AsyncAgentboxd.stream()`: realtime events over a WebSocket (async iterator with reconnect and
  resume), with the optional `stream` extra (`pip install 'agentboxd[stream]'`); `stream_token()` on
  both clients.
- `AsyncAgentboxd.stream()` keeps reconnecting when the stream-token request fails with a network error, a 429 or
  a 5xx (during a deploy, for example), waiting at least `Retry-After`. It used to stop. 401 and 403 still raise.
- Sign in with Agentboxd: `identity.token(inbox_id, audience=..., nonce=, scope=, expires_in=)` mints a
  short-lived, single-use identity token; `identity.clients` (CRUD + `rotate_secret`) and
  `identity.inbox` (`get`, `update`, `sign_ins`) on both clients.
- Agent self-signup: `Agentboxd.signup(agent_name=, owner_email=)` / `await AsyncAgentboxd.signup(...)`
  (classmethods, no key needed) solve the API's proof of work and return a `Signup` with a ready
  `client`, the one-time `api_key` and the inbox; `solve_signup_challenge()` is exported.
  `client.account.get()` and `client.account.request_claim(email)` on both clients.
- Identities without a mailbox: `client.identities` (`create`, `list`, `get`, `update`, `delete`,
  `pause`, `resume`) on both clients, `identity.token(identity_id=..., audience=...)`, and
  `signup(kind="identity")` (``Signup.identity``). New `Identity` type; `Inbox.kind`.
- `inboxes.pause(inbox_id, reason=...)` / `inboxes.resume(inbox_id)` on both clients: the kill switch
  (sends refused with 423 `inbox_paused`, inbound events held until resume).
- `domains.rotate_dkim(domain_id)` / `domains.activate_dkim(domain_id)`: DKIM key rotation for custom domains.
- Claim/ack queue on both clients: `messages.claim(inbox_id, ...)`, `messages.ack/nack/extend(message_id,
  lease_id, ...)` and `inboxes.consume(inbox_id, handler, concurrency=..., stop=...)` (threads for the sync
  client, tasks for the async one; extends the lease while the handler runs, acks on success, nacks with
  backoff on an exception). `Metrics["queue"]` per inbox.
- `deliverability()` on both clients: bounce and complaint rates, suppressed contacts, domain authentication and
  the shared IP's blocklist status.
- Agent-to-agent messaging: `messages.send` / `reply` and `drafts.create` / `update` take structured `data`
  and a `type` (`message`, `task`, `event`); messages carry `channel`, `type`, `data`, `delivery` and the
  verified-sender `agent` block (`MessageAgent`); `messages.list`, `wait` and `search` filter by `channel`
  and `type`. `agentboxd.identity.verify_agent_message()` (and `averify_agent_message()`) checks a message's
  delivery signature outside Agentboxd, with the `identity` extra (`pip install 'agentboxd[identity]'`).
- `verify_webhook()` for the HMAC-SHA256 webhook signature; `iter_all` / `aiter_all` pagination helpers;
  `attachment_from_path` / `attachment_from_bytes`.
- Typed errors: `AgentboxdError` (deprecated alias `MailroomError`) and subclasses per status, with `details` and
  `retry_after` (seconds, on 429); `APIConnectionError` for network failures.
- Reads `AGENTBOXD_API_KEY` and `AGENTBOXD_BASE_URL` (legacy fallbacks: `MAILROOM_API_KEY`,
  `MAILROOM_URL`). Default base URL: `https://api.agentboxd.com`.
- Trust layer: `Message["ai_disclosure"]` (untrusted unless `verified`), `client.emergency_stop(reason)`, and
  human on call with `client.escalation.get()` / `update(...)` / `get_inbox(id)` / `update_inbox(id, ...)` (sync and
  async); the `workspace.stopped`, `workspace.resumed` and `escalation.sent` event types.
- Agent cards and the directory (aSIM): `client.agents` (`get`, `update`, `delete`, `revoke`, `restore`) for an
  inbox's or identity's card and bundle, `card=` on `inboxes.create` / `identities.create`, and `client.directory`
  (`resolve`, `verify`, `search`, `report`), sync and async. `verify_agent_message(..., check_revocation={"api_key":
  ...})` also asks the directory whether the sender is still active (codes `agent_revoked`, `agent_suspended`,
  `agent_deleted`, `revocation_check_failed`). The `agent.updated`, `agent.revoked`, `agent.deleted` and
  `agent.reported` event types; list entries of `type` `token` (`agents:any`, `agents:verified`, `workspace:self`).
- aSIM phase 2: agent-held keys (`client.agents.keys`: `list`, `register`, `retire`, `revoke`) and, in
  `agentboxd.identity` (`identity` extra), `generate_agent_key()` (Ed25519 or P-256), `create_key_proof()`,
  `sign_agent_message()` and `verify_author_signature()` (`AuthorSignatureVerificationError`); `messages.send` /
  `reply` take `agent_signature` and messages carry `author`. `verify_agent_message()` accepts the
  `domain_verified` assurance and checks that the delivery signature's `agent_sig` names the message's author
  signature. Public directory: `agents.update(..., visibility="public", handle=..., indexable=...)`,
  `agents.oasf(inbox_id)`, `directory.resolve(handle="@acme/billing")`, `directory.search(scope="public")`,
  `directory.get_handle` / `set_handle` / `release_handle`, and `client.public_directory` (`search`, `get`,
  `a2a_card`, `oasf`, `keys`, `handle`), sync and async. Cards carry `handle`, `domain`, the `domain_verified`
  badge, `listing`, `indexable` and `keys.agent`.
- Python 3.9+, only dependency `httpx`, fully typed (`py.typed`).
