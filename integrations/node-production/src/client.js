import { randomUUID } from "node:crypto";
import { isIP } from "node:net";

import { ProxyAgent, request as undiciRequest } from "undici";

import { buildExecutionContract } from "./execution.js";

const IDEMPOTENT = new Set(["GET", "HEAD", "OPTIONS", "PUT", "DELETE"]);
const RETRYABLE = new Set([408, 425, 429, 500, 502, 503, 504]);
const CONNECTION_MODES = new Set(["pooled", "fresh_tunnel"]);
const DEFAULTS = Object.freeze({
  connectionMode: "pooled",
  maxAttempts: 3,
  connectTimeoutMs: 10_000,
  headersTimeoutMs: 15_000,
  bodyTimeoutMs: 30_000,
  deadlineMs: 60_000,
  maxResponseBytes: 10 * 1024 * 1024,
  backoffBaseMs: 250,
  backoffMaxMs: 5_000,
  jitterMs: 100,
  retryAfterMaxMs: 10_000,
  allowHttpTargets: false,
  allowPrivateTargets: false,
  estimatedCostPerAttempt: null,
  costCurrency: null,
});

export class ProxyConfigError extends Error {
  constructor(message, code = "INVALID_CONFIGURATION") {
    super(message);
    this.name = "ProxyConfigError";
    this.code = code;
  }
}

class ResponseLimitError extends Error {
  constructor() {
    super("Response exceeded the configured byte limit");
    this.code = "RESPONSE_TOO_LARGE";
  }
}

export class ProxyResult {
  constructor({
    ok,
    statusCode = null,
    attempts,
    elapsedMs,
    method,
    requestId,
    targetUrl,
    body = null,
    contentType = "",
    error = null,
    connectionMode = "pooled",
    estimatedCostPerAttempt = null,
    costCurrency = null,
  }) {
    this.ok = ok;
    this.statusCode = statusCode;
    this.attempts = attempts;
    this.retries = Math.max(0, attempts - 1);
    this.elapsedMs = elapsedMs;
    this.method = method;
    this.requestId = requestId;
    this.url = safeTarget(targetUrl);
    this.body = body;
    this.contentType = contentType;
    this.error = error;
    this.connectionMode = connectionMode;
    this.execution = buildExecutionContract({
      ok,
      attempts,
      elapsedMs,
      statusCode,
      responseBytes: body == null ? null : body.byteLength,
      errorKind: error?.kind || null,
      estimatedCostPerAttempt,
      costCurrency,
    });
  }

  text(encoding = "utf8") {
    return this.body ? this.body.toString(encoding) : "";
  }

  json() {
    return JSON.parse(this.text());
  }

  toJSON() {
    const value = {
      attempts: this.attempts,
      connection_mode: this.connectionMode,
      elapsed_ms: this.elapsedMs,
      execution: this.execution,
      method: this.method,
      ok: this.ok,
      request_id: this.requestId,
      retries: this.retries,
      status_code: this.statusCode,
      url: this.url,
    };
    if (this.body) {
      value.response = {
        bytes: this.body.byteLength,
        content_type: this.contentType || null,
      };
    }
    if (this.error) value.error = this.error;
    return value;
  }
}

