import { createHash } from "node:crypto";
import { lstat, readFile } from "node:fs/promises";
import path from "node:path";

import { BrowserPolicyError } from "./browser.js";


const MAX_ACCEPTANCE_CONFIG_BYTES = 64 * 1024;
const FIELD_PATH_PATTERN = /^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$/;


export class AcceptanceConfigError extends Error {
  constructor(message, code = "INVALID_ACCEPTANCE_CONFIG") {
    super(message);
    this.name = "AcceptanceConfigError";
    this.code = code;
  }
}


function requiredString(value, name) {
  if (typeof value !== "string" || !value.trim()) {
    throw new AcceptanceConfigError(`${name} is required`);
  }
  if (/replace[_ -]?me|secret-from-secret-manager/i.test(value)) {
    throw new AcceptanceConfigError(
      `${name} still contains a placeholder`,
      "ACCEPTANCE_PLACEHOLDER_FOUND",
    );
  }
  return value;
}


function parseBodyAssertion(value) {
  if (value == null) return null;
  if (
    typeof value !== "object" ||
    !FIELD_PATH_PATTERN.test(value.json_field || "") ||
    !["string", "number", "boolean"].includes(typeof value.equals) ||
    (
      typeof value.equals === "string" &&
      /replace[_ -]?me|secret-from-secret-manager/i.test(value.equals)
    )
  ) {
    throw new AcceptanceConfigError(
      "http.body_assertion must contain a safe json_field and scalar equals value",
    );
  }
  return Object.freeze({
    jsonField: value.json_field,
    equals: value.equals,
  });
}

function parseOptionalFieldPath(value, name) {
  if (value == null || value === "") return null;
  if (!FIELD_PATH_PATTERN.test(value)) {
    throw new AcceptanceConfigError(`${name} must be a safe dotted field path`);
  }
  return value;
}

function parseConnectionMode(value) {
  const normalized =
    value == null || value === ""
      ? "pooled"
      : String(value).trim().toLowerCase();
  if (!["pooled", "fresh_tunnel"].includes(normalized)) {
    throw new AcceptanceConfigError(
      "http.connection_mode must be pooled or fresh_tunnel",
      "INVALID_CONNECTION_MODE",
    );
  }
  return normalized;
}


export async function loadPrivateAcceptanceConfig(configPath) {
  const absolute = path.resolve(configPath);
  const info = await lstat(absolute);
  if (!info.isFile() || info.isSymbolicLink()) {
    throw new AcceptanceConfigError(
      "Acceptance config must be a regular file",
      "UNSAFE_ACCEPTANCE_CONFIG",
    );
  }
  if ((info.mode & 0o077) !== 0) {
    throw new AcceptanceConfigError(
      "Acceptance config must be readable only by its owner",
      "UNSAFE_ACCEPTANCE_CONFIG_PERMISSIONS",
    );
  }
  if (info.size > MAX_ACCEPTANCE_CONFIG_BYTES) {
    throw new AcceptanceConfigError(
      "Acceptance config is too large",
      "ACCEPTANCE_CONFIG_TOO_LARGE",
    );
  }
  let source;
  try {
    source = JSON.parse(await readFile(absolute, "utf8"));
  } catch {
    throw new AcceptanceConfigError(
      "Acceptance config must be valid JSON",
      "INVALID_ACCEPTANCE_JSON",
    );
  }
  if (
    !source ||
    typeof source !== "object" ||
    !source.proxy ||
    !source.http ||
    !source.browser
  ) {
    throw new AcceptanceConfigError(
      "Acceptance config requires proxy, http, and browser sections",
    );
  }
  const artifactDir = path.resolve(
    path.dirname(absolute),
    source.artifact_dir || ".local-acceptance",
  );
  return Object.freeze({
    artifactDir,
    proxy: Object.freeze({
      url: requiredString(source.proxy.url, "proxy.url"),
      username:
        source.proxy.username == null
          ? undefined
          : requiredString(source.proxy.username, "proxy.username"),
      password:
        source.proxy.password == null
          ? undefined
          : requiredString(source.proxy.password, "proxy.password"),
    }),
    http: Object.freeze({
      targetUrl: requiredString(source.http.target_url, "http.target_url"),
      connectionMode: parseConnectionMode(source.http.connection_mode),
      requestId:
        source.http.request_id || "local-proxy-acceptance",
      bodyAssertion: parseBodyAssertion(source.http.body_assertion),
      fingerprintJsonField: parseOptionalFieldPath(
        source.http.fingerprint_json_field,
        "http.fingerprint_json_field",
      ),
    }),
    browser: Object.freeze({
      approved: source.browser.approved === true,
      targetUrl: requiredString(
        source.browser.target_url,
        "browser.target_url",
      ),
      targetLabel: requiredString(
        source.browser.target_label,
        "browser.target_label",
      ),
      allowedHosts: source.browser.allowed_hosts,
      resourceAllowedHosts:
        source.browser.resource_allowed_hosts ||
        source.browser.allowed_hosts,
      captureScreenshot: source.browser.capture_screenshot === true,
      captureTrace: source.browser.capture_trace === true,
      jobId: source.browser.job_id || undefined,
      navigationTimeoutMs: source.browser.navigation_timeout_ms,
      totalDeadlineMs: source.browser.total_deadline_ms,
      maxRequests: source.browser.max_requests,
      expectedStatusMin: source.browser.expected_status_min,
      expectedStatusMax: source.browser.expected_status_max,
      headless: source.browser.headless !== false,
      fullPage: source.browser.full_page === true,
      maxScreenshotBytes: source.browser.max_screenshot_bytes,
      allowPrivateTargets: source.browser.allow_private_targets === true,
    }),
    cost: Object.freeze({
      estimatedPerAttempt:
        source.cost?.estimated_per_attempt == null
          ? null
          : Number(source.cost.estimated_per_attempt),
      currency:
        source.cost?.currency == null
          ? null
          : String(source.cost.currency).trim().toUpperCase(),
    }),
  });
}


