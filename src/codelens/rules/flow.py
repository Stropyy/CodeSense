"""Name-use and control-flow rules."""

from __future__ import annotations

import ast

from ..model import Diagnostic, RuleContext, Severity
from .base import Rule, emit, files_with_trees, register


@register
class UnusedVariables(Rule):
    id = "CL001"
    name = "unused variables"
    default_severity = Severity.WARNING

    def check(self, context: RuleContext) -> list[Diagnostic]:
        out = []
        for file in files_with_trees(context.project):
            for scope in file.scopes:
                for name, bindings in scope.bindings.items():
                    if name.startswith("_") or name == "__all__" or file.dynamic_module_names and scope.kind == "module":
                        continue
                    for binding in bindings:
                        if binding.kind == "variable" and not binding.used:
                            out.append(emit(self, context, file, binding.node,
                                            f"variable {name!r} is assigned but never used"))
        return out


@register
class UnusedImports(Rule):
    id = "CL002"
    name = "unused imports"
    default_severity = Severity.WARNING

    def check(self, context: RuleContext) -> list[Diagnostic]:
        out = []
        for file in files_with_trees(context.project):
            for scope in file.scopes:
                for name, bindings in scope.bindings.items():
                    if name.startswith("_") or file.dynamic_module_names and scope.kind == "module":
                        continue
                    for binding in bindings:
                        if binding.kind == "import" and not binding.used:
                            out.append(emit(self, context, file, binding.node,
                                            f"import {name!r} is never used"))
        return out


@register
class UnusedArguments(Rule):
    id = "CL003"
    name = "unused function arguments"
    default_severity = Severity.WARNING

    def check(self, context: RuleContext) -> list[Diagnostic]:
        out = []
        for file in files_with_trees(context.project):
            for scope in file.scopes:
                if scope.kind != "function":
                    continue
                for name, bindings in scope.bindings.items():
                    if name.startswith("_") or name in {"self", "cls"}:
                        continue
                    for binding in bindings:
                        if binding.kind == "argument" and not binding.used:
                            out.append(emit(self, context, file, binding.node,
                                            f"argument {name!r} is never used"))
        return out


def _contains_loop_break(node: ast.AST) -> bool:
    """Whether a while suite contains a break targeting that loop."""
    class BreakFinder(ast.NodeVisitor):
        found = False
        nested = 0

        def visit_Break(self, current):
            if self.nested == 0:
                self.found = True

        def visit_For(self, current):
            self.nested += 1
            self.generic_visit(current)
            self.nested -= 1

        visit_AsyncFor = visit_For
        visit_While = visit_For

        def visit_FunctionDef(self, current):
            return

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_Lambda = visit_FunctionDef

    finder = BreakFinder()
    for statement in getattr(node, "body", []):
        finder.visit(statement)
    return finder.found


def _constant_truth(node: ast.expr) -> bool | None:
    """Return a truth value only when the expression is a safe AST literal."""
    try:
        return bool(ast.literal_eval(node))
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


def _is_true(node: ast.expr) -> bool:
    return _constant_truth(node) is True


def _is_false(node: ast.expr) -> bool:
    return _constant_truth(node) is False


def _pattern_is_wildcard(pattern: ast.pattern) -> bool:
    return isinstance(pattern, ast.MatchAs) and pattern.pattern is None


def _always_terminates(statements: list[ast.stmt]) -> bool:
    """Conservative return/raise/break/continue termination approximation."""
    for statement in statements:
        if isinstance(statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            return True
        if isinstance(statement, ast.If):
            if _is_true(statement.test):
                if _always_terminates(statement.body):
                    return True
            elif _is_false(statement.test):
                if _always_terminates(statement.orelse):
                    return True
            elif statement.orelse and _always_terminates(statement.body) and _always_terminates(statement.orelse):
                return True
        elif isinstance(statement, ast.Try):
            if statement.finalbody and _always_terminates(statement.finalbody):
                return True
            paths = [statement.body, *(handler.body for handler in statement.handlers)]
            if statement.orelse:
                paths.append(statement.orelse)
            if paths and all(_always_terminates(path) for path in paths):
                return True
        elif isinstance(statement, ast.Match):
            exhaustive = any(
                _pattern_is_wildcard(case.pattern) and case.guard is None
                for case in statement.cases
            )
            if exhaustive and statement.cases and all(_always_terminates(case.body) for case in statement.cases):
                return True
        elif isinstance(statement, (ast.With, ast.AsyncWith)):
            if _always_terminates(statement.body):
                return True
        elif isinstance(statement, ast.While) and _is_true(statement.test) and not _contains_loop_break(statement):
            return True
    return False


@register
class UnreachableCode(Rule):
    id = "CL004"
    name = "unreachable code"
    default_severity = Severity.WARNING

    def check(self, context: RuleContext) -> list[Diagnostic]:
        out = []

        def scan(file, statements):
            dead = False
            for statement in statements:
                if dead:
                    out.append(emit(self, context, file, statement, "statement is unreachable"))
                    continue
                # Literal-false suites cannot execute; literal-true branches have
                # the opposite suite excluded. Other suites are scanned normally.
                if isinstance(statement, ast.If) and _is_false(statement.test):
                    for child in statement.body:
                        out.append(emit(self, context, file, child, "statement is in a constant-false branch"))
                    scan(file, statement.orelse)
                elif isinstance(statement, ast.If) and _is_true(statement.test):
                    scan(file, statement.body)
                    for child in statement.orelse:
                        out.append(emit(self, context, file, child, "statement is in a constant-false branch"))
                elif isinstance(statement, ast.While) and _is_false(statement.test):
                    for child in statement.body:
                        out.append(emit(self, context, file, child, "statement is in a constant-false loop"))
                    scan(file, statement.orelse)
                else:
                    for suite in _child_suites(statement):
                        scan(file, suite)
                if _always_terminates([statement]):
                    dead = True

        for file in files_with_trees(context.project):
            scan(file, file.tree.body)
        return out


def _child_suites(node: ast.stmt) -> list[list[ast.stmt]]:
    suites: list[list[ast.stmt]] = []
    for attr in ("body", "orelse", "finalbody"):
        value = getattr(node, attr, None)
        if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
            suites.append(value)
    if isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
        suites.extend(handler.body for handler in node.handlers if handler.body)
    if isinstance(node, ast.Match):
        suites.extend(case.body for case in node.cases if case.body)
    return suites
