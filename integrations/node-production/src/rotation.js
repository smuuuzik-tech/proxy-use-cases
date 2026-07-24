import { createHash } from "node:crypto";

import {
  ProxyClient,
  ProxyConfigError,
  settingsFromEnv,
} from "./client.js";


const FIELD_PATH_PATTERN = /^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$/;
const MODES = Object.freeze(["pooled", "fresh_tunnel"]);


export class RotationDiagnosticError extends Error {
  constructor(message, code = "INVALID_ROTATION_DIAGNOSTIC") {
    super(message);
    this.name = "RotationDiagnosticError";
    this.code = code;
  }
}


function required(value, name) {
  const normalized = value == null ? "" : String(value).trim();
  if (!normalized) {
    throw new RotationDiagnosticError(`${name} is required`);
  }
  return normalized;
}


function integer(value, fallback, minimum, maximum, name) {
  if (value == null || String(value).trim() === "") return fallback;
  const parsed = Number(value);
  if (
    !Number.isSafeInteger(parsed) ||
    parsed < minimum ||
    parsed > maximum
  ) {
    throw new RotationDiagnosticError(
      `${name} must be an integer between ${minimum} and ${maximum}`,
    );
  }
  return parsed;
}


function targetLabel(value) {
  const label = required(value, "targetLabel");
  if (
    label.length > 80 ||
    !/^[\p{Letter}\p{Number} _-]+$/u.test(label)
  ) {
    throw new RotationDiagnosticError(
      "targetLabel must contain only letters, numbers, spaces, underscore, or dash",
      "INVALID_TARGET_LABEL",
    );
  }
  return label;
}


function fieldPath(value) {
  const normalized = required(value, "jsonField");
  const unsafeSegments = new Set(["__proto__", "constructor", "prototype"]);
  if (
    !FIELD_PATH_PATTERN.test(normalized) ||
    normalized.split(".").some((part) => unsafeSegments.has(part))
  ) {
    throw new RotationDiagnosticError(
      "jsonField must be a safe dotted field path",
      "INVALID_JSON_FIELD",
    );
  }
  return normalized;
}


export function rotationSettingsFromEnv(env = process.env) {
  const proxySettings = settingsFromEnv({
    ...env,
    B2B_CONNECTION_MODE: "pooled",
  });
  return Object.freeze({
    ...proxySettings,
    targetUrl: required(
      env.B2B_ROTATION_TARGET_URL,
      "B2B_ROTATION_TARGET_URL",
    ),
    targetLabel: targetLabel(
      env.B2B_ROTATION_TARGET_LABEL || "authorized rotation check",
    ),
    jsonField: fieldPath(env.B2B_ROTATION_JSON_FIELD || "ip"),
    samplesPerMode: integer(
      env.B2B_ROTATION_SAMPLES_PER_MODE,
      10,
      3,
      50,
      "B2B_ROTATION_SAMPLES_PER_MODE",
    ),
  });
}


function normalizeSettings(input) {
  if (!input || typeof input !== "object") {
    throw new RotationDiagnosticError("Rotation settings must be an object");
  }
  const {
    targetUrl,
    targetLabel: rawTargetLabel,
    jsonField: rawJsonField = "ip",
    samplesPerMode: rawSamples = 10,
    ...proxySettings
  } = input;
  return Object.freeze({
    targetUrl: required(targetUrl, "targetUrl"),
    targetLabel: targetLabel(rawTargetLabel),
    jsonField: fieldPath(rawJsonField),
    samplesPerMode: integer(
      rawSamples,
      10,
      3,
      50,
      "samplesPerMode",
    ),
    proxySettings: Object.freeze({
      ...proxySettings,
      maxAttempts: 1,
    }),
  });
}


function valueAtPath(value, path) {
  return path.split(".").reduce(
    (current, part) =>
      current && typeof current === "object" ? current[part] : undefined,
    value,
  );
}


function observationFingerprint(value) {
  if (!["string", "number", "boolean"].includes(typeof value)) return null;
  return createHash("sha256")
    .update(`${typeof value}:${String(value)}`)
    .digest("hex")
    .slice(0, 16);
}


function percentile(values, fraction) {
  if (!values.length) return null;
  const ordered = [...values].sort((left, right) => left - right);
  return ordered[Math.max(0, Math.ceil(ordered.length * fraction) - 1)];
}


function counts(values) {
  const result = {};
  for (const value of values) {
    const key = String(value);
    result[key] = (result[key] || 0) + 1;
  }
  return Object.fromEntries(
    Object.entries(result).sort(([left], [right]) =>
      left.localeCompare(right),
    ),
  );
}


function stableErrorCode(value) {
  const normalized = typeof value === "string" ? value : "";
  return /^[A-Z0-9_]{1,80}$/.test(normalized)
    ? normalized
    : "REQUEST_FAILED";
}


