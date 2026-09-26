/**
 * Checks the OpenClaw files in this folder without running OpenClaw:
 *  - openclaw.json has an `mcp.servers.agentboxd` stdio entry (command, args, env) as OpenClaw's config expects;
 *  - skills/agentboxd-email/SKILL.md has the frontmatter OpenClaw reads (`name`, `description`, and a
 *    `metadata.openclaw` block that parses as JSON), a name that matches its folder, and names only tools
 *    the Agentboxd MCP server really has.
 *
 *   npx tsx openclaw/validate.ts       (from examples/guides; `npm run openclaw:check`)
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const here = new URL('./', import.meta.url);
const read = (p: string, base: URL = here) => readFileSync(new URL(p, base), 'utf8').replace(/\r\n/g, '\n');

// ---- openclaw.json: the mcp.servers entry (`openclaw mcp set agentboxd '<json>'` writes the same) ----
interface StdioServer {
  command: string;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
}
const config = JSON.parse(read('openclaw.json')) as { mcp?: { servers?: Record<string, StdioServer> } };
const server = config.mcp?.servers?.agentboxd;
assert.ok(server, 'openclaw.json: mcp.servers.agentboxd is missing');
assert.equal(server.command, 'npx');
assert.deepEqual(server.args, ['-y', '@agentboxd/mcp']);
assert.ok(server.env && 'AGENTBOXD_API_KEY' in server.env, 'openclaw.json: env.AGENTBOXD_API_KEY is missing');
assert.ok(!/^mr_[A-Za-z0-9]{40}$/.test(server.env.AGENTBOXD_API_KEY ?? ''), 'openclaw.json must hold a placeholder, never a real key');
const allowedKeys = new Set(['command', 'args', 'env', 'cwd', 'workingDirectory']);
for (const k of Object.keys(server)) assert.ok(allowedKeys.has(k), `openclaw.json: unknown stdio field "${k}"`);

// ---- SKILL.md: YAML frontmatter with a JSON metadata block ----
const skill = read('skills/agentboxd-email/SKILL.md');
const fm = /^---\n([\s\S]*?)\n---\n/.exec(skill);
assert.ok(fm, 'SKILL.md: missing --- frontmatter ---');
const front = fm[1]!;
const field = (key: string) => new RegExp(`^${key}: (.+)$`, 'm').exec(front)?.[1]?.trim();
assert.equal(field('name'), 'agentboxd-email', 'SKILL.md: name must match the folder name');
const description = field('description') ?? '';
assert.ok(description.length > 20 && description.length <= 300, 'SKILL.md: description should be one clear sentence');
const metaStart = front.indexOf('metadata:');
assert.ok(metaStart >= 0, 'SKILL.md: metadata block is missing');
// OpenClaw's example writes the metadata as a JSON object (with an optional trailing comma).
const metaJson = front.slice(metaStart + 'metadata:'.length).trim().replace(/,(\s*})/g, '$1');
const metadata = JSON.parse(metaJson) as { openclaw?: { requires?: { bins?: string[]; env?: string[] } } };
assert.ok(metadata.openclaw, 'SKILL.md: metadata.openclaw is missing');
assert.deepEqual(metadata.openclaw.requires?.bins, ['npx']);

// Every tool the skill names must exist in the MCP server (its MCPB manifest lists them all).
const manifest = JSON.parse(read('../../../mcp/mcpb/manifest.json')) as { tools: { name: string }[] };
const tools = new Set(manifest.tools.map((t) => t.name));
const named = [...skill.matchAll(/`([a-z]+(?:_[a-z]+)+)`/g)].map((m) => m[1]!).filter((n) => n !== 'client_id');
assert.ok(named.length >= 8, 'SKILL.md should name the tools it uses');
for (const n of named) assert.ok(tools.has(n), `SKILL.md names "${n}", which the MCP server doesn't have`);

console.log(`openclaw ok: mcp.servers.agentboxd (${server.command} ${server.args?.join(' ')}), skill "${field('name')}" using ${new Set(named).size} tools`);
