import path from 'node:path';
import { isIP } from 'node:net';

const PROXY_PROTOCOLS = new Set(['http:', 'socks5:']);

export class ConfigurationError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ConfigurationError';
  }
}

function required(env, name) {
  const value = env[name]?.trim();
  if (!value) {
    throw new ConfigurationError(`${name} is required`);
  }
  return value;
}

function parseBoolean(value, name, fallback) {
  if (value === undefined || value.trim() === '') return fallback;
  if (value === 'true') return true;
  if (value === 'false') return false;
  throw new ConfigurationError(`${name} must be "true" or "false"`);
}

function parseInteger(value, name, fallback, minimum, maximum) {
  if (value === undefined || value.trim() === '') return fallback;
  if (!/^\d+$/.test(value.trim())) {
    throw new ConfigurationError(`${name} must be an integer`);
  }

  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new ConfigurationError(
      `${name} must be between ${minimum} and ${maximum}`,
    );
  }
  return parsed;
}

function isPrivateHost(hostname) {
  const host = hostname
    .toLowerCase()
    .replace(/^\[|\]$/g, '')
    .replace(/\.$/, '');
  if (host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local')) {
    return true;
  }
  if (isIP(host) === 4) {
    const [a, b] = host.split('.').map(Number);
    return (
      a === 0 ||
      a === 10 ||
      a === 127 ||
      (a === 100 && b >= 64 && b <= 127) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) ||
      (a === 198 && (b === 18 || b === 19)) ||
      a >= 224
    );
  }
  if (isIP(host) === 6) {
    if (host.startsWith('::ffff:')) {
      return true;
    }
    return (
      host === '::' ||
      host === '::1' ||
      host.startsWith('fc') ||
      host.startsWith('fd') ||
      host.startsWith('fe8') ||
      host.startsWith('fe9') ||
      host.startsWith('fea') ||
      host.startsWith('feb') ||
      host.startsWith('ff')
    );
  }
  return false;
}

export function parseAllowedHosts(raw, allowPrivateTargets = false) {
  const hosts = raw
    .split(',')
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);

  if (hosts.length === 0) {
    throw new ConfigurationError('ALLOWED_HOSTS must contain at least one host');
  }

  const normalizedHosts = [];
  for (const host of hosts) {
    if (host.includes('*')) {
      throw new ConfigurationError(
        'ALLOWED_HOSTS accepts exact hostnames only; wildcards are not allowed',
      );
    }

    let parsed;
    try {
      parsed = new URL(`https://${host}`);
    } catch {
      throw new ConfigurationError('ALLOWED_HOSTS contains an invalid hostname');
    }

    const normalizedHost = parsed.hostname.toLowerCase();
    const isBracketedIpv6 = host.startsWith('[') && host.endsWith(']');
    if (
      (!isBracketedIpv6 && normalizedHost !== host) ||
      parsed.port ||
      parsed.pathname !== '/' ||
      parsed.username ||
      parsed.password
    ) {
      throw new ConfigurationError(
        'ALLOWED_HOSTS must contain hostnames without scheme, port, path, or credentials',
      );
    }
    if (!allowPrivateTargets && isPrivateHost(normalizedHost)) {
      throw new ConfigurationError(
        'Private, loopback, link-local, and localhost targets require ALLOW_PRIVATE_TARGETS=true',
      );
    }
    normalizedHosts.push(normalizedHost);
  }

  return [...new Set(normalizedHosts)];
}

export function parseCheckUrl(raw, allowedHosts) {
  let url;
  try {
    url = new URL(raw);
  } catch {
    throw new ConfigurationError('CHECK_URL must be a valid absolute URL');
  }

  if (url.protocol !== 'https:') {
    throw new ConfigurationError('CHECK_URL must use https');
  }
  if (url.username || url.password) {
    throw new ConfigurationError('CHECK_URL must not contain credentials');
  }
  if (!allowedHosts.includes(url.hostname.toLowerCase())) {
    throw new ConfigurationError(
      'CHECK_URL hostname must exactly match an entry in ALLOWED_HOSTS',
    );
  }
  if (url.port) {
    throw new ConfigurationError('CHECK_URL must use the default HTTPS port');
  }

  url.hash = '';
  return url.toString();
}

