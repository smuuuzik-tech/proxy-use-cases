from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Mapping, Sequence

from .probe import ConfigError, ExitCode, ProbeConfig, render_report, run_probe
from .redaction import redact_text


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ConfigError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(
        prog="proxy-diagnostics",
        description=(
            "Classify proxy authentication, DNS, TLS, timeout and upstream failures."
        ),
    )
    parser.add_argument("--proxy", help="Proxy URL without credentials.")
    parser.add_argument("--target", help="Authorized HTTPS target URL.")
    parser.add_argument("--connect-timeout", type=float, default=None)
    parser.add_argument("--total-timeout", type=float, default=None)
    parser.add_argument("--allow-private-target", action="store_true")
    parser.add_argument("--curl-binary", default=None)
    parser.add_argument("--output", default="-")
    parser.add_argument("--compact", action="store_true")
    return parser


def config_from_args(
    args: argparse.Namespace,
    environ: Mapping[str, str],
) -> ProbeConfig:
    proxy_url = args.proxy or environ.get("PD_PROXY_URL", "")
    target_url = args.target or environ.get(
        "PD_TARGET_URL",
        "https://api.ipify.org?format=json",
    )
    if not proxy_url:
        raise ConfigError("set --proxy or PD_PROXY_URL")
    return ProbeConfig(
        proxy_url=proxy_url,
        target_url=target_url,
        proxy_username=environ.get("PD_PROXY_USERNAME"),
        proxy_password=environ.get("PD_PROXY_PASSWORD"),
        connect_timeout_seconds=args.connect_timeout
        if args.connect_timeout is not None
        else float(environ.get("PD_CONNECT_TIMEOUT", "5")),
        total_timeout_seconds=args.total_timeout
        if args.total_timeout is not None
        else float(environ.get("PD_TOTAL_TIMEOUT", "15")),
        allow_private_target=args.allow_private_target,
        curl_binary=args.curl_binary or environ.get("PD_CURL_BINARY", "curl"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        config = config_from_args(args, os.environ)
        report = run_probe(config)
        rendered = render_report(report, compact=args.compact)
        if args.output == "-":
            print(rendered)
        else:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        return int(report.exit_code)
    except (ConfigError, ValueError) as exc:
        print(f"configuration error: {redact_text(exc)}", file=sys.stderr)
        return int(ExitCode.CONFIG)
    except OSError as exc:
        print(f"output error: {redact_text(exc)}", file=sys.stderr)
        return int(ExitCode.UNKNOWN)


if __name__ == "__main__":
    raise SystemExit(main())
