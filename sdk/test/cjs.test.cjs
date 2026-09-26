// Smoke test of the built CommonJS entry (run `npm run build` first). No dependencies: node:test.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const sdk = require('agentboxd');

test('require() returns the CommonJS build with every export', () => {
  assert.equal(typeof sdk.Agentboxd, 'function');
  assert.equal(sdk.Agentboxd, sdk.Mailroom); // deprecated alias
  assert.equal(sdk.AgentboxdError, sdk.MailroomError); // deprecated alias
  assert.equal(typeof sdk.verifyWebhook, 'function');
  assert.equal(typeof sdk.EventStream, 'function');
  assert.equal(typeof sdk.StreamClosedError, 'function');
  assert.equal(sdk.DEFAULT_BASE_URL, 'https://api.agentboxd.com');
  assert.match(require.resolve('agentboxd'), /dist[\\/]cjs[\\/]index\.js$/);
});

test('the CommonJS client makes requests', async () => {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ data: [], next_cursor: null }), { status: 200 });
  };
  const mr = new sdk.Agentboxd({ apiKey: 'mr_test', baseUrl: 'http://api.test', fetch });
  const page = await mr.inboxes.list({ limit: 5 });
  assert.deepEqual(page.data, []);
  assert.equal(calls[0].url, 'http://api.test/v1/inboxes?limit=5');
});

test('require("agentboxd/identity") loads the relying-party helper, which loads jose', async () => {
  const identity = require('agentboxd/identity');
  assert.equal(typeof identity.verifyAgentIdentityToken, 'function');
  assert.equal(typeof identity.MemoryReplayCache, 'function');
  assert.match(require.resolve('agentboxd/identity'), /dist[\\/]cjs[\\/]identity\.js$/);
  // An empty key set: the token fails verification (so jose was loaded), not with jose_missing.
  await assert.rejects(
    identity.verifyAgentIdentityToken('a.b.c', { audience: 'abxc_x', jwks: { keys: [] } }),
    (e) => e instanceof identity.AgentIdentityError && e.code === 'invalid_token',
  );
});
