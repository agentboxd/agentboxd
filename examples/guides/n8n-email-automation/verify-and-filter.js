// n8n Code node ("Run Once for All Items"): verify the Agentboxd webhook signature and keep only
// email worth answering. Needs NODE_FUNCTION_ALLOW_BUILTIN=crypto on the n8n instance and the
// Webhook node's "Raw Body" option on. The same code is embedded in inbound-reply.workflow.json.
const crypto = require('crypto');

// The secret returned once by POST /v1/webhooks. Keep it out of shared workflow exports.
const SECRET = 'whsec_replace_me';

const item = $input.first();
const headers = item.json.headers;
const raw = await this.helpers.getBinaryDataBuffer(0, 'data');

const ts = String(headers['x-mailroom-timestamp'] || '');
const sig = String(headers['x-mailroom-signature'] || '');
if (!/^\d+$/.test(ts) || Math.abs(Date.now() / 1000 - Number(ts)) > 300) {
  throw new Error('missing or stale X-Mailroom-Timestamp');
}
const expected = crypto.createHmac('sha256', SECRET).update(`${ts}.`).update(raw).digest('hex');
if (!/^[0-9a-f]{64}$/i.test(sig) || !crypto.timingSafeEqual(Buffer.from(sig, 'hex'), Buffer.from(expected, 'hex'))) {
  throw new Error('bad X-Mailroom-Signature');
}

const event = JSON.parse(raw.toString('utf8'));
// The content of a message comes with one of these. In a workspace that screens agent mail it is withheld
// until the check passes (message.enriched) or a person releases it (message.released); see
// https://agentboxd.com/docs/api#screening-reads
if (!['message.received', 'message.enriched', 'message.released'].includes(event.type)) return [];

const m = event.data.message;
if (m.withheld) return []; // not screened yet, or held: a later event brings the content
// Handle each message once, whichever event brought it. Saved only for runs of the published workflow.
const seen = $getWorkflowStaticData('global');
seen.handled = seen.handled || [];
if (seen.handled.includes(m.id)) return [];
seen.handled = [...seen.handled, m.id].slice(-500);

// Mail that failed SPF or DMARC, looks like an attack, is spam or is an automatic reply: never auto-answer it.
// A forged From on a domain without DMARC gets no fail label, so don't put the sender's words in the answer.
const SKIP_LABELS = [
  'spf-fail', 'dmarc-fail', 'ai:injection-risk', 'local:injection-risk', 'ai:phishing', 'ai:auto-reply', 'spam', 'local:spam',
];
if (m.labels.some((l) => SKIP_LABELS.includes(l))) return [];
// A reply goes to the Reply-To when there is one, and SPF and DMARC never check that address. Answer only when it
// is the From address itself, or a stranger could have this inbox write to anyone they name.
const address = (s) => (/<([^<>]+)>\s*$/.exec(s)?.[1] ?? s).trim().toLowerCase();
const from = address(m.from);
if (m.reply_to && address(m.reply_to) !== from) return [];
// Bounces, auto-replies, bulk mail and lists: answering them starts mail loops.
if (/mailer-daemon|postmaster|no-?reply/.test(from)) return [];
const header = (k) => [].concat(m.headers[k] ?? []).join(' ').toLowerCase();
if (m.auto_reply || (header('auto-submitted') && header('auto-submitted') !== 'no')) return [];
if (/bulk|list|junk|auto_reply/.test(header('precedence')) || header('list-id')) return [];
// Only the first email of a conversation. This acknowledgement carries In-Reply-To, so two inboxes running this
// workflow can't keep answering each other.
if (m.in_reply_to || (m.references ?? []).length) return [];

return [
  {
    json: {
      inbox_id: event.data.inbox.id,
      message_id: m.id,
      from: m.from,
      subject: m.subject || '(no subject)',
      text: m.extracted_text || '',
    },
  },
];
