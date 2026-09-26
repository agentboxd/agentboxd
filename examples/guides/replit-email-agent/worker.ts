/**
 * Stream mode: a background worker that holds a WebSocket to Agentboxd and handles each new email. No
 * public URL and no webhook secret, but it must run all the time: use a Reserved VM deployment
 * (background worker), not Autoscale, which stops idle instances.
 *
 *   npx tsx worker.ts        Secrets: AGENTBOXD_API_KEY; optional AGENTBOXD_INBOX (client_id)
 */
import { Agentboxd } from 'agentboxd';
import { handleMessage } from './handle.js';

const mr = new Agentboxd();
const inbox = await mr.inboxes.create({ client_id: process.env.AGENTBOXD_INBOX ?? 'replit-agent' });
console.log(`watching ${inbox.address}`);

// Reconnects and resumes on its own (missed events are replayed after a short drop). Node 22+ has a
// global WebSocket; on Node 20 the SDK loads the `ws` package from package.json.
const stream = mr.stream({ inboxIds: [inbox.id], eventTypes: ['message.received'], payload: 'envelope' });
stream.on('error', (err) => console.error('stream:', err.message));
process.on('SIGTERM', () => stream.close());

for await (const event of stream) {
  const id = (event.data as { message_id?: string }).message_id;
  if (!id) continue;
  try {
    console.log(`${id}: ${await handleMessage(mr, id)}`);
  } catch (err) {
    console.error(`${id}: failed:`, err);
  }
}
