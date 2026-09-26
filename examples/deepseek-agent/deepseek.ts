/**
 * Minimal typed client for DeepSeek's OpenAI-compatible Chat Completions API.
 * Zero dependencies: global fetch, AbortSignal timeouts, retries with exponential backoff on 429/5xx.
 */

export interface ToolCall {
  id: string;
  type: 'function';
  function: { name: string; arguments: string };
}

export type ChatMessage =
  | { role: 'system'; content: string }
  | { role: 'user'; content: string }
  | { role: 'assistant'; content: string | null; tool_calls?: ToolCall[] }
  | { role: 'tool'; tool_call_id: string; content: string };

export type AssistantMessage = Extract<ChatMessage, { role: 'assistant' }>;

export interface ToolDefinition {
  type: 'function';
  function: { name: string; description: string; parameters: Record<string, unknown> };
}

export interface ChatRequest {
  messages: ChatMessage[];
  tools?: ToolDefinition[];
  tool_choice?: 'auto' | 'none' | 'required';
  temperature?: number;
  /** Overrides the client's default model for this call. */
  model?: string;
}

export interface ChatResult {
  /** Normalized assistant message, safe to append to the history (no `reasoning_content`). */
  message: AssistantMessage;
  finish_reason: string | null;
  usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number };
  model?: string;
}

/** Anything that can answer a chat request: the real client, or a scripted fake in tests. */
export interface LlmClient {
  chat(req: ChatRequest): Promise<ChatResult>;
}

export class DeepSeekError extends Error {
  constructor(
    message: string,
    public readonly status: number | null,
    public readonly retryable: boolean,
    public readonly body?: string,
    /** Server's Retry-After hint, if any. */
    public readonly retryAfterMs?: number,
  ) {
    super(message);
    this.name = 'DeepSeekError';
  }
}

export interface DeepSeekOptions {
  apiKey: string;
  /** Default `https://api.deepseek.com`. */
  baseUrl?: string;
  /** Default `deepseek-flash`. */
  model?: string;
  /** Per-attempt timeout (ms). Default 120 000. */
  timeoutMs?: number;
  /** Retries after the first attempt, on 429/5xx/network errors/timeouts. Default 3. */
  maxRetries?: number;
  /** First backoff delay (ms); doubles each retry, with jitter. Default 1000. */
  retryBaseMs?: number;
  fetch?: typeof fetch;
  /** Injectable for tests. */
  sleep?: (ms: number) => Promise<void>;
}

export const DEFAULT_DEEPSEEK_MODEL = 'deepseek-flash';
export const DEFAULT_DEEPSEEK_BASE_URL = 'https://api.deepseek.com';

interface RawResponse {
  model?: string;
  choices?: Array<{
    finish_reason?: string | null;
    message?: {
      role?: string;
      content?: string | null;
      reasoning_content?: string | null;
      tool_calls?: Array<{ id?: string; type?: string; function?: { name?: string; arguments?: string } }>;
    };
  }>;
  usage?: ChatResult['usage'];
  error?: { message?: string };
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

export class DeepSeekClient implements LlmClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  readonly model: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly retryBaseMs: number;
  private readonly fetchImpl: typeof fetch;
  private readonly sleep: (ms: number) => Promise<void>;

  constructor(opts: DeepSeekOptions) {
    if (!opts.apiKey) throw new DeepSeekError('DeepSeek API key is missing (set DEEPSEEK_API_KEY)', null, false);
    this.apiKey = opts.apiKey;
    this.baseUrl = (opts.baseUrl ?? DEFAULT_DEEPSEEK_BASE_URL).replace(/\/+$/, '');
    this.model = opts.model ?? DEFAULT_DEEPSEEK_MODEL;
    this.timeoutMs = opts.timeoutMs ?? 120_000;
    this.maxRetries = opts.maxRetries ?? 3;
    this.retryBaseMs = opts.retryBaseMs ?? 1000;
    this.fetchImpl = opts.fetch ?? fetch;
    this.sleep = opts.sleep ?? defaultSleep;
  }

