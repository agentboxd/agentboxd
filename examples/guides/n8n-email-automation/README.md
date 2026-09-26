# n8n: receive and send agent email

Guide: https://agentboxd.com/guides/n8n-email-automation

| File | What |
|---|---|
| `inbound-reply.workflow.json` | Webhook trigger (raw body) → Code node that verifies the `X-Mailroom-Signature` HMAC and skips spoofed or automatic mail → HTTP Request that replies in the thread. |
| `send-and-wait.workflow.json` | Manual trigger → get-or-create an inbox (`client_id`) → send an email → long-poll `/messages/wait` for the answer. |
| `verify-and-filter.js` | The Code node's source, readable on its own. |
| `workflows.ts` | Builds both workflow files from that source (`--check` verifies them). |

## Set up

1. In n8n, create a credential **Header Auth** named `Agentboxd API key`: Name `Authorization`,
   Value `Bearer mr_...`. Imported workflows refer to it by that name; pick it again in each HTTP
   Request node if n8n asks.
2. Import both files (**Workflows → Import from File**).
3. Allow the Code node to use `crypto`: `NODE_FUNCTION_ALLOW_BUILTIN=crypto` on the n8n instance
   (with external task runners, set it in the runner's `env-overrides` instead).
4. Publish `Agentboxd: acknowledge inbound email` and register its production URL with Agentboxd:

```bash
curl -s https://api.agentboxd.com/v1/webhooks \
  -H "Authorization: Bearer $AGENTBOXD_API_KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://n8n.example.com/webhook/agentboxd-inbound","events":["message.received"]}'
```

5. Paste the `secret` from that response into `SECRET` in the Code node.

Self-hosted Agentboxd: rebuild the files with your API base,
`API_BASE=https://mail-api.example.com npx tsx n8n-email-automation/workflows.ts`.

Checked against n8n 2.40.7 (Webhook node v2, Code node v2, HTTP Request node v4.2) on
25 September 2026, end to end against a local Agentboxd stack.
