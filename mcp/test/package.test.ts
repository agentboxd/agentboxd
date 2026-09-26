import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { describe, expect, it } from 'vitest';
import { API_KEY_ENV, BASE_URL_ENV } from '../src/config.js';
import { SERVER_NAME, SERVER_VERSION, TOOL_NAMES } from '../src/server.js';

const read = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8')) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const pkg = read('../package.json');
const serverJson = read('../server.json');
const manifest = read('../mcpb/manifest.json');

describe('publishing metadata stays in sync', () => {
  it('server.json (MCP Registry) matches package.json', () => {
    expect(serverJson.name).toBe(pkg.mcpName);
    expect(serverJson.version).toBe(pkg.version);
    expect(serverJson.description.length).toBeLessThanOrEqual(100);
    const [npm] = serverJson.packages;
    expect(npm).toMatchObject({ registryType: 'npm', identifier: pkg.name, version: pkg.version, transport: { type: 'stdio' } });
    expect(npm.environmentVariables.map((v: { name: string }) => v.name)).toEqual([API_KEY_ENV[0], BASE_URL_ENV[0]]);
  });

  it('the MCPB manifest lists every tool and passes the primary env vars', () => {
    expect(manifest.name).toBe(SERVER_NAME);
    expect(manifest.tools.map((t: { name: string }) => t.name)).toEqual([...TOOL_NAMES]);
    expect(Object.keys(manifest.server.mcp_config.env)).toEqual([API_KEY_ENV[0], BASE_URL_ENV[0]]);
  });

  it('the stdio smoke script expects exactly the registered tools', async () => {
    const url = pathToFileURL(fileURLToPath(new URL('../scripts/smoke-stdio.mjs', import.meta.url))).href;
    const { EXPECTED_TOOLS } = (await import(url)) as { EXPECTED_TOOLS: string[] };
    expect([...EXPECTED_TOOLS].sort()).toEqual([...TOOL_NAMES].sort());
  });

  it('the npm bin and version are what the docs promise', () => {
    expect(pkg.bin).toEqual({ 'agentboxd-mcp': 'dist/index.js' });
    expect(SERVER_VERSION).toBe(pkg.version);
    expect(pkg.publishConfig.access).toBe('public');
  });
});