export function settingsFromEnv(env = process.env) {
  return validateSettings({
    proxyUrl: required(env.B2B_PROXY_URL, "B2B_PROXY_URL"),
    proxyUsername: optional(env.B2B_PROXY_USERNAME),
    proxyPassword: optional(env.B2B_PROXY_PASSWORD),
    connectionMode: connectionMode(env.B2B_CONNECTION_MODE),
    maxAttempts: integer(env.B2B_MAX_ATTEMPTS, 3, 1, 8),
    connectTimeoutMs: integer(env.B2B_CONNECT_TIMEOUT_MS, 10_000, 100, 120_000),
    headersTimeoutMs: integer(env.B2B_HEADERS_TIMEOUT_MS, 15_000, 100, 120_000),
    bodyTimeoutMs: integer(env.B2B_BODY_TIMEOUT_MS, 30_000, 100, 300_000),
    deadlineMs: integer(env.B2B_DEADLINE_MS, 60_000, 100, 600_000),
    maxResponseBytes: integer(
      env.B2B_MAX_RESPONSE_BYTES,
      10 * 1024 * 1024,
      1,
      10 * 1024 * 1024,
    ),
    backoffBaseMs: integer(env.B2B_BACKOFF_BASE_MS, 250, 0, 60_000),
    backoffMaxMs: integer(env.B2B_BACKOFF_MAX_MS, 5_000, 0, 120_000),
    jitterMs: integer(env.B2B_JITTER_MS, 100, 0, 30_000),
    retryAfterMaxMs: integer(env.B2B_RETRY_AFTER_MAX_MS, 10_000, 0, 120_000),
    allowHttpTargets: boolean(env.B2B_ALLOW_HTTP_TARGETS, false),
    allowPrivateTargets: boolean(env.B2B_ALLOW_PRIVATE_TARGETS, false),
    estimatedCostPerAttempt: optionalNumber(
      env.B2B_ESTIMATED_COST_PER_ATTEMPT,
      0,
      1_000_000,
    ),
    costCurrency: currency(env.B2B_COST_CURRENCY),
  });
}

export class ProxyClient {
  constructor(
    settings,
    {
      dispatcher = null,
      dispatcherFactory = (options) => new ProxyAgent(options),
      requestFn = undiciRequest,
      sleep = defaultSleep,
      random = Math.random,
      now = Date.now,
    } = {},
  ) {
    this.settings = validateSettings(settings);
    this.requestFn = requestFn;
    this.sleep = sleep;
    this.random = random;
    this.now = now;
    this.closed = false;
    if (dispatcher && this.settings.connectionMode === "fresh_tunnel") {
      throw new ProxyConfigError(
        "An injected dispatcher is incompatible with fresh_tunnel",
        "INCOMPATIBLE_DISPATCHER",
      );
    }
    this.dispatcherFactory = dispatcherFactory;
    this.ownsDispatcher =
      this.settings.connectionMode === "pooled" && !dispatcher;
    this.dispatcher =
      this.settings.connectionMode === "pooled"
        ? dispatcher || createDispatcher(this.dispatcherFactory, this.settings)
        : null;
  }

  static fromEnv(env = process.env, dependencies = {}) {
    return new ProxyClient(settingsFromEnv(env), dependencies);
  }

  async close() {
    if (this.closed) return;
    this.closed = true;
    if (this.ownsDispatcher) await this.dispatcher.close();
  }

  async [Symbol.asyncDispose]() {
    await this.close();
  }

  get(target, options = {}) {
    return this.request("GET", target, options);
  }

