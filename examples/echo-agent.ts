/**
 * Echo agent: the end-to-end demo.
 *
 * On start it gets-or-creates its inbox (idempotent via client_id), registers a webhook for
 * message.received, then replies to every incoming email with a short summary of it.
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
import { Agentboxd, type Message, type MessageEventData, verifyWebhook, type WebhookEvent } from '../sdk/src/index.js';

const apiKey = process.env.AGENTBOXD_API_KEY || process.env.MAILROOM_API_KEY;
if (!apiKey) {
  console.error('Set AGENTBOXD_API_KEY (create one with: npm run create-key -- --org Default --name echo)');
  process.exit(1);
}
const port = Number(process.env.ECHO_PORT ?? 4000);
const webhookUrl = process.env.ECHO_WEBHOOK_URL ?? `http://host.docker.internal:${port}/webhook`;
const mr = new Agentboxd({ apiKey, baseUrl: process.env.AGENTBOXD_BASE_URL || process.env.MAILROOM_URL || 'http://localhost:3000' });

/** Deterministic "summary": first sentence, size, attachments. Swap in an LLM call here. */
export function summarize(message: Message): string {
  const body = (message.extracted_text ?? message.text ?? '').trim();
  const words = body ? body.split(/\s+/).length : 0;
  const firstSentence = body.split(/(?<=[.!?])\s+|\n/)[0]?.slice(0, 200) ?? '';
  const atts = message.attachments.filter((a) => !a.inline);
  const lines = [
    `Hi! I'm an echo agent. I received your message "${message.subject ?? '(no subject)'}".`,
    '',
    `Summary: ${words} word${words === 1 ? '' : 's'}${atts.length ? `, ${atts.length} attachment(s): ${atts.map((a) => a.filename ?? 'unnamed').join(', ')}` : ''}.`,
  ];
  if (firstSentence) lines.push(`It starts with: "${firstSentence}"`);
  return lines.join('\n');
}

/** Never answer bounces, auto-replies, lists or ourselves: that's how mail loops start. */
function shouldReply(message: Message, ownAddress: string): boolean {
  const h = (k: string) => {
    const v = message.headers[k];
    return (Array.isArray(v) ? v.join(' ') : (v ?? '')).toLowerCase();
  };
  const from = message.from.toLowerCase();
  if (from.includes(ownAddress.toLowerCase()) || /mailer-daemon|postmaster|no-?reply/.test(from)) return false;
  if (h('auto-submitted') && h('auto-submitted') !== 'no') return false;
  if (/bulk|list|junk/.test(h('precedence')) || h('list-id') || h('x-autoreply') || h('x-autorespond')) return false;
  return !message.labels.includes('spam');
}

async function main() {
  const inbox = await mr.inboxes.create({
    client_id: 'echo-agent',
    username: process.env.ECHO_USERNAME ?? 'echo',
    display_name: 'Echo Agent',
  });

  const existing = (await mr.webhooks.list()).data.find((w) => w.url === webhookUrl);
  if (existing) await mr.webhooks.delete(existing.id); // secrets are only shown at creation; re-register
  const webhook = await mr.webhooks.create({ url: webhookUrl, events: ['message.received'], inbox_ids: [inbox.id] });
  const secret = webhook.secret!;

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
      if (event.type !== 'message.received') return;
      const { message } = event.data;
      if (!shouldReply(message, inbox.address)) {
        console.log(`skipping auto/bulk message ${message.id}`);
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