function summarizeMode(mode, observations) {
  const successful = observations.filter((item) => item.ok);
  const fingerprints = successful.map((item) => item.fingerprint);
  const sequenceChanges = fingerprints
    .slice(1)
    .filter((value, index) => value !== fingerprints[index]).length;
  const latencies = successful.map((item) => item.elapsedMs);
  return {
    connection_mode: mode,
    requests: observations.length,
    successful: successful.length,
    failed: observations.length - successful.length,
    attempts: observations.reduce(
      (total, item) => total + item.attempts,
      0,
    ),
    unique_observations: new Set(fingerprints).size,
    sequence_changes: sequenceChanges,
    reuse_rate:
      successful.length === 0
        ? null
        : Number(
            (
              1 -
              new Set(fingerprints).size / successful.length
            ).toFixed(4),
          ),
    latency_ms: {
      p50: percentile(latencies, 0.5),
      p95: percentile(latencies, 0.95),
      max: latencies.length ? Math.max(...latencies) : null,
    },
    error_codes: counts(
      observations
        .filter((item) => !item.ok)
        .map((item) => stableErrorCode(item.errorCode)),
    ),
  };
}


function connectionSensitivity(pooled, fresh) {
  if (
    pooled.successful < pooled.requests ||
    fresh.successful < fresh.requests
  ) {
    return "insufficient_evidence";
  }
  if (
    pooled.unique_observations === 1 &&
    fresh.unique_observations === 1
  ) {
    return "stable_or_provider_sticky";
  }
  if (
    pooled.unique_observations / pooled.successful >= 0.8 &&
    fresh.unique_observations / fresh.successful >= 0.8
  ) {
    return "high_rotation_in_both_modes";
  }
  if (
    fresh.unique_observations > pooled.unique_observations &&
    fresh.unique_observations / fresh.successful >= 0.8
  ) {
    return "connection_sensitive_rotation";
  }
  return "mixed_rotation";
}


function compareModes(pooled, fresh) {
  const pooledP50 = pooled.latency_ms.p50;
  const freshP50 = fresh.latency_ms.p50;
  return {
    fresh_tunnel_unique_observation_gain:
      fresh.unique_observations - pooled.unique_observations,
    fresh_tunnel_p50_latency_delta_ms:
      pooledP50 == null || freshP50 == null
        ? null
        : freshP50 - pooledP50,
    fresh_tunnel_p50_latency_ratio:
      pooledP50 == null || freshP50 == null || pooledP50 === 0
        ? null
        : Number((freshP50 / pooledP50).toFixed(4)),
  };
}


async function runMode({
  mode,
  settings,
  clientFactory,
}) {
  const observations = [];
  const client = clientFactory({
    ...settings.proxySettings,
    connectionMode: mode,
  });
  try {
    for (let index = 0; index < settings.samplesPerMode; index += 1) {
      const result = await client.get(settings.targetUrl, {
        requestId: `rotation-${mode}-${index + 1}`,
        retry: false,
      });
      if (!result.ok) {
        observations.push({
          ok: false,
          attempts: result.attempts,
          elapsedMs: result.elapsedMs,
          errorCode:
            result.error?.code ||
            (result.statusCode == null
              ? "REQUEST_FAILED"
              : `HTTP_${result.statusCode}`),
        });
        continue;
      }
      let payload;
      try {
        payload = result.json();
      } catch {
        payload = null;
      }
      const fingerprint = observationFingerprint(
        valueAtPath(payload, settings.jsonField),
      );
      observations.push({
        ok: fingerprint !== null,
        attempts: result.attempts,
        elapsedMs: result.elapsedMs,
        fingerprint,
        errorCode:
          fingerprint === null ? "INVALID_OBSERVATION" : null,
      });
    }
  } finally {
    await client.close();
  }
  return summarizeMode(mode, observations);
}


export async function runRotationDiagnostic(
  input,
  {
    clientFactory = (settings) => new ProxyClient(settings),
    completedAt = () => new Date(),
  } = {},
) {
  const settings = normalizeSettings(input);
  const modes = {};
  for (const mode of MODES) {
    modes[mode] = await runMode({
      mode,
      settings,
      clientFactory,
    });
  }
  const sensitivity = connectionSensitivity(
    modes.pooled,
    modes.fresh_tunnel,
  );
  return {
    schema_version: "1.0",
    completed_at: completedAt().toISOString(),
    target_label: settings.targetLabel,
    samples_per_mode: settings.samplesPerMode,
    automatic_mode_change: false,
    modes,
    comparison: compareModes(modes.pooled, modes.fresh_tunnel),
    decision: {
      connection_sensitivity: sensitivity,
      independent_request_mode:
        sensitivity === "connection_sensitive_rotation"
          ? "fresh_tunnel"
          : "pooled",
      multi_step_session: "provider_sticky_endpoint_required",
    },
  };
}


export { ProxyConfigError };
