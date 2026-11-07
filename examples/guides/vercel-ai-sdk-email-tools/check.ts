/**
 * Offline check of the tools against a fake Agentboxd API (no server, no model): mail whose content is withheld
 * (not screened yet, or held for a person) is left out of the list, and reading it returns a short note without
 * marking it read, so the agent still finds it unread once its content is there.
 *   npx tsx vercel-ai-sdk-email-tools/check.ts
 */
import assert from 'node:assert/strict';
import { Agentboxd, type Message } from 'agentboxd';
import { emailActions, withheldNote } from './tools.js';

const INBOX = 'inb_check';

function message(id: string, over: Partial<Message> = {}): Message {
  return {
    id,
    inbox_id: INBOX,
    thread_id: `thr_${id}`,
    direction: 'inbound',
    status: 'received',
    rfc_message_id: `<${id}@example.com>`,
    in_reply_to: null,
    references: [],
    from: 'Dana <dana@example.com>',
    to: ['agent@example.com'],
    cc: [],
    bcc: [],
    reply_to: null,
    subject: 'Opening hours',
    text: 'Are you open on Saturday?',
    html: null,
    extracted_text: 'Are you open on Saturday?',
    headers: {},
    labels: [],
    is_read: false,
    provider_message_id: null,
    size_bytes: 100,
    sent_at: null,
    received_at: '2026-10-01T10:00:00.000Z',
    created_at: '2026-10-01T10:00:00.000Z',
    attachments: [],
    ai: { verification: null },
    ...over,
  };
}

/** What the API returns for mail it withholds from an API key (src/services/screening.ts withholdMessage). */
const withheld = (id: string, state: 'pending' | 'held', subject: string): Message =>
  message(id, {
    subject,
    text: null,
    extracted_text: null,
    withheld: { state, reason: state === 'held' ? 'phishing' : null, attachments: 0 },
  });

const store = new Map<string, Message>(
  [
    withheld('msg_pending', 'pending', '[not screened yet]'),
    withheld('msg_held', 'held', '[held: phishing]'),
    message('msg_ok'),
  ].map((m) => [m.id, m]),
);
const patched: string[] = [];

const fakeFetch = (async (input: string | URL | Request, init?: RequestInit) => {
  const url = new URL(String(input instanceof Request ? input.url : input));
  const method = init?.method ?? 'GET';
  const json = (data: unknown) => Response.json(data);
  if (method === 'GET' && url.pathname === `/v1/inboxes/${INBOX}/messages`) return json({ data: [...store.values()], next_cursor: null });
  const one = url.pathname.match(/^\/v1\/messages\/([^/]+)$/);
  const m = one && store.get(one[1]!);
  if (m && method === 'GET') return json(m);
  if (m && method === 'PATCH') {
    patched.push(m.id);
    return json({ ...m, is_read: true });
  }
  return Response.json({ error: { code: 'not_found', message: `${method} ${url.pathname}` } }, { status: 404 });
}) as typeof fetch;

const a = emailActions(new Agentboxd({ apiKey: 'mr_check', baseUrl: 'https://agentboxd.test', fetch: fakeFetch }), INBOX);

const listed = await a.listMessages({});
assert.deepEqual(listed.messages.map((m) => m.id), ['msg_ok'], 'withheld mail must be left out of the list');

const pending = await a.readMessage({ messageId: 'msg_pending' });
assert.deepEqual(pending, { message: null, unavailable: withheldNote(store.get('msg_pending')!) });
assert.match(String(pending.unavailable), /still being checked/);
const held = await a.readMessage({ messageId: 'msg_held' });
assert.match(String(held.unavailable), /Held for a person/);
assert.deepEqual(patched, [], 'withheld mail must stay unread');

const read = await a.readMessage({ messageId: 'msg_ok' });
assert.equal(read.message?.text, 'Are you open on Saturday?');
assert.deepEqual(patched, ['msg_ok'], 'mail read in full is marked read');
console.log('vercel-ai tools ok: withheld mail skipped in the list, left unread when read');
