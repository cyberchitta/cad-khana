from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from cad_khana.mechanism.diagnostics import SCHEMA_VERSION

Diag = dict[str, Any]

# The exact text returned when two diagnostics are equivalent. The CLI
# keys its exit code off this (0 = identical, 1 = differences).
NO_CHANGES = "no changes\n"


def _pct(old: float, new: float) -> str:
    if old == 0:
        return f"{old:.3g} → {new:.3g}"
    return f"{old:.3g} → {new:.3g} ({(new - old) / abs(old) * 100:+.1f}%)"


def _delta(old: Any, new: Any) -> str:
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return _pct(float(old), float(new))
    return f"{old} → {new}"


def file_kind(diag: Diag) -> str:
    return "printability" if "kind" in diag else "mechanism"


def _status_section(old: Diag, new: Diag) -> list[str]:
    return (
        [f"  {old.get('status')} → {new.get('status')}"]
        if old.get("status") != new.get("status")
        else []
    )


def _require_current_schema(old: Diag, new: Diag) -> None:
    ov, nv = old.get("schema_version"), new.get("schema_version")
    if ov != SCHEMA_VERSION or nv != SCHEMA_VERSION:
        raise ValueError(
            f"schema mismatch: expected {SCHEMA_VERSION}, "
            f"got old={ov} new={nv}; "
            "regenerate by re-running check/inspect"
        )


def _selected(diag: Diag) -> list[str] | None:
    selection = diag.get("selection")
    return None if selection is None else selection["only"]


def _require_same_selection(old: Diag, new: Diag) -> None:
    """A partial run holds a subset of the claims, so against a full run
    (or another subset) every claim it left out would read as removed
    and every interference as unknown. Two runs of one selection
    compare like for like."""
    before, after = _selected(old), _selected(new)
    if before != after:
        raise ValueError(
            "cannot diff a partial run against a different selection "
            f"(old only={before}, new only={after}): claims one run left out "
            "would read as removed; re-run both with the same --only, or "
            "both without"
        )


def _selection_section(old: Diag, new: Diag) -> list[str]:
    before, after = old.get("selection") or {}, new.get("selection") or {}
    return [
        f"  {field} {before[field]} → {after[field]}"
        for field in ("declared", "evaluated")
        if before and before[field] != after[field]
    ]


def _assertion_state(assertion: Diag) -> str:
    if assertion["passed"] is not None:
        return "passed" if assertion["passed"] else "failed"
    kind = assertion.get("skipped")
    return f"skipped ({kind})" if kind else "skipped"


def _waive_state(waived: str | None) -> str:
    return f"waived ({waived})" if waived else "unwaived"


def _value_moved(old: Any, new: Any) -> bool:
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return abs(float(old) - float(new)) > 1e-6
    return old != new


def _worst_pose(assertion: Diag) -> str:
    """Where a held assertion's value came from, when that is not the
    as-built pose — a drifting worst value usually moved poses too."""
    at = assertion.get("worst_at")
    return f" (worst at {at['motion']} t={at['t']:g})" if at else ""


