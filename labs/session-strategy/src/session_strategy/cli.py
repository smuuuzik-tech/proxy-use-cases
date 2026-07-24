from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .analysis import AnalysisError, analyze_records, load_jsonl


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AnalysisError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(
        prog="proxy-session-analyzer",
        description=(
            "Compare sticky and rotating proxy outcomes using workload JSONL."
        ),
    )
    parser.add_argument("input", help="JSONL workload observations.")
    parser.add_argument("--output", default="-", help="Report path or - for stdout.")
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        report = analyze_records(load_jsonl(args.input))
        rendered = json.dumps(
            report,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
        if args.output == "-":
            print(rendered)
        else:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        return 0
    except AnalysisError as exc:
        print(f"analysis error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"output error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
