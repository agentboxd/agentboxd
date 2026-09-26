/**
 * An agent with no API key gives itself an email inbox, then asks its human to claim the workspace.
 *   npx tsx agent-self-signup/signup.ts you@example.com
 * Prints the key once: store it (e.g. as AGENTBOXD_API_KEY) before doing anything else.
 */
import { Agentboxd } from 'agentboxd';

const ownerEmail = process.argv[2]; // optional: your own address, to claim the workspace later

// Solves a short proof-of-work challenge (a few seconds of CPU), then creates the workspace.
const { client, api_key, inbox, restrictions, claim } = await Agentboxd.signup({
  agentName: 'research-agent',
  ownerEmail,
});

console.log(`AGENTBOXD_API_KEY=${api_key}  # shown once: store it now`);
console.log(`inbox: ${inbox.address} (${inbox.id})`);
console.log(`claim: ${claim.status}${claim.email ? ` to ${claim.email}` : ''}`);
console.log(`until claimed: ${restrictions.recipients_per_day} new recipients a day, no webhooks`);

// Receive mail right away: long-poll up to 60 s for the next email.
const mail = await client.messages.wait(inbox.id, { timeout: 60 });
if (mail) {
  console.log(`from ${mail.from}: ${mail.subject}`);
  // Replies in a thread someone started with the agent don't count toward the daily limit.
  await client.messages.reply(inbox.id, mail.id, { text: 'Thanks, got it.' });
}

// Where the workspace stands: claim status, limits, and when an idle unclaimed workspace is deleted.
const account = await client.account.get();
console.log(account.claim.status, account.claim.expires_at ?? '');