def _assertions_section(old: list[Diag], new: list[Diag]) -> list[str]:
    old_map = {a["name"]: a for a in old}
    new_map = {a["name"]: a for a in new}
    common = old_map.keys() & new_map.keys()
    regressed = [
        f"  regressed: {name}"
        + (f" — {new_map[name]['detail']}" if new_map[name].get("detail") else "")
        for name in sorted(common)
        if old_map[name]["passed"] is True and new_map[name]["passed"] is False
    ]
    fixed = [
        f"  fixed: {name}"
        for name in sorted(common)
        if old_map[name]["passed"] is False and new_map[name]["passed"] is True
    ]
    # Transitions into or out of the skipped state (passed = null), or
    # between skip classes.
    skip_changed = [
        f"  changed: {name}"
        f" {_assertion_state(old_map[name])}"
        f" → {_assertion_state(new_map[name])}"
        for name in sorted(common)
        if _assertion_state(old_map[name]) != _assertion_state(new_map[name])
        and None in (old_map[name]["passed"], new_map[name]["passed"])
    ]
    # Recorded values (assert_distance / assert_scalar) that moved while
    # the pass/fail state stayed put — drift the boolean can't see.
    value_changed = [
        f"  changed: {name} value {_delta(old_map[name].get('value'), new_map[name].get('value'))}"
        f"{_worst_pose(new_map[name])}"
        for name in sorted(common)
        if old_map[name]["passed"] == new_map[name]["passed"]
        and _value_moved(old_map[name].get("value"), new_map[name].get("value"))
    ]
    # A claim folding several parts into one result: a selection that
    # shrank stays green, so the count is what shows it.
    measured_changed = [
        f"  changed: {name} measured {old_map[name].get('measured')}"
        f" → {new_map[name].get('measured')}"
        for name in sorted(common)
        if old_map[name].get("measured") != new_map[name].get("measured")
    ]
    waive_changed = [
        f"  changed: {name}"
        f" {_waive_state(old_map[name].get('waived'))}"
        f" → {_waive_state(new_map[name].get('waived'))}"
        for name in sorted(common)
        if old_map[name].get("waived") != new_map[name].get("waived")
    ]
    added = [
        f"  added: {name} ({_assertion_state(new_map[name])})"
        for name in sorted(new_map.keys() - old_map.keys())
    ]
    removed = [f"  removed: {name}" for name in sorted(old_map.keys() - new_map.keys())]
    return (
        regressed + fixed + skip_changed + value_changed + measured_changed
        + waive_changed + added + removed
    )


# --- Mechanism diff -----------------------------------------------------


_PART_SCALAR_FIELDS = ("volume_mm3", "surface_area_mm2")

# Numeric part fields (mm / mm² / mm³) compare within this absolute
# tolerance. Rebuilding the same geometry through a different (but
# mathematically equivalent) transform-composition order perturbs
# coordinates at the last-ulp level (~1e-13 mm observed); a real design
# change moves them by clearance-scale amounts (≥ 0.01 mm). Exact float
# equality would report the noise and bury the signal.
_PART_NUMERIC_TOLERANCE = 1e-6


def _numbers_close(old: Any, new: Any) -> bool:
    """Equality with ``_PART_NUMERIC_TOLERANCE`` on numbers, recursing
    through lists/dicts (bbox, center_of_mass). Non-numeric leaves fall
    back to exact equality."""
    if isinstance(old, bool) or isinstance(new, bool):
        return old == new
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return abs(float(old) - float(new)) <= _PART_NUMERIC_TOLERANCE
    if isinstance(old, list) and isinstance(new, list):
        return len(old) == len(new) and all(
            _numbers_close(o, n) for o, n in zip(old, new)
        )
    if isinstance(old, dict) and isinstance(new, dict):
        return old.keys() == new.keys() and all(
            _numbers_close(old[k], new[k]) for k in old
        )
    return old == new


def _mech_part_changes(name: str, old: Diag, new: Diag) -> list[str]:
    scalar_lines = [
        f"    {f}: {_delta(old.get(f), new.get(f))}"
        for f in _PART_SCALAR_FIELDS
        if not _numbers_close(old.get(f), new.get(f))
    ]
    bbox_line = (
        ["    bbox: changed"]
        if not _numbers_close(old.get("bbox"), new.get("bbox"))
        else []
    )
    com_line = (
        [f"    center_of_mass_mm: {old.get('center_of_mass_mm')} → {new.get('center_of_mass_mm')}"]
        if not _numbers_close(
            old.get("center_of_mass_mm"), new.get("center_of_mass_mm")
        )
        else []
    )
    valid_line = (
        [f"    is_valid: {old.get('is_valid')} → {new.get('is_valid')}"]
        if old.get("is_valid") != new.get("is_valid")
        else []
    )
    solids_line = (
        [f"    solid_count: {old.get('solid_count')} → {new.get('solid_count')}"]
        if old.get("solid_count") != new.get("solid_count")
        else []
    )
    changes = scalar_lines + bbox_line + com_line + valid_line + solids_line
    return [f"  changed: {name}", *changes] if changes else []


