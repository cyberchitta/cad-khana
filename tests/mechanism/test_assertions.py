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


# --- assert_tangent_contact ---------------------------------------------


def test_tangent_contact_passes_for_face_touching_parts():
    a = (
        Assembly()
        .with_part("foot", _cube())
        .with_part("rail", _cube(), location=Location((10, 0, 0)))
        .assert_tangent_contact("foot", "rail")
    )
    (result,) = evaluate(a)
    assert result.passed
    assert result.detail is None
    assert abs(result.value) < 1e-6


def test_tangent_contact_fails_on_gap_with_gap_in_detail():
    # The case assert_no_interference can't see: a rest that floated
    # 3 mm off its support still passes the no-overlap check.
    a = (
        Assembly()
        .with_part("foot", _cube())
        .with_part("rail", _cube(), location=Location((13, 0, 0)))
        .assert_tangent_contact("foot", "rail")
    )
    (result,) = evaluate(a)
    assert result.passed is False
    assert "gap" in result.detail
    assert abs(result.value - 3.0) < 1e-6


def test_tangent_contact_fails_on_overlap():
    a = (
        Assembly()
        .with_part("foot", _cube())
        .with_part("rail", _cube(), location=Location((5, 0, 0)))
        .assert_tangent_contact("foot", "rail")
    )
    (result,) = evaluate(a)
    assert result.passed is False
    assert "overlap" in result.detail


def test_tangent_contact_tol_absorbs_placement_noise():
    a = (
        Assembly()
        .with_part("foot", _cube())
        .with_part("rail", _cube(), location=Location((10.0005, 0, 0)))
        .assert_tangent_contact("foot", "rail")
    )
    assert evaluate(a)[0].passed


def test_tangent_contact_gap_above_tol_fails():
    a = (
        Assembly()
        .with_part("foot", _cube())
        .with_part("rail", _cube(), location=Location((10.1, 0, 0)))
        .assert_tangent_contact("foot", "rail")
    )
    assert evaluate(a)[0].passed is False


def test_tangent_contact_custom_tol_is_respected():
    a = (
        Assembly()
        .with_part("foot", _cube())
        .with_part("rail", _cube(), location=Location((10.1, 0, 0)))
        .assert_tangent_contact("foot", "rail", tol_mm=0.2)
    )
    assert evaluate(a)[0].passed


def test_tangent_contact_against_absent_part_is_skipped():
    a = Assembly().with_part("a", _cube()).assert_tangent_contact("a", "bolt")
    (result,) = evaluate(a)
    assert result.passed is None
    assert "bolt" in result.detail


def test_tangent_contact_auto_name():
    a = (
        Assembly()
        .with_part("foot", _cube())
        .with_part("rail", _cube(), location=Location((10, 0, 0)))
        .assert_tangent_contact("foot", "rail")
    )
    assert evaluate(a)[0].name == "tangent_contact:foot/rail"


# --- assert_allowed_contact ---------------------------------------------


def test_allowed_contact_passes_within_max_and_records_volume():
    # 1 mm penetration of 10x10 faces: 100 mm^3 of intended overlap.
    a = (
        Assembly()
        .with_part("shaft", _cube())
        .with_part("bore", _cube(), location=Location((9, 0, 0)))
        .assert_allowed_contact("shaft", "bore", max_overlap_mm3=150)
    )
    (result,) = evaluate(a)
    assert result.passed
    assert result.detail is None
    assert abs(result.value - 100.0) < 1e-3


def test_allowed_contact_fails_above_max():
    a = (
        Assembly()
        .with_part("shaft", _cube())
        .with_part("bore", _cube(), location=Location((9, 0, 0)))
        .assert_allowed_contact("shaft", "bore", max_overlap_mm3=50)
    )
    (result,) = evaluate(a)
    assert result.passed is False
    assert "above max" in result.detail


def test_allowed_contact_gap_passes_without_min():
    # Contact is allowed, not required.
    a = (
        Assembly()
        .with_part("shaft", _cube())
        .with_part("bore", _cube(), location=Location((20, 0, 0)))
        .assert_allowed_contact("shaft", "bore", max_overlap_mm3=150)
    )
    (result,) = evaluate(a)
    assert result.passed
    assert result.value == 0.0


def test_allowed_contact_min_makes_engagement_the_claim():
    # A press-fit drifting back to a clearance fit must fail loudly —
    # the original workaround modeled the bore oversize to appease
    # assert_no_interference, and nothing caught the lie.
    a = (
        Assembly()
        .with_part("shaft", _cube())
        .with_part("bore", _cube(), location=Location((20, 0, 0)))
        .assert_allowed_contact(
            "shaft", "bore", max_overlap_mm3=150, min_overlap_mm3=50
        )
    )
    (result,) = evaluate(a)
    assert result.passed is False
    assert "below min" in result.detail


