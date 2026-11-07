/**
 * The local server's HTTP mode reads at most MCP_MAX_BODY_BYTES of a request body (default 4 MiB, like the
 * hosted server) and answers 413 past it, without running a tool.
 */
import { createServer, request, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { Agentboxd } from '../../sdk/src/index.js';
import { ConfigError, loadConfig } from '../src/config.js';
import { createLocalHttpServer } from '../src/localHttp.js';
import { API_KEY, startFakeAgentboxd, type FakeAgentboxd } from './fake-agentboxd.js';

const LIMIT = 2048;
let fake: FakeAgentboxd;
let http: Server;
let port: number;
const logs: string[] = [];

/** A free port: the allowed Host names include the port, so it must be known before the config is built. */
async function freePort(): Promise<number> {
  return new Promise((resolve) => {
    const s = createServer().listen(0, '127.0.0.1', () => {
      const p = (s.address() as AddressInfo).port;
      s.close(() => resolve(p));
    });
  });
}

beforeAll(async () => {
  fake = await startFakeAgentboxd();
  port = await freePort();
  const config = loadConfig({ MCP_MAX_BODY_BYTES: String(LIMIT) }, [`--port=${port}`]);
  http = createLocalHttpServer({ current: new Agentboxd({ apiKey: API_KEY, baseUrl: fake.url }) }, {}, config, (...args) => logs.push(args.join(' ')));
  await new Promise<void>((resolve) => http.listen(port, '127.0.0.1', resolve));
});

afterAll(async () => {
  await new Promise((r) => http.close(r));
  await fake.close();
});

beforeEach(() => {
  fake.requests.length = 0;
  logs.length = 0;
});

/** Sends `body`, or only `partial` under a declared Content-Length when the body is not meant to arrive. */
function post(body: string, extraHeaders: Record<string, string> = {}, partial?: string): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const req = request(
      {
        host: '127.0.0.1',
        port,
        path: '/mcp',
        method: 'POST',
        headers: { Host: `127.0.0.1:${port}`, 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', ...extraHeaders },
      },
      (res) => {
        let text = '';
        res.on('data', (c: Buffer) => (text += c.toString()));
        res.on('end', () => {
          resolve({ status: res.statusCode!, body: text });
          req.destroy();
        });
      },
    );
    req.on('error', reject); // after the answer, a no-op
    if (partial === undefined) req.end(body);
    else req.write(partial);
  });
}

const call = (pad: number) =>
  JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'list_inboxes', arguments: {}, _meta: { pad: 'x'.repeat(pad) } } });

