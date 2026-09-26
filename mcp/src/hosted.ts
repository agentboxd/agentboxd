/**
 * The hosted remote MCP server (https://mcp.agentboxd.com/mcp): an OAuth 2.1 protected resource in front
 * of the same tools as the npm package. See docs/remote-mcp-contract.md §2 and §5.
 *
 * Per request: Host and Origin checks (DNS rebinding) → body limit → the Bearer access token is exchanged
 * at the authorization server for a short-lived API token (the person's token never reaches the API) →
 * per-grant rate limit → a fresh stateless MCP server whose tools call the API with that token.
 */
import type { IncomingMessage, ServerResponse } from 'node:http';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { Agentboxd } from '../../sdk/src/index.js';
import { ConfigError } from './config.js';
import { createAgentboxdMcpServer } from './server.js';

export const CONNECTOR_SCOPE = 'mcp';
export const EXCHANGE_CLIENT_ID = 'agentboxd-mcp';
const TOKEN_EXCHANGE_GRANT = 'urn:ietf:params:oauth:grant-type:token-exchange';
const ACCESS_TOKEN_TYPE = 'urn:ietf:params:oauth:token-type:access_token';

export interface HostedConfig {
  /** Canonical resource URL (MCP_RESOURCE_URL), e.g. https://mcp.agentboxd.com/mcp. Its path is the MCP endpoint. */
  resource: string;
  /** Public issuer (IDENTITY_ISSUER), listed in the protected resource metadata. */
  issuer: string;
  /** Where this process reaches the api service (AGENTBOXD_INTERNAL_URL), e.g. http://api:3000. */
  internalUrl: string;
  /** CONNECTOR_EXCHANGE_SECRET, shared with the api. */
  exchangeSecret: string;
  allowedOrigins: string[];
  allowedHosts: string[];
  maxBodyBytes: number;
  rateLimitPerMinute: number;
  port: number;
  host: string;
}

const list = (v: string | undefined) =>
  (v ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);

function positiveInt(name: string, raw: string | undefined, fallback: number): number {
  if (!raw?.trim()) return fallback;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 1) throw new ConfigError(`${name} must be a positive integer`);
  return n;
}

function url(name: string, raw: string | undefined, fallback?: string): string {
  const v = (raw?.trim() || fallback)?.replace(/\/+$/, '');
  if (!v) throw new ConfigError(`${name} is required`);
  try {
    const u = new URL(v);
    if (u.protocol !== 'https:' && u.protocol !== 'http:') throw new Error('scheme');
  } catch {
    throw new ConfigError(`${name} is not a valid http(s) URL: ${v}`);
  }
  return v;
}

export function loadHostedConfig(env: NodeJS.ProcessEnv = process.env): HostedConfig {
  const production = env.NODE_ENV === 'production';
  const resource = url('MCP_RESOURCE_URL', env.MCP_RESOURCE_URL, production ? 'https://mcp.agentboxd.com/mcp' : 'http://localhost:3334/mcp');
  const issuer = url('IDENTITY_ISSUER', env.IDENTITY_ISSUER, production ? 'https://id.agentboxd.com' : 'http://localhost:3000/oidc');
  const internalUrl = url('AGENTBOXD_INTERNAL_URL', env.AGENTBOXD_INTERNAL_URL, 'http://api:3000');
  const exchangeSecret = env.CONNECTOR_EXCHANGE_SECRET?.trim() ?? '';
  if (exchangeSecret.length < 32) throw new ConfigError('CONNECTOR_EXCHANGE_SECRET must be set (at least 32 characters, the same value as the api)');
  if (new URL(resource).pathname === '/' || new URL(resource).pathname === '') throw new ConfigError('MCP_RESOURCE_URL needs a path, e.g. /mcp');
  const allowedOrigins = env.MCP_ALLOWED_ORIGINS === undefined ? ['https://claude.ai', 'https://claude.com'] : list(env.MCP_ALLOWED_ORIGINS);
  const allowedHosts = [new URL(resource).host.toLowerCase(), ...list(env.MCP_ALLOWED_HOSTS).map((h) => h.toLowerCase())];
  return {
    resource,
    issuer,
    internalUrl,
    exchangeSecret,
    allowedOrigins,
    allowedHosts,
    maxBodyBytes: positiveInt('MCP_MAX_BODY_BYTES', env.MCP_MAX_BODY_BYTES, 4 * 1024 * 1024),
    rateLimitPerMinute: positiveInt('MCP_RATE_LIMIT_PER_MINUTE', env.MCP_RATE_LIMIT_PER_MINUTE, 120),
    port: positiveInt('MCP_HTTP_PORT', env.MCP_HTTP_PORT, 3334),
    host: env.MCP_HTTP_HOST?.trim() || '0.0.0.0',
  };
}

