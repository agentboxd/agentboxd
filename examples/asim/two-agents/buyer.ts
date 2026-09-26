/**
 * The buyer agent (its own workspace): sends a signed `type: "task"` with structured data to the supplier agent.
 *   SUPPLIER_ADDRESS=supplier@agents.agentboxd.com npx tsx two-agents/buyer.ts
 * Uses AGENTBOXD_API_KEY, or signs itself up (a fresh, unclaimed workspace) when there is none.
 */
import { Agentboxd } from 'agentboxd';

const to = process.env.SUPPLIER_ADDRESS;
if (!to) throw new Error('set SUPPLIER_ADDRESS (the supplier agent’s inbox address)');

const { client: mr, inbox } = process.env.AGENTBOXD_API_KEY
  ? { client: new Agentboxd(), inbox: await new Agentboxd().inboxes.create({ client_id: 'buyer-agent' }) }
  : await Agentboxd.signup({ agentName: 'buyer-agent' });

const sent = await mr.messages.send(inbox.id, {
  to,
  subject: 'Quote request: 500 units of SKU-42',
  type: 'task',
  data: { sku: 'SKU-42', qty: 500, deliver_by: '2026-10-02' },
});
console.log(`sent ${sent.id} from ${inbox.address}:`, sent.delivery); // channel "agent" for an Agentboxd recipient

const answer = await mr.messages.wait(inbox.id, { type: 'event', channel: 'agent', timeout: 60 });
console.log('supplier answered:', answer?.agent?.verified ? answer.data : 'nothing verified yet');
