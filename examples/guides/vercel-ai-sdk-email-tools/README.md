# Vercel AI SDK email tools

Guide: https://agentboxd.com/guides/vercel-ai-sdk-email-tools

| File | What |
|---|---|
| `tools.ts` | `emailTools(mr, inboxId)`: six `tool({ description, inputSchema, execute })` definitions bound to one inbox, with a send budget and untrusted-content marking. `emailActions` holds the logic. |
| `agent.ts` | `generateText({ model: openai('gpt-4.1-mini'), tools, stopWhen: isStepCount(10), … })` working the inbox. |
| `smoke.ts` | Runs the tool functions against a local Agentboxd dev stack without a model. |

```bash
cd examples/guides && npm ci
export OPENAI_API_KEY=sk-... AGENTBOXD_API_KEY=mr_...
npm run vercel-ai -- "Check for new email and answer simple questions"
AGENTBOXD_BASE_URL=http://localhost:3000 npm run vercel-ai:smoke
```

Written against Node 22+, `ai` 7.0.114, `@ai-sdk/openai` 4.0.75 and `zod` 4.6.5 (checked 25 September 2026).