  async request(method, target, options = {}) {
    if (this.closed) {
      throw new ProxyConfigError("ProxyClient is closed", "CLIENT_CLOSED");
    }
    const normalizedMethod = normalizeMethod(method);
    const targetUrl = validateTarget(target, this.settings);
    const headers = normalizeHeaders(options.headers);
    const requestId = validateRequestId(
      options.requestId || headers.get("x-request-id") || randomUUID(),
    );
    if (!headers.has("x-request-id")) headers.set("x-request-id", requestId);

    const canRetry =
      options.retry !== false &&
      IDEMPOTENT.has(normalizedMethod) &&
      replayable(options.body);
    const maxAttempts = canRetry ? this.settings.maxAttempts : 1;
    const started = this.now();

    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      const remaining = this.settings.deadlineMs - (this.now() - started);
      if (remaining <= 0) {
        return failed("DEADLINE_EXCEEDED", "timeout", {
          attempt: Math.max(0, attempt - 1),
          started,
          method: normalizedMethod,
          requestId,
          targetUrl,
          now: this.now,
          settings: this.settings,
        });
      }
      const timeoutSignal = AbortSignal.timeout(remaining);
      const signal = options.signal
        ? AbortSignal.any([options.signal, timeoutSignal])
        : timeoutSignal;
      let dispatcher = this.dispatcher;
      let ownsAttemptDispatcher = false;
      let outcome;
      try {
        if (this.settings.connectionMode === "fresh_tunnel") {
          dispatcher = createDispatcher(
            this.dispatcherFactory,
            this.settings,
          );
          ownsAttemptDispatcher = true;
        }
        const response = await this.requestFn(targetUrl, {
          method: normalizedMethod,
          dispatcher,
          headers: Object.fromEntries(headers),
          body: options.body,
          signal,
          headersTimeout: Math.min(this.settings.headersTimeoutMs, remaining),
          bodyTimeout: Math.min(this.settings.bodyTimeoutMs, remaining),
          maxRedirections: 0,
        });
        const body = await readBounded(
          response.body,
          this.settings.maxResponseBytes,
        );
        outcome = { type: "response", response, body };
      } catch (error) {
        outcome = { type: "error", error };
      } finally {
        if (
          ownsAttemptDispatcher &&
          !(await closeOwnedDispatcher(dispatcher))
        ) {
          outcome = { type: "cleanup_error" };
        }
      }

      if (outcome.type === "cleanup_error") {
        return failed("DISPATCHER_CLOSE_FAILED", "transport", {
          attempt,
          started,
          method: normalizedMethod,
          requestId,
          targetUrl,
          now: this.now,
          settings: this.settings,
        });
      }

      if (outcome.type === "response") {
        const { response, body } = outcome;
        const result = new ProxyResult({
          ok: response.statusCode >= 200 && response.statusCode < 300,
          statusCode: response.statusCode,
          attempts: attempt,
          elapsedMs: this.now() - started,
          method: normalizedMethod,
          requestId,
          targetUrl,
          body,
          contentType: header(response.headers, "content-type"),
          connectionMode: this.settings.connectionMode,
          estimatedCostPerAttempt: this.settings.estimatedCostPerAttempt,
          costCurrency: this.settings.costCurrency,
        });

        if (
          !canRetry ||
          attempt === maxAttempts ||
          !RETRYABLE.has(response.statusCode)
        ) {
          return result;
        }
        const retry = retryDelay(
          response.headers,
          attempt,
          this.settings,
          this.now,
          this.random,
        );
        if (!retry.allowed || this.now() - started + retry.delayMs >= this.settings.deadlineMs) {
          return result;
        }
        try {
          await this.sleep(retry.delayMs, options.signal);
        } catch {
          return failed("REQUEST_ABORTED", "aborted", {
            attempt,
            started,
            method: normalizedMethod,
            requestId,
            targetUrl,
            now: this.now,
            settings: this.settings,
          });
        }
        continue;
      }

      const classified = classify(
        outcome.error,
        options.signal?.aborted === true,
        timeoutSignal.aborted,
      );
      if (
        !canRetry ||
        attempt === maxAttempts ||
        classified.kind === "aborted" ||
        classified.kind === "response_limit"
      ) {
        return failed(classified.code, classified.kind, {
          attempt,
          started,
          method: normalizedMethod,
          requestId,
          targetUrl,
          now: this.now,
          settings: this.settings,
        });
      }
      const delay = backoff(attempt, this.settings, this.random);
      if (this.now() - started + delay >= this.settings.deadlineMs) {
        return failed(classified.code, classified.kind, {
          attempt,
          started,
          method: normalizedMethod,
          requestId,
          targetUrl,
          now: this.now,
          settings: this.settings,
        });
      }
      try {
        await this.sleep(delay, options.signal);
      } catch {
        return failed("REQUEST_ABORTED", "aborted", {
          attempt,
          started,
          method: normalizedMethod,
          requestId,
          targetUrl,
          now: this.now,
          settings: this.settings,
        });
      }
    }
    throw new Error("unreachable");
  }
}

