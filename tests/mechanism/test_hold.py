import pytest
from build123d import Axis, Box, BuildPart, Location, Plane

from cad_khana.mechanism.assembly import Assembly, RevoluteJoint
from cad_khana.mechanism.assertions import JointWindow
from cad_khana.mechanism.diagnostics import JointRange, PoseCounts, WorstAt
from cad_khana.mechanism.hold import hold
from cad_khana.mechanism.motion import Motion


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def _swung() -> Assembly:
    """A cube on a Z revolute joint, built clear of a fixed post at
    0deg; it starts to overlap the post past ~45deg and coincides with
    it at 90deg. A second fixed cube, ``base``, is far from both."""
    arm = (
        Assembly()
        .with_part("arm", _cube(), location=Location((20, 0, 0)))
        .with_part("tip", _cube(2), location=Location((40, 0, 0)))
    )
    return (
        Assembly()
        .with_part("post", _cube(), location=Location((0, 20, 0)))
        .with_part("base", _cube(), location=Location((0, 0, -50)))
        .with_subassembly("swing", arm, joint=RevoluteJoint(axis=Axis.Z))
    )


def _swing(hi: float, step: float = 15.0) -> Motion:
    return Motion.over_joint("swing_in", "swing", 0.0, hi, step)


def _only(assembly: Assembly):
    (result,) = hold(assembly).assertions
    return result


def test_no_motion_is_one_pose():
    result = _only(_swung().assert_no_interference("post", "swing.arm"))
    assert result.passed
    assert result.poses == PoseCounts(evaluated=1, distinct=1, in_phase=1, failed=0)
    assert result.worst_at is None


def test_a_claim_green_as_built_fails_over_the_motion_that_breaks_it():
    a = (
        _swung()
        .assert_no_interference("post", "swing.arm")
        .with_motion(_swing(90))
    )
    result = _only(a)
    assert result.passed is False
    assert result.poses.evaluated == 8  # as built + 7 samples
    assert result.poses.failed == 3  # 60, 75, 90deg
    assert result.worst_at.motion == "swing_in"
    assert result.worst_at.joints_deg == {"swing": pytest.approx(60.0)}
    assert "3 of 8 poses" in result.detail


def test_a_claim_the_motion_never_moves_is_evaluated_once():
    a = (
        _swung()
        .assert_no_interference("post", "base")
        .with_motion(_swing(90))
    )
    result = _only(a)
    assert result.passed
    assert result.poses == PoseCounts(evaluated=8, distinct=1, in_phase=8, failed=0)


def test_parts_that_move_together_are_evaluated_once():
    a = (
        _swung()
        .assert_no_interference("swing.arm", "swing.tip")
        .with_motion(_swing(90))
    )
    assert _only(a).poses.distinct == 1


def test_a_pose_met_twice_is_evaluated_once():
    a = (
        _swung()
        .assert_no_interference("base", "swing.arm")
        .with_motion(Motion.over_joint("turn", "swing", 0.0, 360.0, step=90.0))
    )
    # as built, 0, 90, 180, 270, 360 — three of them the same pose
    assert _only(a).poses == PoseCounts(
        evaluated=6, distinct=4, in_phase=6, failed=0
    )


def test_value_is_the_worst_over_the_motion_and_says_where():
    a = (
        _swung()
        .assert_distance("post", "swing.arm", min_mm=1.0)
        .with_motion(_swing(30))
    )
    result = _only(a)
    assert result.passed
    assert result.value < 200**0.5  # closer than as built
    assert result.worst_at == WorstAt(
        motion="swing_in", t=1.0, joints_deg={"swing": pytest.approx(30.0)}
    )


def test_worst_is_the_as_built_pose_when_the_motion_only_helps():
    a = (
        _swung()
        .assert_distance("post", "swing.arm", min_mm=1.0)
        .with_motion(Motion.over_joint("away", "swing", 0.0, -30.0, step=15.0))
    )
    result = _only(a)
    assert result.value == pytest.approx(200**0.5)
    assert result.worst_at is None


