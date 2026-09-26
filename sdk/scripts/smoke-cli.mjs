#!/usr/bin/env node
/**
 * End-to-end check of the built `agentboxd` bin against a real Agentboxd server in development mode
 * (it delivers test mail through POST /dev/inbound, which the hosted API does not have). Run
 * `npm run build` first.
 *
 *   AGENTBOXD_API_KEY=mr_... AGENTBOXD_BASE_URL=http://localhost:3000 node scripts/smoke-cli.mjs
 *   node scripts/smoke-cli.mjs "npx -y --package=./agentboxd-0.2.0.tgz agentboxd"   # a packed tarball
 *
 * Covers: login (stdin) into a temporary config dir, whoami, inboxes create/list/pause/resume,
 * send (refused while paused), wait-code, messages list/get, tail (sees a live message.received),
 * drafts list, logout. Exits non-zero on the first failure. (Arguments avoid spaces: with an npx
 * command on Windows the child runs through a shell.)
 */
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const key = process.env.AGENTBOXD_API_KEY;
const base = process.env.AGENTBOXD_BASE_URL;
if (!key || !base) {
  console.error('set AGENTBOXD_API_KEY and AGENTBOXD_BASE_URL (an Agentboxd dev server)');
  process.exit(2);
}
const binCmd = process.argv[2]?.split(' ') ?? [process.execPath, fileURLToPath(new URL('../dist/esm/cli/main.js', import.meta.url))];
const configDir = mkdtempSync(path.join(tmpdir(), 'abx-smoke-'));
// The saved key is used, not the environment: this exercises `login`.
const env = { ...process.env, AGENTBOXD_API_KEY: '', MAILROOM_API_KEY: '' /* legacy env var, still read */, AGENTBOXD_BASE_URL: '', AGENTBOXD_CONFIG_DIR: configDir };

function cli(args, input) {
  const r = spawnSync(binCmd[0], [...binCmd.slice(1), ...args], { env, input: input ?? '', encoding: 'utf8', shell: process.platform === 'win32' && binCmd[0] === 'npx' });
  return { code: r.status, out: r.stdout, err: r.stderr };
}
function ok(args, input) {
  const r = cli(args, input);
  assert.equal(r.code, 0, `agentboxd ${args.join(' ')} exited ${r.code}\n${r.err}${r.out}`);
  return r;
}
const json = (args) => JSON.parse(ok([...args, '--json']).out);
const step = (s) => console.log(`✓ ${s}`);

async function deliver(to, subject, text) {
  const id = `<${Date.now()}.${Math.random().toString(36).slice(2)}@example.test>`;
  const raw = [`From: Acme <no-reply@acme.example>`, `To: ${to}`, `Subject: ${subject}`, `Message-ID: ${id}`, `Date: ${new Date().toUTCString()}`, 'MIME-Version: 1.0', 'Content-Type: text/plain; charset=utf-8', '', text, ''].join('\r\n');
  const res = await fetch(`${base.replace(/\/+$/, '')}/dev/inbound`, { method: 'POST', headers: { 'Content-Type': 'message/rfc822' }, body: raw });
  assert.ok(res.ok, `/dev/inbound answered ${res.status}`);
}

try {
  ok(['--version']);
  ok(['login', '--base-url', base], key + '\n');
  step('login saved the key');
  assert.match(ok(['whoami']).out, /workspace:/);
  step('whoami');

  const inbox = json(['inboxes', 'create', '--client-id', `cli-smoke-${Date.now()}`]);
  assert.match(inbox.address, /@/);
  assert.ok(json(['inboxes', 'list']).data.some((i) => i.id === inbox.id));
  step(`inboxes create/list: ${inbox.address}`);

  json(['inboxes', 'pause', inbox.address, '--reason', 'smoke-test']);
  const refused = cli(['send', inbox.id, '--to', 'someone@example.com', '--subject', 'x', '--text', 'x']);
  assert.equal(refused.code, 1);
  assert.match(refused.err, /inbox_paused/);
  json(['inboxes', 'resume', inbox.id]);
  step('pause refuses sends, resume');

  const sent = json(['send', inbox.id, '--to', 'someone@example.com', '--subject', 'Hello-from-the-CLI', '--text', 'Hi']);
  assert.equal(sent.direction, 'outbound');
  step(`send: ${sent.id} (${sent.status})`);

  // tail in the background, then deliver a code email; wait-code and tail both have to see it.
  const tail = spawn(binCmd[0], [...binCmd.slice(1), 'tail', '--inbox', inbox.id, '--event', 'message.received', '--json'], { env, shell: process.platform === 'win32' && binCmd[0] === 'npx' });
  let tailOut = '';
  tail.stdout.on('data', (d) => (tailOut += d));
  await new Promise((r) => setTimeout(r, 2500));
  const since = new Date(Date.now() - 1000).toISOString();
  await deliver(inbox.address, 'Your Acme code', 'Your verification code is 482913. It expires in 10 minutes.');
  const code = ok(['wait-code', inbox.id, '--since', since, '--timeout', '30']);
  assert.equal(code.out.trim(), '482913');
  step('wait-code printed 482913');

  const deadline = Date.now() + 15_000;
  while (!tailOut.includes('message.received') && Date.now() < deadline) await new Promise((r) => setTimeout(r, 200));
  // Through a shell (npx on Windows) the signal reaches the shell, not the CLI: kill the whole tree.
  if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(tail.pid), '/t', '/f']);
  else tail.kill('SIGINT');
  tail.stdout.destroy();
  const events = tailOut.trim().split('\n').filter(Boolean).map((l) => JSON.parse(l));
  assert.ok(events.some((e) => e.type === 'message.received'), `tail saw no message.received: ${tailOut}`);
  step('tail streamed message.received');

  const list = json(['messages', 'list', inbox.id]);
  const inbound = list.data.find((m) => m.direction === 'inbound');
  assert.ok(inbound);
  assert.match(ok(['messages', 'get', inbound.id]).out, /UNTRUSTED EMAIL CONTENT[\s\S]*482913/);
  step('messages list/get');

  assert.ok(Array.isArray(json(['drafts', 'list', inbox.id]).data));
  step('drafts list');

  json(['inboxes', 'pause', inbox.id, '--reason', 'smoke-test-done']);
  ok(['logout']);
  assert.equal(cli(['inboxes', 'list']).code, 2);
  step('logout');
  console.log('cli smoke ok');
} finally {
  rmSync(configDir, { recursive: true, force: true });
}
process.exit(0);
