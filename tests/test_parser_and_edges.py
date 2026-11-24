"""Parsing, scope, suppression, and conservative dynamic-feature behavior."""

from pathlib import Path

from codelens.engine import analyze_project


def test_syntax_error_is_reported_and_other_files_are_still_analyzed(tmp_path: Path):
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (tmp_path / "clean.py").write_text("value = 1\nprint(value)\n", encoding="utf-8")
    results = analyze_project(tmp_path, rule_ids={"CL001"})
    assert [(item.file, item.rule_id) for item in results] == [("broken.py", "PARSE_ERROR")]


def test_empty_file_is_clean(tmp_path: Path):
    source = tmp_path / "empty.py"
    source.write_text("", encoding="utf-8")
    assert analyze_project(source) == []


def test_closures_decorators_async_match_comprehensions_and_star_import(tmp_path: Path):
    source = tmp_path / "edges.py"
    source.write_text(
        """from math import *
from math import sqrt
__all__ = ["sqrt"]
if True:
    from os import path
    path.exists(".")
def decorate(fn):
    return fn
@decorate
async def fetch(_unused, value):
    captured = value
    def inner():
        return captured
    values = [item for item in range(3)]
    match values:
        case []:
            return await inner()
        case _:
            return len(values)
""",
        encoding="utf-8",
    )
    ids = {"CL001", "CL002", "CL003", "CL004", "CL013"}
    assert analyze_project(source, rule_ids=ids) == []


def test_try_finally_preserves_unreachable_tail_detection(tmp_path: Path):
    source = tmp_path / "flow.py"
    source.write_text(
        "def f():\n    try:\n        return 1\n    finally:\n        cleanup()\n    after = 2\n",
        encoding="utf-8",
    )
    results = analyze_project(source, rule_ids={"CL004"})
    assert [(item.line, item.rule_id) for item in results] == [(6, "CL004")]


def test_match_wildcard_is_exhaustive_for_missing_return(tmp_path: Path):
    source = tmp_path / "match.py"
    source.write_text("def f(value):\n    match value:\n        case _:\n            return 1\n", encoding="utf-8")
    assert analyze_project(source, rule_ids={"CL013"}) == []


def test_globals_suppresses_unused_name_warnings_filewide(tmp_path: Path):
    source = tmp_path / "dynamic.py"
    source.write_text("import math\ndef f():\n    local = 1\n    return globals()\n", encoding="utf-8")
    assert analyze_project(source, rule_ids={"CL001", "CL002", "CL003"}) == []


def test_getattr_is_not_interpreted_as_a_name_use(tmp_path: Path):
    source = tmp_path / "getattr_case.py"
    source.write_text("from math import sqrt\ngetattr(math, 'sqrt')\n", encoding="utf-8")
    results = analyze_project(source, rule_ids={"CL002"})
    assert [item.message for item in results] == ["import 'sqrt' is never used"]


def test_relative_import_cycle_inside_a_package(tmp_path: Path):
    package = tmp_path / "samplepkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "a.py").write_text("from .b import value\n", encoding="utf-8")
    (package / "b.py").write_text("from .a import other\n", encoding="utf-8")
    results = analyze_project(package, rule_ids={"CL005"})
    assert len(results) == 1
    assert results[0].file == "a.py"
    assert results[0].message == "circular import: samplepkg.a -> samplepkg.b -> samplepkg.a"


def test_annotations_and_future_imports_are_not_reported_unused(tmp_path: Path):
    source = tmp_path / "annotations.py"
    source.write_text(
        "from __future__ import annotations\nfrom typing import Any\ndef f(value: Any) -> Any:\n    return value\n",
        encoding="utf-8",
    )
    assert analyze_project(source, rule_ids={"CL002"}) == []


def test_literal_false_conditions_and_constant_true_loops(tmp_path: Path):
    source = tmp_path / "constants.py"
    source.write_text(
        "def f():\n    if 0:\n        never()\n    while 1:\n        continue\n    after()\n",
        encoding="utf-8",
    )
    results = analyze_project(source, rule_ids={"CL004"})
    assert [(item.line, item.message) for item in results] == [
        (3, "statement is in a constant-false branch"),
        (6, "statement is unreachable"),
    ]


def test_diagnostic_column_counts_unicode_characters(tmp_path: Path):
    source = tmp_path / "unicode.py"
    source.write_text("é; unused = 2\n", encoding="utf-8")
    results = analyze_project(source, rule_ids={"CL001"})
    assert results[0].column == 4


def test_assignment_and_loop_evaluation_order_preserves_name_uses(tmp_path: Path):
    source = tmp_path / "order.py"
    source.write_text(
        "def update(value):\n    value = value + 1\n    return value\n\ndef iterate(item):\n    for item in item:\n        pass\n",
        encoding="utf-8",
    )
    results = analyze_project(source, rule_ids={"CL001", "CL003"})
    assert [(item.rule_id, item.message) for item in results] == [
        ("CL001", "variable 'item' is assigned but never used")
    ]


def test_conditional_imports_are_included_in_cycle_graph(tmp_path: Path):
    (tmp_path / "a.py").write_text("if TYPE_CHECKING:\n    from b import value\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from a import something\nvalue = 1\n", encoding="utf-8")
    results = analyze_project(tmp_path, rule_ids={"CL005"})
    assert len(results) == 1
    assert results[0].rule_id == "CL005"


def test_circular_import_location_uses_indented_import_column(tmp_path: Path):
    (tmp_path / "a.py").write_text("if True:\n    from b import value\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from a import something\n", encoding="utf-8")
    result = analyze_project(tmp_path, rule_ids={"CL005"})[0]
    assert (result.file, result.line, result.column) == ("a.py", 2, 5)


def test_inline_suppression_is_line_local_and_accepts_multiple_ids(tmp_path: Path):
    source = tmp_path / "suppress.py"
    source.write_text(
        "first = 1  # codelens: ignore[CL001, CL014]\nsecond = 2\n",
        encoding="utf-8",
    )
    results = analyze_project(source, rule_ids={"CL001"})
    assert [(item.line, item.message) for item in results] == [
        (2, "variable 'second' is assigned but never used")
    ]


def test_excluded_directories_are_not_discovered(tmp_path: Path):
    (tmp_path / "app.py").write_text("", encoding="utf-8")
    (tmp_path / "skip").mkdir()
    (tmp_path / "skip" / "bad.py").write_text("def bad(:\n", encoding="utf-8")
    assert analyze_project(tmp_path, excludes=["skip"]) == []
