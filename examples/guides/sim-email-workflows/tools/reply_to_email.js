// Sim custom tool "reply_to_email" (Code tab). Parameters: message_id, text.
// Secrets: AGENTBOXD_API_KEY, AGENTBOXD_INBOX_ID. Replies only in the agent's own inbox, in the thread.
const apiKey = {{AGENTBOXD_API_KEY}};
const inboxId = {{AGENTBOXD_INBOX_ID}};

const res = await fetch(
  `https://api.agentboxd.com/v1/inboxes/${encodeURIComponent(inboxId)}/messages/${encodeURIComponent(message_id)}/reply`,
  {
    method: 'POST',
    headers: {
      Authorization: 'Bearer ' + apiKey,
      'Content-Type': 'application/json',
      // A retried workflow run does not send the same reply twice.
      'Idempotency-Key': `sim-reply-${message_id}`,
    },
    body: JSON.stringify({ text }),
  },
);
const body = await res.json();
if (!res.ok) return { error: body.error?.code ?? res.status, message: body.error?.message ?? '' };
return { sent: true, id: body.id, thread_id: body.thread_id, to: body.to };
