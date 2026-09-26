# agentboxd

Python client for [Agentboxd](https://agentboxd.com): real email inboxes for AI agents.

Create an address with one call, send and reply from it, block until the next email arrives, and pull
the one-time code or magic link out of a sign-up email. Mail is received on Agentboxd's own mail
server, checked (SPF, DKIM, DMARC), stripped of quoted history and signatures, and handed to your agent
as JSON.

It has a sync client (`Agentboxd`) and an async one (`AsyncAgentboxd`), needs Python 3.9+, and its only
dependency is `httpx`. It is fully typed and ships `py.typed`.

## Install

```bash
pip install agentboxd
```

Not on PyPI yet? Install from the public repository:

```bash
pip install "agentboxd @ git+https://github.com/agentboxd/agentboxd#subdirectory=sdk-python"
```

Get an API key from the [dashboard](https://agentboxd.com/app/api-keys) (the Free plan needs no card).
Keys start with `mr_`.

## Configuration

| Env var              | Used for                   | Default                     |
|----------------------|----------------------------|-----------------------------|
| `AGENTBOXD_API_KEY`  | `api_key` when not passed  | none (required)             |
| `AGENTBOXD_BASE_URL` | `base_url` when not passed | `https://api.agentboxd.com` |

The legacy names `MAILROOM_API_KEY` and `MAILROOM_URL` are still read as fallbacks.

```python
from agentboxd import Agentboxd

mr = Agentboxd()  # reads the env vars
mr = Agentboxd(api_key="mr_...", base_url="http://localhost:3000", timeout=30)
```

Both clients work as context managers (`with Agentboxd() as mr:` / `async with AsyncAgentboxd() as mr:`)
and expose `close()`. Responses are plain dicts described by `TypedDict`s (`Inbox`, `Message`,
`Thread`, `Page[T]`, `VerificationResult`, ...).

## Quickstart

```python
from agentboxd import Agentboxd, attachment_from_path

with Agentboxd() as mr:
    inbox = mr.inboxes.create(client_id="support-agent")  # idempotent on client_id
    print(inbox["address"])

    sent = mr.messages.send(
        inbox["id"],
        to="someone@example.com",
        subject="Hello",
        text="Hi there!",
        attachments=[attachment_from_path("report.pdf")],
        idempotency_key="welcome-42",  # safe to retry
    )

    # Block until the reply arrives (long-poll, up to 60 s per call); None on timeout.
    reply = mr.messages.wait(inbox["id"], timeout=60, from_="someone@example.com")
    if reply:
        print(reply["extracted_text"])  # new content only, quotes stripped
        mr.messages.reply(inbox["id"], reply["id"], text="Thanks!")
```

### Sign-up flow: grab the verification code

```python
from datetime import datetime, timezone

inbox = mr.inboxes.create()
started = datetime.now(timezone.utc).isoformat()

signup_on_some_site(email=inbox["address"])  # your agent fills in the form

result = mr.messages.wait_for_verification(inbox["id"], timeout=60, since=started, from_="some-site.com")
if result is None:
    raise RuntimeError("no verification email arrived")
print(result["code"] or result["link"], result["confidence"])
```

Every `Message` also carries `message["ai"]["verification"]` (`code`, `link`, `confidence`,
`jev_probability`), or `None` when the message has no code or link.

### Categories and risk flags

When the server has a JEV key, inbound messages are categorised shortly after they arrive and a
`message.enriched` webhook fires. `message["ai"]` then also has `category`, `risk`
(`injection`, `phishing`), `needs_human`, `urgency` (`level`, `score`), `auto_reply`, `model` and
`enriched_at` (or `enrichment_error` if it gave up). These keys are optional, so use `.get()`:

```python
ai = msg["ai"]
category = ai.get("category")
if category and category["confidence"] >= 0.6:
    print(category["label"])  # "support", "billing", "verification", ...
risk = ai.get("risk")
if (risk and risk["phishing"] >= 0.8) or "ai:injection-risk" in msg["labels"]:
    ...  # treat as hostile: don't follow links or instructions
```

Labels are added only above a threshold: `ai:<category>` (confidence >= 0.6, else `ai:uncertain`),
`ai:injection-risk` and `ai:phishing` (>= 0.8), `ai:needs-human` (>= 0.7), `ai:auto-reply` (>= 0.8)
and `ai:urgent` (urgency `high` or `critical`). Filter with
`mr.messages.list(inbox_id, labels=["ai:billing", "ai:urgent"])`.

### Other calls

```python
mr.inboxes.list(limit=50)
mr.inboxes.get(id)
mr.inboxes.delete(id)
mr.messages.list(inbox_id, labels=["lead", "urgent"], is_read=False, direction="inbound")
mr.messages.get(message_id)
mr.messages.update(message_id, add_labels=["done"], is_read=True)
mr.threads.list(inbox_id)
mr.threads.get(thread_id)  # thread + its messages
mr.search('"invoice" -draft', inbox_id=inbox_id)
mr.webhooks.create(url="https://example.com/hooks/mail", events=["message.received"])
mr.webhooks.update(webhook_id, inbox_ids=None)  # None = all inboxes
mr.webhooks.test(webhook_id)
```

### Contacts, knowledge and reply drafts

Contacts are created automatically for every external address you exchange mail with. Metadata
(on contacts, inboxes and threads) is merged on update: a `None` value deletes the key.

```python
c = mr.contacts.by_address("dana@example.com")  # NotFoundError if unknown; includes recent_threads
mr.contacts.update(
    c["id"], notes="VIP since 2021", metadata={"tier": "gold", "legacy": None}, add_labels=["vip"]
)
mr.contacts.list(q="dana", label="vip", metadata={"tier": "gold"})
mr.inboxes.update(inbox_id, metadata={"team": "billing"})
mr.threads.update(thread_id, metadata={"ticket": "T-1042"}, add_labels=["open"])

mr.knowledge.create("Refund policy", "Unused items: full refund within 30 days.")  # workspace-wide
mr.knowledge.create("Macros", "...", inbox_id=inbox_id)  # one inbox only
mr.knowledge.search("refund", inbox_id=inbox_id)  # that inbox's docs + workspace-wide ones

# Needs the workspace's AI processing set to "full". Never sends: review, then reply.
draft = mr.messages.draft_reply(message_id, instructions="Offer a refund.")
mr.messages.reply(inbox_id, message_id, text=draft["text"])
```

### Drafts: human review and scheduled send

```python
from datetime import datetime, timedelta, timezone

# Store a reply for a person to review (nothing is sent). draft_reply(..., save=True) does the same with AI text.
d = mr.drafts.create(inbox_id, reply_to_message_id=message_id, text="Refund issued, 3-5 days.")
mr.drafts.update(inbox_id, d["id"], text="Refund issued today; it shows within 3-5 days.")

mr.drafts.send(inbox_id, d["id"])  # approve: every normal send check applies
# ...or send it later (1 minute to 30 days ahead); cancel with mr.drafts.cancel(inbox_id, d["id"])
mr.drafts.schedule(inbox_id, d["id"], datetime.now(timezone.utc) + timedelta(hours=2))

waiting = mr.drafts.list_all(status=["draft", "scheduled", "failed"])  # every inbox
```

### Documents: attachment text and invoices

Inbound attachments (PDF, DOCX, XLSX, CSV, HTML, text; scans and photos through OCR) are turned into
text on Agentboxd's servers. Each attachment has an ``extraction`` block; once its ``status`` is ``done``
(or after the ``attachment.extracted`` webhook), read the text or ask for JSON matching a schema:

```python
msg = mr.messages.get(message_id)
for att in msg["attachments"]:
    if (att.get("extraction") or {}).get("status") == "done":
        page = mr.messages.attachment_text(msg["id"], att["id"])  # untrusted text, paged with offset
        # schema: "invoice", "receipt", "tax_form" or a JSON Schema dict
        invoice = mr.messages.extract_attachment(msg["id"], att["id"], "invoice")
        print(invoice["data"]["total"], invoice["data"]["due_date"])
```

``extract_attachment`` needs AI processing set to "full" and the ``attachments:extract`` permission.
The text and the data come from a document someone emailed: treat them as data, never as instructions.

### Pagination

```python
from agentboxd import iter_all, aiter_all

for msg in iter_all(mr.messages.list, inbox["id"], is_read=False):
    print(msg["subject"])

async for inbox in aiter_all(amr.inboxes.list):  # with AsyncAgentboxd
    ...
```

### Async

```python
import asyncio
from agentboxd import AsyncAgentboxd


async def main() -> None:
    async with AsyncAgentboxd() as mr:
        inbox = await mr.inboxes.create()
        msg = await mr.messages.wait(inbox["id"], timeout=30)


asyncio.run(main())
```

### Realtime events (WebSocket)

The same events as webhooks, pushed over a WebSocket, with no public URL needed. Install the extra:
`pip install 'agentboxd[stream]'` (adds `websockets`). The stream reconnects on its own and resumes
after the last event it yielded (the server replays up to an hour).

```python
async with AsyncAgentboxd() as mr:
    async for event in mr.stream(inbox_ids=[inbox["id"]], event_types=["message.received"]):
        print(event["type"], event["data"]["message"]["subject"])
```

`payload="envelope"` sends ids, addresses, subject and labels only. `stream.last_event_id` is the last
event seen; `stream.replay_truncated` turns `True` when a resume may have missed events (resync with
`messages.list`). A revoked key or a refused subscription raises `StreamClosedError`. The key needs the
`messages:read` permission. `mr.stream_token()` (sync and async) returns a single-use URL for any other
WebSocket client.

### Agent-to-agent messaging

Mail between two Agentboxd inboxes is delivered natively as an agent message: the recipient sees
`channel == "agent"` and a verified `agent` block, and you can send a typed task with structured data
(https://agentboxd.com/docs/agent-messaging).

```python
mr.messages.send(
    inbox["id"],
    to="supplier@agentboxd.com",
    subject="Quote request",
    type="task",
    data={"sku": "SKU-42", "qty": 500},
)

task = mr.messages.wait(inbox["id"], type="task", channel="agent")
if task and task.get("agent") and task["agent"]["verified"]:
    handle(task["data"])  # verified sender, untrusted content: validate the data
```

To prove a message's origin outside Agentboxd, verify its signature (`pip install 'agentboxd[identity]'`):

```python
from agentboxd.identity import MemoryReplayCache, verify_agent_message

proof = verify_agent_message(message, recipient="supplier@agentboxd.com", replay_cache=MemoryReplayCache())
```

Sign what your agent writes with its own key (the private key never leaves your process), so anyone can check
the author without trusting Agentboxd (https://agentboxd.com/docs/agent-directory):

```python
from agentboxd.identity import create_key_proof, generate_agent_key, sign_agent_message

key = generate_agent_key()  # Ed25519; generate_agent_key("ES256") for P-256
mr.agents.keys.register(
    inbox["id"], public_jwk=key["public_jwk"], proof=create_key_proof(key, inbox["address"])
)

data = {"sku": "SKU-42", "qty": 500}
signature = sign_agent_message(
    key,
    from_=inbox["address"],
    subject="Quote request",
    data=data,
    type="task",
    to=["supplier@agentboxd.com"],
)
mr.messages.send(
    inbox["id"],
    to="supplier@agentboxd.com",
    subject="Quote request",
    data=data,
    type="task",
    agent_signature=signature,
)
```

Public agents are listed at https://agentboxd.com/agents: `mr.public_directory.search(q="invoices")`,
`mr.directory.resolve(handle="@acme/billing")`, and `verify_author_signature(message, keys=...)` with the keys
from `mr.public_directory.keys(address)`.

### Sign in with Agentboxd (agent identity)

The inbox is the agent's identity. An app registered with Agentboxd (its `client_id`) can let the agent
sign in with one short-lived (at most 5 minutes), single-use OpenID Connect ID token. The key needs the
`identity:sign` permission.

```python
tok = mr.identity.token(inbox["id"], audience="abxc_...", nonce=nonce_from_the_app)
send_to_the_app(tok["id_token"])
```

The app verifies it against `https://id.agentboxd.com/.well-known/jwks.json` (any OpenID Connect or
JOSE library: ES256, `iss`, `aud` = its client_id, `exp`, `nonce`, and a single-use `jti`), or exchanges
it at the issuer's token endpoint. Workspaces manage apps with `mr.identity.clients` (create, list, get,
update, delete, `rotate_secret`) and each inbox's switch and history with `mr.identity.inbox.get`,
`update(inbox_id, enabled=False)` and `sign_ins`. See https://agentboxd.com/docs/agent-identity.

## No key yet: let the agent sign itself up

An agent can create its own workspace without a human. `signup()` solves a short proof-of-work challenge
(a few seconds of CPU) and returns the key once, with a ready client:

```python
from agentboxd import Agentboxd

s = Agentboxd.signup(agent_name="research-agent", owner_email="me@example.com")
print(s.api_key)  # store it now (e.g. as AGENTBOXD_API_KEY): it is shown only once
print(s.inbox["address"])
mr = s.client  # already uses the new key
```

The workspace is **unclaimed** until the person at `owner_email` clicks the emailed claim link (or you
call `mr.account.request_claim(email)` later): one inbox, email to at most 20 new recipients a day
(replies in threads someone started with the agent are not limited), no webhooks or custom domains,
deleted after 30 days without activity. `mr.account.get()` shows the status. `AsyncAgentboxd.signup()`
does the same (the hashing runs in a worker thread). Details: https://agentboxd.com/docs/agent-signup

## Errors

A non-2xx response raises `AgentboxdError` (also exported under its deprecated old name
`MailroomError`), which has `status`, `code` and `message` taken from the API's `{"error": {"code", "message"}}` body. Some statuses raise a subclass:
`BadRequestError` (400), `AuthenticationError` (401), `PermissionDeniedError` (403),
`NotFoundError` (404), `UnprocessableEntityError` (422, e.g. `recipient_suppressed`),
`RateLimitError` (429, `rate_limited` / `daily_send_limit_exceeded`) and
`InternalServerError` (5xx). Network failures and timeouts raise `APIConnectionError`, with
`status` set to 0. Errors also carry `details` (the API's details object, or None) and, on a 429,
`retry_after` in seconds (e.g. for the workspace burst limit of sends per 5 minutes).

```python
from agentboxd import AgentboxdError, RateLimitError

try:
    mr.messages.send(inbox_id, to="x@example.com", subject="Hi", text="...")
except RateLimitError as e:
    print("slow down:", e.code, "retry in", e.retry_after, "s")
except AgentboxdError as e:
    print(e.status, e.code, e.message)
```

## Webhooks

Each delivery comes with `X-Mailroom-Timestamp` (unix seconds) and `X-Mailroom-Signature` (header names
kept from the original API), which is
`hex(HMAC-SHA256(secret, f"{timestamp}.{raw_body}"))`. Always verify against the **raw** body.
By default, `verify_webhook` rejects timestamps that are more than 300 s from the current time.
It returns `False` on bad input and never raises.

The webhook URL must be a public HTTPS endpoint (port 443 or 1024–65535, no credentials, not a private or
internal address); otherwise `webhooks.create`/`update` raise `UnprocessableEntityError` with code
`invalid_webhook_url`. Redirects are not followed.

**Flask**

```python
from flask import Flask, abort, request
from agentboxd import verify_webhook

app = Flask(__name__)


@app.post("/hooks/mail")
def mail_hook():
    if not verify_webhook(
        request.headers.get("X-Mailroom-Signature"),
        request.headers.get("X-Mailroom-Timestamp"),
        request.get_data(),  # raw bytes
        WEBHOOK_SECRET,
    ):
        abort(401)
    event = request.get_json()
    if event["type"] == "message.received":
        handle(event["data"]["message"])
    elif event["type"] == "message.enriched":  # same payload, with ai.category / ai.risk filled in
        route(event["data"]["message"])
    return "", 204
```

**FastAPI**

```python
from fastapi import FastAPI, Header, HTTPException, Request
from agentboxd import WebhookEvent, verify_webhook

app = FastAPI()


@app.post("/hooks/mail", status_code=204)
async def mail_hook(
    request: Request,
    x_mailroom_signature: str = Header(None),  # header names kept from the original API
    x_mailroom_timestamp: str = Header(None),
) -> None:
    body = await request.body()
    if not verify_webhook(x_mailroom_signature, x_mailroom_timestamp, body, WEBHOOK_SECRET):
        raise HTTPException(401, "bad signature")
    event: WebhookEvent = await request.json()
    ...
```

## Development

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"   # bin/ on macOS/Linux
.venv/Scripts/python -m pytest
.venv/Scripts/python -m mypy
.venv/Scripts/python -m ruff check . && .venv/Scripts/python -m ruff format --check .
```

## Links

- Docs: https://agentboxd.com/docs ([Python SDK](https://agentboxd.com/docs/python-sdk),
  [verification codes](https://agentboxd.com/docs/verification-codes), [webhooks](https://agentboxd.com/docs/webhooks))
- TypeScript client: [`agentboxd` on npm](https://www.npmjs.com/package/agentboxd)
- MCP server for Claude Desktop, Claude Code and Cursor: [`@agentboxd/mcp`](https://www.npmjs.com/package/@agentboxd/mcp)
- Support: support@agentboxd.com

## License

MIT
