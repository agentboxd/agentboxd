# Changelog

All notable changes to the `agentboxd` npm package. This project follows
[Semantic Versioning](https://semver.org/); while the version is 0.x, minor releases may contain
breaking changes, which are always listed here.

## 0.3.1 (unreleased)

- Internal names now use Agentboxd: `Agentboxd`, `AgentboxdError` and `AgentboxdOptions` are the primary
  declarations. `Mailroom`, `MailroomError` and `MailroomOptions` remain as deprecated aliases of the same
  class/type (`instanceof MailroomError` still works; `err.name` is unchanged). No behaviour change.

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
