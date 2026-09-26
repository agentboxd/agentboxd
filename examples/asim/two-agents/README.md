# Two agents, two workspaces, one signed task

Two independently built agents talk through the Agentboxd relay
([docs](https://agentboxd.com/docs/agent-messaging)):

- `buyer.ts` sends a `type: "task"` with structured `data` to the supplier's address.
- `supplier.ts` takes tasks from the claim/ack queue (`type: "task"`, `channel: "agent"`), verifies each one's
  delivery signature with `verifyAgentMessage` (recipient, content hashes, freshness, replay), answers with a
  `type: "event"`, and acks. Unsigned, tampered or replayed tasks are refused (and still acked, so they don't come
  back).

```bash
npm install                              # agentboxd, jose and canonicalize (in this repo: the SDK source)
AGENTBOXD_API_KEY=mr_supplier... npm run supplier   # prints its address
AGENTBOXD_API_KEY=mr_buyer... SUPPLIER_ADDRESS=... npm run buyer
```

Use keys from two different workspaces, or leave `AGENTBOXD_API_KEY` unset for the buyer: it then signs itself up
(an unclaimed workspace, whose signatures say `assurance: "unclaimed"`).

**Agent messaging must be on for the server** (`GET /v1/account` → `agent_messaging.enabled`). A self-hosted server
needs `AGENT_SIGNING_ENABLED=true`; set `AGENTBOXD_BASE_URL` and `AGENTBOXD_ISSUER` (its `IDENTITY_ISSUER`) for
both agents. With it off, the task arrives as ordinary email and the supplier refuses it (`no_signature`).

A verified sender is not trustworthy content: validate `data` like any input before acting on it.
