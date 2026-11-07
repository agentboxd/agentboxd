/**
 * The hosted remote MCP server (https://mcp.agentboxd.com/mcp): an OAuth 2.1 protected resource in front
 * of the same tools as the npm package. See docs/remote-mcp-contract.md §2 and §5.
 *
 * Per request: Host and Origin checks (DNS rebinding) → a Bearer header (else 401) → a declared body over the limit
 * gets 413 → per-grant rate limit for a token already known from an earlier exchange (429, no exchange) → the Bearer
 * access token is exchanged at the authorization server for a short-lived API token (the person's token never
 * reaches the API; else 401 or 503) → per-grant rate limit for a token that was not known → only then is the body
 * read and parsed; a JSON-RPC batch counts each of its messages against the limit → a fresh stateless MCP server whose
 * tools call the API with that token.
 */
import { createHash } from 'node:crypto';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { Agentboxd } from '../../sdk/src/index.js';
import { ConfigError, positiveInt } from './config.js';
import { BodyTooLarge, declaresMoreThan, DEFAULT_MAX_BODY_BYTES, readBody } from './httpBody.js';
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
    maxBodyBytes: positiveInt('MCP_MAX_BODY_BYTES', env.MCP_MAX_BODY_BYTES, DEFAULT_MAX_BODY_BYTES),
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
  /** `expiresIn`: seconds the service token lives (`expires_in`), never past the access token's own expiry. */
  | { ok: true; token: string; grantId: string; clientId: string; expiresIn?: number }
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
      const expiresIn = typeof body.expires_in === 'number' && body.expires_in > 0 ? body.expires_in : undefined;
      return { ok: true, token: body.access_token, grantId: body.grant_id, clientId: String(body.client_id ?? ''), ...(expiresIn !== undefined && { expiresIn }) };
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

  /** Counts `n` requests (one, or the messages of a JSON-RPC batch). Seconds until the window resets when over the limit, else 0. */
  take(grantId: string, n = 1): number {
    const window = Math.floor(this.now() / 60_000);
    const w = this.windows.get(grantId);
    const entry = w && w.window === window ? w : { window, count: 0 };
    entry.count += n;
    this.windows.set(grantId, entry);
    if (this.windows.size > 10_000) for (const [k, v] of this.windows) if (v.window !== window) this.windows.delete(k);
    return entry.count > this.limit ? this.secondsToReset() : 0;
  }

  /**
   * Takes back one request that `take` let through in this window, because it ended before it was served (its token
   * exchange failed). Nothing to take back once the window has changed.
   */
  refund(grantId: string): void {
    const w = this.windows.get(grantId);
    if (w && w.window === Math.floor(this.now() / 60_000) && w.count > 0) w.count--;
  }

  private secondsToReset(): number {
    return 60 - (Math.floor(this.now() / 1000) % 60);
  }
}

/** How long a token is remembered when the exchange gave no lifetime, and the most it is ever remembered. */
const KNOWN_TOKEN_DEFAULT_SECONDS = 60;
const KNOWN_TOKEN_MAX_SECONDS = 300;

/**
 * The grant behind each access token that was exchanged successfully, so a request is counted against its
 * connection's minute before the exchange, and one past the limit costs no exchange. Keyed by the token's SHA-256 (the token
 * itself is never kept). An entry lasts as long as the service token its exchange returned (at most 5 minutes,
 * never past the access token's expiry); past `max` entries the oldest go first. Only successful exchanges add
 * entries, so made-up tokens can't grow it.
 */
export class KnownTokens {
  private entries = new Map<string, { grantId: string; clientId: string; until: number }>();
  constructor(
    private readonly max = 10_000,
    private readonly now: () => number = Date.now,
  ) {}

  private static key(token: string): string {
    return createHash('sha256').update(token).digest('base64url');
  }

  get(token: string): { grantId: string; clientId: string } | undefined {
    const key = KnownTokens.key(token);
    const e = this.entries.get(key);
    if (!e) return undefined;
    if (e.until <= this.now()) {
      this.entries.delete(key);
      return undefined;
    }
    return { grantId: e.grantId, clientId: e.clientId };
  }

  remember(token: string, grantId: string, clientId: string, expiresIn: number | undefined): void {
    const key = KnownTokens.key(token);
    const seconds = Math.min(expiresIn ?? KNOWN_TOKEN_DEFAULT_SECONDS, KNOWN_TOKEN_MAX_SECONDS);
    this.entries.delete(key); // re-inserted last, so the oldest stay first in line to go
    this.entries.set(key, { grantId, clientId, until: this.now() + seconds * 1000 });
    for (const oldest of this.entries.keys()) {
      if (this.entries.size <= this.max) break;
      this.entries.delete(oldest);
    }
  }

  forget(token: string): void {
    this.entries.delete(KnownTokens.key(token));
  }

  get size(): number {
    return this.entries.size;
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

function json(res: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}) {
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...headers }).end(JSON.stringify(body));
}

const rpcError = (code: number, message: string) => ({ jsonrpc: '2.0', error: { code, message }, id: null });

/** The most messages of a batch whose methods are logged: the MCP SDK refuses larger batches anyway. */
const MAX_LOGGED_BATCH = 100;