def _mech_parts_section(old: Diag, new: Diag) -> list[str]:
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    common = sorted(set(old) & set(new))
    header = [
        *([f"  added: {', '.join(added)}"] if added else []),
        *([f"  removed: {', '.join(removed)}"] if removed else []),
    ]
    changes = [
        line
        for name in common
        for line in _mech_part_changes(name, old[name], new[name])
    ]
    return header + changes


def _pair_key(entry: Diag) -> tuple[str, str]:
    return tuple(sorted((entry["a"], entry["b"])))


def _interferences_section(old: list[Diag], new: list[Diag]) -> list[str]:
    old_map = {_pair_key(e): e for e in old}
    new_map = {_pair_key(e): e for e in new}
    added = [
        f"  added: {new_map[k]['a']} / {new_map[k]['b']}"
        f" volume={new_map[k]['volume_mm3']:.3g} mm³"
        for k in sorted(new_map.keys() - old_map.keys())
    ]
    removed = [
        f"  removed: {old_map[k]['a']} / {old_map[k]['b']}"
        for k in sorted(old_map.keys() - new_map.keys())
    ]
    changed = [
        f"  changed: {old_map[k]['a']} / {old_map[k]['b']}"
        f" volume {_pct(old_map[k]['volume_mm3'], new_map[k]['volume_mm3'])}"
        for k in sorted(old_map.keys() & new_map.keys())
        if abs(old_map[k]["volume_mm3"] - new_map[k]["volume_mm3"]) > 1e-6
    ]
    return added + removed + changed


def _motion_changes(name: str, old: Diag, new: Diag) -> list[str]:
    samples = (
        [f"  changed: {name} samples {old['samples']} → {new['samples']}"]
        if old["samples"] != new["samples"]
        else []
    )
    old_joints, new_joints = old["joints_deg"], new["joints_deg"]
    joints = [
        f"  changed: {name} {joint} {field} "
        f"{old_joints[joint][field]} → {new_joints[joint][field]}"
        for joint in sorted(old_joints.keys() & new_joints.keys())
        for field in ("min", "max", "max_step")
        if not _numbers_close(old_joints[joint][field], new_joints[joint][field])
    ]
    driven = [
        f"  changed: {name} no longer drives {joint}"
        for joint in sorted(old_joints.keys() - new_joints.keys())
    ] + [
        f"  changed: {name} now drives {joint}"
        for joint in sorted(new_joints.keys() - old_joints.keys())
    ]
    # A motion can keep its samples and its joint range and stop testing
    # anything -- the one regression no other line here would show.
    counts = (
        [
            f"  changed: {name} moved {old['moved']} of {old['movable']} "
            f"claims → {new['moved']} of {new['movable']}"
        ]
        if (old["moved"], old["movable"]) != (new["moved"], new["movable"])
        else []
    )
    return samples + joints + driven + counts


def _motions_section(old: list[Diag], new: list[Diag]) -> list[str]:
    """How much the run looked at. A motion that went away, or came
    back coarser, changes what every held green below it means."""
    old_map = {m["name"]: m for m in old}
    new_map = {m["name"]: m for m in new}
    added = [
        f"  added: {name} ({new_map[name]['samples']} samples)"
        for name in sorted(new_map.keys() - old_map.keys())
    ]
    removed = [
        f"  removed: {name} ({old_map[name]['samples']} samples)"
        for name in sorted(old_map.keys() - new_map.keys())
    ]
    changed = [
        line
        for name in sorted(old_map.keys() & new_map.keys())
        for line in _motion_changes(name, old_map[name], new_map[name])
    ]
    return added + removed + changed


def _mech_warning_label(w: Diag) -> str:
    subject = (
        w.get("joint") or w.get("assertion") or w.get("part") or w.get("motion")
    )
    return f"{w['kind']}: {subject}" if subject else w["kind"]


def _mech_warnings_section(old: list[Diag], new: list[Diag]) -> list[str]:
    old_labels = {_mech_warning_label(w) for w in old}
    new_labels = {_mech_warning_label(w) for w in new}
    return [f"  added: {label}" for label in sorted(new_labels - old_labels)] + [
        f"  removed: {label}" for label in sorted(old_labels - new_labels)
    ]


