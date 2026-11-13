"""Command line interface: ``python -m caseproof FILE.jsonl``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .ledger import CaseLedger


def _parse_floor(text: str) -> Tuple[str, int]:
    label, sep, number = text.rpartition("=")
    if not sep or not label:
        raise argparse.ArgumentTypeError("expected LABEL=N, got %r" % text)
    try:
        value = int(number)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("floor must be an integer: %r" % number) from exc
    if value < 0:
        raise argparse.ArgumentTypeError("floor must be >= 0")
    return label, value


def _iter_cases(path: str, wrapped: bool) -> Iterable[Tuple[Any, Optional[str]]]:
    stream = sys.stdin if path == "-" else open(path, "r", encoding="utf-8")
    try:
        for lineno, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError("%s:%d: invalid JSON: %s" % (path, lineno, exc)) from exc
            if wrapped:
                if not isinstance(value, dict) or "case" not in value:
                    raise ValueError(
                        "%s:%d: --wrapped lines need a 'case' field" % (path, lineno)
                    )
                label = value.get("label")
                if label is not None and not isinstance(label, str):
                    raise ValueError("%s:%d: label must be a string" % (path, lineno))
                yield value["case"], label
            else:
                yield value, None
    finally:
        if stream is not sys.stdin:
            stream.close()


def _human(report: Dict[str, Any]) -> str:
    lines = [
        "declared cases : %d" % report["total"],
        "unique cases   : %d (%.3f%%)" % (report["unique"], 100.0 * report["unique_ratio"]),
        "duplicate events: %d" % report["duplicate_events"],
    ]
    if report["labels"]:
        lines.append("labels:")
        for label, counts in report["labels"].items():
            lines.append(
                "  %-16s total %6d  unique %6d" % (label, counts["total"], counts["unique"])
            )
    if report["top_duplicates"]:
        lines.append("most repeated keys:")
        for item in report["top_duplicates"][:3]:
            lines.append(
                "  sha256:%s  %6dx  %s"
                % (item["digest"][:16], item["count"], item["sample"])
            )
    if "certified" in report:
        lines.append("verdict        : %s" % ("CERTIFIED" if report["certified"] else "REJECTED"))
        for failure in report["failures"]:
            lines.append("  - %s" % failure)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="caseproof",
        description="Count declared differential-test cases vs unique content hashes.",
    )
    parser.add_argument("file", help="JSONL file with one case per line ('-' for stdin)")
    parser.add_argument("--wrapped", action="store_true", help="lines are {case, label} objects")
    parser.add_argument("--min-unique", type=int, default=1, help="required distinct cases")
    parser.add_argument(
        "--require-label",
        metavar="LABEL=N",
        type=_parse_floor,
        action="append",
        default=[],
        help="required distinct cases per label (repeatable)",
    )
    parser.add_argument("--top", type=int, default=5, help="how many repeated keys to report")
    parser.add_argument("--json-out", metavar="PATH", help="write the full report as JSON")
    parser.add_argument("--quiet", action="store_true", help="suppress the human summary")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_unique < 0 or args.top < 0:
        print("caseproof: --min-unique and --top must be >= 0", file=sys.stderr)
        return 2
    ledger = CaseLedger()
    try:
        for case, label in _iter_cases(args.file, args.wrapped):
            ledger.add(case, label=label)
    except (OSError, ValueError) as exc:
        print("caseproof: %s" % exc, file=sys.stderr)
        return 2

    per_label = dict(args.require_label)
    report = ledger.certify(args.min_unique, per_label, top=args.top)
    if not args.quiet:
        print(_human(report))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return 0 if report["certified"] else 1
