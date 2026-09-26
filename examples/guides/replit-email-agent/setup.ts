/**
 * One-time setup for webhook mode: the agent's inbox and a webhook pointing at the published app.
 * Run it in the Replit Shell after publishing, with the app's .replit.app URL (development URLs
 * change, so never register one).
 *
 *   npx tsx setup.ts https://my-agent.replit.app
 *
 * It prints the webhook secret once: add it as the AGENTBOXD_WEBHOOK_SECRET secret (for the published
 * app too), then republish.
 */
import { Agentboxd } from 'agentboxd';

const appUrl = process.argv[2]?.replace(/\/+$/, '');
if (!appUrl?.startsWith('https://')) throw new Error('usage: npx tsx setup.ts https://<your-app>.replit.app');

const mr = new Agentboxd();
const inbox = await mr.inboxes.create({ client_id: process.env.AGENTBOXD_INBOX ?? 'replit-agent' });
const url = `${appUrl}/webhook`;

const existing = (await mr.webhooks.list()).data.find((w) => w.url === url);
if (existing) {
  console.log(`Webhook ${existing.id} already points at ${url}. Delete it in the dashboard to get a new secret.`);
} else {
  const hook = await mr.webhooks.create({
    url,
    events: ['message.received'],
    inbox_ids: [inbox.id],
    payload: 'envelope', // ids and subject only: the app reads the mail through the API
  });
  console.log(`Inbox:   ${inbox.address}`);
  console.log(`Webhook: ${hook.id} → ${url}`);
  console.log(`\nAdd this secret as AGENTBOXD_WEBHOOK_SECRET (shown once):\n${hook.secret}`);
}
