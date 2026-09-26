/**
 * Runs the tool functions against a local Agentboxd dev stack without a model (no OpenAI key needed):
 * create an inbox, deliver a test email to it, list it, read it, reply, and read a verification code.
 *   AGENTBOXD_API_KEY=mr_… AGENTBOXD_BASE_URL=http://localhost:3000 npx tsx vercel-ai-sdk-email-tools/smoke.ts
 */
import assert from 'node:assert/strict';
import { Agentboxd } from 'agentboxd';
import { deliverLocally } from '../_shared/dev-inbound.js';
import { emailActions, emailTools } from './tools.js';

const baseUrl = process.env.AGENTBOXD_BASE_URL ?? 'http://localhost:3000';
const mr = new Agentboxd({ baseUrl });

const inbox = await mr.inboxes.create({ client_id: `ai-sdk-smoke-${Date.now()}` });
const tools = emailTools(mr, inbox.id);
assert.deepEqual(Object.keys(tools).sort(), [
  'get_verification_code',
  'list_messages',
  'read_message',
  'reply_to_email',
  'send_email',
  'wait_for_email',
]);
const a = emailActions(mr, inbox.id, { maxSends: 1 });

const before = new Date().toISOString(); // wait only counts mail that arrives after `since`
await deliverLocally(baseUrl, {
  from: 'Dana <dana@example.com>',
  to: inbox.address,
  subject: 'Opening hours',
  text: 'Hi, are you open on Saturday?\n\nOn Mon, Sep 22, 2026 Support wrote:\n> Thanks for your order.',
});
const waited = await a.waitForEmail({ since: before, timeoutSeconds: 10, from: 'dana@' });
assert.ok(waited.message, 'wait_for_email returned nothing');
console.log('wait_for_email →', waited.message.subject, '|', waited.message.text);

const listed = await a.listMessages({});
assert.equal(listed.messages.length, 1);
const read = await a.readMessage({ messageId: listed.messages[0]!.id });
assert.equal(read.message.text, 'Hi, are you open on Saturday?'); // extracted_text: quoted history cut
const replied = await a.reply({ messageId: read.message.id, text: 'Yes, 10:00 to 14:00.' });
console.log('reply_to_email →', replied.status, 'thread', replied.thread_id === read.message.thread_id ? 'kept' : 'NEW');
await assert.rejects(a.sendEmail({ to: 'x@example.com', subject: 'x', text: 'x' }), /budget/);

const since = new Date().toISOString();
await deliverLocally(baseUrl, {
  from: 'Acme <no-reply@acme.example>',
  to: inbox.address,
  subject: 'Your Acme verification code',
  text: 'Your verification code is 482913. It expires in 10 minutes.',
});
const v = await a.getVerificationCode({ since, timeoutSeconds: 10 });
assert.equal(v.code, '482913');
console.log('get_verification_code →', v.code, v.confidence);
console.log('smoke ok');
