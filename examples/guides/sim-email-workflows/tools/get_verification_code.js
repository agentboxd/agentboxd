// Sim custom tool "get_verification_code" (Code tab). Parameters: since, timeout_seconds.
// Secrets: AGENTBOXD_API_KEY, AGENTBOXD_INBOX_ID. Waits (up to 60 s) for a sign-up or login email.
const apiKey = {{AGENTBOXD_API_KEY}};
const inboxId = {{AGENTBOXD_INBOX_ID}};
const q = new URLSearchParams({ timeout: String(Math.min(Math.max(Number(timeout_seconds) || 30, 1), 60)) });
if (since) q.set('since', since);

const res = await fetch(`https://api.agentboxd.com/v1/inboxes/${encodeURIComponent(inboxId)}/verification?${q}`, {
  headers: { Authorization: 'Bearer ' + apiKey },
});
const body = await res.json();
if (!res.ok) return { error: body.error?.code ?? res.status, message: body.error?.message ?? '' };
if (!body.data) return { found: false, message: 'No verification email yet. Call again to keep waiting.' };
const { code, link, confidence, from } = body.data;
return { found: true, code, link, confidence, from };
