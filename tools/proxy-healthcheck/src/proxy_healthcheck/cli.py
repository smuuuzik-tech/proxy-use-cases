from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .config import ConfigError, load_config
from .models import ExitCode
from .redaction import redact_text
from .engine import run_healthcheck


class ConfigArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ConfigError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = ConfigArgumentParser(
        prog="proxy-healthcheck",
        description="Provider-neutral proxy pool diagnostics for authorized infrastructure.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="JSON config path. Values can be overridden with PHC_* environment variables.",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="JSON report path, or - for stdout (default).",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON instead of indented JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        config = load_config(args.config)
        report = run_healthcheck(config)
        rendered = json.dumps(
            report.to_dict(),
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
        if args.output == "-":
            print(rendered)
        else:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        return report.exit_code
    except ConfigError as exc:
        print(f"configuration error: {redact_text(exc)}", file=sys.stderr)
        return int(ExitCode.CONFIG_ERROR)
    except OSError as exc:
        print(f"output error: {redact_text(exc)}", file=sys.stderr)
        return int(ExitCode.INTERNAL_ERROR)
    except Exception as exc:
        print(f"internal error: {redact_text(exc)}", file=sys.stderr)
        return int(ExitCode.INTERNAL_ERROR)


if __name__ == "__main__":
    raise SystemExit(main())
