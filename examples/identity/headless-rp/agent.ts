/**
 * The agent side of a headless sign-in: mint an identity token for the app, hand it over.
 * The API key needs the `identity:sign` permission (preset "sign_in" = inboxes:read + identity:sign).
 *
 * Env: AGENTBOXD_API_KEY, INBOX_ID, AGENTBOXD_CLIENT_ID (the app's client_id), RP_URL.
 * Run (with the relying party from server.ts running): npm run agent
 */
import { Agentboxd } from 'agentboxd';

const RP_URL = process.env.RP_URL ?? 'http://localhost:4000';
const mr = new Agentboxd(); // reads AGENTBOXD_API_KEY

// Optional: ask the app for a nonce so the token is bound to this login attempt.
const { nonce, audience } = (await (await fetch(`${RP_URL}/login/nonce`)).json()) as { nonce: string; audience: string };

// A short-lived (≤ 5 min), single-use ID token addressed to this app only.
const { id_token } = await mr.identity.token({
  inboxId: process.env.INBOX_ID ?? '',
  audience: process.env.AGENTBOXD_CLIENT_ID ?? audience,
  nonce,
});

const res = await fetch(`${RP_URL}/login/verify`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ id_token, nonce }),
});
console.log(res.status, await res.json());
