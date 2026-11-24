"""Deterministic recursive Python file discovery."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from collections.abc import Iterable


DEFAULT_EXCLUDES = ("venv", ".venv", "__pycache__")


def discover_python_files(root: Path, excludes: Iterable[str] = ()) -> list[Path]:
    """Return sorted ``.py`` files, skipping matching paths and directories.

    An exclude may match a component name (for example ``venv``), a glob
    (``*_generated.py``), or a root-relative path (``build/**``).
    """
    if root.is_file():
        if root.suffix != ".py":
            raise ValueError(f"input file is not a Python source file: {root}")
        return [root.resolve()]
    if not root.is_dir():
        raise ValueError(f"path does not exist or is not a directory: {root}")

    patterns = tuple(DEFAULT_EXCLUDES) + tuple(excludes)
    base = root.resolve()
    found: list[Path] = []
    for candidate in base.rglob("*.py"):
        relative = candidate.relative_to(base).as_posix()
        parts = candidate.relative_to(base).parts
        if any(
            fnmatch.fnmatchcase(relative, pattern)
            or any(fnmatch.fnmatchcase(part, pattern) for part in parts)
            for pattern in patterns
        ):
            continue
        if candidate.is_file():
            found.append(candidate.resolve())
    return sorted(found, key=lambda path: path.as_posix())
