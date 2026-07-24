import assert from "node:assert/strict";
import test from "node:test";

import {
  ProxyClient,
  ProxyConfigError,
  settingsFromEnv,
} from "../src/client.js";

const SETTINGS = {
  proxyUrl: "http://proxy.example:8080",
  maxAttempts: 3,
  connectTimeoutMs: 1_000,
  headersTimeoutMs: 1_000,
  bodyTimeoutMs: 1_000,
  deadlineMs: 10_000,
  maxResponseBytes: 1_024,
  backoffBaseMs: 10,
  backoffMaxMs: 100,
  jitterMs: 0,
  retryAfterMaxMs: 1_000,
};

function body(...chunks) {
  return {
    destroy() {},
    async *[Symbol.asyncIterator]() {
      for (const chunk of chunks) yield Buffer.from(chunk);
    },
  };
}

function response(statusCode, chunks = ["{}"], headers = {}) {
  return { statusCode, headers, body: body(...chunks) };
}

function mocked(requestFn, overrides = {}) {
  return new ProxyClient(
    { ...SETTINGS, ...overrides },
    {
      dispatcher: { close: async () => {} },
      requestFn,
      sleep: async () => {},
      random: () => 0,
    },
  );
}

test("reads bounded settings from environment", () => {
  const value = settingsFromEnv({
    B2B_PROXY_URL: "https://proxy.example:8443",
    B2B_PROXY_USERNAME: "account",
    B2B_PROXY_PASSWORD: "secret",
    B2B_MAX_ATTEMPTS: "4",
    B2B_ALLOW_HTTP_TARGETS: "true",
  });
  assert.equal(value.maxAttempts, 4);
  assert.equal(value.allowHttpTargets, true);
});

test("rejects credentials embedded in proxy URL", () => {
  assert.throws(
    () =>
      new ProxyClient({
        ...SETTINGS,
        proxyUrl: "http://user:secret@proxy.example:8080",
      }),
    (error) =>
      error instanceof ProxyConfigError &&
      error.code === "CREDENTIALS_IN_PROXY_URL",
  );
});

test("returns a stable configuration error for an invalid proxy URL", () => {
  assert.throws(
    () =>
      new ProxyClient({
        ...SETTINGS,
        proxyUrl: "not a proxy URL with secret=value",
      }),
    (error) =>
      error instanceof ProxyConfigError &&
      error.code === "INVALID_PROXY_URL" &&
      !error.message.includes("secret"),
  );
});

test("blocks HTTP and loopback targets by default", async () => {
  const client = mocked(async () => response(200));
  await assert.rejects(
    () => client.get("http://service.example/items"),
    (error) => error.code === "UNSAFE_TARGET_SCHEME",
  );
  await assert.rejects(
    () => client.get("https://127.0.0.1/items"),
    (error) => error.code === "PRIVATE_TARGET_BLOCKED",
  );
});

test("returns body to code while JSON remains redacted", async () => {
  const calls = [];
  const client = mocked(async (url, options) => {
    calls.push({ url: String(url), options });
    return response(200, ['{"items":[1,2]}'], {
      "content-type": "application/json",
    });
  });
  const result = await client.get(
    "https://service.example/private/items?token=secret",
    { requestId: "inventory-001" },
  );
  assert.equal(result.ok, true);
  assert.deepEqual(result.json(), { items: [1, 2] });
  assert.equal(result.url, "https://service.example/<redacted-path>");
  assert.equal(calls[0].options.maxRedirections, 0);
  assert.equal(calls[0].options.headers["x-request-id"], "inventory-001");
  assert.doesNotMatch(JSON.stringify(result), /private|token|secret|items/);
  assert.equal(result.execution.quality.outcome, "success");
  assert.equal(result.execution.route.selected, "http_proxy");
  assert.equal(result.execution.route.automatic_escalation, false);
});

test("retries retryable status for GET", async () => {
  let calls = 0;
  const client = mocked(async () => {
    calls += 1;
    return calls === 1 ? response(503) : response(200);
  });
  const result = await client.get("https://service.example/health");
  assert.equal(result.ok, true);
  assert.equal(result.attempts, 2);
});

