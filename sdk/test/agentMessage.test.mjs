// verifyAgentMessage against the built ES module and the shared, server-produced vectors
// (../../test/fixtures/agent-messages/vectors.json). jose and canonicalize are devDependencies here
// (optional peer dependencies for users). Run `npm run build` first.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import * as main from 'agentboxd';
import { AgentMessageVerificationError, verifyAgentMessage } from 'agentboxd/identity';

const fixture = JSON.parse(readFileSync(new URL('../../test/fixtures/agent-messages/vectors.json', import.meta.url), 'utf8'));

const code = async (p) => {
  try {
    await p;
    return 'valid';
  } catch (err) {
    if (err instanceof AgentMessageVerificationError) return err.code;
    throw err;
  }
};

test('verification lives in the agentboxd/identity subpath only', () => {
  assert.equal(main.verifyAgentMessage, undefined);
});

for (const v of fixture.vectors) {
  test(`vector: ${v.name} → ${v.expect}`, async () => {
    const result = await code(
      verifyAgentMessage(v.message, {
        recipient: v.recipient,
        issuer: fixture.issuer,
        keys: fixture.keys,
        currentDate: new Date((v.claims.iat + 60) * 1000),
      }),
    );
    assert.equal(result, v.expect);
  });
}

// checkRevocation: the directory's live answer about the sender (POST /v1/directory/verify).
const valid = fixture.vectors.find((v) => v.expect === 'valid');
const verifyWith = (answer, status = 200, calls = []) =>
  verifyAgentMessage(valid.message, {
    recipient: valid.recipient,
    issuer: fixture.issuer,
    keys: fixture.keys,
    maxAgeSeconds: null,
    checkRevocation: {
      apiKey: 'mr_k',
      baseUrl: 'http://api.test/',
      fetch: async (url, init) => {
        calls.push({ url: String(url), init });
        return new Response(JSON.stringify(answer), { status });
      },
    },
  });

test('checkRevocation: an active sender passes, and the signature is sent to the directory', async () => {
  const calls = [];
  const res = await verifyWith({ valid: true, status: 'active', reasons: [] }, 200, calls);
  assert.equal(res.from, valid.claims.from);
  assert.equal(calls[0].url, 'http://api.test/v1/directory/verify');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer mr_k');
  assert.deepEqual(JSON.parse(calls[0].init.body), { signature: valid.message.agent.signature });
});

test('checkRevocation: revoked, suspended and deleted senders fail with their reason', async () => {
  for (const status of ['revoked', 'suspended', 'deleted']) {
    assert.equal(await code(verifyWith({ valid: false, status, reasons: [`agent_${status}`] })), `agent_${status}`);
  }
});

test('checkRevocation: a directory error fails closed', async () => {
  assert.equal(await code(verifyWith({ error: { code: 'directory_disabled' } }, 503)), 'revocation_check_failed');
  assert.equal(await code(verifyWith({ valid: false, status: null, reasons: ['unknown_key'] })), 'revocation_check_failed');
});
