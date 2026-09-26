# Changelog

All notable changes to the `agentboxd` Python package. This project follows
[Semantic Versioning](https://semver.org/); while the version is 0.x, minor releases may contain
breaking changes, which are always listed here.

## 0.1.0 (unreleased)

First public release.

- Internal names now use Agentboxd; `MailroomError` remains importable as a deprecated alias of
  `AgentboxdError` (the same class).

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
