import json
from pathlib import Path

import pytest
from build123d import Box, BuildPart, Locations, Pos
from pytest import approx

from cad_khana.printability.inspect import inspect
from cad_khana.printability.methods import FDM


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def _plate(x: float, y: float, z: float):
    with BuildPart() as p:
        Box(x, y, z)
    return p.part


def _l_shape():
    # Base 20³ cube with a 10×20×4 ledge protruding off the +X face at
    # mid-height — the ledge underside is a genuine overhang.
    base = _plate(20, 20, 20)
    ledge = Pos(15, 0, 5) * Box(10, 20, 4)
    return base + ledge


def test_inspect_writes_named_printability_json(tmp_path: Path):
    inspect(_cube(10), method=FDM(), out=tmp_path, name="cube")
    assert (tmp_path / "cube-printability.json").exists()


def test_inspect_json_schema(tmp_path: Path):
    inspect(_cube(10), method=FDM(), out=tmp_path, name="cube")
    data = json.loads((tmp_path / "cube-printability.json").read_text())
    assert data["kind"] == "printability"
    assert data["name"] == "cube"
    assert data["method"] == "FDM"
    assert data["status"] == "ok"
    assert data["volume_mm3"] == approx(1000.0)
    assert data["surface_area_mm2"] == approx(600.0)
    assert data["center_of_mass_mm"] == approx([0.0, 0.0, 0.0], abs=1e-9)
    assert data["is_valid"] is True
    assert data["min_wall_mm"] == approx(10.0, abs=0.05)
    assert "bbox" in data
    assert "assertions" in data


def test_inspect_fails_when_wall_below_minimum(tmp_path: Path):
    method = FDM(wall_min_mm=5.0)
    with pytest.raises(SystemExit) as exc:
        inspect(_plate(20, 20, 1), method=method, out=tmp_path, name="plate")
    assert exc.value.code == 1
    data = json.loads((tmp_path / "plate-printability.json").read_text())
    assert data["status"] == "assertion_failed"
    wall_failures = [
        a for a in data["assertions"] if "wall" in a["name"] and not a["passed"]
    ]
    assert wall_failures
    assert " at (" in wall_failures[0]["detail"]


def test_inspect_records_min_wall_witness(tmp_path: Path):
    inspect(_plate(20, 20, 2), method=FDM(), out=tmp_path, name="plate")
    data = json.loads((tmp_path / "plate-printability.json").read_text())
    assert data["min_wall_mm"] == approx(2.0, abs=0.05)
    at = data["min_wall_at"]
    assert len(at) == 3
    # The thin dimension is Z; the witness sits on a top/bottom face.
    assert abs(at[2]) == approx(1.0, abs=0.05)


def test_inspect_failure_prints_summary_to_stderr(tmp_path: Path, capsys):
    method = FDM(wall_min_mm=5.0)
    with pytest.raises(SystemExit):
        inspect(_plate(20, 20, 1), method=method, out=tmp_path, name="plate")
    err = capsys.readouterr().err
    assert "plate: assertion failed: wall_min:5.0" in err
    assert "plate-printability.json" in err


def test_inspect_passes_on_thick_printable_part(tmp_path: Path):
    # Default FDM settings; a cube has no real overhangs (bottom face is
    # on the build plate) and the wall is comfortably thick.
    result = inspect(_cube(10), method=FDM(), out=tmp_path, name="cube")
    assert result.status == "ok"
    assert all(a.passed for a in result.assertions)


def test_inspect_records_overhang_diagnostic(tmp_path: Path):
    # A real overhang (ledge underside) should be detected and flagged.
    with pytest.raises(SystemExit):
        inspect(_l_shape(), method=FDM(), out=tmp_path, name="ell")
    data = json.loads((tmp_path / "ell-printability.json").read_text())
    assert data["overhang"] is not None
    assert data["overhang"]["max_angle_deg"] == approx(90.0, abs=0.01)


