#!/usr/bin/env node
/** The `agentboxd` bin: wires `run()` to this process (stdio, environment, Ctrl-C). */
import { run } from './run.js';

function readStdin(): Promise<string> {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (c: string) => (data += c));
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

/** Reads a line from the terminal without echoing it. */
function readSecret(prompt: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const stdin = process.stdin;
    process.stderr.write(prompt);
    stdin.setRawMode(true);
    stdin.setEncoding('utf8');
    stdin.resume();
    let value = '';
    const done = (err?: Error) => {
      stdin.setRawMode(false);
      stdin.pause();
      stdin.off('data', onData);
      process.stderr.write('\n');
      if (err) reject(err);
      else resolve(value);
    };
    const onData = (chunk: string) => {
      for (const ch of chunk) {
        if (ch === '\r' || ch === '\n') return done();
        if (ch === '\u0003') return done(new Error('cancelled'));
        if (ch === '\u007f' || ch === '\b') value = value.slice(0, -1);
        else value += ch;
      }
    };
    stdin.on('data', onData);
  });
}

let interrupt: () => void = () => {};
const interrupted = new Promise<void>((r) => (interrupt = r));
let interrupts = 0;
process.on('SIGINT', () => {
  // First Ctrl-C closes a running `tail` cleanly; a second one quits at once.
  if (++interrupts > 1) process.exit(130);
  interrupt();
});

const code = await run(process.argv.slice(2), {
  stdout: process.stdout,
  stderr: process.stderr,
  env: process.env,
  readStdin,
  stdinIsTTY: process.stdin.isTTY === true,
  readSecret,
  interrupted,
});
process.exitCode = code;
// A finished command must not wait for sockets kept alive by fetch.
setImmediate(() => process.exit(code)).unref();
