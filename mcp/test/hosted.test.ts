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
  describeRpc,
  exchangeEndpoint,
  GrantRateLimiter,
  httpExchanger,
  KnownTokens,
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

  it('a made-up token gets its 401 before the body is read or parsed', async () => {
    const bad = await post('{nope', { Authorization: 'Bearer zzz' });
    expect(bad.status).toBe(401);
    expect(exchanged).toEqual(['zzz']);
    // A body within the limit that never arrives: the 401 comes without waiting for it.
    const status = await new Promise<number>((resolve, reject) => {
      const u = new URL(base);
      const req = request(
        { host: u.hostname, port: u.port, path: '/mcp', method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': '1000', Authorization: 'Bearer abxmt_made_up' } },
        (r) => {
          r.resume();
          resolve(r.statusCode ?? 0);
          req.destroy();
        },
      );
      req.on('error', reject); // after the answer, a no-op
      req.write('{"jsonrpc":"2.0"');
      setTimeout(() => {
        req.destroy();
        resolve(0); // no answer while the body was missing
      }, 2_000);
    });
    expect(status).toBe(401);
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
    const big = { jsonrpc: '2.0', id: 1, method: 'x', params: { pad: 'x'.repeat(4000) } };
    expect((await post(big, { Authorization: `Bearer ${ACCESS_TOKEN}` })).status).toBe(413);
    expect(exchanged).toEqual([]);
    const bad = await post('{nope', { Authorization: `Bearer ${ACCESS_TOKEN}` });
    expect(bad.status).toBe(400);
    expect(await bad.json()).toMatchObject({ error: { code: -32700 } });
    expect((await fetch(`${base}/other`)).status).toBe(404);
  });

  it('413 for a chunked body that grows past the limit (no Content-Length to check first)', async () => {
    const r = await new Promise<{ status: number; body: string }>((resolve, reject) => {
      const u = new URL(base);
      const req = request(
        { host: u.hostname, port: u.port, path: '/mcp', method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${ACCESS_TOKEN}` } },
        (res) => {
          let text = '';
          res.on('data', (c: Buffer) => (text += c.toString()));
          res.on('end', () => resolve({ status: res.statusCode ?? 0, body: text }));
        },
      );
      req.on('error', reject);
      for (let i = 0; i < 8; i++) req.write('x'.repeat(1024));
      req.end();
    });
    expect(r.status).toBe(413);
    expect(JSON.parse(r.body)).toMatchObject({ error: { code: -32000, message: 'Request body larger than 2048 bytes' } });
    expect(fake.requests).toEqual([]);
  });

  it('401 without a Bearer header before the body is read, whatever its size', async () => {
    const big = { jsonrpc: '2.0', id: 1, method: 'x', params: { pad: 'x'.repeat(4000) } };
    const res = await post(big);
    expect(res.status).toBe(401);
    expect(res.headers.get('www-authenticate')).toMatch(/^Bearer resource_metadata=/);
    // A declared length far over the limit is answered without waiting for the body.
    const status = await new Promise<number>((resolve, reject) => {
      const u = new URL(base);
      const req = request(
        { host: u.hostname, port: u.port, path: '/mcp', method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': String(64 * 1024 * 1024) } },
        (r) => {
          r.resume();
          resolve(r.statusCode ?? 0);
          req.destroy();
        },
      );
      req.on('error', reject); // after the answer, a no-op
      req.write('{"jsonrpc":"2.0"');
    });
    expect(status).toBe(401);
    expect(exchanged).toEqual([]);
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

  it('logs the size of a batch and the method and tool of each message, never their arguments (#295 A5)', async () => {
    logs.length = 0;
    const res = await post(
      [
        { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'create_inbox', arguments: { username: 'secret-batch-part' } } },
        { jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} },
        { jsonrpc: '2.0', method: 'notifications/initialized' },
      ],
      { Authorization: `Bearer ${ACCESS_TOKEN}` },
    );
    expect(res.status).toBe(200);
    await res.text();
    const entry = logs.find((l) => l.rpc === 'batch');
    expect(entry).toMatchObject({ batch: 3, methods: ['tools/call', 'tools/list', 'notifications/initialized'], tools: ['create_inbox'], grant: 'grant-1', status: 200 });
    expect(JSON.stringify(logs)).not.toContain('secret-batch-part');
  });

  it('describeRpc: one message, a batch (a response has no method), at most 100 methods logged', () => {
    expect(describeRpc({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'get_message', arguments: { message_id: 'x' } } })).toEqual({
      rpc: 'tools/call',
      tool: 'get_message',
    });
    expect(describeRpc([{ jsonrpc: '2.0', id: 1, result: {} }, { jsonrpc: '2.0', id: 2, method: 'ping' }])).toEqual({ rpc: 'batch', batch: 2, methods: [null, 'ping'] });
    const big = describeRpc(Array.from({ length: 150 }, (_, i) => ({ jsonrpc: '2.0', id: i, method: 'm'.repeat(100) })));
    expect(big).toMatchObject({ rpc: 'batch', batch: 150 });
    expect(big.methods).toHaveLength(100);
    expect(big.methods![0]).toHaveLength(64);
    expect(describeRpc('nope')).toEqual({});
  });
});

describe('rate limit per grant', () => {
  it('counts per grant in one-minute windows; refund takes back one request, never below none', () => {
    let t = 0;
    const l = new GrantRateLimiter(2, () => t);
    expect(l.take('a')).toBe(0);
    expect(l.take('a')).toBe(0);
    l.refund('a');
    expect(l.take('a')).toBe(0);
    expect(l.take('a')).toBeGreaterThan(0);
    // take(n) counts n at once (a batch).
    expect(new GrantRateLimiter(3, () => t).take('z', 3)).toBe(0);
    const n = new GrantRateLimiter(3, () => t);
    expect(n.take('z', 2)).toBe(0);
    expect(n.take('z', 2)).toBeGreaterThan(0);
    expect(l.take('b')).toBe(0);
    l.refund('b');
    l.refund('b');
    l.refund('c');
    expect(l.take('b')).toBe(0);
    expect(l.take('b')).toBe(0);
    expect(l.take('b')).toBeGreaterThan(0);
    t = 60_000;
    expect(l.take('a')).toBe(0);
  });

  describe('a connection past its allowance', () => {
    const LIMIT = 3;
    const TOKENS: Record<string, string> = { abxmt_a: 'grant-a', abxmt_a2: 'grant-a', abxmt_b: 'grant-b' };
    let srv: Server;
    let url: string;
    let t = 1_000_000 * 60_000; // the start of a minute
    let calls: string[] = [];
    let revoked = new Set<string>();
    let down = false;

    beforeAll(async () => {
      const ex: Exchanger = async (token) => {
        calls.push(token);
        if (down) return { ok: false, kind: 'unavailable', description: 'down' };
        const grantId = TOKENS[token];
        if (!grantId || revoked.has(token)) return { ok: false, kind: 'invalid', description: 'the access token is invalid, expired or revoked' };
        return { ok: true, token: API_KEY, grantId, clientId: 'c', expiresIn: 300 };
      };
      srv = createServer();
      await new Promise<void>((r) => srv.listen(0, '127.0.0.1', r));
      url = `http://127.0.0.1:${(srv.address() as AddressInfo).port}/mcp`;
      const limited = loadHostedConfig({
        MCP_RESOURCE_URL: url,
        IDENTITY_ISSUER: 'https://id.agentboxd.test',
        AGENTBOXD_INTERNAL_URL: fake.url,
        CONNECTOR_EXCHANGE_SECRET: SECRET,
        MCP_MAX_BODY_BYTES: '2048',
        MCP_RATE_LIMIT_PER_MINUTE: String(LIMIT),
      });
      const handle = createHostedHandler(limited, { exchange: ex, log: () => {}, now: () => t });
      srv.on('request', (req, res) => void handle(req, res));
    });

    afterAll(async () => {
      await new Promise((r) => srv.close(r));
    });

    beforeEach(() => {
      t += 60_000;
      calls = [];
      revoked = new Set();
      down = false;
    });

    /** Sends `body` (a string as is, anything else as JSON). */
    const send = async (token: string, body: unknown = init) => {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', Authorization: `Bearer ${token}` },
        body: typeof body === 'string' ? body : JSON.stringify(body),
      });
      await res.text();
      return res;
    };

    /** Sends the headers and the first bytes of `body` now, the rest when `finish` is called. */
    const open = (token: string, body: string) => {
      const u = new URL(url);
      let finish = () => {};
      const status = new Promise<number>((resolve, reject) => {
        const req = request(
          {
            host: u.hostname,
            port: u.port,
            path: u.pathname,
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Accept: 'application/json, text/event-stream',
              Authorization: `Bearer ${token}`,
              'Content-Length': String(Buffer.byteLength(body)),
            },
          },
          (res) => {
            res.resume();
            res.on('end', () => resolve(res.statusCode ?? 0));
          },
        );
        req.on('error', reject); // after the answer, a no-op
        req.write(body.slice(0, 5));
        finish = () => void req.end(body.slice(5));
      });
      return { status, finish: () => finish() };
    };

    it('serves every request of the allowance, then answers 429 without another exchange or reading the body', async () => {
      for (let i = 0; i < LIMIT; i++) expect((await send('abxmt_a')).status).toBe(200);
      expect(calls).toHaveLength(LIMIT);
      for (let i = 0; i < 5; i++) {
        const r = await send('abxmt_a');
        expect(r.status).toBe(429);
        expect(Number(r.headers.get('retry-after'))).toBeGreaterThan(0);
      }
      // A declared body over the limit gets 413 before anything else, and no exchange either.
      expect((await send('abxmt_a', { jsonrpc: '2.0', id: 1, method: 'x', params: { pad: 'x'.repeat(4000) } })).status).toBe(413);
      expect(calls).toHaveLength(LIMIT);
      // Another connection is not affected; the next minute starts afresh.
      expect((await send('abxmt_b')).status).toBe(200);
      t += 60_000;
      expect((await send('abxmt_a')).status).toBe(200);
      expect(calls).toEqual([...Array<string>(LIMIT).fill('abxmt_a'), 'abxmt_b', 'abxmt_a']);
    });

    it('a new token of a connection that used up its minute is exchanged once, then refused like the others', async () => {
      for (let i = 0; i < LIMIT; i++) expect((await send('abxmt_a')).status).toBe(200);
      // A refreshed access token is not known yet: one exchange tells which connection it belongs to.
      expect((await send('abxmt_a2')).status).toBe(429);
      expect((await send('abxmt_a2')).status).toBe(429);
      expect(calls.filter((c) => c === 'abxmt_a2')).toHaveLength(1);
    });

    it('a token known from an earlier exchange is still checked by the exchange: revoked means 401', async () => {
      expect((await send('abxmt_b')).status).toBe(200);
      revoked.add('abxmt_b');
      expect((await send('abxmt_b')).status).toBe(401);
      expect((await send('abxmt_b')).status).toBe(401);
      expect(calls).toEqual(['abxmt_b', 'abxmt_b', 'abxmt_b']);
    });

    it('counts a request before its body arrives: bodies sent slowly cost no exchange past the limit', async () => {
      expect((await send('abxmt_a')).status).toBe(200); // known now, 1 of LIMIT used
      const held = Array.from({ length: 10 }, () => open('abxmt_a', JSON.stringify(init)));
      await new Promise((r) => setTimeout(r, 100)); // every request's headers are in, no body is complete
      for (const h of held) h.finish();
      const statuses = await Promise.all(held.map((h) => h.status));
      expect(statuses.filter((s) => s === 200)).toHaveLength(LIMIT - 1);
      expect(statuses.filter((s) => s === 429)).toHaveLength(10 - (LIMIT - 1));
      expect(calls).toHaveLength(LIMIT);
    });

    it('a request that cost an exchange counts even when its body is not valid JSON', async () => {
      const statuses: number[] = [];
      for (let i = 0; i < LIMIT + 3; i++) statuses.push((await send('abxmt_a', '{nope')).status);
      expect(statuses).toEqual([...Array<number>(LIMIT).fill(400), 429, 429, 429]);
      expect(calls).toHaveLength(LIMIT);
    });

    it('a request whose exchange fails does not count toward the minute', async () => {
      expect((await send('abxmt_a')).status).toBe(200); // known now, 1 of LIMIT used
      down = true;
      for (let i = 0; i < LIMIT + 2; i++) expect((await send('abxmt_a')).status).toBe(503);
      down = false;
      for (let i = 1; i < LIMIT; i++) expect((await send('abxmt_a')).status).toBe(200);
      expect((await send('abxmt_a')).status).toBe(429);
    });

    const listInboxes = (id: number) => ({ jsonrpc: '2.0', id, method: 'tools/call', params: { name: 'list_inboxes', arguments: {} } });
    const toolRuns = () => fake.requests.filter((q) => q.method === 'GET' && q.path === '/v1/inboxes').length;

    it('a JSON-RPC batch counts each of its messages, and a batch past the limit runs none of them (#295 A5)', async () => {
      const first = await send('abxmt_a', [listInboxes(1), listInboxes(2)]);
      expect(first.status).toBe(200);
      expect(toolRuns()).toBe(2);
      // 2 of LIMIT used: a second batch of 2 would make 4.
      const second = await send('abxmt_a', [listInboxes(3), listInboxes(4)]);
      expect(second.status).toBe(429);
      expect(Number(second.headers.get('retry-after'))).toBeGreaterThan(0);
      expect(toolRuns()).toBe(2);
      // The minute is used up for single requests too, at no exchange.
      expect((await send('abxmt_a')).status).toBe(429);
      expect(calls).toEqual(['abxmt_a', 'abxmt_a']);
    });

    it('a batch larger than the whole allowance is refused at once (no tool runs)', async () => {
      const r = await send('abxmt_b', Array.from({ length: 10 }, (_, i) => listInboxes(i + 1)));
      expect(r.status).toBe(429);
      expect(toolRuns()).toBe(0);
      expect(calls).toEqual(['abxmt_b']);
    });

    it('a batch of one counts once, like a single message', async () => {
      for (let i = 0; i < LIMIT; i++) expect((await send('abxmt_a', [listInboxes(i + 1)])).status).toBe(200);
      expect((await send('abxmt_a', [listInboxes(9)])).status).toBe(429);
    });

    it('a token whose exchange failed is forgotten: it goes to the exchange again, not to the limit', async () => {
      expect((await send('abxmt_a2')).status).toBe(200);
      revoked.add('abxmt_a2');
      expect((await send('abxmt_a2')).status).toBe(401);
      for (let i = 1; i < LIMIT; i++) expect((await send('abxmt_a')).status).toBe(200); // grant-a uses up its minute
      expect((await send('abxmt_a')).status).toBe(429);
      expect((await send('abxmt_a2')).status).toBe(401);
      expect(calls.filter((c) => c === 'abxmt_a2')).toHaveLength(3);
    });
  });
});

