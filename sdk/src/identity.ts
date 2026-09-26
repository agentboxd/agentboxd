/**
 * "Sign in with Agentboxd" for relying parties: verify an agent's identity token (an OpenID Connect
 * ID token signed by the Agentboxd issuer) before trusting who the agent is.
 *
 *   import { verifyAgentIdentityToken, MemoryReplayCache } from 'agentboxd/identity';
 *   const replayCache = new MemoryReplayCache();
 *   const agent = await verifyAgentIdentityToken(token, { audience: 'abxc_…', replayCache });
 *   agent.sub; agent.email; agent.isAgent;
 *
 * Uses the `jose` package (an optional peer dependency: `npm install jose`), loaded only when this
 * function runs, so the rest of the SDK stays dependency-free. The CommonJS build loads it with
 * `require()`, which needs Node 20.19+ or 22.12+ (jose is ESM-only).
 */

/** The hosted issuer. Self-hosted servers use their IDENTITY_ISSUER. */
export const DEFAULT_IDENTITY_ISSUER = 'https://id.agentboxd.com';
/** Always `true` in Agentboxd ID tokens: the subject is an AI agent's inbox, not a person. */
export const AGENT_CLAIM = 'https://agentboxd.com/claims/agent';
/** `true` when the agent has a mailbox, `false` for an identity-only agent (no `email` claim then). */
export const MAILBOX_CLAIM = 'https://agentboxd.com/claims/mailbox';
/** `{ id, name }` of the agent's workspace (scope `workspace`, when the workspace opted in). */
export const WORKSPACE_CLAIM = 'https://agentboxd.com/claims/workspace';
/** Agentboxd ID tokens never live longer than this. */
export const MAX_IDENTITY_TOKEN_SECONDS = 300;

/**
 * Remembers which token ids (`jti`) were already accepted, until they expire. `use` returns true the
 * first time a jti is seen and false for a replay. Implement it on Redis/your database when you run
 * more than one process (e.g. `SET jti 1 NX EXAT exp`).
 */
export interface ReplayCache {
  use(jti: string, expiresAt: number): boolean | Promise<boolean>;
}

/** An in-process ReplayCache (one Node process). `expiresAt` is in seconds since the epoch. */
export class MemoryReplayCache implements ReplayCache {
  private readonly seen = new Map<string, number>();

  use(jti: string, expiresAt: number): boolean {
    const now = Date.now() / 1000;
    for (const [k, exp] of this.seen) if (exp < now) this.seen.delete(k);
    if (this.seen.has(jti)) return false;
    this.seen.set(jti, expiresAt);
    return true;
  }

  get size(): number {
    return this.seen.size;
  }
}

/** A JSON Web Key Set, e.g. the body of `{issuer}/.well-known/jwks.json`. */
export interface JsonWebKeySet {
  keys: Array<Record<string, unknown>>;
}

export interface VerifyAgentIdentityOptions {
  /** Your `client_id` (the token's `aud`). */
  audience: string;
  /** Default https://id.agentboxd.com. */
  issuer?: string;
  /** The nonce you gave the agent, if any: the token's `nonce` must equal it. */
  nonce?: string;
  /**
   * Single-use enforcement. Strongly recommended unless you exchange the token at the issuer's token
   * endpoint (JWT bearer grant), which enforces single use centrally.
   */
  replayCache?: ReplayCache;
  /** Seconds of clock skew allowed on exp/iat. Default 30. */
  clockTolerance?: number;
  /** Reject tokens without `https://agentboxd.com/claims/agent: true`. Default true. */
  requireAgent?: boolean;
  /** Default `{issuer}/.well-known/jwks.json`. */
  jwksUri?: string;
  /** A key set to use instead of fetching `jwksUri` (tests, air-gapped verifiers). */
  jwks?: JsonWebKeySet;
}

/** The raw claims of an Agentboxd ID token. */
export interface AgentIdentityClaims {
  iss: string;
  sub: string;
  aud: string | string[];
  iat: number;
  exp: number;
  jti: string;
  auth_time?: number;
  nonce?: string;
  email?: string;
  email_verified?: boolean;
  name?: string;
  preferred_username?: string;
  [claim: string]: unknown;
}

export interface AgentWorkspace {
  id: string;
  name: string;
}

export interface VerifiedAgentIdentity {
  /** Stable subject: pairwise per client by default, else the inbox id. Key your user record on it. */
  sub: string;
  /** The inbox address (scope `email`), else null. Always null for an identity-only agent. */
  email: string | null;
  emailVerified: boolean;
  /** Scope `profile`: the agent's display name, else its handle. */
  name: string | null;
  /** Scope `profile`: the agent's handle (address local part). Not unique across domains. */
  username: string | null;
  isAgent: boolean;
  /**
   * false for an identity-only agent: it has no mailbox, so there is no email to contact it at. True for
   * inboxes (and for tokens from issuers older than the claim).
   */
  mailbox: boolean;
  workspace: AgentWorkspace | null;
  jti: string;
  issuer: string;
  audience: string;
  issuedAt: Date;
  expiresAt: Date;
  claims: AgentIdentityClaims;
}

export type AgentIdentityErrorCode =
  | 'jose_missing'
  | 'invalid_token'
  | 'token_expired'
  | 'nonce_mismatch'
  | 'not_agent'
  | 'token_replayed';

