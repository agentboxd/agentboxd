/**
 * Runs the webhook server against a local Agentboxd dev stack: delivers an email, posts a signed
 * `message.received` envelope event the way Agentboxd does, and checks the reply, the idempotency on a
 * retried delivery, and that a bad signature is refused.
 *
 *   AGENTBOXD_API_KEY=mr_… AGENTBOXD_BASE_URL=http://localhost:3000 npx tsx replit-email-agent/smoke.ts
 */
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import type { AddressInfo } from 'node:net';
import { Agentboxd } from 'agentboxd';
import { deliverLocally } from '../_shared/dev-inbound.js';
import { HANDLED } from './handle.js';
import { webhookServer } from './server.js';

const baseUrl = process.env.AGENTBOXD_BASE_URL ?? 'http://localhost:3000';
const mr = new Agentboxd({ baseUrl });
const secret = 'whsec_smoke_test';
const logs: string[] = [];
const server = webhookServer(mr, secret, (l) => logs.push(l)).listen(0, '127.0.0.1');
await new Promise((r) => server.once('listening', r));
const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;

async function post(body: string, signWith = secret) {
  const ts = String(Math.floor(Date.now() / 1000));
  const sig = createHmac('sha256', signWith).update(`${ts}.${body}`).digest('hex');
  return fetch(`${url}/webhook`, {
    method: 'POST',
    // Header names kept from the original API.
    headers: { 'content-type': 'application/json', 'x-mailroom-signature': sig, 'x-mailroom-timestamp': ts },
    body,
  });
}

try {
  assert.equal((await fetch(url)).status, 200); // health check

  const inbox = await mr.inboxes.create({ client_id: `replit-smoke-${Date.now()}` });
  const since = new Date(Date.now() - 5000).toISOString(); // a little slack for clock skew with the server
  await deliverLocally(baseUrl, { from: 'Dana <dana@example.com>', to: inbox.address, subject: 'Opening hours', text: 'Open on Saturday?' });
  const msg = await mr.messages.wait(inbox.id, { since, timeout: 10 });
  assert.ok(msg, 'test email did not arrive');

  const event = JSON.stringify({
    id: 'evt_smoke',
    type: 'message.received',
    created_at: new Date().toISOString(),
    data: { inbox_id: inbox.id, thread_id: msg.thread_id, message_id: msg.id, from: msg.from, to: msg.to, subject: msg.subject, labels: [], received_at: msg.received_at },
  });

  assert.equal((await post(event, 'wrong-secret')).status, 401);
  assert.equal((await post(event)).status, 204);
  assert.equal((await post(event)).status, 204); // a retried delivery
  assert.deepEqual(logs, [`${msg.id}: replied`, `${msg.id}: already-handled`]);

  const thread = await mr.threads.get(msg.thread_id);
  const replies = thread.messages.filter((m) => m.direction === 'outbound');
  assert.equal(replies.length, 1, 'exactly one reply');
  assert.match(replies[0]!.text ?? '', /Hi Dana/);
  assert.ok((await mr.messages.get(msg.id)).labels.includes(HANDLED));
  console.log('webhook: 401 on a bad signature, one reply for two deliveries, message labelled', HANDLED);
  console.log('smoke ok');
} finally {
  server.close();
}
