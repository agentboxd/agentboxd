#!/usr/bin/env node
/**
 * Builds an MCPB bundle directory for @agentboxd/mcp (Claude Desktop one-click install, Smithery
 * "Local (MCPB bundle)" publishing). Unlike the npm build, every dependency is inlined, so the bundle
 * runs with nothing but Node.
 *
 *   npm run build:mcpb            # → build/mcpb/ (manifest.json, server/index.cjs, icon.png, ...)
 *   npm run build:mcpb -- --pack  # also runs `npx @anthropic-ai/mcpb pack` → build/agentboxd-<version>.mcpb
 */
import { execFileSync } from 'node:child_process';
import { copyFileSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = path.join(root, 'build/mcpb');
const pkg = JSON.parse(readFileSync(path.join(root, 'package.json'), 'utf8'));

rmSync(out, { recursive: true, force: true });
mkdirSync(path.join(out, 'server'), { recursive: true });

await build({
  entryPoints: [path.join(root, 'src/index.ts')],
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node20',
  outfile: path.join(out, 'server/index.cjs'),
  legalComments: 'eof',
  logLevel: 'warning',
});

const manifest = JSON.parse(readFileSync(path.join(root, 'mcpb/manifest.json'), 'utf8'));
manifest.version = pkg.version;
writeFileSync(path.join(out, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
copyFileSync(path.join(root, 'mcpb/icon.png'), path.join(out, 'icon.png'));
for (const f of ['README.md', 'LICENSE']) copyFileSync(path.join(root, f), path.join(out, f));
console.log(`MCPB directory ready: ${path.relative(root, out)} (version ${pkg.version})`);

if (process.argv.includes('--pack')) {
  const file = path.join(root, 'build', `agentboxd-${pkg.version}.mcpb`);
  const npx = process.platform === 'win32' ? 'npx.cmd' : 'npx';
  execFileSync(npx, ['-y', '@anthropic-ai/mcpb', 'pack', out, file], { stdio: 'inherit', shell: process.platform === 'win32' });
  console.log(`packed ${path.relative(root, file)}`);
}
