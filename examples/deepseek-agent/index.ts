/**
 * DeepSeek-powered email agent on Agentboxd.
 *
 *   npx tsx examples/deepseek-agent/index.ts "Summarize the unread mail in my support inbox"
 *   npx tsx examples/deepseek-agent/index.ts --demo signup [--simulate]
 *   npx tsx examples/deepseek-agent/index.ts --demo triage [--inbox <inbox_id>]
 *
 * Flags: --model <id>  --max-steps <n>  --max-sends <n>  --quiet
 * Env:   DEEPSEEK_API_KEY (required), DEEPSEEK_MODEL, DEEPSEEK_BASE_URL,
 *        AGENTBOXD_API_KEY (required), AGENTBOXD_BASE_URL (default https://api.agentboxd.com);
 *        the legacy names MAILROOM_API_KEY / MAILROOM_URL are also read
 */
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { Agentboxd } from '../../sdk/src/index.js';
import { type AgentEvent, runAgent } from './agent.js';
import { DEFAULT_DEEPSEEK_MODEL, DeepSeekClient } from './deepseek.js';

export const DEMO_CLIENT_ID = 'deepseek-demo';
export const DEMO_CODE = '482913';

/** A realistic third-party verification email, as raw RFC 822. */
export function acmeVerificationEml(to: string, date = new Date()): string {
  const id = `${date.getTime()}.${Math.random().toString(36).slice(2, 10)}@mail.acme-cloud.example`;
  return [
    'From: Acme Cloud <no-reply@acme-cloud.example>',
    `To: ${to}`,
    'Subject: Confirm your Acme Cloud account',
    `Date: ${date.toUTCString()}`,
    `Message-ID: <${id}>`,
    'MIME-Version: 1.0',
    'Content-Type: text/plain; charset=utf-8',
    'Content-Transfer-Encoding: 7bit',
    '',
    'Welcome to Acme Cloud!',
    '',
    `Your verification code is ${DEMO_CODE}`,
    '',
    'Enter this code on the sign-up page to confirm your email address. It expires in 10 minutes.',
    "If you didn't create an Acme Cloud account, you can ignore this email.",
    '',
    '-- The Acme Cloud team',
    '',
  ].join('\r\n');
}

/** POST a raw .eml to {AGENTBOXD_BASE_URL}/dev/inbound (only exists when the server runs with NODE_ENV=development). */
export async function injectInbound(baseUrl: string, eml: string, fetchImpl: typeof fetch = fetch): Promise<void> {
  const res = await fetchImpl(`${baseUrl.replace(/\/+$/, '')}/dev/inbound`, {
    method: 'POST',
    headers: { 'Content-Type': 'message/rfc822' },
    body: eml,
    signal: AbortSignal.timeout(15_000),
  });
  if (!res.ok) {
    const hint = res.status === 404 ? ' (the /dev/inbound endpoint only exists when the server runs with NODE_ENV=development)' : '';
    throw new Error(`POST /dev/inbound → HTTP ${res.status}${hint}: ${(await res.text()).slice(0, 300)}`);
  }
}

export function signupTask(address: string, inboxId: string, since: string): string {
  return (
    `You just signed up to Acme Cloud with ${address} (inbox_id ${inboxId}) at ${since}. ` +
    'Retrieve the verification code that Acme emailed and report it. ' +
    `Use get_verification_code with inbox_id ${inboxId}, since ${since} and timeout 60.`
  );
}

export function triageTask(inboxId?: string): string {
  const scope = inboxId
    ? `in inbox ${inboxId}`
    : 'across my inboxes (use list_inboxes first; look at the 5 most recently created inboxes at most)';
  return (
    `Triage my recent inbound email ${scope}: list up to 20 recent inbound messages, then give a prioritized summary ` +
    'grouped as Urgent / Needs reply / FYI / Ignore (spam, suspicious, automated). One line per message: sender, subject, why. ' +
    'Flag any message with a security warning. Do not send or reply to anything.'
  );
}

// ---------- pretty printing ----------

const dim = (s: string) => (process.stdout.isTTY ? `\x1b[2m${s}\x1b[0m` : s);
const bold = (s: string) => (process.stdout.isTTY ? `\x1b[1m${s}\x1b[0m` : s);
const oneLine = (s: string, max: number) => {
  const flat = s.replace(/\s+/g, ' ');
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
};

function printer(quiet: boolean) {
  return (e: AgentEvent) => {
    switch (e.type) {
      case 'step':
        if (!quiet) console.log(dim(`— step ${e.step}/${e.maxSteps}`));
        break;
      case 'assistant':
        if (!quiet) console.log(`  💭 ${oneLine(e.content, 300)}`);
        break;
      case 'tool_call':
        console.log(`  → ${bold(e.name)}(${oneLine(e.arguments, 200)})`);
        break;
      case 'tool_result':
        if (!quiet) console.log(`  ${e.isError ? '✗' : '←'} ${dim(oneLine(e.content, 240))}`);
        break;
      case 'max_steps':
        console.log(dim('  (step limit reached)'));
        break;
      case 'final':
        break;
    }
  };
}

