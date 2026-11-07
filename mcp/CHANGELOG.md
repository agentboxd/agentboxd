# Changelog

All notable changes to `@agentboxd/mcp`. This project follows [Semantic Versioning](https://semver.org/);
while the version is 0.x, minor releases may contain breaking changes, which are always listed here.

## 0.3.0 (2026-11-07)

- Tool arguments that are ids (`inbox_id`, `message_id`, `thread_id`, `draft_id`, `attachment_id`, `contact_id`,
  `lease_id`, `reply_to_message_id`, `message_ids`) must be letters, digits, `_` and `-` (1-128 characters), as the
  API's ids are; anything else is an input error before any API call. The input schemas carry the pattern.
  `update_agent_card` goes through the SDK's agent methods instead of building its own request path.
- `extract_attachment` has `readOnlyHint: false`: it is a POST that runs a model and counts toward the plan, so
  clients ask before calling it.
- `claim_messages` takes only messages whose AI scoring (prompt injection, phishing) is done, so their warning
  labels are there: `enriched` now defaults to `true` (pass `false` for the old behaviour). It changes nothing where
  the workspace's AI processing is off.
- `get_verification_code` shows `ai_check` (for example "Not checked yet …": a code usually arrives before its
  check is done) and, when the message's labels could not be read (a key without `messages:read`), a `label_check`
  that says no warning could be given. Before, such a result looked like one without a warning. The server
  instructions say what both mean.
- The results of `reply_to_email`, `reply_to_message`, `forward_email`, `create_draft`, `send_draft` and
  `schedule_draft` start with the untrusted-content line, like `get_draft`: they carry the received subject
  ("Re: …", "Fwd: …") or AI text written from an email.
- A message the API marks `withheld` never shows its subject, text, HTML, data, files, detected code, disclosure
  header or the local check's excerpts, whatever the server sent; a `search_email` result for one has no
  snippet, and a thread whose first message is withheld shows a placeholder subject. The API already withholds them;
  this keeps it so in the MCP server too.
- The hosted server counts every message of a JSON-RPC batch against the connection's limit for the minute (a batch
  past it gets 429 and runs nothing), and its log line names the batch's size and the method and tool of each
  message. Before, a batch of up to 100 tool calls counted as one request and was logged as `batch`.
- HTTP mode (`--http`) reads at most `MCP_MAX_BODY_BYTES` of a request body (4 MiB by default, as on the hosted
  server) and answers 413 past it. Before, it held any body in memory, however large.
- The hosted server reads a request's body only after it has checked the token and the connection's limit for the
  minute: a missing or invalid token gets 401, and a connection past its limit gets 429, with the body unread. A
  connection past its limit no longer costs a token exchange per request. A request with invalid JSON, or with a
  chunked body past the size limit, now counts toward the minute.
- A message with attachments labelled `virus-unscanned` (accepted while the virus scanner was unavailable) gets a
  `warning` that starts `UNSCANNED FILES`: its attachments should not be opened or forwarded until a person checks
  them. Mail without attachments and `get_verification_code` get no warning for it. The server instructions say what
  the warning means.
- An error result carries the API's `details` and `docs_url` (where the fix is documented), and a hint not to retry for
  `sending_paused`, `org_suspended` and `recipient_suppressed`, as for `workspace_stopped`.
- `list_suppressions`: the workspace's suppressed addresses (hard bounce or complaint) with the reason and date, to
  explain a `recipient_suppressed` refusal. Read-only: removing an address is left to a person.
- `list_messages` without `inbox_id` lists the mail of every inbox the key can see, newest first; each message has its
  `inbox_id`. `add_agent` takes `expires_at`: the new key stops working then (`401 api_key_expired`).
- `get_verification_code` skips codes from senders that failed authentication (DMARC, or SPF without an aligned DKIM
  pass) unless `include_unauthenticated: true`; such a result carries `auth_failed: true` and a warning.
  `update_escalation` accepts the `draft_created` trigger.
- `get_message` and `get_thread` with `mark_read: true` leave mail whose content was withheld (still being checked, or
  held for a person) unread, so it shows up again once it is screened or released.