export class AgentIdentityError extends Error {
  constructor(
    public readonly code: AgentIdentityErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'AgentIdentityError';
  }
}

type Jose = typeof import('jose');
type GetKey = ReturnType<Jose['createRemoteJWKSet']> | ReturnType<Jose['createLocalJWKSet']>;

let josePromise: Promise<Jose> | undefined;
async function loadJose(): Promise<Jose> {
  josePromise ??= import('jose').catch((err: unknown) => {
    josePromise = undefined;
    throw new AgentIdentityError(
      'jose_missing',
      `verifyAgentIdentityToken needs the "jose" package: npm install jose (${(err as Error).message})`,
    );
  });
  return josePromise;
}

/** One remote key set per JWKS URL, so its cache (and unknown-kid refetch cooldown) is shared. */
const remoteSets = new Map<string, GetKey>();

const isWorkspace = (v: unknown): v is AgentWorkspace =>
  typeof v === 'object' && v !== null && typeof (v as AgentWorkspace).id === 'string' && typeof (v as AgentWorkspace).name === 'string';

/**
 * Verifies an Agentboxd identity token (docs: https://agentboxd.com/docs/agent-identity): ES256
 * signature against the issuer's JWKS, `typ: JWT`, `iss`, `aud`, `exp`/`iat` (with clock tolerance,
 * at most 300 s lifetime), `nonce`, the agent claim, and single use through `replayCache`.
 * Throws AgentIdentityError.
 */
export async function verifyAgentIdentityToken(token: string, opts: VerifyAgentIdentityOptions): Promise<VerifiedAgentIdentity> {
  if (!opts || typeof opts.audience !== 'string' || !opts.audience) {
    throw new TypeError('verifyAgentIdentityToken: options.audience (your client_id) is required');
  }
  const jose = await loadJose();
  const issuer = (opts.issuer ?? DEFAULT_IDENTITY_ISSUER).replace(/\/+$/, '');
  const tolerance = opts.clockTolerance ?? 30;

  let getKey: GetKey;
  if (opts.jwks) {
    getKey = jose.createLocalJWKSet(opts.jwks as Parameters<Jose['createLocalJWKSet']>[0]);
  } else {
    const uri = opts.jwksUri ?? `${issuer}/.well-known/jwks.json`;
    let set = remoteSets.get(uri);
    if (!set) {
      set = jose.createRemoteJWKSet(new URL(uri));
      remoteSets.set(uri, set);
    }
    getKey = set;
  }

  let claims: AgentIdentityClaims;
  try {
    const { payload } = await jose.jwtVerify(token, getKey, {
      issuer,
      audience: opts.audience,
      algorithms: ['ES256'],
      typ: 'JWT',
      clockTolerance: tolerance,
      maxTokenAge: MAX_IDENTITY_TOKEN_SECONDS,
      requiredClaims: ['iss', 'sub', 'aud', 'iat', 'exp', 'jti'],
    });
    claims = payload as AgentIdentityClaims;
  } catch (err) {
    if (err instanceof jose.errors.JWTExpired) throw new AgentIdentityError('token_expired', 'identity token expired');
    throw new AgentIdentityError('invalid_token', `invalid identity token: ${(err as Error).message}`);
  }

  const now = Date.now() / 1000;
  if (claims.iat > now + tolerance) throw new AgentIdentityError('invalid_token', 'identity token iat is in the future');
  if (claims.exp - claims.iat > MAX_IDENTITY_TOKEN_SECONDS) {
    throw new AgentIdentityError('invalid_token', `identity token lives longer than ${MAX_IDENTITY_TOKEN_SECONDS} s`);
  }
  if (opts.nonce !== undefined && claims.nonce !== opts.nonce) throw new AgentIdentityError('nonce_mismatch', 'identity token nonce does not match');
  const isAgent = claims[AGENT_CLAIM] === true;
  if ((opts.requireAgent ?? true) && !isAgent) throw new AgentIdentityError('not_agent', 'identity token is not an agent identity');
  if (opts.replayCache && !(await opts.replayCache.use(claims.jti, claims.exp))) {
    throw new AgentIdentityError('token_replayed', 'identity token was already used');
  }

  const workspace = claims[WORKSPACE_CLAIM];
  return {
    sub: claims.sub,
    email: typeof claims.email === 'string' ? claims.email : null,
    emailVerified: claims.email_verified === true,
    name: typeof claims.name === 'string' ? claims.name : null,
    username: typeof claims.preferred_username === 'string' ? claims.preferred_username : null,
    isAgent,
    mailbox: claims[MAILBOX_CLAIM] !== false,
    workspace: isWorkspace(workspace) ? { id: workspace.id, name: workspace.name } : null,
    jti: claims.jti,
    issuer: claims.iss,
    audience: opts.audience,
    issuedAt: new Date(claims.iat * 1000),
    expiresAt: new Date(claims.exp * 1000),
    claims,
  };
}

// ---------- agent message signatures (https://agentboxd.com/docs/agent-messaging#verify-a-message-outside-agentboxd) ----------

