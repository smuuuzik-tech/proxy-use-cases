import { randomUUID } from 'node:crypto';
import { chmod, mkdir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { redactText, sanitizeUrl } from './redaction.mjs';

export function slugifyRegionLabel(label) {
  const slug = label
    .normalize('NFKD')
    .replace(/[^\p{Letter}\p{Number}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
    .toLowerCase()
    .slice(0, 50);
  return slug || 'region';
}

export function createArtifactPaths(
  artifactDir,
  regionLabel,
  now = new Date(),
  runId = randomUUID(),
) {
  const timestamp = now.toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z');
  const suffix = runId.replace(/[^a-zA-Z0-9]/g, '').slice(0, 12);
  const base = `regional-qa-${slugifyRegionLabel(regionLabel)}-${timestamp}-${suffix}`;
  return Object.freeze({
    screenshot: path.join(artifactDir, `${base}.png`),
    report: path.join(artifactDir, `${base}.json`),
  });
}

export function createEvidenceReport({
  config,
  completedAt,
  elapsedTimeMs,
  observed,
  outcome,
  exitCode,
  screenshotPath,
  error,
}) {
  const secrets = [
    config.proxy.server,
    config.proxy.username,
    config.proxy.password,
  ].filter(Boolean);
  return {
    schemaVersion: 1,
    timestamp: completedAt.toISOString(),
    requestedRegionLabel: config.regionLabel,
    regionVerification: 'operator_asserted_not_independently_verified',
    outcome,
    exitCode,
    check: {
      requestedUrl: sanitizeUrl(config.checkUrl),
      observedUrl: sanitizeUrl(observed.url),
      status: Number.isInteger(observed.status) ? observed.status : null,
      title:
        config.includeTitle && observed.title
          ? redactText(observed.title, secrets)
          : null,
      elapsedTimeMs: Math.max(0, Math.round(elapsedTimeMs)),
    },
    expectedStatus: {
      min: config.expectedStatus.min,
      max: config.expectedStatus.max,
    },
    artifacts: {
      screenshot: screenshotPath ? path.basename(screenshotPath) : null,
    },
    error: error ? redactText(error, secrets) : null,
  };
}

export async function writeEvidenceReport(report, destination) {
  await ensurePrivateDirectory(path.dirname(destination));
  const temporary = path.join(
    path.dirname(destination),
    `.${path.basename(destination)}.${randomUUID()}.tmp`,
  );
  await writeFile(temporary, `${JSON.stringify(report, null, 2)}\n`, {
    encoding: 'utf8',
    flag: 'wx',
    mode: 0o600,
  });
  await rename(temporary, destination);
}

export async function writePrivateArtifact(data, destination) {
  await ensurePrivateDirectory(path.dirname(destination));
  const temporary = path.join(
    path.dirname(destination),
    `.${path.basename(destination)}.${randomUUID()}.tmp`,
  );
  await writeFile(temporary, data, { flag: 'wx', mode: 0o600 });
  await rename(temporary, destination);
}

async function ensurePrivateDirectory(directory) {
  const created = await mkdir(directory, { recursive: true, mode: 0o700 });
  if (created !== undefined) {
    await chmod(directory, 0o700);
  }
}
