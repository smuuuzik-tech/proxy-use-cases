import assert from 'node:assert/strict';
import test from 'node:test';
import {
  redactObject,
  redactText,
  sanitizeUrl,
} from '../src/redaction.mjs';

test('redactText removes literal and URL-encoded credentials', () => {
  const password = 'p@ss word';
  const output = redactText(
    `password=${password} encoded=${encodeURIComponent(password)}`,
    [password],
  );

  assert.equal(output.includes(password), false);
  assert.equal(output.includes(encodeURIComponent(password)), false);
  assert.match(output, /\[REDACTED\]/);
});

test('sanitizeUrl strips credentials, path, fragment, and all query values', () => {
  const output = sanitizeUrl(
    'https://user:pass@example.com/path?scenario=price&session_token=abc#private',
  );

  assert.equal(
    output,
    'https://example.com/[PATH_REDACTED]?[QUERY_REDACTED]',
  );
});

test('redactText sanitizes URLs embedded in browser errors', () => {
  const output = redactText(
    'navigation failed at https://example.com/customer/42?account=private',
  );
  assert.equal(output.includes('customer'), false);
  assert.equal(output.includes('private'), false);
});

test('redactObject removes common credential fields recursively', () => {
  const output = redactObject({
    username: 'user',
    nested: { password: 'pass', status: 200 },
  });

  assert.deepEqual(output, {
    username: '[REDACTED]',
    nested: { password: '[REDACTED]', status: 200 },
  });
});

test('redactText removes local user paths from shareable errors', () => {
  const output = redactText(
    "Cannot find package imported from /Users/alice/private/project/src/cli.mjs",
  );

  assert.equal(output.includes('/Users/alice'), false);
  assert.match(output, /\[LOCAL_PATH\]/);
});
