# Sim workflows with Agentboxd

Guide: https://agentboxd.com/guides/sim-email-workflows

| File | Where it goes in Sim |
|---|---|
| `tools/<name>.json` | **Settings → Custom Tools → Add**, Schema tab (OpenAI function format) |
| `tools/<name>.js` | The same tool's Code tab. Parameters are plain variables; `{{AGENTBOXD_API_KEY}}` and `{{AGENTBOXD_INBOX_ID}}` are workspace secrets |
| `validate.ts` | Checks the tools the way Sim runs them (schema shape, names, the code compiles as an async function body); `--smoke` runs them against a local Agentboxd dev stack |

Tools: `list_unread_emails`, `reply_to_email` (in the agent's own inbox only, with an idempotency key),
`get_verification_code`. There is deliberately no free "send to anyone" tool.

```bash
cd examples/guides && npm ci
npm run sim:check
AGENTBOXD_API_KEY=mr_... AGENTBOXD_BASE_URL=http://localhost:3000 npm run sim:smoke
```

Written against the Sim docs (docs.sim.ai: custom tools, API block, webhook and schedule triggers,
secrets, MCP) as of 2026-09-26.
