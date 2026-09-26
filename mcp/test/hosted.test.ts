/**
 * The hosted MCP server (docs/remote-mcp-contract.md §2, §5): discovery, the 401 challenge, Host/Origin
 * checks, limits, the token exchange client and a real MCP client session over Streamable HTTP whose
 * tools reach the (fake) API with the exchanged token, never the person's access token.
 */
import { createServer, request, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { ConfigError } from '../src/config.js';
import {
  createHostedHandler,
  exchangeEndpoint,
  GrantRateLimiter,
  httpExchanger,
  loadHostedConfig,
  protectedResourceMetadata,
  resourceMetadataUrl,
  wwwAuthenticate,
  type Exchanger,
  type HostedConfig,
} from '../src/hosted.js';
import { HOSTED_SERVER_INSTRUCTIONS, HOSTED_TOOL_NAMES } from '../src/server.js';
import { API_KEY, startFakeAgentboxd, type FakeAgentboxd } from './fake-agentboxd.js';

const ACCESS_TOKEN = 'abxmt_person-access-token-000000000000000000000';
const SECRET = 's'.repeat(40);

let fake: FakeAgentboxd;
let http: Server;
let base: string;
let cfg: HostedConfig;
const logs: Record<string, unknown>[] = [];
const exchanged: string[] = [];
let exchangeMode: 'ok' | 'invalid' | 'down' = 'ok';

const exchange: Exchanger = async (token) => {
  exchanged.push(token);
  if (exchangeMode === 'down') return { ok: false, kind: 'unavailable', description: 'down' };
  if (exchangeMode === 'invalid' || token !== ACCESS_TOKEN) return { ok: false, kind: 'invalid', description: 'the access token is invalid, expired or revoked' };
  return { ok: true, token: API_KEY, grantId: 'grant-1', clientId: 'https://claude.ai/oauth/claude-code-client-metadata' };
};

async function post(body: unknown, headers: Record<string, string> = {}, path = '/mcp') {
  return fetch(`${base}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', ...headers },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

const init = { jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 't', version: '0' } } };

beforeAll(async () => {
  fake = await startFakeAgentboxd();
  http = createServer();
  await new Promise<void>((r) => http.listen(0, '127.0.0.1', r));
  const port = (http.address() as AddressInfo).port;
  base = `http://127.0.0.1:${port}`;
  cfg = loadHostedConfig({
    MCP_RESOURCE_URL: `${base}/mcp`,
    IDENTITY_ISSUER: 'https://id.agentboxd.test',
    AGENTBOXD_INTERNAL_URL: fake.url,
    CONNECTOR_EXCHANGE_SECRET: SECRET,
    MCP_ALLOWED_ORIGINS: 'https://claude.ai',
    MCP_MAX_BODY_BYTES: '2048',
    MCP_RATE_LIMIT_PER_MINUTE: '1000',
  });
  const handle = createHostedHandler(cfg, { exchange, log: (e) => logs.push(e) });
  http.on('request', (req, res) => void handle(req, res));
});

afterAll(async () => {
  await new Promise((r) => http.close(r));
  await fake.close();
});

beforeEach(() => {
  exchangeMode = 'ok';
  exchanged.length = 0;
  fake.requests.length = 0;
});

describe('discovery', () => {
  it('serves protected resource metadata at the path-suffixed and root well-known URLs', async () => {
    for (const p of ['/.well-known/oauth-protected-resource/mcp', '/.well-known/oauth-protected-resource']) {
      const res = await fetch(`${base}${p}`);
      expect(res.status).toBe(200);
      expect(res.headers.get('access-control-allow-origin')).toBe('*');
      expect(await res.json()).toEqual({
        resource: `${base}/mcp`,
        authorization_servers: ['https://id.agentboxd.test'],
        scopes_supported: ['mcp'],
        bearer_methods_supported: ['header'],
        resource_name: 'Agentboxd',
        resource_documentation: 'https://agentboxd.com/docs/mcp',
      });
    }
    expect(resourceMetadataUrl({ resource: 'https://mcp.agentboxd.com/mcp' })).toBe('https://mcp.agentboxd.com/.well-known/oauth-protected-resource/mcp');
    expect(protectedResourceMetadata({ resource: 'https://mcp.agentboxd.com/mcp', issuer: 'https://id.agentboxd.com' }).resource).toBe('https://mcp.agentboxd.com/mcp');
  });

  it('health check', async () => {
    expect((await fetch(`${base}/health`)).status).toBe(200);
  });
});

describe('the 401 challenge', () => {
  it('answers every unauthenticated MCP request, initialize included, with resource_metadata and scope', async () => {
    const res = await post(init);
    expect(res.status).toBe(401);
    expect(res.headers.get('www-authenticate')).toBe(`Bearer resource_metadata="${base}/.well-known/oauth-protected-resource/mcp", scope="mcp"`);
    expect(await res.json()).toMatchObject({ error: 'invalid_token' });
    expect(exchanged).toEqual([]);
  });

  it('marks an invalid token with error="invalid_token"', async () => {
    const res = await post(init, { Authorization: 'Bearer abxmt_nope' });
    expect(res.status).toBe(401);
    expect(res.headers.get('www-authenticate')).toMatch(/^Bearer error="invalid_token", error_description="[^"]+", resource_metadata="[^"]+", scope="mcp"$/);
  });

  it('never reads a token from the query string', async () => {
    const res = await post(init, {}, `/mcp?access_token=${ACCESS_TOKEN}`);
    expect(res.status).toBe(401);
    expect(exchanged).toEqual([]);
  });

  it('503 (not 401) when the authorization server is down, so clients keep their tokens', async () => {
    exchangeMode = 'down';
    const res = await post(init, { Authorization: `Bearer ${ACCESS_TOKEN}` });
    expect(res.status).toBe(503);
    expect(res.headers.get('retry-after')).toBe('5');
  });

  it('wwwAuthenticate strips quotes from descriptions', () => {
    expect(wwwAuthenticate({ resource: 'https://m.test/mcp' }, { code: 'invalid_token', description: 'a "b"' })).toContain('error_description="a b"');
  });
});

describe('transport guards', () => {
  it('421 for a foreign Host (DNS rebinding)', async () => {
    // fetch() can't override Host; a raw request can, like a rebinding page would via DNS.
    const status = await new Promise<number>((resolve, reject) => {
      const u = new URL(base);
      const req = request(
        { host: u.hostname, port: u.port, path: '/mcp', method: 'POST', headers: { Host: 'evil.example', 'Content-Type': 'application/json', Authorization: `Bearer ${ACCESS_TOKEN}` } },
        (res) => {
          res.resume();
          resolve(res.statusCode ?? 0);
        },
      );
      req.on('error', reject);
      req.end(JSON.stringify(init));
    });
    expect(status).toBe(421);
    expect(exchanged).toEqual([]);
  });

  it('403 for an Origin that is not allowed; CORS for one that is', async () => {
    const bad = await post(init, { Origin: 'https://evil.example', Authorization: `Bearer ${ACCESS_TOKEN}` });
    expect(bad.status).toBe(403);
    expect(await bad.json()).toMatchObject({ jsonrpc: '2.0', error: { code: -32000 }, id: null });
    expect(exchanged).toEqual([]);

    const pre = await fetch(`${base}/mcp`, { method: 'OPTIONS', headers: { Origin: 'https://claude.ai', 'Access-Control-Request-Method': 'POST' } });
    expect(pre.status).toBe(204);
    expect(pre.headers.get('access-control-allow-origin')).toBe('https://claude.ai');
    expect(pre.headers.get('access-control-allow-headers')).toMatch(/Authorization/);

    const unauth = await post(init, { Origin: 'https://claude.ai' });
    expect(unauth.status).toBe(401);
    expect(unauth.headers.get('access-control-expose-headers')).toMatch(/WWW-Authenticate/);
  });

  it('405 for GET and DELETE (stateless: no SSE stream, no sessions)', async () => {
    expect((await fetch(`${base}/mcp`, { headers: { Authorization: `Bearer ${ACCESS_TOKEN}` } })).status).toBe(405);
    expect((await fetch(`${base}/mcp`, { method: 'DELETE' })).status).toBe(405);
  });

  it('413 over the body limit, 400 for invalid JSON, 404 elsewhere', async () => {
    expect((await post({ jsonrpc: '2.0', id: 1, method: 'x', params: { pad: 'x'.repeat(4000) } })).status).toBe(413);
    const bad = await post('{nope', { Authorization: `Bearer ${ACCESS_TOKEN}` });
    expect(bad.status).toBe(400);
    expect(await bad.json()).toMatchObject({ error: { code: -32700 } });
    expect((await fetch(`${base}/other`)).status).toBe(404);
  });
});

describe('an authorized MCP session', () => {
  async function connect() {
    const client = new Client({ name: 'hosted-test', version: '0.0.0' });
    const transport = new StreamableHTTPClientTransport(new URL(`${base}/mcp`), {
      requestInit: { headers: { Authorization: `Bearer ${ACCESS_TOKEN}` } },
    });
    await client.connect(transport);
    return client;
  }

  it('lists the hosted tools (no signup) and the hosted instructions', async () => {
    const client = await connect();
    const { tools } = await client.listTools();
    expect(tools.map((t) => t.name).sort()).toEqual([...HOSTED_TOOL_NAMES].sort());
    expect(tools.map((t) => t.name)).not.toContain('signup');
    expect(client.getInstructions()).toBe(HOSTED_SERVER_INSTRUCTIONS);
    expect(HOSTED_SERVER_INSTRUCTIONS).not.toMatch(/Call signup/);
    await client.close();
  });

  it('tools call the API with the exchanged token, never the access token; no session id is minted', async () => {
    const client = await connect();
    const r = (await client.callTool({ name: 'create_inbox', arguments: { client_id: 'hosted' } })) as CallToolResult;
    expect(r.isError).toBeFalsy();
    expect(fake.requests.some((q) => q.method === 'POST' && q.path === '/v1/inboxes')).toBe(true);
    expect(exchanged.every((t) => t === ACCESS_TOKEN)).toBe(true);
    await client.close();

    const res = await post(init, { Authorization: `Bearer ${ACCESS_TOKEN}` });
    expect(res.status).toBe(200);
    expect(res.headers.get('mcp-session-id')).toBeNull();
  });

  it('the claim/ack queue tools work hosted (claim_messages, ack_message)', async () => {
    expect(HOSTED_TOOL_NAMES).toEqual(expect.arrayContaining(['claim_messages', 'ack_message']));
    const client = await connect();
    const claimed = (await client.callTool({ name: 'claim_messages', arguments: { inbox_id: 'inb_1' } })) as CallToolResult;
    expect(claimed.isError).toBeFalsy();
    expect((claimed.content[0] as { text: string }).text).toContain('lease_1');
    const acked = (await client.callTool({ name: 'ack_message', arguments: { message_id: 'msg_1', lease_id: 'lease_1' } })) as CallToolResult;
    expect(acked.isError).toBeFalsy();
    expect(fake.requests.map((q) => `${q.method} ${q.path}`)).toEqual(
      expect.arrayContaining(['POST /v1/inboxes/inb_1/messages/claim', 'POST /v1/messages/msg_1/ack']),
    );
    await client.close();
  });

  it('turns insufficient_permissions into a tool error with a reconnect hint', async () => {
    fake.overrides.set('GET /v1/deliverability', { status: 403, body: { error: { code: 'insufficient_permissions', message: 'this API key lacks the "metrics:read" permission' } } });
    const client = await connect();
    const r = (await client.callTool({ name: 'get_deliverability', arguments: {} })) as CallToolResult;
    expect(r.isError).toBe(true);
    const payload = JSON.parse((r.content[0] as { text: string }).text) as { error: { code: string; hint?: string } };
    expect(payload.error.code).toBe('insufficient_permissions');
    expect(payload.error.hint).toMatch(/reconnect/);
    fake.overrides.clear();
    await client.close();
  });

  it('logs method, tool, grant and status, and never the token or arguments', async () => {
    logs.length = 0;
    const client = await connect();
    await client.callTool({ name: 'create_inbox', arguments: { username: 'secret-local-part' } });
    await client.close();
    const call = logs.find((l) => l.tool === 'create_inbox');
    expect(call).toMatchObject({ msg: 'mcp request', rpc: 'tools/call', tool: 'create_inbox', grant: 'grant-1', status: 200 });
    const text = JSON.stringify(logs);
    expect(text).not.toContain(ACCESS_TOKEN);
    expect(text).not.toContain(API_KEY);
    expect(text).not.toContain('secret-local-part');
  });
});

describe('rate limit per grant', () => {
  it('counts per grant in one-minute windows', () => {
    let t = 0;
    const l = new GrantRateLimiter(2, () => t);
    expect(l.take('a')).toBe(0);
    expect(l.take('a')).toBe(0);
    expect(l.take('a')).toBeGreaterThan(0);
    expect(l.take('b')).toBe(0);
    t = 60_000;
    expect(l.take('a')).toBe(0);
  });
});

describe('token exchange client', () => {
  it('posts an RFC 8693 exchange to the internal issuer with Basic auth and the issuer Host', async () => {
    const seen: { url: string; headers: Record<string, string>; body: URLSearchParams }[] = [];
    const answers = [
      { status: 200, body: { access_token: 'abxst_x', grant_id: 'g', client_id: 'c', expires_in: 300 } },
      { status: 400, body: { error: 'invalid_grant' } },
      { status: 401, body: { error: 'invalid_client' } },
    ];
    const fakeFetch = (async (url: string, init: RequestInit) => {
      seen.push({ url, headers: init.headers as Record<string, string>, body: init.body as URLSearchParams });
      const a = answers.shift()!;
      return new Response(JSON.stringify(a.body), { status: a.status, headers: { 'Content-Type': 'application/json' } });
    }) as unknown as typeof fetch;
    const c = { ...cfg, issuer: 'https://id.agentboxd.com', internalUrl: 'http://api:3000' };
    const ex = httpExchanger(c, fakeFetch);
    expect(await ex('abxmt_a')).toEqual({ ok: true, token: 'abxst_x', grantId: 'g', clientId: 'c' });
    expect(await ex('abxmt_b')).toMatchObject({ ok: false, kind: 'invalid' });
    expect(await ex('abxmt_c')).toMatchObject({ ok: false, kind: 'unavailable' });
    expect(seen[0]!.url).toBe('http://api:3000/token');
    expect(seen[0]!.headers['X-Forwarded-Host']).toBe('id.agentboxd.com');
    expect(seen[0]!.headers.Authorization).toBe(`Basic ${Buffer.from(`agentboxd-mcp:${SECRET}`).toString('base64')}`);
    expect(Object.fromEntries(seen[0]!.body)).toEqual({
      grant_type: 'urn:ietf:params:oauth:grant-type:token-exchange',
      subject_token: 'abxmt_a',
      subject_token_type: 'urn:ietf:params:oauth:token-type:access_token',
      resource: cfg.resource,
      audience: 'agentboxd-api',
    });
    expect(exchangeEndpoint({ issuer: 'http://localhost:3000/oidc', internalUrl: 'http://api:3000' }).url).toBe('http://api:3000/oidc/token');
  });

  it('maps a network failure to unavailable', async () => {
    const ex = httpExchanger(cfg, (async () => {
      throw new TypeError('fetch failed');
    }) as unknown as typeof fetch);
    expect(await ex('abxmt_a')).toMatchObject({ ok: false, kind: 'unavailable' });
  });
});

describe('configuration', () => {
  it('requires the exchange secret and a resource path; production defaults', () => {
    expect(() => loadHostedConfig({})).toThrow(ConfigError);
    expect(() => loadHostedConfig({ CONNECTOR_EXCHANGE_SECRET: SECRET, MCP_RESOURCE_URL: 'https://mcp.example.com' })).toThrow(/path/);
    const prod = loadHostedConfig({ NODE_ENV: 'production', CONNECTOR_EXCHANGE_SECRET: SECRET });
    expect(prod).toMatchObject({
      resource: 'https://mcp.agentboxd.com/mcp',
      issuer: 'https://id.agentboxd.com',
      internalUrl: 'http://api:3000',
      allowedOrigins: ['https://claude.ai', 'https://claude.com'],
      allowedHosts: ['mcp.agentboxd.com'],
      port: 3334,
      rateLimitPerMinute: 120,
    });
  });
});