def test_allowed_contact_reason_appears_in_failure_detail():
    a = (
        Assembly()
        .with_part("shaft", _cube())
        .with_part("bore", _cube(), location=Location((9, 0, 0)))
        .assert_allowed_contact(
            "shaft", "bore", max_overlap_mm3=50, reason="press fit"
        )
    )
    (result,) = evaluate(a)
    assert "press fit" in result.detail


def test_allowed_contact_bound_tolerates_solver_noise():
    a = (
        Assembly()
        .with_part("shaft", _cube())
        .with_part("bore", _cube(), location=Location((9, 0, 0)))
        .assert_allowed_contact("shaft", "bore", max_overlap_mm3=100 - 1e-9)
    )
    assert evaluate(a)[0].passed


def test_allowed_contact_against_absent_part_is_skipped():
    a = (
        Assembly()
        .with_part("a", _cube())
        .assert_allowed_contact("a", "bolt", max_overlap_mm3=1)
    )
    (result,) = evaluate(a)
    assert result.passed is None


def test_allowed_contact_auto_name_carries_bounds():
    a = (
        Assembly()
        .with_part("shaft", _cube())
        .with_part("bore", _cube(), location=Location((9, 0, 0)))
        .assert_allowed_contact(
            "shaft", "bore", max_overlap_mm3=150, min_overlap_mm3=50
        )
    )
    assert evaluate(a)[0].name == "allowed_contact:shaft/bore>=50<=150"


# --- assert_distance ----------------------------------------------------


def test_distance_min_bound_passes_and_records_value():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
        .assert_distance("a", "b", min_mm=5)
    )
    (result,) = evaluate(a)
    assert result.passed
    assert result.detail is None
    assert abs(result.value - 10.0) < 1e-6


def test_distance_max_bound_fails_when_too_far():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
        .assert_distance("a", "b", max_mm=5)
    )
    (result,) = evaluate(a)
    assert result.passed is False
    assert "above max" in result.detail
    assert abs(result.value - 10.0) < 1e-6


def test_distance_min_max_band_expresses_close_but_not_touching():
    a = (
        Assembly()
        .with_part("gear", _cube())
        .with_part("pinion", _cube(), location=Location((10.2, 0, 0)))
        .assert_distance("gear", "pinion", min_mm=0.15, max_mm=0.25)
    )
    (result,) = evaluate(a)
    assert result.passed
    assert abs(result.value - 0.2) < 1e-6


def test_distance_along_measures_directed_gap():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((0, 0, 20)))
        .assert_distance("a", "b", along="Z", min_mm=5)
    )
    (result,) = evaluate(a)
    assert result.passed
    assert abs(result.value - 10.0) < 1e-6


def test_distance_along_is_negative_when_projections_overlap():
    # Euclidean gap is 2 mm, but the Z projections coincide entirely.
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((12, 0, 0)))
        .assert_distance("a", "b", along="Z", min_mm=1)
    )
    (result,) = evaluate(a)
    assert result.passed is False
    assert abs(result.value - (-10.0)) < 1e-6


def test_distance_to_plane_directed():
    from build123d import Plane

    a = (
        Assembly()
        .with_part("ramp", _cube(), location=Location((0, 0, 20)))
        .assert_distance("ramp", Plane.XY.offset(5), along="-Z", min_mm=5)
    )
    (result,) = evaluate(a)
    assert result.passed
    assert abs(result.value - 10.0) < 1e-6


def test_distance_to_plane_undirected_is_zero_when_crossing():
    from build123d import Plane

    a = (
        Assembly()
        .with_part("a", _cube())
        .assert_distance("a", Plane.XY, min_mm=1)
    )
    (result,) = evaluate(a)
    assert result.passed is False
    assert result.value == 0.0


def test_distance_grow_measures_from_offset_surface():
    a = (
        Assembly()
        .with_part("pinion", _cube())
        .with_part("rails", _cube(), location=Location((20, 0, 0)))
        .assert_distance("pinion", "rails", min_mm=1, grow_a_mm=3)
    )
    (result,) = evaluate(a)
    assert result.passed
    assert abs(result.value - 7.0) < 1e-6


def test_distance_against_absent_part_is_skipped():
    a = Assembly().with_part("a", _cube()).assert_distance("a", "bolt", min_mm=1)
    (result,) = evaluate(a)
    assert result.passed is None
    assert "bolt" in result.detail


def test_distance_to_plane_with_absent_part_is_skipped():
    from build123d import Plane

    a = (
        Assembly()
        .with_part("a", _cube())
        .assert_distance("ghost", Plane.XY, min_mm=1)
    )
    (result,) = evaluate(a)
    assert result.passed is None
    assert "ghost" in result.detail


def test_distance_requires_at_least_one_bound():
    import pytest

    with pytest.raises(ValueError, match="min_mm and/or max_mm"):
        Assembly().with_part("a", _cube()).assert_distance("a", "b")


def test_distance_plane_along_must_be_parallel_to_normal():
    import pytest
    from build123d import Plane

    with pytest.raises(ValueError, match="parallel to the plane normal"):
        Assembly().with_part("a", _cube()).assert_distance(
            "a", Plane.XY, along="X", min_mm=1
        )