// ---------- discovery (RFC 9728) ----------

export const mcpPath = (cfg: Pick<HostedConfig, 'resource'>) => new URL(cfg.resource).pathname.replace(/\/+$/, '') || '/';

/** The protected resource metadata URL advertised in WWW-Authenticate (path-suffixed form, RFC 9728 §3.1). */
export const resourceMetadataUrl = (cfg: Pick<HostedConfig, 'resource'>) =>
  `${new URL(cfg.resource).origin}/.well-known/oauth-protected-resource${mcpPath(cfg)}`;

export function protectedResourceMetadata(cfg: Pick<HostedConfig, 'resource' | 'issuer'>) {
  return {
    resource: cfg.resource,
    authorization_servers: [cfg.issuer],
    scopes_supported: [CONNECTOR_SCOPE],
    bearer_methods_supported: ['header'],
    resource_name: 'Agentboxd',
    resource_documentation: 'https://agentboxd.com/docs/mcp',
  };
}

const quote = (s: string) => s.replace(/["\\]/g, '');

/** RFC 6750 §3 challenge with the RFC 9728 resource_metadata pointer. */
export function wwwAuthenticate(cfg: Pick<HostedConfig, 'resource'>, error?: { code: string; description: string }): string {
  const parts = [`resource_metadata="${resourceMetadataUrl(cfg)}"`, `scope="${CONNECTOR_SCOPE}"`];
  if (error) parts.unshift(`error="${quote(error.code)}"`, `error_description="${quote(error.description)}"`);
  return `Bearer ${parts.join(', ')}`;
}

// ---------- token exchange (§5.1) ----------

export type ExchangeResult =
  | { ok: true; token: string; grantId: string; clientId: string }
  | { ok: false; kind: 'invalid' | 'unavailable'; description: string };

export type Exchanger = (accessToken: string) => Promise<ExchangeResult>;

/** The token endpoint as this process reaches it: internal URL + the issuer's path, Host of the issuer. */
export function exchangeEndpoint(cfg: Pick<HostedConfig, 'issuer' | 'internalUrl'>) {
  const issuer = new URL(cfg.issuer);
  return { url: `${cfg.internalUrl}${issuer.pathname.replace(/\/+$/, '')}/token`, forwardedHost: issuer.host };
}

export function httpExchanger(cfg: HostedConfig, fetchFn: typeof fetch = fetch): Exchanger {
  const { url: endpoint, forwardedHost } = exchangeEndpoint(cfg);
  const basic = `Basic ${Buffer.from(`${encodeURIComponent(EXCHANGE_CLIENT_ID)}:${encodeURIComponent(cfg.exchangeSecret)}`).toString('base64')}`;
  return async (accessToken) => {
    let res: Response;
    try {
      res = await fetchFn(endpoint, {
        method: 'POST',
        headers: {
          Authorization: basic,
          'Content-Type': 'application/x-www-form-urlencoded',
          Accept: 'application/json',
          'X-Forwarded-Host': forwardedHost,
          'X-Forwarded-Proto': new URL(cfg.issuer).protocol.replace(':', ''),
        },
        body: new URLSearchParams({
          grant_type: TOKEN_EXCHANGE_GRANT,
          subject_token: accessToken,
          subject_token_type: ACCESS_TOKEN_TYPE,
          resource: cfg.resource,
          audience: 'agentboxd-api',
        }),
        signal: AbortSignal.timeout(10_000),
      });
    } catch {
      return { ok: false, kind: 'unavailable', description: 'the authorization server is unreachable' };
    }
    const body = (await res.json().catch(() => null)) as Record<string, unknown> | null;
    if (res.ok && body && typeof body.access_token === 'string' && typeof body.grant_id === 'string') {
      return { ok: true, token: body.access_token, grantId: body.grant_id, clientId: String(body.client_id ?? '') };
    }
    if (res.status === 400 && body?.error === 'invalid_grant') {
      return { ok: false, kind: 'invalid', description: 'the access token is invalid, expired or revoked' };
    }
    // Anything else is our fault (misconfigured secret, server error): don't make the client sign in again.
    return { ok: false, kind: 'unavailable', description: `token exchange failed (HTTP ${res.status}${body?.error ? ` ${String(body.error)}` : ''})` };
  };
}

// ---------- rate limit ----------

/** Fixed one-minute windows per grant, in process (the API also limits per grant across replicas). */
export class GrantRateLimiter {
  private windows = new Map<string, { window: number; count: number }>();
  constructor(
    private readonly limit: number,
    private readonly now: () => number = Date.now,
  ) {}

  /** Seconds until the window resets when over the limit, else 0. */
  take(grantId: string): number {
    const window = Math.floor(this.now() / 60_000);
    const w = this.windows.get(grantId);
    const entry = w && w.window === window ? w : { window, count: 0 };
    entry.count++;
    this.windows.set(grantId, entry);
    if (this.windows.size > 10_000) for (const [k, v] of this.windows) if (v.window !== window) this.windows.delete(k);
    return entry.count > this.limit ? 60 - (Math.floor(this.now() / 1000) % 60) : 0;
  }
}

// ---------- HTTP handler ----------

export interface HostedDeps {
  exchange?: Exchanger;
  /** fetch used by the per-request API client (tests). */
  fetch?: typeof fetch;
  /** One JSON line per request; never tokens, arguments or results. */
  log?: (entry: Record<string, unknown>) => void;
  now?: () => number;
}

class BodyTooLarge extends Error {}

async function readBody(req: IncomingMessage, max: number): Promise<Buffer> {
  const declared = Number(req.headers['content-length'] ?? '0');
  if (declared > max) throw new BodyTooLarge();
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > max) throw new BodyTooLarge();
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks);
}

