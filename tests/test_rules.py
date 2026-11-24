"""Rule-level regression tests, with both triggering and clean examples."""

from __future__ import annotations

from pathlib import Path

import pytest

from codelens.engine import analyze_project
from codelens.model import AnalysisConfig
from codelens.rules.base import RULE_REGISTRY


@pytest.mark.parametrize(
    ("rule_id", "bad", "good", "config"),
    [
        ("CL001", "def f():\n    unused = 1\n    return 2\n", "def f():\n    value = 1\n    return value\n", {}),
        ("CL002", "import math\n", "import math\nmath.sqrt(4)\n", {}),
        ("CL003", "def f(unused):\n    return 1\n", "def f(value):\n    return value\n", {}),
        ("CL004", "def f():\n    return 1\n    later()\n", "def f():\n    value = 1\n    return value\n", {}),
        ("CL006", "def f(a, b):\n    if a:\n        pass\n    if b:\n        pass\n    return 0\n", "def f(a):\n    if a:\n        return 1\n    return 0\n", {"max_complexity": 2}),
        ("CL007", "def f():\n    try:\n        pass\n    except:\n        pass\n", "def f():\n    try:\n        pass\n    except Exception:\n        pass\n", {}),
        ("CL008", "def f(value=[]):\n    return value\n", "def f(value=()):\n    return value\n", {}),
        ("CL009", "def f():\n    one = 1\n    two = 2\n    return one + two\n", "def f():\n    return 1\n", {"max_function_lines": 3}),
        ("CL010", "def f(a, b):\n    if a:\n        if b:\n            return 1\n    return 0\n", "def f(a):\n    if a:\n        return 1\n    return 0\n", {"max_nesting_depth": 1}),
        ("CL011", "def f(a, b, c):\n    return a + b + c\n", "def f(a, b):\n    return a + b\n", {"max_parameters": 2}),
        ("CL012", "value = {'x': 1, 'x': 2}\n", "value = {'x': 1, 'y': 2}\n", {}),
        ("CL013", "def f(flag):\n    if flag:\n        return 1\n", "def f(flag):\n    if flag:\n        return 1\n    else:\n        return 2\n", {}),
        ("CL014", "list = []\n", "items = []\n", {}),
    ],
)
def test_each_file_rule_has_triggering_and_clean_examples(tmp_path: Path, rule_id, bad, good, config):
    source = tmp_path / "sample.py"
    source.write_text(bad, encoding="utf-8")
    diagnostics = analyze_project(source, config=AnalysisConfig(**config), rule_ids={rule_id})
    assert [item.rule_id for item in diagnostics] == [rule_id]

    source.write_text(good, encoding="utf-8")
    assert analyze_project(source, config=AnalysisConfig(**config), rule_ids={rule_id}) == []


def test_builtin_registry_contains_exactly_fourteen_rules():
    assert len(RULE_REGISTRY) == 14
    assert set(RULE_REGISTRY) == {f"CL{number:03}" for number in range(1, 15)}


def test_circular_import_rule_has_cycle_and_acyclic_cases(tmp_path: Path):
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("from b import value\n", encoding="utf-8")
    b.write_text("from a import other\n", encoding="utf-8")
    assert [item.rule_id for item in analyze_project(tmp_path, rule_ids={"CL005"})] == ["CL005"]

    b.write_text("value = 3\n", encoding="utf-8")
    assert analyze_project(tmp_path, rule_ids={"CL005"}) == []


def test_all_rule_ids_are_documented_by_registry():
    assert set(RULE_REGISTRY) == {
        "CL001", "CL002", "CL003", "CL004", "CL005", "CL006", "CL007",
        "CL008", "CL009", "CL010", "CL011", "CL012", "CL013", "CL014",
    }
