import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { buildExecutionContract } from "../integrations/node-production/src/execution.js";


const root = resolve(import.meta.dirname, "..");
const readJson = (path) =>
  JSON.parse(readFileSync(resolve(root, path), "utf8"));

const schema = readJson("contracts/proxy-execution.schema.json");
const browser = readJson("contracts/fixtures/execution-browser-success.json");
const success = readJson("contracts/fixtures/execution-success.json");
const timeout = readJson("contracts/fixtures/execution-timeout.json");

assert.equal(schema.$schema, "https://json-schema.org/draft/2020-12/schema");
assert.equal(schema.properties.schema_version.const, "1.1");
assert.deepEqual(schema.required, [
  "schema_version",
  "route",
  "quality",
  "cost",
]);

assert.deepEqual(
  buildExecutionContract({
    ok: true,
    attempts: 1,
    elapsedMs: 925,
    statusCode: 200,
    selectedRoute: "browser",
    routeReason: "manual_browser_approval",
  }),
  browser,
);
assert.deepEqual(
  buildExecutionContract({
    ok: true,
    attempts: 1,
    elapsedMs: 184,
    statusCode: 200,
    responseBytes: 17,
  }),
  success,
);
assert.deepEqual(
  buildExecutionContract({
    ok: false,
    attempts: 3,
    elapsedMs: 1500,
    errorKind: "timeout",
    estimatedCostPerAttempt: 0.002,
    costCurrency: "USD",
  }),
  timeout,
);

for (const fixture of [browser, success, timeout]) {
  assert.equal(fixture.route.automatic_escalation, false);
  assert.equal(fixture.quality.retries, Math.max(0, fixture.quality.attempts - 1));
  assert.ok(!JSON.stringify(fixture).match(/password|token|proxy_url|target_url/i));
}

process.stdout.write("Execution contract OK: schema 1.1, 3 fixtures.\n");
