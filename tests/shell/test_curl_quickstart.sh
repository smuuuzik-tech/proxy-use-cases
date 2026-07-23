#!/usr/bin/env bash

set -Eeuo pipefail

readonly TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPOSITORY_ROOT="$(cd "$TEST_DIR/../.." && pwd)"
readonly SCRIPT_UNDER_TEST="$REPOSITORY_ROOT/quickstarts/curl/check_proxy.sh"
readonly FAKE_CURL="$TEST_DIR/fixtures/fake_curl.sh"

test_tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/curl-quickstart-tests.XXXXXX")"
trap 'rm -rf "$test_tmp_dir"' EXIT HUP INT TERM

pass_count=0

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

pass() {
  pass_count=$((pass_count + 1))
  printf 'ok %d - %s\n' "$pass_count" "$1"
}

assert_file_has_exact_line() {
  local expected="$1"
  local file="$2"
  command grep -Fqx -- "$expected" "$file" ||
    fail "expected argument was not passed to cURL"
}

chmod +x "$FAKE_CURL"

args_file="$test_tmp_dir/args"
stdout_file="$test_tmp_dir/stdout"
stderr_file="$test_tmp_dir/stderr"

if CURL_BIN="$FAKE_CURL" \
  FAKE_CURL_ARGS_FILE="$args_file" \
  "$SCRIPT_UNDER_TEST" >"$stdout_file" 2>"$stderr_file"; then
  fail "missing PROXY_URL should fail"
fi
command grep -Fq "PROXY_URL is required" "$stderr_file" ||
  fail "missing PROXY_URL should explain the problem"
pass "rejects a missing PROXY_URL"

PROXY_URL="http://proxy.example.com:8080" \
CURL_BIN="$FAKE_CURL" \
FAKE_CURL_ARGS_FILE="$args_file" \
"$SCRIPT_UNDER_TEST" >"$stdout_file" 2>"$stderr_file" ||
  fail "anonymous proxy check should succeed"
[[ "$(command cat "$stdout_file")" == '{"ip":"203.0.113.10"}' ]] ||
  fail "successful stdout should contain only the endpoint response"
[[ ! -s "$stderr_file" ]] || fail "successful check should not write to stderr"
assert_file_has_exact_line "--disable" "$args_file"
assert_file_has_exact_line "--fail" "$args_file"
assert_file_has_exact_line "--noproxy" "$args_file"
assert_file_has_exact_line "--connect-timeout" "$args_file"
assert_file_has_exact_line "--max-time" "$args_file"
assert_file_has_exact_line "--proxy" "$args_file"
assert_file_has_exact_line "http://proxy.example.com:8080" "$args_file"
assert_file_has_exact_line "--config" "$args_file"
if command grep -Fq "api.ipify.org" "$args_file"; then
  fail "CHECK_URL must not be passed as a command-line argument"
fi
pass "uses safe defaults and prints the successful response"

PROXY_URL="socks5h://proxy.example.com:1080" \
PROXY_USER="alice" \
PROXY_PASSWORD="s3cr3t" \
CURL_BIN="$FAKE_CURL" \
FAKE_CURL_ARGS_FILE="$args_file" \
FAKE_CURL_REQUIRE_AUTH=1 \
"$SCRIPT_UNDER_TEST" >"$stdout_file" 2>"$stderr_file" ||
  fail "authenticated proxy check should succeed"
if command grep -Fq "alice" "$args_file" || command grep -Fq "s3cr3t" "$args_file"; then
  fail "credentials must not be passed as command-line arguments"
fi
if command grep -Fq "alice" "$stdout_file" ||
  command grep -Fq "s3cr3t" "$stdout_file" ||
  command grep -Fq "alice" "$stderr_file" ||
  command grep -Fq "s3cr3t" "$stderr_file"; then
  fail "credentials must not be printed"
fi
assert_file_has_exact_line "--config" "$args_file"
assert_file_has_exact_line "-" "$args_file"
pass "passes authentication through stdin without printing credentials"

