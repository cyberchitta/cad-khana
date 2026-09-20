import pytest
from build123d import Axis, Box, BuildPart, Location

from cad_khana.mechanism.assembly import Assembly, RevoluteJoint
from cad_khana.mechanism.motion import Motion
from cad_khana.mechanism.sweep import TRANSIENT, classify, over_motion, sweep


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def _hinged() -> Assembly:
    """A cube on a revolute joint about Z, clear of a fixed post at 0°
    and swung into it at 90°."""
    arm = Assembly().with_part("arm", _cube(), location=Location((20, 0, 0)))
    return (
        Assembly()
        .with_part("post", _cube(), location=Location((0, 20, 0)))
        .with_subassembly("swing", arm, joint=RevoluteJoint(axis=Axis.Z))
    )


def _nested() -> Assembly:
    """Two joints, one under the other: ``turret`` and ``turret.swing``."""
    return Assembly().with_subassembly(
        "turret", _hinged(), joint=RevoluteJoint(axis=Axis.Z)
    )


def test_posed_sets_every_named_joint():
    posed = _nested().posed({"turret": 30.0, "turret.swing": 45.0})
    assert posed.joint_angles == {"turret": 30.0, "turret.swing": 45.0}


def test_posed_leaves_unnamed_joints_as_built():
    built = _nested().with_joint_angle("turret", 10.0)
    assert built.posed({"turret.swing": 45.0}).joint_angles == {
        "turret": 10.0,
        "turret.swing": 45.0,
    }


def test_posed_returns_new_assembly():
    built = _hinged()
    built.posed({"swing": 45.0})
    assert built.joint_angles == {"swing": 0.0}


def test_posed_empty_pose_is_the_assembly_as_built():
    built = _hinged()
    assert built.posed({}) == built


def test_posed_unknown_joint_raises():
    with pytest.raises(KeyError):
        _hinged().posed({"nope": 1.0})


def test_motion_poses_follow_the_schedule():
    motion = Motion(
        "cycle",
        lambda t: {"turret": 90 * t, "turret.swing": 10 * t * t},
        (0.0, 0.5, 1.0),
    )
    assert motion.poses == (
        {"turret": 0.0, "turret.swing": 0.0},
        {"turret": 45.0, "turret.swing": 2.5},
        {"turret": 90.0, "turret.swing": 10.0},
    )


def test_over_joint_includes_both_ends():
    motion = Motion.over_joint("swing_in", "swing", 90.0, 30.0, step=20.0)
    assert [p["swing"] for p in motion.poses] == pytest.approx(
        [90.0, 70.0, 50.0, 30.0]
    )


def test_over_joint_never_steps_wider_than_asked():
    """A range the step doesn't divide gets more samples, not a wider
    step — the declared step is the resolution the claim is held at."""
    motion = Motion.over_joint("swing_in", "swing", 0.0, 50.0, step=20.0)
    angles = [p["swing"] for p in motion.poses]
    assert angles[0] == 0.0 and angles[-1] == pytest.approx(50.0)
    assert max(b - a for a, b in zip(angles, angles[1:])) <= 20.0


def test_over_joint_zero_range_is_one_pose():
    assert Motion.over_joint("hold", "swing", 5.0, 5.0, step=2.0).poses == (
        {"swing": 5.0},
    )


def test_over_joint_rejects_nonpositive_step():
    with pytest.raises(ValueError):
        Motion.over_joint("swing_in", "swing", 0.0, 90.0, step=0.0)


def test_sweep_runs_over_a_declared_motion():
    """Derive and hold share one declaration: the motion a claim will
    be held over is the one its window is derived from."""
    assembly = _hinged()
    motion = Motion.over_joint("swing_in", "swing", 0.0, 90.0, step=15.0)
    result = sweep(
        over_motion(assembly, motion), motion.ts, pairs=(("post", "swing.arm"),)
    )
    assert [a["swing"] for a in result.angles] == pytest.approx(
        [0.0, 15.0, 30.0, 45.0, 60.0, 75.0, 90.0]
    )
    (phase,) = classify(result)
    assert phase.kind == TRANSIENT
