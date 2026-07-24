import assert from "node:assert/strict";
import test from "node:test";

import {
  RotationDiagnosticError,
  rotationSettingsFromEnv,
  runRotationDiagnostic,
} from "../src/rotation.js";


const SETTINGS = {
  proxyUrl: "http://proxy.example:8080",
  proxyUsername: "account",
  proxyPassword: "secret",
  targetUrl: "https://authorized.example/identity",
  targetLabel: "authorized identity endpoint",
  jsonField: "network.ip",
  samplesPerMode: 4,
};


function successful(value, elapsedMs = 25) {
  return {
    ok: true,
    attempts: 1,
    elapsedMs,
    json: () => ({ network: { ip: value } }),
  };
}


function clientFactoryFor(valuesByMode, calls = []) {
  const offsets = { pooled: 0, fresh_tunnel: 0 };
  return (settings) => {
    const mode = settings.connectionMode;
    calls.push({ type: "create", mode, maxAttempts: settings.maxAttempts });
    return {
      async get(target, options) {
        calls.push({
          type: "request",
          mode,
          target,
          requestId: options.requestId,
          retry: options.retry,
        });
        const value = valuesByMode[mode][offsets[mode]];
        offsets[mode] += 1;
        return value;
      },
      async close() {
        calls.push({ type: "close", mode });
      },
    };
  };
}


test("reads safe rotation settings from environment", () => {
  const value = rotationSettingsFromEnv({
    B2B_PROXY_URL: "https://proxy.example:8443",
    B2B_PROXY_USERNAME: "account",
    B2B_PROXY_PASSWORD: "secret",
    B2B_ROTATION_TARGET_URL: "https://authorized.example/identity",
    B2B_ROTATION_TARGET_LABEL: "customer identity check",
    B2B_ROTATION_JSON_FIELD: "network.ip",
    B2B_ROTATION_SAMPLES_PER_MODE: "7",
  });

  assert.equal(value.connectionMode, "pooled");
  assert.equal(value.targetLabel, "customer identity check");
  assert.equal(value.jsonField, "network.ip");
  assert.equal(value.samplesPerMode, 7);
});


test("detects connection-sensitive rotation without reporting observations", async () => {
  const calls = [];
  const report = await runRotationDiagnostic(
    SETTINGS,
    {
      clientFactory: clientFactoryFor(
        {
          pooled: [
            successful("198.51.100.10", 10),
            successful("198.51.100.10", 20),
            successful("198.51.100.10", 30),
            successful("198.51.100.10", 40),
          ],
          fresh_tunnel: [
            successful("198.51.100.20", 50),
            successful("198.51.100.21", 60),
            successful("198.51.100.22", 70),
            successful("198.51.100.23", 80),
          ],
        },
        calls,
      ),
      completedAt: () => new Date("2026-07-24T10:00:00.000Z"),
    },
  );

  assert.equal(report.completed_at, "2026-07-24T10:00:00.000Z");
  assert.equal(report.modes.pooled.unique_observations, 1);
  assert.equal(report.modes.pooled.reuse_rate, 0.75);
  assert.equal(report.modes.fresh_tunnel.unique_observations, 4);
  assert.equal(report.modes.fresh_tunnel.sequence_changes, 3);
  assert.deepEqual(report.comparison, {
    fresh_tunnel_unique_observation_gain: 3,
    fresh_tunnel_p50_latency_delta_ms: 40,
    fresh_tunnel_p50_latency_ratio: 3,
  });
  assert.equal(
    report.decision.connection_sensitivity,
    "connection_sensitive_rotation",
  );
  assert.equal(report.decision.independent_request_mode, "fresh_tunnel");
  assert.equal(report.automatic_mode_change, false);
  assert.deepEqual(
    calls.filter((item) => item.type === "close").map((item) => item.mode),
    ["pooled", "fresh_tunnel"],
  );
  assert.ok(
    calls
      .filter((item) => item.type === "request")
      .every((item) => item.retry === false),
  );
  assert.ok(
    calls
      .filter((item) => item.type === "create")
      .every((item) => item.maxAttempts === 1),
  );
  assert.doesNotMatch(
    JSON.stringify(report),
    /198\.51\.100\.|[a-f0-9]{16}/,
  );
});


test("prefers pooling when both modes already rotate independently", async () => {
  const report = await runRotationDiagnostic(
    { ...SETTINGS, samplesPerMode: 5 },
    {
      clientFactory: clientFactoryFor({
        pooled: [
          successful("pooled-a"),
          successful("pooled-b"),
          successful("pooled-c"),
          successful("pooled-d"),
          successful("pooled-d"),
        ],
        fresh_tunnel: [
          successful("fresh-a"),
          successful("fresh-b"),
          successful("fresh-c"),
          successful("fresh-d"),
          successful("fresh-e"),
        ],
      }),
    },
  );

  assert.equal(
    report.decision.connection_sensitivity,
    "high_rotation_in_both_modes",
  );
  assert.equal(report.decision.independent_request_mode, "pooled");
  assert.doesNotMatch(JSON.stringify(report), /pooled-a|fresh-a/);
});


test("reports insufficient evidence using stable error codes only", async () => {
  const privateError = "private proxy socket and endpoint details";
  const failed = {
    ok: false,
    attempts: 1,
    elapsedMs: 15,
    error: { code: `proxy_password=${privateError}`, message: privateError },
  };
  const report = await runRotationDiagnostic(
    { ...SETTINGS, samplesPerMode: 3 },
    {
      clientFactory: clientFactoryFor({
        pooled: [failed, failed, failed],
        fresh_tunnel: [
          successful("fresh-a"),
          successful("fresh-b"),
          successful("fresh-c"),
        ],
      }),
    },
  );

  assert.equal(
    report.decision.connection_sensitivity,
    "insufficient_evidence",
  );
  assert.deepEqual(report.modes.pooled.error_codes, {
    REQUEST_FAILED: 3,
  });
  assert.doesNotMatch(JSON.stringify(report), new RegExp(privateError));
});


test("rejects unsafe fields and out-of-range sample counts", async () => {
  await assert.rejects(
    () =>
      runRotationDiagnostic({
        ...SETTINGS,
        jsonField: "__proto__.secret",
      }),
    (error) =>
      error instanceof RotationDiagnosticError &&
      error.code === "INVALID_JSON_FIELD",
  );
  await assert.rejects(
    () =>
      runRotationDiagnostic({
        ...SETTINGS,
        samplesPerMode: 51,
      }),
    (error) => error instanceof RotationDiagnosticError,
  );
});
