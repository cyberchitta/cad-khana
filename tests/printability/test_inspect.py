import json
import re
from pathlib import Path

import pytest
from build123d import Box, BuildPart, Cylinder, Locations, Pos, Rot
from pytest import approx

from cad_khana.printability.feature import Feature
from cad_khana.printability.inspect import inspect
from cad_khana.printability.methods import FDM
from cad_khana.printability.waiver import Waiver


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


def test_inspect_records_the_declared_method_params(tmp_path: Path):
    method = FDM(up_axis=(0, -1, 0), wall_min_mm=1.2, overhang_max_deg=50.0)
    inspect(_cube(10), method=method, out=tmp_path, name="cube")
    data = json.loads((tmp_path / "cube-printability.json").read_text())
    assert data["method"] == "FDM"
    assert data["method_params"] == {
        "up_axis": [0, -1, 0],
        "wall_min_mm": 1.2,
        "overhang_max_deg": 50.0,
    }


def test_up_axis_is_recorded_as_declared_not_normalised(tmp_path: Path):
    inspect(_cube(10), method=FDM(up_axis=(0, 0, 2.5)), out=tmp_path, name="cube")
    data = json.loads((tmp_path / "cube-printability.json").read_text())
    assert data["method_params"]["up_axis"] == [0, 0, 2.5]


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
    assert data["overhang"] == {
        "area_mm2": 0.0,
        "max_angle_deg": approx(90.0, abs=0.01),
        "regions": [],
    }

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


# --- bound waivers ------------------------------------------------------


def _double_ledge():
    # The L-shape plus a second 10×20×4 ledge off the -X face: a new
    # down-facing face, 200 mm² more at 90°.
    return _l_shape() + Pos(-15, 0, -5) * Box(10, 20, 4)


def test_bound_overhang_waiver_applies_within_its_bound(tmp_path: Path):
    result = inspect(
        _l_shape(),
        method=FDM(),
        out=tmp_path,
        name="ell",
        waive={
            "overhang_max": Waiver(
                reason="ledge underside, 200 mm², printed with supports",
                max_area_mm2=201.0,
                max_regions=1,
            )
        },
    )
    assert result.status == "ok"
    data = json.loads((tmp_path / "ell-printability.json").read_text())
    (overhang,) = [a for a in data["assertions"] if a["name"].startswith("overhang")]
    assert overhang["passed"] is False
    assert overhang["waived"] == "ledge underside, 200 mm², printed with supports"
    assert "within the waiver's max_area_mm2 201.0, max_regions 1" in overhang["detail"]
    (warning,) = data["warnings"]
    assert warning["kind"] == "waived_failure"
    assert warning["detail"] == overhang["detail"]


def test_a_new_down_facing_face_breaks_a_bound_overhang_waiver(tmp_path: Path, capsys):
    with pytest.raises(SystemExit) as exc:
        inspect(
            _double_ledge(),
            method=FDM(),
            out=tmp_path,
            name="ell",
            waive={
                "overhang_max": Waiver(
                    reason="ledge underside, 200 mm²", max_area_mm2=201.0
                )
            },
        )
    assert exc.value.code == 1
    data = json.loads((tmp_path / "ell-printability.json").read_text())
    assert data["status"] == "assertion_failed"
    (overhang,) = [a for a in data["assertions"] if a["name"].startswith("overhang")]
    assert overhang["passed"] is False
    assert overhang["waived"] is None
    assert (
        "waiver not applied: area_mm2 400.00 exceeds its max_area_mm2 201.0"
        in overhang["detail"]
    )
    assert data["warnings"] == []
    assert "ell: assertion failed: overhang_max:45.0" in capsys.readouterr().err


