import assert from "node:assert/strict";
import {
  chmod,
  mkdtemp,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  AcceptanceConfigError,
  buildAcceptanceSummary,
  evaluateBodyAssertion,
  loadPrivateAcceptanceConfig,
} from "../src/acceptance.js";


function validConfig() {
  return {
    artifact_dir: ".acceptance-output",
    proxy: {
      url: "http://proxy.example.test:8080",
      username: "client-user",
      password: "private-password",
    },
    http: {
      target_url: "https://service.example.test/ip",
      request_id: "acceptance-001",
      fingerprint_json_field: "network.ip",
      body_assertion: {
        json_field: "network.ip",
        equals: "203.0.113.10",
      },
    },
    browser: {
      approved: true,
      target_url: "https://service.example.test/check",
      target_label: "approved target",
      allowed_hosts: ["service.example.test"],
      capture_screenshot: false,
      capture_trace: false,
    },
  };
}


async function configFile(mode = 0o600, source = validConfig()) {
  const directory = await mkdtemp(path.join(os.tmpdir(), "acceptance-config-"));
  const destination = path.join(directory, "acceptance.private.json");
  await writeFile(destination, `${JSON.stringify(source)}\n`, { mode });
  await chmod(destination, mode);
  return destination;
}


test("loads a private acceptance config without exposing its values", async () => {
  const destination = await configFile();
  const config = await loadPrivateAcceptanceConfig(destination);

  assert.equal(config.proxy.username, "client-user");
  assert.equal(config.http.bodyAssertion.jsonField, "network.ip");
  assert.equal(config.browser.approved, true);
  assert.equal(
    config.artifactDir,
    path.join(path.dirname(destination), ".acceptance-output"),
  );
});


test("rejects a group-readable acceptance config", async () => {
  const destination = await configFile(0o640);

  await assert.rejects(
    () => loadPrivateAcceptanceConfig(destination),
    (error) =>
      error instanceof AcceptanceConfigError &&
      error.code === "UNSAFE_ACCEPTANCE_CONFIG_PERMISSIONS",
  );
});


test("rejects placeholders before any network operation", async () => {
  const source = validConfig();
  source.proxy.password = "replace_me";
  const destination = await configFile(0o600, source);

  await assert.rejects(
    () => loadPrivateAcceptanceConfig(destination),
    (error) => error.code === "ACCEPTANCE_PLACEHOLDER_FOUND",
  );
});


test("evaluates an optional private response assertion", () => {
  const response = {
    json: () => ({ network: { ip: "203.0.113.10" } }),
  };

  assert.deepEqual(
    evaluateBodyAssertion(response, {
      jsonField: "network.ip",
      equals: "203.0.113.10",
    }, "network.ip"),
    {
      configured: true,
      passed: true,
      observation_fingerprint: "7b17999e58497c64",
    },
  );
  assert.deepEqual(evaluateBodyAssertion(response, null), {
    configured: false,
    passed: null,
    observation_fingerprint: null,
  });
});


test("acceptance summary contains decisions but no response body", () => {
  const execution = {
    schema_version: "1.1",
    route: { selected: "http_proxy" },
    quality: { outcome: "success" },
  };
  const summary = buildAcceptanceSummary({
    completedAt: new Date("2026-07-24T10:00:00.000Z"),
    httpResult: {
      ok: true,
      execution,
      body: Buffer.from("private response"),
    },
    bodyAssertion: { configured: true, passed: true },
    browserReport: {
      job_id: "acceptance-001",
      state: "completed",
      execution: {
        ...execution,
        route: { selected: "browser" },
      },
      artifacts: { screenshot: null, trace: null },
    },
    replay: { verified: true },
    audit: { clean: true },
  });

  assert.equal(summary.passed, true);
  assert.doesNotMatch(JSON.stringify(summary), /private response/);
});
