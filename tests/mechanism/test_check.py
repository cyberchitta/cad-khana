import json
from pathlib import Path

import pytest
from build123d import Box, BuildPart, Location
from pytest import approx

from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.check import check
from cad_khana.mechanism.diagnostics import SCHEMA_VERSION


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def test_check_writes_stl_and_step(tmp_path: Path):
    assembly = (
        Assembly()
        .add("housing", _cube(20))
        .add("lid", _cube(20), location=Location((0, 0, 25)))
    )
    result = check(assembly, out=tmp_path)
    names = sorted(path.name for path in result.exports)
    assert names == ["assembly.step", "assembly.stl"]
    for path in result.exports:
        assert path.exists()
        assert path.stat().st_size > 0


def test_check_creates_missing_out_directory(tmp_path: Path):
    target = tmp_path / "nested" / "outputs"
    check(Assembly().add("a", _cube()), out=target)
    assert target.is_dir()


def test_check_writes_mechanism_json(tmp_path: Path):
    check(Assembly().add("cube", _cube(10)), out=tmp_path)
    diag_path = tmp_path / "mechanism.json"
    assert diag_path.exists()
    data = json.loads(diag_path.read_text())
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["status"] == "ok"
    assert data["error"] is None
    assert set(data["parts"]) == {"cube"}
    assert data["parts"]["cube"]["volume_mm3"] == approx(1000.0)
    assert "min_wall_mm" not in data["parts"]["cube"]
    assert data["interferences"] == []
    assert "overhangs" not in data
    assert data["assertions"] == []


def test_mechanism_json_has_no_kind_field(tmp_path: Path):
    check(Assembly().add("cube", _cube(10)), out=tmp_path)
    data = json.loads((tmp_path / "mechanism.json").read_text())
    assert "kind" not in data


def test_check_records_exports_in_diagnostics(tmp_path: Path):
    result = check(Assembly().add("cube", _cube()), out=tmp_path)
    data = json.loads((tmp_path / "mechanism.json").read_text())
    assert sorted(data["exports"]) == sorted(str(p) for p in result.exports)


def test_check_result_carries_diagnostics(tmp_path: Path):
    result = check(Assembly().add("cube", _cube(10)), out=tmp_path)
    assert result.diagnostics.status == "ok"
    assert result.diagnostics.parts["cube"].volume_mm3 == approx(1000.0)


def test_check_records_passing_assertion(tmp_path: Path):
    assembly = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((20, 0, 0)))
        .assert_no_interference("a", "b")
    )
    result = check(assembly, out=tmp_path)
    assert result.diagnostics.status == "ok"
    assert len(result.diagnostics.assertions) == 1
    assert result.diagnostics.assertions[0].passed


def test_check_raises_system_exit_on_assertion_failure(tmp_path: Path):
    assembly = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b")
    )
    with pytest.raises(SystemExit) as exc:
        check(assembly, out=tmp_path)
    assert exc.value.code == 1


def test_check_writes_diagnostics_before_exit_on_failure(tmp_path: Path):
    assembly = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b")
    )
    with pytest.raises(SystemExit):
        check(assembly, out=tmp_path)
    data = json.loads((tmp_path / "mechanism.json").read_text())
    assert data["status"] == "assertion_failed"
    assert len(data["assertions"]) == 1
    assert not data["assertions"][0]["passed"]
    assert data["assertions"][0]["detail"] is not None


def test_check_still_exports_on_assertion_failure(tmp_path: Path):
    assembly = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b")
    )
    with pytest.raises(SystemExit):
        check(assembly, out=tmp_path)
    assert (tmp_path / "assembly.stl").exists()
    assert (tmp_path / "assembly.step").exists()


def test_check_collects_all_assertion_failures(tmp_path: Path):
    assembly = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b", name="first")
        .assert_clearance("a", "b", min_mm=0.2, name="second")
    )
    with pytest.raises(SystemExit):
        check(assembly, out=tmp_path)
    data = json.loads((tmp_path / "mechanism.json").read_text())
    names = [a["name"] for a in data["assertions"]]
    assert names == ["first", "second"]
    assert all(not a["passed"] for a in data["assertions"])


def test_check_records_interferences(tmp_path: Path):
    assembly = (
        Assembly()
        .add("a", _cube(10))
        .add("b", _cube(10), location=Location((5, 0, 0)))
    )
    check(assembly, out=tmp_path)
    data = json.loads((tmp_path / "mechanism.json").read_text())
    assert len(data["interferences"]) == 1
    hit = data["interferences"][0]
    assert (hit["a"], hit["b"]) == ("a", "b")
    assert hit["volume_mm3"] == approx(500.0)
    assert hit["centroid"][0] == approx(2.5)
    assert hit["centroid"][1] == approx(0.0, abs=1e-9)


def test_check_export_parameter_false_skips_stl_step(tmp_path: Path):
    check(Assembly().add("cube", _cube()), out=tmp_path, export=False)
    assert not (tmp_path / "assembly.stl").exists()
    assert not (tmp_path / "assembly.step").exists()
    data = json.loads((tmp_path / "mechanism.json").read_text())
    assert data["exports"] == []


def test_check_export_parameter_true_forces_export(tmp_path: Path):
    check(Assembly().add("cube", _cube()), out=tmp_path, export=True)
    assert (tmp_path / "assembly.stl").exists()
    assert (tmp_path / "assembly.step").exists()
