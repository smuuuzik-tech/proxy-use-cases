#!/usr/bin/env node

import { ProxyClient, ProxyConfigError } from "./client.js";

const args = process.argv.slice(2);
const prettyIndex = args.indexOf("--pretty");
const pretty = prettyIndex >= 0;
if (pretty) args.splice(prettyIndex, 1);

if (args.length > 1 || args.includes("--help")) {
  process.stdout.write(
    "Usage: andrey-proxy-node [target-url] [--pretty]\n\n" +
      "Prefer B2B_TARGET_URL so the target URL is absent from process arguments.\n",
  );
  process.exit(args.includes("--help") ? 0 : 2);
}

const target = args[0] || process.env.B2B_TARGET_URL;
if (!target) {
  process.stderr.write('{"error":{"code":"TARGET_REQUIRED"}}\n');
  process.exit(2);
}

let client;
try {
  client = ProxyClient.fromEnv();
  const result = await client.get(target);
  process.stdout.write(`${JSON.stringify(result, null, pretty ? 2 : 0)}\n`);
  process.exitCode = result.ok ? 0 : result.statusCode ? 3 : 4;
} catch (error) {
  const code =
    error instanceof ProxyConfigError ? error.code : "UNEXPECTED_ERROR";
  process.stderr.write(`${JSON.stringify({ error: { code } })}\n`);
  process.exitCode = 2;
} finally {
  await client?.close();
}
