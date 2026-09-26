/**
 * A tiny sign-up app to run the Playwright test against: /signup takes an email address and "sends"
 * a 6-digit code, /verify checks it. Stand-in for your real app under test.
 *
 * It delivers the code email to a local Agentboxd dev stack through POST /dev/inbound (AGENTBOXD_BASE_URL,
 * default http://localhost:3000). Your own app would send a normal email instead, and the test
 * would not change.
 */
import { randomInt } from 'node:crypto';
import { createServer } from 'node:http';
import { deliverLocally } from '../_shared/dev-inbound.js';

const PORT = Number(process.env.DEMO_APP_PORT ?? 4400);
const AGENTBOXD_BASE_URL = process.env.AGENTBOXD_BASE_URL ?? 'http://localhost:3000';
const codes = new Map<string, string>(); // email → pending code

const page = (body: string) =>
  `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Acme sign-up</title></head><body><main>${body}</main></body></html>`;
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

async function form(req: import('node:http').IncomingMessage): Promise<URLSearchParams> {
  let raw = '';
  for await (const chunk of req) raw += chunk;
  return new URLSearchParams(raw);
}

createServer(async (req, res) => {
  const url = new URL(req.url ?? '/', `http://localhost:${PORT}`);
  const html = (status: number, body: string) => res.writeHead(status, { 'Content-Type': 'text/html; charset=utf-8' }).end(page(body));
  try {
    if (req.method === 'GET' && url.pathname === '/health') return void res.end('ok');
    if (req.method === 'GET' && url.pathname === '/signup') {
      return html(
        200,
        `<h1>Create your account</h1><form method="post" action="/signup"><label>Email <input name="email" type="email" required></label><button>Sign up</button></form>`,
      );
    }
    if (req.method === 'POST' && url.pathname === '/signup') {
      const email = (await form(req)).get('email') ?? '';
      const code = String(randomInt(100000, 1000000));
      codes.set(email, code);
      await deliverLocally(AGENTBOXD_BASE_URL, {
        from: 'Acme <no-reply@acme.example>',
        to: email,
        subject: 'Your Acme verification code',
        text: `Welcome to Acme.\n\nYour verification code is ${code}. It expires in 10 minutes.\n\nIf you didn't sign up, ignore this email.`,
      });
      return html(
        200,
        `<h1>Check your email</h1><p>We sent a code to ${esc(email)}.</p><form method="post" action="/verify"><input type="hidden" name="email" value="${esc(email)}"><label>Verification code <input name="code" inputmode="numeric" required></label><button>Verify</button></form>`,
      );
    }
    if (req.method === 'POST' && url.pathname === '/verify') {
      const f = await form(req);
      const ok = codes.get(f.get('email') ?? '') === f.get('code');
      return html(ok ? 200 : 400, ok ? '<h1>Welcome to Acme</h1><p>Your email is verified.</p>' : '<h1>Wrong code</h1>');
    }
    html(404, '<h1>Not found</h1>');
  } catch (err) {
    console.error(err);
    res.writeHead(500).end('error');
  }
}).listen(PORT, () => console.log(`demo app on http://localhost:${PORT}/signup`));
