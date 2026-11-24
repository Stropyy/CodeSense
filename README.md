# CodeLens

CodeLens is a static analyzer for Python 3.10+ projects. It parses source with
`ast`, builds a lightweight scope index and project import graph, and reports
maintainability diagnostics. It never imports or executes the analyzed code.
The core uses only the Python standard library.

## Install

```bash
python -m pip install .
```

For development and tests:

```bash
python -m pip install '.[test]'
pytest
```

## Usage

```bash
codelens src/
codelens src/ --severity info --format json
codelens . --rules CL001,CL005 --ignore CL002 --exclude build,generated
codelens . --config codelens.json --max-complexity 12
```

The input can be a `.py` file or a directory. Directory scans recurse through
Python files and exclude `venv`, `.venv`, and `__pycache__` by default. Supply
`--exclude` more than once or separate patterns with commas. Patterns match a
path, a glob, or any path component.

`--severity` is the minimum severity to show and use for the exit status. The
default is `warning`. Exit codes are `0` when no displayed issues remain, `1`
when one or more issues meet the threshold, and `2` for usage, configuration,
or input errors. Syntax errors are reported as `PARSE_ERROR`; analysis
continues with other files.

Text output is sorted by file, line, and column. Severity colors appear when
writing to a terminal. JSON output contains a `diagnostics` array and severity
counts in `summary`:

```text
src/example.py:8:5  WARNING  CL001  variable 'temporary' is assigned but never used
Summary: 0 error(s), 1 warning(s), 0 info item(s).
```

```json
{
  "diagnostics": [
    {
      "column": 5,
      "file": "src/example.py",
      "line": 8,
      "message": "variable 'temporary' is assigned but never used",
      "rule_id": "CL001",
      "severity": "warning"
    }
  ],
  "summary": {"error": 0, "info": 0, "warning": 1}
}
```

Inline comments suppress diagnostics on that source line. One or more ids can
be listed, or `ALL` can suppress every rule on the line:

```python
temporary = calculate()  # codelens: ignore[CL001]
value = third_party_call()  # codelens: ignore[CL001, CL006]
```

### Configuration

Configuration is JSON. Command-line thresholds override matching config
values. Supported keys are `exclude`, `severity`, `max_complexity`,
`max_function_lines`, `max_nesting_depth`, `max_parameters`, and `rules` for
severity overrides.

```json
{
  "exclude": ["build", "*_generated.py"],
  "severity": "warning",
  "max_complexity": 10,
  "max_function_lines": 50,
  "max_nesting_depth": 4,
  "max_parameters": 5,
  "rules": {"CL009": "info", "CL012": {"severity": "error"}}
}
```

## Rule reference

There are exactly 14 built-in rules. Defaults are warnings unless noted.
Thresholds use strict greater-than comparisons: a value equal to the limit is
allowed.

