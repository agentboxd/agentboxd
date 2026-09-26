/**
 * Builds the two importable n8n workflows in this folder from one source, so the Code node always
 * matches verify-and-filter.js.
 *   npx tsx n8n-email-automation/workflows.ts          write the .workflow.json files
 *   npx tsx n8n-email-automation/workflows.ts --check  fail if they are out of date or malformed
 *
 * API_BASE (default https://api.agentboxd.com) is baked into the HTTP Request URLs.
 */
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const dir = (f: string) => fileURLToPath(new URL(f, import.meta.url));
const API = (process.env.API_BASE ?? 'https://api.agentboxd.com').replace(/\/+$/, '');
const credentials = { httpHeaderAuth: { id: 'agentboxdApiKey', name: 'Agentboxd API key' } };
const auth = { authentication: 'genericCredentialType', genericAuthType: 'httpHeaderAuth' };

interface N8nNode {
  parameters: Record<string, unknown>;
  id: string;
  name: string;
  type: string;
  typeVersion: number;
  position: [number, number];
  webhookId?: string;
  credentials?: typeof credentials;
}

const chain = (...names: string[]) =>
  Object.fromEntries(names.slice(0, -1).map((n, i) => [n, { main: [[{ node: names[i + 1]!, type: 'main', index: 0 }]] }]));

export function inboundWorkflow(code: string) {
  const nodes: N8nNode[] = [
    {
      parameters: { httpMethod: 'POST', path: 'agentboxd-inbound', responseMode: 'onReceived', options: { rawBody: true } },
      id: '6f1d2c3a-1b4e-4d8a-9c10-2a3b4c5d6e01',
      name: 'Agentboxd webhook',
      type: 'n8n-nodes-base.webhook',
      typeVersion: 2,
      position: [0, 0],
      webhookId: '5c7e9a10-3d2f-4b6a-8e1c-9f0a1b2c3d41',
    },
    {
      parameters: { jsCode: code },
      id: '6f1d2c3a-1b4e-4d8a-9c10-2a3b4c5d6e02',
      name: 'Verify and filter',
      type: 'n8n-nodes-base.code',
      typeVersion: 2,
      position: [260, 0],
    },
    {
      parameters: {
        method: 'POST',
        url: `=${API}/v1/inboxes/{{ $json.inbox_id }}/messages/{{ $json.message_id }}/reply`,
        ...auth,
        sendHeaders: true,
        headerParameters: { parameters: [{ name: 'Idempotency-Key', value: '=ack-{{ $json.message_id }}' }] },
        sendBody: true,
        specifyBody: 'json',
        jsonBody:
          '={{ JSON.stringify({ text: \'Hi,\\n\\nThanks for your email about "\' + $json.subject + \'". We have it and will answer within one business day.\\n\\nAcme Support\' }) }}',
        options: {},
      },
      id: '6f1d2c3a-1b4e-4d8a-9c10-2a3b4c5d6e03',
      name: 'Reply in thread',
      type: 'n8n-nodes-base.httpRequest',
      typeVersion: 4.2,
      position: [520, 0],
      credentials,
    },
  ];
  return {
    id: 'agentboxdInboundAck',
    name: 'Agentboxd: acknowledge inbound email',
    nodes,
    connections: chain('Agentboxd webhook', 'Verify and filter', 'Reply in thread'),
    settings: { executionOrder: 'v1' },
    pinData: {},
  };
}

