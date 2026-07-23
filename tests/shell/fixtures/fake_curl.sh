#!/usr/bin/env bash

set -Eeuo pipefail

: "${FAKE_CURL_ARGS_FILE:?FAKE_CURL_ARGS_FILE is required}"

printf '%s\n' "$@" >"$FAKE_CURL_ARGS_FILE"

config_from_stdin=""
previous_argument=""
for argument in "$@"; do
  if [[ "$previous_argument" == "--config" && "$argument" == "-" ]]; then
    config_from_stdin="$(command cat)"
    break
  fi
  previous_argument="$argument"
done

if [[ "${FAKE_CURL_REQUIRE_AUTH:-0}" == "1" ]]; then
  [[ "$config_from_stdin" == *'proxy-user = "alice:s3cr3t"'* ]] || exit 97
fi
[[ "$config_from_stdin" == *'url = "https://api.ipify.org?format=json"'* ]] || exit 98

case "${FAKE_CURL_MODE:-success}" in
  success)
    printf '{"ip":"203.0.113.10"}'
    ;;
  timeout)
    printf 'curl: (28) Operation timed out\n' >&2
    exit 28
    ;;
  empty)
    ;;
  *)
    printf 'fake_curl.sh: unsupported test mode\n' >&2
    exit 99
    ;;
esac
