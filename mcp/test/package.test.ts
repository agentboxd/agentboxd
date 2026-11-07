import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { describe, expect, it } from 'vitest';
import { API_KEY_ENV, BASE_URL_ENV } from '../src/config.js';
import { createAgentboxdMcpServer, SERVER_NAME, SERVER_VERSION, TOOL_NAMES } from '../src/server.js';

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

/** README "Tools" rows: name → the parameter list it shows (`{ a, b? }`), or the tool it says it is the same as. */
function readmeToolRows(): Map<string, { params?: { name: string; optional: boolean }[]; sameAs?: string }> {
  const readme = readFileSync(new URL('../README.md', import.meta.url), 'utf8');
  const section = readme.slice(readme.indexOf('\n## Tools\n'), readme.indexOf('\n## ', readme.indexOf('\n## Tools\n') + 1));
  const rows = new Map<string, { params?: { name: string; optional: boolean }[]; sameAs?: string }>();
  for (const line of section.split('\n')) {
    const m = /^\| `([a-z_]+)` \| (.*?) \|/.exec(line);
    if (!m) continue;
    const [, name, what] = m as unknown as [string, string, string];
    const list = /^`\{([^}`]*)\}`/.exec(what);
    const same = /^Same as `([a-z_]+)`/.exec(what);
    rows.set(name, {
      ...(list && {
        params: list[1]!
          .replace(/\([^)]*\)/g, '') // "(1-60, default 30)"
          .split(',')
          .map((p) => p.trim())
          .filter(Boolean)
          .map((p) => ({ name: p.replace(/\?$/, ''), optional: p.endsWith('?') })),
      }),
      ...(same && { sameAs: same[1] }),
    });
  }
  return rows;
}

describe('README tool table', () => {
  it('has a row per tool, listing exactly the parameters the tool takes, optional ones marked "?"', async () => {
    const server = createAgentboxdMcpServer(null); // keyless, so signup is listed too
    const [ct, st] = InMemoryTransport.createLinkedPair();
    const client = new Client({ name: 'readme-check', version: '0.0.0' });
    await Promise.all([server.connect(st), client.connect(ct)]);
    const { tools } = await client.listTools();
    await client.close();
    const schemas = new Map(tools.map((t) => [t.name, t.inputSchema]));
    const show = (params: { name: string; optional: boolean }[]) =>
      `{ ${params
        .map((p) => `${p.name}${p.optional ? '?' : ''}`)
        .sort()
        .join(', ')} }`;
    const shape = (name: string) => {
      const s = schemas.get(name);
      if (!s) return 'no such tool';
      const required = new Set(s.required ?? []);
      return show(Object.keys(s.properties ?? {}).map((p) => ({ name: p, optional: !required.has(p) })));
    };

    const rows = readmeToolRows();
    const problems: string[] = [];
    for (const name of TOOL_NAMES) if (!rows.has(name)) problems.push(`${name}: no row`);
    for (const [name, row] of rows) {
      const tool = shape(name);
      if (row.sameAs) {
        if (tool !== shape(row.sameAs)) problems.push(`${name}: "Same as ${row.sameAs}", but it takes ${tool}`);
      } else if (!row.params) {
        problems.push(`${name}: the row should start with its parameters, e.g. \`{ inbox_id, limit? }\``);
      } else if (show(row.params) !== tool) {
        problems.push(`${name}: README lists ${show(row.params)}, the tool takes ${tool}`);
      }
    }
    expect(problems).toEqual([]);
  });
});
