/**
 * A Playwright fixture that gives each test its own temporary Agentboxd inbox and deletes it
 * (with its mail) when the test ends. Temporary inboxes are receive-only and live on their own
 * domain, so test sign-ups never touch your permanent agent addresses.
 */
import { test as base } from '@playwright/test';
import { Agentboxd, type Inbox } from 'agentboxd';

export const mr = new Agentboxd();

export const test = base.extend<{ inbox: Inbox }>({
  // eslint-disable-next-line no-empty-pattern -- Playwright fixtures take a destructured first argument.
  inbox: async ({}, use) => {
    const inbox = await mr.inboxes.createTemporary({ ttlSeconds: 900 });
    await use(inbox);
    await mr.inboxes.delete(inbox.id); // wipe now instead of at expires_at
  },
});

export { expect } from '@playwright/test';

/** Waits for the sign-up email and returns its code; fails the test with a clear message on timeout. */
export async function verificationCode(inbox: Inbox, since: string, opts: { from?: string; timeout?: number } = {}): Promise<string> {
  const v = await mr.messages.waitForVerification(inbox.id, { since, from: opts.from, timeout: opts.timeout ?? 30 });
  if (!v?.code) throw new Error(`no verification code for ${inbox.address} within ${opts.timeout ?? 30} s`);
  return v.code;
}
