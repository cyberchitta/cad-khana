from __future__ import annotations

import re
from re import Pattern

_PATTERNS: tuple[tuple[Pattern[str], str], ...] = (
    (
        re.compile(r"NoneType.*has no attribute 'part'"),
        "Missing .part accessor — use `with BuildPart() as p: ...; return p.part`.",
    ),
    (
        re.compile(r"has no attribute 'volume'"),
        "`a & b` returns None when solids don't overlap; guard with "
        "`if inter is None` or use assert_no_interference() instead of bare &.",
    ),
    (
        re.compile(r"TypeError.*Location"),
        "Location takes a position tuple: Location((x, y, z)) or "
        "Location((x, y, z), (rx, ry, rz)).",
    ),
    (
        re.compile(r"BRep_API: command not done|BRepAlgo_BooleanOperation"),
        "OCCT boolean operation failed. Check that both solids are valid and "
        "non-degenerate; try adjusting tolerances or simplifying geometry.",
    ),
    (
        re.compile(r"StdFail_NotDone"),
        "OCCT fillet/chamfer failed. The radius may be too large for the "
        "selected edges. Try a smaller radius or fewer edges.",
    ),
    (
        re.compile(r"No module named"),
        "Import not found. User scripts may import from build123d, bd_warehouse, "
        "and cad_khana. Other modules are not available unless installed in the "
        "khana environment.",
    ),
)


def match_hint(error_text: str) -> str | None:
    return next(
        (hint for pat, hint in _PATTERNS if pat.search(error_text)),
        None,
    )
