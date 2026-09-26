# MCP email server: Claude Desktop, Claude Code, Cursor

Guide: https://agentboxd.com/guides/mcp-email-server

| File | Where it goes |
|---|---|
| `claude_desktop_config.json` | Claude Desktop: Settings → Developer → Edit Config (macOS `~/Library/Application Support/Claude/`, Windows `%APPDATA%\Claude\`). Fully quit and reopen Claude afterwards. |
| `.mcp.json` | Claude Code, project scope: the root of your repository. `${AGENTBOXD_API_KEY}` is read from your shell, so the key stays out of git. |
| `.cursor/mcp.json` | Cursor: `.cursor/mcp.json` in a project or `~/.cursor/mcp.json` globally. `${env:AGENTBOXD_API_KEY}` is read from the environment. |
| `smoke.ts` | Connects to the server over stdio like those clients do, lists the tools, creates a temporary inbox and reads a code from it. |

Claude Code without a file:

```bash
claude mcp add agentboxd --scope user -e AGENTBOXD_API_KEY=mr_... -- npx -y @agentboxd/mcp
```

## Smoke test

```bash
cd examples/guides && npm ci
cp mcp-email-server/.env.example .env   # fill in, then export the variables
AGENTBOXD_API_KEY=mr_... npm run mcp:smoke
```

Against a local Agentboxd dev stack (`AGENTBOXD_BASE_URL=http://localhost:3000`) it also delivers a test
verification email and checks that `get_verification_code` returns it, marked as untrusted content.
Until `@agentboxd/mcp` is on npm, set `MCP_COMMAND="npx tsx ../../mcp/src/index.ts"`.

Written against `@modelcontextprotocol/sdk` 1.30.1 and `@agentboxd/mcp` 0.1.0.
