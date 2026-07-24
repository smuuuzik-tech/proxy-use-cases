export type ProxyConnectionMode = "pooled" | "fresh_tunnel";

export interface ProxySettings {
  proxyUrl: string;
  proxyUsername?: string;
  proxyPassword?: string;
  connectionMode?: ProxyConnectionMode;
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
  estimatedCostPerAttempt?: number | null;
  costCurrency?: string | null;
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

export type ExecutionOutcome =
  | "success"
  | "http_error"
  | "transport_error"
  | "timeout"
  | "aborted"
  | "response_limit";

export type ExecutionNextAction =
  | "complete"
  | "none"
  | "review_http_response"
  | "review_policy_or_credentials"
  | "review_response_limit"
  | "review_retry_or_escalation";

export interface ProxyExecutionContract {
  schema_version: "1.1";
  route: {
    selected: "http_proxy" | "browser";
    reason: "configured_http_proxy" | "manual_browser_approval";
    next_action: ExecutionNextAction;
    automatic_escalation: false;
    manual_candidates: Array<"browser" | "managed_unblocker" | "ai_extraction">;
  };
  quality: {
    outcome: ExecutionOutcome;
    attempts: number;
    retries: number;
    elapsed_ms: number;
    status_code: number | null;
    response_bytes: number | null;
  };
  cost: {
    basis: "not_configured" | "per_attempt";
    currency: string | null;
    unit_cost: number | null;
    estimated_total: number | null;
  };
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
  readonly connectionMode: ProxyConnectionMode;
  readonly error: {
    code: string;
    kind: "aborted" | "response_limit" | "timeout" | "transport";
  } | null;
  readonly execution: ProxyExecutionContract;
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