test("estimates configured attempt cost after retries", async () => {
  let calls = 0;
  const client = mocked(
    async () => {
      calls += 1;
      return calls === 1 ? response(503) : response(200);
    },
    {
      estimatedCostPerAttempt: 0.002,
      costCurrency: "USD",
    },
  );

  const result = await client.get("https://service.example/health");

  assert.deepEqual(result.execution.cost, {
    basis: "per_attempt",
    currency: "USD",
    unit_cost: 0.002,
    estimated_total: 0.004,
  });
});

test("cost configuration is optional but must be complete", () => {
  const configured = settingsFromEnv({
    B2B_PROXY_URL: "https://proxy.example:8443",
    B2B_ESTIMATED_COST_PER_ATTEMPT: "0.0025",
    B2B_COST_CURRENCY: "usd",
  });
  assert.equal(configured.estimatedCostPerAttempt, 0.0025);
  assert.equal(configured.costCurrency, "USD");

  assert.throws(
    () =>
      new ProxyClient({
        ...SETTINGS,
        estimatedCostPerAttempt: 0.1,
      }),
    (error) =>
      error instanceof ProxyConfigError &&
      error.code === "INVALID_COST_CONFIGURATION",
  );
});

test("does not retry POST", async () => {
  let calls = 0;
  const client = mocked(async () => {
    calls += 1;
    return response(503);
  });
  const result = await client.request(
    "POST",
    "https://service.example/items",
    { body: "{}" },
  );
  assert.equal(result.attempts, 1);
  assert.equal(calls, 1);
});

test("does not retry excessive Retry-After", async () => {
  let calls = 0;
  const client = mocked(async () => {
    calls += 1;
    return response(429, ["limited"], { "retry-after": "120" });
  });
  const result = await client.get("https://service.example/items");
  assert.equal(result.statusCode, 429);
  assert.equal(calls, 1);
});

test("enforces response byte limit", async () => {
  const client = mocked(async () => response(200, ["1234", "5678"]), {
    maxResponseBytes: 6,
  });
  const result = await client.get("https://service.example/large");
  assert.deepEqual(result.error, {
    code: "RESPONSE_TOO_LARGE",
    kind: "response_limit",
  });
});

test("returns stable error without leaking message", async () => {
  const client = mocked(async () => {
    const error = new Error("http://user:secret@proxy.example");
    error.code = "UND_ERR_CONNECT_TIMEOUT";
    throw error;
  });
  const result = await client.get("https://service.example/items?secret=1");
  assert.equal(result.attempts, 3);
  assert.deepEqual(result.error, {
    code: "UND_ERR_CONNECT_TIMEOUT",
    kind: "timeout",
  });
  assert.doesNotMatch(JSON.stringify(result), /user|secret|proxy\.example/);
});

test("returns a stable result when an external abort interrupts backoff", async () => {
  const controller = new AbortController();
  const client = new ProxyClient(SETTINGS, {
    dispatcher: { close: async () => {} },
    requestFn: async () => {
      const error = new Error("user:secret@proxy.example");
      error.code = "UND_ERR_SOCKET";
      throw error;
    },
    sleep: async () => {
      controller.abort(new Error("private abort reason"));
      throw controller.signal.reason;
    },
  });
  const result = await client.get("https://service.example/private?token=1", {
    signal: controller.signal,
  });
  assert.deepEqual(result.error, {
    code: "REQUEST_ABORTED",
    kind: "aborted",
  });
  assert.doesNotMatch(
    JSON.stringify(result),
    /secret|proxy\.example|private abort|token/,
  );
});

test("rejects Proxy-Authorization as target header", async () => {
  const client = mocked(async () => response(200));
  await assert.rejects(
    () =>
      client.get("https://service.example/items", {
        headers: { "Proxy-Authorization": "Basic secret" },
      }),
    (error) => error.code === "UNSAFE_TARGET_HEADER",
  );
});

test("does not close injected dispatcher", async () => {
  let closes = 0;
  const client = new ProxyClient(SETTINGS, {
    dispatcher: { close: async () => (closes += 1) },
    requestFn: async () => response(200),
  });
  await client.close();
  await client.close();
  assert.equal(closes, 0);
});