| ID | Default | Detection | Limitations |
| --- | --- | --- | --- |
| CL001 | warning | Assigned local, module, class, or comprehension variables that have no statically resolved load. | Names beginning with `_` are treated as intentionally unused. Attributes and dynamically constructed names are not resolved. A file containing `globals()`, `locals()`, `eval()`, or `exec()` suppresses unused-name findings because those calls can inspect names dynamically. |
| CL002 | warning | Imported names with no statically resolved load. | Star imports have no individually trackable names. Static `__all__` exports count as use; dynamic `__all__` suppresses module-level unused names. Dynamic attribute access such as `getattr(module, name)` cannot be resolved. |
| CL003 | warning | Function, async-function, and lambda arguments with no statically resolved load. | `_`-prefixed names and conventional `self`/`cls` are ignored. A file containing `globals()`, `locals()`, `eval()`, or `exec()` suppresses unused-name findings because reflective access cannot be modeled. |
| CL004 | warning | Statements after unconditional return, raise, break, or continue; literal-false suites; and statements after a constant-true loop with no loop-targeting break. | Control-flow is conservative. It does not evaluate arbitrary conditions, and exception behavior or complex `finally` blocks can make reachability uncertain. |
| CL005 | error | Cycles in the project-wide import graph, including resolvable relative imports. | Conditional imports are all treated as possible edges. Imports assembled dynamically and external packages are outside the graph. A cycle is reported once at a stable edge in the cycle. |
| CL006 | warning | Function cyclomatic complexity above `--max-complexity` (default 10). Counts branches, handlers, boolean operators, comprehensions, and match cases. | This is a source-structure estimate; it does not model runtime short-circuit outcomes or generated code. Nested functions are measured separately. |
| CL007 | warning | `except:` clauses that catch every exception. | Does not assess whether a broad typed handler (such as `except Exception`) is appropriate. |
| CL008 | warning | List, dict, or set literals and empty `list()`, `dict()`, or `set()` calls used as defaults. | Other mutable objects constructed by factories or custom calls are not recognized. |
| CL009 | warning | Functions spanning more than `--max-function-lines` (default 50) source lines. | Counts the AST line span, including blank/comment lines and nested definitions; it does not measure executable statements. |
| CL010 | warning | Control-flow nesting beyond `--max-nesting-depth` (default 4). | Counts `if`, loops, `try`, `with`, and `match`; helper functions/classes and comprehensions are handled separately or omitted. |
| CL011 | warning | Functions with more than `--max-parameters` (default 5), excluding a leading `self` or `cls`. | Counts positional-only, positional, keyword-only, `*args`, and `**kwargs` parameters equally. It does not assess parameter cohesion. |
| CL012 | error | Repeated literal/hashable keys in a dictionary literal. | Only keys understood by `ast.literal_eval` are checked; computed expressions and keys produced by `**mapping` are unknown. |
| CL013 | warning | Functions with a value return that can also fall through without a value return. Raises count as terminating paths. | This is a conservative control-flow approximation. It skips generators and functions that only return `None`; implicit `None` may be intentional. |
| CL014 | warning | Variables, arguments, definitions, or imports whose names shadow Python builtins. | Some APIs intentionally use builtin names. Bindings are checked in every scope, including method parameters. |

## Static-analysis behavior

The parser uses `ast.parse` and never imports the target package. Syntax-invalid
files receive a `PARSE_ERROR` diagnostic and do not prevent other files from
being analyzed. Nested functions and closures use lexical name resolution;
class namespaces are skipped when resolving names from methods. Comprehensions
have their own scope for iteration variables. `__all__` is understood when it
is a literal list, tuple, or set of strings. A file with `globals()`,
`locals()`, `eval()`, or `exec()` suppresses unused-name checks throughout
that file to avoid misleading results from reflection. `getattr` calls and
other dynamic name construction are not evaluated. Conditional imports are
included in the graph, so mutually exclusive branches can produce conservative
cycle reports.

## Project layout

```text
pyproject.toml
README.md
src/codelens/
  __init__.py
  __main__.py
  cli.py
  config.py
  discovery.py
  engine.py
  model.py
  parser.py
  rules/
    __init__.py
    base.py
    flow.py
    project.py
    structure.py
tests/
```

## Adding a rule

Create a class in a `codelens.rules` module that subclasses `Rule`, defines a
unique id, a name and default severity, and implements `check(context)` to
return `Diagnostic` objects. Decorate the class with `@register`; import a new
module from `rules/__init__.py` so it is loaded with the built-in rules. Use
`emit()` to apply severity overrides and build correctly located diagnostics.
The engine discovers registered rules and does not need rule-specific changes.

```python
from codelens.model import Diagnostic, RuleContext, Severity
from codelens.rules.base import Rule, emit, files_with_trees, register


@register
class ExampleRule(Rule):
    id = "CL015"
    name = "example check"
    default_severity = Severity.INFO

    def check(self, context: RuleContext) -> list[Diagnostic]:
        diagnostics = []
        for file in files_with_trees(context.project):
            # Inspect file.tree without importing or executing its source.
            pass
        return diagnostics
```