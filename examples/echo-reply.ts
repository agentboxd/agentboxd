/**
 * What the echo agent (echo-agent.ts) answers, and which mail it leaves alone. Kept apart from echo-agent.ts,
 * which starts the agent as soon as it is loaded.
 */
import type { Message } from '../sdk/src/index.js';

/**
 * Labels that mean the sender failed authentication (the From may be someone else's), the mail looks like an
 * attack, or it is spam or an automatic reply. An agent that answers these sends a stranger's mail on to whoever the
 * stranger chose.
 */
export const SKIP_LABELS = [
  'spf-fail',
  'dmarc-fail',
  'ai:injection-risk',
  'local:injection-risk',
  'ai:phishing',
  'ai:auto-reply',
  'spam',
  'local:spam',
];

/**
 * A fixed "summary": the size of the message, never its words. Text and file names are written by the sender, so
 * putting them in the body would let anyone send their text from this inbox. The server still sets the reply's
 * subject to "Re: <their subject>", which is why shouldReply answers only the From address. Swap in your model call
 * here, and keep what it writes away from the sender's own text.
 */
export function summarize(message: Message): string {
  const body = (message.extracted_text ?? message.text ?? '').trim();
  const words = body ? body.split(/\s+/).length : 0;
  const files = message.attachments.filter((a) => !a.inline).length;
  return [
    "Hi! I'm an echo agent. I received your message.",
    '',
    `Summary: ${words} word${words === 1 ? '' : 's'}${files ? `, ${files} attachment${files === 1 ? '' : 's'}` : ''}.`,
  ].join('\n');
}

/** The address in "Name <address>", the form the API shows addresses in, lower case. */
function addressOf(display: string): string {
  const s = display.trim();
  return (/<([^<>]+)>$/.exec(s)?.[1] ?? s).trim().toLowerCase();
}

/**
 * Never answer bounces, automatic replies, lists, ourselves, or mail that failed authentication or looks like an
 * attack: that's how mail loops start, and how a stranger gets this inbox to write to someone else.
 */
export function shouldReply(message: Message, ownAddress: string): boolean {
  const h = (k: string) => {
    const v = message.headers[k];
    return (Array.isArray(v) ? v.join(' ') : (v ?? '')).toLowerCase();
  };
  const from = message.from.toLowerCase();
  if (from.includes(ownAddress.toLowerCase()) || /mailer-daemon|postmaster|no-?reply/.test(from)) return false;
  // A reply goes to the Reply-To when there is one, and SPF and DMARC never check that address: answer only when it
  // is the From address itself.
  if (message.reply_to && addressOf(message.reply_to) !== addressOf(message.from)) return false;
  if (message.auto_reply) return false; // the server's flag: Auto-Submitted, X-Autoreply, Precedence or ai:auto-reply
  if (h('auto-submitted') && h('auto-submitted') !== 'no') return false;
  if (/bulk|list|junk|auto_reply/.test(h('precedence')) || h('list-id') || h('x-autoreply') || h('x-autorespond')) return false;
  return !message.labels.some((l) => SKIP_LABELS.includes(l));
}
