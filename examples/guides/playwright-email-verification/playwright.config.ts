import { defineConfig, devices } from '@playwright/test';

// APP_URL points at the app under test. Without it, the demo app in this folder is started.
const appUrl = process.env.APP_URL;

export default defineConfig({
  testDir: '.',
  // Waiting for an email takes a few seconds; leave room for it on top of the page steps.
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: appUrl ?? 'http://localhost:4400', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  ...(appUrl
    ? {}
    : {
        webServer: {
          command: 'npx tsx playwright-email-verification/demo-app.ts',
          url: 'http://localhost:4400/health',
          reuseExistingServer: true,
          cwd: '..',
        },
      }),
});
