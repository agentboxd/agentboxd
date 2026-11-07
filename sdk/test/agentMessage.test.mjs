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

// Keys from agent-keys.json: an unknown kid fetches the key set again at most once a minute per URI, so a sender
// can't make every verification hit the network; each fetch has a timeout.
test('unknown kids refetch the key set at most once per cooldown', async (t) => {
  const uri = 'https://keys.example.test/cooldown/agent-keys.json';
  const [head, payload, sig] = valid.message.agent.signature.split('.');
  const junk = (i) => {
    const header = JSON.parse(Buffer.from(head, 'base64url').toString('utf8'));
    return `${Buffer.from(JSON.stringify({ ...header, kid: `junk-${i}` })).toString('base64url')}.${payload}.${sig}`;
  };
  let served = { keys: [] };
  const fetches = [];
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    fetches.push({ url: String(url), signal: init?.signal });
    return new Response(JSON.stringify(served), { status: 200 });
  });
  t.mock.timers.enable({ apis: ['Date'], now: Date.now() });
  const verify = (signature) =>
    code(
      verifyAgentMessage(valid.message, {
        recipient: valid.recipient,
        issuer: fixture.issuer,
        keysUri: uri,
        signature,
        currentDate: new Date((valid.claims.iat + 60) * 1000),
      }),
    );

  for (let i = 0; i < 20; i++) assert.equal(await verify(junk(i)), 'unknown_key');
  assert.equal(fetches.length, 1); // the first lookup; refetches for unknown kids wait for the cooldown
  assert.equal(fetches[0].url, uri);
  assert.ok(fetches[0].signal instanceof globalThis.AbortSignal);

  // After the cooldown, a key published since the last fetch is found.
  served = fixture.keys;
  t.mock.timers.tick(60_000);
  assert.equal(await verify(undefined), 'valid');
  assert.equal(fetches.length, 2);
});

// Replay: the nonce is kept as long as the signature verifies, and recorded only after every other check.
const setCache = () => {
  const seen = new Map();
  return { seen, use: (nonce, expiresAt) => (seen.has(nonce) ? false : (seen.set(nonce, expiresAt), true)) };
};
const plain = fixture.vectors.find((v) => v.claims.type === 'message' && v.expect === 'valid');
const at = (v, seconds) => new Date((v.claims.iat + seconds) * 1000);
const verifyVector = (v, extra = {}) =>
  verifyAgentMessage(v.message, { recipient: v.recipient, issuer: fixture.issuer, keys: fixture.keys, currentDate: at(v, 60), ...extra });

test('replay: the nonce is kept until iat + maxAge + the clock tolerance', async () => {
  const cache = setCache();
  await verifyVector(valid, { replayCache: cache });
  assert.equal(cache.seen.get(valid.claims.nonce), valid.claims.iat + 900 + 30);
  const custom = setCache();
  await verifyVector(valid, { replayCache: custom, maxAgeSeconds: 60, clockTolerance: 5 });
  assert.equal(custom.seen.get(valid.claims.nonce), valid.claims.iat + 60 + 5);
  const day = setCache();
  await verifyVector(plain, { replayCache: day });
  assert.equal(day.seen.get(plain.claims.nonce), plain.claims.iat + 86_400 + 30);
});

test('replay: with a replay cache, a signature older than the nonce is kept is too_old, also without a window', async () => {
  // Without a replay cache, plain messages have no age limit (archives, audits).
  assert.equal(await code(verifyVector(plain, { currentDate: at(plain, 200_000) })), 'valid');
  assert.equal(await code(verifyVector(plain, { replayCache: setCache(), currentDate: at(plain, 86_400) })), 'valid');
  // Its nonce is forgotten after a day, so the same signature must not verify again after that.
  assert.equal(await code(verifyVector(plain, { replayCache: setCache(), currentDate: at(plain, 86_400 + 31) })), 'too_old');
  assert.equal(await code(verifyVector(plain, { replayCache: setCache(), maxAgeSeconds: null, currentDate: at(plain, 200_000) })), 'too_old');
});

test('replay: the nonce is recorded only after the revocation check passed, so a failed check can be retried', async () => {
  const cache = setCache();
  let down = true;
  const checkRevocation = {
    apiKey: 'mr_k',
    baseUrl: 'http://api.test',
    fetch: async () => {
      if (down) throw new TypeError('fetch failed');
      return new Response(JSON.stringify({ valid: true, status: 'active', reasons: [] }), { status: 200 });
    },
  };
  assert.equal(await code(verifyVector(valid, { replayCache: cache, checkRevocation })), 'revocation_check_failed');
  assert.equal(cache.seen.size, 0);
  down = false;
  assert.equal(await code(verifyVector(valid, { replayCache: cache, checkRevocation })), 'valid');
  assert.equal(await code(verifyVector(valid, { replayCache: cache, checkRevocation })), 'replayed');
  // A revoked sender doesn't burn the nonce either.
  const revoked = setCache();
  const answer = (status) => ({ ...checkRevocation, fetch: async () => new Response(JSON.stringify({ valid: false, status, reasons: [] }), { status: 200 }) });
  assert.equal(await code(verifyVector(valid, { replayCache: revoked, checkRevocation: answer('revoked') })), 'agent_revoked');
  assert.equal(revoked.seen.size, 0);
});

test('a revoked key without a readable revoked_at is revoked', async () => {
  const kid = JSON.parse(Buffer.from(valid.message.agent.signature.split('.')[0], 'base64url').toString('utf8')).kid;
  const keysWith = (patch) => ({ keys: fixture.keys.keys.map((k) => (k.kid === kid ? { ...k, ...patch } : k)) });
  assert.equal(await code(verifyVector(valid, { keys: keysWith({ status: 'revoked', revoked_at: null }) })), 'key_revoked');
  assert.equal(await code(verifyVector(valid, { keys: keysWith({ status: 'revoked', revoked_at: undefined }) })), 'key_revoked');
  assert.equal(await code(verifyVector(valid, { keys: keysWith({ status: 'revoked', revoked_at: 'not a time' }) })), 'key_revoked');
  // Retired message keys keep verifying (a rotated-out key signs 6 more minutes).
  assert.equal(await code(verifyVector(valid, { keys: keysWith({ status: 'retired', retired_at: '2020-01-01T00:00:00.000Z' }) })), 'valid');
});
