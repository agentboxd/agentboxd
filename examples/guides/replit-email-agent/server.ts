/**
 * Webhook mode: a small HTTP server that Agentboxd calls on every `message.received`. Suits a Replit
 * Autoscale deployment (it scales to zero between emails) or a Reserved VM.
 *
 *   npx tsx server.ts        Secrets: AGENTBOXD_API_KEY, AGENTBOXD_WEBHOOK_SECRET (from setup.ts)
 */
import { createServer, type Server } from 'node:http';
import { pathToFileURL } from 'node:url';
import { Agentboxd, verifyWebhook, type EnvelopeEventData, type MessageEventData, type WebhookEvent } from 'agentboxd';
import { handleMessage } from './handle.js';

export function webhookServer(mr: Agentboxd, secret: string, log: (line: string) => void = console.log): Server {
  return createServer((req, res) => {
    // Health check: Replit's deployment check expects the home page to answer quickly.
    if (req.method === 'GET' && req.url === '/') {
      res.writeHead(200, { 'content-type': 'text/plain' }).end('ok');
      return;
    }
    if (req.method !== 'POST' || req.url !== '/webhook') {
      res.writeHead(404).end();
      return;
    }
    const chunks: Buffer[] = [];
    let size = 0;
    req.on('data', (c: Buffer) => {
      size += c.length;
      if (size > 1_000_000) req.destroy();
      else chunks.push(c);
    });
    req.on('end', () => {
      const raw = Buffer.concat(chunks); // verify the exact bytes, before any JSON parsing
      const ok = verifyWebhook(
        String(req.headers['x-mailroom-signature'] ?? ''),
        String(req.headers['x-mailroom-timestamp'] ?? ''),
        raw,
        secret,
      );
      if (!ok) {
        res.writeHead(401).end('bad signature');
        return;
      }
      const event = JSON.parse(raw.toString('utf8')) as WebhookEvent<EnvelopeEventData | MessageEventData>;
      // setup.ts subscribes with payload "envelope" (ids and subject, no content); a full payload works too.
      const id =
        event.type !== 'message.received' ? null : 'message_id' in event.data ? event.data.message_id : event.data.message.id;
      if (!id) {
        res.writeHead(204).end();
        return;
      }
      // The work happens inside the request: on Autoscale an instance only runs while it serves one.
      // A failure answers 500 and Agentboxd retries; a retry after a timeout (10 s) is safe because
      // handleMessage labels what it handled and sends with an idempotency key.
      handleMessage(mr, id)
        .then((outcome) => {
          log(`${id}: ${outcome}`);
          res.writeHead(204).end();
        })
        .catch((err: unknown) => {
          log(`${id}: failed: ${String(err)}`);
          res.writeHead(500).end();
        });
    });
  });
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) {
  const secret = process.env.AGENTBOXD_WEBHOOK_SECRET;
  if (!secret) throw new Error('Set the AGENTBOXD_WEBHOOK_SECRET secret (setup.ts prints it).');
  const port = Number(process.env.PORT ?? 3000);
  // 0.0.0.0, not localhost: a published Replit app can't reach a server bound to localhost only.
  webhookServer(new Agentboxd(), secret).listen(port, '0.0.0.0', () => console.log(`listening on :${port}`));
}
