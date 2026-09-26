# Contributing

Thanks for helping. This repository holds the open-source Agentboxd clients: the TypeScript client
(`sdk/`), the MCP server (`mcp/`), the Python client (`sdk-python/`) and example agents (`examples/`).
The API server is not open source, so bugs in the API itself are best reported by email to
support@agentboxd.com (or as an issue here if you're not sure where the problem is).

## Before you start

- For anything larger than a small fix, open an issue first so we can agree on the shape.
- Keep the clients in step: a new API field or method should land in the TypeScript and Python clients
  (and the MCP server, if an agent would use it) in the same pull request, or the issue should say why not.
- No new runtime dependencies in `sdk/` (it has none) or `sdk-python/` (only `httpx`) without discussing it.

## Setup and checks

Node 20+ and Python 3.9+.

```bash
# TypeScript client
cd sdk && npm install && npm run typecheck && npm run build && npm test

# MCP server (typecheck covers ../sdk/src too)
cd mcp && npm ci && npm run typecheck && npm test && npm run build && npm run smoke

# Python client
cd sdk-python
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"      # .venv\Scripts\python on Windows
.venv/bin/python -m pytest
.venv/bin/python -m mypy --strict
.venv/bin/python -m ruff check . && .venv/bin/python -m ruff format --check .

# Examples
npm install && npm run typecheck:examples && npm run test:examples
```

CI runs the same commands on every pull request.

## Pull requests

- One logical change per pull request, with tests for behaviour changes.
- Update the package's `CHANGELOG.md` under an "Unreleased" heading.
- Update the package README if you change something a user types or reads.
- Don't bump versions; releases are cut by the maintainers.

## Code of conduct

Be kind and assume good intent. Harassment or personal attacks aren't tolerated; maintainers may
remove comments or block accounts that cross that line.
