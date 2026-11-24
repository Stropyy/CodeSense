"""Command-line interface for CodeLens."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from .config import read_config
from .engine import analyze_project, validate_rule_ids
from .model import Diagnostic, Severity
from .rules.base import RULE_REGISTRY


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def _csv_items(values: list[str] | None) -> list[str]:
    return [part.strip() for value in values or [] for part in value.split(",") if part.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codelens",
        description="Statically inspect a Python file or project for maintainability issues.",
    )
    parser.add_argument("path", type=Path, help="Python file or project directory to analyze")
    parser.add_argument("--severity", choices=("error", "warning", "info"),
                        help="minimum severity to display and use for the issue exit code (default: warning)")
    parser.add_argument("--rules", help="comma-separated rule ids to enable, such as CL001,CL005")
    parser.add_argument("--ignore", action="append", metavar="R3", help="rule id(s) to ignore; repeat or comma-separate")
    parser.add_argument("--exclude", action="append", metavar="PATTERN", help="path or directory pattern to exclude")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="output format")
    parser.add_argument("--max-complexity", type=_positive_int, help="complexity warning threshold (default: 10)")
    parser.add_argument("--max-function-lines", type=_positive_int, help="function line limit (default: 50)")
    parser.add_argument("--max-nesting-depth", type=_positive_int, help="control-flow nesting limit (default: 4)")
    parser.add_argument("--max-parameters", type=_positive_int, help="function parameter limit (default: 5)")
    parser.add_argument("--config", type=Path, help="JSON configuration file")
    return parser


def _render_text(diagnostics: list[Diagnostic], color: bool) -> str:
    lines: list[str] = []
    colors = {Severity.ERROR: "\033[31m", Severity.WARNING: "\033[33m", Severity.INFO: "\033[36m"}
    reset = "\033[0m"
    for item in diagnostics:
        severity = item.severity.value.upper()
        if color:
            severity = f"{colors[item.severity]}{severity}{reset}"
        lines.append(f"{item.file}:{item.line}:{item.column}  {severity}  {item.rule_id}  {item.message}")
    counts = {severity: sum(item.severity is severity for item in diagnostics) for severity in Severity}
    lines.append(
        "Summary: "
        f"{counts[Severity.ERROR]} error(s), "
        f"{counts[Severity.WARNING]} warning(s), "
        f"{counts[Severity.INFO]} info item(s)."
    )
    return "\n".join(lines)


def _render_json(diagnostics: list[Diagnostic]) -> str:
    counts = {severity.value: sum(item.severity is severity for item in diagnostics) for severity in Severity}
    return json.dumps(
        {"diagnostics": [item.to_dict() for item in diagnostics], "summary": counts},
        indent=2,
        sort_keys=True,
    )


def main(argv: list[str] | None = None) -> int:
    """Run CodeLens and return its documented process status."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        config, config_excludes, config_severity = read_config(args.config)
        threshold = Severity.parse(args.severity) if args.severity else (config_severity or Severity.WARNING)
        replacements = {}
        for key in ("max_complexity", "max_function_lines", "max_nesting_depth", "max_parameters"):
            value = getattr(args, key)
            if value is not None:
                replacements[key] = value
        config = replace(config, **replacements)

        if args.rules:
            selected = validate_rule_ids(args.rules.split(","))
        else:
            selected = set(RULE_REGISTRY)
        ignored = validate_rule_ids(_csv_items(args.ignore)) if args.ignore else set()
        selected -= ignored
        for rule_id in config.severity_overrides:
            if rule_id not in RULE_REGISTRY:
                raise ValueError(f"unknown rule id in config: {rule_id}")

        excludes = [*config_excludes, *_csv_items(args.exclude)]
        diagnostics = analyze_project(args.path, excludes=excludes, config=config, rule_ids=selected)
        diagnostics = [item for item in diagnostics if item.severity.rank >= threshold.rank]
    except (OSError, ValueError) as exc:
        print(f"codelens: error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(_render_json(diagnostics))
    else:
        print(_render_text(diagnostics, color=sys.stdout.isatty()))
    return 1 if diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
