import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { buildExecutionContract } from "../src/execution.js";


function fixture(name) {
  return JSON.parse(
    readFileSync(
      new URL(`../../../contracts/fixtures/${name}`, import.meta.url),
      "utf8",
    ),
  );
}

test("success contract matches the cross-language fixture", () => {
  const contract = buildExecutionContract({
    ok: true,
    attempts: 1,
    elapsedMs: 184,
    statusCode: 200,
    responseBytes: 17,
  });

  assert.deepEqual(contract, fixture("execution-success.json"));
});

test("timeout contract matches the cross-language fixture", () => {
  const contract = buildExecutionContract({
    ok: false,
    attempts: 3,
    elapsedMs: 1500,
    errorKind: "timeout",
    estimatedCostPerAttempt: 0.002,
    costCurrency: "USD",
  });

  assert.deepEqual(contract, fixture("execution-timeout.json"));
});

test("browser contract matches the cross-language fixture", () => {
  const contract = buildExecutionContract({
    ok: true,
    attempts: 1,
    elapsedMs: 925,
    statusCode: 200,
    selectedRoute: "browser",
    routeReason: "manual_browser_approval",
  });

  assert.deepEqual(contract, fixture("execution-browser-success.json"));
});

test("HTTP outcomes produce stable next actions", () => {
  const auth = buildExecutionContract({
    ok: false,
    attempts: 1,
    elapsedMs: 10,
    statusCode: 407,
  });
  const rateLimit = buildExecutionContract({
    ok: false,
    attempts: 2,
    elapsedMs: 25,
    statusCode: 429,
  });
  const notFound = buildExecutionContract({
    ok: false,
    attempts: 1,
    elapsedMs: 10,
    statusCode: 404,
  });

  assert.equal(auth.route.next_action, "review_policy_or_credentials");
  assert.equal(rateLimit.route.next_action, "review_retry_or_escalation");
  assert.equal(notFound.route.next_action, "review_http_response");
  assert.equal(auth.route.automatic_escalation, false);
});
