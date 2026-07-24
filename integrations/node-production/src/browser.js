import { randomUUID } from "node:crypto";
import { isIP } from "node:net";
import path from "node:path";

import { buildExecutionContract } from "./execution.js";
import {
  createDurableBrowserJob,
  finalizeDurableBrowserJob,
  markPrivateArtifact,
  writePrivateArtifact,
} from "./job-store.js";

export {
  auditBrowserJob,
  replayBrowserJob,
} from "./job-store.js";


const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const PROXY_PROTOCOLS = new Set(["http:", "https:", "socks5:"]);


export class BrowserPolicyError extends Error {
  constructor(message, code = "INVALID_BROWSER_POLICY") {
    super(message);
    this.name = "BrowserPolicyError";
    this.code = code;
  }
}


class BrowserRunError extends Error {
  constructor(code, kind) {
    super(code);
    this.name = "BrowserRunError";
    this.code = code;
    this.kind = kind;
  }
}


function required(value, name) {
  const normalized = value == null ? "" : String(value).trim();
  if (!normalized) {
    throw new BrowserPolicyError(`${name} is required`, "MISSING_BROWSER_SETTING");
  }
  return normalized;
}


function envBoolean(value, name, fallback) {
  if (value == null || String(value).trim() === "") return fallback;
  if (String(value).trim().toLowerCase() === "true") return true;
  if (String(value).trim().toLowerCase() === "false") return false;
  throw new BrowserPolicyError(`${name} must be true or false`);
}


function envInteger(value, name, fallback, minimum, maximum) {
  if (value == null || String(value).trim() === "") return fallback;
  const number = Number(value);
  if (
    !Number.isSafeInteger(number) ||
    number < minimum ||
    number > maximum
  ) {
    throw new BrowserPolicyError(
      `${name} must be an integer between ${minimum} and ${maximum}`,
    );
  }
  return number;
}


function envOptionalNumber(value, name, minimum, maximum) {
  if (value == null || String(value).trim() === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number < minimum || number > maximum) {
    throw new BrowserPolicyError(
      `${name} must be finite and between ${minimum} and ${maximum}`,
    );
  }
  return number;
}


function unsafeHost(hostname) {
  const host = hostname
    .toLowerCase()
    .replace(/^\[|\]$/g, "")
    .replace(/\.$/, "");
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local")) {
    return true;
  }
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
      (a === 198 && (b === 18 || b === 19)) ||
      a >= 224
    );
  }
  if (isIP(host) === 6) {
    return (
      host === "::" ||
      host === "::1" ||
      host.startsWith("fc") ||
      host.startsWith("fd") ||
      /^fe[89ab]/.test(host) ||
      host.startsWith("ff") ||
      host.startsWith("::ffff:")
    );
  }
  return false;
}


function parseAllowedHosts(value, allowPrivateTargets) {
  const source = Array.isArray(value) ? value : String(value || "").split(",");
  const hosts = [];
  for (const candidate of source) {
    const host = String(candidate).trim().toLowerCase();
    if (!host) continue;
    if (host.includes("*")) {
      throw new BrowserPolicyError(
        "Browser allowlists accept exact hostnames only",
        "WILDCARD_HOST_BLOCKED",
      );
    }
    let parsed;
    try {
      parsed = new URL(`https://${host}`);
    } catch {
      throw new BrowserPolicyError("Browser allowlist contains an invalid host");
    }
    const normalized = parsed.hostname.toLowerCase();
    const bracketedIpv6 = host.startsWith("[") && host.endsWith("]");
    if (
      (!bracketedIpv6 && normalized !== host) ||
      parsed.port ||
      parsed.username ||
      parsed.password ||
      parsed.pathname !== "/"
    ) {
      throw new BrowserPolicyError(
        "Browser allowlists contain hostnames without scheme, port, or path",
      );
    }
    if (!allowPrivateTargets && unsafeHost(normalized)) {
      throw new BrowserPolicyError(
        "Private browser targets require explicit opt-in",
        "PRIVATE_TARGET_BLOCKED",
      );
    }
    hosts.push(normalized);
  }
  if (!hosts.length) {
    throw new BrowserPolicyError("Browser allowlist must not be empty");
  }
  return [...new Set(hosts)];
}


function parseTargetUrl(value, allowedHosts) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new BrowserPolicyError("Browser target must be an absolute URL");
  }
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.port ||
    !allowedHosts.includes(url.hostname.toLowerCase())
  ) {
    throw new BrowserPolicyError(
      "Browser target must be an allowlisted HTTPS URL on the default port",
      "TARGET_POLICY_BLOCKED",
    );
  }
  url.hash = "";
  return url.toString();
}