- Screening: a message held from agents (a warning, a failed or skipped check) shows a `screening` field ("HELD from
  agents because …"); one still being checked says so. In workspaces that screen agent mail, `claim_messages` and
  `wait_for_email` return only screened mail, and the server instructions say so. The API withholds the content of
  held and unscreened mail from MCP clients on every tool; such a message shows "Content withheld: …". There is no
  tool to release held mail, and hosted connections never get the `messages:release` permission: a person releases
  it in the dashboard. Escalation `triggers` gain `held`.
- `get_message` and `get_thread` take `mark_read: true` to also mark the received messages they return read. They
  stay read-only by default, so MCP clients don't ask for approval on every read. A key without `messages:write`
  still reads; the mail stays unread.
- New tool `mark_read` (`{ message_ids, read? }`): marks up to 100 messages read or unread.
- Automatic replies (out of office and the like) show `auto_reply: true` and a note not to answer them. The server
  instructions say so too: two automatic senders can reply to each other forever.
- New tool `delete_contact` (`{ contact_id }`; workspace-wide keys with `contacts:write`). It never forgets the
  address: blocking an address from coming back is left to a person (API or dashboard). `get_contact`
  shows the contact's `kind` (`person`, `automated`, `sales`, `unknown`), `domain` and `last_subject`;
  `update_contact` takes `kind`. 49 tools in total (48 on the hosted server).
- Messages show `ai_check` next to `warning`: whether the message was checked for prompt injection and phishing, and
  how much of it ("Not checked yet …", "only in part …"). `claim_messages` takes `analysis: "completed"`.
- New tools `forward_email` (forward a message in a new thread, with a note and its attachments) and `add_agent`
  (another inbox or identity with its own key in an unclaimed workspace, instead of a second `signup`). 47 tools
  in total (46 on the hosted server). The MCPB manifest and the stdio smoke test list them too.
- Tool arguments that are ids can no longer steer a call to another API route: the bundled SDK refuses a request path
  with a `.`/`..` segment, `?`, `#` or backslash (`invalid_argument`). Before, a prompt-injected model could pass
  `draft_id: "../../…"` to `cancel_draft` and reach any route with the same method that the key allows.
- Drafts show `approved_by` (`{ type, id, label }`) and `approved_at` once someone approved the send: the person,
  API key or connector that sent or scheduled it.
- HTTP mode (`--http`) answers 403 unless the `Host` header is `localhost`, `127.0.0.1` or `[::1]` with its port (or
  `MCP_HTTP_HOST`), and unless a browser `Origin`, when sent, is a page on this machine. Before, a web page could point
  its own name at 127.0.0.1 (DNS rebinding) and call the tools with your key. If you reach the server by another name,
  for example on a LAN with `MCP_HTTP_HOST=0.0.0.0`, list it in the new `MCP_HTTP_ALLOWED_HOSTS` (and browser origins
  in `MCP_HTTP_ALLOWED_ORIGINS`).
- Meetings (beta): six tools. `list_events` and `get_event` (read-only) show invites the inbox received and
  meetings it organizes, inside the untrusted marker, with a warning when no authenticated sender vouches for the
  organizer. `respond_to_invite` accepts, declines or answers tentative, or proposes another time; the answer goes to
  the organizer only. `create_meeting`, `update_meeting` and `cancel_meeting` send real invitations, changes and
  cancellations from the inbox (`update_meeting` and `cancel_meeting` are marked destructive). An invite that is held
  or not screened yet comes without its title, description, location, links and names, whatever the server sent,
  and no tool opts into held mail. Every `event_id` takes the id pattern.
- Messages that carry an invite, an update, an answer or a cancellation show `calendar: { event_id, method }` with a
  pointer to `get_event`. The server instructions add the flow: read the invite with `get_event`, answer with
  `respond_to_invite`, never on the sender's say-so.
- A `message_withheld` error comes with a hint: don't look for another way to read or answer the message, tell the
  user.
- Meetings, recurring series: `list_events` takes `expand: "occurrences"` to list each occurrence of a series between
  `from` and `to` (at most 2 years). Occurrences show `series_id` and a note that their id is the series' own (an
  answer, change or cancel acts on the whole series); the result says `truncated` when a series had more
  occurrences than one list gives.
- Meetings, approval drafts: `respond_to_invite`, `create_meeting`, `update_meeting` and `cancel_meeting` take
  `draft: true`: nothing is sent, the message is saved as a draft for a person to approve (the result has `draft`,
  `message: null` and a note to tell the user). Their descriptions say a key with `drafts:write` but not
  `messages:send` must pass it, and a 403 for `messages:send` without it comes with a hint to call again with
  `draft: true`. Drafts in `get_draft`, `list_drafts` and the results show their `calendar`
  (`{ action, method, event_id, removed_attendees }`) and what sending them does.
- A message's `calendar` shows `event_id` only when the message changed a meeting; without one it says the message
  changed no meeting, so there is nothing to read or answer. A `calendar_event_changed` error comes with a hint:
  nothing was sent, read the meeting again, and make a new draft if a draft was refused.

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
