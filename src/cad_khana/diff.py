from __future__ import annotations

from typing import Any

from cad_khana.mechanism.diagnostics import SCHEMA_VERSION

Diag = dict[str, Any]


def _pct(old: float, new: float) -> str:
    if old == 0:
        return f"{old:.3g} → {new:.3g}"
    return f"{old:.3g} → {new:.3g} ({(new - old) / abs(old) * 100:+.1f}%)"


def _delta(old: Any, new: Any) -> str:
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return _pct(float(old), float(new))
    return f"{old} → {new}"


def _kind(diag: Diag) -> str:
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
            "regenerate by re-running build/check/inspect"
        )


def _assertions_section(old: list[Diag], new: list[Diag]) -> list[str]:
    old_map = {a["name"]: a for a in old}
    new_map = {a["name"]: a for a in new}
    common = old_map.keys() & new_map.keys()
    regressed = [
        f"  regressed: {name}"
        + (f" — {new_map[name]['detail']}" if new_map[name].get("detail") else "")
        for name in sorted(common)
        if old_map[name]["passed"] and not new_map[name]["passed"]
    ]
    fixed = [
        f"  fixed: {name}"
        for name in sorted(common)
        if not old_map[name]["passed"] and new_map[name]["passed"]
    ]
    added = [
        f"  added: {name} ({'passed' if new_map[name]['passed'] else 'failed'})"
        for name in sorted(new_map.keys() - old_map.keys())
    ]
    removed = [f"  removed: {name}" for name in sorted(old_map.keys() - new_map.keys())]
    return regressed + fixed + added + removed


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
    changes = scalar_lines + bbox_line + com_line + valid_line
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


def _diff_mechanism(old: Diag, new: Diag) -> str:
    sections: tuple[tuple[str, list[str]], ...] = (
        ("status", _status_section(old, new)),
        ("parts", _mech_parts_section(old.get("parts", {}), new.get("parts", {}))),
        (
            "interferences",
            _interferences_section(
                old.get("interferences", []), new.get("interferences", [])
            ),
        ),
        (
            "assertions",
            _assertions_section(
                old.get("assertions", []), new.get("assertions", [])
            ),
        ),
    )
    blocks = [f"{title}:\n" + "\n".join(lines) for title, lines in sections if lines]
    return "\n".join(blocks) + "\n" if blocks else "no changes\n"


# --- Printability diff --------------------------------------------------


def _scalar_line(field: str, old: Any, new: Any) -> list[str]:
    if old == new:
        return []
    return [f"  {field}: {_delta(old, new)}"]


def _overhang_section(old: Diag | None, new: Diag | None) -> list[str]:
    if old == new:
        return []
    if old is None:
        return [
            f"  added: area={new['area_mm2']:.3g} mm²"
            f" max_angle={new['max_angle_deg']:.3g}°"
        ]
    if new is None:
        return ["  removed"]
    lines = []
    if old.get("area_mm2") != new.get("area_mm2"):
        lines.append(
            f"  area_mm2: {_pct(old['area_mm2'], new['area_mm2'])}"
        )
    if old.get("max_angle_deg") != new.get("max_angle_deg"):
        lines.append(
            f"  max_angle_deg: {_delta(old['max_angle_deg'], new['max_angle_deg'])}"
        )
    return lines


def _bbox_section(old: Any, new: Any) -> list[str]:
    return ["  bbox: changed"] if old != new else []


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
    sections: tuple[tuple[str, list[str]], ...] = (
        ("status", _status_section(old, new)),
        ("name", name_section),
        ("method", method_section),
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
        (
            "min_wall_mm",
            _scalar_line("min_wall_mm", old.get("min_wall_mm"), new.get("min_wall_mm")),
        ),
        ("overhang", _overhang_section(old.get("overhang"), new.get("overhang"))),
        (
            "assertions",
            _assertions_section(
                old.get("assertions", []), new.get("assertions", [])
            ),
        ),
    )
    blocks = [f"{title}:\n" + "\n".join(lines) for title, lines in sections if lines]
    return "\n".join(blocks) + "\n" if blocks else "no changes\n"


# --- Dispatch -----------------------------------------------------------


def diff(old: Diag, new: Diag) -> str:
    old_kind = _kind(old)
    new_kind = _kind(new)
    if old_kind != new_kind:
        raise ValueError(
            f"cannot diff {old_kind} against {new_kind}; "
            "both files must be the same kind"
        )
    _require_current_schema(old, new)
    return (
        _diff_printability(old, new)
        if old_kind == "printability"
        else _diff_mechanism(old, new)
    )
