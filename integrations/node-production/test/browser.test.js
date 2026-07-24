import assert from "node:assert/strict";
import {
  chmod,
  mkdtemp,
  readFile,
  stat,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  auditBrowserJob,
  BrowserPolicyError,
  BrowserRouteClient,
  browserSettingsFromEnv,
  replayBrowserJob,
} from "../src/browser.js";


const TARGET =
  "https://app.example.test/private/check?token=request-secret";


async function privateDirectory(prefix) {
  const directory = await mkdtemp(path.join(os.tmpdir(), prefix));
  await chmod(directory, 0o700);
  return directory;
}


function settings(artifactDir, overrides = {}) {
  return {
    routeApproved: true,
    proxyUrl: "http://proxy.example.test:8080",
    proxyUsername: "client-user",
    proxyPassword: "private-password",
    targetUrl: TARGET,
    targetLabel: "client acceptance",
    allowedHosts: ["app.example.test"],
    resourceAllowedHosts: ["app.example.test", "cdn.example.test"],
    artifactDir,
    navigationTimeoutMs: 5_000,
    totalDeadlineMs: 10_000,
    maxRequests: 20,
    captureScreenshot: true,
    captureTrace: true,
    ...overrides,
  };
}


function route(url, { navigation = false, method = "GET" } = {}) {
  const observed = { continued: false, aborted: false };
  return {
    observed,
    request() {
      return {
        isNavigationRequest: () => navigation,
        method: () => method,
        url: () => url,
      };
    },
    async continue() {
      observed.continued = true;
    },
    async abort() {
      observed.aborted = true;
    },
  };
}


function fakeChromium({
  statusCode = 200,
  targetUrl = TARGET,
  timeout = false,
  resourceRequests = 1,
} = {}) {
  const observed = {
    launch: null,
    context: null,
    primaryRoute: null,
    resourceRoutes: [],
    traceStarted: false,
    contextClosed: false,
    browserClosed: false,
  };
  let routeHandler;
  const page = {
    handlers: new Map(),
    on(name, handler) {
      this.handlers.set(name, handler);
    },
    async goto(url) {
      const primary = route(url, { navigation: true });
      observed.primaryRoute = primary.observed;
      await routeHandler(primary);
      for (let index = 0; index < resourceRequests; index += 1) {
        const resource = route(
          `https://tracker.example.test/pixel-${index}`,
        );
        observed.resourceRoutes.push(resource.observed);
        await routeHandler(resource);
      }
      if (timeout) {
        const error = new Error("private target timeout detail");
        error.name = "TimeoutError";
        throw error;
      }
      return { status: () => statusCode };
    },
    url() {
      return targetUrl;
    },
    async screenshot() {
      return Buffer.from("private screenshot bytes");
    },
  };
  const context = {
    tracing: {
      async start() {
        observed.traceStarted = true;
      },
      async stop({ path: destination }) {
        await writeFile(destination, Buffer.from("private trace bytes"), {
          mode: 0o600,
        });
      },
    },
    async routeWebSocket() {},
    async route(_pattern, handler) {
      routeHandler = handler;
    },
    async newPage() {
      return page;
    },
    on() {},
    async close() {
      observed.contextClosed = true;
    },
  };
  const browser = {
    async newContext(options) {
      observed.context = options;
      return context;
    },
    async close() {
      observed.browserClosed = true;
    },
  };
  return {
    observed,
    chromium: {
      async launch(options) {
        observed.launch = options;
        return browser;
      },
    },
  };
}


test("browser route requires explicit approval before execution", () => {
  assert.throws(
    () =>
      browserSettingsFromEnv({
        B2B_BROWSER_ROUTE_APPROVED: "false",
      }),
    (error) =>
      error instanceof BrowserPolicyError &&
      error.code === "BROWSER_ROUTE_NOT_APPROVED",
  );
});


test("browser client starts from validated environment settings", async () => {
  const artifactDir = await privateDirectory("browser-env-");
  const fake = fakeChromium();
  const client = BrowserRouteClient.fromEnv(
    {
      B2B_BROWSER_ROUTE_APPROVED: "true",
      B2B_PROXY_URL: "http://proxy.example.test:8080",
      B2B_PROXY_USERNAME: "client-user",
      B2B_PROXY_PASSWORD: "private-password",
      B2B_BROWSER_TARGET_URL: TARGET,
      B2B_BROWSER_TARGET_LABEL: "environment check",
      B2B_BROWSER_ALLOWED_HOSTS: "app.example.test",
      B2B_BROWSER_RESOURCE_ALLOWED_HOSTS:
        "app.example.test,tracker.example.test",
      B2B_BROWSER_ARTIFACT_DIR: artifactDir,
    },
    { loadChromium: async () => fake.chromium },
  );

  const report = await client.run({ jobId: "environment-001" });

  assert.equal(report.state, "completed");
  assert.equal(report.execution.route.selected, "browser");
});


test("browser policy rejects inline credentials and non-exact allowlists", async () => {
  const artifactDir = await privateDirectory("browser-policy-");
  assert.throws(
    () =>
      new BrowserRouteClient(
        settings(artifactDir, {
          proxyUrl: "http://user:secret@proxy.example.test:8080",
        }),
      ),
    (error) => error.code === "INVALID_PROXY_URL",
  );
  assert.throws(
    () =>
      new BrowserRouteClient(
        settings(artifactDir, {
          allowedHosts: ["*.example.test"],
        }),
      ),
    (error) => error.code === "WILDCARD_HOST_BLOCKED",
  );
});


