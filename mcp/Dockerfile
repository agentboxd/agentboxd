# syntax=docker/dockerfile:1
# Hosted MCP server (compose service `mcp`, docs/remote-mcp-contract.md §5). Build context: the repo root,
# because the server bundles the TypeScript SDK from sdk/src:
#   docker build -f mcp/Dockerfile .
FROM node:22-alpine AS build
WORKDIR /app/mcp
COPY mcp/package.json mcp/package-lock.json ./
RUN npm ci
COPY sdk/src /app/sdk/src
COPY mcp/tsconfig.json ./
COPY mcp/src ./src
RUN npm run build:hosted

FROM node:22-alpine AS runtime
# Lets deploy/cleanup.sh remove this project's old images and never another project's.
# The label value is the private deploy tooling's project key (deploy/cleanup.sh), not a product name.
LABEL org.agentboxd.project="mailroom"
WORKDIR /app
ENV NODE_ENV=production
COPY mcp/package.json mcp/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=build /app/mcp/dist-hosted ./dist-hosted
USER node
EXPOSE 3334
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 CMD wget -qO- http://127.0.0.1:3334/health || exit 1
CMD ["node", "dist-hosted/server.js"]