// ---------- main ----------

function usage(): never {
  console.error(
    [
      'Usage:',
      '  npx tsx examples/deepseek-agent/index.ts "<task>"',
      '  npx tsx examples/deepseek-agent/index.ts --demo signup [--simulate]',
      '  npx tsx examples/deepseek-agent/index.ts --demo triage [--inbox <inbox_id>]',
      'Options: --model <id> --max-steps <n> --max-sends <n> --quiet',
    ].join('\n'),
  );
  process.exit(2);
}

async function main() {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      demo: { type: 'string' },
      simulate: { type: 'boolean', default: false },
      inbox: { type: 'string' },
      model: { type: 'string' },
      'max-steps': { type: 'string' },
      'max-sends': { type: 'string' },
      quiet: { type: 'boolean', default: false },
      help: { type: 'boolean', short: 'h', default: false },
    },
  });
  if (values.help) usage();

  const deepseekKey = process.env.DEEPSEEK_API_KEY;
  const agentboxdKey = process.env.AGENTBOXD_API_KEY || process.env.MAILROOM_API_KEY;
  if (!deepseekKey || !agentboxdKey) {
    console.error('Set DEEPSEEK_API_KEY and AGENTBOXD_API_KEY (and optionally AGENTBOXD_BASE_URL, DEEPSEEK_MODEL).');
    process.exit(1);
  }
  const agentboxdUrl = process.env.AGENTBOXD_BASE_URL || process.env.MAILROOM_URL || 'https://api.agentboxd.com';
  const model = values.model ?? process.env.DEEPSEEK_MODEL ?? DEFAULT_DEEPSEEK_MODEL;
  const maxSteps = values['max-steps'] ? Number(values['max-steps']) : undefined;
  let maxEmailsPerRun = values['max-sends'] !== undefined ? Number(values['max-sends']) : undefined;
  if ((maxSteps !== undefined && !(maxSteps >= 1)) || (maxEmailsPerRun !== undefined && !(maxEmailsPerRun >= 0))) usage();

  const agentboxd = new Agentboxd({ apiKey: agentboxdKey, baseUrl: agentboxdUrl });
  const llm = new DeepSeekClient({ apiKey: deepseekKey, model, baseUrl: process.env.DEEPSEEK_BASE_URL });

  let task: string;
  let background: Promise<void> | undefined;
  if (values.demo === 'signup') {
    const inbox = await agentboxd.inboxes.create({ client_id: DEMO_CLIENT_ID, display_name: 'DeepSeek Demo Agent' });
    // A few seconds of slack for clock skew between this machine and the server.
    const since = new Date(Date.now() - 5_000).toISOString();
    console.log(`Inbox: ${inbox.address} (${inbox.id})`);
    if (values.simulate) {
      console.log(dim('Simulating Acme: injecting a verification email via /dev/inbound in 3 s…'));
      background = new Promise<void>((resolve) => setTimeout(resolve, 3_000))
        .then(() => injectInbound(agentboxdUrl, acmeVerificationEml(inbox.address)))
        .then(() => console.log(dim('  (simulated Acme email delivered)')))
        .catch((err: unknown) => console.error(`Simulation failed: ${err instanceof Error ? err.message : String(err)}`));
    } else {
      console.log(`Sign up somewhere with ${inbox.address} now; the agent waits up to 60 s for the code.`);
    }
    task = signupTask(inbox.address, inbox.id, since);
    maxEmailsPerRun ??= 0;
  } else if (values.demo === 'triage') {
    task = triageTask(values.inbox);
    maxEmailsPerRun = 0; // triage never sends
  } else if (values.demo !== undefined) {
    usage();
  } else {
    task = positionals.join(' ').trim();
    if (!task) usage();
  }

  console.log(dim(`Model: ${model} · API: ${agentboxdUrl}`));
  console.log(`${bold('Task:')} ${task}\n`);

  const result = await runAgent({ task, agentboxd, llm, maxSteps, maxEmailsPerRun, onEvent: printer(values.quiet) });
  await background;

  console.log(`\n${bold('Answer:')}\n${result.answer}`);
  console.log(dim(`\n${result.steps} step(s), ${result.toolCalls.length} tool call(s), ${result.emailsSent} email(s) sent.`));
}

// Run only when executed directly (tests import the helpers above).
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch((err: unknown) => {
    console.error(err instanceof Error ? err.message : err);
    process.exit(1);
  });
}