test("successful browser job is private, replayable, and sanitized", async () => {
  const artifactDir = await privateDirectory("browser-success-");
  const fake = fakeChromium();
  let clock = Date.parse("2026-07-24T10:00:00.000Z");
  const client = new BrowserRouteClient(settings(artifactDir), {
    loadChromium: async () => fake.chromium,
    now: () => (clock += 25),
  });

  const report = await client.run({ jobId: "acceptance-001" });
  const jobDir = path.join(artifactDir, "acceptance-001");
  const serialized = JSON.stringify(report);

  assert.equal(report.state, "completed");
  assert.equal(report.execution.schema_version, "1.1");
  assert.equal(report.execution.route.selected, "browser");
  assert.equal(report.execution.route.reason, "manual_browser_approval");
  assert.deepEqual(report.execution.route.manual_candidates, [
    "managed_unblocker",
    "ai_extraction",
  ]);
  assert.equal(report.observation.blocked_request_count, 1);
  assert.equal(fake.observed.primaryRoute.continued, true);
  assert.equal(fake.observed.resourceRoutes[0].aborted, true);
  assert.equal(fake.observed.launch.proxy.username, "client-user");
  assert.equal(fake.observed.context.acceptDownloads, false);
  assert.equal(fake.observed.context.serviceWorkers, "block");
  assert.equal(fake.observed.traceStarted, true);
  assert.equal(fake.observed.contextClosed, true);
  assert.equal(fake.observed.browserClosed, true);
  assert.doesNotMatch(
    serialized,
    /proxy\.example|client-user|private-password|private\/check|request-secret/,
  );

  const replay = await replayBrowserJob(path.join(jobDir, "report.json"));
  assert.equal(replay.verified, true);
  assert.equal(replay.job_id, "acceptance-001");
  assert.deepEqual(
    await auditBrowserJob(jobDir, [
      "http://proxy.example.test:8080",
      "client-user",
      "private-password",
      TARGET,
    ]),
    { clean: true, files_checked: 4 },
  );
  for (const name of [
    "manifest.json",
    "events.jsonl",
    "report.json",
    "receipt.json",
    "screenshot.png",
    "trace.zip",
  ]) {
    assert.equal((await stat(path.join(jobDir, name))).mode & 0o077, 0);
  }
});


test("request budget produces a stable response-limit outcome", async () => {
  const artifactDir = await privateDirectory("browser-budget-");
  const fake = fakeChromium({ resourceRequests: 3 });
  const client = new BrowserRouteClient(
    settings(artifactDir, {
      captureScreenshot: false,
      captureTrace: false,
      maxRequests: 2,
    }),
    { loadChromium: async () => fake.chromium },
  );

  const report = await client.run({ jobId: "budget-001" });

  assert.equal(report.state, "failed");
  assert.equal(report.error.code, "BROWSER_REQUEST_LIMIT");
  assert.equal(report.execution.quality.outcome, "response_limit");
  assert.equal(report.execution.route.next_action, "review_response_limit");
});


test("timeout and HTTP status use normalized outcomes", async () => {
  const timeoutDir = await privateDirectory("browser-timeout-");
  const timeoutFake = fakeChromium({ timeout: true });
  const timeoutClient = new BrowserRouteClient(
    settings(timeoutDir, {
      captureScreenshot: false,
      captureTrace: false,
    }),
    { loadChromium: async () => timeoutFake.chromium },
  );
  const timeout = await timeoutClient.run({ jobId: "timeout-001" });
  assert.equal(timeout.execution.quality.outcome, "timeout");
  assert.equal(timeout.error.code, "BROWSER_TIMEOUT");
  assert.doesNotMatch(JSON.stringify(timeout), /private target timeout/);

  const statusDir = await privateDirectory("browser-status-");
  const statusFake = fakeChromium({ statusCode: 403 });
  const statusClient = new BrowserRouteClient(
    settings(statusDir, {
      captureScreenshot: false,
      captureTrace: false,
    }),
    { loadChromium: async () => statusFake.chromium },
  );
  const status = await statusClient.run({ jobId: "status-001" });
  assert.equal(status.execution.quality.outcome, "http_error");
  assert.equal(
    status.execution.route.next_action,
    "review_policy_or_credentials",
  );
});


test("replay detects a modified report", async () => {
  const artifactDir = await privateDirectory("browser-tamper-");
  const fake = fakeChromium();
  const client = new BrowserRouteClient(
    settings(artifactDir, {
      captureScreenshot: false,
      captureTrace: false,
    }),
    { loadChromium: async () => fake.chromium },
  );
  await client.run({ jobId: "tamper-001" });
  const reportPath = path.join(artifactDir, "tamper-001", "report.json");
  const report = JSON.parse(await readFile(reportPath, "utf8"));
  report.target_label = "modified";
  await writeFile(reportPath, `${JSON.stringify(report)}\n`, { mode: 0o600 });

  await assert.rejects(
    () => replayBrowserJob(reportPath),
    (error) => error.code === "REPORT_INTEGRITY_FAILED",
  );
});
