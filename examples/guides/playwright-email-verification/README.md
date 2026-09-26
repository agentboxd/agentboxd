# Sign-up and OTP emails in Playwright tests

Guide: https://agentboxd.com/guides/playwright-email-verification

| File | What |
|---|---|
| `fixtures.ts` | An `inbox` fixture: a temporary Agentboxd inbox per test, deleted afterwards, plus `verificationCode(inbox, since)`. |
| `signup.spec.ts` | The test: fill the sign-up form with the inbox address, wait for the code, enter it. |
| `playwright.config.ts` | `APP_URL` points at your app; without it the demo app below is started. |
| `demo-app.ts` | A tiny sign-up app for trying the test. It delivers its code email through a local Agentboxd dev stack. |

```bash
cd examples/guides && npm ci && npx playwright install chromium
export AGENTBOXD_API_KEY=mr_...
APP_URL=https://staging.example.com npm run test:e2e      # your app
AGENTBOXD_BASE_URL=http://localhost:3000 npm run test:e2e       # demo app + local Agentboxd dev stack
```

Written against `@playwright/test` 1.63.0 (checked 25 September 2026).
