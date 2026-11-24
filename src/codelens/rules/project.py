"""Project-wide import graph and circular import rule."""

from __future__ import annotations

import ast

from ..model import Diagnostic, FileAnalysis, ImportRef, RuleContext, Severity
from .base import Rule, emit, register


def _relative_base(file: FileAnalysis) -> str:
    if file.path.name == "__init__.py":
        return file.module_name
    return file.module_name.rpartition(".")[0]


def _resolve_relative(file: FileAnalysis, level: int, module: str) -> str:
    package_name = _relative_base(file)
    package = package_name.split(".") if package_name else []
    if level:
        remove = level - 1
        if remove >= len(package):
            return ""
        package = package[: len(package) - remove]
    if module:
        package.extend(module.split("."))
    return ".".join(package)


def _target_modules(file: FileAnalysis, import_ref: ImportRef, modules: dict[str, FileAnalysis]) -> set[str]:
    node = import_ref.node
    candidates: list[str] = []
    if isinstance(node, ast.Import):
        candidates.append(import_ref.target)
    elif isinstance(node, ast.ImportFrom):
        base = _resolve_relative(file, node.level, node.module or "") if node.level else (node.module or "")
        if not base:
            return set()
        imported_name = None
        if import_ref.bound_name:
            alias = next((item for item in node.names
                          if (item.asname or item.name) == import_ref.bound_name), None)
            imported_name = alias.name if alias is not None else import_ref.bound_name
        if imported_name and imported_name != "*":
            submodule = f"{base}.{imported_name}"
            if submodule in modules:
                candidates.append(submodule)
        candidates.append(base)
    for original in candidates:
        candidate = original
        while candidate:
            if candidate in modules:
                return {candidate}
            candidate = candidate.rpartition(".")[0]
    return set()


def _canonical_cycle(cycle: list[str]) -> tuple[str, ...]:
    body = cycle[:-1]
    if not body:
        return tuple(cycle)
    rotations = [tuple(body[index:] + body[:index]) for index in range(len(body))]
    best = min(rotations)
    return (*best, best[0])


@register
class CircularImports(Rule):
    id = "CL005"
    name = "circular imports"
    default_severity = Severity.ERROR

    def check(self, context: RuleContext) -> list[Diagnostic]:
        modules = context.project.modules
        graph: dict[str, list[tuple[str, FileAnalysis, ImportRef]]] = {name: [] for name in modules}
        for file in context.project.files:
            if file.tree is None:
                continue
            for import_ref in file.imports:
                for target in _target_modules(file, import_ref, modules):
                    graph[file.module_name].append((target, file, import_ref))
        for edges in graph.values():
            edges.sort(key=lambda item: (item[0], item[2].line))

        state: dict[str, int] = {}
        stack: list[str] = []
        discovered: dict[tuple[str, ...], tuple[FileAnalysis, ImportRef]] = {}

        def visit(module: str) -> None:
            state[module] = 1
            stack.append(module)
            for target, source_file, import_ref in graph.get(module, []):
                if state.get(target, 0) == 0:
                    visit(target)
                elif state.get(target) == 1:
                    start = stack.index(target)
                    cycle = _canonical_cycle([*stack[start:], target])
                    if cycle not in discovered:
                        canonical_source, canonical_target = cycle[0], cycle[1]
                        edge = next(
                            (item for item in graph[canonical_source] if item[0] == canonical_target),
                            (target, source_file, import_ref),
                        )
                        discovered[cycle] = (edge[1], edge[2])
            stack.pop()
            state[module] = 2

        for module in sorted(graph):
            if state.get(module, 0) == 0:
                visit(module)

        out = []
        for cycle in sorted(discovered):
            file, import_ref = discovered[cycle]
            out.append(emit(self, context, file, import_ref.node,
                            f"circular import: {' -> '.join(cycle)}"))
        return out