def test_a_region_count_bound_catches_a_new_face_the_area_bound_misses(tmp_path: Path):
    with pytest.raises(SystemExit):
        inspect(
            _double_ledge(),
            method=FDM(),
            out=tmp_path,
            name="ell",
            waive={"overhang_max": Waiver(reason="one ledge", max_regions=1)},
        )
    data = json.loads((tmp_path / "ell-printability.json").read_text())
    (overhang,) = [a for a in data["assertions"] if a["name"].startswith("overhang")]
    assert overhang["waived"] is None
    assert "regions 2 exceeds its max_regions 1" in overhang["detail"]


def test_bound_wall_waiver_applies_at_or_above_its_floor(tmp_path: Path):
    result = inspect(
        _plate(20, 20, 1),
        method=FDM(wall_min_mm=5.0),
        out=tmp_path,
        name="plate",
        waive={"wall_min": Waiver(reason="1 mm skin, by design", min_wall_mm=1.0)},
    )
    assert result.status == "ok"
    (wall,) = [a for a in result.assertions if a.name.startswith("wall_min")]
    assert wall.waived == "1 mm skin, by design"


def test_a_thinner_wall_breaks_a_bound_wall_waiver(tmp_path: Path):
    with pytest.raises(SystemExit):
        inspect(
            _plate(20, 20, 1),
            method=FDM(wall_min_mm=5.0),
            out=tmp_path,
            name="plate",
            waive={"wall_min": Waiver(reason="2 mm skin", min_wall_mm=2.0)},
        )
    data = json.loads((tmp_path / "plate-printability.json").read_text())
    (wall,) = [a for a in data["assertions"] if a["name"].startswith("wall_min")]
    assert wall["waived"] is None
    assert "waiver not applied: min_wall_mm 1.0000 below its min_wall_mm 2.0" in (
        wall["detail"]
    )


def test_a_bound_waiver_whose_check_passes_is_stale(tmp_path: Path):
    result = inspect(
        _cube(10),
        method=FDM(),
        out=tmp_path,
        name="cube",
        waive={"wall_min": Waiver(reason="gone", min_wall_mm=1.0)},
    )
    (warning,) = result.warnings
    assert (warning.kind, warning.reason) == ("stale_waiver", "gone")


def test_a_bare_string_waiver_detail_is_unchanged(tmp_path: Path):
    inspect(
        _l_shape(),
        method=FDM(),
        out=tmp_path,
        name="ell",
        waive={"overhang_max": "ledge"},
    )
    data = json.loads((tmp_path / "ell-printability.json").read_text())
    (overhang,) = [a for a in data["assertions"] if a["name"].startswith("overhang")]
    assert overhang["waived"] == "ledge"
    assert "waiver" not in overhang["detail"]


def test_a_bound_for_another_kind_raises(tmp_path: Path):
    with pytest.raises(ValueError, match="max_area_mm2"):
        inspect(
            _plate(20, 20, 1),
            method=FDM(wall_min_mm=5.0),
            out=tmp_path,
            name="plate",
            waive={"wall_min": Waiver(reason="x", max_area_mm2=1.0)},
        )


# --- feature waivers ----------------------------------------------------


def _right_ledge():
    return Pos(15, 0, 5) * Box(10, 20, 4)


def _left_ledge():
    return Pos(-15, 0, -5) * Box(10, 20, 4)


def _ledged(**waivers):
    # _double_ledge's two ledges as features: each underside, 200 mm² at
    # 90°, lies on its own ledge block's bottom face.
    return {
        "right": Feature(_right_ledge(), waive=waivers.get("right", {})),
        "left": Feature(_left_ledge(), waive=waivers.get("left", {})),
    }


def _pocket(x: float, floor: float):
    return Pos(x, 0, floor / 2) * Box(8, 6, 10 - floor)


def _two_floors():
    # A 40×10×10 bar with two 8×6 pockets from the top: a 1.0 mm floor at
    # x = -10 and a 0.8 mm floor at x = +10. Every other wall is 2 mm.
    return _plate(40, 10, 10) - _pocket(-10, 1.0) - _pocket(10, 0.8)


_END = r"\((-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\) \[([^\]]*)\]"


