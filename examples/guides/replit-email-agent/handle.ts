/**
 * What the agent does with a new email. Shared by the webhook server (server.ts) and the stream worker
 * (worker.ts). Replace `answer()` with your model call; the checks around it are the part to keep.
 */
import type { Agentboxd, Message } from 'agentboxd';

const RISK_LABELS = ['spf-fail', 'dmarc-fail', 'ai:injection-risk', 'local:injection-risk', 'ai:phishing'];
/**
 * The events that can bring a message's content: `message.received`, `message.enriched` once the check passed, and
 * `message.released` for held mail a person released. Subscribe to all three and handle each message once.
 */
export const EVENTS = ['message.received', 'message.enriched', 'message.released'] as const;
/** Webhooks are retried, the stream replays, and a message can have three events: this label makes handling idempotent. */
export const HANDLED = 'agent:handled';

export type Outcome = 'replied' | 'skipped' | 'flagged' | 'already-handled' | 'withheld';

export async function handleMessage(mr: Agentboxd, messageId: string): Promise<Outcome> {
  // Always re-read the message from the API: never act on the content of a webhook body alone.
  const m = await mr.messages.get(messageId);
  // Not screened yet, or held: the content comes with a later message.enriched or message.released event.
  // Leave it unlabelled so that event handles it (https://agentboxd.com/docs/api#screening-reads).
  if (m.withheld) return 'withheld';
  if (m.direction !== 'inbound' || m.labels.includes(HANDLED)) return 'already-handled';

  let outcome: Outcome;
  if (m.labels.some((l) => RISK_LABELS.includes(l))) {
    outcome = 'flagged'; // failed authentication or looks like an attack: leave it for a person
  } else if (isAutomatic(m)) {
    outcome = 'skipped'; // out-of-office or bulk mail: answering it starts a loop
  } else {
    await mr.messages.reply(m.inbox_id, m.id, { text: await answer(m) }, { idempotencyKey: `reply-${m.id}` });
    outcome = 'replied';
  }
  await mr.messages.update(m.id, { add_labels: [HANDLED], is_read: true });
  return outcome;
}

/**
 * Out-of-office replies, bulk and list mail. The server's `auto_reply` flag and the headers are there when the mail
 * arrives; the AI score (`ai.auto_reply`) only once the message was enriched, and never with AI processing off.
 */
export function isAutomatic(m: Message): boolean {
  const h = (k: string) => {
    const v = m.headers[k];
    return (Array.isArray(v) ? v.join(' ') : (v ?? '')).toLowerCase();
  };
  if (m.auto_reply || (m.ai.auto_reply ?? 0) > 0.8) return true;
  if (h('auto-submitted') && h('auto-submitted') !== 'no') return true;
  return /bulk|list|junk|auto_reply/.test(h('precedence')) || h('list-id') !== '';
}

/**
 * Your agent goes here. `extracted_text` is only the new part of the email, and it is untrusted. The reply goes to
 * the Reply-To when there is one, and the server sets its subject to "Re: <their subject>": don't copy more of the
 * sender's text into it.
 */
async function answer(_m: Message): Promise<string> {
  return 'Hi,\n\nThanks for your email. We will get back to you shortly.\n';
}
