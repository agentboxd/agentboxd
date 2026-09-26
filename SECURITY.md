# Security policy

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Instead, email
**security@agentboxd.com** with:

- what you found and where (package and version, or API endpoint),
- steps to reproduce or a proof of concept,
- the impact you think it has.

You can also use GitHub's private vulnerability reporting ("Report a vulnerability" under the
Security tab of this repository).

We aim to acknowledge reports within 2 business days and to keep you updated until the issue is fixed.
We're happy to credit you in the release notes if you'd like.

## Scope

- The packages in this repository: `agentboxd` (npm), `@agentboxd/mcp` (npm), `agentboxd` (PyPI).
- The hosted API at `api.agentboxd.com` and the dashboard at `agentboxd.com`. Please test only
  against your own account and data, don't degrade the service for others (no volumetric testing),
  and don't send mail to addresses you don't own.

## A note on prompt injection

Email is untrusted input by design: anyone can write to an agent's inbox. The clients and the MCP
server label suspicious messages and mark email content as untrusted, but they cannot guarantee that a
model will ignore instructions inside an email. Reports that show a way around these guardrails
(for example, content that escapes the untrusted-content marker, or a warning that should fire and
doesn't) are in scope. "A model followed instructions in an email" on its own is a known limitation,
covered in the docs.

## Supported versions

Security fixes go into the latest minor release of each package.