function validateSettings(input) {
  if (!input || typeof input !== "object") {
    throw new ProxyConfigError("Settings must be an object");
  }
  const settings = { ...DEFAULTS, ...input };
  let proxy;
  try {
    proxy = new URL(required(settings.proxyUrl, "proxyUrl"));
  } catch {
    throw new ProxyConfigError("proxyUrl must be an absolute URL", "INVALID_PROXY_URL");
  }
  if (!["http:", "https:"].includes(proxy.protocol)) {
    throw new ProxyConfigError("proxyUrl must use http or https", "UNSUPPORTED_PROXY_SCHEME");
  }
  if (proxy.username || proxy.password) {
    throw new ProxyConfigError(
      "Pass proxy credentials separately from proxyUrl",
      "CREDENTIALS_IN_PROXY_URL",
    );
  }
  if ((proxy.pathname && proxy.pathname !== "/") || proxy.search || proxy.hash) {
    throw new ProxyConfigError("proxyUrl must not contain path, query, or fragment", "INVALID_PROXY_URL");
  }
  if (Boolean(settings.proxyUsername) !== Boolean(settings.proxyPassword)) {
    throw new ProxyConfigError(
      "proxyUsername and proxyPassword must be provided together",
      "INCOMPLETE_PROXY_CREDENTIALS",
    );
  }
  if (!CONNECTION_MODES.has(settings.connectionMode)) {
    throw new ProxyConfigError(
      "connectionMode must be pooled or fresh_tunnel",
      "INVALID_CONNECTION_MODE",
    );
  }
  const ranges = {
    maxAttempts: [1, 8],
    connectTimeoutMs: [100, 120_000],
    headersTimeoutMs: [100, 120_000],
    bodyTimeoutMs: [100, 300_000],
    deadlineMs: [100, 600_000],
    maxResponseBytes: [1, 10 * 1024 * 1024],
    backoffBaseMs: [0, 60_000],
    backoffMaxMs: [0, 120_000],
    jitterMs: [0, 30_000],
    retryAfterMaxMs: [0, 120_000],
  };
  for (const [key, [min, max]] of Object.entries(ranges)) {
    if (!Number.isInteger(settings[key]) || settings[key] < min || settings[key] > max) {
      throw new ProxyConfigError(`${key} must be an integer between ${min} and ${max}`, "INVALID_NUMERIC_LIMIT");
    }
  }
  if (settings.backoffMaxMs < settings.backoffBaseMs) {
    throw new ProxyConfigError("backoffMaxMs must be >= backoffBaseMs", "INVALID_BACKOFF");
  }
  if ((settings.estimatedCostPerAttempt == null) !== (settings.costCurrency == null)) {
    throw new ProxyConfigError(
      "estimatedCostPerAttempt and costCurrency must be provided together",
      "INVALID_COST_CONFIGURATION",
    );
  }
  if (
    settings.estimatedCostPerAttempt != null &&
    (
      !Number.isFinite(settings.estimatedCostPerAttempt) ||
      settings.estimatedCostPerAttempt < 0 ||
      settings.estimatedCostPerAttempt > 1_000_000
    )
  ) {
    throw new ProxyConfigError(
      "estimatedCostPerAttempt must be finite and between 0 and 1000000",
      "INVALID_COST_CONFIGURATION",
    );
  }
  if (
    settings.costCurrency != null &&
    !/^[A-Z]{3}$/.test(settings.costCurrency)
  ) {
    throw new ProxyConfigError(
      "costCurrency must be a three-letter uppercase code",
      "INVALID_COST_CONFIGURATION",
    );
  }
  return Object.freeze({
    ...settings,
    proxyUrl: proxy.toString(),
    proxyUsername: optional(settings.proxyUsername),
    proxyPassword: optional(settings.proxyPassword),
    allowHttpTargets: Boolean(settings.allowHttpTargets),
    allowPrivateTargets: Boolean(settings.allowPrivateTargets),
  });
}

function agentOptions(settings) {
  const options = {
    uri: settings.proxyUrl,
    connect: { timeout: settings.connectTimeoutMs },
  };
  if (settings.proxyUsername) {
    options.token = `Basic ${Buffer.from(
      `${settings.proxyUsername}:${settings.proxyPassword}`,
      "utf8",
    ).toString("base64")}`;
  }
  return options;
}

function createDispatcher(factory, settings) {
  let dispatcher;
  try {
    dispatcher = factory(agentOptions(settings));
  } catch {
    throw new ProxyConfigError(
      "Dispatcher factory failed",
      "DISPATCHER_CREATE_FAILED",
    );
  }
  if (!dispatcher || typeof dispatcher.close !== "function") {
    throw new ProxyConfigError(
      "Dispatcher factory must return a closeable dispatcher",
      "INVALID_DISPATCHER_FACTORY",
    );
  }
  return dispatcher;
}

