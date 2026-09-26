// Tests of the `agentboxd` CLI (run `npm run build` first). fetch and WebSocket are fakes; the config
// directory is a temporary folder. No dependencies: node:test.
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { parseSince, run } from '../dist/esm/cli/run.js';

const dirs = [];
after(() => dirs.forEach((d) => rmSync(d, { recursive: true, force: true })));
const tempDir = () => {
  const d = mkdtempSync(path.join(tmpdir(), 'abx-cli-'));
  dirs.push(d);
  return d;
};

/** Routes: { 'METHOD /path': body | (url, init) => [status, body] }. Unmatched → 404. */
function fakeApi(routes) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const u = new URL(String(url));
    const key = `${init.method ?? 'GET'} ${u.pathname}`;
    calls.push({ key, url: u, init, body: init.body ? JSON.parse(init.body) : undefined });
    const r = routes[key];
    const [status, body] = r === undefined ? [404, { error: { code: 'not_found', message: 'Not found' } }] : typeof r === 'function' ? r(u, init) : [200, r];
    return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
  };
  return { calls, fetch };
}

async function cli(argv, { routes = {}, env = {}, stdin, WebSocket, interrupted, now } = {}) {
  const api = fakeApi(routes);
  let stdout = '';
  let stderr = '';
  const configDir = env.AGENTBOXD_CONFIG_DIR ?? tempDir();
  const code = await run(argv, {
    stdout: { write: (s) => (stdout += s) },
    stderr: { write: (s) => (stderr += s) },
    env: { AGENTBOXD_API_KEY: 'mr_test_key', AGENTBOXD_BASE_URL: 'http://api.test', ...env, AGENTBOXD_CONFIG_DIR: configDir },
    readStdin: async () => stdin ?? '',
    stdinIsTTY: stdin === undefined,
    fetch: api.fetch,
    WebSocket,
    interrupted,
    now,
    platform: 'linux',
  });
  return { code, stdout, stderr, calls: api.calls, configDir };
}

const inbox = (over = {}) => ({
  id: 'inb_1',
  address: 'bot@agents.agentboxd.com',
  username: 'bot',
  display_name: null,
  client_id: null,
  daily_send_limit: 100,
  status: 'active',
  temporary: false,
  expires_at: null,
  created_at: '2026-09-26T10:00:00.000Z',
  ...over,
});
const message = (over = {}) => ({
  id: 'msg_1',
  inbox_id: 'inb_1',
  thread_id: 'thr_1',
  direction: 'inbound',
  status: 'received',
  from: 'Alice <alice@example.com>',
  to: ['bot@agents.agentboxd.com'],
  cc: [],
  bcc: [],
  subject: 'Hello',
  text: 'Hi!\n\n> old quote',
  html: null,
  extracted_text: 'Hi!',
  labels: [],
  is_read: false,
  received_at: '2026-09-26T10:01:00.000Z',
  sent_at: null,
  created_at: '2026-09-26T10:01:00.000Z',
  attachments: [],
  ai: { verification: null },
  ...over,
});

