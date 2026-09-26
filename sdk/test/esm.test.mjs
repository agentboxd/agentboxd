// Smoke test of the built ES module entry (run `npm run build` first). No dependencies: node:test.
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { test } from 'node:test';
import { Agentboxd, AgentboxdError, DEFAULT_BASE_URL, EventStream, Mailroom, MailroomError, verifyWebhook } from 'agentboxd';

function stubFetch(status, body) {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
  };
  return { calls, fetch };
}

test('exports the client under both names (Mailroom* are deprecated aliases)', () => {
  assert.equal(Agentboxd, Mailroom);
  assert.equal(AgentboxdError, MailroomError);
  assert.ok(new AgentboxdError(400, 'x', 'y') instanceof MailroomError);
  assert.equal(DEFAULT_BASE_URL, 'https://api.agentboxd.com');
});

test('sends the key as a Bearer token to the base URL', async () => {
  const { calls, fetch } = stubFetch(200, { id: 'inb_1', address: 'a@homingbox.net' });
  const mr = new Agentboxd({ apiKey: 'mr_test', baseUrl: 'http://api.test/', fetch });
  const inbox = await mr.inboxes.create({ client_id: 'x' });
  assert.equal(inbox.id, 'inb_1');
  assert.equal(calls[0].url, 'http://api.test/v1/inboxes');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer mr_test');
  assert.deepEqual(JSON.parse(calls[0].init.body), { client_id: 'x' });
});

test('API errors throw AgentboxdError with status and code', async () => {
  const { fetch } = stubFetch(404, { error: { code: 'not_found', message: 'Inbox not found' } });
  const mr = new Agentboxd({ apiKey: 'mr_test', fetch });
  await assert.rejects(mr.inboxes.get('nope'), (e) => e instanceof AgentboxdError && e.status === 404 && e.code === 'not_found');
});

test('verifyWebhook checks HMAC-SHA256 over "timestamp.body"', () => {
  const ts = String(Math.floor(Date.now() / 1000));
  const body = '{"id":"evt_1"}';
  const sig = createHmac('sha256', 'whsec_x').update(`${ts}.${body}`).digest('hex');
  assert.equal(verifyWebhook(sig, ts, body, 'whsec_x'), true);
  assert.equal(verifyWebhook(sig, ts, body + ' ', 'whsec_x'), false);
});

test('stream() mints a token and subscribes over the given WebSocket', async () => {
  const { calls, fetch } = stubFetch(201, { token: 'st_x', expires_at: '', url: 'ws://api.test/v1/stream?token=st_x' });
  const sockets = [];
  class FakeWS {
    constructor(url) {
      this.url = url;
      this.readyState = 1;
      this.sent = [];
      sockets.push(this);
      void Promise.resolve().then(() => this.onmessage({ data: JSON.stringify({ type: 'hello', heartbeat_seconds: 30 }) }));
    }
    send(d) {
      this.sent.push(JSON.parse(d));
    }
    close() {}
  }
  const s = new Agentboxd({ apiKey: 'mr_test', baseUrl: 'http://api.test', fetch }).stream({ eventTypes: ['message.received'], WebSocket: FakeWS });
  assert.ok(s instanceof EventStream);
  while (!sockets[0]?.sent.length) await new Promise((r) => setTimeout(r, 5));
  assert.equal(calls[0].url, 'http://api.test/v1/stream/token');
  assert.equal(sockets[0].url, 'ws://api.test/v1/stream?token=st_x');
  assert.deepEqual(sockets[0].sent[0], { type: 'subscribe', event_types: ['message.received'] });
  s.close();
});
