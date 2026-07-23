const SENSITIVE_OBJECT_KEY =
  /^(authorization|cookie|password|proxyPassword|proxyUsername|secret|token|username)$/i;

function replaceAllLiteral(text, secret) {
  if (!secret) return text;
  return text.split(secret).join('[REDACTED]');
}

export function sanitizeUrl(raw) {
  if (!raw) return null;

  try {
    const url = new URL(raw);
    if (!['http:', 'https:'].includes(url.protocol)) return null;
    const pathMarker = url.pathname === '/' ? '/' : '/[PATH_REDACTED]';
    const queryMarker = url.search ? '?[QUERY_REDACTED]' : '';
    return `${url.origin}${pathMarker}${queryMarker}`;
  } catch {
    return null;
  }
}

export function redactText(value, secrets = []) {
  let text = String(value ?? '');
  for (const secret of secrets.filter(Boolean)) {
    text = replaceAllLiteral(text, secret);
    text = replaceAllLiteral(text, encodeURIComponent(secret));
  }

  return text
    .replace(
      /\b(authorization|password|proxy_password|secret|token)=([^&\s]+)/gi,
      '$1=[REDACTED]',
    )
    .replace(
      /(https?:\/\/)([^/\s:@]+):([^@\s/]+)@/gi,
      '$1[REDACTED]@',
    )
    .replace(
      /(?:\/Users\/|\/home\/)[^ \n\r\t"'`]+/g,
      '[LOCAL_PATH]',
    )
    .replace(
      /\b[A-Za-z]:\\Users\\[^ \n\r\t"'`]+/g,
      '[LOCAL_PATH]',
    )
    .replace(/https?:\/\/[^\s"'<>]+/gi, (candidate) => {
      const sanitized = sanitizeUrl(candidate);
      return sanitized ?? '[REDACTED_URL]';
    });
}

export function redactObject(value, secrets = []) {
  if (Array.isArray(value)) {
    return value.map((item) => redactObject(item, secrets));
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        SENSITIVE_OBJECT_KEY.test(key)
          ? '[REDACTED]'
          : redactObject(item, secrets),
      ]),
    );
  }
  return typeof value === 'string' ? redactText(value, secrets) : value;
}
