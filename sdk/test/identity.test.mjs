// verifyAgentIdentityToken and mr.identity against the built ES module (run `npm run build` first).
// jose is a devDependency here (an optional peer dependency for users).
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { test } from 'node:test';
import { exportJWK, generateKeyPair, SignJWT } from 'jose';
import * as main from 'agentboxd';
import { AgentIdentityError, MemoryReplayCache, verifyAgentIdentityToken } from 'agentboxd/identity';

const { Agentboxd } = main;

const ISSUER = 'https://id.agentboxd.test';
const AUD = 'abxc_test_client';
const { privateKey, publicKey } = await generateKeyPair('ES256');
const jwks = { keys: [{ ...(await exportJWK(publicKey)), kid: 'k1', alg: 'ES256', use: 'sig' }] };
const now = () => Math.floor(Date.now() / 1000);

async function sign(claims = {}, header = {}, opts = {}) {
  const iat = opts.iat ?? now();
  return new SignJWT({
    email: 'agent@agents.agentboxd.com',
    email_verified: true,
    'https://agentboxd.com/claims/agent': true,
    jti: opts.jti ?? randomUUID(),
    ...claims,
  })
    .setProtectedHeader({ alg: 'ES256', kid: 'k1', typ: 'JWT', ...header })
    .setIssuer(opts.iss ?? ISSUER)
    .setSubject('pairwise-sub')
    .setAudience(opts.aud ?? AUD)
    .setIssuedAt(iat)
    .setExpirationTime(opts.exp ?? iat + 300)
    .sign(opts.key ?? privateKey);
}

const verify = (token, extra = {}) => verifyAgentIdentityToken(token, { audience: AUD, issuer: ISSUER, jwks, ...extra });
const rejects = (p, code) => assert.rejects(p, (e) => e instanceof AgentIdentityError && e.code === code);

test('verification is only in the agentboxd/identity subpath (the main entry never loads jose)', () => {
  assert.equal(main.verifyAgentIdentityToken, undefined);
  assert.equal(typeof verifyAgentIdentityToken, 'function');
});

test('a valid token verifies and maps the claims', async () => {
  const token = await sign({ 'https://agentboxd.com/claims/workspace': { id: 'w1', name: 'Acme' }, nonce: 'n1', name: 'Support' });
  const agent = await verify(token, { nonce: 'n1' });
  assert.equal(agent.sub, 'pairwise-sub');
  assert.equal(agent.email, 'agent@agents.agentboxd.com');
  assert.equal(agent.emailVerified, true);
  assert.equal(agent.isAgent, true);
  assert.equal(agent.name, 'Support');
  assert.deepEqual(agent.workspace, { id: 'w1', name: 'Acme' });
  assert.equal(agent.audience, AUD);
});

test('audience, issuer and signature mismatches are rejected', async () => {
  await rejects(verify(await sign({}, {}, { aud: 'someone_else' })), 'invalid_token');
  await rejects(verify(await sign({}, {}, { iss: 'https://evil.test' })), 'invalid_token');
  const other = await generateKeyPair('ES256');
  await rejects(verify(await sign({}, {}, { key: other.privateKey })), 'invalid_token');
});

test('expired tokens, future iat and lifetimes over 300 s are rejected', async () => {
  await rejects(verify(await sign({}, {}, { iat: now() - 400, exp: now() - 100 })), 'token_expired');
  await rejects(verify(await sign({}, {}, { iat: now() + 120, exp: now() + 400 })), 'invalid_token');
  await rejects(verify(await sign({}, {}, { exp: now() + 3600 })), 'invalid_token');
  // Within the clock tolerance.
  await verify(await sign({}, {}, { iat: now() - 310, exp: now() - 10 }));
});

test('nonce and the agent claim are enforced', async () => {
  await rejects(verify(await sign({ nonce: 'a' }), { nonce: 'b' }), 'nonce_mismatch');
  await rejects(verify(await sign(), { nonce: 'b' }), 'nonce_mismatch');
  await rejects(verify(await sign({ 'https://agentboxd.com/claims/agent': false })), 'not_agent');
  const person = await verify(await sign({ 'https://agentboxd.com/claims/agent': undefined }), { requireAgent: false });
  assert.equal(person.isAgent, false);
});

test('a replay cache makes tokens single-use', async () => {
  const replayCache = new MemoryReplayCache();
  const token = await sign();
  await verify(token, { replayCache });
  await rejects(verify(token, { replayCache }), 'token_replayed');
  assert.equal(replayCache.size, 1);
});

