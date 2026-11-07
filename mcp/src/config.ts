import { DEFAULT_MAX_BODY_BYTES } from './httpBody.js';

export const DEFAULT_AGENTBOXD_URL = 'https://api.agentboxd.com';

/** Env vars read for the API key / base URL, in priority order (the MAILROOM_* names are legacy fallbacks). */
export const API_KEY_ENV = ['AGENTBOXD_API_KEY', 'MAILROOM_API_KEY'] as const;
export const BASE_URL_ENV = ['AGENTBOXD_BASE_URL', 'MAILROOM_URL'] as const;

export interface Config {
  /**
   * Undefined = keyless start: every tool answers no_api_key until the agent calls `signup`, which
   * creates a workspace and hands the new key to the running server.
   */
  apiKey?: string;
  /** --save-key=<path>: signup writes the new key there, and a keyless start reads it back. */
  saveKeyPath?: string;
  baseUrl: string;
  /** Streamable HTTP port; undefined = stdio. */
  httpPort?: number;
  httpHost: string;
  /** Host header values HTTP mode answers (lowercase, with the port); MCP_HTTP_ALLOWED_HOSTS adds more. */
  httpAllowedHosts: string[];
  /** Browser origins HTTP mode accepts besides pages on this machine (MCP_HTTP_ALLOWED_ORIGINS). */
  httpAllowedOrigins: string[];
  /** Largest request body HTTP mode reads (MCP_MAX_BODY_BYTES, default 4 MiB); a larger one gets 413. */
  maxBodyBytes: number;
}

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigError';
  }
}

/** A positive integer env value, or `fallback` when it is unset or blank. */
export function positiveInt(name: string, raw: string | undefined, fallback: number): number {
  if (!raw?.trim()) return fallback;
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 1) throw new ConfigError(`${name} must be a positive integer`);
  return n;
}

/** First non-blank value among `names`, with the name it came from. */
function firstEnv(env: NodeJS.ProcessEnv, names: readonly string[]): { name: string; value: string } | undefined {
  for (const name of names) {
    const value = env[name]?.trim();
    if (value) return { name, value };
  }
  return undefined;
}

