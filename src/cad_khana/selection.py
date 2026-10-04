"""Select a subset of one run: claims by name glob, parts by tree path.

Pure. ``khana check --only`` narrows the claims ``hold`` evaluates;
``khana view --only/--hide`` narrows the parts ``viewer.push`` sends.
A selection that names nothing is an error, not an empty run: a typo'd
glob that evaluated zero claims and exited 0 would be the vacuous green
this tool exists to prevent.
"""

from __future__ import annotations

from difflib import get_close_matches
from fnmatch import fnmatchcase


class SelectionError(ValueError):
    """A selection that matches nothing — a usage error at the CLI."""


def claims(names: tuple[str, ...], patterns: tuple[str, ...]) -> tuple[bool, ...]:
    """Which of ``names`` match any of ``patterns`` (``fnmatch`` globs,
    case-sensitive). Every pattern must match at least one name, so one
    typo among several is caught rather than silently evaluating less."""
    unmatched = tuple(p for p in patterns if not any(fnmatchcase(n, p) for n in names))
    if unmatched:
        raise SelectionError(
            f"no assertion matches {', '.join(map(repr, unmatched))} "
            f"(of {len(names)} declared; globs are fnmatch, case-sensitive)"
        )
    return tuple(any(fnmatchcase(n, p) for p in patterns) for n in names)


def _under(name: str, path: str) -> bool:
    return name == path or name.startswith(path + ".")


def _groups(names: tuple[str, ...]) -> tuple[str, ...]:
    """Every part path and every sub-assembly path above one."""
    return tuple(
        dict.fromkeys(
            ".".join(segments[:i])
            for segments in (n.split(".") for n in names)
            for i in range(1, len(segments) + 1)
        )
    )


def _check_known(names: tuple[str, ...], selected: tuple[str, ...]) -> None:
    known = _groups(names)
    unknown = tuple(p for p in selected if p not in known)
    if unknown:
        raise SelectionError(
            "; ".join(
                f"no part or sub-assembly at {p!r}"
                + (
                    f" — close: {', '.join(close)}"
                    if (close := get_close_matches(p, known, n=3))
                    else ""
                )
                for p in unknown
            )
        )


def paths(
    names: tuple[str, ...],
    only: tuple[str, ...] = (),
    hide: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """The part paths under any of ``only`` (all of them when empty) and
    under none of ``hide``, in their original order. A path names a part
    or a whole sub-assembly: ``s1`` is every part below ``s1``, never
    ``s10``."""
    _check_known(names, only + hide)
    kept = tuple(
        n
        for n in names
        if (not only or any(_under(n, p) for p in only))
        and not any(_under(n, p) for p in hide)
    )
    if not kept:
        raise SelectionError("the selection leaves nothing to show")
    return kept
