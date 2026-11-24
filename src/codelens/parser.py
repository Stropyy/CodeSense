"""Safe source reading and AST/scope collection (target code is never run)."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

from .model import Binding, FileAnalysis, ImportRef, Scope

_SUPPRESSION = re.compile(r"#\s*codelens:\s*ignore\[([^\]]+)\]", re.IGNORECASE)


def module_name_for(path: Path, root: Path) -> str:
    """Derive an importable project module name from a source path."""
    if root.is_file():
        return path.stem
    relative = path.relative_to(root)
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    package_root = (root / "__init__.py").is_file()
    names = ([root.name] if package_root else []) + parts
    return ".".join(names) or (root.name if path.name == "__init__.py" else path.stem)


def _suppression_comments(source: str) -> dict[int, set[str]]:
    suppressions: dict[int, set[str]] = {}
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            match = _SUPPRESSION.search(token.string)
            if match:
                ids = {item.strip().upper() for item in match.group(1).split(",") if item.strip()}
                suppressions.setdefault(token.start[0], set()).update(ids)
    except (tokenize.TokenError, IndentationError):
        # Keep suppressions found before malformed syntax; parsing reports the error.
        pass
    return suppressions


class ScopeCollector(ast.NodeVisitor):
    """Collect import bindings and name uses while observing Python scopes."""

    def __init__(self, analysis: FileAnalysis) -> None:
        self.analysis = analysis
        self.scope = analysis.root_scope
        self.scopes = analysis.scopes
        self._function_depth = 0

    def _bind(self, name: str, node: ast.AST, kind: str) -> Binding:
        destination = self.scope
        if name in destination.global_names:
            destination = self.analysis.root_scope
        elif name in destination.nonlocal_names:
            parent = destination.parent
            while parent is not None and parent.kind != "function":
                parent = parent.parent
            if parent is not None:
                destination = parent
        line = getattr(node, "lineno", 1)
        return destination.add(Binding(name, node, kind, line))

    def _new_scope(self, kind: str, node: ast.AST, parent: Scope | None = None) -> Scope:
        scope = Scope(kind, node, parent if parent is not None else self.scope)
        self.scopes.append(scope)
        return scope

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        if node.returns is not None:
            self.visit(node.returns)
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            if arg.annotation is not None:
                self.visit(arg.annotation)
        if node.args.vararg and node.args.vararg.annotation is not None:
            self.visit(node.args.vararg.annotation)
        if node.args.kwarg and node.args.kwarg.annotation is not None:
            self.visit(node.args.kwarg.annotation)
        self._bind(node.name, node, "definition")
        fn_scope = self._new_scope("function", node)
        old_scope = self.scope
        self.scope = fn_scope
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            self._bind(arg.arg, arg, "argument")
        if node.args.vararg:
            self._bind(node.args.vararg.arg, node.args.vararg, "argument")
        if node.args.kwarg:
            self._bind(node.args.kwarg.arg, node.args.kwarg, "argument")
        self._function_depth += 1
        for statement in node.body:
            self.visit(statement)
        self._function_depth -= 1
        self.scope = old_scope

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in [*node.args.defaults, *node.args.kw_defaults]:
            if default is not None:
                self.visit(default)
        old_scope = self.scope
        scope = self._new_scope("function", node)
        self.scope = scope
        for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]:
            self._bind(arg.arg, arg, "argument")
        if node.args.vararg:
            self._bind(node.args.vararg.arg, node.args.vararg, "argument")
        if node.args.kwarg:
            self._bind(node.args.kwarg.arg, node.args.kwarg, "argument")
        self.visit(node.body)
        self.scope = old_scope

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expr in [*node.decorator_list, *node.bases, *(kw.value for kw in node.keywords)]:
            self.visit(expr)
        self._bind(node.name, node, "definition")
        old_scope = self.scope
        self.scope = self._new_scope("class", node)
        for statement in node.body:
            self.visit(statement)
        self.scope = old_scope

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            binding = self.scope.lookup(node.id)
            if binding is not None:
                binding.used = True
        elif isinstance(node.ctx, ast.Store):
            self._bind(node.id, node, "variable")
        elif isinstance(node.ctx, ast.Del):
            binding = self.scope.lookup(node.id)
            if binding is not None:
                binding.used = True

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self.visit(target)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)
        self.visit(node.target)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            binding = self.scope.lookup(node.target.id)
            if binding is not None:
                binding.used = True
            self.visit(node.value)
            self._bind(node.target.id, node.target, "variable")
        else:
            self.visit(node.target)
            self.visit(node.value)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        old_scope = self.scope
        while self.scope.kind == "comprehension" and self.scope.parent is not None:
            self.scope = self.scope.parent
        self.visit(node.target)
        self.scope = old_scope

    def visit_For(self, node: ast.For) -> None:
        self.visit(node.iter)
        self.visit(node.target)
        for statement in node.body:
            self.visit(statement)
        for statement in node.orelse:
            self.visit(statement)

    visit_AsyncFor = visit_For

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        for statement in node.body:
            self.visit(statement)
        for statement in node.orelse:
            self.visit(statement)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            bound_name = alias.asname or alias.name.split(".", 1)[0]
            self._bind(bound_name, node, "import")
            self.analysis.imports.append(ImportRef(alias.name, bound_name, node, node.lineno))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module == "__future__":
            return
        module = node.module or ""
        prefix = "." * node.level + module
        for alias in node.names:
            if alias.name == "*":
                self.analysis.imports.append(ImportRef(prefix, None, node, node.lineno, True))
                continue
            bound_name = alias.asname or alias.name
            self._bind(bound_name, node, "import")
            target = prefix
            self.analysis.imports.append(ImportRef(target, bound_name, node, node.lineno))

    def visit_Global(self, node: ast.Global) -> None:
        self.scope.global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.scope.nonlocal_names.update(node.names)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in {"globals", "locals", "eval", "exec"}:
            self.analysis.dynamic_module_names = True
            for bindings in self.analysis.root_scope.bindings.values():
                for binding in bindings:
                    binding.used = True
            for bindings in self.scope.bindings.values():
                for binding in bindings:
                    binding.used = True
        self.generic_visit(node)

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node, node.elt, None)

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node, node.elt, None)

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node, node.elt, None)

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node, node.key, node.value)

    def _visit_comprehension(
        self, node: ast.AST, first_value: ast.expr, second_value: ast.expr | None
    ) -> None:
        generators = getattr(node, "generators")
        if generators:
            self.visit(generators[0].iter)
        old_scope = self.scope
        self.scope = self._new_scope("comprehension", node)
        for index, generator in enumerate(generators):
            if index:
                self.visit(generator.iter)
            self.visit(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        self.visit(first_value)
        if second_value is not None:
            self.visit(second_value)
        self.scope = old_scope

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is not None:
            self.visit(node.type)
        if node.name:
            self._bind(node.name, node, "variable")
        for statement in node.body:
            self.visit(statement)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.pattern is not None:
            self.visit(node.pattern)
        if node.name:
            self._bind(node.name, node, "variable")

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name:
            self._bind(node.name, node, "variable")

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        for key in node.keys:
            self.visit(key)
        for pattern in node.patterns:
            self.visit(pattern)
        if node.rest:
            self._bind(node.rest, node, "variable")


def parse_file(path: Path, root: Path) -> FileAnalysis:
    """Read and parse source without importing or executing it."""
    root = root.resolve()
    try:
        with tokenize.open(path) as stream:
            source = stream.read()
    except (OSError, UnicodeError, SyntaxError) as exc:
        source = ""
        err = f"unable to read source: {exc}"
        root_scope = Scope("module", ast.Module(body=[], type_ignores=[]))
        return FileAnalysis(path, _display_path(path, root), source, None,
                            module_name_for(path, root), root_scope, parse_error=err)

    module_name = module_name_for(path, root)
    root_scope = Scope("module", ast.Module(body=[], type_ignores=[]))
    analysis = FileAnalysis(
        path=path,
        display_path=_display_path(path, root),
        source=source,
        tree=None,
        module_name=module_name,
        root_scope=root_scope,
        scopes=[root_scope],
        suppressions=_suppression_comments(source),
    )
    try:
        tree = ast.parse(source, filename=str(path), type_comments=True)
    except SyntaxError as exc:
        analysis.parse_error = f"{exc.msg}"
        analysis.parse_error_line = max(1, exc.lineno or 1)
        analysis.parse_error_column = max(1, exc.offset or 1)
        analysis.tree = None
        return analysis
    analysis.tree = tree
    analysis.root_scope.node = tree
    collector = ScopeCollector(analysis)
    collector.visit(tree)
    if analysis.dynamic_module_names:
        for scope in analysis.scopes:
            for bindings in scope.bindings.values():
                for binding in bindings:
                    binding.used = True
    _apply_all_exports(analysis)
    return analysis


def _display_path(path: Path, root: Path) -> str:
    if root.is_file():
        return path.name
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _apply_all_exports(analysis: FileAnalysis) -> None:
    """Treat statically listed ``__all__`` names as public uses."""
    if analysis.tree is None:
        return
    exports: set[str] = set()
    dynamic = False
    for statement in analysis.tree.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
                continue
            value = getattr(statement, "value", None)
            if value is None:
                dynamic = True
                continue
            try:
                values = ast.literal_eval(value)
            except (ValueError, TypeError):
                dynamic = True
                continue
            if isinstance(values, (list, tuple, set)) and all(isinstance(item, str) for item in values):
                exports.update(values)
            else:
                dynamic = True
    if dynamic:
        for bindings in analysis.root_scope.bindings.values():
            for binding in bindings:
                binding.used = True
    else:
        for name in exports:
            found = analysis.root_scope.bindings.get(name, [])
            if found:
                found[-1].used = True
