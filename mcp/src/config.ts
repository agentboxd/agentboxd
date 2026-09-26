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
}

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigError';
  }
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

  return { apiKey, saveKeyPath, baseUrl, httpPort, httpHost: env.MCP_HTTP_HOST?.trim() || '127.0.0.1' };
}
