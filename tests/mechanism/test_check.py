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


def test_check_never_exports(tmp_path: Path):
    """Exporting is not what an orchestrator does — STL/STEP come from
    ``export_assembly`` / ``khana export``, and there is no toggle."""
    check(Assembly().with_part("cube", _cube()), out=tmp_path)
    assert not (tmp_path / "assembly.stl").exists()
    assert not (tmp_path / "assembly.step").exists()


def test_check_takes_no_export_parameter():
    """The Phase C strip removed it outright — no back-compat shim."""
    with pytest.raises(TypeError):
        check(Assembly(), out="unused", export=True)


def test_check_creates_missing_out_directory(tmp_path: Path):
    target = tmp_path / "nested" / "outputs"
    check(Assembly().with_part("a", _cube()), out=target)
    assert target.is_dir()


def test_check_writes_mechanism_json(tmp_path: Path):
    check(Assembly().with_part("cube", _cube(10)), out=tmp_path)
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
    check(Assembly().with_part("cube", _cube(10)), out=tmp_path)
    data = json.loads((tmp_path / "mechanism.json").read_text())
    assert "kind" not in data


def test_mechanism_json_has_no_exports_field(tmp_path: Path):
    """The field went with the limb: a permanently-empty array is a
    vestige an agent would read as "this run exported nothing"."""
    check(Assembly().with_part("cube", _cube()), out=tmp_path)
    data = json.loads((tmp_path / "mechanism.json").read_text())
    assert "exports" not in data


def test_check_result_carries_diagnostics(tmp_path: Path):
    result = check(Assembly().with_part("cube", _cube(10)), out=tmp_path)
    assert result.diagnostics.status == "ok"
    assert result.diagnostics.parts["cube"].volume_mm3 == approx(1000.0)


def test_check_records_passing_assertion(tmp_path: Path):
    assembly = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
        .assert_no_interference("a", "b")
    )
    result = check(assembly, out=tmp_path)
    assert result.diagnostics.status == "ok"
    assert len(result.diagnostics.assertions) == 1
    assert result.diagnostics.assertions[0].passed


def test_check_raises_system_exit_on_assertion_failure(tmp_path: Path):
    assembly = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b")
    )
    with pytest.raises(SystemExit) as exc:
        check(assembly, out=tmp_path)
    assert exc.value.code == 1


def test_check_writes_diagnostics_before_exit_on_failure(tmp_path: Path):
    assembly = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b")
    )
    with pytest.raises(SystemExit):
        check(assembly, out=tmp_path)
    data = json.loads((tmp_path / "mechanism.json").read_text())
    assert data["status"] == "assertion_failed"
    assert len(data["assertions"]) == 1
    assert not data["assertions"][0]["passed"]
    assert data["assertions"][0]["detail"] is not None


def test_check_collects_all_assertion_failures(tmp_path: Path):
    assembly = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b", name="first")
        .assert_clearance("a", "b", min_mm=0.2, name="second")
    )
    with pytest.raises(SystemExit):
        check(assembly, out=tmp_path)
    data = json.loads((tmp_path / "mechanism.json").read_text())
    names = [a["name"] for a in data["assertions"]]
    assert names == ["first", "second"]
    assert all(not a["passed"] for a in data["assertions"])


def test_check_failure_prints_summary_to_stderr(tmp_path: Path, capsys):
    assembly = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b", name="first")
        .assert_clearance("a", "b", min_mm=0.2, name="second")
    )
    with pytest.raises(SystemExit):
        check(assembly, out=tmp_path)
    err = capsys.readouterr().err
    assert "assertion failed: first — " in err
    assert "assertion failed: second — " in err
    assert "mechanism.json" in err


def test_check_skipped_assertion_does_not_fail_the_run(tmp_path: Path):
    assembly = (
        Assembly()
        .with_part("a", _cube())
        .assert_clearance("a", "bolt", min_mm=0.2, name="detail_only")
    )
    result = check(assembly, out=tmp_path)
    assert result.diagnostics.status == "ok"
    data = json.loads((tmp_path / "mechanism.json").read_text())
    assert data["status"] == "ok"
    assert data["assertions"][0]["passed"] is None
    assert "skipped" in data["assertions"][0]["detail"]


def test_check_skipped_alongside_failure_still_fails(tmp_path: Path):
    assembly = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b", name="real")
        .assert_clearance("a", "bolt", min_mm=0.2, name="detail_only")
    )
    with pytest.raises(SystemExit):
        check(assembly, out=tmp_path)
    data = json.loads((tmp_path / "mechanism.json").read_text())
    assert data["status"] == "assertion_failed"
    by_name = {a["name"]: a for a in data["assertions"]}
    assert by_name["real"]["passed"] is False
    assert by_name["detail_only"]["passed"] is None


def test_check_records_interferences(tmp_path: Path):
    assembly = (
        Assembly()
        .with_part("a", _cube(10))
        .with_part("b", _cube(10), location=Location((5, 0, 0)))
    )
    check(assembly, out=tmp_path)
    data = json.loads((tmp_path / "mechanism.json").read_text())
    assert len(data["interferences"]) == 1
    hit = data["interferences"][0]
    assert (hit["a"], hit["b"]) == ("a", "b")
    assert hit["volume_mm3"] == approx(500.0)
    assert hit["centroid"][0] == approx(2.5)
    assert hit["centroid"][1] == approx(0.0, abs=1e-9)


