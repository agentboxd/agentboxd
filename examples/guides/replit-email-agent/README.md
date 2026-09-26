# Email agent on Replit

Guide: https://agentboxd.com/guides/replit-email-agent

A Replit template: an agent with its own Agentboxd inbox that answers new email, in one of two modes.

| File | What it is |
|---|---|
| `handle.ts` | What the agent does with a new email (re-read it from the API, skip risky and automatic mail, reply once, label it). Put your model call in `answer()`. |
| `server.ts` | Webhook mode: `POST /webhook` verifies the signature and handles the email; `GET /` is the health check. Autoscale or Reserved VM. |
| `worker.ts` | Stream mode: holds a WebSocket (`mr.stream()`) and handles each email. No public URL; needs a Reserved VM. |
| `setup.ts` | One-time: creates the inbox and registers the webhook for your `.replit.app` URL, prints the secret |
| `.replit`, `package.json` | Replit run and deployment config (Node 20, port 3000 → 80) |
| `smoke.ts` | Checks the webhook server against a local Agentboxd dev stack (signature, reply, retry) |

On Replit: import this folder, add the `AGENTBOXD_API_KEY` secret, then either

- **webhook mode**: publish (Autoscale is fine), run `npm run setup -- https://<your-app>.replit.app` in the
  Shell, add the printed secret as `AGENTBOXD_WEBHOOK_SECRET`, republish; or
- **stream mode**: publish as a Reserved VM background worker with the run command `npm run worker`.

In this repository `agentboxd` resolves to the SDK source (see `../tsconfig.json`), so the template's
own `package.json` isn't installed here. Check it with:

```bash
cd examples/guides && npm ci
AGENTBOXD_API_KEY=mr_... AGENTBOXD_BASE_URL=http://localhost:3000 npx tsx replit-email-agent/smoke.ts
```

Written against the Replit docs (Secrets, deployment types, `.replit` configuration) as of 2026-09-26.
