#!/usr/bin/env node

import { performance } from 'node:perf_hooks';
import path from 'node:path';
import { buildConfig, ConfigurationError, isAllowedUrl } from './config.mjs';
import { loadEnvFileIfPresent } from './env.mjs';
import { ExitCode } from './exit-codes.mjs';
import {
  createArtifactPaths,
  createEvidenceReport,
  writePrivateArtifact,
  writeEvidenceReport,
} from './report.mjs';
import { redactText } from './redaction.mjs';

function publicError(error, secrets = []) {
  const message = error instanceof Error ? error.message : String(error);
  return redactText(message, secrets);
}

async function tryScreenshot(page, destination, fullPage, maximumBytes) {
  if (!page || page.url() === 'about:blank') return null;
  const screenshot = await page.screenshot({ fullPage });
  if (screenshot.length > maximumBytes) {
    throw new Error(`Screenshot exceeds ${maximumBytes} bytes`);
  }
  await writePrivateArtifact(screenshot, destination);
  return destination;
}

async function execute() {
  let config;
  try {
    await loadEnvFileIfPresent();
    config = buildConfig();
  } catch (error) {
    const message =
      error instanceof ConfigurationError
        ? error.message
        : 'Unexpected configuration error';
    console.error(`Configuration error: ${message}`);
    return ExitCode.CONFIGURATION;
  }

  const secrets = [
    config.proxy.server,
    config.proxy.username,
    config.proxy.password,
  ].filter(Boolean);
  const paths = createArtifactPaths(
    config.artifactDir,
    config.regionLabel,
    new Date(),
  );
  const observed = { url: null, status: null, title: null };
  let screenshotPath = null;
  let outcome = 'failed';
  let errorMessage = null;
  let exitCode = ExitCode.UNEXPECTED;
  let browser = null;
  let page = null;
  const started = performance.now();

  try {
    let chromium;
    try {
      ({ chromium } = await import('playwright'));
    } catch (error) {
      errorMessage = `Playwright is unavailable: ${publicError(error, secrets)}`;
      exitCode = ExitCode.BROWSER_UNAVAILABLE;
      return await finalize();
    }

    try {
      browser = await chromium.launch({
        headless: config.headless,
        proxy: config.proxy,
        args: config.chromiumArgs,
      });
    } catch (error) {
      errorMessage = `Browser launch failed: ${publicError(error, secrets)}`;
      exitCode = ExitCode.BROWSER_UNAVAILABLE;
      return await finalize();
    }

    const context = await browser.newContext(config.browserContext);
    if (config.blockWebSockets) {
      await context.routeWebSocket(/.*/, (webSocket) => webSocket.close());
    }
    await context.route('**/*', async (route) => {
      const request = route.request();
      const allowedHosts = request.isNavigationRequest()
        ? config.allowedHosts
        : config.resourceAllowedHosts;
      if (!isAllowedUrl(request.url(), allowedHosts)) {
        await route.abort('blockedbyclient');
        return;
      }
      await route.continue();
    });
    page = await context.newPage();
    context.on('page', (candidate) => {
      if (candidate !== page) {
        void candidate.close();
      }
    });
    page.setDefaultNavigationTimeout(config.navigationTimeoutMs);

    let response;
    try {
      response = await page.goto(config.checkUrl, {
        waitUntil: 'domcontentloaded',
        timeout: config.navigationTimeoutMs,
      });
      observed.url = page.url();
      observed.status = response?.status() ?? null;
      observed.title = config.includeTitle ? await page.title() : null;

      if (!isAllowedUrl(observed.url, config.allowedHosts)) {
        throw new Error('Final URL is outside ALLOWED_HOSTS');
      }
    } catch (error) {
      observed.url = page.url() === 'about:blank' ? null : page.url();
      try {
        observed.title =
          config.includeTitle && observed.url ? await page.title() : null;
      } catch {
        observed.title = null;
      }
      try {
        screenshotPath = await tryScreenshot(
          page,
          paths.screenshot,
          config.fullPage,
          config.maxScreenshotBytes,
        );
      } catch {
        screenshotPath = null;
      }
      outcome = 'navigation_failed';
      errorMessage = publicError(error, secrets);
      exitCode = ExitCode.NAVIGATION_FAILED;
    }

    if (exitCode !== ExitCode.NAVIGATION_FAILED) {
      try {
        screenshotPath = await tryScreenshot(
          page,
          paths.screenshot,
          config.fullPage,
          config.maxScreenshotBytes,
        );
      } catch (error) {
        outcome = 'artifact_write_failed';
        errorMessage = `Screenshot write failed: ${publicError(error, secrets)}`;
        exitCode = ExitCode.ARTIFACT_WRITE_FAILED;
      }
    }

    if (exitCode !== ExitCode.NAVIGATION_FAILED && screenshotPath) {
      const statusAccepted =
        observed.status !== null &&
        observed.status >= config.expectedStatus.min &&
        observed.status <= config.expectedStatus.max;

      if (!statusAccepted) {
        outcome = 'assertion_failed';
        errorMessage = `Observed HTTP status ${observed.status ?? 'none'} is outside the expected range`;
        exitCode = ExitCode.ASSERTION_FAILED;
      } else {
        outcome = 'passed';
        exitCode = ExitCode.OK;
      }
    }
  } catch (error) {
    errorMessage = publicError(error, secrets);
    exitCode = ExitCode.UNEXPECTED;
  } finally {
    if (browser) {
      try {
        await browser.close();
      } catch (error) {
        if (exitCode === ExitCode.OK) {
          outcome = 'failed';
          errorMessage = `Browser close failed: ${publicError(error, secrets)}`;
          exitCode = ExitCode.UNEXPECTED;
        }
      }
    }
  }

  return await finalize();

  async function finalize() {
    const report = createEvidenceReport({
      config,
      completedAt: new Date(),
      elapsedTimeMs: performance.now() - started,
      observed,
      outcome,
      exitCode,
      screenshotPath,
      error: errorMessage,
    });

    try {
      await writeEvidenceReport(report, paths.report);
      console.log(
        JSON.stringify(
          {
            outcome: report.outcome,
            exitCode: report.exitCode,
            report: path.basename(paths.report),
            screenshot: screenshotPath ? path.basename(screenshotPath) : null,
          },
          null,
          2,
        ),
      );
      return exitCode;
    } catch (error) {
      console.error(
        `Artifact write failed: ${publicError(error, secrets)}`,
      );
      return ExitCode.ARTIFACT_WRITE_FAILED;
    }
  }
}

process.exitCode = await execute();