export function parseProxy(rawServer, username, password) {
  let url;
  try {
    url = new URL(rawServer);
  } catch {
    throw new ConfigurationError(
      'PROXY_SERVER must be an absolute http:// or socks5:// URL',
    );
  }

  if (!PROXY_PROTOCOLS.has(url.protocol)) {
    throw new ConfigurationError('PROXY_SERVER must use http or socks5');
  }
  if (url.username || url.password) {
    throw new ConfigurationError(
      'Keep proxy credentials in PROXY_USERNAME and PROXY_PASSWORD',
    );
  }
  if (!['', '/'].includes(url.pathname) || url.search || url.hash) {
    throw new ConfigurationError(
      'PROXY_SERVER must not contain a path, query, or fragment',
    );
  }

  const user = username ?? '';
  const pass = password ?? '';
  if ((user && !user.trim()) || (pass && !pass.trim())) {
    throw new ConfigurationError(
      'Proxy credentials must not contain only whitespace',
    );
  }
  const hasUser = Boolean(user.trim());
  const hasPass = Boolean(pass.trim());
  if (hasUser !== hasPass) {
    throw new ConfigurationError(
      'PROXY_USERNAME and PROXY_PASSWORD must be provided together',
    );
  }
  if (url.protocol === 'socks5:' && hasUser) {
    throw new ConfigurationError(
      'Playwright supports username/password authentication for HTTP proxies; use an unauthenticated or IP-allowlisted SOCKS5 endpoint',
    );
  }

  return {
    server: url.toString().replace(/\/$/, ''),
    ...(hasUser ? { username: user, password: pass } : {}),
  };
}

export function isAllowedUrl(raw, allowedHosts) {
  try {
    const url = new URL(raw);
    return (
      url.protocol === 'https:' &&
      !url.username &&
      !url.password &&
      !url.port &&
      allowedHosts.includes(url.hostname.toLowerCase())
    );
  } catch {
    return false;
  }
}

export function buildConfig(env = process.env, options = {}) {
  const cwd = options.cwd ?? process.cwd();
  const allowPrivateTargets = parseBoolean(
    env.ALLOW_PRIVATE_TARGETS,
    'ALLOW_PRIVATE_TARGETS',
    false,
  );
  const allowedHosts = parseAllowedHosts(
    required(env, 'ALLOWED_HOSTS'),
    allowPrivateTargets,
  );
  const resourceAllowedHosts = env.RESOURCE_ALLOWED_HOSTS?.trim()
    ? parseAllowedHosts(env.RESOURCE_ALLOWED_HOSTS, allowPrivateTargets)
    : allowedHosts;
  const statusMin = parseInteger(
    env.EXPECTED_STATUS_MIN,
    'EXPECTED_STATUS_MIN',
    200,
    100,
    599,
  );
  const statusMax = parseInteger(
    env.EXPECTED_STATUS_MAX,
    'EXPECTED_STATUS_MAX',
    399,
    100,
    599,
  );
  if (statusMin > statusMax) {
    throw new ConfigurationError(
      'EXPECTED_STATUS_MIN must not exceed EXPECTED_STATUS_MAX',
    );
  }

  const regionLabel = required(env, 'REGION_LABEL');
  if (regionLabel.length > 80 || /[\u0000-\u001f\u007f]/u.test(regionLabel)) {
    throw new ConfigurationError(
      'REGION_LABEL must be 1-80 characters without control characters',
    );
  }

  const artifactDir = env.ARTIFACT_DIR?.trim() || 'artifacts';

  return Object.freeze({
    proxy: Object.freeze(
      parseProxy(
        required(env, 'PROXY_SERVER'),
        env.PROXY_USERNAME,
        env.PROXY_PASSWORD,
      ),
    ),
    chromiumArgs: Object.freeze([
      '--force-webrtc-ip-handling-policy=disable_non_proxied_udp',
    ]),
    regionLabel,
    checkUrl: parseCheckUrl(required(env, 'CHECK_URL'), allowedHosts),
    allowedHosts: Object.freeze(allowedHosts),
    resourceAllowedHosts: Object.freeze(resourceAllowedHosts),
    artifactDir: path.resolve(cwd, artifactDir),
    navigationTimeoutMs: parseInteger(
      env.NAVIGATION_TIMEOUT_MS,
      'NAVIGATION_TIMEOUT_MS',
      30_000,
      1_000,
      120_000,
    ),
    expectedStatus: Object.freeze({ min: statusMin, max: statusMax }),
    headless: parseBoolean(env.HEADLESS, 'HEADLESS', true),
    browserContext: Object.freeze({
      viewport: Object.freeze({ width: 1440, height: 900 }),
      serviceWorkers: 'block',
    }),
    blockWebSockets: true,
    fullPage: parseBoolean(env.FULL_PAGE, 'FULL_PAGE', false),
    maxScreenshotBytes: parseInteger(
      env.MAX_SCREENSHOT_BYTES,
      'MAX_SCREENSHOT_BYTES',
      10_485_760,
      1024,
      52_428_800,
    ),
    includeTitle: parseBoolean(env.INCLUDE_PAGE_TITLE, 'INCLUDE_PAGE_TITLE', false),
  });
}
