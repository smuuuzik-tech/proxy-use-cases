"""Command-line interface with stable JSON output and documented exit codes."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence

from .client import B2BHttpClient
from .config import ClientSettings, ConfigError


EXIT_OK = 0
EXIT_CONFIGURATION = 2
EXIT_HTTP_STATUS = 3
EXIT_TRANSPORT = 4
EXIT_INTERNAL = 5


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ConfigError(message)


def _parser() -> argparse.ArgumentParser:
    parser = JsonArgumentParser(
        prog="proxy-b2b",
        description="Send one provider-neutral HTTP request through a configured proxy.",
    )
    parser.add_argument("url", nargs="?", help="Absolute HTTPS target URL")
    parser.add_argument(
        "--method",
        default="GET",
        choices=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"],
    )
    parser.add_argument("--headers-file", help="JSON object with request headers")
    body = parser.add_mutually_exclusive_group()
    body.add_argument("--body-file", help="Raw UTF-8 body file, or - for stdin")
    body.add_argument("--json-body-file", help="JSON body file, or - for stdin")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    return parser


def _headers(payload: object) -> Dict[str, str]:
    if not isinstance(payload, dict):
        raise ConfigError("Headers file must contain one JSON object.")
    parsed: Dict[str, str] = {}
    for name, value in payload.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise ConfigError("Header names and values must be strings.")
        name = name.strip()
        if not name or "\n" in name or "\r" in name:
            raise ConfigError("Header name is invalid.")
        if "\n" in value or "\r" in value:
            raise ConfigError("Header value is invalid.")
        parsed[name] = value
    return parsed


def _read_input(source: str, label: str, maximum: int = 1_048_576) -> str:
    try:
        if source == "-":
            value = sys.stdin.read(maximum + 1)
        else:
            with Path(source).open("rb") as handle:
                raw = handle.read(maximum + 1)
            if len(raw) > maximum:
                raise ConfigError(f"{label} exceeds {maximum} bytes.")
            value = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"Cannot read {label}.") from exc
    if len(value.encode("utf-8")) > maximum:
        raise ConfigError(f"{label} exceeds {maximum} bytes.")
    return value


def _reject_json_constant(value: str) -> None:
    raise ConfigError(f"Non-finite JSON value {value} is not allowed.")


def _load_json(value: str, label: str) -> object:
    try:
        return json.loads(value, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{label} must contain valid JSON.") from exc


def _emit(payload: dict, pretty: bool) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2 if pretty else None,
            sort_keys=pretty,
        )
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = None
    try:
        args = _parser().parse_args(argv)
        settings = ClientSettings.from_env()
        target_url = args.url or os.environ.get("B2B_TARGET_URL", "").strip()
        if not target_url:
            raise ConfigError("Target URL is required as an argument or B2B_TARGET_URL.")
        headers: Dict[str, str] = {}
        if args.headers_file:
            headers = _headers(
                _load_json(
                    _read_input(args.headers_file, "headers file"),
                    "Headers file",
                )
            )
        if args.headers_file == "-" and (
            args.body_file == "-" or args.json_body_file == "-"
        ):
            raise ConfigError("stdin can be used for only one input.")
        content = (
            _read_input(args.body_file, "body file")
            if args.body_file is not None
            else None
        )
        json_data = None
        if args.json_body_file is not None:
            json_data = _load_json(
                _read_input(args.json_body_file, "JSON body file"),
                "JSON body file",
            )

        with B2BHttpClient(settings) as client:
            result = client.request(
                args.method,
                target_url,
                headers=headers,
                content=content,
                json_data=json_data,
                request_id=os.environ.get("B2B_REQUEST_ID"),
            )
        _emit(result.to_dict(), args.pretty)
        if result.ok:
            return EXIT_OK
        if result.error_code == "transport_error":
            return EXIT_TRANSPORT
        return EXIT_HTTP_STATUS
    except ConfigError as exc:
        _emit(
            {
                "ok": False,
                "error": {"code": "configuration_error", "message": str(exc)},
            },
            bool(args and args.pretty),
        )
        return EXIT_CONFIGURATION
    except Exception:
        _emit(
            {
                "ok": False,
                "error": {
                    "code": "internal_error",
                    "message": "Unexpected internal error.",
                },
            },
            bool(args and args.pretty),
        )
        return EXIT_INTERNAL


if __name__ == "__main__":
    sys.exit(main())
