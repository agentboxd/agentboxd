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