/** JOSE `typ` of agent message signatures. */
export const AGENT_MESSAGE_TYP = 'agentboxd-msg+jwt';
/** Default freshness window for `task` and `event` messages (seconds). Plain messages have none by default. */
export const DEFAULT_AGENT_MESSAGE_MAX_AGE_SECONDS = 900;
/** Replay entries are kept this long when no freshness window applies. */
const REPLAY_WITHOUT_MAX_AGE_SECONDS = 86_400;

export type AgentMessageAssurance = 'unclaimed' | 'workspace' | 'domain_verified' | 'org_verified';

/** One key of `{issuer}/.well-known/agent-keys.json`: a public JWK plus its lifecycle. */
export interface AgentKey {
  kid: string;
  kty: string;
  alg?: string;
  status: 'active' | 'retired' | 'revoked';
  revoked_at?: string | null;
  [member: string]: unknown;
}

export interface AgentKeySet {
  keys: AgentKey[];
}

/** The parts of an API message the signature covers (an `agentboxd` `Message` has them all). */
export interface AgentMessageLike {
  rfc_message_id: string;
  from: string;
  to: string[];
  cc: string[];
  subject: string | null;
  text: string | null;
  html: string | null;
  data?: unknown;
  type?: string;
  in_reply_to: string | null;
  attachments: { sha256: string }[];
  agent?: { signature?: string | null } | null;
  /** The author signature (aSIM phase 2): checked against the delivery signature's agent_sig claim when both exist. */
  author?: { signature?: string | null } | null;
}

export interface VerifyAgentMessageOptions {
  /** Your inbox address: the signature's `aud` must be it (a copy made for someone else doesn't verify). */
  recipient: string;
  /** Default https://id.agentboxd.com. */
  issuer?: string;
  /** The JWS, when the message doesn't carry it in `agent.signature`. */
  signature?: string;
  /** Default `{issuer}/.well-known/agent-keys.json` (cached 5 minutes, refetched on an unknown key id). */
  keysUri?: string;
  /** A key set to use instead of fetching `keysUri` (tests, air-gapped verifiers). */
  keys?: AgentKeySet;
  /**
   * Reject signatures older than this (seconds). Default: 900 for `task` and `event`, none for `message`.
   * `null` turns the check off (archives, audits).
   */
  maxAgeSeconds?: number | null;
  /** Rejects a `nonce` seen before, until `iat + maxAgeSeconds` (a day without a window). */
  replayCache?: ReplayCache;
  /** Seconds of clock skew allowed. Default 30. */
  clockTolerance?: number;
  /** "Now" for the freshness check (tests). */
  currentDate?: Date;
  /**
   * Also ask the directory whether the sender is still in good standing (POST /v1/directory/verify, uncached, so a
   * revocation counts at once). Needs an Agentboxd API key with directory:read. Fails with `agent_revoked`,
   * `agent_suspended` or `agent_deleted`, or `revocation_check_failed` when the directory can't answer.
   */
  checkRevocation?: RevocationCheckOptions;
}

export interface RevocationCheckOptions {
  apiKey: string;
  /** Default https://api.agentboxd.com. */
  baseUrl?: string;
  /** A fetch implementation (default: the global one). */
  fetch?: typeof fetch;
}

export interface AgentMessageClaims {
  iss: string;
  v: number;
  jti: string;
  nonce: string;
  iat: number;
  msg_id: string;
  from: string;
  aud: string;
  to: string[];
  cc: string[];
  subject_sha256?: string;
  text_sha256?: string;
  html_sha256?: string;
  data_sha256?: string;
  att: string[];
  type: 'message' | 'task' | 'event';
  in_reply_to?: string;
  assurance: AgentMessageAssurance;
  card: boolean;
  /** AI disclosure of the sending workspace (servers with the trust layer): the signed form of `Agent-Disclosure`. */
  disclosure?: { agent: true; on_behalf_of?: string; operator: string | null };
  /** aSIM phase 2: binds this copy to the sender's own author signature (its key id and the SHA-256 of the JWS). */
  agent_sig?: { kid: string; jws_sha256: string };
  [claim: string]: unknown;
}

export interface VerifiedAgentMessage {
  /** The sender, as Agentboxd verified it at delivery. */
  from: string;
  recipient: string;
  assurance: AgentMessageAssurance;
  type: 'message' | 'task' | 'event';
  msgId: string;
  jti: string;
  nonce: string;
  kid: string;
  issuedAt: Date;
  claims: AgentMessageClaims;
}

export type AgentMessageErrorCode =
  | 'jose_missing'
  | 'canonicalize_missing'
  | 'no_signature'
  | 'invalid_signature'
  | 'unknown_key'
  | 'key_revoked'
  | 'wrong_issuer'
  | 'wrong_audience'
  | 'content_mismatch'
  | 'too_old'
  | 'issued_in_future'
  | 'replayed'
  | 'agent_revoked'
  | 'agent_suspended'
  | 'agent_deleted'
  | 'revocation_check_failed';

export class AgentMessageVerificationError extends Error {
  constructor(
    public readonly code: AgentMessageErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'AgentMessageVerificationError';
  }
}

