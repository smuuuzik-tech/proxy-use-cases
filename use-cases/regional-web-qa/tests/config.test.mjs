import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildConfig,
  ConfigurationError,
  isAllowedUrl,
  parseProxy,
} from '../src/config.mjs';

const validEnv = Object.freeze({
  PROXY_SERVER: 'http://proxy.example:3128',
  PROXY_USERNAME: 'business-user',
  PROXY_PASSWORD: 'business-password',
  REGION_LABEL: 'DE / Berlin',
  CHECK_URL: 'https://staging.example.com/regional?scenario=pricing',
  ALLOWED_HOSTS: 'staging.example.com,preview.example.com',
});

test('buildConfig creates provider-neutral Playwright proxy config', () => {
  const config = buildConfig(validEnv, { cwd: '/tmp/regional-qa-test' });

  assert.deepEqual(config.proxy, {
    server: 'http://proxy.example:3128',
    username: 'business-user',
    password: 'business-password',
  });
  assert.equal(config.regionLabel, 'DE / Berlin');
  assert.equal(config.checkUrl, validEnv.CHECK_URL);
  assert.deepEqual(config.allowedHosts, [
    'staging.example.com',
    'preview.example.com',
  ]);
  assert.deepEqual(config.resourceAllowedHosts, config.allowedHosts);
  assert.equal(config.navigationTimeoutMs, 30_000);
  assert.equal(config.includeTitle, false);
  assert.deepEqual(config.browserContext, {
    viewport: { width: 1440, height: 900 },
    serviceWorkers: 'block',
  });
  assert.equal(config.blockWebSockets, true);
  assert.deepEqual(config.chromiumArgs, [
    '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
  ]);
  assert.equal(config.fullPage, false);
  assert.equal(config.maxScreenshotBytes, 10_485_760);
});

test('CHECK_URL must exactly match the hostname allowlist', () => {
  assert.throws(
    () =>
      buildConfig(
        {
          ...validEnv,
          CHECK_URL: 'https://not-staging.example.com/',
        },
        { cwd: '/tmp/regional-qa-test' },
      ),
    ConfigurationError,
  );

  assert.equal(
    isAllowedUrl(
      'https://staging.example.com/final',
      ['staging.example.com'],
    ),
    true,
  );
  assert.equal(
    isAllowedUrl('http://staging.example.com/final', ['staging.example.com']),
    false,
  );
  assert.equal(
    isAllowedUrl('https://staging.example.com:8443/final', ['staging.example.com']),
    false,
  );
  assert.equal(
    isAllowedUrl(
      'https://attacker-staging.example.com/final',
      ['staging.example.com'],
    ),
    false,
  );
});

test('wildcards and credentials in allowlisted inputs are rejected', () => {
  assert.throws(
    () =>
      buildConfig(
        { ...validEnv, ALLOWED_HOSTS: '*.example.com' },
        { cwd: '/tmp/regional-qa-test' },
      ),
    /wildcards/,
  );
  assert.throws(
    () =>
      buildConfig(
        {
          ...validEnv,
          CHECK_URL: 'https://user:pass@staging.example.com/',
        },
        { cwd: '/tmp/regional-qa-test' },
      ),
    /must not contain credentials/,
  );
});

test('proxy credentials must be separate and complete', () => {
  assert.throws(
    () => parseProxy('http://user:pass@proxy.example:3128', '', ''),
    /Keep proxy credentials/,
  );
  assert.throws(
    () => parseProxy('http://proxy.example:3128', 'user', ''),
    /provided together/,
  );
  assert.deepEqual(parseProxy('socks5://proxy.example:1080', '', ''), {
    server: 'socks5://proxy.example:1080',
  });
  assert.throws(
    () => parseProxy('socks5://proxy.example:1080', 'user', 'pass'),
    /HTTP proxies/,
  );
  assert.throws(
    () => parseProxy('http://proxy.example:1080', '   ', '   '),
    /only whitespace/,
  );
});

test('status range is validated', () => {
  assert.throws(
    () =>
      buildConfig(
        {
          ...validEnv,
          EXPECTED_STATUS_MIN: '400',
          EXPECTED_STATUS_MAX: '399',
        },
        { cwd: '/tmp/regional-qa-test' },
      ),
    /must not exceed/,
  );
});

test('private and loopback targets require an explicit opt-in', () => {
  for (const host of [
    '127.0.0.1',
    '169.254.169.254',
    '100.64.0.1',
    '[::1]',
    '[::]',
    '[ff02::1]',
    '[::ffff:127.0.0.1]',
  ]) {
    assert.throws(
      () =>
        buildConfig(
          {
            ...validEnv,
            ALLOWED_HOSTS: host,
            CHECK_URL: `https://${host}/`,
          },
          { cwd: '/tmp/regional-qa-test' },
        ),
      /ALLOW_PRIVATE_TARGETS=true/,
    );
  }
});

test('proxy credential whitespace is preserved', () => {
  assert.deepEqual(parseProxy('http://proxy.example:3128', ' user ', ' pass '), {
    server: 'http://proxy.example:3128',
    username: ' user ',
    password: ' pass ',
  });
});