describe('known tokens', () => {
  it('remembers a token for its exchange lifetime (at most 5 minutes), forgets on request, keeps the newest', () => {
    let t = 0;
    const k = new KnownTokens(2, () => t);
    k.remember('tok-1', 'g1', 'c', 30);
    k.remember('tok-2', 'g2', 'c', 3600);
    expect(k.get('tok-1')).toEqual({ grantId: 'g1', clientId: 'c' });
    t = 30_000;
    expect(k.get('tok-1')).toBeUndefined();
    expect(k.get('tok-2')).toMatchObject({ grantId: 'g2' });
    t = 300_000;
    expect(k.get('tok-2')).toBeUndefined();

    k.remember('tok-3', 'g3', 'c', undefined); // no lifetime given: one minute
    k.remember('tok-4', 'g4', 'c', 120);
    k.remember('tok-5', 'g5', 'c', 120);
    expect(k.size).toBe(2);
    expect(k.get('tok-3')).toBeUndefined();
    expect(k.get('tok-5')).toMatchObject({ grantId: 'g5' });
    k.forget('tok-5');
    expect(k.get('tok-5')).toBeUndefined();
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
    expect(await ex('abxmt_a')).toEqual({ ok: true, token: 'abxst_x', grantId: 'g', clientId: 'c', expiresIn: 300 });
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
