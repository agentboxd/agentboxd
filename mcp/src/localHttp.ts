/**
 * The local server's Streamable HTTP mode (`agentboxd-mcp --http`): stateless, no authentication of its own,
 * so it answers only its own Host names and pages on this machine (DNS rebinding), and reads at most
 * MCP_MAX_BODY_BYTES of a request body.
 */
import { createServer, type Server } from 'node:http';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { refuseHttpRequest, type Config } from './config.js';
import { BodyTooLarge, readBody } from './httpBody.js';
import { createAgentboxdMcpServer, type ClientRef, type ServerOptions } from './server.js';

type HttpConfig = Pick<Config, 'httpAllowedHosts' | 'httpAllowedOrigins' | 'maxBodyBytes'>;

const rpcError = (code: number, message: string) => JSON.stringify({ jsonrpc: '2.0', error: { code, message }, id: null });

/** The HTTP server, not yet listening. `log` gets one line per refused or failed request. */
export function createLocalHttpServer(
  client: ClientRef,
  opts: ServerOptions,
  config: HttpConfig,
  log: (...args: unknown[]) => void = console.error,
): Server {
  return createServer(async (req, res) => {
    const refused = refuseHttpRequest(config, req.headers.host, req.headers.origin);
    if (refused) {
      log(`agentboxd-mcp: refused a request for Host ${JSON.stringify(req.headers.host ?? '')}: ${refused}`);
      res.writeHead(403, { 'Content-Type': 'application/json' }).end(rpcError(-32000, refused));
      return;
    }
    const path = new URL(req.url ?? '/', 'http://localhost').pathname;
    if (path !== '/mcp') {
      res.writeHead(404, { 'Content-Type': 'application/json' }).end(JSON.stringify({ error: 'Use /mcp' }));
      return;
    }
    if (req.method !== 'POST') {
      // Stateless mode: no server-initiated SSE stream or sessions to delete.
      res.writeHead(405, { Allow: 'POST', 'Content-Type': 'application/json' }).end(rpcError(-32000, 'Method not allowed.'));
      return;
    }
    try {
      let raw: Buffer;
      try {
        raw = await readBody(req, config.maxBodyBytes);
      } catch (err) {
        if (!(err instanceof BodyTooLarge)) throw err;
        log(`agentboxd-mcp: refused a request: ${err.message} (MCP_MAX_BODY_BYTES)`);
        res.writeHead(413, { 'Content-Type': 'application/json' }).end(rpcError(-32000, `${err.message}. Set MCP_MAX_BODY_BYTES to allow more.`));
        return;
      }
      const body: unknown = JSON.parse(raw.toString('utf8') || 'null');
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
      log('HTTP request failed:', err);
      if (!res.headersSent) {
        res.writeHead(400, { 'Content-Type': 'application/json' }).end(rpcError(-32700, 'Invalid request'));
      }
    }
  });
}
