from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from .engine import BenchmarkError, load_benchmark, run_benchmark


class ConfigArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise BenchmarkError(message, "INVALID_ARGUMENTS")


def build_parser() -> argparse.ArgumentParser:
    parser = ConfigArgumentParser(
        prog="proxybench",
        description=(
            "Compare sanitized Proxy Healthcheck reports with explicit B2B gates."
        ),
    )
    parser.add_argument("--config", required=True, help="Benchmark manifest JSON.")
    parser.add_argument(
        "--output",
        default="-",
        help="Benchmark result path, or - for stdout.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Write compact JSON.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = run_benchmark(load_benchmark(args.config))
        rendered = json.dumps(
            result,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
        if args.output == "-":
            print(rendered)
        else:
            _write_private_atomic(Path(args.output), rendered + "\n")
        return 0 if result["recommended_candidate"] else 1
    except BenchmarkError as exc:
        print(
            json.dumps({"error": {"code": exc.code}}, sort_keys=True),
            file=sys.stderr,
        )
        return 64
    except OSError:
        print(
            json.dumps({"error": {"code": "OUTPUT_ERROR"}}, sort_keys=True),
            file=sys.stderr,
        )
        return 70


def _write_private_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