def test_a_phased_requirement_counts_only_its_phase():
    a = (
        _swung()
        .assert_no_interference(
            "post", "swing.arm", during=JointWindow("swing", 0, 30)
        )
        .with_motion(_swing(90))
    )
    result = _only(a)
    assert result.passed
    assert result.poses.in_phase == 4  # as built, 0, 15, 30
    assert result.poses.evaluated == 8
    assert result.skipped is None


def test_a_requirement_never_in_phase_is_skipped_and_warned():
    a = (
        _swung()
        .assert_no_interference(
            "post", "swing.arm", name="raised", during=JointWindow("swing", 100, 120)
        )
        .with_motion(_swing(90))
    )
    held = hold(a)
    (result,) = held.assertions
    assert result.passed is None
    assert result.skipped == "out_of_phase"
    assert result.poses.in_phase == 0
    assert {"kind": "never_in_phase", "assertion": "raised"} in held.warnings


def test_a_permission_forbids_the_contact_outside_its_window():
    a = (
        _swung()
        .assert_allowed_contact(
            "post", "swing.arm", max_overlap_mm3=2000,
            during=JointWindow("swing", 80, 100),
        )
        .with_motion(_swing(90))
    )
    result = _only(a)
    assert result.passed is False  # overlaps at 60 and 75deg, outside it
    assert result.poses.failed == 2
    assert result.poses.in_phase == 1


def test_a_window_on_a_joint_that_moves_neither_part_is_still_held():
    """The pair never moves, so its geometry is the same at every pose
    — but the permission is not, and reusing the as-built verdict
    would hold green through the phase that forbids the contact."""
    a = (
        _swung()
        .with_part("block", _cube(), location=Location((5, 20, 0)))
        .assert_allowed_contact(
            "post", "block", max_overlap_mm3=2000,
            during=JointWindow("swing", 0, 10),
        )
        .with_motion(_swing(90))
    )
    result = _only(a)
    assert result.passed is False
    assert result.poses.in_phase == 2


def test_layered_permissions_partition_the_motion():
    a = (
        _swung()
        .assert_allowed_contact(
            "post", "swing.arm", max_overlap_mm3=5,
            during=JointWindow("swing", 0, 50),
        )
        .assert_allowed_contact(
            "post", "swing.arm", max_overlap_mm3=2000,
            during=JointWindow("swing", 50, 100),
        )
        .with_motion(_swing(90))
    )
    assert [r.passed for r in hold(a).assertions] == [True, True]


def test_a_units_motion_is_held_at_the_root_that_composes_it():
    unit = (
        _swung()
        .assert_no_interference("post", "swing.arm")
        .with_motion(_swing(90))
    )
    held = hold(Assembly().with_subassembly("m05", unit))
    (result,) = held.assertions
    assert result.passed is False
    assert result.worst_at.motion == "m05.swing_in"
    assert result.worst_at.joints_deg == {"m05.swing": pytest.approx(60.0)}


def test_a_datum_plane_under_a_driven_joint_moves_with_it():
    """The tip clears its unit's own datum plane at every pose, because
    the plane rides the joint with it; held against the as-built plane
    the tip would swing through it at 15deg."""
    arm = (
        Assembly()
        .with_part("tip", _cube(2), location=Location((40, 0, 0)))
        .assert_distance(
            "tip", Plane(origin=(0, 10, 0), z_dir=(0, 1, 0)), min_mm=5.0
        )
    )
    a = (
        Assembly()
        .with_subassembly("swing", arm, joint=RevoluteJoint(axis=Axis.Z))
        .with_motion(_swing(90))
    )
    result = _only(a)
    assert result.passed
    assert result.value == pytest.approx(9.0)


