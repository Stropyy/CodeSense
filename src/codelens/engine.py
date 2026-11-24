"""Analysis orchestration for files and registered rules."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable

from .discovery import discover_python_files
from .model import AnalysisConfig, Diagnostic, FileAnalysis, ProjectAnalysis, RuleContext, Severity
from .parser import parse_file
from . import rules as _builtin_rules  # noqa: F401
from .rules.base import RULE_REGISTRY


PARSE_ERROR_ID = "PARSE_ERROR"


def analyze_project(
    path: Path,
    *,
    excludes: Iterable[str] = (),
    config: AnalysisConfig | None = None,
    rule_ids: set[str] | None = None,
) -> list[Diagnostic]:
    """Analyze a Python file or project directory without executing target code."""
    root = path.expanduser().resolve()
    paths = discover_python_files(root, excludes)
    files = [parse_file(file_path, root) for file_path in paths]
    modules = {file.module_name: file for file in files}
    project = ProjectAnalysis(root, files, modules)
    actual_config = config or AnalysisConfig()
    context = RuleContext(project, actual_config)
    diagnostics: list[Diagnostic] = []

    for file in files:
        if file.parse_error is not None:
            diagnostics.append(Diagnostic(
                file=file.display_path,
                line=file.parse_error_line,
                column=file.parse_error_column,
                rule_id=PARSE_ERROR_ID,
                severity=Severity.ERROR,
                message=f"could not parse file: {file.parse_error}",
            ))

    selected = rule_ids if rule_ids is not None else set(RULE_REGISTRY)
    for rule_id in sorted(selected):
        rule_type = RULE_REGISTRY[rule_id]
        diagnostics.extend(rule_type().check(context))

    diagnostics = [
        diagnostic
        for diagnostic in diagnostics
        if not ({diagnostic.rule_id, "ALL"} & _suppressed_ids(files, diagnostic.file, diagnostic.line))
    ]
    diagnostics.sort(key=lambda item: (item.file, item.line, item.column, item.rule_id, item.message))
    return diagnostics


def _suppressed_ids(files: list[FileAnalysis], display_path: str, line: int) -> set[str]:
    for file in files:
        if file.display_path == display_path:
            return file.suppressions.get(line, set())
    return set()


def validate_rule_ids(rule_ids: Iterable[str]) -> set[str]:
    """Normalize and validate requested rule identifiers."""
    normalized = {rule_id.strip().upper() for rule_id in rule_ids if rule_id.strip()}
    unknown = normalized - set(RULE_REGISTRY)
    if unknown:
        raise ValueError(f"unknown rule id(s): {', '.join(sorted(unknown))}")
    return normalized