test('unsigned (alg none) and wrongly typed tokens are rejected', async () => {
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
  const t = now();
  const none = `${b64({ alg: 'none', typ: 'JWT' })}.${b64({ iss: ISSUER, sub: 's', aud: AUD, iat: t, exp: t + 60, jti: 'j', 'https://agentboxd.com/claims/agent': true })}.`;
  await rejects(verify(none), 'invalid_token');
  await rejects(verify(await sign({}, { typ: 'at+jwt' })), 'invalid_token');
});

test('audience is required', async () => {
  await assert.rejects(verifyAgentIdentityToken('x', {}), TypeError);
});

test('mr.identity calls the documented routes', async () => {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url: String(url), method: init.method, body: init.body && JSON.parse(init.body) });
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  };
  const mr = new Agentboxd({ apiKey: 'mr_test', baseUrl: 'http://api.test', fetch });
  await mr.identity.token({ inboxId: 'i1', audience: AUD, nonce: 'n', scope: ['openid', 'email'], expiresIn: 60 });
  await mr.identity.token({ inboxId: 'i1', audience: AUD });
  await mr.identity.clients.create({ name: 'App', type: 'verify_only' });
  await mr.identity.clients.rotateSecret('c1');
  await mr.identity.inbox.update('i1', { enabled: false });
  await mr.identity.inbox.signIns('i1', { limit: 5 });
  assert.deepEqual(
    calls.map((c) => `${c.method} ${c.url}`),
    [
      'POST http://api.test/v1/inboxes/i1/identity-token',
      'POST http://api.test/v1/inboxes/i1/identity-token',
      'POST http://api.test/v1/identity/clients',
      'POST http://api.test/v1/identity/clients/c1/secret',
      'PATCH http://api.test/v1/inboxes/i1/identity',
      'GET http://api.test/v1/inboxes/i1/identity/sign-ins?limit=5',
    ],
  );
  assert.deepEqual(calls[0].body, { audience: AUD, nonce: 'n', scope: 'openid email', expires_in: 60 });
  assert.deepEqual(calls[1].body, { audience: AUD });
});

test('identity-only agents: mailbox false and no email; username from preferred_username', async () => {
  const token = await sign({ email: undefined, email_verified: undefined, 'https://agentboxd.com/claims/mailbox': false, name: 'Researcher', preferred_username: 'sharp-otter-1' });
  const agent = await verify(token);
  assert.equal(agent.mailbox, false);
  assert.equal(agent.email, null);
  assert.equal(agent.emailVerified, false);
  assert.equal(agent.username, 'sharp-otter-1');
  // Tokens from issuers older than the claim are mailboxes.
  assert.equal((await verify(await sign())).mailbox, true);
});

test('mr.identities and identity.token({ identityId }) call the documented routes', async () => {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url: String(url), method: init.method, body: init.body && JSON.parse(init.body) });
    return new Response(JSON.stringify({ ok: true }), { status: 200 });
  };
  const mr = new Agentboxd({ apiKey: 'mr_test', baseUrl: 'http://api.test', fetch });
  await mr.identities.create({ display_name: 'Researcher', client_id: 'r1' });
  await mr.identities.list({ limit: 2, metadata: { team: 'research' } });
  await mr.identities.get('id1');
  await mr.identities.update('id1', { display_name: null });
  await mr.identities.delete('id1');
  await mr.identities.pause('id1', { reason: 'audit' });
  await mr.identities.resume('id1');
  await mr.identity.token({ identityId: 'id1', audience: AUD });
  assert.deepEqual(
    calls.map((c) => `${c.method} ${c.url}`),
    [
      'POST http://api.test/v1/identities',
      'GET http://api.test/v1/identities?limit=2&metadata.team=research',
      'GET http://api.test/v1/identities/id1',
      'PATCH http://api.test/v1/identities/id1',
      'DELETE http://api.test/v1/identities/id1',
      'POST http://api.test/v1/inboxes/id1/pause',
      'POST http://api.test/v1/inboxes/id1/resume',
      'POST http://api.test/v1/inboxes/id1/identity-token',
    ],
  );
  assert.deepEqual(calls[0].body, { display_name: 'Researcher', client_id: 'r1' });
  assert.deepEqual(calls[7].body, { audience: AUD });
});