type Canonicalize = (input: unknown) => string | undefined;
let canonicalizePromise: Promise<Canonicalize> | undefined;
/** RFC 8785 through the `canonicalize` package (optional peer dependency, needed only for messages with data). */
async function loadCanonicalize(): Promise<Canonicalize> {
  canonicalizePromise ??= import('canonicalize')
    .then((m: unknown) => {
      const mod = m as Canonicalize | { default: Canonicalize | { default: Canonicalize } };
      if (typeof mod === 'function') return mod;
      const d = mod.default;
      return typeof d === 'function' ? d : d.default;
    })
    .catch((err: unknown) => {
      canonicalizePromise = undefined;
      throw new AgentMessageVerificationError(
        'canonicalize_missing',
        `verifying a message with data needs the "canonicalize" package: npm install canonicalize (${(err as Error).message})`,
      );
    });
  return canonicalizePromise;
}

async function loadJoseFor(): Promise<Jose> {
  try {
    return await loadJose();
  } catch (err) {
    throw new AgentMessageVerificationError('jose_missing', (err as Error).message.replace('verifyAgentIdentityToken', 'verifyAgentMessage'));
  }
}

const keyCache = new Map<string, { at: number; keys: AgentKeySet }>();
const KEY_CACHE_MS = 300_000;

async function fetchAgentKeys(uri: string, fresh: boolean): Promise<AgentKeySet> {
  const hit = keyCache.get(uri);
  if (hit && !fresh && Date.now() - hit.at < KEY_CACHE_MS) return hit.keys;
  const res = await fetch(uri, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new AgentMessageVerificationError('unknown_key', `could not fetch ${uri}: HTTP ${res.status}`);
  const keys = (await res.json()) as AgentKeySet;
  keyCache.set(uri, { at: Date.now(), keys });
  return keys;
}

const bare = (address: string) => (/<([^<>]+)>\s*$/.exec(address)?.[1] ?? address).trim().toLowerCase();
const addressSet = (list: readonly string[]) => [...new Set(list.map(bare).filter(Boolean))].sort();
const lf = (s: string) => s.replace(/\r\n?/g, '\n');

function b64u(bytes: Uint8Array): string {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function sha256b64u(value: string): Promise<string> {
  return b64u(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))));
}

