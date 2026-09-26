#!/usr/bin/env node
/**
 * Entry point of the hosted MCP server (compose service `mcp`, docs/remote-mcp-contract.md §5):
 *   MCP_RESOURCE_URL=https://mcp.agentboxd.com/mcp IDENTITY_ISSUER=https://id.agentboxd.com \
 *   AGENTBOXD_INTERNAL_URL=http://api:3000 CONNECTOR_EXCHANGE_SECRET=... node dist-hosted/server.js
 */
import { createServer } from 'node:http';
import { ConfigError } from './config.js';
import { createHostedHandler, loadHostedConfig, type HostedConfig } from './hosted.js';
import { SERVER_VERSION } from './server.js';

let cfg: HostedConfig;
try {
  cfg = loadHostedConfig(process.env);
} catch (err) {
  if (err instanceof ConfigError) {
    console.error(`agentboxd-mcp-hosted: ${err.message}`);
    process.exit(1);
  }
  throw err;
}

const handle = createHostedHandler(cfg);
const server = createServer((req, res) => {
  handle(req, res).catch((err: unknown) => {
    console.error(JSON.stringify({ t: new Date().toISOString(), msg: 'mcp request failed', err: (err as Error)?.message ?? String(err) }));
    if (!res.headersSent) {
      res.writeHead(500, { 'Content-Type': 'application/json' }).end(JSON.stringify({ jsonrpc: '2.0', error: { code: -32603, message: 'Internal error' }, id: null }));
    } else {
      res.end();
    }
  });
});
// wait_for_email long-polls up to 60 s: keep the socket open a little longer than that.
server.requestTimeout = 90_000;
server.headersTimeout = 20_000;
server.keepAliveTimeout = 65_000;

server.listen(cfg.port, cfg.host, () => {
  console.error(`agentboxd-mcp-hosted ${SERVER_VERSION} listening on http://${cfg.host}:${cfg.port} for ${cfg.resource}`);
});

const stop = () => server.close(() => process.exit(0));
process.on('SIGTERM', stop);
process.on('SIGINT', stop);
