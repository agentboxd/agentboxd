# OpenClaw: give your agent an email address

Guide: https://agentboxd.com/guides/openclaw

| File | Where it goes |
|---|---|
| `openclaw.json` | The `mcp.servers.agentboxd` entry to merge into OpenClaw's config (`~/.openclaw/openclaw.json`, or `$OPENCLAW_STATE_DIR/openclaw.json`). Or skip the file and run the `openclaw mcp add` command below. |
| `skills/agentboxd-email/SKILL.md` | An OpenClaw skill that tells the agent when and how to use the email tools, and the safety rules. Copy the folder to `<workspace>/skills/` (this agent) or `~/.openclaw/skills/` (every agent). |
| `validate.ts` | Checks both files without OpenClaw: the config shape, the skill frontmatter, and that every tool the skill names exists in `@agentboxd/mcp`. |

Add the server from the terminal:

```bash
openclaw mcp add agentboxd --command npx --arg -y --arg @agentboxd/mcp --env AGENTBOXD_API_KEY=mr_...
openclaw mcp probe agentboxd      # connects and reports the tool count
```

## Checks

```bash
cd examples/guides && npm ci
npm run openclaw:check           # validate.ts
AGENTBOXD_API_KEY=mr_... npm run mcp:smoke   # the same MCP server, driven over stdio like OpenClaw does
```

Written against the OpenClaw docs for `openclaw mcp` (stdio servers under `mcp.servers`) and skills (`SKILL.md`
with `name`, `description` and `metadata.openclaw`) as of 2026-09-25, and `@agentboxd/mcp` 0.1.0.
