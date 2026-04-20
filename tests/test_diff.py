import pytest

from cad_khana.diff import diff


def _empty_mech() -> dict:
    return {
        "schema_version": "0.1",
        "status": "ok",
        "parts": {},
        "interferences": [],
        "assertions": [],
    }


def _empty_printability() -> dict:
    return {
        "schema_version": "0.1",
        "kind": "printability",
        "status": "ok",
        "name": "part",
        "method": "FDM",
        "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]},
        "volume_mm3": 1.0,
        "min_wall_mm": 1.0,
        "overhang": None,
        "assertions": [],
    }


# --- mechanism diff -----------------------------------------------------


def test_identical_mechanism_reports_no_changes():
    assert diff(_empty_mech(), _empty_mech()) == "no changes\n"


def test_status_change_is_reported():
    old = _empty_mech()
    new = _empty_mech() | {"status": "assertion_failed"}
    out = diff(old, new)
    assert "status:" in out
    assert "ok → assertion_failed" in out


def test_part_added_and_removed():
    old = _empty_mech() | {"parts": {"a": {"volume_mm3": 10, "bbox": {}}}}
    new = _empty_mech() | {"parts": {"b": {"volume_mm3": 20, "bbox": {}}}}
    out = diff(old, new)
    assert "added: b" in out
    assert "removed: a" in out


def test_part_volume_delta_with_percent():
    old = _empty_mech() | {"parts": {"a": {"volume_mm3": 100, "bbox": {}}}}
    new = _empty_mech() | {"parts": {"a": {"volume_mm3": 120, "bbox": {}}}}
    out = diff(old, new)
    assert "changed: a" in out
    assert "volume_mm3" in out
    assert "+20.0%" in out


def test_interference_added():
    old = _empty_mech()
    new = _empty_mech() | {
        "interferences": [
            {"a": "pin", "b": "tang", "volume_mm3": 0.5, "centroid": [0, 0, 0]}
        ]
    }
    out = diff(old, new)
    assert "interferences:" in out
    assert "added: pin / tang" in out
    assert "0.5" in out


def test_assertion_regression_shows_detail():
    old = _empty_mech() | {"assertions": [{"name": "clr", "passed": True, "detail": None}]}
    new = _empty_mech() | {
        "assertions": [
            {"name": "clr", "passed": False, "detail": "clearance 0.1mm below min 0.2mm"}
        ]
    }
    out = diff(old, new)
    assert "regressed: clr" in out
    assert "clearance 0.1mm" in out


def test_assertion_fix_is_reported():
    old = _empty_mech() | {"assertions": [{"name": "clr", "passed": False, "detail": "x"}]}
    new = _empty_mech() | {"assertions": [{"name": "clr", "passed": True, "detail": None}]}
    out = diff(old, new)
    assert "fixed: clr" in out


# --- printability diff --------------------------------------------------


def test_identical_printability_reports_no_changes():
    assert diff(_empty_printability(), _empty_printability()) == "no changes\n"


def test_printability_volume_delta():
    old = _empty_printability()
    new = _empty_printability() | {"volume_mm3": 1.5}
    out = diff(old, new)
    assert "volume_mm3" in out
    assert "+50" in out


def test_printability_min_wall_delta():
    old = _empty_printability() | {"min_wall_mm": 1.0}
    new = _empty_printability() | {"min_wall_mm": 2.0}
    out = diff(old, new)
    assert "min_wall_mm" in out


def test_printability_overhang_added():
    old = _empty_printability()
    new = _empty_printability() | {
        "overhang": {"area_mm2": 100.0, "max_angle_deg": 90.0}
    }
    out = diff(old, new)
    assert "overhang:" in out
    assert "added" in out


def test_printability_overhang_removed():
    old = _empty_printability() | {
        "overhang": {"area_mm2": 100.0, "max_angle_deg": 90.0}
    }
    new = _empty_printability()
    out = diff(old, new)
    assert "overhang:" in out
    assert "removed" in out


def test_printability_assertion_regression():
    old = _empty_printability() | {
        "assertions": [{"name": "wall_min:1.5", "passed": True, "detail": None}]
    }
    new = _empty_printability() | {
        "assertions": [
            {"name": "wall_min:1.5", "passed": False, "detail": "min wall 1.0mm below min 1.5mm"}
        ]
    }
    out = diff(old, new)
    assert "regressed: wall_min:1.5" in out


# --- dispatch errors ----------------------------------------------------


def test_diff_across_kinds_raises():
    with pytest.raises(ValueError):
        diff(_empty_mech(), _empty_printability())


def test_diff_across_kinds_raises_reverse():
    with pytest.raises(ValueError):
        diff(_empty_printability(), _empty_mech())
