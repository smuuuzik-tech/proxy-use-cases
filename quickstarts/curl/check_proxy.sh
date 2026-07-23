#!/usr/bin/env bash

set -Eeuo pipefail

readonly SCRIPT_NAME="${0##*/}"

die() {
  printf '%s: %s\n' "$SCRIPT_NAME" "$1" >&2
  exit "${2:-64}"
}

validate_positive_seconds() {
  local variable_name="$1"
  local value="$2"

  if [[ ! "$value" =~ ^[0-9]+([.][0-9]+)?$ ]] || [[ "$value" =~ ^0+([.]0+)?$ ]]; then
    die "${variable_name} must be a positive number of seconds."
  fi
}

escape_curl_config_value() {
  local value="$1"

  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

write_runtime_config() {
  local escaped_url
  local escaped_user
  local escaped_password

  escaped_url="$(escape_curl_config_value "$CHECK_URL")"
  printf 'url = "%s"\n' "$escaped_url"
  if [[ "$has_proxy_user" == true ]]; then
    escaped_user="$(escape_curl_config_value "$PROXY_USER")"
    escaped_password="$(escape_curl_config_value "$PROXY_PASSWORD")"
    printf 'proxy-user = "%s:%s"\n' "$escaped_user" "$escaped_password"
  fi
}

readonly PROXY_URL="${PROXY_URL:-}"
readonly CHECK_URL="${CHECK_URL:-https://api.ipify.org?format=json}"
readonly CONNECT_TIMEOUT_SECONDS="${CONNECT_TIMEOUT_SECONDS:-10}"
readonly MAX_TIME_SECONDS="${MAX_TIME_SECONDS:-30}"
readonly CURL_BIN="${CURL_BIN:-curl}"

[[ -n "$PROXY_URL" ]] || die "PROXY_URL is required."

case "$PROXY_URL" in
  http://* | https://* | socks4://* | socks4a://* | socks5://* | socks5h://*) ;;
  *) die "PROXY_URL must use http, https, socks4, socks4a, socks5, or socks5h." ;;
esac

proxy_authority="${PROXY_URL#*://}"
proxy_authority="${proxy_authority%%/*}"
[[ "$proxy_authority" != *"@"* ]] ||
  die "Keep credentials out of PROXY_URL; use PROXY_USER and PROXY_PASSWORD."

case "$CHECK_URL" in
  https://*) ;;
  *) die "CHECK_URL must use HTTPS." ;;
esac
[[ "$CHECK_URL" != *$'\n'* && "$CHECK_URL" != *$'\r'* ]] ||
  die "CHECK_URL must not contain line breaks."
check_authority="${CHECK_URL#https://}"
check_authority="${check_authority%%/*}"
[[ "$check_authority" != *"@"* ]] ||
  die "CHECK_URL must not contain credentials."

validate_positive_seconds "CONNECT_TIMEOUT_SECONDS" "$CONNECT_TIMEOUT_SECONDS"
validate_positive_seconds "MAX_TIME_SECONDS" "$MAX_TIME_SECONDS"

command -v "$CURL_BIN" >/dev/null 2>&1 || die "curl was not found." 69

has_proxy_user=false
has_proxy_password=false
[[ -n "${PROXY_USER:-}" ]] && has_proxy_user=true
[[ -n "${PROXY_PASSWORD:-}" ]] && has_proxy_password=true

if [[ "$has_proxy_user" != "$has_proxy_password" ]]; then
  die "Set both PROXY_USER and PROXY_PASSWORD, or neither."
fi

if [[ "$has_proxy_user" == true ]]; then
  [[ "$PROXY_USER" != *:* ]] || die "PROXY_USER must not contain a colon."
  [[ "$PROXY_USER" != *$'\n'* && "$PROXY_USER" != *$'\r'* ]] ||
    die "PROXY_USER must not contain line breaks."
  [[ "$PROXY_PASSWORD" != *$'\n'* && "$PROXY_PASSWORD" != *$'\r'* ]] ||
    die "PROXY_PASSWORD must not contain line breaks."
fi

curl_args=(
  "$CURL_BIN"
  --disable
  --silent
  --show-error
  --fail
  --noproxy ""
  --connect-timeout "$CONNECT_TIMEOUT_SECONDS"
  --max-time "$MAX_TIME_SECONDS"
  --proxy "$PROXY_URL"
  --proto "=https"
  --header "Accept: application/json, text/plain;q=0.9"
  --config -
)

umask 077
response_file="$(mktemp "${TMPDIR:-/tmp}/proxy-check-response.XXXXXX")" ||
  die "Could not create a temporary response file." 73
trap 'rm -f "$response_file"' EXIT HUP INT TERM

curl_status=0
write_runtime_config |
  "${curl_args[@]}" >"$response_file" || curl_status=$?

if ((curl_status != 0)); then
  printf '%s: proxy check failed (curl exit code %d).\n' "$SCRIPT_NAME" "$curl_status" >&2
  exit "$curl_status"
fi

[[ -s "$response_file" ]] || die "The check endpoint returned an empty response." 65

command cat "$response_file"
printf '\n'