describe('HTTP mode body limit', () => {
  it('serves a body within the limit', async () => {
    const r = await post(call(100));
    expect(r.status).toBe(200);
    expect(r.body).toContain('agent@agents.test');
    expect(fake.requests.some((q) => q.method === 'GET' && q.path === '/v1/inboxes')).toBe(true);
  });

  it('answers 413 past MCP_MAX_BODY_BYTES, and no tool runs', async () => {
    const r = await post(call(LIMIT));
    expect(r.status).toBe(413);
    expect(JSON.parse(r.body)).toEqual({
      jsonrpc: '2.0',
      error: { code: -32000, message: `Request body larger than ${LIMIT} bytes. Set MCP_MAX_BODY_BYTES to allow more.` },
      id: null,
    });
    expect(fake.requests).toEqual([]);
    expect(logs.join('\n')).toMatch(/refused a request: Request body larger than 2048 bytes/);
  });

  it('answers 413 for a chunked body that grows past the limit (no Content-Length to check first)', async () => {
    const r = await new Promise<{ status: number; body: string }>((resolve, reject) => {
      const req = request(
        { host: '127.0.0.1', port, path: '/mcp', method: 'POST', headers: { Host: `127.0.0.1:${port}`, 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' } },
        (res) => {
          let text = '';
          res.on('data', (c: Buffer) => (text += c.toString()));
          res.on('end', () => resolve({ status: res.statusCode ?? 0, body: text }));
        },
      );
      req.on('error', reject);
      const body = call(4 * LIMIT);
      for (let i = 0; i < body.length; i += 1024) req.write(body.slice(i, i + 1024));
      req.end();
    });
    expect(r.status).toBe(413);
    expect(JSON.parse(r.body)).toMatchObject({ error: { code: -32000, message: expect.stringContaining('MCP_MAX_BODY_BYTES') } });
    expect(fake.requests).toEqual([]);
  });

  it('answers 413 for a declared Content-Length past the limit without waiting for the body', async () => {
    const r = await post('', { 'Content-Length': String(64 * 1024 * 1024) }, '{"jsonrpc":"2.0"');
    expect(r.status).toBe(413);
    expect(fake.requests).toEqual([]);
  }, 5_000);

  it('MCP_MAX_BODY_BYTES: 4 MiB by default, a positive integer, read only in HTTP mode', () => {
    expect(loadConfig({}, ['--http']).maxBodyBytes).toBe(4 * 1024 * 1024);
    expect(loadConfig({ MCP_MAX_BODY_BYTES: '1000' }, ['--http']).maxBodyBytes).toBe(1000);
    for (const bad of ['0', '-5', '1.5', 'lots']) {
      expect(() => loadConfig({ MCP_MAX_BODY_BYTES: bad }, ['--http'])).toThrow(ConfigError);
    }
    // stdio has no request bodies: a stray value doesn't stop it.
    expect(loadConfig({ MCP_MAX_BODY_BYTES: 'lots' }, []).httpPort).toBeUndefined();
  });
});

/**
 * #295 A1: the DNS-rebinding guard (Host and Origin) runs before anything else, also in a keyless start: there a
 * rebinding page could otherwise call `signup` and then act with the new workspace's key.
 */
describe('HTTP mode without an API key refuses other sites', () => {
  let keyless: Server;
  let keylessPort: number;
  const ref: { current: Agentboxd | null } = { current: null };

  beforeAll(async () => {
    keylessPort = await freePort();
    const config = loadConfig({}, [`--port=${keylessPort}`]);
    keyless = createLocalHttpServer(ref, { baseUrl: fake.url }, config, (...args) => logs.push(args.join(' ')));
    await new Promise<void>((resolve) => keyless.listen(keylessPort, '127.0.0.1', resolve));
  });

  afterAll(async () => {
    await new Promise((r) => keyless.close(r));
  });

  function send(headers: Record<string, string>, body: unknown): Promise<{ status: number; body: string }> {
    return new Promise((resolve, reject) => {
      const req = request(
        {
          host: '127.0.0.1',
          port: keylessPort,
          path: '/mcp',
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', ...headers },
        },
        (res) => {
          let text = '';
          res.on('data', (c: Buffer) => (text += c.toString()));
          res.on('end', () => resolve({ status: res.statusCode!, body: text }));
        },
      );
      req.on('error', reject);
      req.end(JSON.stringify(body));
    });
  }

  const signup = { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'signup', arguments: {} } };

  it('answers 403 to a foreign Host or Origin, and signup never runs', async () => {
    const cases: Record<string, string>[] = [
      { Host: `attacker.example:${keylessPort}` },
      { Host: `attacker.example:${keylessPort}`, Origin: `http://attacker.example:${keylessPort}` },
      { Host: `127.0.0.1:${keylessPort}`, Origin: 'https://evil.example' },
      { Host: `localhost:${keylessPort}`, Origin: 'null' },
    ];
    for (const headers of cases) {
      const r = await send(headers, signup);
      expect(r.status, JSON.stringify(headers)).toBe(403);
      expect(JSON.parse(r.body)).toMatchObject({ error: { message: expect.stringMatching(/^Forbidden: (Host|Origin) not allowed/) } });
    }
    expect(fake.requests).toEqual([]);
    expect(ref.current).toBeNull();
  });

  it('still serves a local client (the signup tool is listed)', async () => {
    const r = await send({ Host: `localhost:${keylessPort}` }, { jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} });
    expect(r.status).toBe(200);
    expect(r.body).toContain('"signup"');
  });
});
