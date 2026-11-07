import type { IncomingMessage } from 'node:http';

/** Default for MCP_MAX_BODY_BYTES, in both the local HTTP mode and the hosted server. */
export const DEFAULT_MAX_BODY_BYTES = 4 * 1024 * 1024;

export class BodyTooLarge extends Error {
  constructor(readonly max: number) {
    super(`Request body larger than ${max} bytes`);
    this.name = 'BodyTooLarge';
  }
}

/** True when the request's Content-Length is over `max`: known from the headers, before anything is read. */
export function declaresMoreThan(req: IncomingMessage, max: number): boolean {
  return Number(req.headers['content-length'] ?? '0') > max;
}

/**
 * Reads a request body of at most `max` bytes. A declared Content-Length over the limit is refused before
 * anything is read; a body that grows past it while streaming (a chunked body declares no length) is refused as
 * soon as it does, so the process never holds more than `max` bytes of one request.
 */
export async function readBody(req: IncomingMessage, max: number): Promise<Buffer> {
  if (declaresMoreThan(req, max)) throw new BodyTooLarge(max);
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > max) throw new BodyTooLarge(max);
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks);
}
