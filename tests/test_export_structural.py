"""Unit tests for the structural-emission groups in
``cad_khana.export._structural_groups``. The function feeds
``export_animated_glb``'s per-joint animation-channel emission, so
correctness here is load-bearing for animated GLB output.
"""

from build123d import Axis, Box, BuildPart, Pos

from cad_khana.export import _structural_groups
from cad_khana.mechanism.assembly import Assembly, RevoluteJoint


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def test_structural_groups_empty_for_flat_assembly():
    a = Assembly().with_part("only", _cube())
    assert _structural_groups(a) == []


def test_structural_groups_one_group_per_top_level_joint():
    rotor = Assembly().with_part("hub", _cube()).with_part("spider", _cube())
    a = Assembly().with_subassembly(
        "rotor", rotor, joint=RevoluteJoint(axis=Axis.Z, angle_deg=0.0)
    )
    groups = _structural_groups(a)
    assert len(groups) == 1
    assert set(groups[0]) == {"hub", "spider"}


def test_structural_groups_nested_joints_produce_non_overlapping_groups():
    # rotor → platform_dump (nested joint). Each part must appear in
    # exactly one group — the innermost jointed ancestor's group.
    platform = (
        Assembly()
        .with_part("acrylic", _cube())
        .with_part("frame", _cube())
    )
    rotor = (
        Assembly()
        .with_part("hub", _cube())
        .with_part("spider", _cube())
        .with_subassembly(
            "platform_dump",
            platform,
            location=Pos(0, -100, 0),
            joint=RevoluteJoint(axis=Axis.X, angle_deg=0.0),
        )
    )
    a = Assembly().with_subassembly(
        "rotor", rotor, joint=RevoluteJoint(axis=Axis.Z, angle_deg=0.0)
    )
    groups = _structural_groups(a)
    assert len(groups) == 2
    rotor_grp = next(g for g in groups if "hub" in g)
    platform_grp = next(g for g in groups if "acrylic" in g)
    assert set(rotor_grp) == {"hub", "spider"}
    assert set(platform_grp) == {"acrylic", "frame"}
    flat = [n for g in groups for n in g]
    assert len(flat) == len(set(flat)), "groups must be non-overlapping"


def test_structural_groups_non_jointed_subassembly_is_absorbed():
    # A non-jointed sub-assembly's parts belong to the nearest jointed
    # ancestor; they are NOT a separate group.
    static_wrapper = Assembly().with_part("inner_a", _cube()).with_part(
        "inner_b", _cube()
    )
    rotor = (
        Assembly()
        .with_part("hub", _cube())
        .with_subassembly("static_wrapper", static_wrapper)
    )
    a = Assembly().with_subassembly(
        "rotor", rotor, joint=RevoluteJoint(axis=Axis.Z, angle_deg=0.0)
    )
    groups = _structural_groups(a)
    assert len(groups) == 1
    assert set(groups[0]) == {"hub", "inner_a", "inner_b"}