def test_a_directed_distance_under_a_driven_joint_turns_with_it():
    """The tip stays 14 mm out from the arm along the unit's own X at
    every pose; measured along the as-built X the gap closes as the
    unit swings."""
    arm = (
        Assembly()
        .with_part("arm", _cube(), location=Location((20, 0, 0)))
        .with_part("tip", _cube(2), location=Location((40, 0, 0)))
        .assert_distance("arm", "tip", along="X", min_mm=14.0, max_mm=14.0)
    )
    a = (
        Assembly()
        .with_subassembly("swing", arm, joint=RevoluteJoint(axis=Axis.Z))
        .with_motion(_swing(90))
    )
    result = _only(a)
    assert result.passed
    assert result.value == pytest.approx(14.0)


def test_a_direction_turns_even_when_no_part_moves():
    """Two coaxial joints turning against each other leave every part
    where it was, but the outer unit's X has turned — and the claim is
    about that X. At 90deg it reads across the pair, where they overlap."""
    pair = (
        Assembly()
        .with_part("arm", _cube(), location=Location((20, 0, 0)))
        .with_part("tip", _cube(2), location=Location((40, 0, 0)))
    )
    outer = (
        Assembly()
        .with_subassembly("inner", pair, joint=RevoluteJoint(axis=Axis.Z))
        .assert_distance("inner.arm", "inner.tip", along="X", min_mm=14.0)
    )
    a = (
        Assembly()
        .with_subassembly("outer", outer, joint=RevoluteJoint(axis=Axis.Z))
        .with_motion(
            Motion(
                "counter",
                lambda t: {"outer": 90 * t, "outer.inner": -90 * t},
                (0.0, 0.5, 1.0),
            )
        )
    )
    result = _only(a)
    assert result.passed is False
    assert result.poses.failed == 2
    assert result.value == pytest.approx(-6.0)


def test_motion_summary_says_how_much_was_looked_at():
    (summary,) = hold(_swung().with_motion(_swing(50, step=20.0))).motions
    assert summary.name == "swing_in"
    assert summary.samples == 4
    (joint_range,) = summary.joints_deg.values()
    assert list(summary.joints_deg) == ["swing"]
    assert joint_range == JointRange(
        min=0.0, max=pytest.approx(50.0), max_step=pytest.approx(50 / 3)
    )


def test_a_joint_no_motion_drives_is_warned():
    assert {"kind": "joint_never_driven", "joint": "swing"} in hold(
        _swung()
    ).warnings
    assert not any(
        w["kind"] == "joint_never_driven"
        for w in hold(_swung().with_motion(_swing(90))).warnings
    )


def test_rest_pose_only_interferences_are_marked_once_a_motion_is_declared():
    marker = {"kind": "interferences_rest_pose_only"}
    assert marker not in hold(_swung()).warnings
    assert marker in hold(_swung().with_motion(_swing(90))).warnings


def test_absence_is_not_a_pose_count():
    a = (
        _swung()
        .assert_no_interference("post", "swing.bolt")
        .with_motion(_swing(90))
    )
    result = _only(a)
    assert result.skipped == "absent_part"
    assert result.poses == PoseCounts(evaluated=0, distinct=0, in_phase=0, failed=0)


def test_scalar_claims_ride_along_unchanged():
    a = _swung().assert_scalar("budget", 3.0, le=5.0).with_motion(_swing(90))
    result = _only(a)
    assert result.passed and result.value == 3.0
    assert result.poses.distinct == 1


def test_a_solid_count_is_the_same_at_every_pose():
    """Connectivity does not depend on where a part is — a moving part's
    count is looked at once, however long the motion."""
    a = _swung().assert_solid_count("swing.arm", eq=1).with_motion(_swing(90))
    result = _only(a)
    assert result.passed
    assert result.poses == PoseCounts(evaluated=8, distinct=1, in_phase=8, failed=0)


# --- a motion that tests nothing (V1-V6) ---

VACUOUS = "motion_moved_nothing"


def _motion_named(assembly: Assembly, name: str):
    (summary,) = [m for m in hold(assembly).motions if m.name == name]
    return summary