def _worst_wall(detail: str) -> tuple[str, dict[float, tuple[str, float, float]], str]:
    """The worst unwaived wall in a detail: its thickness, each end keyed by
    its z (the features it traces to, and its x, y), and the reasons."""
    m = re.search(rf"worst wall (\S+) from {_END} to {_END}: (.*)$", detail)
    g = m.groups()
    ends = (g[1:5], g[5:9])
    return (
        g[0],
        {float(z): (names, float(x), float(y)) for x, y, z, names in ends},
        g[9],
    )


def _written(tmp_path: Path, name: str, kind: str) -> dict:
    data = json.loads((tmp_path / f"{name}-printability.json").read_text())
    (a,) = [a for a in data["assertions"] if a["name"].startswith(kind)]
    return a


def _warned(tmp_path: Path, name: str) -> list[dict]:
    return json.loads((tmp_path / f"{name}-printability.json").read_text())["warnings"]


def test_each_feature_waives_the_region_on_its_own_surface(tmp_path: Path):
    result = inspect(
        _double_ledge(),
        method=FDM(),
        out=tmp_path,
        name="ell",
        features=_ledged(
            right={"overhang_max": Waiver(reason="right ledge", max_area_mm2=201.0)},
            left={"overhang_max": Waiver(reason="left ledge", max_area_mm2=201.0)},
        ),
    )
    assert result.status == "ok"
    overhang = _written(tmp_path, "ell", "overhang")
    assert overhang["waived"] == "right: right ledge; left: left ledge"
    assert overhang["detail"].endswith(
        "waived by feature right (max_area_mm2 201.0), left (max_area_mm2 201.0)"
    )


def test_a_region_on_a_feature_that_does_not_waive_fails(tmp_path: Path):
    with pytest.raises(SystemExit):
        inspect(
            _double_ledge(),
            method=FDM(),
            out=tmp_path,
            name="ell",
            features=_ledged(right={"overhang_max": "right ledge"}),
        )
    overhang = _written(tmp_path, "ell", "overhang")
    assert overhang["waived"] is None
    assert overhang["detail"].endswith(
        "not waived: 1 region no feature waives, worst region 200.00mm² at "
        "(-15.00, 0.00, -7.00) [left]: left does not waive overhang_max"
    )


def test_a_region_on_no_feature_fails(tmp_path: Path):
    with pytest.raises(SystemExit):
        inspect(
            _double_ledge(),
            method=FDM(),
            out=tmp_path,
            name="ell",
            features={"right": Feature(_right_ledge(), waive={"overhang_max": "r"})},
        )
    assert _written(tmp_path, "ell", "overhang")["detail"].endswith(
        "worst region 200.00mm² at (-15.00, 0.00, -7.00) [none]: traces to no feature"
    )


def test_a_feature_bound_reads_only_that_features_regions(tmp_path: Path):
    with pytest.raises(SystemExit):
        inspect(
            _double_ledge(),
            method=FDM(),
            out=tmp_path,
            name="ell",
            features=_ledged(
                right={"overhang_max": Waiver(reason="r", max_area_mm2=150.0)},
                left={"overhang_max": Waiver(reason="l", max_area_mm2=201.0)},
            ),
        )
    assert _written(tmp_path, "ell", "overhang")["detail"].endswith(
        "(15.00, 0.00, 3.00) [right]: right's waiver not applied: area_mm2 200.00 "
        "exceeds its max_area_mm2 150.0"
    )


def test_a_bore_crown_traces_to_the_bore_not_the_block_it_was_cut_from(
    tmp_path: Path,
):
    bore = Rot(90, 0, 0) * Cylinder(3, 30)
    result = inspect(
        _plate(20, 20, 20) - bore,
        method=FDM(),
        out=tmp_path,
        name="bored",
        features={
            "body": Feature(_plate(20, 20, 20)),
            "bore": Feature(bore, waive={"overhang_max": "Ø6 crown, bridged"}),
        },
    )
    assert result.status == "ok"
    assert _written(tmp_path, "bored", "overhang")["waived"] == "bore: Ø6 crown, bridged"


