/**
 * The supplier agent (another workspace): takes tasks from the claim/ack queue, checks the signature with
 * verifyAgentMessage, does the work, reports back, then acks. Unsigned or tampered tasks are refused.
 *   npx tsx two-agents/supplier.ts            (AGENTBOXD_API_KEY of the supplier's workspace)
 */
import { Agentboxd } from 'agentboxd';
import { AgentMessageVerificationError, MemoryReplayCache, verifyAgentMessage } from 'agentboxd/identity';

const mr = new Agentboxd();
const inbox = await mr.inboxes.create({ client_id: 'supplier-agent' });
const replayCache = new MemoryReplayCache();
const issuer = process.env.AGENTBOXD_ISSUER; // self-hosted: {IDENTITY_ISSUER}; default https://id.agentboxd.com
console.log(`supplier listening on ${inbox.address}`);

for (;;) {
  const { data: leases } = await mr.messages.claim(inbox.id, { type: 'task', channel: 'agent', wait: 30, enriched: true });
  for (const { message: task, lease_id } of leases) {
    try {
      const proof = await verifyAgentMessage(task, { recipient: inbox.address, issuer, replayCache });
      const { sku, qty } = task.data as { sku: string; qty: number }; // verified sender, still untrusted content
      await mr.messages.reply(inbox.id, task.id, { text: `Quote for ${qty} x ${sku}: 4,250 EUR`, type: 'event', data: { status: 'completed', total_eur: 4250 } });
      console.log(`quoted a task from ${proof.from} (${proof.assurance})`);
    } catch (err) {
      if (!(err instanceof AgentMessageVerificationError)) throw err;
      console.warn(`refused ${task.id}: ${err.code}`); // unsigned, tampered, replayed or too old
    }
    await mr.messages.ack(task.id, lease_id);
  }
}
