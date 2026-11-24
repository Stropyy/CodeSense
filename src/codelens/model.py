"""Shared models for parsed files, scopes, rules, and diagnostics."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Severity(str, Enum):
    """Diagnostic severity, ordered from least to most serious."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"

    @property
    def rank(self) -> int:
        return {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}[self]

    @classmethod
    def parse(cls, value: str) -> "Severity":
        try:
            return cls(value.lower())
        except ValueError as exc:
            raise ValueError(f"invalid severity {value!r}; expected error, warning, or info") from exc


@dataclass(slots=True)
class Diagnostic:
    """One issue reported by a rule or by the parser."""

    file: str
    line: int
    column: int
    rule_id: str
    severity: Severity
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "message": self.message,
        }


@dataclass(slots=True)
class Binding:
    """A name introduced in a lexical scope."""

    name: str
    node: ast.AST
    kind: str
    line: int
    used: bool = False


@dataclass(slots=True)
class Scope:
    """A simplified lexical scope used for name-use rules."""

    kind: str
    node: ast.AST
    parent: "Scope | None" = None
    bindings: dict[str, list[Binding]] = field(default_factory=dict)
    global_names: set[str] = field(default_factory=set)
    nonlocal_names: set[str] = field(default_factory=set)

    def add(self, binding: Binding) -> Binding:
        self.bindings.setdefault(binding.name, []).append(binding)
        return binding

    def lookup(self, name: str) -> Binding | None:
        """Resolve a load, skipping class namespaces for nested functions."""
        scope: Scope | None = self
        first = True
        while scope is not None:
            if not (scope.kind == "class" and not first):
                found = scope.bindings.get(name)
                if found:
                    return found[-1]
            first = False
            scope = scope.parent
        return None


@dataclass(slots=True)
class ImportRef:
    """A statically observed import edge and its local binding, if any."""

    target: str
    bound_name: str | None
    node: ast.AST
    line: int
    is_star: bool = False


@dataclass(slots=True)
class FileAnalysis:
    """Parsed and scope-indexed representation of one Python file."""

    path: Path
    display_path: str
    source: str
    tree: ast.Module | None
    module_name: str
    root_scope: Scope
    scopes: list[Scope] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    suppressions: dict[int, set[str]] = field(default_factory=dict)
    parse_error: str | None = None
    parse_error_line: int = 1
    parse_error_column: int = 1
    dynamic_module_names: bool = False


@dataclass(slots=True)
class ProjectAnalysis:
    """All files analyzed together, including a module-name index."""

    root: Path
    files: list[FileAnalysis]
    modules: dict[str, FileAnalysis]


@dataclass(slots=True)
class AnalysisConfig:
    """Rule thresholds and severity overrides."""

    max_complexity: int = 10
    max_function_lines: int = 50
    max_nesting_depth: int = 4
    max_parameters: int = 5
    severity_overrides: dict[str, Severity] = field(default_factory=dict)


@dataclass(slots=True)
class RuleContext:
    """Context passed to every registered rule."""

    project: ProjectAnalysis
    config: AnalysisConfig

