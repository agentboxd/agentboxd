# Changelog

All notable changes to `@agentboxd/mcp`. This project follows [Semantic Versioning](https://semver.org/);
while the version is 0.x, minor releases may contain breaking changes, which are always listed here.

## 0.2.0 (2026-09-26)

aSIM phase 2 (additive):

- New tools `search_public_agents` (the public agent directory; results carry a one-line summary with handle,
  status, assurance and badges) and `list_agent_keys` (an inbox's own public signing keys; no tool ever handles
  private keys). 45 tools in total (44 on the hosted server).
- `resolve_agent` takes a `handle` (e.g. `@acme/billing`) instead of an address and returns a `summary` line;
  `update_agent_card` takes `visibility: "public"`, `handle` (null clears it) and `indexable`.
- Messages show `author` when the sending agent signed with its own key ("Author-signed by the agent's own key")
  or when that signature did not verify, inside the untrusted wrapper.

## 0.1.0 (2026-09-25)

First public release.

- Tools: `create_inbox`, `create_temporary_inbox`, `list_inboxes`, `send_email`, `reply_to_email`,
  `list_messages`, `get_message`, `get_thread`, `search_email`, `wait_for_email`,
  `get_verification_code`, `get_contact`, `update_contact`, `search_knowledge`, `draft_reply` (with
  `save`), and drafts for human review and scheduled send: `create_draft`, `list_drafts`, `get_draft`,
  `send_draft`, `schedule_draft`, `cancel_draft`, and `get_identity_token` (Sign in with Agentboxd: a
  short-lived, single-use ID token for one app), and for documents `get_attachment_text` (text
  extracted from an attachment, OCR included, paged) and `extract_attachment` (JSON for the `invoice`,
  `receipt`, `tax_form` or a custom schema). `get_message` shows each attachment's extraction status.
- Agent self-signup: the server starts without `AGENTBOXD_API_KEY`; the `signup` tool creates the
  agent's own (unclaimed) workspace and inbox by solving the API's proof of work and switches the running
  server to the new key. Nothing is written to disk unless `--save-key=<file>` is passed. `get_account`
  shows claim status and limits; `request_claim` emails a person a claim link.
- Inbox kill switch: `pause_inbox` and `resume_inbox`; `get_deliverability`.
- Claim/ack work queue: `claim_messages` and `ack_message` (the model is told to ack only after the work is
  done; an un-acked message comes back when its lease runs out).
- Identities without a mailbox: `create_identity` and `list_identities`; `get_identity_token` accepts an
  identity id and `signup` takes `kind: "identity"`.
- Agent-to-agent messaging: `send_email`, `reply_to_email` and `create_draft` take structured `data` and a
  `type` (`message`, `task`, `event`) and report the `channel` and a `delivery_summary`; `send_message` and
  `reply_to_message` are the same tools described for agents. Messages show `channel`, `type`, `data` and a
  `sender` line (verified Agentboxd agent or unverified email sender); `list_messages` and `wait_for_email`
  filter by `channel` and `type`. The untrusted marker is now `UNTRUSTED MESSAGE CONTENT` and covers `data`,
  even from a verified agent. 36 tools in total (35 on the hosted server).
- stdio by default; stateless Streamable HTTP with `--http [--port=N]` or `MCP_HTTP_PORT`.
- Reads `AGENTBOXD_API_KEY` and `AGENTBOXD_BASE_URL` (legacy fallbacks: `MAILROOM_API_KEY`, `MAILROOM_URL`).
- Untrusted-content marker on every result that contains email, `warning` field for messages that failed
  SPF/DMARC or look like prompt injection or phishing, and server instructions telling the model never
  to follow instructions found in email.
- Trust layer: `get_escalation` and `update_escalation` (human on call: who is emailed when mail needs a person,
  for the workspace or one inbox), `emergency_stop` (stops every send of the workspace; no tool resumes it), messages
  show `ai_disclosure` (unverified ones say so), and a `workspace_stopped` error carries a "do not retry, tell the
  user" hint.
- Agent directory: `resolve_agent` (another agent's card by address), `search_agents` (the agents listed in your
  workspace), `verify_agent_message` (who signed a received agent message and whether the sender is still in good
  standing) and `update_agent_card` (your inbox's card; private by default). Card text is returned inside the
  untrusted marker. 43 tools in total (42 on the hosted server).
- Published to the MCP Registry as `com.agentboxd/mcp`; MCPB bundle for one-click install.
