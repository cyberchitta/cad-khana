from cad_khana.core.diff import diff


def _empty() -> dict:
    return {
        "schema_version": "0.1",
        "status": "ok",
        "parts": {},
        "interferences": [],
        "overhangs": [],
        "assertions": [],
    }


def test_identical_diagnostics_report_no_changes():
    assert diff(_empty(), _empty()) == "no changes\n"


def test_status_change_is_reported():
    old = _empty()
    new = _empty() | {"status": "assertion_failed"}
    out = diff(old, new)
    assert "status:" in out
    assert "ok → assertion_failed" in out


def test_part_added_and_removed():
    old = _empty() | {"parts": {"a": {"volume_mm3": 10, "bbox": {}}}}
    new = _empty() | {"parts": {"b": {"volume_mm3": 20, "bbox": {}}}}
    out = diff(old, new)
    assert "added: b" in out
    assert "removed: a" in out


def test_part_volume_delta_with_percent():
    old = _empty() | {"parts": {"a": {"volume_mm3": 100, "bbox": {}}}}
    new = _empty() | {"parts": {"a": {"volume_mm3": 120, "bbox": {}}}}
    out = diff(old, new)
    assert "changed: a" in out
    assert "volume_mm3" in out
    assert "+20.0%" in out


def test_interference_added():
    old = _empty()
    new = _empty() | {
        "interferences": [
            {"a": "pin", "b": "tang", "volume_mm3": 0.5, "centroid": [0, 0, 0]}
        ]
    }
    out = diff(old, new)
    assert "interferences:" in out
    assert "added: pin / tang" in out
    assert "0.5" in out


def test_assertion_regression_shows_detail():
    old = _empty() | {"assertions": [{"name": "clr", "passed": True, "detail": None}]}
    new = _empty() | {
        "assertions": [
            {"name": "clr", "passed": False, "detail": "clearance 0.1mm below min 0.2mm"}
        ]
    }
    out = diff(old, new)
    assert "regressed: clr" in out
    assert "clearance 0.1mm" in out


def test_assertion_fix_is_reported():
    old = _empty() | {"assertions": [{"name": "clr", "passed": False, "detail": "x"}]}
    new = _empty() | {"assertions": [{"name": "clr", "passed": True, "detail": None}]}
    out = diff(old, new)
    assert "fixed: clr" in out
