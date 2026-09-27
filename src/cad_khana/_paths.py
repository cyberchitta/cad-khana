"""Resolve user-supplied ``out=`` paths relative to the running script."""

from __future__ import annotations

import sys
from pathlib import Path

# Set only by the CLI boundary (``khana run --out-root``), reset when the
# run ends — the same boundary-owned switch as ``_failures.defer``. A
# script under a bare interpreter never sees one.
_root: Path | None = None


def set_root(root: Path | None) -> None:
    """Redirect every relative ``out=`` under ``root`` (``None``: stop)."""
    global _root
    _root = root


def under_root(path: Path) -> Path:
    """Map an anchored ``out=`` directory under the run's output root.

    The mirrored part is the path relative to the cwd — the repo root an
    agent runs from — so two scripts' ``outputs/`` stay distinct under one
    root; an anchor outside the cwd mirrors its whole absolute path. With
    no root set the path comes back unchanged.
    """
    if _root is None:
        return path
    resolved, cwd = path.resolve(), Path.cwd().resolve()
    base = cwd if resolved.is_relative_to(cwd) else Path(resolved.anchor)
    return _root / resolved.relative_to(base)


def resolve_out(out: str | Path) -> Path:
    """Resolve an ``out=`` path against the running script's directory.

    Absolute paths are returned unchanged. Relative paths are anchored to
    ``sys.modules['__main__'].__file__``'s directory when set — true for both
    ``python <script>`` and ``runpy.run_path(..., run_name='__main__')`` (how
    ``khana`` invokes user scripts) — so ``out="outputs"`` lands next to the
    script regardless of the cwd it was launched from. Falls back to a
    cwd-relative ``Path`` when no ``__main__`` file is set (e.g. REPL). A
    relative path then moves under the run's output root, if one is set.
    """
    p = Path(out)
    if p.is_absolute():
        return p
    main_file = getattr(sys.modules.get("__main__"), "__file__", None)
    return under_root(p if main_file is None else Path(main_file).resolve().parent / p)