def _diff_mechanism(old: Diag, new: Diag) -> str:
    sections: tuple[tuple[str, list[str]], ...] = (
        ("status", _status_section(old, new)),
        ("selection", _selection_section(old, new)),
        ("motions", _motions_section(old.get("motions", []), new.get("motions", []))),
        ("parts", _mech_parts_section(old.get("parts", {}), new.get("parts", {}))),
        (
            "interferences",
            _interferences_section(
                old.get("interferences") or [], new.get("interferences") or []
            ),
        ),
        (
            "assertions",
            _assertions_section(
                old.get("assertions", []), new.get("assertions", [])
            ),
        ),
        (
            "warnings",
            _mech_warnings_section(
                old.get("warnings", []), new.get("warnings", [])
            ),
        ),
    )
    blocks = [f"{title}:\n" + "\n".join(lines) for title, lines in sections if lines]
    return "\n".join(blocks) + "\n" if blocks else NO_CHANGES


# --- Printability diff --------------------------------------------------


def _scalar_line(field: str, old: Any, new: Any) -> list[str]:
    if old == new:
        return []
    return [f"  {field}: {_delta(old, new)}"]


def _at(point: list[float]) -> str:
    return "(" + ", ".join(f"{c:.2f}" for c in point) + ")"


def _region_key(region: Diag) -> tuple[float, ...]:
    """Where a region is, to the precision the diff prints: a face that
    kept its place matches across runs; one that moved reads as removed
    and added, which is what a waiver naming it needs to hear."""
    return tuple(round(c, 2) for c in region["centroid_mm"])


def _largest_first(regions: Iterable[Diag]) -> list[Diag]:
    return sorted(regions, key=lambda r: -r["area_mm2"])


def _regions_section(old: list[Diag], new: list[Diag]) -> list[str]:
    old_map = {_region_key(r): r for r in old}
    new_map = {_region_key(r): r for r in new}
    added = [
        f"  region added: {r['area_mm2']:.3g} mm² at {_at(r['centroid_mm'])}"
        for r in _largest_first(new_map[k] for k in new_map.keys() - old_map.keys())
    ]
    removed = [
        f"  region removed: {r['area_mm2']:.3g} mm² at {_at(r['centroid_mm'])}"
        for r in _largest_first(old_map[k] for k in old_map.keys() - new_map.keys())
    ]
    changed = [
        f"  region changed: at {_at(new_map[k]['centroid_mm'])} area "
        f"{_pct(old_map[k]['area_mm2'], new_map[k]['area_mm2'])}"
        for k in sorted(old_map.keys() & new_map.keys())
        if not _numbers_close(old_map[k]["area_mm2"], new_map[k]["area_mm2"])
    ]
    return added + removed + changed


def _overhang_section(old: Diag | None, new: Diag | None) -> list[str]:
    if old == new:
        return []
    if old is None:
        return [
            f"  added: area={new['area_mm2']:.3g} mm²"
            f" max_angle={new['max_angle_deg']:.3g}°"
            f" regions={len(new['regions'])}"
        ]
    if new is None:
        return ["  removed"]
    area = (
        [f"  area_mm2: {_pct(old['area_mm2'], new['area_mm2'])}"]
        if old["area_mm2"] != new["area_mm2"]
        else []
    )
    angle = (
        [f"  max_angle_deg: {_delta(old['max_angle_deg'], new['max_angle_deg'])}"]
        if old["max_angle_deg"] != new["max_angle_deg"]
        else []
    )
    return area + angle + _regions_section(old["regions"], new["regions"])


def _method_params_section(old: Diag, new: Diag) -> list[str]:
    """Every declared method parameter that changed — an ``up_axis``
    flip otherwise shows only through the readings it moved."""
    return [
        f"  {key}: {_delta(old.get(key), new.get(key))}"
        for key in sorted(old.keys() | new.keys())
        if not _numbers_close(old.get(key), new.get(key))
    ]


