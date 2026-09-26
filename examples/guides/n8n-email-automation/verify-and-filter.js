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
if (event.type !== 'message.received') return [];

const m = event.data.message;
// Spoofed senders: never auto-answer them.
if (m.labels.includes('spf-fail') || m.labels.includes('dmarc-fail')) return [];
// Auto-replies, bulk mail and bounces: answering them starts mail loops.
const auto = String(m.headers['auto-submitted'] || 'no').toLowerCase();
const precedence = String(m.headers['precedence'] || '').toLowerCase();
if (auto !== 'no' || ['bulk', 'junk', 'list', 'auto_reply'].includes(precedence)) return [];

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
