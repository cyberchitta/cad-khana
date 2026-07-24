import json
from pathlib import Path

import pytest
from build123d import Box, BuildPart, Pos
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