function parseProxy(proxyUrl, username, password) {
  let url;
  try {
    url = new URL(proxyUrl);
  } catch {
    throw new BrowserPolicyError("Proxy URL must be absolute", "INVALID_PROXY_URL");
  }
  if (
    !PROXY_PROTOCOLS.has(url.protocol) ||
    url.username ||
    url.password ||
    !["", "/"].includes(url.pathname) ||
    url.search ||
    url.hash
  ) {
    throw new BrowserPolicyError(
      "Proxy URL must contain only a supported scheme, host, and port",
      "INVALID_PROXY_URL",
    );
  }
  const proxyUsername = username == null ? "" : String(username);
  const proxyPassword = password == null ? "" : String(password);
  if (
    (proxyUsername && !proxyUsername.trim()) ||
    (proxyPassword && !proxyPassword.trim()) ||
    Boolean(proxyUsername) !== Boolean(proxyPassword)
  ) {
    throw new BrowserPolicyError(
      "Proxy username and password must be provided together",
      "INCOMPLETE_PROXY_CREDENTIALS",
    );
  }
  if (url.protocol === "socks5:" && proxyUsername) {
    throw new BrowserPolicyError(
      "Authenticated SOCKS5 is not supported by this browser route",
      "UNSUPPORTED_PROXY_AUTH",
    );
  }
  return Object.freeze({
    server: url.toString().replace(/\/$/, ""),
    ...(proxyUsername
      ? { username: proxyUsername, password: proxyPassword }
      : {}),
  });
}


function validTargetLabel(value) {
  const label = required(value, "targetLabel");
  if (
    label.length > 80 ||
    !/^[\p{Letter}\p{Number} _-]+$/u.test(label)
  ) {
    throw new BrowserPolicyError(
      "targetLabel must contain only letters, numbers, spaces, underscore, or dash",
      "INVALID_TARGET_LABEL",
    );
  }
  return label;
}


function validateBrowserSettings(input, cwd = process.cwd()) {
  if (!input || typeof input !== "object") {
    throw new BrowserPolicyError("Browser settings must be an object");
  }
  if (input.routeApproved !== true) {
    throw new BrowserPolicyError(
      "Browser route requires explicit approval",
      "BROWSER_ROUTE_NOT_APPROVED",
    );
  }
  const allowPrivateTargets = input.allowPrivateTargets === true;
  const allowedHosts = parseAllowedHosts(
    input.allowedHosts,
    allowPrivateTargets,
  );
  const resourceAllowedHosts = parseAllowedHosts(
    input.resourceAllowedHosts || allowedHosts,
    allowPrivateTargets,
  );
  const navigationTimeoutMs = Number(input.navigationTimeoutMs ?? 30_000);
  const totalDeadlineMs = Number(input.totalDeadlineMs ?? 60_000);
  const maxRequests = Number(input.maxRequests ?? 200);
  const maxScreenshotBytes = Number(
    input.maxScreenshotBytes ?? 10 * 1024 * 1024,
  );
  for (const [name, value, minimum, maximum] of [
    ["navigationTimeoutMs", navigationTimeoutMs, 1_000, 120_000],
    ["totalDeadlineMs", totalDeadlineMs, 1_000, 300_000],
    ["maxRequests", maxRequests, 1, 1_000],
    ["maxScreenshotBytes", maxScreenshotBytes, 1_024, 52_428_800],
  ]) {
    if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
      throw new BrowserPolicyError(
        `${name} must be an integer between ${minimum} and ${maximum}`,
      );
    }
  }
  const expectedStatusMin = Number(input.expectedStatusMin ?? 200);
  const expectedStatusMax = Number(input.expectedStatusMax ?? 399);
  if (
    !Number.isSafeInteger(expectedStatusMin) ||
    !Number.isSafeInteger(expectedStatusMax) ||
    expectedStatusMin < 100 ||
    expectedStatusMax > 599 ||
    expectedStatusMin > expectedStatusMax
  ) {
    throw new BrowserPolicyError("Expected browser status range is invalid");
  }
  const estimatedCostPerAttempt =
    input.estimatedCostPerAttempt == null
      ? null
      : Number(input.estimatedCostPerAttempt);
  const costCurrency =
    input.costCurrency == null ? null : String(input.costCurrency);
  if (
    (estimatedCostPerAttempt == null) !== (costCurrency == null) ||
    (
      estimatedCostPerAttempt != null &&
      (
        !Number.isFinite(estimatedCostPerAttempt) ||
        estimatedCostPerAttempt < 0 ||
        estimatedCostPerAttempt > 1_000_000 ||
        !/^[A-Z]{3}$/.test(costCurrency)
      )
    )
  ) {
    throw new BrowserPolicyError(
      "Browser attempt cost and uppercase currency must be provided together",
      "INVALID_COST_CONFIGURATION",
    );
  }
  const artifactDir = path.resolve(
    cwd,
    String(input.artifactDir || ".browser-jobs"),
  );
  if (artifactDir === path.parse(artifactDir).root) {
    throw new BrowserPolicyError(
      "Browser artifact directory must not be a filesystem root",
      "UNSAFE_ARTIFACT_DIRECTORY",
    );
  }
  return Object.freeze({
    routeApproved: true,
    proxy: parseProxy(
      required(input.proxyUrl, "proxyUrl"),
      input.proxyUsername,
      input.proxyPassword,
    ),
    targetUrl: parseTargetUrl(
      required(input.targetUrl, "targetUrl"),
      allowedHosts,
    ),
    targetLabel: validTargetLabel(input.targetLabel),
    allowedHosts: Object.freeze(allowedHosts),
    resourceAllowedHosts: Object.freeze(resourceAllowedHosts),
    allowPrivateTargets,
    artifactDir,
    navigationTimeoutMs,
    totalDeadlineMs,
    maxRequests,
    expectedStatusMin,
    expectedStatusMax,
    headless: input.headless !== false,
    captureScreenshot: input.captureScreenshot === true,
    captureTrace: input.captureTrace === true,
    fullPage: input.fullPage === true,
    maxScreenshotBytes,
    estimatedCostPerAttempt,
    costCurrency,
  });
}


