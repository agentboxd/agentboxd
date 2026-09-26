/**
 * Realtime event stream client (GET /v1/stream). The same event bodies as webhooks, pushed over a
 * WebSocket, with automatic reconnect and resume (`since` = the last event id seen).
 *
 *   for await (const event of mr.stream({ eventTypes: ['message.received'] })) console.log(event.type, event.id);
 *
 *   const s = mr.stream({ inboxIds: [inbox.id] });
 *   s.on('event', (e) => …);  s.on('error', (err) => …);  …  s.close();
 *
 * Works with `globalThis.WebSocket` (browsers, Node 22+), the `ws` package (Node 20; install it), or
 * any constructor passed as `WebSocket`. Every connection uses a single-use token from
 * POST /v1/stream/token, so the API key never appears in a URL and no custom headers are needed.
 */

/** One event, exactly like a webhook body. `data` is the envelope form with `payload: 'envelope'`. */
export interface StreamEvent<T = unknown> {
  id: string;
  type: string;
  created_at: string;
  data: T;
}

export interface StreamOptions {
  /** Only these inboxes (default: every inbox the key can see). */
  inboxIds?: string[];
  /** Only these event types (default: all). */
  eventTypes?: string[];
  /** `full` (default) or `envelope` (ids, addresses, subject, labels; no bodies). */
  payload?: 'full' | 'envelope';
  /** Replay events after this event id first (last hour, at most 1000). */
  since?: string;
  /** Reconnect (and resume) after drops, restarts and slow-consumer closes. Default true. */
  reconnect?: boolean;
  /** A WebSocket constructor. Default: globalThis.WebSocket, else the `ws` package. */
  WebSocket?: WebSocketConstructor;
}

/** The standard WebSocket surface this client uses (browsers, undici, `ws`). */
export interface WebSocketLike {
  readonly readyState: number;
  send(data: string): void;
  close(code?: number, reason?: string): void;
  onopen: ((ev: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev: { code: number; reason: string }) => void) | null;
  onerror: ((ev: unknown) => void) | null;
}
export type WebSocketConstructor = new (url: string) => WebSocketLike;

/** Why the stream stopped for good: 4001 (credential), 4003 (permission), 1009, or 1008 (subscription refused). */
export class StreamClosedError extends Error {
  constructor(
    readonly code: number,
    readonly reason: string,
  ) {
    super(`stream closed (${code}): ${reason}`);
    this.name = 'StreamClosedError';
  }
}

type Listener<T> = (arg: T) => void;
interface StreamEvents {
  event: StreamEvent;
  open: void;
  /** After each (re)subscribe: `replayed` events were resent; `truncated` means some may be missing (resync via the REST API). */
  subscribed: { replayed: number; truncated: boolean };
  /** A refused subscription or token request (the stream ends), or a failed reconnect attempt (it retries). */
  error: Error;
  /** A connection closed; `willReconnect` tells whether another one follows. */
  close: { code: number; reason: string; willReconnect: boolean };
}

const FATAL = new Set([4001, 4003, 1009]);
const MAX_BACKOFF_MS = 30_000;

async function resolveWebSocket(given?: WebSocketConstructor): Promise<WebSocketConstructor> {
  if (given) return given;
  const global = (globalThis as { WebSocket?: WebSocketConstructor }).WebSocket;
  if (global) return global;
  const name = 'ws'; // not a static import: the SDK has no dependencies
  try {
    const mod = (await import(name)) as { default?: WebSocketConstructor; WebSocket?: WebSocketConstructor };
    const ctor = mod.WebSocket ?? mod.default;
    if (ctor) return ctor;
  } catch {
    // fall through
  }
  throw new Error('No WebSocket implementation: use Node 22+, install the `ws` package, or pass { WebSocket }.');
}

export class EventStream implements AsyncIterable<StreamEvent> {
  /** Id of the last event received; reconnects resume after it. */
  lastEventId: string | undefined;
  private ws: WebSocketLike | undefined;
  private closedByUser = false;
  private finished = false;
  private failure: Error | undefined;
  private attempt = 0;
  private watchdog: ReturnType<typeof setInterval> | undefined;
  private lastSeen = Date.now();
  private heartbeatMs = 30_000;
  private readonly listeners = new Map<keyof StreamEvents, Set<Listener<never>>>();
  private readonly queue: StreamEvent[] = [];
  private readonly waiting: { resolve: (r: IteratorResult<StreamEvent>) => void; reject: (e: Error) => void }[] = [];

  constructor(
    private readonly mintUrl: () => Promise<string>,
    private readonly opts: StreamOptions = {},
  ) {
    this.lastEventId = opts.since;
    void this.connect();
  }

  on<K extends keyof StreamEvents>(type: K, listener: Listener<StreamEvents[K]>): this {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(listener as Listener<never>);
    return this;
  }

  off<K extends keyof StreamEvents>(type: K, listener: Listener<StreamEvents[K]>): this {
    this.listeners.get(type)?.delete(listener as Listener<never>);
    return this;
  }

  private emit<K extends keyof StreamEvents>(type: K, arg: StreamEvents[K]) {
    for (const l of this.listeners.get(type) ?? []) (l as Listener<StreamEvents[K]>)(arg);
  }

