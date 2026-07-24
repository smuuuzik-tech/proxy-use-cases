import type {
  ProxyConnectionMode,
  ProxySettings,
} from "./client.js";

export { ProxyConfigError } from "./client.js";


export interface RotationDiagnosticSettings extends ProxySettings {
  targetUrl: string;
  targetLabel: string;
  jsonField?: string;
  samplesPerMode?: number;
}

export interface RotationModeSummary {
  connection_mode: ProxyConnectionMode;
  requests: number;
  successful: number;
  failed: number;
  attempts: number;
  unique_observations: number;
  sequence_changes: number;
  reuse_rate: number | null;
  latency_ms: {
    p50: number | null;
    p95: number | null;
    max: number | null;
  };
  error_codes: Record<string, number>;
}

export interface RotationDiagnosticReport {
  schema_version: "1.0";
  completed_at: string;
  target_label: string;
  samples_per_mode: number;
  automatic_mode_change: false;
  modes: {
    pooled: RotationModeSummary;
    fresh_tunnel: RotationModeSummary;
  };
  comparison: {
    fresh_tunnel_unique_observation_gain: number;
    fresh_tunnel_p50_latency_delta_ms: number | null;
    fresh_tunnel_p50_latency_ratio: number | null;
  };
  decision: {
    connection_sensitivity:
      | "insufficient_evidence"
      | "stable_or_provider_sticky"
      | "connection_sensitive_rotation"
      | "high_rotation_in_both_modes"
      | "mixed_rotation";
    independent_request_mode: ProxyConnectionMode;
    multi_step_session: "provider_sticky_endpoint_required";
  };
}

export class RotationDiagnosticError extends Error {
  code: string;
}

export function rotationSettingsFromEnv(
  env?: Record<string, string | undefined>,
): Readonly<RotationDiagnosticSettings>;

export function runRotationDiagnostic(
  settings: RotationDiagnosticSettings,
  dependencies?: Record<string, unknown>,
): Promise<RotationDiagnosticReport>;
