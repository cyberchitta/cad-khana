"""`show` reads the diagnostics JSON the library actually writes.

The fixtures are real ``check()`` / ``inspect()`` output, so the reader
is tested against the files agents hold, not a hand-written guess at
their shape.
"""

import json

import pytest
from build123d import Box, BuildPart, Location

from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.check import check
from cad_khana.mechanism.diagnostics import SCHEMA_VERSION
from cad_khana.printability.inspect import inspect
from cad_khana.printability.methods import FDM
from cad_khana.show import (
    by_value,
    group,
    require_diagnostics,
    row,
    select,
    state,
    summary,
)


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


@pytest.fixture(scope="module")
def mech(tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = tmp_path_factory.mktemp("mech")
    assembly = (
        Assembly()
        .with_part("a", _cube(), location=Location((0, 0, 0)))
        .with_part("b", _cube(), location=Location((15, 0, 0)))
        .with_part("c", _cube(), location=Location((0, 13, 0)))
        .assert_distance("a", "b", min_mm=0.2, name="gap.wide:a/b")
        .assert_distance("a", "c", min_mm=0.2, name="gap.narrow:a/c")
        .assert_distance("a", "b", min_mm=10.0, name="tight:a/b")
        .assert_no_interference("b", "c", name="gap.clear:b/c")
        .assert_distance("a", "bolt", min_mm=0.2, name="detail_only")
    )
    with pytest.raises(SystemExit):
        check(assembly, out=out)
    return json.loads((out / "mechanism.json").read_text())


@pytest.fixture(scope="module")
def partial(tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = tmp_path_factory.mktemp("partial")
    assembly = (
        Assembly()
        .with_part("a", _cube(), location=Location((0, 0, 0)))
        .with_part("b", _cube(), location=Location((15, 0, 0)))
        .assert_distance("a", "b", min_mm=0.2, name="gap:a/b")
        .assert_no_interference("a", "b", name="clear:a/b")
    )
    check(assembly, out=out, only=("gap:*",))
    return json.loads((out / "mechanism.json").read_text())


@pytest.fixture(scope="module")
def printability(tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = tmp_path_factory.mktemp("print")
    inspect(
        _cube(1),
        method=FDM(wall_min_mm=5.0),
        out=out,
        name="plate",
        waive={"wall_min": "thin by design"},
    )
    return json.loads((out / "plate-printability.json").read_text())


def _names(assertions: list[dict]) -> list[str]:
    return [a["name"] for a in assertions]


def _named(diag: dict, name: str) -> dict:
    return next(a for a in diag["assertions"] if a["name"] == name)


# --- state ----------------------------------------------------------------


def test_state_reads_each_verdict_off_real_output(mech: dict, printability: dict):
    assert state(_named(mech, "gap.wide:a/b")) == "passed"
    assert state(_named(mech, "tight:a/b")) == "failed"
    assert state(_named(mech, "detail_only")) == "skipped"
    (wall,) = [
        a for a in printability["assertions"] if a["name"].startswith("wall_min")
    ]
    assert state(wall) == "waived"


# --- select ---------------------------------------------------------------


def test_grep_is_a_regex_search_on_the_name(mech: dict):
    assert _names(select(mech["assertions"], grep=r"^gap\.")) == [
        "gap.wide:a/b",
        "gap.narrow:a/c",
        "gap.clear:b/c",
    ]
    assert _names(select(mech["assertions"], grep="a/")) == [
        "gap.wide:a/b",
        "gap.narrow:a/c",
        "tight:a/b",
    ]


def test_failed_excludes_a_waived_failure(printability: dict):
    assert select(printability["assertions"], states=frozenset({"failed"})) == []
    assert len(select(printability["assertions"], states=frozenset({"waived"}))) == 1


def test_state_filters_are_a_union_and_grep_narrows_them(mech: dict):
    both = frozenset({"failed", "skipped"})
    assert _names(select(mech["assertions"], states=both)) == [
        "tight:a/b",
        "detail_only",
    ]
    assert _names(select(mech["assertions"], grep="tight", states=both)) == [
        "tight:a/b"
    ]


def test_no_filter_keeps_file_order(mech: dict):
    assert select(mech["assertions"]) == mech["assertions"]


# --- sort -----------------------------------------------------------------


def test_by_value_is_ascending_with_valueless_claims_last(mech: dict):
    ordered = _names(by_value(mech["assertions"]))
    assert ordered[:3] == ["gap.narrow:a/c", "gap.wide:a/b", "tight:a/b"]
    assert set(ordered[3:]) == {"gap.clear:b/c", "detail_only"}


# --- group ----------------------------------------------------------------


def test_group_keys_on_the_regex_match_and_reports_the_minimum(mech: dict):
    groups = {g.key: g for g in group(mech["assertions"], r"^[^.:]+")}
    assert set(groups) == {"gap", "tight", "detail_only"}
    gap = groups["gap"]
    assert (gap.count, gap.failed, gap.skipped) == (3, 0, 0)
    assert gap.min_value == pytest.approx(3.0)
    assert gap.min_name == "gap.narrow:a/c"
    assert groups["tight"].failed == 1
    assert groups["detail_only"].skipped == 1
    assert groups["detail_only"].min_value is None


def test_group_key_is_the_first_capture_group_when_there_is_one(mech: dict):
    keys = [g.key for g in group(mech["assertions"], r":(\w)/")]
    assert keys == ["a", "b", "(unmatched)"]


def test_names_the_pattern_misses_are_grouped_not_dropped(mech: dict):
    groups = {g.key: g for g in group(mech["assertions"], r"^gap")}
    assert groups["(unmatched)"].count == 2


# --- rows and summary -----------------------------------------------------


def test_row_carries_marker_value_name_and_detail(mech: dict):
    line = row(_named(mech, "tight:a/b"))
    assert line.startswith("FAIL")
    assert "5" in line and "tight:a/b" in line
    assert "min" in line


def test_row_truncates_a_long_detail():
    long = {"name": "x", "passed": False, "detail": "y" * 500, "value": None}
    assert len(row(long, width=80)) <= 80 + len("FAIL") + 32


def test_summary_counts_every_verdict(mech: dict):
    text = summary(mech)
    assert "status: assertion_failed" in text
    assert "5 assertions: 3 passed, 1 failed, 0 waived, 1 skipped" in text
    assert "absent_part 1" in text


def test_summary_lists_warnings_by_kind(printability: dict):
    text = summary(printability)
    assert "printability: plate" in text
    assert "waived_failure 1" in text
    assert "min_wall_mm" in text


def test_summary_names_an_old_schema_rather_than_refusing_it(mech: dict):
    old = mech | {"schema_version": "0.1"}
    text = summary(old)
    assert "0.1" in text and SCHEMA_VERSION in text


def test_a_field_an_old_file_lacks_reads_absent_not_a_default(mech: dict):
    old = {
        k: v
        for k, v in mech.items()
        if k not in {"interferences", "motions", "parts", "warnings"}
    }
    text = summary(old)
    assert "parts absent  interferences absent  motions absent" in text
    assert "warnings: absent" in text


def test_a_printability_field_an_old_file_lacks_reads_absent(printability: dict):
    old = {
        k: v
        for k, v in printability.items()
        if k not in {"min_wall_mm", "overhang", "solid_count"}
    }
    text = summary(old)
    assert "min_wall_mm absent" in text
    assert "area_mm2 absent max_angle_deg absent" in text
    assert "solid_count absent" in text


def test_a_file_that_is_not_diagnostics_is_refused():
    with pytest.raises(ValueError):
        require_diagnostics({"foo": 1})
    with pytest.raises(ValueError):
        require_diagnostics([1, 2])


def test_summary_says_a_partial_run_is_partial(partial: dict):
    text = summary(partial)
    assert "partial run: 1 of 2 assertions (only gap:*)" in text
    assert "interferences not computed" in text