/** The method of one JSON-RPC message and, for tools/call, the tool name. */
function describeMessage(body: unknown): { rpc?: string; tool?: string } {
  if (!body || typeof body !== 'object') return {};
  const m = (body as { method?: unknown }).method;
  const name = (body as { params?: { name?: unknown } }).params?.name;
  return {
    rpc: typeof m === 'string' ? m.slice(0, 64) : undefined,
    tool: m === 'tools/call' && typeof name === 'string' ? name.slice(0, 64) : undefined,
  };
}

/**
 * What to log about a JSON-RPC body: the method and, for tools/call, the tool name; for a batch, its size and the
 * method (and tool) of each message, in order (a message without a method, such as a response, shows null). Nothing else.
 */
export function describeRpc(body: unknown): { rpc?: string; tool?: string; batch?: number; methods?: (string | null)[]; tools?: string[] } {
  if (!Array.isArray(body)) return describeMessage(body);
  const each = body.slice(0, MAX_LOGGED_BATCH).map(describeMessage);
  const tools = each.flatMap((d) => (d.tool ? [d.tool] : []));
  return { rpc: 'batch', batch: body.length, methods: each.map((d) => d.rpc ?? null), ...(tools.length ? { tools } : {}) };
}

const CORS_ALLOW_HEADERS = 'Authorization, Content-Type, Accept, Mcp-Session-Id, MCP-Protocol-Version, Mcp-Method, Mcp-Name, Last-Event-ID';
const CORS_EXPOSE_HEADERS = 'WWW-Authenticate, Mcp-Session-Id, MCP-Protocol-Version';

export function createHostedHandler(cfg: HostedConfig, deps: HostedDeps = {}) {
  const exchange = deps.exchange ?? httpExchanger(cfg);
  const log = deps.log ?? ((e) => process.stdout.write(`${JSON.stringify(e)}\n`));
  const now = deps.now ?? Date.now;
  const limiter = new GrantRateLimiter(cfg.rateLimitPerMinute, now);
  const known = new KnownTokens(10_000, now);
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

    // Authentication: Bearer header only (never a query parameter). Every MCP method needs it, so a request
    // without one gets its 401 before its body is read.
    const auth = req.headers.authorization;
    const bearer = typeof auth === 'string' ? /^Bearer\s+([A-Za-z0-9._~+/=-]+)$/i.exec(auth.trim())?.[1] : undefined;
    if (!bearer) {
      return json(res, 401, { error: 'invalid_token', error_description: 'sign in to Agentboxd to use this MCP server' }, { 'WWW-Authenticate': wwwAuthenticate(cfg) });
    }
    if (declaresMoreThan(req, cfg.maxBodyBytes)) return json(res, 413, rpcError(-32000, new BodyTooLarge(cfg.maxBodyBytes).message));

    // The body is read only after the token is exchanged and the request counted against its connection's minute:
    // a made-up token gets its 401 with the body unread, and a body sent slowly can't keep a request past the limit.
    // A token known from an earlier exchange is counted before the exchange, so past the limit it costs none, even
    // for requests sent all at once. A failed exchange takes the request back: only requests whose token is
    // exchanged count, as for a token that is not known yet.
    const tooMany = (retryAfter: number) =>
      json(res, 429, rpcError(-32000, 'Rate limit exceeded for this connection'), { 'Retry-After': String(retryAfter) });
    const seen = known.get(bearer);
    if (seen) {
      const retryAfter = limiter.take(seen.grantId);
      if (retryAfter) {
        entry.grant = seen.grantId;
        entry.client = seen.clientId;
        return tooMany(retryAfter);
      }
    }

    const exchanged = await exchange(bearer);
    if (!exchanged.ok) {
      if (seen) limiter.refund(seen.grantId);
      if (exchanged.kind === 'unavailable') {
        entry.error = exchanged.description;
        return json(res, 503, rpcError(-32000, 'Agentboxd is temporarily unavailable; try again shortly'), { 'Retry-After': '5' });
      }
      known.forget(bearer);
      return json(res, 401, { error: 'invalid_token', error_description: exchanged.description }, {
        'WWW-Authenticate': wwwAuthenticate(cfg, { code: 'invalid_token', description: exchanged.description }),
      });
    }
    entry.grant = exchanged.grantId;
    entry.client = exchanged.clientId;
    known.remember(bearer, exchanged.grantId, exchanged.clientId, exchanged.expiresIn);
    if (seen?.grantId !== exchanged.grantId) {
      if (seen) limiter.refund(seen.grantId);
      const retryAfter = limiter.take(exchanged.grantId);
      if (retryAfter) return tooMany(retryAfter);
    }

    // Counted from here on, malformed or not: a request that cost an exchange always counts.
    let raw: Buffer;
    try {
      raw = await readBody(req, cfg.maxBodyBytes);
    } catch (err) {
      if (err instanceof BodyTooLarge) return json(res, 413, rpcError(-32000, err.message));
      throw err;
    }
    let body: unknown;
    try {
      body = JSON.parse(raw.toString('utf8'));
    } catch {
      return json(res, 400, rpcError(-32700, 'Parse error: the body is not valid JSON'));
    }
    Object.assign(entry, describeRpc(body));
    // A JSON-RPC batch (protocol 2025-03-26, which the SDK still accepts) runs each of its messages: it counts as that
    // many requests, so up to 100 tool calls can't ride on one. The request itself was counted above.
    if (Array.isArray(body) && body.length > 1) {
      const retryAfter = limiter.take(exchanged.grantId, body.length - 1);
      if (retryAfter) return tooMany(retryAfter);
    }

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