def test_distance_auto_name_carries_pair_axis_and_bounds():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
        .assert_distance("a", "b", along="-Z", min_mm=1, max_mm=2)
    )
    name = evaluate(a)[0].name
    assert name == "distance:a/b@-Z>=1<=2"


# --- assert_scalar ------------------------------------------------------


def test_scalar_claim_passes_within_bound_and_records_value():
    a = Assembly().assert_scalar("slide_margin", 0.5, ge=0.35)
    (result,) = evaluate(a)
    assert result.passed
    assert result.value == 0.5
    assert result.detail is None


def test_scalar_claim_fails_below_ge_with_context():
    a = Assembly().assert_scalar(
        "slide_margin", 0.3, ge=0.35, detail="µ_s budget, ABS on PLA"
    )
    (result,) = evaluate(a)
    assert result.passed is False
    assert "below ge" in result.detail
    assert "µ_s budget" in result.detail


def test_scalar_claim_without_bounds_is_a_recorder():
    a = Assembly().assert_scalar("ratio", 3.75, detail="belt reduction")
    (result,) = evaluate(a)
    assert result.passed
    assert result.value == 3.75
    assert result.detail == "belt reduction"


# --- sub-assembly assertion propagation ---------------------------------


def test_subassembly_assertions_evaluate_qualified_in_composed_run():
    unit = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
        .assert_clearance("a", "b", min_mm=5)
    )
    top = Assembly().with_subassembly("u", unit, location=Location((0, 0, 50)))
    (result,) = evaluate(top)
    assert result.passed
    assert result.name == "u.clearance:a/b>=5"


def test_subassembly_plane_target_tracks_placement():
    # Declared once in the unit's frame; the same claim must hold when
    # the unit is placed elsewhere, because the plane moves with it.
    from build123d import Plane

    unit = (
        Assembly()
        .with_part("ramp", _cube())
        .assert_distance("ramp", Plane.XY.offset(-10), along="-Z", min_mm=5)
    )
    (standalone,) = evaluate(unit)
    top = Assembly().with_subassembly("m05", unit, location=Location((0, 0, 100)))
    (composed,) = evaluate(top)
    assert standalone.passed and composed.passed
    assert abs(standalone.value - composed.value) < 1e-6
    assert composed.name == "m05." + standalone.name


def test_subassembly_contact_assertions_qualify_when_composed():
    unit = (
        Assembly()
        .with_part("foot", _cube())
        .with_part("rail", _cube(), location=Location((10, 0, 0)))
        .assert_tangent_contact("foot", "rail")
    )
    top = Assembly().with_subassembly("u", unit, location=Location((0, 0, 50)))
    (result,) = evaluate(top)
    assert result.passed
    assert result.name == "u.tangent_contact:foot/rail"


def test_subassembly_detail_only_assertion_skips_when_composed():
    unit = (
        Assembly()
        .with_part("a", _cube())
        .assert_clearance("a", "bolt", min_mm=0.2)
    )
    top = Assembly().with_subassembly("u", unit)
    (result,) = evaluate(top)
    assert result.passed is None
    assert "u.bolt" in result.detail


# --- bound-comparison epsilon -------------------------------------------


def test_distance_bound_tolerates_solver_noise():
    # The common consumer pattern: geometry placed *from* the bound
    # constant, so measured == bound ± solver noise (1e-14 boolean
    # noise, ~1e-7 bbox slop observed in the field).
    a = (
        Assembly()
        .with_part("gear", _cube())
        .with_part("pinion", _cube(), location=Location((10.2, 0, 0)))
        .assert_distance("gear", "pinion", min_mm=0.2 + 1e-9)
    )
    (result,) = evaluate(a)
    assert result.passed


def test_distance_epsilon_does_not_mask_real_violations():
    a = (
        Assembly()
        .with_part("gear", _cube())
        .with_part("pinion", _cube(), location=Location((10.2, 0, 0)))
        .assert_distance("gear", "pinion", min_mm=0.21)
    )
    (result,) = evaluate(a)
    assert result.passed is False


def test_distance_max_bound_tolerates_solver_noise():
    a = (
        Assembly()
        .with_part("gear", _cube())
        .with_part("pinion", _cube(), location=Location((10.2, 0, 0)))
        .assert_distance("gear", "pinion", max_mm=0.2 - 1e-9)
    )
    (result,) = evaluate(a)
    assert result.passed


def test_clearance_bound_tolerates_solver_noise():
    a = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
        .assert_clearance("a", "b", min_mm=10 + 1e-9)
    )
    (result,) = evaluate(a)
    assert result.passed


def test_scalar_bound_tolerates_float_noise():
    a = Assembly().assert_scalar("margin", 0.2 - 1e-9, ge=0.2)
    (result,) = evaluate(a)
    assert result.passed


def test_scalar_epsilon_does_not_mask_real_violations():
    a = Assembly().assert_scalar("margin", 0.19, ge=0.2)
    (result,) = evaluate(a)
    assert result.passed is False
