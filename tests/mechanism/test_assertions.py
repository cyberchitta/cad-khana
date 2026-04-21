from build123d import Box, BuildPart, Location

from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.assertions import evaluate


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def test_empty_assembly_produces_no_results():
    assert evaluate(Assembly()) == ()


def test_no_interference_passes_for_separated_parts():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((20, 0, 0)))
        .assert_no_interference("a", "b")
    )
    (result,) = evaluate(a)
    assert result.passed
    assert result.detail is None


def test_no_interference_passes_for_face_touching_parts():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((10, 0, 0)))
        .assert_no_interference("a", "b")
    )
    assert evaluate(a)[0].passed


def test_no_interference_fails_for_overlapping_parts():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b")
    )
    result = evaluate(a)[0]
    assert not result.passed
    assert "interference" in result.detail.lower()


def test_no_interference_default_name_contains_both_parts():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((20, 0, 0)))
        .assert_no_interference("a", "b")
    )
    name = evaluate(a)[0].name
    assert "a" in name and "b" in name


def test_no_interference_custom_name_is_respected():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((20, 0, 0)))
        .assert_no_interference("a", "b", name="custom_rule")
    )
    assert evaluate(a)[0].name == "custom_rule"


def test_clearance_passes_when_gap_exceeds_min():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((20, 0, 0)))
        .assert_clearance("a", "b", min_mm=5)
    )
    result = evaluate(a)[0]
    assert result.passed
    assert result.detail is None


def test_clearance_fails_when_gap_below_min():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((12, 0, 0)))
        .assert_clearance("a", "b", min_mm=5)
    )
    result = evaluate(a)[0]
    assert not result.passed
    assert "clearance" in result.detail.lower()


def test_clearance_fails_when_parts_touch():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((10, 0, 0)))
        .assert_clearance("a", "b", min_mm=0.2)
    )
    assert not evaluate(a)[0].passed


def test_clearance_fails_when_parts_interfere():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((5, 0, 0)))
        .assert_clearance("a", "b", min_mm=0.2)
    )
    assert not evaluate(a)[0].passed


def test_interference_passes_for_overlapping_parts():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((5, 0, 0)))
        .assert_interference("a", "b")
    )
    result = evaluate(a)[0]
    assert result.passed
    assert result.detail is None


def test_interference_fails_for_separated_parts():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((20, 0, 0)))
        .assert_interference("a", "b")
    )
    result = evaluate(a)[0]
    assert not result.passed
    assert "expected interference absent" in result.detail.lower()


def test_interference_fails_for_face_touching_parts():
    # Face-touching has zero intersection volume, so the regression
    # alarm should fire — the overlap this assertion was guarding is
    # no longer there.
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((10, 0, 0)))
        .assert_interference("a", "b")
    )
    assert not evaluate(a)[0].passed


def test_interference_reason_appears_in_failure_detail():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((20, 0, 0)))
        .assert_interference("a", "b", reason="junction design pending")
    )
    result = evaluate(a)[0]
    assert not result.passed
    assert "junction design pending" in result.detail


def test_interference_default_name_contains_both_parts():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((5, 0, 0)))
        .assert_interference("a", "b")
    )
    name = evaluate(a)[0].name
    assert "a" in name and "b" in name


def test_interference_custom_name_is_respected():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((5, 0, 0)))
        .assert_interference("a", "b", name="custom_rule")
    )
    assert evaluate(a)[0].name == "custom_rule"


def test_multiple_assertions_all_evaluated_in_order():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((20, 0, 0)))
        .assert_no_interference("a", "b", name="first")
        .assert_clearance("a", "b", min_mm=5, name="second")
    )
    results = evaluate(a)
    assert [r.name for r in results] == ["first", "second"]
    assert all(r.passed for r in results)


def test_failures_and_passes_coexist():
    a = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b")
        .assert_clearance("a", "b", min_mm=0.2)
    )
    results = evaluate(a)
    assert len(results) == 2
    assert all(not r.passed for r in results)
