from __future__ import annotations

from typing import Any

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


def _schema_warning(old: Diag, new: Diag) -> list[str]:
    ov, nv = old.get("schema_version"), new.get("schema_version")
    return [f"  schema_version: {ov} → {nv}"] if ov != nv else []


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


def _mech_part_changes(name: str, old: Diag, new: Diag) -> list[str]:
    scalar_lines = [
        f"    volume_mm3: {_delta(old.get('volume_mm3'), new.get('volume_mm3'))}"
    ] if old.get("volume_mm3") != new.get("volume_mm3") else []
    bbox_line = ["    bbox: changed"] if old.get("bbox") != new.get("bbox") else []
    changes = scalar_lines + bbox_line
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
        ("schema", _schema_warning(old, new)),
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
    sections: tuple[tuple[str, list[str]], ...] = (
        ("schema", _schema_warning(old, new)),
        ("status", _status_section(old, new)),
        ("name", name_section),
        ("method", method_section),
        ("bbox", _bbox_section(old.get("bbox"), new.get("bbox"))),
        (
            "volume_mm3",
            _scalar_line("volume_mm3", old.get("volume_mm3"), new.get("volume_mm3")),
        ),
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
    return (
        _diff_printability(old, new)
        if old_kind == "printability"
        else _diff_mechanism(old, new)
    )
