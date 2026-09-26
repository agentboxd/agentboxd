/**
 * Talks to the Agentboxd MCP server the way Claude Desktop, Claude Code or Cursor would (stdio), without
 * a model: lists the tools, creates a temporary inbox and reads a verification code from it.
 *
 *   AGENTBOXD_API_KEY=mr_… npx tsx mcp-email-server/smoke.ts
 *
 * Against a local Agentboxd dev stack (AGENTBOXD_BASE_URL=http://localhost:3000) the script also delivers a
 * test email through /dev/inbound, so the whole loop runs without sending real mail.
 */
import assert from 'node:assert/strict';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { getDefaultEnvironment, StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { deliverLocally } from '../_shared/dev-inbound.js';

const apiKey = process.env.AGENTBOXD_API_KEY;
if (!apiKey) throw new Error('Set AGENTBOXD_API_KEY');
const baseUrl = process.env.AGENTBOXD_BASE_URL || 'https://api.agentboxd.com';
const [command, ...args] = (process.env.MCP_COMMAND || 'npx -y @agentboxd/mcp').split(' ');

const transport = new StdioClientTransport({
  command: command!,
  args,
  env: { ...getDefaultEnvironment(), AGENTBOXD_API_KEY: apiKey, AGENTBOXD_BASE_URL: baseUrl },
});
const client = new Client({ name: 'agentboxd-guide-smoke', version: '1.0.0' });
await client.connect(transport);

/** The text of a tool result (the server returns one text part). */
async function call(name: string, input: Record<string, unknown>): Promise<string> {
  const res = await client.callTool({ name, arguments: input });
  const parts = (res.content ?? []) as { type: string; text?: string }[];
  const text = parts.map((p) => p.text ?? '').join('\n');
  if (res.isError) throw new Error(`${name} failed: ${text}`);
  return text;
}

const { tools } = await client.listTools();
console.log(`${tools.length} tools:`, tools.map((t) => t.name).join(', '));
for (const t of ['create_inbox', 'create_temporary_inbox', 'send_email', 'reply_to_email', 'wait_for_email', 'get_verification_code']) {
  assert.ok(tools.some((x) => x.name === t), `missing tool ${t}`);
}

const created = JSON.parse(await call('create_temporary_inbox', { ttl_seconds: 600 })) as { id: string; address: string; expires_at: string };
console.log('create_temporary_inbox →', created.address, 'expires', created.expires_at);

const local = /^http:\/\/(localhost|127\.0\.0\.1)/.test(baseUrl);
if (local) {
  const since = new Date().toISOString();
  await deliverLocally(baseUrl, {
    from: 'Acme Cloud <no-reply@acme-cloud.example>',
    to: created.address,
    subject: 'Confirm your email',
    text: 'Welcome to Acme Cloud.\n\nYour verification code is 731904.\n\nIf you did not sign up, ignore this email.',
  });
  const result = await call('get_verification_code', { inbox_id: created.id, since, timeout_seconds: 15 });
  console.log('get_verification_code →', result.split('\n').join(' | '));
  // UNTRUSTED MESSAGE CONTENT since agent messaging; UNTRUSTED EMAIL CONTENT in earlier releases.
  assert.match(result, /^UNTRUSTED (MESSAGE|EMAIL) CONTENT/, 'results with email content are marked untrusted');
  assert.match(result, /"code": ?"731904"/);
} else {
  console.log('Hosted API: sign up somewhere with that address, then ask your MCP client for the code.');
}

await client.close();
console.log('smoke ok');
