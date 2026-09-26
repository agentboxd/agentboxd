/**
 * Checks the Sim custom tools in tools/ without Sim, the way Sim runs them: each `<name>.json` is a
 * function schema in the OpenAI format Sim's Schema tab takes, and `<name>.js` is the Code tab: the body
 * of an async function whose parameters are the schema's properties, with `{{SECRET}}` references
 * replaced by the secret's value as a string.
 *
 *   npx tsx sim-email-workflows/validate.ts            static checks (schemas, names, code compiles)
 *   AGENTBOXD_API_KEY=mr_… AGENTBOXD_BASE_URL=http://localhost:3000 \
 *     npx tsx sim-email-workflows/validate.ts --smoke   also run every tool against an Agentboxd dev stack
 */
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { Agentboxd } from 'agentboxd';
import { deliverLocally } from '../_shared/dev-inbound.js';

interface ToolSchema {
  type: 'function';
  function: { name: string; description: string; parameters: { type: 'object'; properties: Record<string, { type: string; description: string }>; required: string[] } };
}

const dir = new URL('./tools/', import.meta.url);
const read = (f: string) => readFileSync(new URL(f, dir), 'utf8');
const AsyncFunction = Object.getPrototypeOf(async () => {}).constructor as new (...args: string[]) => (...a: unknown[]) => Promise<unknown>;
const SECRETS = ['AGENTBOXD_API_KEY', 'AGENTBOXD_INBOX_ID'];

/** What Sim does with `{{NAME}}` in unquoted form: the secret's value as a string literal. */
function compile(code: string, params: string[], secrets: Record<string, string>, apiBase = 'https://api.agentboxd.com') {
  const body = code
    .replace(/\{\{([A-Z0-9_]+)\}\}/g, (_, name: string) => JSON.stringify(secrets[name] ?? ''))
    .replaceAll('https://api.agentboxd.com', apiBase);
  return new AsyncFunction(...params, body);
}

const names = readdirSync(dir).filter((f) => f.endsWith('.json')).map((f) => f.slice(0, -5)).sort();
assert.deepEqual(names, ['get_verification_code', 'list_unread_emails', 'reply_to_email']);
const tools = new Map<string, { schema: ToolSchema; code: string; params: string[] }>();
for (const name of names) {
  const schema = JSON.parse(read(`${name}.json`)) as ToolSchema;
  assert.equal(schema.type, 'function', `${name}.json: type must be "function"`);
  assert.equal(schema.function.name, name, `${name}.json: function.name must match the file name`);
  assert.match(schema.function.name, /^[a-z_]+$/);
  assert.ok(schema.function.description.length > 20);
  assert.equal(schema.function.parameters.type, 'object');
  const params = Object.keys(schema.function.parameters.properties);
  for (const r of schema.function.parameters.required) assert.ok(params.includes(r), `${name}.json: required "${r}" is not a property`);
  for (const [p, def] of Object.entries(schema.function.parameters.properties)) assert.ok(def.type && def.description, `${name}.json: ${p} needs type and description`);
  const code = read(`${name}.js`);
  for (const [, s] of code.matchAll(/\{\{([A-Z0-9_]+)\}\}/g)) assert.ok(SECRETS.includes(s!), `${name}.js uses unknown secret {{${s}}}`);
  assert.ok(!/mr_[A-Za-z0-9]{20,}/.test(code), `${name}.js must not contain a key`);
  compile(code, params, {}); // throws on a syntax error
  tools.set(name, { schema, code, params });
}
console.log(`sim tools ok: ${names.join(', ')}`);

if (process.argv.includes('--smoke')) {
  const baseUrl = process.env.AGENTBOXD_BASE_URL ?? 'http://localhost:3000';
  const mr = new Agentboxd({ baseUrl });
  const inbox = await mr.inboxes.create({ client_id: `sim-smoke-${Date.now()}` });
  const secrets = { AGENTBOXD_API_KEY: process.env.AGENTBOXD_API_KEY ?? '', AGENTBOXD_INBOX_ID: inbox.id };
  const call = (name: string, args: Record<string, unknown>) => {
    const t = tools.get(name)!;
    return compile(t.code, t.params, secrets, baseUrl)(...t.params.map((p) => args[p])) as Promise<Record<string, unknown>>;
  };

  const since = new Date(Date.now() - 5000).toISOString();
  await deliverLocally(baseUrl, { from: 'Dana <dana@example.com>', to: inbox.address, subject: 'Opening hours', text: 'Open on Saturday?' });
  await mr.messages.wait(inbox.id, { since, timeout: 10 });
  const listed = (await call('list_unread_emails', { limit: 5 })) as { emails: { id: string; text: string }[] };
  assert.equal(listed.emails.length, 1, JSON.stringify(listed));
  assert.equal(listed.emails[0]!.text, 'Open on Saturday?');
  const reply = await call('reply_to_email', { message_id: listed.emails[0]!.id, text: 'Yes, 10 to 2.' });
  assert.equal(reply.sent, true, JSON.stringify(reply));
  const again = await call('reply_to_email', { message_id: listed.emails[0]!.id, text: 'Yes, 10 to 2.' });
  assert.equal(again.id, reply.id, 'the idempotency key must make a retry return the same message');

  const codeSince = new Date(Date.now() - 5000).toISOString();
  await deliverLocally(baseUrl, { from: 'Acme <no-reply@acme.example>', to: inbox.address, subject: 'Your code', text: 'Your verification code is 482913.' });
  const code = await call('get_verification_code', { since: codeSince, timeout_seconds: 10 });
  assert.equal(code.code, '482913', JSON.stringify(code));
  const bad = await compile(tools.get('list_unread_emails')!.code, ['limit'], { ...secrets, AGENTBOXD_API_KEY: 'mr_wrong' }, baseUrl)(5);
  assert.ok((bad as { error?: unknown }).error, 'a wrong key must come back as an error object');
  console.log('sim smoke ok: listed, replied once (idempotent), read code 482913, bad key reported');
}
