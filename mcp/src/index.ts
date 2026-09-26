#!/usr/bin/env node
/**
 * Agentboxd MCP server entry point.
 *   stdio (default):  AGENTBOXD_API_KEY=... agentboxd-mcp        (legacy MAILROOM_API_KEY also read)
 *   Streamable HTTP:  AGENTBOXD_API_KEY=... agentboxd-mcp --http [--port=3333]   (or MCP_HTTP_PORT=3333)
 *   No key:           agentboxd-mcp [--save-key=./agentboxd.env]   the agent calls the signup tool to create its own
 *                     workspace; the key stays in memory unless --save-key names a file to keep it in.
 */
import { readFileSync } from 'node:fs';
import { createServer as createHttpServer } from 'node:http';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { Agentboxd } from '../../sdk/src/index.js';
import { ConfigError, loadConfig, type Config } from './config.js';
import { createAgentboxdMcpServer, SERVER_VERSION, type ClientRef, type ServerOptions } from './server.js';

async function runStdio(client: ClientRef, opts: ServerOptions): Promise<void> {
  const server = createAgentboxdMcpServer(client, opts);
  await server.connect(new StdioServerTransport());
  console.error(`agentboxd-mcp ${SERVER_VERSION} running on stdio`);
}

async function runHttp(client: ClientRef, opts: ServerOptions, config: Config): Promise<void> {
  const port = config.httpPort!;
  const http = createHttpServer(async (req, res) => {
    const path = new URL(req.url ?? '/', 'http://localhost').pathname;
    if (path !== '/mcp') {
      res.writeHead(404, { 'Content-Type': 'application/json' }).end(JSON.stringify({ error: 'Use /mcp' }));
      return;
    }
    if (req.method !== 'POST') {
      // Stateless mode: no server-initiated SSE stream or sessions to delete.
      res.writeHead(405, { Allow: 'POST', 'Content-Type': 'application/json' }).end(
        JSON.stringify({ jsonrpc: '2.0', error: { code: -32000, message: 'Method not allowed.' }, id: null }),
      );
      return;
    }
    try {
      const chunks: Buffer[] = [];
      for await (const chunk of req) chunks.push(chunk as Buffer);
      const body: unknown = JSON.parse(Buffer.concat(chunks).toString('utf8') || 'null');
      // Stateless: a fresh server + transport per request.
      const server = createAgentboxdMcpServer(client, opts);
      const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
      res.on('close', () => {
        void transport.close();
        void server.close();
      });
      await server.connect(transport);
      await transport.handleRequest(req, res, body);
    } catch (err) {
      console.error('HTTP request failed:', err);
      if (!res.headersSent) {
        res.writeHead(400, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ jsonrpc: '2.0', error: { code: -32700, message: 'Invalid request' }, id: null }),
        );
      }
    }
  });
  await new Promise<void>((resolve) => http.listen(port, config.httpHost, resolve));
  console.error(`agentboxd-mcp ${SERVER_VERSION} listening on http://${config.httpHost}:${port}/mcp`);
}

async function main(): Promise<void> {
  let config: Config;
  try {
    config = loadConfig(process.env, process.argv.slice(2), (path) => {
      try {
        return readFileSync(path, 'utf8');
      } catch {
        return undefined;
      }
    });
  } catch (err) {
    if (err instanceof ConfigError) {
      console.error(`agentboxd-mcp: ${err.message}`);
      process.exit(1);
    }
    throw err;
  }
  // Shared by every request in HTTP mode, so a signup in one request serves the next ones.
  const client: ClientRef = { current: config.apiKey ? new Agentboxd({ apiKey: config.apiKey, baseUrl: config.baseUrl }) : null };
  if (!client.current) {
    console.error(
      `agentboxd-mcp: no AGENTBOXD_API_KEY, starting without one. The agent can call the signup tool to create its own workspace${
        config.saveKeyPath ? ` (the key will be saved to ${config.saveKeyPath})` : ' (the key is kept in memory only; pass --save-key=<file> to keep it)'
      }.`,
    );
  }
  const opts: ServerOptions = { baseUrl: config.baseUrl, saveKeyPath: config.saveKeyPath };
  if (config.httpPort !== undefined) await runHttp(client, opts, config);
  else await runStdio(client, opts);
}

main().catch((err: unknown) => {
  console.error('agentboxd-mcp: fatal error:', err);
  process.exit(1);
});
