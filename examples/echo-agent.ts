/**
 * Echo agent: the end-to-end demo.
 *
 * On start it gets-or-creates its inbox (idempotent via client_id), registers a webhook for new mail
 * (message.received, message.enriched, message.released), then replies once to each new email with its word and
 * attachment count (echo-reply.ts). Its text quotes nothing the sender wrote, but the server sets the subject to
 * "Re: <their subject>", so it answers only the From address: mail with a Reply-To to another address is skipped.
 * It also skips automatic replies, bulk and list mail, bounces, mail that failed SPF or DMARC (the sender may be
 * forged), and mail labelled as phishing, prompt injection or spam. In a workspace that screens agent mail, an event
 * whose content is withheld (not screened yet, or held) is skipped: a later one brings the content
 * (/docs/api#screening-reads).
 *
 *   AGENTBOXD_API_KEY=mr_... npm run echo-agent
 *
 * Env:
 *   AGENTBOXD_API_KEY    required (legacy name MAILROOM_API_KEY also read)
 *   AGENTBOXD_BASE_URL   API base URL                    (default http://localhost:3000; legacy MAILROOM_URL)
 *   ECHO_PORT            local port for the webhook      (default 4000)
 *   ECHO_WEBHOOK_URL     URL the Agentboxd worker can reach this agent at
 *                        (default http://host.docker.internal:<port>/webhook, i.e. from Docker Compose)
 *   ECHO_USERNAME        inbox username                  (default echo)
 */
import http from 'node:http';
import { Agentboxd, type MessageEventData, verifyWebhook, type WebhookEvent } from '../sdk/src/index.js';
import { shouldReply, summarize } from './echo-reply.js';

const apiKey = process.env.AGENTBOXD_API_KEY || process.env.MAILROOM_API_KEY;
if (!apiKey) {
  console.error('Set AGENTBOXD_API_KEY (create one with: npm run create-key -- --org Default --name echo)');
  process.exit(1);
}
const port = Number(process.env.ECHO_PORT ?? 4000);
const webhookUrl = process.env.ECHO_WEBHOOK_URL ?? `http://host.docker.internal:${port}/webhook`;
const mr = new Agentboxd({ apiKey, baseUrl: process.env.AGENTBOXD_BASE_URL || process.env.MAILROOM_URL || 'http://localhost:3000' });

/** Events that can carry a new message's content. */
const MAIL_EVENTS = ['message.received', 'message.enriched', 'message.released'] as const;

async function main() {
  const inbox = await mr.inboxes.create({
    client_id: 'echo-agent',
    username: process.env.ECHO_USERNAME ?? 'echo',
    display_name: 'Echo Agent',
  });

  const existing = (await mr.webhooks.list()).data.find((w) => w.url === webhookUrl);
  if (existing) await mr.webhooks.delete(existing.id); // secrets are only shown at creation; re-register
  const webhook = await mr.webhooks.create({ url: webhookUrl, events: [...MAIL_EVENTS], inbox_ids: [inbox.id] });
  const secret = webhook.secret!;
  const answered = new Set<string>(); // message ids; the reply's idempotency key covers a restart

  const server = http.createServer((req, res) => {
    if (req.method !== 'POST' || req.url !== '/webhook') {
      res.writeHead(404).end();
      return;
    }
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => {
      const raw = Buffer.concat(chunks);
      // Header names kept from the original API.
      const sig = String(req.headers['x-mailroom-signature'] ?? '');
      const ts = String(req.headers['x-mailroom-timestamp'] ?? '');
      if (!verifyWebhook(sig, ts, raw, secret)) {
        res.writeHead(401).end('bad signature');
        return;
      }
      res.writeHead(200).end('ok'); // ack fast; do the work after
      const event = JSON.parse(raw.toString('utf8')) as WebhookEvent<MessageEventData>;
      if (!(MAIL_EVENTS as readonly string[]).includes(event.type)) return;
      const { message } = event.data;
      if (message.withheld || answered.has(message.id)) return;
      answered.add(message.id);
      if (!shouldReply(message, inbox.address)) {
        console.log(`skipping message ${message.id} (automatic, bulk, unauthenticated, suspicious or a Reply-To elsewhere)`);
        return;
      }
      mr.messages
        .reply(inbox.id, message.id, { text: summarize(message) }, { idempotencyKey: `echo-${message.id}` })
        .then((sent) => console.log(`replied to ${message.from} (thread ${sent.thread_id})`))
        .catch((err: unknown) => console.error('reply failed:', err));
    });
  });

  server.listen(port, () => {
    console.log(`Echo agent listening on :${port}`);
    console.log(`Inbox:   ${inbox.address}`);
    console.log(`Webhook: ${webhookUrl}`);
    console.log('Send it an email (or POST an .eml to /dev/inbound) and watch it reply.');
  });
}

main().catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
