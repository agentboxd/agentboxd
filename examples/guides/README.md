# Guide examples

Runnable versions of the integration guides at [agentboxd.com/guides](https://agentboxd.com/guides).
Each folder has its own README and `.env.example`. No folder contains a real key.

| Folder | Guide | Language |
|---|---|---|
| [`mcp-email-server/`](mcp-email-server/) | Claude Desktop, Claude Code and Cursor via `@agentboxd/mcp` | JSON config + TypeScript smoke test |
| [`openclaw/`](openclaw/) | OpenClaw: `@agentboxd/mcp` under `mcp.servers` plus an email skill | JSON config + `SKILL.md` + TypeScript validator |
| [`langchain-email-tool/`](langchain-email-tool/) | LangChain email tools | Python |
| [`crewai-email-agent/`](crewai-email-agent/) | CrewAI support crew | Python |
| [`openai-agents-sdk-email/`](openai-agents-sdk-email/) | OpenAI Agents SDK function tools | Python |
| [`vercel-ai-sdk-email-tools/`](vercel-ai-sdk-email-tools/) | Vercel AI SDK tools | TypeScript |
| [`n8n-email-automation/`](n8n-email-automation/) | n8n webhook trigger + HTTP Request | n8n workflow JSON |
| [`playwright-email-verification/`](playwright-email-verification/) | Sign-up codes in Playwright tests | TypeScript |
| [`agent-self-signup/`](agent-self-signup/) | Let an agent sign itself up (no API key, claimed by a human later) | TypeScript + Python |
| [`livekit-voice-agent-email/`](livekit-voice-agent-email/) | LiveKit voice agent: follow-up emails and call summaries | Python |
| [`google-adk-email-agent/`](google-adk-email-agent/) | Google ADK function tools, sends confirmed by a person | Python |
| [`replit-email-agent/`](replit-email-agent/) | Replit template: webhook server or WebSocket stream worker | TypeScript |
| [`sim-email-workflows/`](sim-email-workflows/) | Sim custom tools (schema + code) for the Agent block | JSON + JavaScript + TypeScript validator |

## Before the packages are published

The guides use `npm install agentboxd` / `pip install agentboxd` / `npx @agentboxd/mcp`. Inside this
repository the examples use the local sources instead:

- TypeScript: `tsconfig.json` maps `agentboxd` to `../../sdk/src/index.ts`, and `tsx` follows it.
- Python: `pip install -e ../../sdk-python` (each `requirements.txt` says so).
- MCP: `MCP_COMMAND="npx tsx ../../mcp/src/index.ts"` (run `npm ci` in `mcp/` first).

## Checks

```bash
cd examples/guides
npm ci
npm run typecheck        # every TypeScript example
npm run n8n:check        # the n8n workflow files match their source
npm run openclaw:check   # the OpenClaw config and skill are valid
npm run sim:check        # the Sim custom tools compile the way Sim runs them
ruff check . && ruff format --check .
python -m py_compile langchain-email-tool/*.py crewai-email-agent/*.py openai-agents-sdk-email/*.py agent-self-signup/*.py   livekit-voice-agent-email/*.py google-adk-email-agent/*.py google-adk-email-agent/email_agent/*.py
```

## Running without an LLM key

Every example has a smoke script that calls its tools directly, with no model and no LLM key. The
scripts deliver their test mail through `POST /dev/inbound`, a route that only exists on an Agentboxd
server running in development mode (see
[self-hosting](https://agentboxd.com/docs/self-hosting)). The hosted API has no such route: against it,
mail arrives the normal way, when someone emails the inbox or a service you signed up to sends a code.

```bash
export AGENTBOXD_API_KEY=mr_... AGENTBOXD_BASE_URL=http://localhost:3000   # an Agentboxd dev server

cd examples/guides
npm run vercel-ai:smoke
MCP_COMMAND="npx tsx ../../mcp/src/index.ts" npm run mcp:smoke
npx playwright install chromium && npm run test:e2e
(cd langchain-email-tool && python smoke.py)      # in a venv with requirements.txt installed
(cd openai-agents-sdk-email && python smoke.py)
(cd crewai-email-agent && python smoke.py)
(cd livekit-voice-agent-email && python smoke.py)
(cd google-adk-email-agent && python smoke.py)
npm run replit:smoke
npm run sim:smoke
```