def test_a_feature_waiver_nothing_traces_to_is_stale(tmp_path: Path):
    inspect(
        _l_shape(),
        method=FDM(),
        out=tmp_path,
        name="ell",
        features=_ledged(
            right={"overhang_max": "right ledge"}, left={"overhang_max": "gone"}
        ),
    )
    (stale,) = [w for w in _warned(tmp_path, "ell") if w["kind"] == "stale_waiver"]
    assert stale["reason"] == "gone"
    assert stale["detail"] == "no failure traces to feature left; remove its waiver"


def test_a_feature_waiver_on_a_passing_check_is_stale(tmp_path: Path):
    inspect(
        _cube(),
        method=FDM(),
        out=tmp_path,
        name="cube",
        features={"all": Feature(_cube(), waive={"overhang_max": "nothing"})},
    )
    (stale,) = _warned(tmp_path, "cube")
    assert stale["detail"] == "assertion passed; remove feature all's waiver"


def test_the_body_waiver_takes_what_the_features_leave(tmp_path: Path):
    result = inspect(
        _double_ledge(),
        method=FDM(),
        out=tmp_path,
        name="ell",
        features={"right": Feature(_right_ledge(), waive={"overhang_max": "r"})},
        waive={"overhang_max": "everything else"},
    )
    assert result.status == "ok"
    overhang = _written(tmp_path, "ell", "overhang")
    assert overhang["waived"] == "right: r; everything else"
    assert "1 region no feature waives" in overhang["detail"]


def test_a_thin_wall_is_waived_only_when_both_its_sides_waive(tmp_path: Path):
    features = {
        "bar": Feature(_plate(40, 10, 10), waive={"wall_min": "floors, by design"}),
        "pocket_a": Feature(_pocket(-10, 1.0)),
        "pocket_b": Feature(_pocket(10, 0.8), waive={"wall_min": "0.8 floor"}),
    }
    with pytest.raises(SystemExit):
        inspect(
            _two_floors(),
            method=FDM(wall_min_mm=1.5),
            out=tmp_path,
            name="bar",
            features=features,
        )
    wall = _written(tmp_path, "bar", "wall_min")
    assert wall["waived"] is None
    # The 1.0 floor spans z -5 (the bar's bottom) to -4 (pocket_a's floor).
    thickness, ends, reasons = _worst_wall(wall["detail"])
    assert thickness == "1.0000mm"
    assert {z: names for z, (names, _, _) in ends.items()} == {
        -5.0: "bar",
        -4.0: "pocket_a",
    }
    assert ends[-5.0][1:] == ends[-4.0][1:]
    assert -14 <= ends[-5.0][1] <= -6
    assert reasons == "pocket_a does not waive wall_min"


def test_a_wall_with_one_side_on_no_feature_fails(tmp_path: Path):
    with pytest.raises(SystemExit):
        inspect(
            _two_floors(),
            method=FDM(wall_min_mm=1.5),
            out=tmp_path,
            name="bar",
            features={
                "pocket_a": Feature(_pocket(-10, 1.0), waive={"wall_min": "a"}),
                "pocket_b": Feature(_pocket(10, 0.8), waive={"wall_min": "b"}),
            },
        )
    # The 0.8 floor spans z -5 (the bar's bottom, undeclared) to -4.2.
    thickness, ends, reasons = _worst_wall(
        _written(tmp_path, "bar", "wall_min")["detail"]
    )
    assert thickness == "0.8000mm"
    assert {z: names for z, (names, _, _) in ends.items()} == {
        -5.0: "none",
        -4.2: "pocket_b",
    }
    assert 6 <= ends[-5.0][1] <= 14
    assert reasons == "one side traces to no feature"