/** The key in a --save-key file: `AGENTBOXD_API_KEY=mr_...` (or just the key on its own line). */
export function parseKeyFile(text: string): string | undefined {
  for (const line of text.split(/\r?\n/)) {
    const v = line
      .trim()
      .replace(/^(?:AGENTBOXD_API_KEY|MAILROOM_API_KEY)\s*=\s*/, '')
      .replace(/^["']|["']$/g, '');
    if (/^mr_[A-Za-z0-9]{20,}$/.test(v)) return v;
  }
  return undefined;
}

/** Names this machine answers to; a page served from one of them (any port) is local, not a remote site. */
const LOOPBACK_NAMES = ['localhost', '127.0.0.1', '[::1]'];
/** MCP_HTTP_HOST values that mean every interface rather than one name. */
const ANY_ADDRESS = new Set(['0.0.0.0', '::', '[::]']);

const list = (raw: string | undefined) =>
  (raw ?? '')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);

/**
 * DNS rebinding guard for HTTP mode. A web page can point its own name at 127.0.0.1 and then reach the local
 * port as if it were its own site, so the Host header must be one this server answers to, and an Origin, when
 * a browser sends one, must be a page on this machine or listed in MCP_HTTP_ALLOWED_ORIGINS. Clients that are
 * not browsers send no Origin. Returns why the request is refused, or undefined to serve it.
 */
export function refuseHttpRequest(
  config: Pick<Config, 'httpAllowedHosts' | 'httpAllowedOrigins'>,
  host: string | undefined,
  origin: string | undefined,
): string | undefined {
  if (!host || !config.httpAllowedHosts.includes(host.toLowerCase())) {
    return 'Forbidden: Host not allowed. Set MCP_HTTP_ALLOWED_HOSTS to add it.';
  }
  if (origin === undefined || config.httpAllowedOrigins.includes(origin.toLowerCase())) return undefined;
  try {
    const url = new URL(origin);
    if ((url.protocol === 'http:' || url.protocol === 'https:') && LOOPBACK_NAMES.includes(url.hostname)) return undefined;
  } catch {
    // "null" (a sandboxed page or a local file) or not a URL at all.
  }
  return 'Forbidden: Origin not allowed. Set MCP_HTTP_ALLOWED_ORIGINS to add it.';
}

/** Reads a file if it exists (injected in tests). */
export type ReadFile = (path: string) => string | undefined;

/**
 * AGENTBOXD_API_KEY (legacy MAILROOM_API_KEY) wins. Without it the server still starts: with --save-key
 * it reads the key a previous signup saved there, else it runs keyless and offers the signup tool.
 */
export function loadConfig(
  env: NodeJS.ProcessEnv = process.env,
  argv: string[] = process.argv.slice(2),
  readFile: ReadFile = () => undefined,
): Config {
  const saveArg = argv.findIndex((a) => a === '--save-key' || a.startsWith('--save-key='));
  let saveKeyPath: string | undefined;
  if (saveArg >= 0) {
    const a = argv[saveArg]!;
    saveKeyPath = (a.includes('=') ? a.slice('--save-key='.length) : argv[saveArg + 1])?.trim() || undefined;
    if (!saveKeyPath || saveKeyPath.startsWith('--')) throw new ConfigError('--save-key needs a file path: --save-key=/path/to/agentboxd.env');
  }
  let apiKey = firstEnv(env, API_KEY_ENV)?.value;
  if (!apiKey && saveKeyPath) {
    const text = readFile(saveKeyPath);
    apiKey = text === undefined ? undefined : parseKeyFile(text);
  }
  const urlVar = firstEnv(env, BASE_URL_ENV);
  const baseUrl = (urlVar?.value ?? DEFAULT_AGENTBOXD_URL).replace(/\/+$/, '');
  try {
    new URL(baseUrl);
  } catch {
    throw new ConfigError(`${urlVar?.name ?? 'AGENTBOXD_BASE_URL'} is not a valid URL: ${baseUrl}`);
  }

  let httpPort: number | undefined;
  const portArg = argv.find((a) => a.startsWith('--port='))?.slice('--port='.length);
  const rawPort = portArg ?? env.MCP_HTTP_PORT?.trim();
  if (rawPort) {
    httpPort = Number(rawPort);
    if (!Number.isInteger(httpPort) || httpPort < 1 || httpPort > 65535) {
      throw new ConfigError(`Invalid HTTP port: ${rawPort}`);
    }
  } else if (argv.includes('--http')) {
    httpPort = 3333;
  }

  const httpHost = env.MCP_HTTP_HOST?.trim() || '127.0.0.1';
  const names = [...LOOPBACK_NAMES];
  const ownName = (httpHost.includes(':') && !httpHost.startsWith('[') ? `[${httpHost}]` : httpHost).toLowerCase();
  if (!ANY_ADDRESS.has(ownName) && !names.includes(ownName)) names.push(ownName);
  const httpAllowedHosts =
    httpPort === undefined
      ? []
      : [
          ...names.map((n) => `${n}:${httpPort}`),
          // Browsers leave the default port out of Host.
          ...(httpPort === 80 ? names : []),
          ...list(env.MCP_HTTP_ALLOWED_HOSTS),
        ];
  const httpAllowedOrigins = list(env.MCP_HTTP_ALLOWED_ORIGINS).map((o) => o.replace(/\/+$/, ''));
  // Read only in HTTP mode: stdio has no request bodies, so a stray value there must not stop the server.
  const maxBodyBytes = httpPort === undefined ? DEFAULT_MAX_BODY_BYTES : positiveInt('MCP_MAX_BODY_BYTES', env.MCP_MAX_BODY_BYTES, DEFAULT_MAX_BODY_BYTES);

  return { apiKey, saveKeyPath, baseUrl, httpPort, httpHost, httpAllowedHosts, httpAllowedOrigins, maxBodyBytes };
}