def _bbox_section(old: Any, new: Any) -> list[str]:
    return ["  bbox: changed"] if old != new else []


def _warning_key(w: Diag) -> tuple[str, str]:
    return (w["kind"], w.get("assertion") or w["part"])


def _warning_label(w: Diag) -> str:
    """``kind: subject``, with the rationale when the warning has one
    (a waiver does; ``multi_solid`` does not)."""
    kind, subject = _warning_key(w)
    reason = w.get("reason")
    return f"{kind}: {subject} — {reason}" if reason else f"{kind}: {subject}"


def _warnings_section(old: list[Diag], new: list[Diag]) -> list[str]:
    old_map = {_warning_key(w): w for w in old}
    new_map = {_warning_key(w): w for w in new}
    added = [
        f"  added: {_warning_label(new_map[key])}"
        for key in sorted(new_map.keys() - old_map.keys())
    ]
    removed = [
        f"  removed: {kind}: {subject}"
        for kind, subject in sorted(old_map.keys() - new_map.keys())
    ]
    return added + removed


def _diff_printability(old: Diag, new: Diag) -> str:
    name_section = (
        [f"  {old.get('name')} → {new.get('name')}"]
        if old.get("name") != new.get("name")
        else []
    )
    method_section = (
        [f"  {old.get('method')} → {new.get('method')}"]
        if old.get("method") != new.get("method")
        else []
    )
    com_section = (
        [
            f"  {old.get('center_of_mass_mm')} → {new.get('center_of_mass_mm')}"
        ]
        if old.get("center_of_mass_mm") != new.get("center_of_mass_mm")
        else []
    )
    valid_section = (
        [f"  {old.get('is_valid')} → {new.get('is_valid')}"]
        if old.get("is_valid") != new.get("is_valid")
        else []
    )
    solids_section = (
        [f"  {old.get('solid_count')} → {new.get('solid_count')}"]
        if old.get("solid_count") != new.get("solid_count")
        else []
    )
    sections: tuple[tuple[str, list[str]], ...] = (
        ("status", _status_section(old, new)),
        ("name", name_section),
        ("method", method_section),
        (
            "method_params",
            _method_params_section(
                old.get("method_params", {}), new.get("method_params", {})
            ),
        ),
        ("bbox", _bbox_section(old.get("bbox"), new.get("bbox"))),
        (
            "volume_mm3",
            _scalar_line("volume_mm3", old.get("volume_mm3"), new.get("volume_mm3")),
        ),
        (
            "surface_area_mm2",
            _scalar_line(
                "surface_area_mm2",
                old.get("surface_area_mm2"),
                new.get("surface_area_mm2"),
            ),
        ),
        ("center_of_mass_mm", com_section),
        ("is_valid", valid_section),
        ("solid_count", solids_section),
        (
            "min_wall_mm",
            _scalar_line("min_wall_mm", old.get("min_wall_mm"), new.get("min_wall_mm")),
        ),
        (
            "min_wall_at",
            _scalar_line("min_wall_at", old.get("min_wall_at"), new.get("min_wall_at")),
        ),
        ("overhang", _overhang_section(old.get("overhang"), new.get("overhang"))),
        (
            "assertions",
            _assertions_section(
                old.get("assertions", []), new.get("assertions", [])
            ),
        ),
        (
            "warnings",
            _warnings_section(old.get("warnings", []), new.get("warnings", [])),
        ),
    )
    blocks = [f"{title}:\n" + "\n".join(lines) for title, lines in sections if lines]
    return "\n".join(blocks) + "\n" if blocks else NO_CHANGES


# --- Dispatch -----------------------------------------------------------


def diff(old: Diag, new: Diag) -> str:
    old_kind = file_kind(old)
    new_kind = file_kind(new)
    if old_kind != new_kind:
        raise ValueError(
            f"cannot diff {old_kind} against {new_kind}; "
            "both files must be the same kind"
        )
    _require_current_schema(old, new)
    _require_same_selection(old, new)
    return (
        _diff_printability(old, new)
        if old_kind == "printability"
        else _diff_mechanism(old, new)
    )
