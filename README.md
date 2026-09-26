# Agentboxd

**Real email inboxes for AI agents.** Create an address with one API call, send and reply from it,
block until the next email arrives, and pull the one-time code or magic link out of a sign-up email.

[![npm: agentboxd](https://img.shields.io/npm/v/agentboxd?label=agentboxd)](https://www.npmjs.com/package/agentboxd)
[![npm: @agentboxd/mcp](https://img.shields.io/npm/v/@agentboxd/mcp?label=%40agentboxd%2Fmcp)](https://www.npmjs.com/package/@agentboxd/mcp)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
<!-- Add once published: [![PyPI: agentboxd](https://img.shields.io/pypi/v/agentboxd)](https://pypi.org/project/agentboxd/) -->

This repository holds the open-source clients for the hosted [Agentboxd](https://agentboxd.com) API:

| Package | Install | Source |
|---|---|---|
| TypeScript / Node client | `npm install agentboxd` | [`sdk/`](sdk) |
| Command line | `npx agentboxd --help` | [`sdk/src/cli/`](sdk/src/cli) |
| MCP server (Claude Desktop, Claude Code, Cursor, ...) | `npx -y @agentboxd/mcp` | [`mcp/`](mcp) |
| Python client (sync + async) | Coming soon to PyPI; install from [`sdk-python/`](sdk-python) meanwhile | [`sdk-python/`](sdk-python) |
| Example agents and guide code | | [`examples/`](examples) |
| Agent skill (Claude Code, Cursor, Codex, OpenClaw, ...) | `npx skills add agentboxd/skills` | [agentboxd/skills](https://github.com/agentboxd/skills) |

## What you get

- **Real addresses** on `homingbox.net` or your own domain, with SPF, DKIM and DMARC handled.
- **Mail as clean JSON:** `extracted_text` holds only the new text of a reply, without quoted history or
  signatures; attachments, threads and authentication results are all there.
- **Wait instead of poll:** `messages.wait()` long-polls until the next matching email arrives.
- **Verification codes and magic links** extracted from sign-up and login emails, with a confidence score.
- **Temporary inboxes** that delete themselves (and their mail) after a TTL you choose.
- **Signed webhooks** for `message.received` and friends, plus a verifier in each SDK.
- **Untrusted-input handling:** messages that fail SPF/DMARC or look like prompt injection are labelled,
  and the MCP server marks every result that contains email content.

## 60-second quickstart

Get an API key from the [dashboard](https://agentboxd.com/app/api-keys) (Free plan, no card), then:

```bash
export AGENTBOXD_API_KEY=mr_...
```

**TypeScript**

```ts
import { Agentboxd } from 'agentboxd';

const mr = new Agentboxd(); // reads AGENTBOXD_API_KEY
const inbox = await mr.inboxes.create({ client_id: 'my-agent' }); // idempotent on client_id
console.log(inbox.address);

const since = new Date().toISOString();
// ...sign up somewhere with inbox.address...
const v = await mr.messages.waitForVerification(inbox.id, { since, timeout: 60 });
console.log(v?.code ?? v?.link);
```

**Python**

```python
from agentboxd import Agentboxd

with Agentboxd() as mr:  # reads AGENTBOXD_API_KEY
    inbox = mr.inboxes.create(client_id="my-agent")
    msg = mr.messages.wait(inbox["id"], timeout=60)
    if msg:
        mr.messages.reply(inbox["id"], msg["id"], text="Got it, thanks!")
```

**MCP (Claude Code)**

The hosted connector needs no API key: you sign in and choose what the client may do.

```bash
claude mcp add --transport http agentboxd https://mcp.agentboxd.com/mcp
```

Or run the server locally with a key:

```bash
claude mcp add agentboxd -e AGENTBOXD_API_KEY=mr_... -- npx -y @agentboxd/mcp
```

Then ask: *"Create an inbox, sign up for the newsletter at example.com with it, and tell me the
confirmation link."* Config snippets for Claude Desktop, Cursor and other clients are in
[`mcp/README.md`](mcp/README.md).

## Docs

- [Quickstart](https://agentboxd.com/docs/quickstart) · [API reference](https://agentboxd.com/docs/api)
- [Verification codes](https://agentboxd.com/docs/verification-codes) · [Webhooks](https://agentboxd.com/docs/webhooks) · [Temporary inboxes](https://agentboxd.com/docs/temporary-inboxes) · [Custom domains](https://agentboxd.com/docs/custom-domains)
- [MCP server](https://agentboxd.com/docs/mcp) · [TypeScript SDK](https://agentboxd.com/docs/typescript-sdk) · [Python SDK](https://agentboxd.com/docs/python-sdk)
- Machine-readable: [llms.txt](https://agentboxd.com/llms.txt)

## Examples

- [`examples/echo-agent.ts`](examples/echo-agent.ts): registers a webhook and replies to every email
  with a short summary. Needs a public URL for the webhook (e.g. a tunnel):
  `AGENTBOXD_API_KEY=mr_... AGENTBOXD_BASE_URL=https://api.agentboxd.com ECHO_WEBHOOK_URL=https://<your-tunnel>/webhook npm run echo-agent`
- [`examples/deepseek-agent/`](examples/deepseek-agent): a tool-calling agent that signs up for things
  and triages an inbox, with the email-is-untrusted guardrails wired in.

```bash
npm install          # dev tooling for the examples (tsx, vitest)
npm run echo-agent
npm run deepseek-agent -- --demo signup
```

## Repository layout

```
sdk/          TypeScript client (npm: agentboxd), zero runtime dependencies
mcp/          MCP server (npm: @agentboxd/mcp); inlines the TypeScript client at build time
sdk-python/   Python client (PyPI: agentboxd, coming soon)
examples/     Example agents using the TypeScript client
```

The Agentboxd API server itself is not part of this repository.

## Contributing and security

Issues and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Please report security
problems privately as described in [SECURITY.md](SECURITY.md), not in public issues.

## License

[MIT](LICENSE)
