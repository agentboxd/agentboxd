import { expect, test, verificationCode } from './fixtures.js';

test('a new user signs up with an emailed code', async ({ page, inbox }) => {
  await page.goto('/signup');
  await page.getByLabel('Email').fill(inbox.address);

  const since = new Date().toISOString(); // before the click that sends the email
  await page.getByRole('button', { name: 'Sign up' }).click();
  await expect(page.getByRole('heading', { name: 'Check your email' })).toBeVisible();

  const code = await verificationCode(inbox, since, { from: 'acme.example' });
  expect(code).toMatch(/^\d{6}$/);

  await page.getByLabel('Verification code').fill(code);
  await page.getByRole('button', { name: 'Verify' }).click();
  await expect(page.getByRole('heading', { name: 'Welcome to Acme' })).toBeVisible();
});