export function browserSettingsFromEnv(
  env = process.env,
  { cwd = process.cwd() } = {},
) {
  return validateBrowserSettings(
    {
      routeApproved: envBoolean(
        env.B2B_BROWSER_ROUTE_APPROVED,
        "B2B_BROWSER_ROUTE_APPROVED",
        false,
      ),
      proxyUrl: env.B2B_PROXY_URL,
      proxyUsername: env.B2B_PROXY_USERNAME,
      proxyPassword: env.B2B_PROXY_PASSWORD,
      targetUrl: env.B2B_BROWSER_TARGET_URL,
      targetLabel: env.B2B_BROWSER_TARGET_LABEL,
      allowedHosts: env.B2B_BROWSER_ALLOWED_HOSTS,
      resourceAllowedHosts:
        env.B2B_BROWSER_RESOURCE_ALLOWED_HOSTS ||
        env.B2B_BROWSER_ALLOWED_HOSTS,
      allowPrivateTargets: envBoolean(
        env.B2B_BROWSER_ALLOW_PRIVATE_TARGETS,
        "B2B_BROWSER_ALLOW_PRIVATE_TARGETS",
        false,
      ),
      artifactDir: env.B2B_BROWSER_ARTIFACT_DIR || ".browser-jobs",
      navigationTimeoutMs: envInteger(
        env.B2B_BROWSER_NAVIGATION_TIMEOUT_MS,
        "B2B_BROWSER_NAVIGATION_TIMEOUT_MS",
        30_000,
        1_000,
        120_000,
      ),
      totalDeadlineMs: envInteger(
        env.B2B_BROWSER_TOTAL_DEADLINE_MS,
        "B2B_BROWSER_TOTAL_DEADLINE_MS",
        60_000,
        1_000,
        300_000,
      ),
      maxRequests: envInteger(
        env.B2B_BROWSER_MAX_REQUESTS,
        "B2B_BROWSER_MAX_REQUESTS",
        200,
        1,
        1_000,
      ),
      expectedStatusMin: envInteger(
        env.B2B_BROWSER_EXPECTED_STATUS_MIN,
        "B2B_BROWSER_EXPECTED_STATUS_MIN",
        200,
        100,
        599,
      ),
      expectedStatusMax: envInteger(
        env.B2B_BROWSER_EXPECTED_STATUS_MAX,
        "B2B_BROWSER_EXPECTED_STATUS_MAX",
        399,
        100,
        599,
      ),
      headless: envBoolean(env.B2B_BROWSER_HEADLESS, "B2B_BROWSER_HEADLESS", true),
      captureScreenshot: envBoolean(
        env.B2B_BROWSER_CAPTURE_SCREENSHOT,
        "B2B_BROWSER_CAPTURE_SCREENSHOT",
        false,
      ),
      captureTrace: envBoolean(
        env.B2B_BROWSER_CAPTURE_TRACE,
        "B2B_BROWSER_CAPTURE_TRACE",
        false,
      ),
      fullPage: envBoolean(
        env.B2B_BROWSER_FULL_PAGE,
        "B2B_BROWSER_FULL_PAGE",
        false,
      ),
      maxScreenshotBytes: envInteger(
        env.B2B_BROWSER_MAX_SCREENSHOT_BYTES,
        "B2B_BROWSER_MAX_SCREENSHOT_BYTES",
        10 * 1024 * 1024,
        1_024,
        52_428_800,
      ),
      estimatedCostPerAttempt: envOptionalNumber(
        env.B2B_ESTIMATED_COST_PER_ATTEMPT,
        "B2B_ESTIMATED_COST_PER_ATTEMPT",
        0,
        1_000_000,
      ),
      costCurrency: env.B2B_COST_CURRENCY
        ? env.B2B_COST_CURRENCY.trim().toUpperCase()
        : null,
    },
    cwd,
  );
}


