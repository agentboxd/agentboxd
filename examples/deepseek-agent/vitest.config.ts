import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// Run from the repo root with: npx vitest run --config examples/deepseek-agent/vitest.config.ts
export default defineConfig({
  test: {
    name: 'deepseek-agent',
    root: fileURLToPath(new URL('../..', import.meta.url)),
    include: ['examples/deepseek-agent/**/*.test.ts'],
  },
});
