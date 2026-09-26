# Sign in with Agentboxd: relying-party examples

Agentboxd is an OpenID Connect provider where an AI agent's identity is its inbox. These examples show
an app ("relying party") accepting that identity. Spec: [`docs/agent-identity-contract.md`](../../docs/agent-identity-contract.md);
docs: https://agentboxd.com/docs/agent-identity.

- Issuer: `https://id.agentboxd.com`
- Discovery: `https://id.agentboxd.com/.well-known/openid-configuration`
- JWKS: `https://id.agentboxd.com/.well-known/jwks.json`
- Signing: ES256 only. Scopes: `openid` (required), `email`, `profile`, `workspace`.
- Development issuer (local API): `http://localhost:3000/oidc`

## Which flow to use

| You have | Flow | Example |
| --- | --- | --- |
| An API or CLI that agents call directly, no browser | **Headless token, verified offline**: the agent calls `mr.identity.token({ inboxId, audience })` and sends you the ID token; you verify it against the JWKS and keep a `jti` replay cache | `headless-rp/` (`/login/verify`) |
| The same, but you'd rather the issuer enforce single use, or you already use a standard OAuth client | **Headless token + JWT bearer grant** (RFC 7523): you post the token to `/token` with `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer` and get a fresh ID token + access token; a replayed token gets `invalid_grant` | `headless-rp/` (`/login/exchange`) |
| A web app with a "Sign in with Agentboxd" button, where the agent's owner approves in a browser | **Authorization code + PKCE** (state, nonce and S256 PKCE required) through your auth library | `better-auth/`, `authjs/` |

All tokens live at most 5 minutes and there are no refresh tokens: an agent signs in again with one API call.

## Register your app

Dashboard → **Identity** → **Register an app** (or `POST /v1/identity/clients`, permission `identity:manage`):

- **Server app** (`confidential`): server-side apps. You get a `client_secret` once (store it; rotate from the dashboard).
- **Public app** (`public`): no secret; browser flow with PKCE and the JWT bearer grant.
- **Verify tokens only** (`verify_only`): no secret and no redirect URIs; only receives headless tokens and verifies them itself.

Redirect URIs are matched exactly: `https://…`, or `http://localhost` / `127.0.0.1` / `[::1]` (any port)
for development. The ones these libraries use:

- Better Auth: `{BETTER_AUTH_URL}/api/auth/callback/agentboxd`
- Auth.js: `https://your-app.com/api/auth/callback/agentboxd` (Next.js) or `/auth/callback/agentboxd` (other frameworks)

The agent's key needs `identity:sign` (preset **sign_in** = `inboxes:read` + `identity:sign`).

## Run

```bash
npm install
npm run typecheck
AGENTBOXD_CLIENT_ID=abxc_… AGENTBOXD_CLIENT_SECRET=abxs_… npm run headless-rp   # the app
AGENTBOXD_API_KEY=mr_… INBOX_ID=… AGENTBOXD_CLIENT_ID=abxc_… npm run agent      # the agent signs in
```

## What the ID token contains

`iss`, `sub`, `aud` (your `client_id`), `iat`, `exp` (≤ 300 s later), `auth_time`, `jti`, `nonce` (if
given), `email` + `email_verified: true` (scope `email`), `name` (scope `profile`),
`https://agentboxd.com/claims/agent: true` always, and `https://agentboxd.com/claims/workspace`
(`{ id, name }`) only with scope `workspace` when the agent's workspace opted in.

## Security notes

- **Key users on `sub`, not `email`.** `sub` is pairwise by default: stable for your app, different at
  every other app. `email` is the inbox address and the same everywhere; don't request it if you don't need it.
- **Enforce single use.** Offline verification must keep every accepted `jti` until its `exp`
  (`MemoryReplayCache` for one process; Redis `SET jti 1 NX EXAT exp` for several), or use the JWT bearer
  exchange, which enforces it centrally.
- **Bind tokens to a login attempt** by handing the agent a nonce and requiring it back (`/login/nonce`).
- **Check `aud`** equals your `client_id` and **`iss`** equals the issuer exactly; accept ES256 only.
  The SDK helper does this, with 30 s clock tolerance.
- **Treat agents as agents.** `https://agentboxd.com/claims/agent` is always `true`; use it to route
  agents to API-oriented onboarding or different limits, not to grant more trust.
- An inbox owner can turn the inbox's identity off at any time: new tokens, exchanges and `/userinfo` stop
  immediately; already-issued tokens expire within 5 minutes.
- Keep `client_secret` server-side only; never ship it in a browser or mobile app (use a public client there).
