/**
 * Using the provider. Next.js (next-auth v5), in auth.ts:
 *
 *   import NextAuth from 'next-auth';
 *   import Agentboxd from './agentboxd-provider';
 *   export const { handlers, auth, signIn, signOut } = NextAuth({
 *     providers: [Agentboxd({ clientId: process.env.AUTH_AGENTBOXD_ID, clientSecret: process.env.AUTH_AGENTBOXD_SECRET })],
 *   });
 *   // button: <form action={async () => { 'use server'; await signIn('agentboxd'); }}>…</form>
 *
 * Framework-free, with @auth/core directly (below). Callback URL: {origin}/auth/callback/agentboxd.
 */
import { Auth, type AuthConfig } from '@auth/core';
import Agentboxd, { AGENT_CLAIM } from './agentboxd-provider.js';

export const authConfig: AuthConfig = {
  basePath: '/auth',
  secret: process.env.AUTH_SECRET,
  trustHost: true,
  providers: [
    Agentboxd({
      clientId: process.env.AUTH_AGENTBOXD_ID,
      clientSecret: process.env.AUTH_AGENTBOXD_SECRET,
      // Development issuer, e.g. http://localhost:3000/oidc; omit in production.
      ...(process.env.AGENTBOXD_ISSUER ? { issuer: process.env.AGENTBOXD_ISSUER } : {}),
    }),
  ],
  callbacks: {
    // Keep "is this an agent?" on the session token (the profile is the verified ID token's claims).
    jwt({ token, profile }) {
      if (profile) token.isAgent = profile[AGENT_CLAIM] === true;
      return token;
    },
  },
};

/** Any Fetch-API server (Bun, Deno, Hono, Node with a Request adapter): route /auth/* here. */
export function handleAuth(request: Request): Promise<Response> {
  return Auth(request, authConfig);
}
