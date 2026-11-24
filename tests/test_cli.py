"""CLI integration coverage for cross-file diagnostics and formats."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "codelens", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_reports_exact_circular_import_and_exit_code(tmp_path: Path):
    (tmp_path / "a.py").write_text("from b import value\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from a import other\n", encoding="utf-8")
    result = _run_cli(str(tmp_path), "--rules", "CL005")
    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout == (
        "a.py:1:1  ERROR  CL005  circular import: a -> b -> a\n"
        "Summary: 1 error(s), 0 warning(s), 0 info item(s).\n"
    )


def test_cli_json_contains_diagnostics_summary_and_clean_exit(tmp_path: Path):
    (tmp_path / "clean.py").write_text("value = 1\nprint(value)\n", encoding="utf-8")
    result = _run_cli(str(tmp_path), "--format", "json")
    assert result.returncode == 0
    assert result.stdout == (
        '{\n  "diagnostics": [],\n  "summary": {\n'
        '    "error": 0,\n    "info": 0,\n    "warning": 0\n  }\n}\n'
    )


def test_cli_unknown_rule_is_tool_error(tmp_path: Path):
    result = _run_cli(str(tmp_path), "--rules", "CL999")
    assert result.returncode == 2
    assert result.stdout == ""
    assert "unknown rule id(s): CL999" in result.stderr