export function sendWorkflow() {
  const nodes: N8nNode[] = [
    {
      parameters: {},
      id: '7a2e3d4b-2c5f-4e9b-8d21-3b4c5d6e7f01',
      name: 'Run manually',
      type: 'n8n-nodes-base.manualTrigger',
      typeVersion: 1,
      position: [0, 0],
    },
    {
      parameters: {
        method: 'POST',
        url: `${API}/v1/inboxes`,
        ...auth,
        sendBody: true,
        specifyBody: 'json',
        jsonBody: '{\n  "client_id": "n8n-outreach",\n  "display_name": "Acme Ops"\n}',
        options: {},
      },
      id: '7a2e3d4b-2c5f-4e9b-8d21-3b4c5d6e7f02',
      name: 'Get or create inbox',
      type: 'n8n-nodes-base.httpRequest',
      typeVersion: 4.2,
      position: [240, 0],
      credentials,
    },
    {
      parameters: {
        method: 'POST',
        url: `=${API}/v1/inboxes/{{ $json.id }}/messages/send`,
        ...auth,
        sendBody: true,
        specifyBody: 'json',
        jsonBody:
          "={{ JSON.stringify({ to: 'dana@example.com', subject: 'Can you confirm Friday?', text: 'Hi Dana,\\n\\nDoes Friday 10:00 still work for the delivery?\\n\\nAcme Ops' }) }}",
        options: {},
      },
      id: '7a2e3d4b-2c5f-4e9b-8d21-3b4c5d6e7f03',
      name: 'Send email',
      type: 'n8n-nodes-base.httpRequest',
      typeVersion: 4.2,
      position: [480, 0],
      credentials,
    },
    {
      parameters: {
        method: 'GET',
        url: `=${API}/v1/inboxes/{{ $json.inbox_id }}/messages/wait`,
        ...auth,
        sendQuery: true,
        queryParameters: {
          parameters: [
            { name: 'timeout', value: '60' },
            { name: 'since', value: '={{ $json.created_at }}' },
            { name: 'from', value: 'dana@example.com' },
          ],
        },
        options: { timeout: 70000 },
      },
      id: '7a2e3d4b-2c5f-4e9b-8d21-3b4c5d6e7f04',
      name: 'Wait for the reply',
      type: 'n8n-nodes-base.httpRequest',
      typeVersion: 4.2,
      position: [720, 0],
      credentials,
    },
  ];
  return {
    id: 'agentboxdSendWait',
    name: 'Agentboxd: send an email and wait for the answer',
    nodes,
    connections: chain('Run manually', 'Get or create inbox', 'Send email', 'Wait for the reply'),
    settings: { executionOrder: 'v1' },
    pinData: {},
  };
}

const KNOWN = new Set(['n8n-nodes-base.webhook', 'n8n-nodes-base.code', 'n8n-nodes-base.httpRequest', 'n8n-nodes-base.manualTrigger']);

function validate(wf: { nodes: N8nNode[]; connections: Record<string, { main: { node: string }[][] }> }) {
  const names = new Set(wf.nodes.map((n) => n.name));
  assert.equal(names.size, wf.nodes.length, 'duplicate node names');
  for (const n of wf.nodes) assert.ok(KNOWN.has(n.type), `unknown node type ${n.type}`);
  for (const [from, c] of Object.entries(wf.connections)) {
    assert.ok(names.has(from), `connection from unknown node ${from}`);
    for (const t of c.main.flat()) assert.ok(names.has(t.node), `connection to unknown node ${t.node}`);
  }
}

const code = readFileSync(dir('./verify-and-filter.js'), 'utf8');
const files = {
  'inbound-reply.workflow.json': inboundWorkflow(code),
  'send-and-wait.workflow.json': sendWorkflow(),
};

for (const [file, wf] of Object.entries(files)) {
  validate(wf);
  const json = `${JSON.stringify(wf, null, 2)}\n`;
  if (process.argv.includes('--check')) {
    assert.equal(readFileSync(dir(`./${file}`), 'utf8').replace(/\r\n/g, '\n'), json, `${file} is out of date: run workflows.ts`);
    console.log(`${file}: ok`);
  } else if (process.argv[2] && !process.argv[2].startsWith('--')) {
    writeFileSync(process.argv[2].replace('{file}', file), json);
  } else {
    writeFileSync(dir(`./${file}`), json);
    console.log(`wrote ${file}`);
  }
}
