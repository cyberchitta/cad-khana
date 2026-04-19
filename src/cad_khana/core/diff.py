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


def _part_changes(name: str, old: Diag, new: Diag) -> list[str]:
    scalar_lines = [
        f"    {field}: {_delta(old.get(field), new.get(field))}"
        for field in ("volume_mm3", "min_wall_mm")
        if old.get(field) != new.get(field)
    ]
    bbox_line = ["    bbox: changed"] if old.get("bbox") != new.get("bbox") else []
    changes = scalar_lines + bbox_line
    return [f"  changed: {name}", *changes] if changes else []


def _parts_section(old: Diag, new: Diag) -> list[str]:
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
        for line in _part_changes(name, old[name], new[name])
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


def _overhangs_section(old: list[Diag], new: list[Diag]) -> list[str]:
    old_map = {o["part"]: o for o in old}
    new_map = {o["part"]: o for o in new}
    added = [
        f"  added: {k} area={new_map[k]['area_mm2']:.3g} mm²"
        for k in sorted(new_map.keys() - old_map.keys())
    ]
    removed = [f"  removed: {k}" for k in sorted(old_map.keys() - new_map.keys())]
    changed = [
        f"  changed: {k} area {_pct(old_map[k]['area_mm2'], new_map[k]['area_mm2'])}"
        for k in sorted(old_map.keys() & new_map.keys())
        if old_map[k] != new_map[k]
    ]
    return added + removed + changed


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


def _status_section(old: Diag, new: Diag) -> list[str]:
    return (
        [f"  {old.get('status')} → {new.get('status')}"]
        if old.get("status") != new.get("status")
        else []
    )


def _schema_warning(old: Diag, new: Diag) -> list[str]:
    ov, nv = old.get("schema_version"), new.get("schema_version")
    return [f"  schema_version: {ov} → {nv}"] if ov != nv else []


def diff(old: Diag, new: Diag) -> str:
    sections: tuple[tuple[str, list[str]], ...] = (
        ("schema", _schema_warning(old, new)),
        ("status", _status_section(old, new)),
        ("parts", _parts_section(old.get("parts", {}), new.get("parts", {}))),
        (
            "interferences",
            _interferences_section(
                old.get("interferences", []), new.get("interferences", [])
            ),
        ),
        (
            "overhangs",
            _overhangs_section(
                old.get("overhangs", []), new.get("overhangs", [])
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
