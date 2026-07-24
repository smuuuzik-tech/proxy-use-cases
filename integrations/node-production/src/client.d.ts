export interface ProxySettings {
  proxyUrl: string;
  proxyUsername?: string;
  proxyPassword?: string;
  maxAttempts?: number;
  connectTimeoutMs?: number;
  headersTimeoutMs?: number;
  bodyTimeoutMs?: number;
  deadlineMs?: number;
  maxResponseBytes?: number;
  backoffBaseMs?: number;
  backoffMaxMs?: number;
  jitterMs?: number;
  retryAfterMaxMs?: number;
  allowHttpTargets?: boolean;
  allowPrivateTargets?: boolean;
}

export interface ProxyRequestOptions {
  headers?: Record<string, string>;
  body?: string | Uint8Array | ArrayBuffer;
  requestId?: string;
  retry?: boolean;
  signal?: AbortSignal;
}

export class ProxyConfigError extends Error {
  code: string;
}

export class ProxyResult {
  readonly ok: boolean;
  readonly statusCode: number | null;
  readonly attempts: number;
  readonly retries: number;
  readonly elapsedMs: number;
  readonly method: string;
  readonly requestId: string;
  readonly url: string;
  readonly body: Uint8Array | null;
  readonly contentType: string;
  readonly error: {
    code: string;
    kind: "aborted" | "response_limit" | "timeout" | "transport";
  } | null;
  text(encoding?: string): string;
  json<T = unknown>(): T;
  toJSON(): Record<string, unknown>;
}

export function settingsFromEnv(
  env?: Record<string, string | undefined>,
): Required<ProxySettings>;

export class ProxyClient {
  constructor(settings: ProxySettings, dependencies?: Record<string, unknown>);
  static fromEnv(
    env?: Record<string, string | undefined>,
    dependencies?: Record<string, unknown>,
  ): ProxyClient;
  close(): Promise<void>;
  get(target: string | URL, options?: ProxyRequestOptions): Promise<ProxyResult>;
  request(
    method: string,
    target: string | URL,
    options?: ProxyRequestOptions,
  ): Promise<ProxyResult>;
}
