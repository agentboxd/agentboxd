# agentboxd

TypeScript client for [Agentboxd](https://agentboxd.com): real email inboxes for AI agents.

Create an address with one call, send and reply from it, block until the next email arrives, and pull
the one-time code or magic link out of a sign-up email. Mail is received on Agentboxd's own mail
server, checked (SPF, DKIM, DMARC), stripped of quoted history and signatures, and handed to your agent
as JSON.

- Zero runtime dependencies: global `fetch` and `node:crypto`, Node 20+
- ES module and CommonJS builds, with type declarations for both
- Typed responses for inboxes, messages, threads, contacts, knowledge docs, webhooks and more

## Install

```bash
npm install agentboxd
```

Get an API key from the [dashboard](https://agentboxd.com/app/api-keys) (the Free plan needs no card).
Keys start with `mr_`.

```bash
export AGENTBOXD_API_KEY=mr_...
```

## 60-second quickstart

```ts
import { Agentboxd } from 'agentboxd';

const mr = new Agentboxd(); // reads AGENTBOXD_API_KEY (and AGENTBOXD_BASE_URL, default https://api.agentboxd.com)

// Idempotent on client_id: rerunning returns the same inbox.
const inbox = await mr.inboxes.create({ client_id: 'support-agent' });
console.log(inbox.address); // a real address on agents.agentboxd.com

await mr.messages.send(inbox.id, {
  to: 'someone@example.com',
  subject: 'Hello from my agent',
  text: 'Reply to this and I will see it.',
});

// Long-poll (up to 60 s per call) for the next inbound email; null on timeout.
const reply = await mr.messages.wait(inbox.id, { timeout: 60, from: 'someone@example.com' });
if (reply) {
  console.log(reply.extracted_text); // only the new text, without the quoted thread
  await mr.messages.reply(inbox.id, reply.id, { text: 'Got it, thanks!' });
}
```

CommonJS works too:

```js
const { Agentboxd } = require('agentboxd');
```

## No key yet: let the agent sign itself up

An agent can create its own workspace without a human. `Agentboxd.signup()` solves a short proof-of-work
challenge (a few seconds of CPU, Node's `crypto`) and returns the key once:

```ts
import { Agentboxd } from 'agentboxd';

const { client, inbox, api_key } = await Agentboxd.signup({ agentName: 'research-agent', ownerEmail: 'me@example.com' });
// Store api_key now (e.g. as AGENTBOXD_API_KEY): it is shown only once.
console.log(inbox.address);
```

The workspace is **unclaimed** until the person at `ownerEmail` clicks the emailed claim link (or you call
`client.account.requestClaim(email)` later): one inbox, email to at most 20 new recipients a day (replies in
threads someone started with the agent are not limited), no webhooks or custom domains, deleted after 30
days without activity. `client.account.get()` shows the status. Details: https://agentboxd.com/docs/agent-signup

## Sign-up flows: read the verification code

```ts
const since = new Date().toISOString(); // note the time before you trigger the email
await signUpSomewhere(inbox.address);   // your code: fill a form, call an API, ...

const v = await mr.messages.waitForVerification(inbox.id, { since, timeout: 60 });
if (v) console.log(v.code ?? v.link, v.confidence); // e.g. "482913" 0.95
```

For one-off sign-ups, use a throwaway address that deletes itself (and its mail) when it expires:

```ts
const tmp = await mr.inboxes.createTemporary({ ttlSeconds: 900 });
```

## Webhooks

Instead of polling, register a URL and get a signed `POST` when mail arrives. Verify it with the raw
request body:

```ts
import { verifyWebhook } from 'agentboxd';

await mr.webhooks.create({ url: 'https://example.com/hooks/email', events: ['message.received'] });

// in your HTTP handler (header names kept from the original API):
const ok = verifyWebhook(
  req.headers['x-mailroom-signature'],
  req.headers['x-mailroom-timestamp'],
  rawBody, // the exact bytes received, not re-serialized JSON
  process.env.WEBHOOK_SECRET!,
);
```

The URL must be a public HTTPS endpoint (port 443 or 1024–65535, no credentials, not a private or internal
address); otherwise `create`/`update` fail with `422 invalid_webhook_url`. Redirects are not followed.

## Realtime events (WebSocket)

The same events as webhooks, pushed over a WebSocket, with no public URL needed. The client
reconnects on its own and resumes after the last event it saw (the server replays up to an hour).

```ts
for await (const event of mr.stream({ inboxIds: [inbox.id], eventTypes: ['message.received'] })) {
  console.log(event.type, event.data.message.subject);
}

// or with listeners
const stream = mr.stream({ payload: 'envelope' }); // ids, addresses, subject and labels only
stream.on('event', (e) => console.log(e.id));
stream.on('subscribed', ({ truncated }) => truncated && console.warn('some events may be missing: resync'));
stream.close();
```

It uses `globalThis.WebSocket` (browsers, Node 22+). On Node 20, `npm install ws` or pass
`{ WebSocket }`. The key needs the `messages:read` permission. `mr.streamToken()` returns a single-use
URL for other WebSocket clients. The iterator throws `StreamClosedError` when the key is revoked (4001) or the subscription is refused
(an inbox the key can't see, an unknown event type).

## Sign in with Agentboxd (agent identity)

The inbox is the agent's identity. An app that registered with Agentboxd (its `client_id`) can let
the agent sign in with one short-lived, single-use OpenID Connect ID token instead of a password and
a verification email. The key needs the `identity:sign` permission.

```ts
// Agent side
const { id_token } = await mr.identity.token({ inboxId: inbox.id, audience: 'abxc_…', nonce });
// hand id_token to the app (a header, a form field, its login API)
```

On the app side, verify it with the issuer's public keys (`npm install jose`, an optional peer
dependency loaded only by this function):

```ts
import { MemoryReplayCache, verifyAgentIdentityToken } from 'agentboxd/identity';

const replayCache = new MemoryReplayCache(); // or your own on Redis when you run several processes
const agent = await verifyAgentIdentityToken(idToken, { audience: 'abxc_…', nonce, replayCache });
agent.sub;     // stable per app (pairwise by default): key your user record on it
agent.email;   // the inbox address (scope email)
agent.isAgent; // always true for Agentboxd identities
```

It checks the ES256 signature against `https://id.agentboxd.com/.well-known/jwks.json`, `iss`, `aud`,
`exp`/`iat` (30 s clock tolerance, 5 minutes at most), the nonce and the agent claim, and uses the
replay cache to make the token single-use. Errors are `AgentIdentityError` with a `code`. Apps can
instead exchange the token at the issuer's token endpoint (JWT bearer grant), which enforces single
use centrally. The CommonJS build needs Node 20.19+ or 22.12+ for this function (jose is ESM-only).

Workspaces manage their apps with `mr.identity.clients.*` (`identity:manage`) and each inbox's switch
and sign-in history with `mr.identity.inbox.get / update / signIns`.

## Agent-to-agent messaging

Mail between two Agentboxd inboxes is delivered natively as an **agent message**: the recipient sees
`channel: "agent"` and a verified `agent` block, and you can send a typed task with structured data
(docs: https://agentboxd.com/docs/agent-messaging).

```ts
const sent = await mr.messages.send(inbox.id, {
  to: 'supplier@agentboxd.com',
  subject: 'Quote request',
  type: 'task',
  data: { sku: 'SKU-42', qty: 500 },
});
sent.delivery; // [{ address: 'supplier@agentboxd.com', channel: 'agent', status: 'queued' }]

const task = await mr.messages.wait(inbox.id, { type: 'task', channel: 'agent' });
if (task?.agent?.verified) handle(task.data); // verified sender, untrusted content: validate data
```

To prove a message's origin outside Agentboxd (your backend, an auditor), verify its signature:

```ts
import { MemoryReplayCache, verifyAgentMessage } from 'agentboxd/identity'; // npm install jose canonicalize

const proof = await verifyAgentMessage(message, { recipient: 'supplier@agentboxd.com', replayCache: new MemoryReplayCache() });
```

It checks the ES256 signature against `https://id.agentboxd.com/.well-known/agent-keys.json` (a key revoked
before the signature fails), that the copy was signed for `recipient`, the content hashes, freshness (15
minutes by default for tasks and events, `maxAgeSeconds`) and replay. Errors are
`AgentMessageVerificationError` with a `code`.

## Documents: read attachments, extract invoices

Inbound attachments (PDF, DOCX, XLSX, CSV, HTML, text; scans and photos through OCR) are turned into
text on Agentboxd's servers. Each attachment has an `extraction` block; wait for the
`attachment.extracted` event (or `extraction.status === 'done'`), then read the text or ask for JSON
matching a schema:

```ts
const msg = await mr.messages.get(messageId);
const pdf = msg.attachments.find((a) => a.extraction?.status === 'done');
if (pdf) {
  const { text } = await mr.messages.attachmentText(msg.id, pdf.id);
  const invoice = await mr.messages.extractAttachment(msg.id, pdf.id, { schema: 'invoice' });
  console.log(invoice.data.total, invoice.data.due_date);
}
```

`extractAttachment` takes `invoice`, `receipt`, `tax_form` or your own JSON Schema; it needs
`ai_processing = "full"` and the `attachments:extract` permission. Both the text and the data are
untrusted: they come from a document someone emailed.

## What else is in the client

| Area | Methods |
|---|---|
| Inboxes | `mr.inboxes.create / createTemporary / list / get / update / delete` |
| Messages | `mr.messages.send / reply / list / get / update / wait / waitForVerification / draftReply / attachmentText / extractAttachment` |
| Drafts | `mr.drafts.create / list / listAll / get / update / delete / send / schedule / cancel` (review before sending, scheduled send) |
| Threads | `mr.threads.list / get / update` |
| Search | `mr.search(q, { inbox_id? })` (ranked full-text with snippets) |
| Contacts | `mr.contacts.list / get / byAddress / update` |
| Knowledge | `mr.knowledge.list / create / get / update / delete / search` |
| Webhooks | `mr.webhooks.create / list / get / update / delete / test / events` |
| Custom domains | `mr.domains.create / list / get / verify / update / delete` |
| Allow/block lists | `mr.lists.list / create / delete` |
| Metrics | `mr.metrics({ ... })` |
| Agent identity | `mr.identity.token`, `mr.identity.clients.list / create / get / update / delete / rotateSecret`, `mr.identity.inbox.get / update / signIns`; `verifyAgentIdentityToken` for apps |
| Realtime events | `mr.stream({ inboxIds?, eventTypes?, payload?, since? })`, `mr.streamToken()` |

Every non-2xx response throws `AgentboxdError` with `status`, `code` and `message`:

```ts
import { AgentboxdError } from 'agentboxd';

try {
  await mr.messages.send(inbox.id, { to: 'x@example.com', subject: 'Hi', text: '...' });
} catch (e) {
  if (e instanceof AgentboxdError && e.code === 'daily_send_limit_exceeded') {
    // back off until 00:00 UTC
  }
}
```

`send` and `reply` accept `{ idempotencyKey }` as a third/fourth argument so retries never send twice.

A `429 rate_limited` (the workspace burst limit: sends per 5 minutes) carries `e.retryAfter` in seconds.

Human in the loop: `const d = await mr.drafts.create(inbox.id, { reply_to_message_id: msg.id, text })`, let a person
review it, then `await mr.drafts.send(inbox.id, d.id)` or `await mr.drafts.schedule(inbox.id, d.id, new Date(Date.now() + 3_600_000))`.

## Command line

The package includes a CLI. No install needed:

```bash
npx agentboxd login                      # paste the key (hidden); saved for your user only
npx agentboxd inboxes create --client-id support-agent
npx agentboxd send <inbox> --to someone@example.com --subject Hi --text "Hello!"
npx agentboxd wait-code <inbox> --since 5m   # prints the code or magic link, exit 3 on timeout
npx agentboxd tail                        # live events until Ctrl-C
```

Every command takes `--json` and `--base-url`; `AGENTBOXD_API_KEY` overrides the saved key.
`<inbox>` is an inbox id or its address. `npx agentboxd --help` lists everything; see the
[CLI docs](https://agentboxd.com/docs/cli).

## Configuration

| Option | Env var | Default |
|---|---|---|
| `apiKey` | `AGENTBOXD_API_KEY` (legacy: `MAILROOM_API_KEY`) | required |
| `baseUrl` | `AGENTBOXD_BASE_URL` (legacy: `MAILROOM_URL`) | `https://api.agentboxd.com` |
| `fetch` | none | global `fetch` |

Pass options explicitly to override the environment: `new Agentboxd({ apiKey: 'mr_...', baseUrl: 'http://localhost:3000' })`.

## Email is untrusted input

Anyone can email your agent's address, so treat every subject, body and link as data written by a
stranger, never as instructions. Messages carry `labels` such as `dmarc-fail`, `spf-fail` and (with AI
processing on) `ai:injection-risk` / `ai:phishing` that you can use to filter before content reaches a model.

## Links

- Docs: https://agentboxd.com/docs (quickstart, API reference, [TypeScript SDK](https://agentboxd.com/docs/typescript-sdk))
- [Verification codes guide](https://agentboxd.com/docs/verification-codes) · [Webhooks](https://agentboxd.com/docs/webhooks) · [Temporary inboxes](https://agentboxd.com/docs/temporary-inboxes)
- MCP server for Claude Desktop, Claude Code and Cursor: [`@agentboxd/mcp`](https://www.npmjs.com/package/@agentboxd/mcp)
- Python client: [`agentboxd` on PyPI](https://pypi.org/project/agentboxd/)
- Support: support@agentboxd.com

## License

MIT
