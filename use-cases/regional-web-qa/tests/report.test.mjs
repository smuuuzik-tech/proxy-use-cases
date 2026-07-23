import assert from 'node:assert/strict';
import { chmod, mkdtemp, readFile, stat } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import {
  createArtifactPaths,
  createEvidenceReport,
  writeEvidenceReport,
} from '../src/report.mjs';

const config = Object.freeze({
  proxy: Object.freeze({
    server: 'http://proxy.example:3128',
    username: 'company-user',
    password: 'super-secret',
  }),
  regionLabel: 'DE / Berlin',
  checkUrl:
    'https://staging.example.com/check?scenario=pricing&token=request-secret',
  expectedStatus: Object.freeze({ min: 200, max: 399 }),
  includeTitle: false,
});

test('evidence has required B2B QA fields and contains no proxy credentials', () => {
  const report = createEvidenceReport({
    config,
    completedAt: new Date('2026-07-23T10:20:30.000Z'),
    elapsedTimeMs: 1234.6,
    observed: {
      url: 'https://staging.example.com/de?session=observed-secret',
      status: 200,
      title: 'Regional price — company-user',
    },
    outcome: 'passed',
    exitCode: 0,
    screenshotPath: '/tmp/regional-qa-de.png',
    error: 'failed through http://proxy.example:3128/private?token=proxy-secret',
  });

  assert.equal(report.timestamp, '2026-07-23T10:20:30.000Z');
  assert.equal(report.requestedRegionLabel, 'DE / Berlin');
  assert.equal(
    report.regionVerification,
    'operator_asserted_not_independently_verified',
  );
  assert.equal(report.check.status, 200);
  assert.equal(report.check.elapsedTimeMs, 1235);
  assert.equal(report.artifacts.screenshot, 'regional-qa-de.png');

  const serialized = JSON.stringify(report);
  assert.equal(serialized.includes('company-user'), false);
  assert.equal(serialized.includes('super-secret'), false);
  assert.equal(serialized.includes('request-secret'), false);
  assert.equal(serialized.includes('observed-secret'), false);
  assert.equal(serialized.includes('proxy.example'), false);
});

test('artifact names are unique and filesystem-safe', () => {
  const paths = createArtifactPaths(
    '/evidence',
    'DE / Berlin',
    new Date('2026-07-23T10:20:30.000Z'),
    'run-1234',
  );

  assert.equal(
    paths.screenshot,
    '/evidence/regional-qa-de-berlin-20260723T102030Z-run1234.png',
  );
  assert.equal(
    paths.report,
    '/evidence/regional-qa-de-berlin-20260723T102030Z-run1234.json',
  );
});

test('JSON evidence is written atomically as a private file', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'regional-qa-'));
  const destination = path.join(directory, 'evidence.json');
  const report = { schemaVersion: 1, outcome: 'passed' };

  await writeEvidenceReport(report, destination);

  assert.deepEqual(JSON.parse(await readFile(destination, 'utf8')), report);
});

test('existing artifact directory permissions are not changed', async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'regional-qa-existing-'));
  await chmod(directory, 0o755);
  const destination = path.join(directory, 'evidence.json');

  await writeEvidenceReport({ schemaVersion: 1 }, destination);

  assert.equal((await stat(directory)).mode & 0o777, 0o755);
  assert.equal((await stat(destination)).mode & 0o777, 0o600);
});
