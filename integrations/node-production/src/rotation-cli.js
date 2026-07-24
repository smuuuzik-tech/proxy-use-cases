#!/usr/bin/env node

import {
  ProxyConfigError,
  RotationDiagnosticError,
  rotationSettingsFromEnv,
  runRotationDiagnostic,
} from "./rotation.js";


if (process.argv.includes("--help")) {
  process.stdout.write(
    "Usage: andrey-proxy-rotation\n\n" +
      "Reads proxy credentials from B2B_PROXY_* and the approved diagnostic target from:\n" +
      "  B2B_ROTATION_TARGET_URL\n" +
      "  B2B_ROTATION_TARGET_LABEL\n" +
      "  B2B_ROTATION_JSON_FIELD (default: ip)\n" +
      "  B2B_ROTATION_SAMPLES_PER_MODE (default: 10)\n\n" +
      "The report contains counts and decisions, never raw observed values.\n",
  );
  process.exit(0);
}

try {
  const report = await runRotationDiagnostic(rotationSettingsFromEnv());
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  process.exitCode =
    report.modes.pooled.failed === 0 &&
    report.modes.fresh_tunnel.failed === 0
      ? 0
      : 5;
} catch (error) {
  const code =
    error instanceof RotationDiagnosticError ||
    error instanceof ProxyConfigError
      ? error.code
      : "ROTATION_DIAGNOSTIC_UNEXPECTED";
  process.stderr.write(`${JSON.stringify({ error: { code } })}\n`);
  process.exitCode = 2;
}
