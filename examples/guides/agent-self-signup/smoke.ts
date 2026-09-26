/**
 * Runs the self-signup flow against a local Agentboxd dev stack (SIGNUP_ENABLED=true, a low
 * SIGNUP_POW_DIFFICULTY): sign up with no key, receive a test email, reply to it, check the account.
 *   AGENTBOXD_BASE_URL=http://localhost:3000 npx tsx agent-self-signup/smoke.ts
 */
import assert from 'node:assert/strict';
import { Agentboxd, AgentboxdError } from 'agentboxd';
import { deliverLocally } from '../_shared/dev-inbound.js';

const baseUrl = process.env.AGENTBOXD_BASE_URL ?? 'http://localhost:3000';

const { client, api_key, inbox, workspace, restrictions } = await Agentboxd.signup({ baseUrl, agentName: 'smoke-agent' });
assert.match(api_key, /^mr_/);
assert.equal(workspace.status, 'unclaimed');
console.log('signup →', inbox.address, `(${restrictions.recipients_per_day} new recipients/day until claimed)`);

const since = new Date().toISOString();
await deliverLocally(baseUrl, { from: 'Dana <dana@example.com>', to: inbox.address, subject: 'Hello agent', text: 'Can you hear me?' });
const mail = await client.messages.wait(inbox.id, { since, timeout: 10 });
assert.ok(mail, 'no mail arrived');
const reply = await client.messages.reply(inbox.id, mail.id, { text: 'Loud and clear.' });
console.log('reply →', reply.status);

// Webhooks wait for a human to claim the workspace; the stream works now.
await assert.rejects(client.webhooks.create({ url: 'https://hooks.example.com/x' }), (e: unknown) => e instanceof AgentboxdError && e.code === 'unclaimed_workspace');

const account = await client.account.get();
assert.equal(account.claim.status, 'unclaimed');
console.log('account →', account.claim.status, 'expires', account.claim.expires_at);
console.log('smoke ok');