async function closeOwnedDispatcher(dispatcher) {
  try {
    await dispatcher.close();
    return true;
  } catch {
    try {
      await dispatcher.destroy?.();
    } catch {
      // The public result remains sanitized even when forced cleanup fails.
    }
    return false;
  }
}

function validateTarget(target, settings) {
  let url;
  try {
    url = new URL(target);
  } catch {
    throw new ProxyConfigError("Target must be an absolute URL", "INVALID_TARGET");
  }
  if (url.username || url.password) {
    throw new ProxyConfigError("Target URL must not contain credentials", "CREDENTIALS_IN_TARGET_URL");
  }
  if (url.protocol !== "https:" && !(url.protocol === "http:" && settings.allowHttpTargets)) {
    throw new ProxyConfigError("Target must use https unless HTTP is explicitly allowed", "UNSAFE_TARGET_SCHEME");
  }
  if (!settings.allowPrivateTargets && unsafeHost(url.hostname)) {
    throw new ProxyConfigError(
      "Loopback, private, and link-local targets require explicit opt-in",
      "PRIVATE_TARGET_BLOCKED",
    );
  }
  return url;
}

function unsafeHost(hostname) {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  if (host === "localhost" || host.endsWith(".localhost")) return true;
  if (isIP(host) === 4) {
    const [a, b] = host.split(".").map(Number);
    return (
      a === 0 ||
      a === 10 ||
      a === 127 ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      a >= 224
    );
  }
  if (isIP(host) === 6) {
    return host === "::" || host === "::1" || host.startsWith("fc") ||
      host.startsWith("fd") || /^fe[89ab]/.test(host);
  }
  return false;
}

function normalizeMethod(value) {
  const method = String(value || "").trim().toUpperCase();
  if (!/^[A-Z]{3,12}$/.test(method)) {
    throw new ProxyConfigError("Invalid HTTP method", "INVALID_METHOD");
  }
  return method;
}

