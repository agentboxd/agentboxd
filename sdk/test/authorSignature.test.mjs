// verifyAuthorSignature and agent keys against the built ES module and the shared vectors
// (../../test/fixtures/agent-messages/author-vectors.json). Run `npm run build` first.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import * as main from 'agentboxd';
import { AuthorSignatureError, createKeyProof, generateAgentKey, signAgentMessage, verifyAuthorSignature } from 'agentboxd/identity';

const fixture = JSON.parse(readFileSync(new URL('../../test/fixtures/agent-messages/author-vectors.json', import.meta.url), 'utf8'));

const code = async (p) => {
  try {
    await p;
    return 'valid';
  } catch (err) {
    if (err instanceof AuthorSignatureError) return err.code;
    throw err;
  }
};

test('agent keys live in the agentboxd/identity subpath only', () => {
  assert.equal(main.generateAgentKey, undefined);
  assert.equal(typeof main.Agentboxd.prototype, 'object');
});

for (const v of fixture.vectors) {
  test(`author vector: ${v.name} → ${v.expect}`, async () => {
    assert.equal(await code(verifyAuthorSignature(v.message, { keys: fixture.keys })), v.expect);
  });
}

test('generate → proof → sign → verify (Ed25519)', async () => {
  const key = await generateAgentKey();
  const proof = await createKeyProof({ privateKey: key.privateKey, publicJwk: key.publicJwk, address: 'bot@acme.example' });
  assert.equal(proof.split('.').length, 3);
  const jws = await signAgentMessage({ ...key, from: 'bot@acme.example', text: 'hi', type: 'message' });
  const keys = [{ ...key.publicJwk, kid: key.kid, alg: key.alg, status: 'active', revoked_at: null }];
  const message = { from: 'bot@acme.example', to: [], cc: [], subject: null, text: 'hi', html: null, in_reply_to: null, attachments: [], author: { signature: jws } };
  const r = await verifyAuthorSignature(message, { keys });
  assert.equal(r.kid, key.kid);
  assert.equal(await code(verifyAuthorSignature({ ...message, text: 'bye' }, { keys })), 'content_mismatch');
});

// Key lifecycle and time: the signer picks iat, Agentboxd sets created_at.
const iso = (seconds) => new Date(seconds * 1000).toISOString();
const lifecycle = async () => {
  const key = await generateAgentKey();
  const T = Math.floor(Date.now() / 1000) - 3600; // the key's revocation or retirement, an hour ago
  const message = (iat, over = {}) =>
    signAgentMessage({ ...key, from: 'bot@acme.example', text: 'hi', iat }).then((jws) => ({
      from: 'bot@acme.example',
      to: [],
      cc: [],
      subject: null,
      text: 'hi',
      html: null,
      in_reply_to: null,
      attachments: [],
      author: { signature: jws },
      ...over,
    }));
  const keys = (over) => [{ ...key.publicJwk, kid: key.kid, alg: key.alg, status: 'active', retired_at: null, revoked_at: null, ...over }];
  return { T, message, keys };
};

test('author signatures: a backdated iat does not get a stolen key past its revocation', async () => {
  const { T, message, keys } = await lifecycle();
  const revoked = keys({ status: 'revoked', revoked_at: iso(T) });
  // No created_at: nothing but the signer's own iat dates it, so a revoked key fails (security report #295, A4).
  assert.equal(await code(verifyAuthorSignature(await message(T - 100), { keys: revoked })), 'key_revoked');
  assert.equal(await code(verifyAuthorSignature(await message(T - 100, { created_at: iso(T - 50) }), { keys: revoked })), 'valid');
  // Signed after the revocation with an earlier iat: the message's created_at gives it away.
  assert.equal(await code(verifyAuthorSignature(await message(T - 100, { created_at: iso(T + 10) }), { keys: revoked })), 'key_revoked');
  assert.equal(await code(verifyAuthorSignature(await message(T, { created_at: iso(T - 30) }), { keys: revoked })), 'key_revoked');
  // Revoked without a (readable) time: revoked from the start.
  for (const revoked_at of [null, undefined, 'not a time']) {
    assert.equal(await code(verifyAuthorSignature(await message(T - 100), { keys: keys({ status: 'revoked', revoked_at }) })), 'key_revoked');
  }
});

test('author signatures: a retired key verifies what it signed before retired_at, nothing newer', async () => {
  const { T, message, keys } = await lifecycle();
  const retired = keys({ status: 'retired', retired_at: iso(T) });
  assert.equal(await code(verifyAuthorSignature(await message(T - 100, { created_at: iso(T - 99) }), { keys: retired })), 'valid');
  assert.equal(await code(verifyAuthorSignature(await message(T + 5), { keys: retired })), 'key_retired');
  assert.equal(await code(verifyAuthorSignature(await message(T + 5, { created_at: iso(T + 6) }), { keys: retired })), 'key_retired');
  // Rotation isn't a compromise: a message signed before it and delivered just after still verifies.
  assert.equal(await code(verifyAuthorSignature(await message(T - 100, { created_at: iso(T + 10) }), { keys: retired })), 'valid');
  // Without retired_at there is no cut-off: old signatures stay valid.
  assert.equal(await code(verifyAuthorSignature(await message(T + 5), { keys: keys({ status: 'retired' }) })), 'valid');
});

test('author signatures: an iat in the future, or after the message was created, is refused', async () => {
  const { message, keys } = await lifecycle();
  const now = Math.floor(Date.now() / 1000);
  const active = keys({});
  assert.equal(await code(verifyAuthorSignature(await message(now + 120), { keys: active })), 'issued_in_future');
  assert.equal(await code(verifyAuthorSignature(await message(now + 10), { keys: active })), 'valid'); // inside the 30 s tolerance
  assert.equal(await code(verifyAuthorSignature(await message(now + 10), { keys: active, clockTolerance: 0 })), 'issued_in_future');
  assert.equal(
    await code(verifyAuthorSignature(await message(now + 10), { keys: active, clockTolerance: 0, currentDate: new Date((now + 20) * 1000) })),
    'valid',
  );
  // Agentboxd accepts an iat at most 60 s ahead of its clock; created_at is that clock.
  assert.equal(await code(verifyAuthorSignature(await message(now - 1000, { created_at: iso(now - 1080) }), { keys: active })), 'valid');
  assert.equal(await code(verifyAuthorSignature(await message(now - 1000, { created_at: iso(now - 1200) }), { keys: active })), 'issued_in_future');
});
