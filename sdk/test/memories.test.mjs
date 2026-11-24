// Agent memory and recall: the SDK's memories namespace and recall() (run `npm run build` first).
// fetch is a fake that records each call. No dependencies: node:test.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Agentboxd, AgentboxdError } from 'agentboxd';

const MEMORY_ID = '5b1f0c7e-9a34-4d2b-8c61-7e0f3a9d2b44';

const memory = (over = {}) => ({
  id: MEMORY_ID,
  inbox_id: null,
  content: 'Acme Logistics prefers invoices in US dollars, net 45 days.',
  key: 'customer:acme:billing',
  tags: ['customer'],
  contact_id: 'con_1',
  thread_id: null,
  message_id: null,
  created_by: { type: 'api_key', id: 'key_1' },
  created_at: '2026-11-12T10:00:00.000Z',
  updated_at: '2026-11-12T10:00:00.000Z',
  expires_at: null,
  last_recalled_at: null,
  recall_count: 0,
  ...over,
});

/** Routes: { 'METHOD /path': body | (url, init) => [status, body] }. Unmatched → 404. A 204 has no body. */
function fakeApi(routes = {}) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const u = new URL(String(url));
    const key = `${init.method ?? 'GET'} ${u.pathname}`;
    calls.push({ key, url: u, init, body: init.body ? JSON.parse(init.body) : undefined });
    const r = routes[key];
    const [status, body] = r === undefined ? [404, { error: { code: 'not_found', message: 'Not found' } }] : typeof r === 'function' ? r(u, init) : [200, r];
    if (status === 204) return new Response(null, { status });
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
  };
  return { calls, fetch };
}

const client = (routes) => {
  const api = fakeApi(routes);
  return { mr: new Agentboxd({ apiKey: 'mr_test', baseUrl: 'http://api.test', fetch: api.fetch }), calls: api.calls };
};

test('memories.list passes the filters as query parameters', async () => {
  const { mr, calls } = client({ 'GET /v1/memories': { data: [memory()], next_cursor: 'c2' } });
  const page = await mr.memories.list({ inbox_id: 'inb_1', key: 'customer:acme:billing', tag: 'customer', contact_id: 'con_1', thread_id: 'thr_1', cursor: 'c1', limit: 5 });
  assert.equal(page.data[0].id, MEMORY_ID);
  assert.equal(page.next_cursor, 'c2');
  assert.deepEqual(Object.fromEntries(calls[0].url.searchParams), {
    inbox_id: 'inb_1',
    key: 'customer:acme:billing',
    tag: 'customer',
    contact_id: 'con_1',
    thread_id: 'thr_1',
    cursor: 'c1',
    limit: '5',
  });
  await mr.memories.list();
  assert.equal(calls[1].url.search, '');
});

test('memories.create posts the memory and returns it with similar', async () => {
  const similar = [{ id: 'mem_old', content: 'Acme pays in US dollars.', similarity: 0.951 }];
  const { mr, calls } = client({ 'POST /v1/memories': () => [201, { ...memory(), similar }] });
  const saved = await mr.memories.create({
    content: 'Acme Logistics prefers invoices in US dollars, net 45 days.',
    key: 'customer:acme:billing',
    tags: ['customer'],
    contact_id: 'con_1',
    ttl_seconds: 3600,
  });
  assert.equal(saved.id, MEMORY_ID);
  assert.deepEqual(saved.similar, similar);
  assert.equal(calls[0].url.search, '');
  assert.deepEqual(calls[0].body, {
    content: 'Acme Logistics prefers invoices in US dollars, net 45 days.',
    key: 'customer:acme:billing',
    tags: ['customer'],
    contact_id: 'con_1',
    ttl_seconds: 3600,
  });
});

test('memories.create: inbox_id null means the whole workspace; a Date expires_at becomes an ISO time', async () => {
  const { mr, calls } = client({ 'POST /v1/memories': () => [200, { ...memory(), similar: [] }] });
  await mr.memories.create({ content: 'x', inbox_id: null, expires_at: new Date('2027-01-01T00:00:00Z') });
  assert.deepEqual(calls[0].body, { content: 'x', inbox_id: null, expires_at: '2027-01-01T00:00:00.000Z' });
});