function normalizeHeaders(input = {}) {
  const result = new Map();
  for (const [rawName, rawValue] of Object.entries(input)) {
    const name = rawName.trim().toLowerCase();
    if (!/^[!#$%&'*+\-.^_`|~0-9a-z]+$/.test(name)) {
      throw new ProxyConfigError("Invalid header name", "INVALID_HEADER");
    }
    if (name === "proxy-authorization") {
      throw new ProxyConfigError(
        "Proxy credentials must not be sent as target headers",
        "UNSAFE_TARGET_HEADER",
      );
    }
    const value = String(rawValue);
    if (/[\r\n]/.test(value)) {
      throw new ProxyConfigError("Invalid header value", "INVALID_HEADER");
    }
    result.set(name, value);
  }
  return result;
}

function validateRequestId(value) {
  const result = String(value).trim();
  if (!/^[A-Za-z0-9._:-]{1,128}$/.test(result)) {
    throw new ProxyConfigError("Invalid requestId", "INVALID_REQUEST_ID");
  }
  return result;
}

async function readBounded(body, limit) {
  const chunks = [];
  let total = 0;
  for await (const raw of body) {
    const chunk = Buffer.from(raw);
    total += chunk.byteLength;
    if (total > limit) {
      if (typeof body.destroy === "function") body.destroy();
      throw new ResponseLimitError();
    }
    chunks.push(chunk);
  }
  return Buffer.concat(chunks, total);
}

function retryDelay(headers, attempt, settings, now, random) {
  const retryAfter = header(headers, "retry-after");
  if (retryAfter) {
    const numeric = Number(retryAfter);
    const delayMs = Number.isFinite(numeric)
      ? Math.max(0, numeric * 1_000)
      : Math.max(0, Date.parse(retryAfter) - now());
    if (Number.isFinite(delayMs)) {
      return { allowed: delayMs <= settings.retryAfterMaxMs, delayMs };
    }
  }
  return { allowed: true, delayMs: backoff(attempt, settings, random) };
}

function backoff(attempt, settings, random) {
  const base = Math.min(
    settings.backoffMaxMs,
    settings.backoffBaseMs * 2 ** Math.max(0, attempt - 1),
  );
  return Math.round(base + random() * settings.jitterMs);
}

function classify(error, externalAbort, internalTimeout = false) {
  if (error instanceof ResponseLimitError) {
    return { code: error.code, kind: "response_limit" };
  }
  if (externalAbort) return { code: "REQUEST_ABORTED", kind: "aborted" };
  if (internalTimeout) {
    return { code: "DEADLINE_EXCEEDED", kind: "timeout" };
  }
  const raw = typeof error?.code === "string" ? error.code : "";
  const code = /^[A-Z0-9_]{1,80}$/.test(raw) ? raw : "REQUEST_FAILED";
  if (code.includes("TIMEOUT") || error?.name === "TimeoutError") {
    return { code: code === "REQUEST_FAILED" ? "REQUEST_TIMEOUT" : code, kind: "timeout" };
  }
  if (code === "UND_ERR_ABORTED") return { code, kind: "transport" };
  return { code, kind: "transport" };
}

function failed(code, kind, context) {
  return new ProxyResult({
    ok: false,
    attempts: context.attempt,
    elapsedMs: context.now() - context.started,
    method: context.method,
    requestId: context.requestId,
    targetUrl: context.targetUrl,
    error: { code, kind },
    connectionMode: context.settings.connectionMode,
    estimatedCostPerAttempt: context.settings.estimatedCostPerAttempt,
    costCurrency: context.settings.costCurrency,
  });
}

function header(headers, name) {
  const raw = headers?.[name] ?? headers?.[name.toLowerCase()];
  return Array.isArray(raw) ? String(raw[0] || "") : String(raw ?? "");
}

function safeTarget(target) {
  const url = target instanceof URL ? target : new URL(target);
  return `${url.protocol}//${url.hostname}${url.port ? `:${url.port}` : ""}/<redacted-path>`;
}

function replayable(body) {
  return body == null || typeof body === "string" || Buffer.isBuffer(body) ||
    body instanceof Uint8Array || body instanceof ArrayBuffer;
}

function required(value, name) {
  const result = optional(value);
  if (!result) throw new ProxyConfigError(`${name} is required`);
  return result;
}

function optional(value) {
  return value == null ? "" : String(value).trim();
}

function integer(value, fallback, min, max) {
  if (value == null || value === "") return fallback;
  const number = Number(value);
  if (!Number.isInteger(number) || number < min || number > max) {
    throw new ProxyConfigError(`Expected integer between ${min} and ${max}`, "INVALID_NUMERIC_LIMIT");
  }
  return number;
}

function boolean(value, fallback) {
  if (value == null || value === "") return fallback;
  if (String(value).toLowerCase() === "true") return true;
  if (String(value).toLowerCase() === "false") return false;
  throw new ProxyConfigError("Expected true or false", "INVALID_BOOLEAN_VALUE");
}

function optionalNumber(value, min, max) {
  if (value == null || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number < min || number > max) {
    throw new ProxyConfigError(
      `Expected finite number between ${min} and ${max}`,
      "INVALID_COST_CONFIGURATION",
    );
  }
  return number;
}

function currency(value) {
  if (value == null || String(value).trim() === "") return null;
  return String(value).trim().toUpperCase();
}

function connectionMode(value) {
  if (value == null || String(value).trim() === "") return "pooled";
  const normalized = String(value).trim().toLowerCase();
  if (!CONNECTION_MODES.has(normalized)) {
    throw new ProxyConfigError(
      "B2B_CONNECTION_MODE must be pooled or fresh_tunnel",
      "INVALID_CONNECTION_MODE",
    );
  }
  return normalized;
}

function defaultSleep(delayMs, signal) {
  return new Promise((resolve, reject) => {
    const finish = () => {
      signal?.removeEventListener("abort", abort);
      resolve();
    };
    const timer = setTimeout(finish, delayMs);
    const abort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(signal.reason || new Error("aborted"));
    };
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) abort();
  });
}