function isAllowedBrowserUrl(raw, allowedHosts) {
  try {
    const url = new URL(raw);
    return (
      url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      !url.port &&
      allowedHosts.includes(url.hostname.toLowerCase())
    );
  } catch {
    return false;
  }
}


function classifiedError(error, state) {
  if (state.requestBudgetExceeded) {
    return { code: "BROWSER_REQUEST_LIMIT", kind: "response_limit" };
  }
  if (state.navigationPolicyBlocked) {
    return { code: "TARGET_POLICY_BLOCKED", kind: "transport" };
  }
  if (error instanceof BrowserRunError) {
    return { code: error.code, kind: error.kind };
  }
  if (error?.name === "TimeoutError") {
    return { code: "BROWSER_TIMEOUT", kind: "timeout" };
  }
  if (state.stage === "load") {
    return { code: "PLAYWRIGHT_UNAVAILABLE", kind: "transport" };
  }
  return {
    code: state.stage === "launch" ? "BROWSER_LAUNCH_FAILED" : "BROWSER_FAILED",
    kind: "transport",
  };
}


export class BrowserRouteClient {
  constructor(
    settings,
    {
      loadChromium = async () => {
        const { chromium } = await import("playwright");
        return chromium;
      },
      now = Date.now,
      jobIdFactory = randomUUID,
      normalized = false,
    } = {},
  ) {
    this.settings = normalized ? settings : validateBrowserSettings(settings);
    this.loadChromium = loadChromium;
    this.now = now;
    this.jobIdFactory = jobIdFactory;
  }

  static fromEnv(env = process.env, dependencies = {}) {
    return new BrowserRouteClient(
      browserSettingsFromEnv(env),
      { ...dependencies, normalized: true },
    );
  }

