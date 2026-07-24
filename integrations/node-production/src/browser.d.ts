import type { ProxyExecutionContract } from "./client.js";


export interface BrowserRouteSettings {
  routeApproved: true;
  proxyUrl: string;
  proxyUsername?: string;
  proxyPassword?: string;
  targetUrl: string;
  targetLabel: string;
  allowedHosts: string[] | string;
  resourceAllowedHosts?: string[] | string;
  allowPrivateTargets?: boolean;
  artifactDir?: string;
  navigationTimeoutMs?: number;
  totalDeadlineMs?: number;
  maxRequests?: number;
  expectedStatusMin?: number;
  expectedStatusMax?: number;
  headless?: boolean;
  captureScreenshot?: boolean;
  captureTrace?: boolean;
  fullPage?: boolean;
  maxScreenshotBytes?: number;
  estimatedCostPerAttempt?: number | null;
  costCurrency?: string | null;
}

export interface BrowserRouteReport {
  report_schema_version: "1.0";
  job_id: string;
  state: "completed" | "failed";
  target_label: string;
  created_at: string;
  completed_at: string;
  observation: {
    status_code: number | null;
    elapsed_ms: number;
    request_count: number;
    blocked_request_count: number;
    final_target_allowed: boolean;
  };
  execution: ProxyExecutionContract;
  artifacts: {
    screenshot: string | null;
    trace: string | null;
  };
  error: {
    code: string;
    kind: "http" | "response_limit" | "timeout" | "transport";
  } | null;
}

export class BrowserPolicyError extends Error {
  code: string;
}

export function browserSettingsFromEnv(
  env?: Record<string, string | undefined>,
  options?: { cwd?: string },
): Readonly<BrowserRouteSettings>;

export class BrowserRouteClient {
  constructor(
    settings: BrowserRouteSettings,
    dependencies?: Record<string, unknown>,
  );
  static fromEnv(
    env?: Record<string, string | undefined>,
    dependencies?: Record<string, unknown>,
  ): BrowserRouteClient;
  run(options?: { jobId?: string }): Promise<BrowserRouteReport>;
}

export function replayBrowserJob(reportPath: string): Promise<{
  verified: true;
  job_id: string;
  state: "completed" | "failed";
  target_label: string;
  execution: ProxyExecutionContract;
  artifacts: BrowserRouteReport["artifacts"];
}>;

export function auditBrowserJob(
  jobDirectory: string,
  secrets?: string[],
): Promise<{ clean: true; files_checked: number }>;
