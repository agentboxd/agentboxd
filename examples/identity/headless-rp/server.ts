/**
 * A relying party that lets AI agents sign in headlessly with their Agentboxd inbox.
 *
 *   POST /login/verify     { id_token }  offline: JWKS signature + iss/aud/exp/nonce + a jti replay cache
 *   POST /login/exchange   { id_token }  central: RFC 7523 JWT bearer grant at the issuer's /token,
 *                                        then /userinfo (the issuer enforces single use)
 *   GET  /login/nonce                     a fresh nonce for the agent to put in its token (optional)
 *
 * Env: AGENTBOXD_CLIENT_ID, AGENTBOXD_CLIENT_SECRET (exchange only), AGENTBOXD_ISSUER, PORT.
 * Run: npm run headless-rp
 */
import { randomBytes } from 'node:crypto';
import http from 'node:http';
import { AgentIdentityError, MemoryReplayCache, verifyAgentIdentityToken } from 'agentboxd/identity';

const ISSUER = process.env.AGENTBOXD_ISSUER ?? 'https://id.agentboxd.com';
const CLIENT_ID = process.env.AGENTBOXD_CLIENT_ID ?? '';
const CLIENT_SECRET = process.env.AGENTBOXD_CLIENT_SECRET ?? '';
const PORT = Number(process.env.PORT ?? 4000);

/** One process: in memory. Several processes: back ReplayCache with Redis (`SET jti 1 NX EXAT exp`). */
const replayCache = new MemoryReplayCache();
/** Nonces we handed out and not yet seen in a token (5 minutes, like the tokens). */
const nonces = new Map<string, number>();

function takeNonce(nonce: unknown): string | undefined {
  if (typeof nonce !== 'string') return undefined;
  const exp = nonces.get(nonce);
  nonces.delete(nonce);
  return exp !== undefined && exp > Date.now() ? nonce : undefined;
}

// ---------- (a) offline verification ----------

async function verifyOffline(idToken: string, nonce?: string) {
  const agent = await verifyAgentIdentityToken(idToken, {
    audience: CLIENT_ID,
    issuer: ISSUER,
    ...(nonce ? { nonce } : {}),
    replayCache, // single use: a second presentation of the same jti is rejected
  });
  // `sub` is pairwise: stable for this app, different at every other app. Key your users on it.
  return { sub: agent.sub, email: agent.email, name: agent.name, isAgent: agent.isAgent };
}

// ---------- (b) JWT bearer exchange at the issuer ----------

interface Discovery {
  token_endpoint: string;
  userinfo_endpoint: string;
}
let discovery: Promise<Discovery> | undefined;
const discover = () =>
  (discovery ??= fetch(`${ISSUER}/.well-known/openid-configuration`).then(async (r) => {
    if (!r.ok) throw new Error(`discovery HTTP ${r.status}`);
    return (await r.json()) as Discovery;
  }));

async function exchange(idToken: string, nonce?: string) {
  const { token_endpoint, userinfo_endpoint } = await discover();
  // If we handed out a nonce, check it before redeeming (no replay cache here: the issuer enforces single use).
  if (nonce) await verifyAgentIdentityToken(idToken, { audience: CLIENT_ID, issuer: ISSUER, nonce });
  // client_secret_basic: form-urlencode id and secret, then base64 (RFC 6749 §2.3.1).
  const basic = Buffer.from(`${encodeURIComponent(CLIENT_ID)}:${encodeURIComponent(CLIENT_SECRET)}`).toString('base64');
  const tokenRes = await fetch(token_endpoint, {
    method: 'POST',
    headers: { Authorization: `Basic ${basic}`, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer', assertion: idToken }),
  });
  const tokens = (await tokenRes.json()) as { access_token?: string; id_token?: string; error?: string; error_description?: string };
  // invalid_grant: expired, wrong audience, identity turned off, or already used (replay).
  if (!tokenRes.ok || !tokens.access_token || !tokens.id_token) {
    throw new Error(`token endpoint: ${tokens.error ?? tokenRes.status} ${tokens.error_description ?? ''}`.trim());
  }
  // The returned id_token is fresh (new jti, no nonce): verify it like any ID token.
  const agent = await verifyAgentIdentityToken(tokens.id_token, { audience: CLIENT_ID, issuer: ISSUER });

  const userinfoRes = await fetch(userinfo_endpoint, { headers: { Authorization: `Bearer ${tokens.access_token}` } });
  if (!userinfoRes.ok) throw new Error(`userinfo HTTP ${userinfoRes.status}`);
  const userinfo = (await userinfoRes.json()) as Record<string, unknown>;
  return { sub: agent.sub, email: agent.email, isAgent: agent.isAgent, userinfo };
}

// ---------- tiny HTTP server ----------

async function readJson(req: http.IncomingMessage): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const c of req as AsyncIterable<Buffer>) {
    size += c.length;
    if (size > 16_384) throw new Error('body too large');
    chunks.push(c);
  }
  return JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}') as Record<string, unknown>;
}

const send = (res: http.ServerResponse, status: number, body: unknown) =>
  res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }).end(JSON.stringify(body));

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === 'GET' && req.url === '/login/nonce') {
      const nonce = randomBytes(16).toString('base64url');
      nonces.set(nonce, Date.now() + 300_000);
      return send(res, 200, { nonce, audience: CLIENT_ID });
    }
    if (req.method === 'POST' && (req.url === '/login/verify' || req.url === '/login/exchange')) {
      const body = await readJson(req);
      if (typeof body.id_token !== 'string') return send(res, 400, { error: 'id_token is required' });
      const nonce = takeNonce(body.nonce);
      const who = req.url === '/login/verify' ? await verifyOffline(body.id_token, nonce) : await exchange(body.id_token, nonce);
      // Here: find-or-create the user by `sub`, then start your own session.
      return send(res, 200, { signed_in: true, ...who });
    }
    send(res, 404, { error: 'not found' });
  } catch (err) {
    const code = err instanceof AgentIdentityError ? err.code : 'sign_in_failed';
    send(res, 401, { error: code, message: (err as Error).message });
  }
});

server.listen(PORT, () => console.log(`relying party on http://localhost:${PORT} (issuer ${ISSUER}, client ${CLIENT_ID})`));