if PROXY_URL="http://proxy.example.com:8080" \
  PROXY_USER="alice" \
  CURL_BIN="$FAKE_CURL" \
  FAKE_CURL_ARGS_FILE="$args_file" \
  "$SCRIPT_UNDER_TEST" >"$stdout_file" 2>"$stderr_file"; then
  fail "incomplete authentication should fail"
fi
command grep -Fq "Set both PROXY_USER and PROXY_PASSWORD" "$stderr_file" ||
  fail "incomplete authentication should explain the problem"
pass "rejects incomplete authentication"

if PROXY_URL="http://alice:secret@proxy.example.com:8080" \
  CURL_BIN="$FAKE_CURL" \
  FAKE_CURL_ARGS_FILE="$args_file" \
  "$SCRIPT_UNDER_TEST" >"$stdout_file" 2>"$stderr_file"; then
  fail "embedded credentials should fail"
fi
if command grep -Fq "alice" "$stderr_file" || command grep -Fq "secret" "$stderr_file"; then
  fail "embedded credentials must not be repeated in diagnostics"
fi
pass "rejects embedded credentials without echoing them"

if PROXY_URL="http://proxy.example.com:8080" \
  CHECK_URL="https://api-user:api-secret@allowed.example/ip" \
  CURL_BIN="$FAKE_CURL" \
  FAKE_CURL_ARGS_FILE="$args_file" \
  "$SCRIPT_UNDER_TEST" >"$stdout_file" 2>"$stderr_file"; then
  fail "CHECK_URL with embedded credentials should fail"
fi
if command grep -Fq "api-user" "$stderr_file" || command grep -Fq "api-secret" "$stderr_file"; then
  fail "CHECK_URL credentials must not be repeated in diagnostics"
fi
pass "rejects endpoint credentials without echoing them"

if PROXY_URL="http://proxy.example.com:8080" \
  CHECK_URL=$'https://allowed.example/ip\noutput = "/tmp/injected"' \
  CURL_BIN="$FAKE_CURL" \
  FAKE_CURL_ARGS_FILE="$args_file" \
  "$SCRIPT_UNDER_TEST" >"$stdout_file" 2>"$stderr_file"; then
  fail "CHECK_URL with line breaks should fail"
fi
command grep -Fq "must not contain line breaks" "$stderr_file" ||
  fail "CHECK_URL line break rejection should explain the problem"
pass "rejects cURL config injection through CHECK_URL"

if PROXY_URL="http://proxy.example.com:8080" \
  CONNECT_TIMEOUT_SECONDS="never" \
  CURL_BIN="$FAKE_CURL" \
  FAKE_CURL_ARGS_FILE="$args_file" \
  "$SCRIPT_UNDER_TEST" >"$stdout_file" 2>"$stderr_file"; then
  fail "invalid timeout should fail"
fi
command grep -Fq "must be a positive number of seconds" "$stderr_file" ||
  fail "invalid timeout should explain the problem"
pass "validates timeout values"

set +e
PROXY_URL="http://proxy.example.com:8080" \
CURL_BIN="$FAKE_CURL" \
FAKE_CURL_ARGS_FILE="$args_file" \
FAKE_CURL_MODE=timeout \
"$SCRIPT_UNDER_TEST" >"$stdout_file" 2>"$stderr_file"
curl_status=$?
set -e
[[ "$curl_status" -eq 28 ]] || fail "curl exit code should be preserved"
command grep -Fq "curl exit code 28" "$stderr_file" ||
  fail "curl failure should include the exit code"
pass "preserves cURL failure codes"

set +e
PROXY_URL="http://proxy.example.com:8080" \
CURL_BIN="$FAKE_CURL" \
FAKE_CURL_ARGS_FILE="$args_file" \
FAKE_CURL_MODE=empty \
"$SCRIPT_UNDER_TEST" >"$stdout_file" 2>"$stderr_file"
empty_status=$?
set -e
[[ "$empty_status" -eq 65 ]] || fail "empty response should return 65"
command grep -Fq "empty response" "$stderr_file" ||
  fail "empty response should explain the problem"
pass "rejects an empty successful response"

printf '1..%d\n' "$pass_count"