function valueAtPath(value, fieldPath) {
  return fieldPath.split(".").reduce(
    (current, part) =>
      current && typeof current === "object" ? current[part] : undefined,
    value,
  );
}


export function evaluateBodyAssertion(
  response,
  assertion,
  fingerprintJsonField = null,
) {
  if (assertion == null && fingerprintJsonField == null) {
    return {
      configured: false,
      passed: null,
      observation_fingerprint: null,
    };
  }
  let payload;
  try {
    payload = response.json();
  } catch {
    return {
      configured: assertion != null,
      passed: assertion == null ? null : false,
      observation_fingerprint: null,
    };
  }
  const observed =
    fingerprintJsonField == null
      ? undefined
      : valueAtPath(payload, fingerprintJsonField);
  const observationFingerprint =
    observed == null ||
    !["string", "number", "boolean"].includes(typeof observed)
      ? null
      : createHash("sha256")
          .update(`${typeof observed}:${String(observed)}`)
          .digest("hex")
          .slice(0, 16);
  return {
    configured: assertion != null,
    passed:
      assertion == null
        ? null
        : valueAtPath(payload, assertion.jsonField) === assertion.equals,
    observation_fingerprint: observationFingerprint,
  };
}


export function validateAcceptanceApproval(config) {
  if (config.browser.approved !== true) {
    throw new BrowserPolicyError(
      "Private acceptance config must explicitly approve the browser route",
      "BROWSER_ROUTE_NOT_APPROVED",
    );
  }
}


export function buildAcceptanceSummary({
  completedAt,
  httpResult,
  bodyAssertion,
  browserReport,
  replay,
  audit,
}) {
  const httpPassed =
    httpResult.ok &&
    (bodyAssertion.passed === true || bodyAssertion.configured === false);
  const browserPassed =
    browserReport.state === "completed" &&
    replay.verified === true &&
    audit.clean === true;
  return {
    schema_version: "1.0",
    completed_at: completedAt.toISOString(),
    passed: httpPassed && browserPassed,
    http: {
      passed: httpPassed,
      connection_mode: httpResult.connectionMode,
      body_assertion: bodyAssertion,
      execution: httpResult.execution,
    },
    browser: {
      passed: browserPassed,
      job_id: browserReport.job_id,
      state: browserReport.state,
      replay_verified: replay.verified,
      audit_clean: audit.clean,
      execution: browserReport.execution,
      artifacts: browserReport.artifacts,
    },
  };
}
