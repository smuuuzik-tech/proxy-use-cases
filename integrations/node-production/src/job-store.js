import {
  createHash,
  randomUUID,
} from "node:crypto";
import {
  appendFile,
  chmod,
  lstat,
  mkdir,
  readFile,
  rename,
  writeFile,
} from "node:fs/promises";
import path from "node:path";


const JOB_STORE_SCHEMA_VERSION = "1.0";
const MAX_TEXT_ARTIFACT_BYTES = 2 * 1024 * 1024;
const JOB_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/;


export class JobStoreError extends Error {
  constructor(message, code = "JOB_STORE_ERROR") {
    super(message);
    this.name = "JobStoreError";
    this.code = code;
  }
}


function iso(value) {
  return (value instanceof Date ? value : new Date(value)).toISOString();
}


async function requirePrivateDirectory(directory) {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  const info = await lstat(directory);
  if (!info.isDirectory() || info.isSymbolicLink()) {
    throw new JobStoreError(
      "Artifact location must be a real directory",
      "UNSAFE_ARTIFACT_DIRECTORY",
    );
  }
  if ((info.mode & 0o077) !== 0) {
    throw new JobStoreError(
      "Artifact directory must not be accessible to group or other users",
      "UNSAFE_ARTIFACT_PERMISSIONS",
    );
  }
}


async function writePrivateJson(destination, value) {
  const temporary = path.join(
    path.dirname(destination),
    `.${path.basename(destination)}.${randomUUID()}.tmp`,
  );
  const serialized = `${JSON.stringify(value, null, 2)}\n`;
  await writeFile(temporary, serialized, {
    encoding: "utf8",
    flag: "wx",
    mode: 0o600,
  });
  await rename(temporary, destination);
  await chmod(destination, 0o600);
  return serialized;
}


async function appendPrivateEvent(destination, event, create = false) {
  const serialized = `${JSON.stringify(event)}\n`;
  if (create) {
    await writeFile(destination, serialized, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    });
  } else {
    await appendFile(destination, serialized, {
      encoding: "utf8",
      flag: "a",
      mode: 0o600,
    });
  }
  await chmod(destination, 0o600);
}


export async function createDurableBrowserJob({
  artifactDir,
  jobId = randomUUID(),
  targetLabel,
  createdAt = new Date(),
}) {
  if (!JOB_ID_PATTERN.test(jobId)) {
    throw new JobStoreError(
      "jobId must contain 1..80 safe characters",
      "INVALID_JOB_ID",
    );
  }
  await requirePrivateDirectory(artifactDir);
  const jobDir = path.join(artifactDir, jobId);
  try {
    await mkdir(jobDir, { mode: 0o700 });
  } catch (error) {
    if (error?.code === "EEXIST") {
      throw new JobStoreError("jobId already exists", "JOB_ALREADY_EXISTS");
    }
    throw error;
  }
  await chmod(jobDir, 0o700);

  const paths = Object.freeze({
    jobDir,
    manifest: path.join(jobDir, "manifest.json"),
    events: path.join(jobDir, "events.jsonl"),
    report: path.join(jobDir, "report.json"),
    receipt: path.join(jobDir, "receipt.json"),
    screenshot: path.join(jobDir, "screenshot.png"),
    trace: path.join(jobDir, "trace.zip"),
  });
  const timestamp = iso(createdAt);
  const manifest = {
    schema_version: JOB_STORE_SCHEMA_VERSION,
    job_id: jobId,
    target_label: targetLabel,
    state: "running",
    created_at: timestamp,
    updated_at: timestamp,
    attempts: 1,
  };
  await writePrivateJson(paths.manifest, manifest);
  await appendPrivateEvent(
    paths.events,
    {
      schema_version: JOB_STORE_SCHEMA_VERSION,
      job_id: jobId,
      event: "started",
      timestamp,
    },
    true,
  );
  return Object.freeze({
    schemaVersion: JOB_STORE_SCHEMA_VERSION,
    jobId,
    targetLabel,
    createdAt: timestamp,
    paths,
  });
}


export async function writePrivateArtifact(destination, data) {
  const temporary = path.join(
    path.dirname(destination),
    `.${path.basename(destination)}.${randomUUID()}.tmp`,
  );
  await writeFile(temporary, data, { flag: "wx", mode: 0o600 });
  await rename(temporary, destination);
  await chmod(destination, 0o600);
}


export async function markPrivateArtifact(destination) {
  await chmod(destination, 0o600);
}