test('--help and --version', async () => {
  const h = await cli(['--help']);
  assert.equal(h.code, 0);
  assert.match(h.stdout, /inboxes create/);
  assert.match(h.stdout, /wait-code/);
  const v = await cli(['--version']);
  assert.equal(v.code, 0);
  assert.equal(v.stdout.trim(), JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8')).version);
  const c = await cli(['send', '--help']);
  assert.match(c.stdout, /Usage: agentboxd send <inbox> --to/);
});

test('usage errors exit 2 with a hint', async () => {
  let r = await cli(['frobnicate']);
  assert.equal(r.code, 2);
  assert.match(r.stderr, /unknown command 'frobnicate'/);
  r = await cli(['inboxes']);
  assert.equal(r.code, 2);
  assert.match(r.stderr, /needs a subcommand: list, create, pause, resume/);
  r = await cli(['inboxes', 'list', '--subject', 'x']);
  assert.equal(r.code, 2);
  assert.match(r.stderr, /--subject is not an option of `inboxes list`/);
  r = await cli(['messages', 'get']);
  assert.equal(r.code, 2);
  assert.match(r.stderr, /wrong number of arguments/);
  r = await cli(['send', 'inb_1', '--to', 'a@example.com']);
  assert.equal(r.code, 2);
  assert.match(r.stderr, /--subject is required/);
  r = await cli(['--nope']);
  assert.equal(r.code, 2);
  assert.match(r.stderr, /unknown option '--nope'/);
});

test('no key: explains login and AGENTBOXD_API_KEY', async () => {
  const r = await cli(['inboxes', 'list'], { env: { AGENTBOXD_API_KEY: '' } });
  assert.equal(r.code, 2);
  assert.match(r.stderr, /no API key: run `npx agentboxd login`, or set AGENTBOXD_API_KEY/);
  assert.equal(r.calls.length, 0);
});

test('login stores the key with 0600 permissions, whoami and logout use it', async () => {
  const account = { workspace: { id: 'org_1', name: 'Acme', plan: 'free', status: 'active', created_at: '' }, claim: { status: 'not_applicable' }, limits: {}, restrictions: null };
  const dir = tempDir();
  const env = { AGENTBOXD_API_KEY: '', AGENTBOXD_CONFIG_DIR: dir };
  const login = await cli(['login'], { env, stdin: 'mr_saved_key\n', routes: { 'GET /v1/account': account } });
  assert.equal(login.code, 0, login.stderr);
  assert.match(login.stdout, /Logged in to Acme/);
  assert.equal(login.calls[0].init.headers.Authorization, 'Bearer mr_saved_key');
  const file = path.join(dir, 'config.json');
  assert.deepEqual(JSON.parse(readFileSync(file, 'utf8')), { api_key: 'mr_saved_key', base_url: 'http://api.test' });
  if (process.platform !== 'win32') assert.equal(statSync(file).mode & 0o777, 0o600);

  const who = await cli(['whoami'], { env, routes: { 'GET /v1/account': account } });
  assert.equal(who.code, 0);
  assert.equal(who.calls[0].init.headers.Authorization, 'Bearer mr_saved_key');
  assert.match(who.stdout, /workspace: Acme/);

  // The environment wins over the saved key.
  const envWins = await cli(['whoami', '--json'], { env: { ...env, AGENTBOXD_API_KEY: 'mr_env_key' }, routes: { 'GET /v1/account': account } });
  assert.equal(envWins.calls[0].init.headers.Authorization, 'Bearer mr_env_key');
  assert.match(JSON.parse(envWins.stdout).key_source, /AGENTBOXD_API_KEY/);

  const out = await cli(['logout'], { env });
  assert.equal(out.code, 0);
  assert.throws(() => statSync(file));
});

test('login rejects a bad key (401) and does not save it', async () => {
  const dir = tempDir();
  const r = await cli(['login'], {
    env: { AGENTBOXD_API_KEY: '', AGENTBOXD_CONFIG_DIR: dir },
    stdin: 'mr_wrong',
    routes: { 'GET /v1/account': () => [401, { error: { code: 'unauthorized', message: 'invalid API key' } }] },
  });
  assert.equal(r.code, 1);
  assert.match(r.stderr, /invalid API key \(401 unauthorized\)/);
  assert.match(r.stderr, /agentboxd login/);
  assert.throws(() => statSync(path.join(dir, 'config.json')));
  const notAKey = await cli(['login'], { env: { AGENTBOXD_CONFIG_DIR: dir }, stdin: 'hello' });
  assert.equal(notAKey.code, 2);
});

test('--base-url overrides the environment', async () => {
  const r = await cli(['inboxes', 'list', '--base-url', 'http://other.test/'], { routes: { 'GET /v1/inboxes': { data: [], next_cursor: null } } });
  assert.equal(r.code, 0);
  assert.equal(r.calls[0].url.origin, 'http://other.test');
});

test('inboxes list: table, --json, pagination hint', async () => {
  const routes = { 'GET /v1/inboxes': { data: [inbox(), inbox({ id: 'inb_2', address: 'x@tmp.agentboxd.com', temporary: true, expires_at: '2026-09-26T11:00:00Z' })], next_cursor: 'c2' } };
  const r = await cli(['inboxes', 'list'], { routes });
  assert.equal(r.code, 0);
  assert.match(r.stdout, /inb_1\s+bot@agents\.agentboxd\.com\s+active/);
  assert.match(r.stdout, /temporary until 2026-09-26 11:00/);
  assert.match(r.stderr, /--cursor c2/);
  assert.equal(r.calls[0].url.searchParams.get('include_temporary'), 'true');
  const j = await cli(['inboxes', 'list', '--json', '--temporary', '--limit', '5'], { routes });
  assert.equal(JSON.parse(j.stdout).data.length, 2);
  assert.equal(j.calls[0].url.searchParams.get('temporary'), 'true');
  assert.equal(j.calls[0].url.searchParams.get('limit'), '5');
  const bad = await cli(['inboxes', 'list', '--limit', '500'], { routes });
  assert.equal(bad.code, 2);
});

test('inboxes create, temporary, pause and resume (by address)', async () => {
  const routes = {
    'POST /v1/inboxes': (_u, init) => [201, inbox({ client_id: JSON.parse(init.body).client_id ?? null })],
    'GET /v1/inboxes': { data: [inbox()], next_cursor: null },
    'POST /v1/inboxes/inb_1/pause': inbox({ status: 'paused' }),
    'POST /v1/inboxes/inb_1/resume': { ...inbox(), released_events: 2 },
  };
  const c = await cli(['inboxes', 'create', '--client-id', 'support', '--display-name', 'Support'], { routes });
  assert.equal(c.code, 0);
  assert.equal(c.stdout.trim(), 'bot@agents.agentboxd.com');
  assert.deepEqual(c.calls[0].body, { display_name: 'Support', client_id: 'support' });
  const t = await cli(['inboxes', 'create', '--temporary', '--ttl', '600'], { routes });
  assert.deepEqual(t.calls[0].body, { ttl_seconds: 600 });
  const tBad = await cli(['inboxes', 'create', '--temporary', '--username', 'x'], { routes });
  assert.equal(tBad.code, 2);
  const p = await cli(['inboxes', 'pause', 'BOT@agents.agentboxd.com', '--reason', 'loop'], { routes });
  assert.equal(p.code, 0, p.stderr);
  assert.equal(p.calls[1].key, 'POST /v1/inboxes/inb_1/pause');
  assert.deepEqual(p.calls[1].body, { reason: 'loop' });
  const r = await cli(['inboxes', 'resume', 'inb_1'], { routes });
  assert.match(r.stdout, /2 held event/);
  const missing = await cli(['inboxes', 'pause', 'nobody@example.com'], { routes });
  assert.equal(missing.code, 1);
  assert.match(missing.stderr, /no inbox with the address nobody@example.com/);
});

test('send: body from flags, file, stdin; attachments; idempotency key', async () => {
  const dir = tempDir();
  const pdf = path.join(dir, 'report.pdf');
  writeFileSync(pdf, 'PDFDATA');
  const txt = path.join(dir, 'body.txt');
  writeFileSync(txt, 'from a file');
  const routes = { 'POST /v1/inboxes/inb_1/messages/send': (_u, init) => [201, message({ id: 'msg_out', direction: 'outbound', status: 'queued', to: JSON.parse(init.body).to })] };
  const a = await cli(['send', 'inb_1', '--to', 'a@example.com', '--to', 'b@example.com', '--subject', 'Hi', '--text', 'Hello', '--attach', pdf, '--idempotency-key', 'k1'], { routes });
  assert.equal(a.code, 0, a.stderr);
  assert.match(a.stdout, /Queued msg_out to a@example.com, b@example.com/);
  assert.deepEqual(a.calls[0].body.to, ['a@example.com', 'b@example.com']);
  assert.equal(a.calls[0].body.text, 'Hello');
  assert.deepEqual(a.calls[0].body.attachments, [{ filename: 'report.pdf', content_type: 'application/pdf', content_base64: Buffer.from('PDFDATA').toString('base64') }]);
  assert.equal(a.calls[0].init.headers['Idempotency-Key'], 'k1');
  const f = await cli(['send', 'inb_1', '--to', 'a@example.com', '--subject', 'Hi', '--text-file', txt], { routes });
  assert.equal(f.calls[0].body.text, 'from a file');
  const s = await cli(['send', 'inb_1', '--to', 'a@example.com', '--subject', 'Hi'], { routes, stdin: 'piped body' });
  assert.equal(s.calls[0].body.text, 'piped body');
  const none = await cli(['send', 'inb_1', '--to', 'a@example.com', '--subject', 'Hi'], { routes });
  assert.equal(none.code, 2);
  assert.match(none.stderr, /no message body/);
  const missingFile = await cli(['send', 'inb_1', '--to', 'a@example.com', '--subject', 'Hi', '--text', 'x', '--attach', path.join(dir, 'nope.pdf')], { routes });
  assert.equal(missingFile.code, 2);
});

test('API errors: message, code and a hint; --json prints the error object', async () => {
  const routes = { 'POST /v1/inboxes/inb_1/messages/send': () => [423, { error: { code: 'inbox_paused', message: 'inbox is paused' } }] };
  const r = await cli(['send', 'inb_1', '--to', 'a@example.com', '--subject', 'Hi', '--text', 'x'], { routes });
  assert.equal(r.code, 1);
  assert.match(r.stderr, /inbox is paused \(423 inbox_paused\)/);
  assert.match(r.stderr, /agentboxd inboxes resume/);
  const j = await cli(['send', 'inb_1', '--to', 'a@example.com', '--subject', 'Hi', '--text', 'x', '--json'], { routes });
  assert.deepEqual(JSON.parse(j.stdout).error, { status: 423, code: 'inbox_paused', message: 'inbox is paused', details: null });
  const forbidden = await cli(['inboxes', 'list'], { routes: { 'GET /v1/inboxes': () => [403, { error: { code: 'forbidden', message: 'missing permission inboxes:read' } }] } });
  assert.match(forbidden.stderr, /lacks a permission/);
  const limited = await cli(['inboxes', 'list'], { routes: { 'GET /v1/inboxes': () => [429, { error: { code: 'rate_limited', message: 'slow down', details: { retry_after_seconds: 7 } } }] } });
  assert.match(limited.stderr, /retry in 7s/);
});

test('network failure names the base URL', async () => {
  let stderr = '';
  const code = await run(['inboxes', 'list'], {
    stdout: { write: () => {} },
    stderr: { write: (s) => (stderr += s) },
    env: { AGENTBOXD_API_KEY: 'mr_x', AGENTBOXD_BASE_URL: 'http://down.test', AGENTBOXD_CONFIG_DIR: tempDir() },
    readStdin: async () => '',
    stdinIsTTY: true,
    fetch: async () => {
      throw new TypeError('fetch failed', { cause: new Error('connect ECONNREFUSED') });
    },
  });
  assert.equal(code, 1);
  assert.match(stderr, /Can't reach http:\/\/down\.test/);
});

test('messages list and get (untrusted banner, warnings, codes)', async () => {
  const routes = {
    'GET /v1/inboxes/inb_1/messages': { data: [message(), message({ id: 'msg_2', direction: 'outbound', status: 'sent', to: ['alice@example.com'], is_read: true, subject: 'Re: Hello' })], next_cursor: null },
    'GET /v1/messages/msg_1': message({ labels: ['dmarc-fail'], ai: { verification: { code: '482913', link: null, confidence: 0.7, jev_probability: null } } }),
  };
  const l = await cli(['messages', 'list', 'inb_1', '--unread'], { routes });
  assert.equal(l.code, 0);
  assert.equal(l.calls[0].url.searchParams.get('is_read'), 'false');
  assert.match(l.stdout, /msg_1 .*Alice <alice@example\.com>\s+\* Hello/);
  assert.match(l.stdout, /msg_2 .*→ alice@example\.com\s+Re: Hello/);
  const g = await cli(['messages', 'get', 'msg_1'], { routes });
  assert.match(g.stdout, /UNTRUSTED EMAIL CONTENT/);
  assert.match(g.stdout, /warning: {2}dmarc-fail/);
  assert.match(g.stdout, /code: {5}482913/);
  assert.match(g.stdout, /\nHi!\n?$/);
  assert.doesNotMatch(g.stdout, /old quote/);
  const j = await cli(['messages', 'get', 'msg_1', '--json'], { routes });
  assert.equal(JSON.parse(j.stdout).text, 'Hi!\n\n> old quote');
  const badDir = await cli(['messages', 'list', 'inb_1', '--direction', 'sideways'], { routes });
  assert.equal(badDir.code, 2);
});

test('parseSince: ISO times and durations', () => {
  const now = Date.parse('2026-09-26T12:00:00Z');
  assert.equal(parseSince('10m', now), '2026-09-26T11:50:00.000Z');
  assert.equal(parseSince('2h', now), '2026-09-26T10:00:00.000Z');
  assert.equal(parseSince('2026-09-26T09:00:00+02:00', now), '2026-09-26T07:00:00.000Z');
  assert.throws(() => parseSince('yesterday', now), /--since/);
});

test('wait-code: loops 60-second long-polls until the code, prints it alone on stdout', async () => {
  let t = Date.parse('2026-09-26T12:00:00Z');
  let n = 0;
  const routes = {
    'GET /v1/inboxes/inb_1/verification': (u) => {
      n++;
      t += Number(u.searchParams.get('timeout')) * 1000; // the server held the request that long
      return n < 3 ? [200, { data: null }] : [200, { data: { code: '482913', link: 'https://acme.test/v?t=1', confidence: 0.95, jev_probability: 0.99, message_id: 'msg_1', from: 'no-reply@acme.test', subject: 'Your code', received_at: '' } }];
    },
  };
  const r = await cli(['wait-code', 'inb_1', '--since', '5m', '--timeout', '150', '--from', 'acme'], { routes, now: () => t });
  assert.equal(r.code, 0, r.stderr);
  assert.equal(r.stdout, '482913\n');
  assert.match(r.stderr, /link: https:\/\/acme\.test/);
  assert.deepEqual(
    r.calls.map((c) => c.url.searchParams.get('timeout')),
    ['60', '60', '30'],
  );
  assert.equal(r.calls[0].url.searchParams.get('since'), '2026-09-26T11:55:00.000Z');
  assert.equal(r.calls[0].url.searchParams.get('from'), 'acme');
});

test('wait-code: exit 3 on timeout', async () => {
  let t = 0;
  const routes = {
    'GET /v1/inboxes/inb_1/verification': (u) => {
      t += Number(u.searchParams.get('timeout')) * 1000;
      return [200, { data: null }];
    },
  };
  const r = await cli(['wait-code', 'inb_1', '--timeout', '5', '--json'], { routes, now: () => t });
  assert.equal(r.code, 3);
  assert.equal(JSON.parse(r.stdout).error.code, 'timeout');
  assert.match(r.stderr, /no verification email arrived within 5s/);
});

test('drafts list (all inboxes or one) and drafts send', async () => {
  const draft = { id: 'drf_1', inbox_id: 'inb_1', status: 'draft', to: ['a@example.com'], subject: 'Offer', send_at: null };
  const routes = {
    'GET /v1/drafts': { data: [draft], next_cursor: null },
    'GET /v1/inboxes/inb_1/drafts': { data: [draft], next_cursor: null },
    'POST /v1/inboxes/inb_1/drafts/drf_1/send': { draft: { ...draft, status: 'sent' }, message: message({ id: 'msg_s', direction: 'outbound', to: ['a@example.com'] }) },
  };
  const all = await cli(['drafts', 'list', '--status', 'draft,scheduled'], { routes });
  assert.equal(all.code, 0);
  assert.equal(all.calls[0].key, 'GET /v1/drafts');
  assert.equal(all.calls[0].url.searchParams.get('status'), 'draft,scheduled');
  assert.match(all.stdout, /drf_1\s+inb_1\s+draft\s+a@example\.com\s+Offer/);
  const one = await cli(['drafts', 'list', 'inb_1'], { routes });
  assert.equal(one.calls[0].key, 'GET /v1/inboxes/inb_1/drafts');
  const s = await cli(['drafts', 'send', 'inb_1', 'drf_1'], { routes });
  assert.equal(s.code, 0);
  assert.match(s.stdout, /Sent draft drf_1 as msg_s/);
});

class FakeWS {
  static sockets = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    this.onopen = this.onmessage = this.onclose = this.onerror = null;
    FakeWS.sockets.push(this);
    setTimeout(() => {
      this.readyState = 1;
      this.onopen?.({});
      this.onmessage?.({ data: JSON.stringify({ type: 'hello', heartbeat_seconds: 30 }) });
    }, 0);
  }
  send(data) {
    this.sent.push(JSON.parse(data));
    const msg = JSON.parse(data);
    if (msg.type !== 'subscribe') return;
    setTimeout(() => {
      this.onmessage?.({ data: JSON.stringify({ type: 'subscribed', replayed: 0 }) });
      for (const id of ['evt_1', 'evt_2'])
        this.onmessage?.({
          data: JSON.stringify({
            type: 'event',
            event: { id, type: 'message.received', created_at: '2026-09-26T12:00:00Z', data: { message: message({ id: `msg_${id}` }) } },
          }),
        });
    }, 0);
  }
  close(code = 1000, reason = '') {
    this.readyState = 3;
    setTimeout(() => this.onclose?.({ code, reason }), 0);
  }
}

test('tail: subscribes with filters and prints events until interrupted', async () => {
  FakeWS.sockets = [];
  let stop;
  const interrupted = new Promise((r) => (stop = r));
  const routes = {
    'POST /v1/stream/token': [201, { token: 'st_1', expires_at: '', url: 'ws://api.test/v1/stream?token=st_1' }],
    'GET /v1/inboxes': { data: [inbox()], next_cursor: null },
  };
  routes['POST /v1/stream/token'] = () => [201, { token: 'st_1', expires_at: '', url: 'ws://api.test/v1/stream?token=st_1' }];
  setTimeout(() => stop(), 50);
  const r = await cli(['tail', '--inbox', 'bot@agents.agentboxd.com', '--event', 'message.received', '--envelope', '--json'], { routes, WebSocket: FakeWS, interrupted });
  assert.equal(r.code, 0, r.stderr);
  assert.equal(FakeWS.sockets[0].url, 'ws://api.test/v1/stream?token=st_1');
  assert.deepEqual(FakeWS.sockets[0].sent[0], { type: 'subscribe', inbox_ids: ['inb_1'], event_types: ['message.received'], payload: 'envelope' });
  const lines = r.stdout.trim().split('\n').map((l) => JSON.parse(l));
  assert.deepEqual(lines.map((e) => e.id), ['evt_1', 'evt_2']);

  FakeWS.sockets = [];
  let stop2;
  const int2 = new Promise((r2) => (stop2 = r2));
  setTimeout(() => stop2(), 50);
  const h = await cli(['tail'], { routes, WebSocket: FakeWS, interrupted: int2 });
  assert.match(h.stdout, /message\.received\s+Alice <alice@example\.com>\s+Hello\s+msg_evt_1/);
  assert.match(h.stderr, /listening/);
});

test('tail: a revoked key ends with exit 1 and a hint', async () => {
  class RejectingWS extends FakeWS {
    send(data) {
      this.sent.push(JSON.parse(data));
      setTimeout(() => this.onclose?.({ code: 4001, reason: 'credential revoked' }), 0);
    }
  }
  const routes = { 'POST /v1/stream/token': () => [201, { token: 'st_1', expires_at: '', url: 'ws://api.test/v1/stream?token=st_1' }] };
  const r = await cli(['tail'], { routes, WebSocket: RejectingWS });
  assert.equal(r.code, 1);
  assert.match(r.stderr, /stream closed \(4001\)/);
  assert.match(r.stderr, /agentboxd login/);
});

test('the bin runs as a real process (node dist/esm/cli/main.js)', () => {
  const bin = fileURLToPath(new URL('../dist/esm/cli/main.js', import.meta.url));
  assert.match(readFileSync(bin, 'utf8'), /^#!\/usr\/bin\/env node\n/);
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  assert.equal(pkg.bin.agentboxd, 'dist/esm/cli/main.js');
  assert.equal(execFileSync(process.execPath, [bin, '--version'], { encoding: 'utf8' }).trim(), pkg.version);
  const env = { ...process.env, AGENTBOXD_API_KEY: '', MAILROOM_API_KEY: '', AGENTBOXD_CONFIG_DIR: tempDir() };
  const r = spawnSync(process.execPath, [bin, 'inboxes', 'list'], { encoding: 'utf8', env, input: '' });
  assert.equal(r.status, 2);
  assert.match(r.stderr, /no API key/);
});