  /** Stops the stream; a pending `for await` ends normally. */
  close() {
    this.closedByUser = true;
    this.stopWatchdog();
    this.ws?.close(1000, 'client closed');
    this.finish();
  }

  private finish(err?: Error) {
    if (this.finished) return;
    this.finished = true;
    this.failure = err;
    this.stopWatchdog();
    for (const w of this.waiting.splice(0)) {
      if (err) w.reject(err);
      else w.resolve({ value: undefined, done: true });
    }
  }

  private stopWatchdog() {
    if (this.watchdog) clearInterval(this.watchdog);
    this.watchdog = undefined;
  }

  private async connect() {
    if (this.closedByUser || this.finished) return;
    let url: string;
    let Ctor: WebSocketConstructor;
    try {
      Ctor = await resolveWebSocket(this.opts.WebSocket);
      url = await this.mintUrl();
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err));
      // Bad key / missing permission: retrying won't help.
      const status = (err as { status?: number }).status;
      if (status === 401 || status === 403 || !(this.opts.reconnect ?? true) || e.message.startsWith('No WebSocket')) {
        this.emit('error', e);
        this.finish(e);
        return;
      }
      this.emit('error', e);
      this.scheduleReconnect();
      return;
    }
    if (this.closedByUser) return;
    const ws = new Ctor(url);
    this.ws = ws;
    ws.onopen = () => {
      this.lastSeen = Date.now();
      this.emit('open', undefined);
    };
    ws.onerror = () => {
      // Details arrive with onclose.
    };
    ws.onmessage = (ev) => {
      this.lastSeen = Date.now();
      let msg: { type?: string; [k: string]: unknown };
      try {
        msg = JSON.parse(typeof ev.data === 'string' ? ev.data : String(ev.data)) as typeof msg;
      } catch {
        return;
      }
      this.handle(ws, msg);
    };
    ws.onclose = (ev) => {
      if (this.ws === ws) this.ws = undefined;
      this.stopWatchdog();
      const willReconnect = !this.closedByUser && !FATAL.has(ev.code) && (this.opts.reconnect ?? true) && !this.finished;
      this.emit('close', { code: ev.code, reason: ev.reason, willReconnect });
      if (this.closedByUser) return;
      if (FATAL.has(ev.code)) this.finish(new StreamClosedError(ev.code, ev.reason));
      else if (willReconnect) this.scheduleReconnect();
      else this.finish();
    };
  }

  private handle(ws: WebSocketLike, msg: { type?: string; [k: string]: unknown }) {
    switch (msg.type) {
      case 'hello': {
        this.heartbeatMs = (Number(msg.heartbeat_seconds) || 30) * 1000;
        ws.send(
          JSON.stringify({
            type: 'subscribe',
            ...(this.opts.inboxIds?.length ? { inbox_ids: this.opts.inboxIds } : {}),
            ...(this.opts.eventTypes?.length ? { event_types: this.opts.eventTypes } : {}),
            ...(this.opts.payload ? { payload: this.opts.payload } : {}),
            ...(this.lastEventId ? { since: this.lastEventId } : {}),
          }),
        );
        // App-level ping each heartbeat; no traffic for two heartbeats = a dead connection.
        this.stopWatchdog();
        this.watchdog = setInterval(() => {
          if (Date.now() - this.lastSeen > 2 * this.heartbeatMs) ws.close(4000, 'no traffic');
          else if (ws.readyState === 1) ws.send('{"type":"ping"}');
        }, this.heartbeatMs);
        (this.watchdog as { unref?: () => void }).unref?.();
        return;
      }
      case 'subscribed':
        this.attempt = 0;
        this.emit('subscribed', { replayed: Number(msg.replayed) || 0, truncated: msg.replay_truncated === true });
        return;
      case 'event': {
        const event = msg.event as StreamEvent;
        this.lastEventId = event.id;
        this.emit('event', event);
        const w = this.waiting.shift();
        if (w) w.resolve({ value: event, done: false });
        else this.queue.push(event);
        return;
      }
      case 'error': {
        // Every error the server sends is about our own subscription (unknown inbox or event type):
        // reconnecting would repeat it, so the stream ends.
        const err = new StreamClosedError(1008, `${String(msg.code)}: ${String(msg.message)}`);
        this.emit('error', err);
        this.closedByUser = true;
        ws.close(1000, 'subscription refused');
        this.finish(err);
        return;
      }
      default:
        return;
    }
  }

  private scheduleReconnect() {
    if (this.closedByUser || this.finished) return;
    const base = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.attempt++);
    // Not unref'd: a `for await` waiting through a reconnect must keep the process alive.
    setTimeout(() => void this.connect(), base / 2 + Math.random() * (base / 2));
  }

  [Symbol.asyncIterator](): AsyncIterator<StreamEvent> {
    return {
      next: () => {
        const value = this.queue.shift();
        if (value) return Promise.resolve({ value, done: false });
        if (this.finished) return this.failure ? Promise.reject(this.failure) : Promise.resolve({ value: undefined, done: true });
        return new Promise((resolve, reject) => this.waiting.push({ resolve, reject }));
      },
      return: () => {
        this.close();
        return Promise.resolve({ value: undefined, done: true });
      },
    };
  }
}
