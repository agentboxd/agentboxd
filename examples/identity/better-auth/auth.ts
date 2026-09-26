/**
 * "Sign in with Agentboxd" in a Better Auth app (browser flow: authorization code + PKCE).
 *
 * Better Auth's Generic OAuth plugin reads the discovery document, sends state, a PKCE S256 challenge
 * and a nonce, verifies the ID token against the JWKS and checks that it echoes the nonce.
 *
 * Register a client in the Agentboxd dashboard (Identity → Apps, type "confidential") with the
 * redirect URI Better Auth uses by default:
 *
 *   {BETTER_AUTH_URL}/api/auth/callback/agentboxd
 *
 * Env: AGENTBOXD_CLIENT_ID, AGENTBOXD_CLIENT_SECRET, AGENTBOXD_ISSUER (default https://id.agentboxd.com).
 */
import { betterAuth } from 'better-auth';
import { memoryAdapter } from 'better-auth/adapters/memory';
import { genericOAuth } from 'better-auth/plugins';

const ISSUER = process.env.AGENTBOXD_ISSUER ?? 'https://id.agentboxd.com';
/** Always `true` in Agentboxd ID tokens: the subject is an AI agent's inbox, not a person. */
const AGENT_CLAIM = 'https://agentboxd.com/claims/agent';

// Demo storage only: use your real database adapter in an app.
const db: Record<string, Record<string, unknown>[]> = { user: [], session: [], account: [], verification: [] };

export const auth = betterAuth({
  database: memoryAdapter(db),
  user: {
    // Keep track of which users are agents (from the agent claim).
    additionalFields: {
      isAgent: { type: 'boolean', required: false, defaultValue: false, input: false },
    },
  },
  plugins: [
    genericOAuth({
      config: [
        {
          providerId: 'agentboxd',
          name: 'Agentboxd',
          discoveryUrl: `${ISSUER}/.well-known/openid-configuration`,
          clientId: process.env.AGENTBOXD_CLIENT_ID ?? '',
          clientSecret: process.env.AGENTBOXD_CLIENT_SECRET ?? '',
          scopes: ['openid', 'email', 'profile'],
          pkce: true,
          // Fail at startup instead of silently decoding unverified ID tokens if discovery is unavailable.
          requireIdTokenVerification: true,
          mapProfileToUser: (profile) => ({
            name: typeof profile.name === 'string' ? profile.name : undefined,
            email: typeof profile.email === 'string' ? profile.email : null,
            // Agentboxd controls delivery to the inbox address, so it is verified by construction.
            emailVerified: profile.email_verified === true,
            isAgent: profile[AGENT_CLAIM] === true,
          }),
        },
      ],
    }),
  ],
});

/*
 * Client side (React, Vue, ...): the provider is a regular social provider.
 *
 *   import { createAuthClient } from 'better-auth/react';
 *   const authClient = createAuthClient();
 *   await authClient.signIn.social({ provider: 'agentboxd', callbackURL: '/dashboard' });
 */
