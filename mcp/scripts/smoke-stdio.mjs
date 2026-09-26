#!/usr/bin/env node
/**
 * Smoke test for a built or installed @agentboxd/mcp binary, with no dependencies.
 *
 * It starts a tiny fake Agentboxd API on 127.0.0.1, launches the server command with
 * AGENTBOXD_API_KEY / AGENTBOXD_BASE_URL pointing at it, and speaks raw newline-delimited JSON-RPC
 * over stdio: initialize → notifications/initialized → tools/list → tools/call list_inboxes.
 * It fails unless every expected tool is listed and the tool call reached the fake API with the key.
 *
 *   node scripts/smoke-stdio.mjs                                  # runs node dist/index.js
 *   node scripts/smoke-stdio.mjs "npx --no-install agentboxd-mcp" # any command (run through a shell)
 */
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const EXPECTED_TOOLS = [
  'create_inbox',
  'create_temporary_inbox',
  'list_inboxes',
  'send_email',
  'send_message',
  'reply_to_email',
  'reply_to_message',
  'list_messages',
  'get_message',
  'get_thread',
  'search_email',
  'wait_for_email',
  'get_verification_code',
  'get_contact',
  'update_contact',
  'search_knowledge',
  'draft_reply',
  'create_draft',
  'list_drafts',
  'get_draft',
  'send_draft',
  'schedule_draft',
  'cancel_draft',
  'get_identity_token',
  'create_identity',
  'list_identities',
  'signup',
  'get_account',
  'request_claim',
  'get_attachment_text',
  'extract_attachment',
  'pause_inbox',
  'resume_inbox',
  'get_deliverability',
  'claim_messages',
  'ack_message',
  'get_escalation',
  'update_escalation',
  'emergency_stop',
  'resolve_agent',
  'search_agents',
  'verify_agent_message',
  'update_agent_card',
  'search_public_agents',
  'list_agent_keys',
];

const API_KEY = 'mr_smoke_test_key';
const TIMEOUT_MS = 30_000;

function startFakeApi() {
  const seen = [];
  const server = createServer((req, res) => {
    seen.push({ method: req.method, url: req.url, auth: req.headers.authorization });
    res.setHeader('Content-Type', 'application/json');
    if (req.headers.authorization !== `Bearer ${API_KEY}`) {
      res.writeHead(401).end(JSON.stringify({ error: { code: 'unauthorized', message: 'bad key' } }));
      return;
    }
    if (req.method === 'GET' && req.url?.startsWith('/v1/inboxes')) {
      const inbox = {
        id: 'inb_smoke',
        address: 'smoke@agents.example.test',
        username: 'smoke',
        display_name: null,
        client_id: null,
        daily_send_limit: 100,
        created_at: new Date(0).toISOString(),
      };
      res.end(JSON.stringify({ data: [inbox], next_cursor: null }));
      return;
    }
    res.writeHead(404).end(JSON.stringify({ error: { code: 'not_found', message: 'not in the smoke fake' } }));
  });
  return new Promise((resolve) =>
    server.listen(0, '127.0.0.1', () => resolve({ server, seen, url: `http://127.0.0.1:${server.address().port}` })),
  );
}

export async function smoke(command) {
  const api = await startFakeApi();
  const env = { ...process.env, AGENTBOXD_API_KEY: API_KEY, AGENTBOXD_BASE_URL: api.url };
  delete env.MAILROOM_API_KEY;
  delete env.MAILROOM_URL;
  delete env.MCP_HTTP_PORT;
  const child = command
    ? spawn(command, { shell: true, env, stdio: ['pipe', 'pipe', 'pipe'] })
    : spawn(process.execPath, [path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../dist/index.js')], {
        env,
        stdio: ['pipe', 'pipe', 'pipe'],
      });

  let stderr = '';
  child.stderr.on('data', (d) => (stderr += d));
  const pending = new Map();
  let buf = '';
  child.stdout.on('data', (d) => {
    buf += d;
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line) continue;
      const msg = JSON.parse(line);
      if (msg.id !== undefined && pending.has(msg.id)) {
        pending.get(msg.id)(msg);
        pending.delete(msg.id);
      }
    }
  });
  let nextId = 1;
  const request = (method, params) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      const timer = setTimeout(() => reject(new Error(`timeout waiting for ${method}\nstderr:\n${stderr}`)), TIMEOUT_MS);
      pending.set(id, (msg) => {
        clearTimeout(timer);
        if (msg.error) reject(new Error(`${method} failed: ${JSON.stringify(msg.error)}`));
        else resolve(msg.result);
      });
      child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
    });
  const exited = new Promise((resolve) => child.on('exit', (code) => resolve(code)));

  try {
    const init = await request('initialize', {
      protocolVersion: '2025-06-18',
      capabilities: {},
      clientInfo: { name: 'agentboxd-smoke', version: '0.0.0' },
    });
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
    if (init.serverInfo?.name !== 'agentboxd') throw new Error(`unexpected serverInfo: ${JSON.stringify(init.serverInfo)}`);

    const { tools } = await request('tools/list', {});
    const names = tools.map((t) => t.name).sort();
    const missing = EXPECTED_TOOLS.filter((t) => !names.includes(t));
    const extra = names.filter((t) => !EXPECTED_TOOLS.includes(t));
    if (missing.length || extra.length) throw new Error(`tool mismatch: missing ${missing}, unexpected ${extra}`);

    const result = await request('tools/call', { name: 'list_inboxes', arguments: {} });
    const text = result.content?.[0]?.text ?? '';
    if (result.isError || !text.includes('smoke@agents.example.test')) throw new Error(`list_inboxes failed: ${text}`);
    if (!api.seen.some((r) => r.url?.startsWith('/v1/inboxes') && r.auth === `Bearer ${API_KEY}`)) {
      throw new Error('the fake API never received an authenticated request');
    }
    return { server: init.serverInfo, protocolVersion: init.protocolVersion, tools: names };
  } finally {
    child.stdin.end();
    child.kill();
    await Promise.race([exited, new Promise((r) => setTimeout(r, 2_000))]);
    api.server.close();
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  smoke(process.argv[2])
    .then((r) => {
      console.log(
        `smoke ok: ${r.server.name} ${r.server.version} (protocol ${r.protocolVersion}), ${r.tools.length} tools: ${r.tools.join(', ')}`,
      );
    })
    .catch((err) => {
      console.error(`smoke FAILED: ${err.message}`);
      process.exit(1);
    });
}