export async function finalizeDurableBrowserJob(
  job,
  report,
  completedAt = new Date(),
) {
  if (report.job_id !== job.jobId) {
    throw new JobStoreError("Report job ID does not match", "JOB_ID_MISMATCH");
  }
  const serialized = await writePrivateJson(job.paths.report, report);
  const reportSha256 = createHash("sha256").update(serialized).digest("hex");
  const timestamp = iso(completedAt);
  const receipt = {
    schema_version: JOB_STORE_SCHEMA_VERSION,
    job_id: job.jobId,
    report_file: "report.json",
    report_sha256: reportSha256,
    completed_at: timestamp,
  };
  await writePrivateJson(job.paths.receipt, receipt);
  await writePrivateJson(job.paths.manifest, {
    schema_version: JOB_STORE_SCHEMA_VERSION,
    job_id: job.jobId,
    target_label: job.targetLabel,
    state: report.state,
    created_at: job.createdAt,
    updated_at: timestamp,
    attempts: 1,
    report_file: "report.json",
    receipt_file: "receipt.json",
  });
  await appendPrivateEvent(job.paths.events, {
    schema_version: JOB_STORE_SCHEMA_VERSION,
    job_id: job.jobId,
    event: report.state === "completed" ? "completed" : "failed",
    timestamp,
    outcome: report.execution.quality.outcome,
  });
  return Object.freeze({ reportSha256, receipt });
}


async function readPrivateTextFile(destination) {
  const info = await lstat(destination);
  if (!info.isFile() || info.isSymbolicLink()) {
    throw new JobStoreError(
      "Job artifact must be a regular file",
      "UNSAFE_JOB_ARTIFACT",
    );
  }
  if (info.size > MAX_TEXT_ARTIFACT_BYTES) {
    throw new JobStoreError(
      "Job artifact exceeds the replay limit",
      "JOB_ARTIFACT_TOO_LARGE",
    );
  }
  if ((info.mode & 0o077) !== 0) {
    throw new JobStoreError(
      "Job artifact must be private",
      "UNSAFE_ARTIFACT_PERMISSIONS",
    );
  }
  return readFile(destination, "utf8");
}


function parseJson(raw, code) {
  try {
    return JSON.parse(raw);
  } catch {
    throw new JobStoreError("Job artifact is not valid JSON", code);
  }
}


function validateReplayReport(report) {
  if (
    !report ||
    report.report_schema_version !== "1.0" ||
    !JOB_ID_PATTERN.test(report.job_id || "") ||
    !["completed", "failed"].includes(report.state) ||
    report.execution?.schema_version !== "1.1" ||
    report.execution?.route?.selected !== "browser"
  ) {
    throw new JobStoreError(
      "Browser report has an unsupported contract",
      "UNSUPPORTED_BROWSER_REPORT",
    );
  }
}


export async function replayBrowserJob(reportPath) {
  const rawReport = await readPrivateTextFile(reportPath);
  const report = parseJson(rawReport, "INVALID_BROWSER_REPORT");
  validateReplayReport(report);
  const receiptPath = path.join(path.dirname(reportPath), "receipt.json");
  const receipt = parseJson(
    await readPrivateTextFile(receiptPath),
    "INVALID_BROWSER_RECEIPT",
  );
  const digest = createHash("sha256").update(rawReport).digest("hex");
  if (
    receipt.job_id !== report.job_id ||
    receipt.report_file !== path.basename(reportPath) ||
    receipt.report_sha256 !== digest
  ) {
    throw new JobStoreError(
      "Browser report receipt does not match",
      "REPORT_INTEGRITY_FAILED",
    );
  }
  return {
    verified: true,
    job_id: report.job_id,
    state: report.state,
    target_label: report.target_label,
    execution: report.execution,
    artifacts: report.artifacts,
  };
}


export async function auditBrowserJob(jobDir, secrets = []) {
  const names = ["manifest.json", "events.jsonl", "report.json", "receipt.json"];
  const needles = secrets
    .filter((value) => typeof value === "string" && value.length > 0)
    .flatMap((value) => [value, encodeURIComponent(value)]);
  for (const name of names) {
    const raw = await readPrivateTextFile(path.join(jobDir, name));
    if (needles.some((needle) => raw.includes(needle))) {
      throw new JobStoreError(
        "A sensitive value was found in a text artifact",
        "SECRET_EXPOSURE_DETECTED",
      );
    }
  }
  return { clean: true, files_checked: names.length };
}
