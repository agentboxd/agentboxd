#!/usr/bin/env node
/**
 * Builds the `agentboxd` package: an ES module build (dist/esm) and a CommonJS build (dist/cjs), each
 * with its own .d.ts. dist/cjs gets a {"type":"commonjs"} package.json so Node and TypeScript read
 * those files as CommonJS even though the package itself is "type": "module".
 * No dependencies beyond `typescript`.
 */
import { execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const tsc = createRequire(import.meta.url).resolve('typescript/bin/tsc');
const run = (project) => execFileSync(process.execPath, [tsc, '-p', project], { cwd: root, stdio: 'inherit' });

rmSync(path.join(root, 'dist'), { recursive: true, force: true });
run('tsconfig.json');
run('tsconfig.cjs.json');
mkdirSync(path.join(root, 'dist/cjs'), { recursive: true });
writeFileSync(path.join(root, 'dist/cjs/package.json'), JSON.stringify({ type: 'commonjs' }, null, 2) + '\n');
console.log('built dist/esm and dist/cjs');
