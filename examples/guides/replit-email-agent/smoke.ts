/**
 * Runs the webhook server against a local Agentboxd dev stack: delivers an email, posts signed events the
 * way Agentboxd does, and checks that a bad signature is refused, that an event whose content is withheld
 * (not screened yet) is skipped, that the later `message.enriched` gets one reply, and that a retried
 * delivery doesn't send a second one.
 *
 *   AGENTBOXD_API_KEY=mr_… AGENTBOXD_BASE_URL=http://localhost:3000 npx tsx replit-email-agent/smoke.ts
 */
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import type { AddressInfo } from 'node:net';
import { Agentboxd, type Message } from 'agentboxd';
import { deliverLocally } from '../_shared/dev-inbound.js';
import { HANDLED } from './handle.js';
import { webhookServer } from './server.js';

const baseUrl = process.env.AGENTBOXD_BASE_URL ?? 'http://localhost:3000';
const mr = new Agentboxd({ baseUrl });
const secret = 'whsec_smoke_test';
const logs: string[] = [];

/** What the API answers an API key in a screening workspace while the message's check hasn't finished. */
const withheld = (m: Message): Message => ({
  ...m,
  subject: '[not screened yet]',
  text: null,
  html: null,
  extracted_text: null,
  headers: {},
  attachments: [],
  withheld: { state: 'pending', reason: null, attachments: 0 },
});
// A local stack screens mail as it arrives (no model), so this client stands in for one whose check is still
// running: reading the message gets the withheld form, and replying or labelling it would be a bug.
const screening = {
  messages: {
    get: async (id: string) => withheld(await mr.messages.get(id)),
    reply: () => assert.fail('replied to a withheld message'),
    update: () => assert.fail('labelled a withheld message'),
  },
} as unknown as Agentboxd;

async function listen(client: Agentboxd) {
  const server = webhookServer(client, secret, (l) => logs.push(l)).listen(0, '127.0.0.1');
  await new Promise((r) => server.once('listening', r));
  return { server, url: `http://127.0.0.1:${(server.address() as AddressInfo).port}` };
}
const live = await listen(mr);
const pending = await listen(screening);

async function post(body: string, signWith = secret, url = live.url) {
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
  assert.equal((await fetch(live.url)).status, 200); // health check

  const inbox = await mr.inboxes.create({ client_id: `replit-smoke-${Date.now()}` });
  const since = new Date(Date.now() - 5000).toISOString(); // a little slack for clock skew with the server
  await deliverLocally(baseUrl, { from: 'Dana <dana@example.com>', to: inbox.address, subject: 'Opening hours', text: 'Open on Saturday?' });
  const msg = await mr.messages.wait(inbox.id, { since, from: 'dana@example.com', timeout: 10 }); // not the welcome email
  assert.ok(msg, 'test email did not arrive');

  const envelope = (type: string) =>
    JSON.stringify({
      id: `evt_smoke_${type}`,
      type,
      created_at: new Date().toISOString(),
      data: { inbox_id: inbox.id, thread_id: msg.thread_id, message_id: msg.id, from: msg.from, to: msg.to, subject: msg.subject, labels: [], received_at: msg.received_at },
    });
  // The same event with the full payload, as message.received carries it before the check finishes.
  const fullWithheld = JSON.stringify({
    id: 'evt_smoke_full',
    type: 'message.received',
    created_at: new Date().toISOString(),
    data: { inbox, thread_id: msg.thread_id, message: { ...withheld(msg), subject: '[withheld from this event: read the message]' } },
  });

  assert.equal((await post(envelope('message.received'), 'wrong-secret')).status, 401);
  assert.equal((await post(fullWithheld)).status, 204); // withheld in the payload: skipped without a read
  assert.equal((await post(envelope('message.received'), secret, pending.url)).status, 204); // withheld on read: skipped
  assert.equal((await post(envelope('message.enriched'))).status, 204); // the check passed: handled
  assert.equal((await post(envelope('message.enriched'))).status, 204); // a retried delivery
  assert.equal((await post(envelope('message.sent'))).status, 204); // not an event the agent handles
  assert.deepEqual(logs, [`${msg.id}: withheld`, `${msg.id}: replied`, `${msg.id}: already-handled`]);

  const thread = await mr.threads.get(msg.thread_id);
  const replies = thread.messages.filter((m) => m.direction === 'outbound');
  assert.equal(replies.length, 1, 'exactly one reply');
  assert.match(replies[0]!.text ?? '', /Hi Dana/);
  assert.ok((await mr.messages.get(msg.id)).labels.includes(HANDLED));
  console.log('webhook: 401 on a bad signature, withheld events skipped, one reply for two deliveries, labelled', HANDLED);
  console.log('smoke ok');
} finally {
  live.server.close();
  pending.server.close();
}
