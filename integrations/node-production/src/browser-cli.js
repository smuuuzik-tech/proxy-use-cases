#!/usr/bin/env node

import {
  auditBrowserJob,
  BrowserPolicyError,
  BrowserRouteClient,
  replayBrowserJob,
} from "./browser.js";
import { JobStoreError } from "./job-store.js";


const args = process.argv.slice(2);

function usage() {
  process.stdout.write(
    "Usage:\n" +
      "  andrey-proxy-browser\n" +
      "  andrey-proxy-browser --replay <private-report.json>\n" +
      "  andrey-proxy-browser --audit <private-job-directory>\n\n" +
      "Run mode reads proxy, target, policy, and artifact settings from B2B_* environment variables.\n" +
      "Never pass proxy credentials or a target URL as command-line arguments.\n",
  );
}

function stableError(error) {
  if (error instanceof BrowserPolicyError || error instanceof JobStoreError) {
    return error.code;
  }
  return "BROWSER_UNEXPECTED";
}

if (args.includes("--help")) {
  usage();
  process.exit(0);
}

try {
  if (args[0] === "--replay" && args.length === 2) {
    const replay = await replayBrowserJob(args[1]);
    process.stdout.write(`${JSON.stringify(replay, null, 2)}\n`);
  } else if (args[0] === "--audit" && args.length === 2) {
    const audit = await auditBrowserJob(
      args[1],
      [
        process.env.B2B_PROXY_URL,
        process.env.B2B_PROXY_USERNAME,
        process.env.B2B_PROXY_PASSWORD,
        process.env.B2B_BROWSER_TARGET_URL,
      ].filter(Boolean),
    );
    process.stdout.write(`${JSON.stringify(audit, null, 2)}\n`);
  } else if (args.length === 0) {
    const client = BrowserRouteClient.fromEnv();
    const report = await client.run({
      jobId: process.env.B2B_BROWSER_JOB_ID || undefined,
    });
    process.stdout.write(
      `${JSON.stringify(
        {
          job_id: report.job_id,
          state: report.state,
          execution: report.execution,
          artifacts: report.artifacts,
          error: report.error,
        },
        null,
        2,
      )}\n`,
    );
    if (report.state === "completed") {
      process.exitCode = 0;
    } else if (report.execution.quality.outcome === "http_error") {
      process.exitCode = 3;
    } else {
      process.exitCode = 4;
    }
  } else {
    usage();
    process.exitCode = 2;
  }
} catch (error) {
  process.stderr.write(
    `${JSON.stringify({ error: { code: stableError(error) } })}\n`,
  );
  process.exitCode =
    error instanceof BrowserPolicyError
      ? 2
      : error instanceof JobStoreError
        ? 5
        : 4;
}