def test_inspect_fails_when_overhang_exceeds_threshold(tmp_path: Path):
    with pytest.raises(SystemExit):
        inspect(_l_shape(), method=FDM(), out=tmp_path, name="ell")
    data = json.loads((tmp_path / "ell-printability.json").read_text())
    overhang_failures = [
        a
        for a in data["assertions"]
        if "overhang" in a["name"] and not a["passed"]
    ]
    assert overhang_failures



def test_raised_overhang_threshold_still_records_the_angle(tmp_path: Path):
    result = inspect(
        _l_shape(), method=FDM(overhang_max_deg=90.0), out=tmp_path, name="ell"
    )
    data = json.loads((tmp_path / "ell-printability.json").read_text())
    assert result.status == "ok"
    assert data["overhang"] == {"area_mm2": 0.0, "max_angle_deg": approx(90.0, abs=0.01)}

# --- waivers ------------------------------------------------------------


def test_waived_failure_does_not_fail_the_run(tmp_path: Path):
    result = inspect(
        _plate(20, 20, 1),
        method=FDM(wall_min_mm=5.0),
        out=tmp_path,
        name="plate",
        waive={"wall_min": "ray-sampling artifact at thin annulus edges"},
    )
    assert result.status == "ok"
    data = json.loads((tmp_path / "plate-printability.json").read_text())
    assert data["status"] == "ok"
    (wall,) = [a for a in data["assertions"] if a["name"].startswith("wall_min")]
    assert wall["passed"] is False
    assert wall["waived"] == "ray-sampling artifact at thin annulus edges"
    (warning,) = data["warnings"]
    assert warning["kind"] == "waived_failure"
    assert warning["assertion"] == wall["name"]
    assert warning["reason"] == wall["waived"]
    assert "below min" in warning["detail"]


def test_waiver_survives_threshold_change(tmp_path: Path):
    # Keys match the assertion *kind*, not the kind:threshold name.
    result = inspect(
        _plate(20, 20, 1),
        method=FDM(wall_min_mm=3.0),
        out=tmp_path,
        name="plate",
        waive={"wall_min": "known artifact"},
    )
    assert result.status == "ok"


def test_two_kind_waiver_in_one_block(tmp_path: Path):
    # The m02 rotor case: wall artifact + accepted overhang, one call.
    result = inspect(
        _l_shape(),
        method=FDM(wall_min_mm=5.0),
        out=tmp_path,
        name="rotor",
        waive={
            "wall_min": "sharp-edge sampling artifact",
            "overhang_max": "accepted 90° ceiling; printed with supports",
        },
    )
    assert result.status == "ok"
    assert {w.kind for w in result.warnings} == {"waived_failure"}
    assert len(result.warnings) == 2


def test_unwaived_failure_still_exits_nonzero(tmp_path: Path):
    # Both kinds fail; only wall_min waived — overhang still fails the run.
    with pytest.raises(SystemExit) as exc:
        inspect(
            _l_shape(),
            method=FDM(wall_min_mm=5.0),
            out=tmp_path,
            name="ell",
            waive={"wall_min": "artifact"},
        )
    assert exc.value.code == 1
    data = json.loads((tmp_path / "ell-printability.json").read_text())
    assert data["status"] == "assertion_failed"
    (wall,) = [a for a in data["assertions"] if a["name"].startswith("wall_min")]
    assert wall["waived"] == "artifact"


def test_stale_waiver_is_reported(tmp_path: Path, capsys):
    result = inspect(
        _cube(10),
        method=FDM(),
        out=tmp_path,
        name="cube",
        waive={"wall_min": "no longer needed"},
    )
    assert result.status == "ok"
    (warning,) = result.warnings
    assert warning.kind == "stale_waiver"
    assert "remove the waiver" in warning.detail
    assert "cube: warning: stale_waiver" in capsys.readouterr().err


def test_unknown_waive_key_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="walls"):
        inspect(
            _cube(10),
            method=FDM(),
            out=tmp_path,
            name="cube",
            waive={"walls": "typo"},
        )


