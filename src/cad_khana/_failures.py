"""Script-scoped collection of failed diagnostic runs.

`check()` and `inspect()` raise on an unwaived failure, so one red part
aborts a script before the rest have written their JSON — a sweep across
many parts is impossible in one run, and the stale files left behind read
as current. Deferral turns that into: record the failure, let the script
finish so every diagnostics file on disk is fresh, raise once at the end.

The decision to defer belongs to the boundary, never to the library —
same rule as the export/viewer/draw toggles. Deferring is only safe where
something is still in a position to exit nonzero afterwards, and that is
the CLI. `atexit` is not: a `SystemExit` raised from an exit handler is
reported as "Exception ignored" and the process still exits 0 (measured,
CPython 3.13), which would trade an early abort for a silent green run —
the worse failure for a diagnostics-first tool. So a script run under a
bare interpreter keeps today's raise-on-first-failure behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Failure:
    """One diagnostic run that ended with an unwaived assertion failure.

    The per-failure detail has already gone to stderr at the call site;
    this is what the boundary needs to roll them up and point at the JSON.
    """

    name: str
    diagnostics: Path


_deferring = False
_collected: tuple[Failure, ...] = ()


def defer() -> None:
    """Start collecting failures instead of raising on the first one."""
    global _deferring, _collected
    _deferring, _collected = True, ()


def take() -> tuple[Failure, ...]:
    """Stop deferring and hand back everything collected."""
    global _deferring, _collected
    collected, _deferring, _collected = _collected, False, ()
    return collected


def fail(failure: Failure) -> None:
    """Report a failed run — raise now, or record it for the boundary."""
    global _collected
    if not _deferring:
        raise SystemExit(1)
    _collected += (failure,)