  async chat(req: ChatRequest): Promise<ChatResult> {
    const body = JSON.stringify({
      model: req.model ?? this.model,
      messages: req.messages,
      ...(req.tools?.length ? { tools: req.tools, tool_choice: req.tool_choice ?? 'auto' } : {}),
      temperature: req.temperature ?? 0.2,
      stream: false,
    });

    let lastError: DeepSeekError | undefined;
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      if (attempt > 0) await this.sleep(this.backoff(attempt, lastError));
      try {
        return await this.once(body);
      } catch (err) {
        lastError = err instanceof DeepSeekError ? err : new DeepSeekError(String(err), null, false);
        if (!lastError.retryable) throw lastError;
      }
    }
    throw new DeepSeekError(
      `DeepSeek request failed after ${this.maxRetries + 1} attempts: ${lastError?.message ?? 'unknown error'}`,
      lastError?.status ?? null,
      false,
      lastError?.body,
    );
  }

  private backoff(attempt: number, err: DeepSeekError | undefined): number {
    if (err?.retryAfterMs !== undefined) return Math.min(err.retryAfterMs, 60_000);
    const base = this.retryBaseMs * 2 ** (attempt - 1);
    return base + Math.floor(Math.random() * (base / 2));
  }

  private async once(body: string): Promise<ChatResult> {
    let res: Response;
    try {
      res = await this.fetchImpl(`${this.baseUrl}/chat/completions`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${this.apiKey}`, 'Content-Type': 'application/json' },
        body,
        signal: AbortSignal.timeout(this.timeoutMs),
      });
    } catch (err) {
      const name = err instanceof Error ? err.name : '';
      const timedOut = name === 'TimeoutError' || name === 'AbortError';
      throw new DeepSeekError(
        timedOut ? `DeepSeek request timed out after ${this.timeoutMs} ms` : `DeepSeek network error: ${String(err)}`,
        null,
        true,
      );
    }

    const text = await res.text();
    if (!res.ok) {
      let detail = text.slice(0, 500);
      try {
        detail = (JSON.parse(text) as RawResponse).error?.message ?? detail;
      } catch {
        /* non-JSON error body: keep the raw text */
      }
      const retryable = res.status === 429 || res.status >= 500;
      const hint =
        res.status === 401 ? ' (check DEEPSEEK_API_KEY)' : res.status === 402 ? ' (insufficient DeepSeek balance)' : '';
      const retryAfter = Number(res.headers.get('retry-after'));
      throw new DeepSeekError(
        `DeepSeek HTTP ${res.status}: ${detail}${hint}`,
        res.status,
        retryable,
        text,
        Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : undefined,
      );
    }

    let json: RawResponse;
    try {
      json = JSON.parse(text) as RawResponse;
    } catch {
      throw new DeepSeekError('DeepSeek returned a non-JSON response', res.status, true, text.slice(0, 500));
    }
    const choice = json.choices?.[0];
    if (!choice?.message) throw new DeepSeekError('DeepSeek response has no choices[0].message', res.status, false, text);

    // Normalize: keep only role/content/tool_calls. `reasoning_content` must never be sent back.
    const toolCalls: ToolCall[] = (choice.message.tool_calls ?? []).map((tc, i) => ({
      id: tc.id ?? `call_${i}`,
      type: 'function',
      function: { name: tc.function?.name ?? '', arguments: tc.function?.arguments ?? '{}' },
    }));
    const message: AssistantMessage = {
      role: 'assistant',
      content: choice.message.content ?? null,
      ...(toolCalls.length ? { tool_calls: toolCalls } : {}),
    };
    return { message, finish_reason: choice.finish_reason ?? null, usage: json.usage, model: json.model };
  }
}