function json(res: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...headers }).end(JSON.stringify(body));
}

const rpcError = (code: number, message: string) => ({ jsonrpc: '2.0', error: { code, message }, id: null });

/** What to log about a JSON-RPC body: the method and, for tools/call, the tool name. Nothing else. */
function describeRpc(body: unknown): { rpc?: string; tool?: string } {
  if (Array.isArray(body)) return { rpc: 'batch' };
  if (!body || typeof body !== 'object') return {};
  const m = (body as { method?: unknown }).method;
  const name = (body as { params?: { name?: unknown } }).params?.name;
  return {
    rpc: typeof m === 'string' ? m.slice(0, 64) : undefined,
    tool: m === 'tools/call' && typeof name === 'string' ? name.slice(0, 64) : undefined,
  };
}

const CORS_ALLOW_HEADERS = 'Authorization, Content-Type, Accept, Mcp-Session-Id, MCP-Protocol-Version, Mcp-Method, Mcp-Name, Last-Event-ID';
const CORS_EXPOSE_HEADERS = 'WWW-Authenticate, Mcp-Session-Id, MCP-Protocol-Version';

export function createHostedHandler(cfg: HostedConfig, deps: HostedDeps = {}) {
  const exchange = deps.exchange ?? httpExchanger(cfg);
  const log = deps.log ?? ((e) => process.stdout.write(`${JSON.stringify(e)}\n`));
  const now = deps.now ?? Date.now;
  const limiter = new GrantRateLimiter(cfg.rateLimitPerMinute, now);
  const endpoint = mcpPath(cfg);
  const prmPaths = new Set(['/.well-known/oauth-protected-resource', `/.well-known/oauth-protected-resource${endpoint}`]);
  const allowedOrigins = new Set(cfg.allowedOrigins);
  const allowedHosts = new Set(cfg.allowedHosts);

  return async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const started = now();
    const path = new URL(req.url ?? '/', 'http://localhost').pathname;
    const entry: Record<string, unknown> = { msg: 'mcp request', method: req.method, path };
    // The compose healthcheck polls /health every 15 s: not worth a log line.
    if (path === '/health' && req.method === 'GET') return json(res, 200, { status: 'ok' });
    res.on('finish', () => log({ t: new Date(now()).toISOString(), ...entry, status: res.statusCode, ms: now() - started }));

    if (prmPaths.has(path)) {
      const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET, OPTIONS' };
      if (req.method === 'OPTIONS') return void res.writeHead(204, { ...cors, 'Access-Control-Max-Age': '600' }).end();
      if (req.method !== 'GET') return json(res, 405, { error: 'method_not_allowed' }, { Allow: 'GET', ...cors });
      return json(res, 200, protectedResourceMetadata(cfg), { ...cors, 'Cache-Control': 'public, max-age=300' });
    }

    if (path !== endpoint) return json(res, 404, { error: 'not_found', error_description: `the MCP endpoint is ${endpoint}` });

    // DNS rebinding: only our own Host, and browser origins we know.
    const host = String(req.headers.host ?? '').toLowerCase();
    if (!allowedHosts.has(host)) return json(res, 421, rpcError(-32000, 'Misdirected request: unknown Host'));
    const origin = typeof req.headers.origin === 'string' ? req.headers.origin : undefined;
    if (origin !== undefined && !allowedOrigins.has(origin)) return json(res, 403, rpcError(-32000, 'Forbidden: Origin not allowed'));
    const cors: Record<string, string> = origin
      ? { 'Access-Control-Allow-Origin': origin, Vary: 'Origin', 'Access-Control-Expose-Headers': CORS_EXPOSE_HEADERS }
      : {};
    if (req.method === 'OPTIONS') {
      return void res
        .writeHead(204, { ...cors, 'Access-Control-Allow-Methods': 'POST, OPTIONS', 'Access-Control-Allow-Headers': CORS_ALLOW_HEADERS, 'Access-Control-Max-Age': '600' })
        .end();
    }
    for (const [k, v] of Object.entries(cors)) res.setHeader(k, v);
    // Stateless (2026-07-28 shape): no standalone SSE stream, no sessions to delete.
    if (req.method !== 'POST') return json(res, 405, rpcError(-32000, 'Method not allowed: POST JSON-RPC messages to this endpoint'), { Allow: 'POST, OPTIONS' });

    let raw: Buffer;
    try {
      raw = await readBody(req, cfg.maxBodyBytes);
    } catch (err) {
      if (err instanceof BodyTooLarge) return json(res, 413, rpcError(-32000, `Request body larger than ${cfg.maxBodyBytes} bytes`));
      throw err;
    }
    let body: unknown;
    try {
      body = JSON.parse(raw.toString('utf8'));
    } catch {
      return json(res, 400, rpcError(-32700, 'Parse error: the body is not valid JSON'));
    }
    Object.assign(entry, describeRpc(body));

    // Authentication: Bearer header only (never a query parameter). Every MCP method needs it.
    const auth = req.headers.authorization;
    const bearer = typeof auth === 'string' ? /^Bearer\s+([A-Za-z0-9._~+/=-]+)$/i.exec(auth.trim())?.[1] : undefined;
    if (!bearer) {
      return json(res, 401, { error: 'invalid_token', error_description: 'sign in to Agentboxd to use this MCP server' }, { 'WWW-Authenticate': wwwAuthenticate(cfg) });
    }
    const exchanged = await exchange(bearer);
    if (!exchanged.ok) {
      if (exchanged.kind === 'unavailable') {
        entry.error = exchanged.description;
        return json(res, 503, rpcError(-32000, 'Agentboxd is temporarily unavailable; try again shortly'), { 'Retry-After': '5' });
      }
      return json(res, 401, { error: 'invalid_token', error_description: exchanged.description }, {
        'WWW-Authenticate': wwwAuthenticate(cfg, { code: 'invalid_token', description: exchanged.description }),
      });
    }
    entry.grant = exchanged.grantId;
    entry.client = exchanged.clientId;

    const retryAfter = limiter.take(exchanged.grantId);
    if (retryAfter) return json(res, 429, rpcError(-32000, 'Rate limit exceeded for this connection'), { 'Retry-After': String(retryAfter) });

    const client = new Agentboxd({ apiKey: exchanged.token, baseUrl: cfg.internalUrl, fetch: deps.fetch });
    const server = createAgentboxdMcpServer(client, { hosted: true });
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
    res.on('close', () => {
      void transport.close();
      void server.close();
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, body);
  };
}
