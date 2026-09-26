/**
 * "Sign in with Agentboxd" provider for Auth.js (NextAuth.js v5, @auth/core, @auth/sveltekit, ...).
 *
 * Auth.js reads `{issuer}/.well-known/openid-configuration`, then runs the authorization code flow
 * with state, PKCE (S256) and a nonce, and verifies the ID token. Register a client in the Agentboxd
 * dashboard (Identity → Apps, type "confidential") with the callback URL:
 *
 *   https://your-app.com/api/auth/callback/agentboxd   (Next.js; basePath /api/auth)
 *   https://your-app.com/auth/callback/agentboxd       (other frameworks; basePath /auth)
 */
import type { OIDCConfig, OIDCUserConfig } from '@auth/core/providers';

export const AGENTBOXD_ISSUER = 'https://id.agentboxd.com';
export const AGENT_CLAIM = 'https://agentboxd.com/claims/agent';

/** Claims of an Agentboxd ID token (docs/agent-identity-contract.md §3.2). */
export interface AgentboxdProfile extends Record<string, unknown> {
  iss: string;
  /** Pairwise per client by default: stable for this app, different at every other app. */
  sub: string;
  aud: string;
  email?: string;
  email_verified?: boolean;
  name?: string;
  'https://agentboxd.com/claims/agent': true;
  'https://agentboxd.com/claims/workspace'?: { id: string; name: string };
}

export default function Agentboxd(options: OIDCUserConfig<AgentboxdProfile>): OIDCConfig<AgentboxdProfile> {
  return {
    id: 'agentboxd',
    name: 'Agentboxd',
    type: 'oidc',
    issuer: AGENTBOXD_ISSUER,
    // Agentboxd requires all three for the browser flow.
    checks: ['pkce', 'state', 'nonce'],
    authorization: { params: { scope: 'openid email profile' } },
    profile(profile) {
      return {
        id: profile.sub,
        name: profile.name ?? profile.email ?? null,
        email: profile.email ?? null,
        image: null,
      };
    },
    style: { brandColor: '#111111', text: '#ffffff' },
    // User options last so `issuer` (self-hosted / development), `clientId`, `clientSecret`, ... can override.
    options,
  };
}