function hexToB64u(hex: string): string {
  const clean = hex.toLowerCase();
  const bytes = new Uint8Array(clean.length / 2);
  for (let i = 0; i < bytes.length; i++) bytes[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  return b64u(bytes);
}

const sameList = (a: readonly string[], b: readonly string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

/** Which claims don't match the message held (empty = all match). */
async function contentMismatches(m: AgentMessageLike, c: AgentMessageClaims): Promise<string[]> {
  const bad: string[] = [];
  const hashed = async (value: string | null | undefined, claim: string | undefined, name: string, normalize = false) => {
    const expected = value === null || value === undefined ? undefined : await sha256b64u(normalize ? lf(value) : value);
    if (expected !== claim) bad.push(name);
  };
  if (m.rfc_message_id !== c.msg_id) bad.push('msg_id');
  if (bare(m.from) !== c.from) bad.push('from');
  if (!sameList(addressSet(m.to), c.to ?? [])) bad.push('to');
  if (!sameList(addressSet(m.cc), c.cc ?? [])) bad.push('cc');
  await hashed(m.subject, c.subject_sha256, 'subject');
  await hashed(m.text, c.text_sha256, 'text', true);
  await hashed(m.html, c.html_sha256, 'html', true);
  const hasData = m.data !== undefined && m.data !== null;
  if (hasData || c.data_sha256 !== undefined) {
    const canonical = hasData ? (await loadCanonicalize())(m.data) : undefined;
    const expected = canonical === undefined ? undefined : await sha256b64u(canonical);
    if (expected !== c.data_sha256) bad.push('data');
  }
  const att = m.attachments.map((a) => hexToB64u(a.sha256)).sort();
  if (!sameList(att, c.att ?? [])) bad.push('attachments');
  if ((m.type ?? 'message') !== c.type) bad.push('type');
  if ((m.in_reply_to ?? undefined) !== c.in_reply_to) bad.push('in_reply_to');
  const author = m.author?.signature?.replace(/\s+/g, '');
  if (c.agent_sig && author && (await sha256b64u(author)) !== c.agent_sig.jws_sha256) bad.push('author');
  return bad;
}

/** The directory's live answer about a signature's sender (`checkRevocation`). */
async function checkSenderStanding(signature: string, opts: RevocationCheckOptions): Promise<void> {
  const base = (opts.baseUrl ?? 'https://api.agentboxd.com').replace(/\/+$/, '');
  const doFetch = opts.fetch ?? globalThis.fetch;
  let body: { status?: string | null; reasons?: string[]; error?: { code?: string; message?: string } };
  let status: number;
  try {
    const res = await doFetch(`${base}/v1/directory/verify`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${opts.apiKey}`, 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ signature }),
    });
    status = res.status;
    body = (await res.json()) as typeof body;
  } catch (err) {
    throw new AgentMessageVerificationError('revocation_check_failed', `the directory could not be reached: ${(err as Error).message}`);
  }
  if (status !== 200) {
    throw new AgentMessageVerificationError('revocation_check_failed', `directory verify answered HTTP ${status}: ${body.error?.code ?? 'error'}`);
  }
  if (body.status === 'revoked' || body.status === 'suspended' || body.status === 'deleted') {
    throw new AgentMessageVerificationError(`agent_${body.status}`, `the sender's aSIM is ${body.status} now (directory verify)`);
  }
  if (body.status !== 'active') {
    throw new AgentMessageVerificationError('revocation_check_failed', `the directory did not confirm the signature: ${(body.reasons ?? []).join(', ') || 'unknown'}`);
  }
}

/**
 * Verifies an agent message's delivery signature outside Agentboxd (docs: https://agentboxd.com/docs/agent-messaging):
 * ES256 against the issuer's agent-keys.json (a key revoked at or before `iat` fails), `typ`, `iss`, `aud` = your
 * address, the content hashes against the message you hold, freshness (`maxAgeSeconds`) and replay (`replayCache`,
 * keyed by `nonce`) and, with `checkRevocation`, the sender's live status in the directory. Throws
 * AgentMessageVerificationError.
 *
 * Inside Agentboxd you don't need it: `message.agent.verified` already says the sender was verified at delivery.
 * Use it to prove a task's origin to your own backend, an auditor or another service. A verified sender is not
 * trustworthy content.
 */
export async function verifyAgentMessage(message: AgentMessageLike, opts: VerifyAgentMessageOptions): Promise<VerifiedAgentMessage> {
  if (!opts || typeof opts.recipient !== 'string' || !opts.recipient) {
    throw new TypeError('verifyAgentMessage: options.recipient (your inbox address) is required');
  }
  const jose = await loadJoseFor();
  const issuer = (opts.issuer ?? DEFAULT_IDENTITY_ISSUER).replace(/\/+$/, '');
  const tolerance = opts.clockTolerance ?? 30;
  const signature = (opts.signature ?? message.agent?.signature ?? '').replace(/\s+/g, '');
  if (!signature) throw new AgentMessageVerificationError('no_signature', 'the message carries no agent signature (not an agent-channel copy)');

  let header: { alg?: string; kid?: string; typ?: string };
  try {
    header = jose.decodeProtectedHeader(signature) as typeof header;
  } catch {
    throw new AgentMessageVerificationError('invalid_signature', 'not a compact JWS');
  }
  if (header.alg !== 'ES256' || header.typ !== AGENT_MESSAGE_TYP || !header.kid) {
    throw new AgentMessageVerificationError('invalid_signature', `expected alg ES256, typ ${AGENT_MESSAGE_TYP} and a kid`);
  }

  const uri = opts.keysUri ?? `${issuer}/.well-known/agent-keys.json`;
  let keySet = opts.keys ?? (await fetchAgentKeys(uri, false));
  let key = keySet.keys.find((k) => k.kid === header.kid);
  if (!key && !opts.keys) {
    keySet = await fetchAgentKeys(uri, true); // rotated since the last fetch
    key = keySet.keys.find((k) => k.kid === header.kid);
  }
  if (!key) throw new AgentMessageVerificationError('unknown_key', `no agent signing key ${header.kid} at ${opts.keys ? 'the given key set' : uri}`);

  let claims: AgentMessageClaims;
  try {
    const { status: _s, revoked_at: _r, created_at: _c, retired_at: _t, ...jwk } = key;
    const publicKey = await jose.importJWK(jwk as Parameters<Jose['importJWK']>[0], 'ES256');
    const { payload } = await jose.compactVerify(signature, publicKey, { algorithms: ['ES256'] });
    claims = JSON.parse(new TextDecoder().decode(payload)) as AgentMessageClaims;
  } catch (err) {
    throw new AgentMessageVerificationError('invalid_signature', `signature does not verify: ${(err as Error).message}`);
  }
  if (typeof claims.iat !== 'number' || typeof claims.nonce !== 'string' || typeof claims.aud !== 'string') {
    throw new AgentMessageVerificationError('invalid_signature', 'missing iat, nonce or aud');
  }
  if (key.status === 'revoked' && key.revoked_at && Date.parse(key.revoked_at) / 1000 <= claims.iat) {
    throw new AgentMessageVerificationError('key_revoked', `key ${key.kid} was revoked at ${key.revoked_at}, before this signature`);
  }
  if (claims.iss !== issuer) throw new AgentMessageVerificationError('wrong_issuer', `issuer is ${String(claims.iss)}, expected ${issuer}`);
  if (claims.aud !== bare(opts.recipient)) {
    throw new AgentMessageVerificationError('wrong_audience', `this copy was signed for ${claims.aud}, not ${bare(opts.recipient)}`);
  }
  const bad = await contentMismatches(message, claims);
  if (bad.length) throw new AgentMessageVerificationError('content_mismatch', `the message differs from what was signed: ${bad.join(', ')}`);

  const now = (opts.currentDate ?? new Date()).getTime() / 1000;
  if (claims.iat > now + tolerance) throw new AgentMessageVerificationError('issued_in_future', 'signature iat is in the future');
  const maxAge =
    opts.maxAgeSeconds === undefined ? (claims.type === 'message' ? null : DEFAULT_AGENT_MESSAGE_MAX_AGE_SECONDS) : opts.maxAgeSeconds;
  if (maxAge !== null && now - claims.iat > maxAge + tolerance) {
    throw new AgentMessageVerificationError('too_old', `signed ${Math.round(now - claims.iat)} s ago; the limit is ${maxAge} s`);
  }
  if (opts.replayCache && !(await opts.replayCache.use(claims.nonce, claims.iat + (maxAge ?? REPLAY_WITHOUT_MAX_AGE_SECONDS)))) {
    throw new AgentMessageVerificationError('replayed', 'this signature was already accepted (nonce seen before)');
  }
  if (opts.checkRevocation) await checkSenderStanding(signature, opts.checkRevocation);

  return {
    from: claims.from,
    recipient: claims.aud,
    assurance: claims.assurance,
    type: claims.type,
    msgId: claims.msg_id,
    jti: claims.jti,
    nonce: claims.nonce,
    kid: header.kid,
    issuedAt: new Date(claims.iat * 1000),
    claims,
  };
}

// ---------- agent-held keys and author signatures (aSIM phase 2, https://agentboxd.com/docs/agent-directory) ----------

/** JOSE `typ` of author signatures (made by the agent's own key). */
export const AUTHOR_SIGNATURE_TYP = 'agentboxd-author+jwt';
/** JOSE `typ` of a key registration proof. */
export const KEY_PROOF_TYP = 'agentboxd-key-proof+jwt';
/** `aud` of a key registration proof. */
export const KEY_PROOF_AUDIENCE = 'agentboxd:agent-key';

export type AgentKeyAlg = 'EdDSA' | 'ES256';

/** A WebCrypto key (structural, so the types don't need the DOM lib or jose). */
export interface CryptoKey {
  readonly type: string;
  readonly extractable: boolean;
  readonly algorithm: unknown;
  readonly usages: readonly string[];
}

/** A public Ed25519 (OKP) or P-256 (EC) JWK: the only members sent to Agentboxd. */
export interface AgentPublicJwk {
  kty: 'OKP' | 'EC';
  crv: 'Ed25519' | 'P-256';
  x: string;
  y?: string;
}

/**
 * An agent's own signing key. Keep `privateKey` secret (store `privateJwk` in your secret manager); only
 * `publicJwk` goes to Agentboxd.
 */
export interface GeneratedAgentKey {
  alg: AgentKeyAlg;
  /** RFC 7638 thumbprint of `publicJwk`: the key id Agentboxd uses. */
  kid: string;
  publicJwk: AgentPublicJwk;
  /** The private key as a JWK (for storage). */
  privateJwk: Record<string, unknown>;
  privateKey: CryptoKey;
}

/** A stored key to sign with: the private key (CryptoKey or JWK), its kid and alg. */
export interface AgentSigningKey {
  privateKey: CryptoKey | Record<string, unknown>;
  kid: string;
  alg: AgentKeyAlg;
}

async function loadJoseForKeys(): Promise<Jose> {
  try {
    return await loadJose();
  } catch (err) {
    throw new AuthorSignatureError('jose_missing', (err as Error).message.replace('verifyAgentIdentityToken', 'agent keys'));
  }
}

const publicMembers = (j: Record<string, unknown>): AgentPublicJwk =>
  j.kty === 'OKP'
    ? { kty: 'OKP', crv: 'Ed25519', x: String(j.x) }
    : { kty: 'EC', crv: 'P-256', x: String(j.x), y: String(j.y) };

/** RFC 7638 thumbprint (SHA-256, base64url) of a public key: its Agentboxd key id. */
export async function agentKeyThumbprint(jwk: AgentPublicJwk | Record<string, unknown>): Promise<string> {
  const jose = await loadJoseForKeys();
  return jose.calculateJwkThumbprint(publicMembers(jwk as Record<string, unknown>) as Parameters<Jose['calculateJwkThumbprint']>[0], 'sha256');
}

/** Generates a key pair locally (Ed25519 by default, ES256 for P-256-only environments). Nothing is sent anywhere. */
export async function generateAgentKey(opts: { alg?: AgentKeyAlg } = {}): Promise<GeneratedAgentKey> {
  const jose = await loadJoseForKeys();
  const alg = opts.alg ?? 'EdDSA';
  const { publicKey, privateKey } = await jose.generateKeyPair(alg, { extractable: true });
  const publicJwk = publicMembers((await jose.exportJWK(publicKey)) as Record<string, unknown>);
  const kid = await agentKeyThumbprint(publicJwk);
  const privateJwk = { ...((await jose.exportJWK(privateKey)) as Record<string, unknown>), kid, alg };
  return { alg, kid, publicJwk, privateJwk, privateKey: privateKey as CryptoKey };
}

async function importPrivate(jose: Jose, key: CryptoKey | Record<string, unknown>, alg: AgentKeyAlg) {
  if (typeof (key as CryptoKey).type === 'string' && (key as CryptoKey).type === 'private') return key as CryptoKey;
  return jose.importJWK(key as Parameters<Jose['importJWK']>[0], alg);
}

const randomNonce = () => b64u(globalThis.crypto.getRandomValues(new Uint8Array(16)));

async function signCompact(jose: Jose, claims: Record<string, unknown>, key: AgentSigningKey, typ: string): Promise<string> {
  const privateKey = await importPrivate(jose, key.privateKey, key.alg);
  return new jose.CompactSign(new TextEncoder().encode(JSON.stringify(claims)))
    .setProtectedHeader({ alg: key.alg, kid: key.kid, typ })
    .sign(privateKey);
}

/**
 * The proof of possession for `agents.keys.register` (valid 5 minutes, single use): a JWS by the new key over
 * `{ aud, sub: the agent's address, jkt: its thumbprint, iat, nonce }`.
 */
export async function createKeyProof(input: {
  privateKey: CryptoKey | Record<string, unknown>;
  publicJwk: AgentPublicJwk | Record<string, unknown>;
  /** The agent's (inbox) address the key is registered for. */
  address: string;
  alg?: AgentKeyAlg;
  /** Seconds since the epoch (tests). */
  iat?: number;
}): Promise<string> {
  const jose = await loadJoseForKeys();
  const pub = publicMembers(input.publicJwk as Record<string, unknown>);
  const alg = input.alg ?? (pub.kty === 'OKP' ? 'EdDSA' : 'ES256');
  const kid = await agentKeyThumbprint(pub);
  return signCompact(
    jose,
    { aud: KEY_PROOF_AUDIENCE, sub: input.address.trim().toLowerCase(), jkt: kid, iat: input.iat ?? Math.floor(Date.now() / 1000), nonce: randomNonce() },
    { privateKey: input.privateKey, kid, alg },
    KEY_PROOF_TYP,
  );
}

/** What an author signature covers (the same shape `messages.sendSigned` hands to its signer). */
export interface AuthorSignInput {
  /** The sending agent's address. */
  from: string;
  /** The final subject (a reply's is `Re: …`). Optional: covered only when given. */
  subject?: string;
  /** Exactly as sent; covered iff given. */
  text?: string;
  html?: string;
  data?: unknown;
  type?: 'message' | 'task' | 'event';
  /** Raw bytes of each attachment, or its SHA-256 hex. */
  attachments?: (Uint8Array | string)[];
  /** Final header recipients (optional: covered only when given). */
  to?: string[];
  cc?: string[];
  inReplyTo?: string;
  /** Seconds since the epoch (tests). */
  iat?: number;
  nonce?: string;
}

async function sha256Bytes(bytes: Uint8Array): Promise<string> {
  return b64u(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes as Uint8Array<ArrayBuffer>)));
}

const HEX_RE = /^[0-9a-fA-F]{64}$/;

/** The author claims for `input` (docs/asim-phase2-contract.md §1.4). */
export async function authorClaims(input: AuthorSignInput): Promise<Record<string, unknown>> {
  const att = await Promise.all(
    (input.attachments ?? []).map((a) => (typeof a === 'string' && HEX_RE.test(a) ? hexToB64u(a) : sha256Bytes(typeof a === 'string' ? new TextEncoder().encode(a) : a))),
  );
  const c: Record<string, unknown> = {
    v: 1,
    from: bare(input.from),
    iat: input.iat ?? Math.floor(Date.now() / 1000),
    nonce: input.nonce ?? randomNonce(),
    type: input.type ?? 'message',
    att: att.sort(),
  };
  if (input.text !== undefined) c.text_sha256 = await sha256b64u(lf(input.text));
  if (input.html !== undefined) c.html_sha256 = await sha256b64u(lf(input.html));
  if (input.data !== undefined && input.data !== null) {
    const canonical = (await loadCanonicalize())(input.data);
    if (canonical === undefined) throw new TypeError('data is not JSON-serializable');
    c.data_sha256 = await sha256b64u(canonical);
  }
  if (input.subject !== undefined) c.subject_sha256 = await sha256b64u(input.subject);
  if (input.to !== undefined) c.to = addressSet(input.to);
  if (input.cc !== undefined) c.cc = addressSet(input.cc);
  if (input.inReplyTo !== undefined) c.in_reply_to = input.inReplyTo;
  return c;
}

/** Signs authored content with the agent's own key: the `agent_signature` of send/reply. */
export async function signAgentMessage(input: AuthorSignInput & AgentSigningKey): Promise<string> {
  const jose = await loadJoseForKeys();
  return signCompact(jose, await authorClaims(input), input, AUTHOR_SIGNATURE_TYP);
}

/** A signer for `mr.messages.sendSigned(inboxId, input, agentSigner(key))`. */
export function agentSigner(key: AgentSigningKey): (content: AuthorSignInput) => Promise<string> {
  return (content) => signAgentMessage({ ...content, ...key });
}

export type AuthorSignatureErrorCode =
  | 'jose_missing'
  | 'canonicalize_missing'
  | 'no_signature'
  | 'malformed'
  | 'wrong_type'
  | 'unknown_key'
  | 'key_revoked'
  | 'bad_signature'
  | 'wrong_sender'
  | 'content_mismatch';

export class AuthorSignatureError extends Error {
  constructor(
    public readonly code: AuthorSignatureErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'AuthorSignatureError';
  }
}

/** The parts of an API message an author signature covers. */
export interface AuthoredMessageLike {
  from: string;
  to: string[];
  cc: string[];
  subject: string | null;
  text: string | null;
  html: string | null;
  data?: unknown;
  type?: string;
  in_reply_to: string | null;
  attachments: { sha256: string }[];
  author?: { signature?: string | null } | null;
}

/** One published agent key (a card's `keys.agent`, or the public `keys.json`). */
export interface PublishedAgentKeyLike {
  kid: string;
  kty: string;
  alg?: string;
  status: 'active' | 'retired' | 'revoked';
  revoked_at?: string | null;
  [member: string]: unknown;
}

export interface VerifiedAuthorSignature {
  from: string;
  kid: string;
  alg: AgentKeyAlg;
  iat: number;
  /** What the signature covers; anything false is not the author's statement (e.g. an automatic text part). */
  covered: { subject: boolean; text: boolean; html: boolean; data: boolean; attachments: boolean; recipients: boolean; in_reply_to: boolean };
  claims: Record<string, unknown>;
}

/**
 * Verifies a message's author signature (docs/asim-phase2-contract.md §1.5) against the agent's published keys
 * (`card.keys.agent` from `directory.resolve`, or `publicDirectory.keys(address)`): the key (a key revoked at or
 * before `iat` fails), the signature, the sender and every claim present. Throws AuthorSignatureError.
 */
export async function verifyAuthorSignature(
  message: AuthoredMessageLike,
  opts: { keys: PublishedAgentKeyLike[] | { keys: PublishedAgentKeyLike[] }; signature?: string },
): Promise<VerifiedAuthorSignature> {
  const jose = await loadJoseForKeys();
  const jws = (opts.signature ?? message.author?.signature ?? '').replace(/\s+/g, '');
  if (!jws) throw new AuthorSignatureError('no_signature', 'the message carries no author signature');
  let header: { alg?: string; kid?: string; typ?: string };
  try {
    header = jose.decodeProtectedHeader(jws) as typeof header;
  } catch {
    throw new AuthorSignatureError('malformed', 'not a compact JWS');
  }
  if (header.typ !== AUTHOR_SIGNATURE_TYP || (header.alg !== 'EdDSA' && header.alg !== 'ES256') || !header.kid) {
    throw new AuthorSignatureError('wrong_type', `expected typ ${AUTHOR_SIGNATURE_TYP}, alg EdDSA or ES256 and a kid`);
  }
  const alg = header.alg as AgentKeyAlg;
  const keys = Array.isArray(opts.keys) ? opts.keys : opts.keys.keys;
  const key = keys.find((k) => k.kid === header.kid);
  if (!key || (key.alg !== undefined && key.alg !== alg)) throw new AuthorSignatureError('unknown_key', `no agent key ${header.kid} in the given keys`);
  let claims: Record<string, unknown>;
  try {
    const publicKey = await jose.importJWK(publicMembers(key) as Parameters<Jose['importJWK']>[0], alg);
    const { payload } = await jose.compactVerify(jws, publicKey, { algorithms: [alg] });
    claims = JSON.parse(new TextDecoder().decode(payload)) as Record<string, unknown>;
  } catch (err) {
    throw new AuthorSignatureError('bad_signature', `signature does not verify: ${(err as Error).message}`);
  }
  if (typeof claims.iat !== 'number' || claims.v !== 1) throw new AuthorSignatureError('malformed', 'missing iat or unknown version');
  if (key.status === 'revoked' && key.revoked_at && Date.parse(key.revoked_at) / 1000 <= claims.iat) {
    throw new AuthorSignatureError('key_revoked', `key ${key.kid} was revoked at ${key.revoked_at}, before this signature`);
  }
  if (claims.from !== bare(message.from)) throw new AuthorSignatureError('wrong_sender', `signed by ${String(claims.from)}, sent by ${bare(message.from)}`);

  const bad: string[] = [];
  const check = async (claim: unknown, value: string | null | undefined, name: string, normalize: boolean) => {
    if (claim === undefined) return false;
    if (value === null || value === undefined || claim !== (await sha256b64u(normalize ? lf(value) : value))) bad.push(name);
    return true;
  };
  const subject = await check(claims.subject_sha256, message.subject, 'subject', false);
  const text = await check(claims.text_sha256, message.text, 'text', true);
  const html = await check(claims.html_sha256, message.html, 'html', true);
  let data = false;
  const hasData = message.data !== undefined && message.data !== null;
  if (claims.data_sha256 !== undefined || hasData) {
    // Data is never added by the server: present data must be covered.
    const canonical = hasData ? (await loadCanonicalize().catch((e: unknown) => {
      throw new AuthorSignatureError('canonicalize_missing', (e as Error).message);
    }))(message.data) : undefined;
    const expected = canonical === undefined ? undefined : await sha256b64u(canonical);
    if (expected !== claims.data_sha256) bad.push('data');
    data = true;
  }
  const att = message.attachments.map((a) => hexToB64u(a.sha256)).sort();
  if (!Array.isArray(claims.att) || !sameList(att, [...(claims.att as string[])].sort())) bad.push('attachments');
  if ((message.type ?? 'message') !== claims.type) bad.push('type');
  let recipients = false;
  if (claims.to !== undefined || claims.cc !== undefined) {
    recipients = true;
    if (!sameList(addressSet(message.to), (claims.to as string[] | undefined) ?? [])) bad.push('to');
    if (!sameList(addressSet(message.cc), (claims.cc as string[] | undefined) ?? [])) bad.push('cc');
  }
  let inReplyTo = false;
  if (claims.in_reply_to !== undefined) {
    inReplyTo = true;
    if (message.in_reply_to !== claims.in_reply_to) bad.push('in_reply_to');
  }
  if (bad.length) throw new AuthorSignatureError('content_mismatch', `the message differs from what the author signed: ${bad.join(', ')}`);
  return {
    from: claims.from as string,
    kid: header.kid,
    alg,
    iat: claims.iat,
    covered: { subject, text, html, data, attachments: true, recipients, in_reply_to: inReplyTo },
    claims,
  };
}
