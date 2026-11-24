"""JSON configuration loading and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import AnalysisConfig, Severity

_THRESHOLDS = {
    "max_complexity": 10,
    "max_function_lines": 50,
    "max_nesting_depth": 4,
    "max_parameters": 5,
}
_ALLOWED = {*_THRESHOLDS, "exclude", "severity", "rules"}


def read_config(path: Path | None) -> tuple[AnalysisConfig, list[str], Severity | None]:
    """Load a JSON config, returning thresholds, excludes, and severity floor."""
    if path is None:
        return AnalysisConfig(), [], None
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read config {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON config {path}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise ValueError("config file must contain a JSON object")
    unknown = set(raw) - _ALLOWED
    if unknown:
        raise ValueError(f"unknown config key(s): {', '.join(sorted(unknown))}")

    values = {}
    for key, default in _THRESHOLDS.items():
        value = raw.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"config {key} must be a positive integer")
        values[key] = value

    excludes = raw.get("exclude", [])
    if isinstance(excludes, str):
        excludes = [excludes]
    if not isinstance(excludes, list) or not all(isinstance(item, str) for item in excludes):
        raise ValueError("config exclude must be a string or a list of strings")

    threshold = None
    if "severity" in raw:
        try:
            threshold = Severity.parse(raw["severity"])
        except (ValueError, AttributeError) as exc:
            raise ValueError("config severity must be error, warning, or info") from exc

    overrides: dict[str, Severity] = {}
    rules = raw.get("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("config rules must be an object mapping rule ids to options")
    for rule_id, options in rules.items():
        if isinstance(options, str):
            value = options
        elif isinstance(options, dict) and set(options) == {"severity"}:
            value = options["severity"]
        else:
            raise ValueError(f"config rule {rule_id} must be a severity string or {{\"severity\": ...}}")
        if not isinstance(rule_id, str):
            raise ValueError("config rule ids must be strings")
        try:
            overrides[rule_id.upper()] = Severity.parse(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"invalid severity for config rule {rule_id}") from exc
    return AnalysisConfig(**values, severity_overrides=overrides), excludes, threshold
