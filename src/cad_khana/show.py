"""Read one diagnostics JSON: a summary, then its assertions filtered.

Pure — takes the parsed file, returns text or data; ``khana show`` does
the reading and the printing. A reader compares nothing, so unlike
``diff`` it reads a file at any ``schema_version`` and says which one
it read rather than refusing it: the fields are shown as written, and
one the file's schema lacks reads ``absent`` rather than a default.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from typing import Any

from cad_khana.diff import file_kind
from cad_khana.mechanism.diagnostics import SCHEMA_VERSION

Diag = dict[str, Any]

STATES = ("passed", "failed", "waived", "skipped")
MARKERS = {"passed": "ok", "failed": "FAIL", "waived": "waived", "skipped": "skip"}
UNMATCHED = "(unmatched)"
DEFAULT_LIMIT = 50
ABSENT = "absent"
DETAIL_WIDTH = 100


def require_diagnostics(diag: Any) -> Diag:
    if not (
        isinstance(diag, dict)
        and "schema_version" in diag
        and isinstance(diag.get("assertions"), list)
    ):
        raise ValueError(
            "not a cad-khana diagnostics file "
            "(no schema_version or assertions list)"
        )
    return diag


def state(assertion: Diag) -> str:
    passed = assertion["passed"]
    return (
        "skipped"
        if passed is None
        else "passed"
        if passed
        else "waived"
        if assertion.get("waived")
        else "failed"
    )


def select(
    assertions: Iterable[Diag],
    *,
    grep: str | None = None,
    states: frozenset[str] = frozenset(),
) -> list[Diag]:
    """Assertions whose name matches ``grep`` (a regex search) and whose
    state is one of ``states``; an empty ``states`` admits every state."""
    pattern = re.compile(grep) if grep else None
    return [
        a
        for a in assertions
        if (pattern is None or pattern.search(a["name"]))
        and (not states or state(a) in states)
    ]


def _number(value: Any) -> float | None:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _value_key(value: Any) -> tuple[bool, float]:
    number = _number(value)
    return (number is None, number or 0.0)


def by_value(assertions: Iterable[Diag]) -> list[Diag]:
    """Ascending ``value``; claims that record none come last."""
    return sorted(assertions, key=lambda a: _value_key(a.get("value")))


@dataclass(frozen=True)
class Group:
    key: str
    count: int
    failed: int
    waived: int
    skipped: int
    min_value: float | None
    min_name: str | None


def _group_key(pattern: re.Pattern[str], name: str) -> str:
    match = pattern.search(name)
    return (
        UNMATCHED
        if match is None
        else match.group(1) if pattern.groups else match.group(0)
    )


def _group(key: str, members: list[Diag]) -> Group:
    states = Counter(state(a) for a in members)
    valued = [a for a in members if _number(a.get("value")) is not None]
    least = min(valued, key=lambda a: _number(a["value"])) if valued else None
    return Group(
        key=key,
        count=len(members),
        failed=states["failed"],
        waived=states["waived"],
        skipped=states["skipped"],
        min_value=None if least is None else _number(least["value"]),
        min_name=None if least is None else least["name"],
    )


def group(assertions: Iterable[Diag], pattern: str) -> list[Group]:
    """One ``Group`` per distinct key, in order of first appearance. The
    key is the pattern's first capture group, or its whole match when it
    has none; names it misses share the key ``(unmatched)``."""
    compiled = re.compile(pattern)
    members: dict[str, list[Diag]] = {}
    for a in assertions:
        members.setdefault(_group_key(compiled, a["name"]), []).append(a)
    return [_group(key, found) for key, found in members.items()]


# --- text -----------------------------------------------------------------


def _fmt(value: Any) -> str:
    number = _number(value)
    return "-" if number is None else f"{number:.4g}"


def _clip(text: str, width: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def row(assertion: Diag, width: int = DETAIL_WIDTH) -> str:
    detail = assertion.get("detail")
    return (
        f"{MARKERS[state(assertion)]:<6} {_fmt(assertion.get('value')):>10}  "
        f"{assertion['name']}"
        + (f" — {_clip(detail, width)}" if detail else "")
    )


def group_row(g: Group) -> str:
    least = f" ({g.min_name})" if g.min_name else ""
    return (
        f"{g.key}  n={g.count} failed={g.failed} waived={g.waived} "
        f"skipped={g.skipped} min={_fmt(g.min_value)}{least}"
    )


def _counted(counts: Counter[str]) -> str:
    return ", ".join(f"{kind} {n}" for kind, n in counts.items())


def _header(diag: Diag) -> str:
    version = diag["schema_version"]
    schema = (
        f"schema {version}"
        if version == SCHEMA_VERSION
        else f"schema {version}, current {SCHEMA_VERSION} — fields read as "
        "written; re-run check/inspect for the current meanings"
    )
    return f"status: {diag.get('status')}  ({file_kind(diag)}, {schema})"


def _error_lines(diag: Diag) -> list[str]:
    error = diag.get("error")
    last = error.strip().splitlines()[-1] if error else None
    return [
        *([f"error: {last}"] if last else []),
        *([f"hint: {diag['hint']}"] if diag.get("hint") else []),
    ]


def _assertion_line(assertions: list[Diag]) -> str:
    states = Counter(state(a) for a in assertions)
    skips = Counter(
        a.get("skipped") or "unclassified" for a in assertions if state(a) == "skipped"
    )
    return (
        f"{len(assertions)} assertions: "
        + ", ".join(f"{states[s]} {s}" for s in STATES)
        + (f" ({_counted(skips)})" if skips else "")
    )


def _read(diag: Diag, key: str, render: Callable[[Any], str] = _fmt) -> str:
    """A field as rendered, or ``absent`` when an older schema lacks it —
    never a default, which would read as a measurement the file never made."""
    return render(diag[key]) if key in diag else ABSENT


def _overhang(field: str) -> Callable[[Any], str]:
    return lambda overhang: _fmt((overhang or {}).get(field))


def _count(items: Any) -> str:
    return str(len(items))


def _interferences(found: list[Diag] | None) -> str:
    return "not computed" if found is None else _count(found)


def _body_line(diag: Diag) -> str:
    if file_kind(diag) == "printability":
        return (
            f"printability: {diag.get('name')} ({diag.get('method')})  "
            f"min_wall_mm {_read(diag, 'min_wall_mm')}  "
            f"overhang area_mm2 {_read(diag, 'overhang', _overhang('area_mm2'))} "
            f"max_angle_deg {_read(diag, 'overhang', _overhang('max_angle_deg'))}  "
            f"solid_count {_read(diag, 'solid_count', str)}"
        )
    return (
        f"parts {_read(diag, 'parts', _count)}  "
        f"interferences {_read(diag, 'interferences', _interferences)}  "
        f"motions {_read(diag, 'motions', _count)}"
    )


def _selection_lines(diag: Diag) -> list[str]:
    selection = diag.get("selection")
    return (
        [
            f"partial run: {selection['evaluated']} of {selection['declared']} "
            f"assertions (only {', '.join(selection['only'])}) — not a "
            "whole-model result"
        ]
        if selection
        else []
    )


def _warnings(warnings: list[Diag]) -> str:
    counts = Counter(w["kind"] for w in warnings)
    return _counted(counts) if counts else "none"


def summary(diag: Diag) -> str:
    return "\n".join(
        [
            _header(diag),
            *_error_lines(diag),
            *_selection_lines(diag),
            _body_line(diag),
            _assertion_line(diag["assertions"]),
            f"warnings: {_read(diag, 'warnings', _warnings)}",
        ]
    )


def _limited(lines: list[str], limit: int) -> list[str]:
    return (
        lines
        if limit == 0 or len(lines) <= limit
        else [*lines[:limit], f"… {len(lines) - limit} more (--limit 0 for all)"]
    )


def _listing(
    assertions: list[Diag], sort: str | None, group_by: str | None
) -> list[Diag] | list[Group]:
    ordered = by_value(assertions) if sort == "value" else assertions
    if group_by is None:
        return ordered
    groups = group(ordered, group_by)
    return (
        sorted(groups, key=lambda g: _value_key(g.min_value))
        if sort == "value"
        else groups
    )


def report(
    diag: Diag,
    *,
    grep: str | None = None,
    states: frozenset[str] = frozenset(),
    sort: str | None = None,
    limit: int | None = None,
    group_by: str | None = None,
) -> str:
    """The summary, then one line per matching assertion (or per group),
    at most ``limit`` of them (default ``DEFAULT_LIMIT``; 0 for all)."""
    chosen = select(diag["assertions"], grep=grep, states=states)
    listing = _listing(chosen, sort, group_by)
    lines = [group_row(g) if group_by else row(g) for g in listing]
    body = (
        _limited(lines, DEFAULT_LIMIT if limit is None else limit)
        if lines
        else ["no matching assertions"]
    )
    return "\n".join([summary(diag), "", *body]) + "\n"


def report_json(
    diag: Diag,
    *,
    grep: str | None = None,
    states: frozenset[str] = frozenset(),
    sort: str | None = None,
    limit: int | None = None,
    group_by: str | None = None,
) -> str:
    """The matching assertions (or groups) as a JSON list, unlimited
    unless ``limit`` is given — it is for piping, not reading."""
    chosen = select(diag["assertions"], grep=grep, states=states)
    listing = _listing(chosen, sort, group_by)
    items = [asdict(g) if isinstance(g, Group) else g for g in listing]
    return json.dumps(items[:limit] if limit else items, indent=2) + "\n"