  async run({ jobId = this.jobIdFactory() } = {}) {
    const createdAt = new Date(this.now());
    const job = await createDurableBrowserJob({
      artifactDir: this.settings.artifactDir,
      jobId,
      targetLabel: this.settings.targetLabel,
      createdAt,
    });
    const started = this.now();
    const state = {
      stage: "load",
      requestCount: 0,
      blockedRequestCount: 0,
      requestBudgetExceeded: false,
      navigationPolicyBlocked: false,
    };
    let browser = null;
    let context = null;
    let page = null;
    let traceStarted = false;
    let statusCode = null;
    let screenshot = null;
    let trace = null;
    let error = null;

    try {
      const chromium = await this.loadChromium();
      state.stage = "launch";
      browser = await chromium.launch({
        headless: this.settings.headless,
        proxy: this.settings.proxy,
        args: ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp"],
      });
      state.stage = "context";
      context = await browser.newContext({
        acceptDownloads: false,
        serviceWorkers: "block",
        viewport: { width: 1440, height: 900 },
      });
      if (this.settings.captureTrace) {
        await context.tracing.start({
          screenshots: true,
          snapshots: true,
          sources: false,
        });
        traceStarted = true;
      }
      if (typeof context.routeWebSocket === "function") {
        await context.routeWebSocket(/.*/, (socket) => socket.close());
      }
      await context.route("**/*", async (route) => {
        const request = route.request();
        state.requestCount += 1;
        const navigation = request.isNavigationRequest();
        const allowedHosts = navigation
          ? this.settings.allowedHosts
          : this.settings.resourceAllowedHosts;
        const allowed =
          state.requestCount <= this.settings.maxRequests &&
          SAFE_METHODS.has(request.method()) &&
          isAllowedBrowserUrl(request.url(), allowedHosts);
        if (!allowed) {
          state.blockedRequestCount += 1;
          if (state.requestCount > this.settings.maxRequests) {
            state.requestBudgetExceeded = true;
          }
          if (
            navigation &&
            !isAllowedBrowserUrl(request.url(), this.settings.allowedHosts)
          ) {
            state.navigationPolicyBlocked = true;
          }
          await route.abort("blockedbyclient");
          return;
        }
        await route.continue();
      });

      page = await context.newPage();
      context.on("page", (candidate) => {
        if (candidate !== page) void candidate.close().catch(() => {});
      });
      page.on("download", (download) => void download.cancel().catch(() => {}));
      page.on("dialog", (dialog) => void dialog.dismiss().catch(() => {}));
      const remaining = Math.max(1, this.settings.totalDeadlineMs - (this.now() - started));
      state.stage = "navigation";
      const response = await page.goto(this.settings.targetUrl, {
        waitUntil: "domcontentloaded",
        timeout: Math.min(this.settings.navigationTimeoutMs, remaining),
      });
      statusCode = response?.status() ?? null;
      if (state.requestBudgetExceeded) {
        throw new BrowserRunError("BROWSER_REQUEST_LIMIT", "response_limit");
      }
      if (!isAllowedBrowserUrl(page.url(), this.settings.allowedHosts)) {
        throw new BrowserRunError("FINAL_TARGET_BLOCKED", "transport");
      }
      if (this.settings.captureScreenshot) {
        state.stage = "screenshot";
        const data = await page.screenshot({ fullPage: this.settings.fullPage });
        if (data.byteLength > this.settings.maxScreenshotBytes) {
          throw new BrowserRunError("SCREENSHOT_LIMIT", "response_limit");
        }
        await writePrivateArtifact(job.paths.screenshot, data);
        screenshot = path.basename(job.paths.screenshot);
      }
    } catch (caught) {
      error = classifiedError(caught, state);
    } finally {
      if (traceStarted && context) {
        try {
          await context.tracing.stop({ path: job.paths.trace });
          await markPrivateArtifact(job.paths.trace);
          trace = path.basename(job.paths.trace);
        } catch {
          if (!error) error = { code: "TRACE_WRITE_FAILED", kind: "transport" };
        }
      }
      if (context) {
        try {
          await context.close();
        } catch {
          if (!error) error = { code: "BROWSER_CLOSE_FAILED", kind: "transport" };
        }
      }
      if (browser) {
        try {
          await browser.close();
        } catch {
          if (!error) error = { code: "BROWSER_CLOSE_FAILED", kind: "transport" };
        }
      }
    }

    const elapsedMs = Math.max(0, Math.round(this.now() - started));
    const statusAccepted =
      statusCode != null &&
      statusCode >= this.settings.expectedStatusMin &&
      statusCode <= this.settings.expectedStatusMax;
    const ok = error == null && statusAccepted;
    if (!error && !statusAccepted) {
      error = { code: "HTTP_STATUS_OUTSIDE_POLICY", kind: "http" };
    }
    const execution = buildExecutionContract({
      ok,
      attempts: 1,
      elapsedMs,
      statusCode,
      errorKind: error?.kind === "http" ? null : error?.kind || null,
      estimatedCostPerAttempt: this.settings.estimatedCostPerAttempt,
      costCurrency: this.settings.costCurrency,
      selectedRoute: "browser",
      routeReason: "manual_browser_approval",
    });
    const completedAt = new Date(this.now());
    const report = {
      report_schema_version: "1.0",
      job_id: job.jobId,
      state: ok ? "completed" : "failed",
      target_label: this.settings.targetLabel,
      created_at: job.createdAt,
      completed_at: completedAt.toISOString(),
      observation: {
        status_code: statusCode,
        elapsed_ms: elapsedMs,
        request_count: state.requestCount,
        blocked_request_count: state.blockedRequestCount,
        final_target_allowed: !state.navigationPolicyBlocked,
      },
      execution,
      artifacts: {
        screenshot,
        trace,
      },
      error,
    };
    await finalizeDurableBrowserJob(job, report, completedAt);
    return report;
  }
}
