import pytest

from cad_khana.diff import diff
from cad_khana.mechanism.diagnostics import SCHEMA_VERSION


def _empty_mech() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "parts": {},
        "interferences": [],
        "assertions": [],
    }


def _empty_printability() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "printability",
        "status": "ok",
        "name": "part",
        "method": "FDM",
        "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]},
        "volume_mm3": 1.0,
        "surface_area_mm2": 6.0,
        "center_of_mass_mm": [0.5, 0.5, 0.5],
        "is_valid": True,
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


# --- schema enforcement -------------------------------------------------


def test_mismatched_schema_version_raises_with_regenerate_hint():
    old = _empty_mech() | {"schema_version": "0.1"}
    new = _empty_mech()
    with pytest.raises(ValueError, match="regenerate"):
        diff(old, new)


def test_both_stale_schema_versions_also_raise():
    old = _empty_mech() | {"schema_version": "0.1"}
    new = _empty_mech() | {"schema_version": "0.1"}
    with pytest.raises(ValueError, match="regenerate"):
        diff(old, new)


def test_printability_schema_mismatch_raises():
    old = _empty_printability() | {"schema_version": "0.1"}
    new = _empty_printability()
    with pytest.raises(ValueError, match="regenerate"):
        diff(old, new)


# --- new mechanism part fields -----------------------------------------


def test_part_surface_area_delta():
    old = _empty_mech() | {
        "parts": {"a": {"volume_mm3": 100, "surface_area_mm2": 60, "bbox": {}}}
    }
    new = _empty_mech() | {
        "parts": {"a": {"volume_mm3": 100, "surface_area_mm2": 72, "bbox": {}}}
    }
    out = diff(old, new)
    assert "surface_area_mm2" in out
    assert "+20.0%" in out


def test_part_center_of_mass_change_reported():
    old = _empty_mech() | {
        "parts": {"a": {"volume_mm3": 100, "center_of_mass_mm": [0, 0, 0], "bbox": {}}}
    }
    new = _empty_mech() | {
        "parts": {"a": {"volume_mm3": 100, "center_of_mass_mm": [1, 0, 0], "bbox": {}}}
    }
    out = diff(old, new)
    assert "center_of_mass_mm" in out


def test_part_is_valid_regression_reported():
    old = _empty_mech() | {
        "parts": {"a": {"volume_mm3": 100, "is_valid": True, "bbox": {}}}
    }
    new = _empty_mech() | {
        "parts": {"a": {"volume_mm3": 100, "is_valid": False, "bbox": {}}}
    }
    out = diff(old, new)
    assert "is_valid" in out
    assert "True → False" in out


# --- new printability fields -------------------------------------------


def test_printability_surface_area_delta():
    old = _empty_printability()
    new = _empty_printability() | {"surface_area_mm2": 9.0}
    out = diff(old, new)
    assert "surface_area_mm2" in out
    assert "+50" in out


def test_printability_is_valid_regression():
    old = _empty_printability()
    new = _empty_printability() | {"is_valid": False}
    out = diff(old, new)
    assert "is_valid" in out