def test_a_wall_on_no_feature_and_a_refusing_one_names_both(tmp_path: Path):
    with pytest.raises(SystemExit):
        inspect(
            _two_floors(),
            method=FDM(wall_min_mm=1.5),
            out=tmp_path,
            name="bar",
            features={
                "pocket_a": Feature(_pocket(-10, 1.0), waive={"wall_min": "a"}),
                "pocket_b": Feature(_pocket(10, 0.8)),
            },
        )
    detail = _written(tmp_path, "bar", "wall_min")["detail"]
    assert re.search(r"not waived: \d+ readings no feature waives, worst", detail)
    thickness, ends, reasons = _worst_wall(detail)
    assert thickness == "0.8000mm"
    assert {z: names for z, (names, _, _) in ends.items()} == {
        -5.0: "none",
        -4.2: "pocket_b",
    }
    assert reasons == (
        "one side traces to no feature; pocket_b does not waive wall_min"
    )



def test_a_wall_with_neither_side_on_a_feature_says_so(tmp_path: Path):
    with pytest.raises(SystemExit):
        inspect(
            _two_floors(),
            method=FDM(wall_min_mm=1.5),
            out=tmp_path,
            name="bar",
            features={"pocket_a": Feature(_pocket(-10, 1.0), waive={"wall_min": "a"})},
        )
    thickness, ends, reasons = _worst_wall(
        _written(tmp_path, "bar", "wall_min")["detail"]
    )
    assert thickness == "0.8000mm"
    assert {z: names for z, (names, _, _) in ends.items()} == {
        -5.0: "none",
        -4.2: "none",
    }
    assert reasons == "neither side traces to a feature"

def test_every_thin_wall_waived_by_its_features_applies(tmp_path: Path):
    result = inspect(
        _two_floors(),
        method=FDM(wall_min_mm=1.5),
        out=tmp_path,
        name="bar",
        features={
            "bar": Feature(_plate(40, 10, 10), waive={"wall_min": "floors"}),
            "pocket_a": Feature(_pocket(-10, 1.0), waive={"wall_min": "a"}),
            "pocket_b": Feature(
                _pocket(10, 0.8), waive={"wall_min": Waiver(reason="b", min_wall_mm=0.79)}
            ),
        },
    )
    assert result.status == "ok"


def test_a_feature_cannot_waive_a_check_with_no_place(tmp_path: Path):
    with pytest.raises(ValueError, match="solid_count"):
        inspect(
            _two_bodies(),
            method=FDM(),
            out=tmp_path,
            name="pair",
            solid_count=1,
            features={"all": Feature(_cube(), waive={"solid_count": "x"})},
        )


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


def test_overhang_regions_land_in_the_json(tmp_path: Path):
    with pytest.raises(SystemExit):
        inspect(_l_shape(), method=FDM(), out=tmp_path, name="ell")
    data = json.loads((tmp_path / "ell-printability.json").read_text())
    (region,) = data["overhang"]["regions"]
    assert region["area_mm2"] == approx(200.0, rel=1e-6)
    assert region["max_angle_deg"] == approx(90.0, abs=1e-6)
    assert region["centroid_mm"] == approx([15.0, 0.0, 3.0], abs=1e-6)
    assert region["bbox"] == {
        "min": approx([10.0, -10.0, 3.0], abs=1e-6),
        "max": approx([20.0, 10.0, 3.0], abs=1e-6),
    }


def test_overhang_failure_detail_names_where_the_largest_region_is(tmp_path: Path):
    part = _l_shape() + Pos(-13, 0, 0) * Box(6, 10, 2)
    with pytest.raises(SystemExit):
        inspect(part, method=FDM(), out=tmp_path, name="ell")
    data = json.loads((tmp_path / "ell-printability.json").read_text())
    (failure,) = [a for a in data["assertions"] if a["name"].startswith("overhang_max")]
    assert "2 regions" in failure["detail"]
    assert "largest 200.00mm² at (15.00, 0.00, 3.00)" in failure["detail"]
