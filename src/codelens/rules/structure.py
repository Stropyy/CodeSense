"""Structural maintainability rules operating directly on the AST."""

from __future__ import annotations

import ast
import builtins

from ..model import Diagnostic, RuleContext, Severity
from .base import Rule, emit, files_with_trees, register
from .flow import _always_terminates


class _FunctionMetric(ast.NodeVisitor):
    """Collect complexity decisions without entering nested lexical scopes."""

    def __init__(self) -> None:
        self.complexity = 1

    def visit_FunctionDef(self, node):
        return

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef

    def visit_If(self, node):
        self.complexity += 1
        self.generic_visit(node)

    visit_IfExp = visit_If
    visit_For = visit_If
    visit_AsyncFor = visit_If
    visit_While = visit_If

    def visit_ExceptHandler(self, node):
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self.complexity += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_comprehension(self, node):
        self.complexity += 1 + len(node.ifs)
        self.generic_visit(node)

    def visit_Match(self, node):
        self.complexity += max(0, len(node.cases) - 1)
        self.generic_visit(node)


@register
class CyclomaticComplexity(Rule):
    id = "CL006"
    name = "high cyclomatic complexity"
    default_severity = Severity.WARNING

    def check(self, context: RuleContext) -> list[Diagnostic]:
        out = []
        threshold = context.config.max_complexity
        for file in files_with_trees(context.project):
            for node in ast.walk(file.tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                metric = _FunctionMetric()
                for statement in node.body:
                    metric.visit(statement)
                if metric.complexity > threshold:
                    out.append(emit(self, context, file, node,
                                    f"{node.name} has cyclomatic complexity {metric.complexity} (limit {threshold})"))
        return out


@register
class BareExcept(Rule):
    id = "CL007"
    name = "bare except"
    default_severity = Severity.WARNING

    def check(self, context: RuleContext) -> list[Diagnostic]:
        out = []
        for file in files_with_trees(context.project):
            for node in ast.walk(file.tree):
                if isinstance(node, ast.ExceptHandler) and node.type is None:
                    out.append(emit(self, context, file, node, "bare except catches every exception"))
        return out


def _is_mutable_default(node: ast.expr) -> bool:
    if isinstance(node, (ast.List, ast.Dict, ast.Set)):
        return True
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in {"list", "dict", "set"} and not node.args and not node.keywords
    return False


@register
class MutableDefaults(Rule):
    id = "CL008"
    name = "mutable default arguments"
    default_severity = Severity.WARNING

    def check(self, context: RuleContext) -> list[Diagnostic]:
        out = []
        for file in files_with_trees(context.project):
            for node in ast.walk(file.tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                    continue
                args = node.args
                for default in [*args.defaults, *(value for value in args.kw_defaults if value is not None)]:
                    if _is_mutable_default(default):
                        out.append(emit(self, context, file, default,
                                        "mutable default is shared between function calls"))
        return out


@register
class LongFunctions(Rule):
    id = "CL009"
    name = "long functions"
    default_severity = Severity.WARNING

    def check(self, context: RuleContext) -> list[Diagnostic]:
        out = []
        limit = context.config.max_function_lines
        for file in files_with_trees(context.project):
            for node in ast.walk(file.tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    end = getattr(node, "end_lineno", node.lineno)
                    length = end - node.lineno + 1
                    if length > limit:
                        out.append(emit(self, context, file, node,
                                        f"{node.name} spans {length} lines (limit {limit})"))
        return out


_CONTROL = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)


@register
class DeepNesting(Rule):
    id = "CL010"
    name = "deeply nested control flow"
    default_severity = Severity.WARNING

    def check(self, context: RuleContext) -> list[Diagnostic]:
        out = []
        limit = context.config.max_nesting_depth
        for file in files_with_trees(context.project):
            roots: list[tuple[list[ast.stmt], ast.AST]] = [(file.tree.body, file.tree)]
            roots.extend((scope.node.body, scope.node) for scope in file.scopes
                         if isinstance(scope.node, (ast.FunctionDef, ast.AsyncFunctionDef)))
            for statements, owner in roots:
                found = False

                def visit_block(block, depth):
                    nonlocal found
                    for statement in block:
                        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            continue
                        next_depth = depth + (1 if isinstance(statement, _CONTROL) else 0)
                        if not found and next_depth > limit:
                            out.append(emit(self, context, file, statement,
                                            f"control flow nesting depth exceeds limit {limit}"))
                            found = True
                        if isinstance(statement, ast.Try):
                            suites = [statement.body, statement.orelse, statement.finalbody]
                            suites.extend(handler.body for handler in statement.handlers)
                        elif isinstance(statement, ast.Match):
                            suites = [case.body for case in statement.cases]
                        else:
                            suites = [getattr(statement, attr, []) for attr in ("body", "orelse")]
                        for suite in suites:
                            if suite and isinstance(suite, list) and isinstance(suite[0], ast.stmt):
                                visit_block(suite, next_depth)

                visit_block(statements, 0)
        return out


def _parameter_count(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    args = node.args
    names = [arg.arg for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs]]
    count = len(names) + int(args.vararg is not None) + int(args.kwarg is not None)
    if names and names[0] in {"self", "cls"}:
        count -= 1
    return count


@register
class TooManyParameters(Rule):
    id = "CL011"
    name = "too many function parameters"
    default_severity = Severity.WARNING

    def check(self, context: RuleContext) -> list[Diagnostic]:
        out = []
        limit = context.config.max_parameters
        for file in files_with_trees(context.project):
            for node in ast.walk(file.tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    count = _parameter_count(node)
                    if count > limit:
                        out.append(emit(self, context, file, node,
                                        f"{node.name} has {count} parameters (limit {limit})"))
        return out


def _literal_key(node: ast.expr):
    try:
        value = ast.literal_eval(node)
        hash(value)
    except (ValueError, TypeError, SyntaxError):
        return False, None
    return True, value


@register
class DuplicateDictKeys(Rule):
    id = "CL012"
    name = "duplicate dictionary keys"
    default_severity = Severity.ERROR

    def check(self, context: RuleContext) -> list[Diagnostic]:
        out = []
        for file in files_with_trees(context.project):
            for node in ast.walk(file.tree):
                if not isinstance(node, ast.Dict):
                    continue
                seen = {}
                for key in node.keys:
                    if key is None:
                        continue
                    valid, value = _literal_key(key)
                    if not valid:
                        continue
                    if value in seen:
                        out.append(emit(self, context, file, key,
                                        f"duplicate dictionary key {value!r}; earlier key is on line {seen[value]}"))
                    else:
                        seen[value] = getattr(key, "lineno", node.lineno)
        return out


def _has_value_return(node: ast.AST) -> bool:
    class ReturnFinder(ast.NodeVisitor):
        found = False

        def visit_Return(self, current):
            if current.value is not None and not (isinstance(current.value, ast.Constant) and current.value.value is None):
                self.found = True

        def visit_FunctionDef(self, current):
            return

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_Lambda = visit_FunctionDef
        visit_ClassDef = visit_FunctionDef

    finder = ReturnFinder()
    for statement in getattr(node, "body", []):
        finder.visit(statement)
    return finder.found


def _contains_yield(node: ast.AST) -> bool:
    class YieldFinder(ast.NodeVisitor):
        found = False

        def visit_Yield(self, current):
            self.found = True

        visit_YieldFrom = visit_Yield

        def visit_FunctionDef(self, current):
            return

        visit_AsyncFunctionDef = visit_FunctionDef
        visit_Lambda = visit_FunctionDef

    finder = YieldFinder()
    for statement in getattr(node, "body", []):
        finder.visit(statement)
    return finder.found


@register
class MissingReturn(Rule):
    id = "CL013"
    name = "missing return on some paths"
    default_severity = Severity.WARNING

    def check(self, context: RuleContext) -> list[Diagnostic]:
        out = []
        for file in files_with_trees(context.project):
            for node in ast.walk(file.tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if _has_value_return(node) and not _contains_yield(node) and not _always_terminates(node.body):
                    out.append(emit(self, context, file, node,
                                    f"{node.name} can finish without returning a value"))
        return out


@register
class ShadowBuiltins(Rule):
    id = "CL014"
    name = "shadowing builtins"
    default_severity = Severity.WARNING

    def check(self, context: RuleContext) -> list[Diagnostic]:
        names = set(dir(builtins))
        out = []
        for file in files_with_trees(context.project):
            for scope in file.scopes:
                for name, bindings in scope.bindings.items():
                    if name in names and not name.startswith("_"):
                        for binding in bindings:
                            out.append(emit(self, context, file, binding.node,
                                            f"{name!r} shadows a Python builtin"))
        return out
