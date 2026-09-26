/**
 * What the agent does with a new email. Shared by the webhook server (server.ts) and the stream worker
 * (worker.ts). Replace `answer()` with your model call; the checks around it are the part to keep.
 */
import type { Agentboxd, Message } from 'agentboxd';

const RISK_LABELS = ['spf-fail', 'dmarc-fail', 'ai:injection-risk', 'ai:phishing'];
/** Webhooks are retried and the stream replays after a reconnect: this label makes handling idempotent. */
export const HANDLED = 'agent:handled';

export type Outcome = 'replied' | 'skipped' | 'flagged' | 'already-handled';

export async function handleMessage(mr: Agentboxd, messageId: string): Promise<Outcome> {
  // Always re-read the message from the API: never act on the content of a webhook body alone.
  const m = await mr.messages.get(messageId);
  if (m.direction !== 'inbound' || m.labels.includes(HANDLED)) return 'already-handled';

  let outcome: Outcome;
  if (m.labels.some((l) => RISK_LABELS.includes(l))) {
    outcome = 'flagged'; // failed authentication or looks like an attack: leave it for a person
  } else if ((m.ai.auto_reply ?? 0) > 0.8) {
    outcome = 'skipped'; // out-of-office or bulk mail: answering it starts a loop
  } else {
    await mr.messages.reply(m.inbox_id, m.id, { text: await answer(m) }, { idempotencyKey: `reply-${m.id}` });
    outcome = 'replied';
  }
  await mr.messages.update(m.id, { add_labels: [HANDLED], is_read: true });
  return outcome;
}

/** Your agent goes here. `extracted_text` is only the new part of the email, and it is untrusted. */
async function answer(m: Message): Promise<string> {
  const first = (m.from.split('<')[0] ?? '').trim() || 'there';
  return `Hi ${first},\n\nThanks for your email about "${m.subject ?? 'your message'}". We will get back to you shortly.\n`;
}