def test_a_motion_that_moves_a_claim_counts_it():
    a = (
        _swung()
        .assert_no_interference("post", "swing.arm")
        .with_motion(_swing(90))
    )
    summary = _motion_named(a, "swing_in")
    assert (summary.moved, summary.movable) == (1, 1)
    assert not [w for w in hold(a).warnings if w["kind"] == VACUOUS]


def test_a_motion_no_claim_rides_is_warned_with_both_counts():
    """The tower case: a declared motion whose joint moves nothing any
    claim references. Every number is right and the run reads green."""
    a = (
        _swung()
        .assert_no_interference("post", "base")
        .with_motion(_swing(90))
    )
    summary = _motion_named(a, "swing_in")
    assert (summary.moved, summary.movable) == (0, 1)
    assert {
        "kind": VACUOUS,
        "motion": "swing_in",
        "moved": 0,
        "movable": 1,
    } in hold(a).warnings


def test_pose_invariant_kinds_are_not_movable():
    """`assert_scalar` / `assert_solid_count` key to () and can never
    move, so counting them would make the warning born noisy.
    `movable: 0` is the distinct diagnosis: nothing here could move."""
    a = (
        _swung()
        .assert_scalar("budget", 3.0, le=5.0)
        .assert_solid_count("swing.arm", eq=1)
        .with_motion(_swing(90))
    )
    summary = _motion_named(a, "swing_in")
    assert (summary.moved, summary.movable) == (0, 0)
    assert {
        "kind": VACUOUS,
        "motion": "swing_in",
        "moved": 0,
        "movable": 0,
    } in hold(a).warnings


def test_movable_counts_only_the_pose_variant_claims():
    a = (
        _swung()
        .assert_solid_count("swing.arm", eq=1)
        .assert_no_interference("post", "swing.arm")
        .with_motion(_swing(90))
    )
    summary = _motion_named(a, "swing_in")
    assert (summary.moved, summary.movable) == (1, 1)


def test_an_absent_claim_is_not_movable():
    """It was never held, so it is not a claim this run could move."""
    a = (
        _swung()
        .assert_no_interference("post", "swing.bolt")
        .with_motion(_swing(90))
    )
    summary = _motion_named(a, "swing_in")
    assert (summary.moved, summary.movable) == (0, 0)


def test_a_motion_that_moves_some_claims_does_not_warn():
    """28 of 2095 tested something. No threshold between some and not
    enough -- that is what the count is for, not the warning."""
    a = (
        _swung()
        .assert_no_interference("post", "swing.arm")
        .assert_no_interference("post", "base")
        .with_motion(_swing(90))
    )
    summary = _motion_named(a, "swing_in")
    assert (summary.moved, summary.movable) == (1, 2)
    assert not [w for w in hold(a).warnings if w["kind"] == VACUOUS]


def test_each_motion_is_counted_on_its_own():
    """Per-motion attribution: one real motion does not excuse a
    vacuous sibling."""
    a = (
        _swung()
        .assert_no_interference("post", "swing.arm")
        .with_motion(_swing(90))
        .with_motion(Motion.over_joint("nudge", "swing", 0.0, 0.0, 15.0))
    )
    held = hold(a)
    by_name = {m.name: m for m in held.motions}
    assert (by_name["swing_in"].moved, by_name["swing_in"].movable) == (1, 1)
    assert (by_name["nudge"].moved, by_name["nudge"].movable) == (0, 1)
    assert [w["motion"] for w in held.warnings if w["kind"] == VACUOUS] == [
        "nudge"
    ]


def test_a_phase_change_counts_as_moved():
    """V3 -- moved reuses the shipped key, which carries phase state.
    Geometry constant, phase crossing: the motion exercised this claim
    hardest, and a geometry-only definition would have missed it."""
    a = (
        _swung()
        .assert_no_interference(
            "post", "base", during=JointWindow("swing", 0.0, 40.0)
        )
        .with_motion(_swing(90))
    )
    summary = _motion_named(a, "swing_in")
    assert (summary.moved, summary.movable) == (1, 1)