def test_waived_failure_prints_warning_to_stderr(tmp_path: Path, capsys):
    inspect(
        _plate(20, 20, 1),
        method=FDM(wall_min_mm=5.0),
        out=tmp_path,
        name="plate",
        waive={"wall_min": "artifact"},
    )
    err = capsys.readouterr().err
    assert "plate: warning: waived_failure: wall_min:5.0 — artifact" in err


# --- solid_count --------------------------------------------------------


def _two_bodies():
    with BuildPart() as p:
        with Locations((0, 0, 0), (30, 0, 0)):
            Box(10, 10, 10)
    return p.part


def test_solid_count_is_reported(tmp_path: Path):
    diag = inspect(_cube(), method=FDM(), out=tmp_path, name="cube")
    assert diag.solid_count == 1
    assert diag.warnings == ()
    data = json.loads((tmp_path / "cube-printability.json").read_text())
    assert data["solid_count"] == 1


def test_a_multi_solid_part_is_warned_about_and_does_not_fail(tmp_path: Path, capsys):
    diag = inspect(_two_bodies(), method=FDM(), out=tmp_path, name="pair")
    assert diag.status == "ok"
    data = json.loads((tmp_path / "pair-printability.json").read_text())
    assert data["solid_count"] == 2
    assert data["warnings"] == [
        {"kind": "multi_solid", "part": "pair", "solid_count": 2}
    ]
    assert "pair: warning: multi_solid: 2 solids" in capsys.readouterr().err


def _assertion(diag, kind: str):
    (found,) = (a for a in diag.assertions if a.name.split(":")[0] == kind)
    return found


def test_an_undeclared_part_carries_no_solid_count_assertion(tmp_path: Path):
    diag = inspect(_cube(), method=FDM(), out=tmp_path, name="cube")
    assert [a.name.split(":")[0] for a in diag.assertions] == [
        "wall_min",
        "overhang_max",
    ]


def test_a_declared_solid_count_answers_the_warning(tmp_path: Path):
    diag = inspect(
        _two_bodies(), method=FDM(), out=tmp_path, name="band", solid_count=2
    )
    claim = _assertion(diag, "solid_count")
    assert claim.name == "solid_count:2"
    assert claim.passed
    assert claim.value == 2.0
    assert diag.warnings == ()
    assert diag.status == "ok"
    data = json.loads((tmp_path / "band-printability.json").read_text())
    assert data["solid_count"] == 2
    assert data["warnings"] == []


def test_a_wrong_declared_solid_count_fails_like_any_claim(tmp_path: Path):
    with pytest.raises(SystemExit):
        inspect(_two_bodies(), method=FDM(), out=tmp_path, name="body", solid_count=1)
    data = json.loads((tmp_path / "body-printability.json").read_text())
    assert data["status"] == "assertion_failed"
    (claim,) = (a for a in data["assertions"] if a["name"] == "solid_count:1")
    assert claim["passed"] is False
    assert claim["value"] == 2.0
    assert claim["detail"] == "2 solids, expected 1"
    assert data["warnings"] == []  # a failure, not also a warning


def test_a_declared_count_a_single_solid_stops_matching_fails(tmp_path: Path):
    """The declaration cannot go stale quietly: a band that stops being
    parted fails its ``solid_count=2`` rather than reading as fine."""
    with pytest.raises(SystemExit):
        inspect(_cube(), method=FDM(), out=tmp_path, name="band", solid_count=2)


def test_a_solid_count_failure_is_waivable_by_kind(tmp_path: Path):
    diag = inspect(
        _two_bodies(),
        method=FDM(),
        out=tmp_path,
        name="body",
        solid_count=1,
        waive={"solid_count": "two halves, glued after printing"},
    )
    assert diag.status == "ok"
    assert _assertion(diag, "solid_count").passed is False
    assert [w.kind for w in diag.warnings] == ["waived_failure"]


def test_waiving_solid_count_without_declaring_it_is_an_unknown_kind(tmp_path: Path):
    with pytest.raises(ValueError, match="solid_count"):
        inspect(
            _two_bodies(),
            method=FDM(),
            out=tmp_path,
            name="body",
            waive={"solid_count": "no claim to waive"},
        )