test('memories.get, update (null clears a field) and delete', async () => {
  const { mr, calls } = client({
    [`GET /v1/memories/${MEMORY_ID}`]: memory(),
    [`PATCH /v1/memories/${MEMORY_ID}`]: memory({ key: null, contact_id: null }),
    [`DELETE /v1/memories/${MEMORY_ID}`]: () => [204, null],
  });
  assert.equal((await mr.memories.get(MEMORY_ID)).key, 'customer:acme:billing');

  const patch = { content: 'Acme pays in euros now.', inbox_id: null, key: null, contact_id: null, thread_id: null, message_id: null, expires_at: null };
  const updated = await mr.memories.update(MEMORY_ID, patch);
  assert.equal(updated.key, null);
  assert.equal(calls[1].init.method, 'PATCH');
  assert.deepEqual(calls[1].body, patch);

  assert.equal(await mr.memories.delete(MEMORY_ID), undefined);
  assert.equal(calls[2].key, `DELETE /v1/memories/${MEMORY_ID}`);
  assert.equal(calls[2].body, undefined);
});

test('memories.update surfaces 409 memory_key_taken', async () => {
  const { mr } = client({ [`PATCH /v1/memories/${MEMORY_ID}`]: () => [409, { error: { code: 'memory_key_taken', message: 'taken' } }] });
  await assert.rejects(mr.memories.update(MEMORY_ID, { key: 'k' }), (e) => e instanceof AgentboxdError && e.status === 409 && e.code === 'memory_key_taken');
});

test('recall posts the question with its options and returns the answer', async () => {
  const answer = {
    mode: 'hybrid',
    sources: ['memories', 'messages'],
    data: [
      { source: 'memory', score: 1, similarity: 0.883, matched: ['meaning', 'keyword'], text: memory().content, untrusted: false, memory: memory() },
      {
        source: 'message',
        score: 0.75,
        similarity: null,
        matched: ['keyword'],
        text: 'Two of the six pallets were crushed on one side.',
        untrusted: true,
        message: { id: 'msg_1', thread_id: 'thr_1', inbox_id: 'inb_1', direction: 'inbound', from: 'dana@example.com', to: ['bot@homingbox.net'], subject: 'Pallets damaged', created_at: '2026-11-10T09:00:00.000Z' },
        attachment: { id: 'att_1', filename: 'delivery-note.pdf' },
      },
    ],
  };
  const { mr, calls } = client({ 'POST /v1/recall': answer });
  const r = await mr.recall('which currency does Acme pay in?', {
    inbox_id: 'inb_1',
    sources: ['memories', 'messages'],
    limit: 5,
    mode: 'hybrid',
    tags: ['customer'],
    contact_id: 'con_1',
    since: new Date('2026-11-01T00:00:00Z'),
    until: '2026-12-01T00:00:00Z',
    min_similarity: 0.8,
  });
  assert.equal(r.mode, 'hybrid');
  assert.equal(r.data[0].memory.id, MEMORY_ID);
  assert.equal(r.data[1].untrusted, true);
  assert.equal(r.data[1].attachment.filename, 'delivery-note.pdf');
  assert.equal(calls[0].key, 'POST /v1/recall');
  assert.equal(calls[0].url.search, '');
  assert.deepEqual(calls[0].body, {
    query: 'which currency does Acme pay in?',
    inbox_id: 'inb_1',
    sources: ['memories', 'messages'],
    limit: 5,
    mode: 'hybrid',
    tags: ['customer'],
    contact_id: 'con_1',
    since: '2026-11-01T00:00:00.000Z',
    until: '2026-12-01T00:00:00Z',
    min_similarity: 0.8,
  });

  await mr.recall('returns policy');
  assert.deepEqual(calls[1].body, { query: 'returns policy' });
});

test('recall surfaces 503 semantic_unavailable', async () => {
  const { mr } = client({ 'POST /v1/recall': () => [503, { error: { code: 'semantic_unavailable', message: 'not available' } }] });
  await assert.rejects(mr.recall('x', { mode: 'semantic' }), (e) => e instanceof AgentboxdError && e.status === 503 && e.code === 'semantic_unavailable');
});

test('memory ids are path segments: encoded, and dot segments or an empty id refused before any call', async () => {
  const { mr, calls } = client({});
  await assert.rejects(mr.memories.get('a/b'), (e) => e instanceof AgentboxdError && e.status === 404);
  assert.equal(calls[0].url.pathname, '/v1/memories/a%2Fb');
  for (const bad of ['..', '.', '']) {
    await assert.rejects(mr.memories.get(bad), (e) => e instanceof AgentboxdError && e.code === 'invalid_argument');
    await assert.rejects(mr.memories.update(bad, { content: 'x' }), (e) => e.code === 'invalid_argument');
    await assert.rejects(mr.memories.delete(bad), (e) => e.code === 'invalid_argument');
  }
  assert.equal(calls.length, 1);
});
