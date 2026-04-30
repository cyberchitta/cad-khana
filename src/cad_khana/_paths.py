"""Resolve user-supplied ``out=`` paths relative to the running script."""

from __future__ import annotations

import sys
from pathlib import Path


def resolve_out(out: str | Path) -> Path:
    """Resolve an ``out=`` path against the running script's directory.

    Absolute paths are returned unchanged. Relative paths are anchored to
    ``sys.modules['__main__'].__file__``'s directory when set — true for both
    ``python <script>`` and ``runpy.run_path(..., run_name='__main__')`` (how
    ``khana`` invokes user scripts) — so ``out="outputs"`` lands next to the
    script regardless of the cwd it was launched from. Falls back to a
    cwd-relative ``Path`` when no ``__main__`` file is set (e.g. REPL).
    """
    p = Path(out)
    if p.is_absolute():
        return p
    main_file = getattr(sys.modules.get("__main__"), "__file__", None)
    if main_file is None:
        return p
    return Path(main_file).resolve().parent / p
