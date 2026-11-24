"""Rule registration and the shared rule contract."""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import ClassVar

from ..model import Diagnostic, FileAnalysis, ProjectAnalysis, RuleContext, Severity


class Rule(ABC):
    """Base class for a statically registered CodeLens rule."""

    id: ClassVar[str]
    name: ClassVar[str]
    default_severity: ClassVar[Severity] = Severity.WARNING

    @abstractmethod
    def check(self, context: RuleContext) -> list[Diagnostic]:
        """Return diagnostics for the complete project."""


RULE_REGISTRY: dict[str, type[Rule]] = {}


def register(rule: type[Rule]) -> type[Rule]:
    """Register a rule class by id; duplicate ids are programmer errors."""
    if rule.id in RULE_REGISTRY:
        raise ValueError(f"duplicate rule id: {rule.id}")
    RULE_REGISTRY[rule.id] = rule
    return rule


def emit(
    rule: Rule,
    context: RuleContext,
    file: FileAnalysis,
    node: ast.AST,
    message: str,
) -> Diagnostic:
    """Build a diagnostic, applying any configured severity override."""
    severity = context.config.severity_overrides.get(rule.id, rule.default_severity)
    line = max(1, int(getattr(node, "lineno", 1)))
    column_offset = max(0, int(getattr(node, "col_offset", 0)))
    source_lines = file.source.splitlines()
    if line <= len(source_lines):
        # AST columns count UTF-8 bytes, while displayed columns count characters.
        prefix = source_lines[line - 1].encode("utf-8")[:column_offset]
        column_offset = len(prefix.decode("utf-8", errors="ignore"))
    return Diagnostic(
        file=file.display_path,
        line=line,
        column=column_offset + 1,
        rule_id=rule.id,
        severity=severity,
        message=message,
    )


def files_with_trees(project: ProjectAnalysis) -> Iterator[FileAnalysis]:
    return (file for file in project.files if file.tree is not None)
