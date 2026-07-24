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
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
        .assert_no_interference("a", "b")
    )
    (result,) = evaluate(a)
    assert result.passed
    assert result.detail is None


def test_no_interference_passes_for_face_touching_parts():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((10, 0, 0)))
        .assert_no_interference("a", "b")
    )
    assert evaluate(a)[0].passed


def test_no_interference_fails_for_overlapping_parts():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b")
    )
    result = evaluate(a)[0]
    assert not result.passed
    assert "interference" in result.detail.lower()


def test_no_interference_default_name_contains_both_parts():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
        .assert_no_interference("a", "b")
    )
    name = evaluate(a)[0].name
    assert "a" in name and "b" in name


def test_no_interference_custom_name_is_respected():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
        .assert_no_interference("a", "b", name="custom_rule")
    )
    assert evaluate(a)[0].name == "custom_rule"


def test_clearance_passes_when_gap_exceeds_min():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
        .assert_clearance("a", "b", min_mm=5)
    )
    result = evaluate(a)[0]
    assert result.passed
    assert result.detail is None


def test_clearance_fails_when_gap_below_min():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((12, 0, 0)))
        .assert_clearance("a", "b", min_mm=5)
    )
    result = evaluate(a)[0]
    assert not result.passed
    assert "clearance" in result.detail.lower()


def test_clearance_fails_when_parts_touch():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((10, 0, 0)))
        .assert_clearance("a", "b", min_mm=0.2)
    )
    assert not evaluate(a)[0].passed


def test_clearance_fails_when_parts_interfere():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((5, 0, 0)))
        .assert_clearance("a", "b", min_mm=0.2)
    )
    assert not evaluate(a)[0].passed


def test_interference_passes_for_overlapping_parts():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((5, 0, 0)))
        .assert_interference("a", "b")
    )
    result = evaluate(a)[0]
    assert result.passed
    assert result.detail is None


def test_interference_fails_for_separated_parts():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
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
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((10, 0, 0)))
        .assert_interference("a", "b")
    )
    assert not evaluate(a)[0].passed


def test_interference_reason_appears_in_failure_detail():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
        .assert_interference("a", "b", reason="junction design pending")
    )
    result = evaluate(a)[0]
    assert not result.passed
    assert "junction design pending" in result.detail


def test_interference_default_name_contains_both_parts():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((5, 0, 0)))
        .assert_interference("a", "b")
    )
    name = evaluate(a)[0].name
    assert "a" in name and "b" in name


def test_interference_custom_name_is_respected():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((5, 0, 0)))
        .assert_interference("a", "b", name="custom_rule")
    )
    assert evaluate(a)[0].name == "custom_rule"


def test_multiple_assertions_all_evaluated_in_order():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
        .assert_no_interference("a", "b", name="first")
        .assert_clearance("a", "b", min_mm=5, name="second")
    )
    results = evaluate(a)
    assert [r.name for r in results] == ["first", "second"]
    assert all(r.passed for r in results)


def test_failures_and_passes_coexist():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b")
        .assert_clearance("a", "b", min_mm=0.2)
    )
    results = evaluate(a)
    assert len(results) == 2
    assert all(not r.passed for r in results)


def test_assertion_against_absent_part_is_skipped():
    # A detail-only assertion (e.g. against a fastener applied by an
    # override) must not crash a standalone run that lacks the part.
    a = Assembly().with_part("a", _cube()).assert_no_interference("a", "bolt")
    (result,) = evaluate(a)
    assert result.passed is None
    assert "skipped" in result.detail
    assert "bolt" in result.detail


def test_clearance_against_absent_part_is_skipped():
    a = Assembly().with_part("a", _cube()).assert_clearance("a", "bolt", min_mm=0.2)
    (result,) = evaluate(a)
    assert result.passed is None


def test_expected_interference_against_absent_part_is_skipped():
    a = Assembly().with_part("a", _cube()).assert_interference("a", "bolt")
    (result,) = evaluate(a)
    assert result.passed is None


def test_skip_detail_names_every_missing_part():
    a = Assembly().with_part("a", _cube()).assert_clearance("bolt", "nut", min_mm=1)
    (result,) = evaluate(a)
    assert "bolt" in result.detail and "nut" in result.detail


def test_skipped_and_failed_assertions_coexist():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((5, 0, 0)))
        .assert_no_interference("a", "b", name="real_failure")
        .assert_clearance("a", "bolt", min_mm=0.2, name="detail_only")
    )
    by_name = {r.name: r for r in evaluate(a)}
    assert by_name["real_failure"].passed is False
    assert by_name["detail_only"].passed is None


def test_anchors_coincident_passes_when_beliefs_agree():
    # Two units each export their belief of a shared datum in their
    # own frame; the parent composes and asserts coincidence.
    deck = Assembly().with_anchor("top", Location((0, 0, 890)))
    chain = Assembly().with_anchor("deck_top", Location((0, 0, -140)))
    top = (
        Assembly()
        .with_subassembly("m05", deck)
        .with_subassembly("chain", chain, location=Location((0, 0, 1030)))
        .assert_anchors_coincident("m05.top", "chain.deck_top")
    )
    (result,) = evaluate(top)
    assert result.passed
    assert result.name == "anchors_coincident:m05.top/chain.deck_top"


def test_anchors_coincident_fails_on_drift_with_distance_detail():
    deck = Assembly().with_anchor("top", Location((0, 0, 890)))
    chain = Assembly().with_anchor("deck_top", Location((0, 0, -150)))
    top = (
        Assembly()
        .with_subassembly("m05", deck)
        .with_subassembly("chain", chain, location=Location((0, 0, 1030)))
        .assert_anchors_coincident("m05.top", "chain.deck_top")
    )
    (result,) = evaluate(top)
    assert not result.passed
    assert "10.000000mm" in result.detail


def test_anchors_coincident_tolerance_is_respected():
    a = (
        Assembly()
        .with_anchor("x", Location((0, 0, 0)))
        .with_anchor("y", Location((0.05, 0, 0)))
        .assert_anchors_coincident("x", "y", tol_mm=0.1)
    )
    (result,) = evaluate(a)
    assert result.passed


def test_anchors_coincident_honors_joint_angle_applied_after_declaration():
    # The assertion re-resolves at evaluate time: declaring at angle 0
    # then rotating the jointed subtree moves its anchor off target.
    from cad_khana.mechanism.assembly import RevoluteJoint
    from build123d import Axis

    unit = Assembly().with_anchor("tip", Location((10, 0, 0)))
    top = (
        Assembly()
        .with_anchor("target", Location((10, 0, 0)))
        .with_subassembly(
            "arm", unit, joint=RevoluteJoint(axis=Axis.Z, frame="local")
        )
        .assert_anchors_coincident("target", "arm.tip")
    )
    (at_rest,) = evaluate(top)
    assert at_rest.passed
    (rotated,) = evaluate(top.with_joint_angle("arm", 90.0))
    assert not rotated.passed
