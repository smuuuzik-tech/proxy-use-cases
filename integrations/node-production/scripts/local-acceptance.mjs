#!/usr/bin/env node

import path from "node:path";

import {
  AcceptanceConfigError,
  buildAcceptanceSummary,
  evaluateBodyAssertion,
  loadPrivateAcceptanceConfig,
  validateAcceptanceApproval,
} from "../src/acceptance.js";
import {
  auditBrowserJob,
  BrowserPolicyError,
  BrowserRouteClient,
  replayBrowserJob,
} from "../src/browser.js";
import { ProxyClient, ProxyConfigError } from "../src/client.js";
import { JobStoreError, writePrivateArtifact } from "../src/job-store.js";


if (process.argv.includes("--help")) {
  process.stdout.write(
    "Local real-proxy acceptance\n\n" +
      "1. Copy acceptance.example.json to acceptance.private.json.\n" +
      "2. Set file permissions to 0600 and fill it locally.\n" +
      "3. Run: npm run acceptance:local\n\n" +
      "Set B2B_ACCEPTANCE_CONFIG to use another private config path.\n",
  );
  process.exit(0);
}

function stableCode(error) {
  if (
    error instanceof AcceptanceConfigError ||
    error instanceof BrowserPolicyError ||
    error instanceof ProxyConfigError ||
    error instanceof JobStoreError
  ) {
    return error.code;
  }
  return "ACCEPTANCE_UNEXPECTED";
}

let proxy = null;
try {
  const configPath =
    process.env.B2B_ACCEPTANCE_CONFIG || "acceptance.private.json";
  const config = await loadPrivateAcceptanceConfig(configPath);
  validateAcceptanceApproval(config);

  proxy = new ProxyClient({
    proxyUrl: config.proxy.url,
    proxyUsername: config.proxy.username,
    proxyPassword: config.proxy.password,
    maxAttempts: 2,
    deadlineMs: 60_000,
    estimatedCostPerAttempt: config.cost.estimatedPerAttempt,
    costCurrency: config.cost.currency,
  });
  const httpResult = await proxy.get(config.http.targetUrl, {
    requestId: config.http.requestId,
  });
  const bodyAssertion = evaluateBodyAssertion(
    httpResult,
    config.http.bodyAssertion,
    config.http.fingerprintJsonField,
  );

  const browser = new BrowserRouteClient({
    routeApproved: true,
    proxyUrl: config.proxy.url,
    proxyUsername: config.proxy.username,
    proxyPassword: config.proxy.password,
    targetUrl: config.browser.targetUrl,
    targetLabel: config.browser.targetLabel,
    allowedHosts: config.browser.allowedHosts,
    resourceAllowedHosts: config.browser.resourceAllowedHosts,
    allowPrivateTargets: config.browser.allowPrivateTargets,
    artifactDir: config.artifactDir,
    navigationTimeoutMs: config.browser.navigationTimeoutMs,
    totalDeadlineMs: config.browser.totalDeadlineMs,
    maxRequests: config.browser.maxRequests,
    expectedStatusMin: config.browser.expectedStatusMin,
    expectedStatusMax: config.browser.expectedStatusMax,
    headless: config.browser.headless,
    captureScreenshot: config.browser.captureScreenshot,
    captureTrace: config.browser.captureTrace,
    fullPage: config.browser.fullPage,
    maxScreenshotBytes: config.browser.maxScreenshotBytes,
    estimatedCostPerAttempt: config.cost.estimatedPerAttempt,
    costCurrency: config.cost.currency,
  });
  const browserReport = await browser.run({
    jobId: config.browser.jobId,
  });
  const jobDir = path.join(config.artifactDir, browserReport.job_id);
  const replay = await replayBrowserJob(path.join(jobDir, "report.json"));
  const audit = await auditBrowserJob(jobDir, [
    config.proxy.url,
    config.proxy.username,
    config.proxy.password,
    config.http.targetUrl,
    config.browser.targetUrl,
  ]);
  const summary = buildAcceptanceSummary({
    completedAt: new Date(),
    httpResult,
    bodyAssertion,
    browserReport,
    replay,
    audit,
  });
  await writePrivateArtifact(
    path.join(jobDir, "acceptance-summary.json"),
    `${JSON.stringify(summary, null, 2)}\n`,
  );
  process.stdout.write(
    `${JSON.stringify(
      {
        passed: summary.passed,
        http: summary.http,
        browser: summary.browser,
      },
      null,
      2,
    )}\n`,
  );
  process.exitCode = summary.passed ? 0 : 6;
} catch (error) {
  process.stderr.write(
    `${JSON.stringify({ error: { code: stableCode(error) } })}\n`,
  );
  process.exitCode = 2;
} finally {
  await proxy?.close();
}
