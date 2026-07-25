import pytest
from build123d import Axis, Box, BuildPart, Color, Location, Pos, ShapeList

from cad_khana.mechanism.assembly import (
    Assembly,
    DetailOverride,
    RevoluteJoint,
)


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def test_with_part_rejects_shapelist_naming_the_part():
    pieces = ShapeList([_cube(5), Pos(20, 0, 0) * _cube(5)])
    with pytest.raises(TypeError, match=r"with_part\('bad'\).*ShapeList.*fuse"):
        Assembly().with_part("bad", pieces)


def test_with_part_rejects_non_shape():
    with pytest.raises(TypeError, match=r"with_part\('bad'\).*int"):
        Assembly().with_part("bad", 42)


def test_empty_assembly_has_no_parts():
    assert Assembly().parts == ()


def test_with_part_returns_new_assembly():
    original = Assembly()
    extended = original.with_part("cube", _cube())
    assert original.parts == ()
    assert len(extended.parts) == 1
    assert extended.parts[0].name == "cube"


def test_chained_with_parts_preserve_order():
    assembly = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((0, 0, 20)))
    )
    assert [p.name for p in assembly.parts] == ["a", "b"]


def test_default_location_is_origin():
    assembly = Assembly().with_part("a", _cube())
    assert assembly.parts[0].location.position == Location().position


def test_compound_includes_all_placed_parts():
    assembly = (
        Assembly()
        .with_part("a", _cube(10))
        .with_part("b", _cube(4), location=Location((0, 0, 8)))
    )
    assert len(assembly.compound.children) == 2


def test_empty_assembly_has_no_assertions():
    assert Assembly().assertions == ()


def test_assert_no_interference_returns_new_assembly():
    original = Assembly()
    extended = original.assert_no_interference("a", "b")
    assert original.assertions == ()
    assert len(extended.assertions) == 1


def test_assert_clearance_returns_new_assembly():
    original = Assembly()
    extended = original.assert_clearance("a", "b", min_mm=0.2)
    assert original.assertions == ()
    assert len(extended.assertions) == 1


def test_assert_interference_returns_new_assembly():
    original = Assembly()
    extended = original.assert_interference("a", "b", reason="pending")
    assert original.assertions == ()
    assert len(extended.assertions) == 1


def test_chained_assertions_preserve_order():
    assembly = (
        Assembly()
        .assert_no_interference("a", "b", name="first")
        .assert_clearance("a", "b", min_mm=0.2, name="second")
    )
    assert [a.name for a in assembly.assertions] == ["first", "second"]


def test_assembly_has_no_min_wall_method():
    assert not hasattr(Assembly(), "assert_min_wall")


def test_default_color_is_none():
    assembly = Assembly().with_part("a", _cube())
    assert assembly.parts[0].color is None


def test_with_part_accepts_per_placement_color():
    bracket = _cube()
    assembly = (
        Assembly()
        .with_part("a", bracket, color=Color("red"))
        .with_part("b", bracket, location=Location((0, 0, 20)), color=Color("blue"))
    )
    assert assembly.parts[0].color is not None
    assert assembly.parts[1].color is not None
    assert assembly.parts[0].part is assembly.parts[1].part


def test_default_material_is_none():
    assembly = Assembly().with_part("a", _cube())
    assert assembly.parts[0].material is None


def test_with_part_accepts_material():
    assembly = Assembly().with_part("a", _cube(), material="aluminium_anodized")
    assert assembly.parts[0].material == "aluminium_anodized"


def test_with_materials_overrides_named_parts():
    assembly = (
        Assembly()
        .with_part("a", _cube(), material="plastic_matte")
        .with_part("b", _cube(), material="plastic_matte")
        .with_part("c", _cube())
    )
    overridden = assembly.with_materials({"a": "steel", "c": "aluminium_anodized"})
    assert overridden.parts[0].material == "steel"
    assert overridden.parts[1].material == "plastic_matte"
    assert overridden.parts[2].material == "aluminium_anodized"
    # original is unchanged
    assert assembly.parts[0].material == "plastic_matte"
    assert assembly.parts[2].material is None


def test_with_detailed_geometry_empty_mapping_is_noop():
    assembly = Assembly().with_part("a", _cube(), material="plastic_matte")
    result = assembly.with_detailed_geometry({})
    assert result.parts == assembly.parts


def test_with_detailed_geometry_swap_preserves_placement_and_material():
    loc = Location((1, 2, 3))
    assembly = Assembly().with_part(
        "a",
        _cube(10),
        location=loc,
        material="plastic_matte",
        color=Color("red"),
    )
    detailed = _cube(20)
    result = assembly.with_detailed_geometry({"a": detailed})
    assert result.parts[0].part is detailed
    assert result.parts[0].location.position == loc.position
    assert result.parts[0].material == "plastic_matte"
    assert result.parts[0].color is not None


def test_with_detailed_geometry_swap_accepts_detail_override():
    assembly = Assembly().with_part("a", _cube(10), material="plastic_matte")
    detailed = _cube(20)
    result = assembly.with_detailed_geometry(
        {"a": DetailOverride(part=detailed, material="steel")}
    )
    assert result.parts[0].part is detailed
    assert result.parts[0].material == "steel"


def test_with_detailed_geometry_addition_appends_placed_part():
    assembly = Assembly().with_part("rail", _cube(10))
    bolt = _cube(2)
    result = assembly.with_detailed_geometry(
        {
            "bolt": DetailOverride(
                part=bolt, location=Location((5, 0, 0)), material="steel"
            )
        }
    )
    assert [p.name for p in result.parts] == ["rail", "bolt"]
    assert result.parts[1].part is bolt
    assert result.parts[1].location.position == Location((5, 0, 0)).position
    assert result.parts[1].material == "steel"


def test_with_detailed_geometry_addition_without_location_raises():
    assembly = Assembly().with_part("rail", _cube(10))
    with pytest.raises(ValueError, match="requires an explicit location"):
        assembly.with_detailed_geometry({"bolt": _cube(2)})


def test_with_detailed_geometry_returns_new_assembly():
    original = Assembly().with_part("a", _cube())
    result = original.with_detailed_geometry({"a": _cube(20)})
    assert original.parts[0].part is not result.parts[0].part


# --- Sub-assemblies + joints ---------------------------------------------


def test_with_subassembly_appends_to_tree():
    leaf = Assembly().with_part("inner", _cube())
    parent = Assembly().with_subassembly("group", leaf)
    assert len(parent.subassemblies) == 1
    assert parent.subassemblies[0].name == "group"
    assert parent.subassemblies[0].assembly is leaf


def test_subassembly_default_location_is_identity():
    leaf = Assembly().with_part("inner", _cube())
    parent = Assembly().with_subassembly("group", leaf)
    assert parent.subassemblies[0].location.position == Location().position


def test_placed_parts_flattens_root_only_assembly():
    assembly = (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((20, 0, 0)))
    )
    placed = assembly.placed_parts
    assert [p.name for p in placed] == ["a", "b"]


def test_placed_parts_composes_subassembly_location():
    leaf = Assembly().with_part("inner", _cube(), location=Location((1, 0, 0)))
    parent = Assembly().with_subassembly(
        "group", leaf, location=Location((10, 0, 0))
    )
    placed = parent.placed_parts
    assert len(placed) == 1
    assert placed[0].name == "group.inner"
    assert placed[0].location.position.X == pytest.approx(11.0)


def test_revolute_joint_default_angle_is_zero():
    j = RevoluteJoint(axis=Axis.Z)
    assert j.angle_deg == 0.0


def test_revolute_joint_transform_at_zero_is_identity():
    j = RevoluteJoint(axis=Axis.Z, angle_deg=0.0)
    p = Pos(5, 0, 0) * _cube()
    moved = p.moved(j.transform)
    # zero-angle rotation should leave the part where it was
    bb_orig = p.bounding_box()
    bb_moved = moved.bounding_box()
    assert bb_moved.min.X == pytest.approx(bb_orig.min.X)
    assert bb_moved.min.Y == pytest.approx(bb_orig.min.Y)


def test_revolute_joint_transform_about_z_rotates_xy():
    j = RevoluteJoint(axis=Axis.Z, angle_deg=90.0)
    p = Pos(10, 0, 0) * _cube()
    bb = p.moved(j.transform).bounding_box()
    # 90° about world Z: point at (10, 0, 0) lands near (0, 10, 0)
    assert bb.center().X == pytest.approx(0.0, abs=1e-6)
    assert bb.center().Y == pytest.approx(10.0, abs=1e-6)


def test_revolute_joint_transform_about_offset_axis_is_pivot_conjugation():
    # Axis along +Z through (5, 0, 0). 180° should map a point at
    # (10, 0, 0) (5 mm past the pivot in +X) onto (0, 0, 0)
    # (5 mm before the pivot in -X), not onto (-10, 0, 0) which is
    # what a rotate-around-origin-then-translate Location would give.
    j = RevoluteJoint(axis=Axis((5, 0, 0), (0, 0, 1)), angle_deg=180.0)
    p = Pos(10, 0, 0) * _cube()
    bb = p.moved(j.transform).bounding_box()
    assert bb.center().X == pytest.approx(0.0, abs=1e-6)
    assert bb.center().Y == pytest.approx(0.0, abs=1e-6)
    assert bb.center().Z == pytest.approx(0.0, abs=1e-6)


def test_revolute_joint_transform_about_offset_x_axis_tilts_outer_edge_down():
    # m03-shape sanity: rotation about +X through (0, -65, -22.5) by
    # +30°. Point at (0, -185, 0) — the platform's far outer edge —
    # should tip in (Y less negative) and DOWN (Z negative); the
    # screw-form Location would put it nowhere near.
    j = RevoluteJoint(
        axis=Axis((0, -65, -22.5), (1, 0, 0)), angle_deg=30.0
    )
    p = Pos(0, -185, 0) * _cube()
    bb = p.moved(j.transform).bounding_box()
    # Expected from T·R·T⁻¹ closed-form:
    #   (p - pivot) = (0, -120, 22.5)
    #   R(+X, 30°)·(0, -120, 22.5) ≈ (0, -115.173, -40.514)
    #   + pivot                    ≈ (0, -180.173, -63.014)
    # (Tolerance is loose-ish because bb.center() of a rotated cube is
    # the AABB centroid, which is the rotated centroid only to within
    # the mesher's bounding-box precision.)
    assert bb.center().X == pytest.approx(0.0, abs=1e-3)
    assert bb.center().Y == pytest.approx(-180.173, abs=1e-2)
    assert bb.center().Z == pytest.approx(-63.014, abs=1e-2)


def test_with_joint_attaches_joint_to_named_subassembly():
    leaf = Assembly().with_part("inner", _cube())
    parent = (
        Assembly()
        .with_subassembly("group", leaf)
        .with_joint("group", RevoluteJoint(axis=Axis.Z, angle_deg=45.0))
    )
    assert parent.subassemblies[0].joint is not None
    assert parent.subassemblies[0].joint.angle_deg == 45.0


def test_with_joint_unknown_subassembly_raises():
    parent = Assembly().with_subassembly("group", Assembly())
    with pytest.raises(KeyError):
        parent.with_joint("other", RevoluteJoint(axis=Axis.Z))


def test_with_joint_angle_updates_existing_joint():
    parent = (
        Assembly()
        .with_subassembly(
            "group",
            Assembly().with_part("inner", _cube()),
            joint=RevoluteJoint(axis=Axis.Z, angle_deg=0.0),
        )
        .with_joint_angle("group", 30.0)
    )
    assert parent.subassemblies[0].joint.angle_deg == 30.0


def test_with_joint_angle_without_joint_raises():
    parent = Assembly().with_subassembly("group", Assembly())
    with pytest.raises(ValueError, match="no joint"):
        parent.with_joint_angle("group", 30.0)


def test_with_joint_angle_dotted_path_updates_nested_joint():
    grandchild = Assembly().with_part("leaf", _cube())
    child = Assembly().with_subassembly(
        "inner", grandchild, joint=RevoluteJoint(axis=Axis.Z, angle_deg=0.0)
    )
    parent = (
        Assembly()
        .with_subassembly("outer", child)
        .with_joint_angle("outer.inner", 45.0)
    )
    inner = parent.subassemblies[0].assembly.subassemblies[0]
    assert inner.joint.angle_deg == 45.0


def test_with_joint_dotted_path_attaches_nested_joint():
    grandchild = Assembly().with_part("leaf", _cube())
    child = Assembly().with_subassembly("inner", grandchild)
    parent = (
        Assembly()
        .with_subassembly("outer", child)
        .with_joint("outer.inner", RevoluteJoint(axis=Axis.Z, angle_deg=15.0))
    )
    inner = parent.subassemblies[0].assembly.subassemblies[0]
    assert inner.joint is not None
    assert inner.joint.angle_deg == 15.0


def test_with_joint_angle_dotted_path_missing_segment_raises():
    grandchild = Assembly().with_part("leaf", _cube())
    child = Assembly().with_subassembly(
        "inner", grandchild, joint=RevoluteJoint(axis=Axis.Z, angle_deg=0.0)
    )
    parent = Assembly().with_subassembly("outer", child)
    with pytest.raises(KeyError):
        parent.with_joint_angle("outer.missing", 10.0)


def test_joint_rotates_subassembly_parts_in_placed_parts():
    leaf = Assembly().with_part(
        "inner", _cube(), location=Location((10, 0, 0))
    )
    parent = Assembly().with_subassembly(
        "group", leaf, joint=RevoluteJoint(axis=Axis.Z, angle_deg=90.0)
    )
    placed = parent.placed_parts
    assert len(placed) == 1
    pos = placed[0].location.position
    assert pos.X == pytest.approx(0.0, abs=1e-6)
    assert pos.Y == pytest.approx(10.0, abs=1e-6)


def test_with_materials_recurses_into_subassemblies():
    leaf = Assembly().with_part("inner", _cube(), material="plastic_matte")
    parent = (
        Assembly()
        .with_part("outer", _cube(), material="plastic_matte")
        .with_subassembly("group", leaf)
    )
    overridden = parent.with_materials(
        {"group.inner": "steel", "outer": "aluminium"}
    )
    assert overridden.parts[0].material == "aluminium"
    assert overridden.subassemblies[0].assembly.parts[0].material == "steel"


# --- Group assertions -------------------------------------------------


def _three_part_assembly():
    return (
        Assembly()
        .with_part("a1", _cube())
        .with_part("a2", _cube(), location=Location((0, 0, 20)))
        .with_part("b1", _cube(), location=Location((0, 0, 40)))
    )


def test_between_is_diff_identical_to_hand_loop():
    base = _three_part_assembly()
    hand = base
    for a in ("a1", "a2"):
        for b in ("b1",):
            hand = hand.assert_no_interference(a, b)
    grouped = base.assert_no_interference_between(("a1", "a2"), ("b1",))
    assert grouped.assertions == hand.assertions


def test_within_is_diff_identical_to_hand_loop():
    base = _three_part_assembly()
    names = ("a1", "a2", "b1")
    hand = base
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            hand = hand.assert_no_interference(names[i], names[j])
    grouped = base.assert_no_interference_within(names)
    assert grouped.assertions == hand.assertions


def test_between_known_overlap_downgrades_order_independent():
    base = _three_part_assembly()
    grouped = base.assert_no_interference_between(
        ("a1",), ("b1",), known_overlaps=(("b1", "a1", "documented"),)
    )
    (assertion,) = grouped.assertions
    assert assertion.name == "interference:a1/b1"
    assert assertion.reason == "documented"


def test_between_suppressed_skips_order_independent():
    base = _three_part_assembly()
    grouped = base.assert_no_interference_between(
        ("a1", "a2"), ("b1",), suppressed=(("b1", "a1"),)
    )
    assert [a.name for a in grouped.assertions] == ["no_interference:a2/b1"]


def test_between_overlapping_groups_dedupes_and_skips_same_name():
    base = _three_part_assembly()
    grouped = base.assert_no_interference_between(
        ("a1", "a2"), ("a2", "a1", "b1")
    )
    assert [a.name for a in grouped.assertions] == [
        "no_interference:a1/a2",
        "no_interference:a1/b1",
        "no_interference:a2/b1",
    ]


def test_within_known_and_suppressed():
    base = _three_part_assembly()
    grouped = base.assert_no_interference_within(
        ("a1", "a2", "b1"),
        known_overlaps=(("a2", "a1", "why"),),
        suppressed=(("b1", "a2"),),
    )
    assert [a.name for a in grouped.assertions] == [
        "interference:a1/a2",
        "no_interference:a1/b1",
    ]


def test_group_path_selects_subtree_parts_sorted():
    sub = Assembly().with_part("z_part", _cube()).with_part("a_part", _cube())
    nested = Assembly().with_subassembly("inner", sub)
    top = (
        Assembly()
        .with_part("outside", _cube(), location=Location((0, 0, 40)))
        .with_subassembly("unit", nested)
    )
    grouped = top.assert_no_interference_between("unit.inner", ("outside",))
    assert [a.name for a in grouped.assertions] == [
        "no_interference:unit.inner.a_part/outside",
        "no_interference:unit.inner.z_part/outside",
    ]


def test_group_path_missing_raises_keyerror():
    top = Assembly().with_subassembly("unit", Assembly())
    with pytest.raises(KeyError):
        top.assert_no_interference_within("unit.nope")


# --- Local-frame joints -----------------------------------------------


def _placed_position(assembly, name):
    for p in assembly.placed_parts:
        if p.name == name:
            return p.location.position
    raise KeyError(name)


def test_local_joint_rotates_about_sub_local_axis():
    # Part at sub-local (10, 0, 0); sub placed at parent (100, 0, 0).
    # A local Z-axis joint at the sub origin swings the part around the
    # sub's own origin — 90° puts it at parent (100, 10, 0).
    sub = Assembly().with_part("tip", _cube(), location=Location((10, 0, 0)))
    top = Assembly().with_subassembly(
        "arm",
        sub,
        location=Location((100, 0, 0)),
        joint=RevoluteJoint(axis=Axis.Z, angle_deg=90.0, frame="local"),
    )
    pos = _placed_position(top, "arm.tip")
    assert abs(pos.X - 100) < 1e-9
    assert abs(pos.Y - 10) < 1e-9


def test_parent_joint_rotates_about_parent_axis():
    # Same geometry with a parent-frame Z joint at the parent origin:
    # the whole placed sub swings around the parent origin — 90° puts
    # the part at parent (0, 110, 0).
    sub = Assembly().with_part("tip", _cube(), location=Location((10, 0, 0)))
    top = Assembly().with_subassembly(
        "arm",
        sub,
        location=Location((100, 0, 0)),
        joint=RevoluteJoint(axis=Axis.Z, angle_deg=90.0, frame="parent"),
    )
    pos = _placed_position(top, "arm.tip")
    assert abs(pos.X - 0) < 1e-9
    assert abs(pos.Y - 110) < 1e-9


def test_local_axis_equals_parent_axis_through_location():
    # A local axis A is interchangeable with the parent-frame axis
    # location * A — here the sub is placed rotated 90° about Z, so its
    # local X axis is the parent's Y axis through the placement point.
    from build123d import Vector

    sub = Assembly().with_part("tip", _cube(), location=Location((0, 0, 30)))
    place = Location((50, 0, 0), (0, 0, 1), 90)
    local = Assembly().with_subassembly(
        "u", sub, location=place,
        joint=RevoluteJoint(axis=Axis.X, angle_deg=35.0, frame="local"),
    )
    parent_axis = Axis((50, 0, 0), (0, 1, 0))
    parent = Assembly().with_subassembly(
        "u", sub, location=place,
        joint=RevoluteJoint(axis=parent_axis, angle_deg=35.0, frame="parent"),
    )
    lp = _placed_position(local, "u.tip")
    pp = _placed_position(parent, "u.tip")
    assert (Vector(lp) - Vector(pp)).length < 1e-9


def test_joint_frame_validated():
    with pytest.raises(ValueError):
        RevoluteJoint(axis=Axis.Z, frame="world")


# --- Path identity ------------------------------------------------------


def test_placed_parts_qualifies_names_at_depth():
    leaf = Assembly().with_part("frame", _cube())
    mid = Assembly().with_subassembly("platform_image", leaf)
    top = (
        Assembly()
        .with_part("bench", _cube())
        .with_subassembly("rotor", mid)
    )
    assert [p.name for p in top.placed_parts] == [
        "bench",
        "rotor.platform_image.frame",
    ]


def test_same_leaf_name_in_two_subtrees_does_not_shadow():
    # Two instances of one builder, distinguished only by their subtree
    # path — the motivating case for path identity. Both must appear in
    # placed_parts under distinct names.
    def cartridge():
        return Assembly().with_part("frame", _cube())

    top = (
        Assembly()
        .with_subassembly("platform_image", cartridge())
        .with_subassembly(
            "platform_dump", cartridge(), location=Location((100, 0, 0))
        )
    )
    names = [p.name for p in top.placed_parts]
    assert names == ["platform_image.frame", "platform_dump.frame"]
    # And a group assertion across the two paths evaluates both parts.
    checked = top.assert_no_interference_between(
        "platform_image", "platform_dump"
    )
    from cad_khana.mechanism.assertions import evaluate

    results = evaluate(checked)
    assert len(results) == 1
    assert results[0].passed


def test_with_materials_keys_on_path_at_depth():
    leaf = Assembly().with_part("frame", _cube(), material="plastic_matte")
    top = Assembly().with_subassembly(
        "rotor", Assembly().with_subassembly("platform_image", leaf)
    )
    overridden = top.with_materials(
        {"rotor.platform_image.frame": "steel"}
    )
    placed = overridden.placed_parts
    assert placed[0].material == "steel"
    # A bare leaf name no longer matches a nested part.
    unmatched = top.with_materials({"frame": "steel"})
    assert unmatched.placed_parts[0].material == "plastic_matte"


def test_with_detailed_geometry_swaps_by_path():
    leaf = Assembly().with_part("rail", _cube(10), material="plastic_matte")
    top = Assembly().with_subassembly("unit", leaf)
    detailed = _cube(20)
    result = top.with_detailed_geometry({"unit.rail": detailed})
    assert result.subassemblies[0].assembly.parts[0].part is detailed
    # No addition happened — the path matched.
    assert result.parts == ()


def test_with_detailed_geometry_bare_name_of_nested_part_is_addition():
    leaf = Assembly().with_part("rail", _cube(10))
    top = Assembly().with_subassembly("unit", leaf)
    with pytest.raises(ValueError, match="requires an explicit location"):
        top.with_detailed_geometry({"rail": _cube(20)})


def test_duplicate_sibling_part_name_raises():
    a = Assembly().with_part("frame", _cube())
    with pytest.raises(ValueError, match="duplicate sibling name"):
        a.with_part("frame", _cube())


def test_duplicate_part_and_subassembly_name_raises():
    a = Assembly().with_part("frame", _cube())
    with pytest.raises(ValueError, match="duplicate sibling name"):
        a.with_subassembly("frame", Assembly())


def test_same_name_at_different_levels_is_fine():
    inner = Assembly().with_part("frame", _cube())
    top = (
        Assembly()
        .with_part("frame", _cube(), location=Location((50, 0, 0)))
        .with_subassembly("unit", inner)
    )
    assert [p.name for p in top.placed_parts] == ["frame", "unit.frame"]


def test_subassembly_name_with_dot_raises():
    with pytest.raises(ValueError, match="tree-path separator"):
        Assembly().with_subassembly("a.b", Assembly())


# --- Anchors ----------------------------------------------------------


def test_with_anchor_and_root_resolution():
    a = Assembly().with_anchor("deck_top", Location((0, 0, 890)))
    assert a.anchor("deck_top").position == Location((0, 0, 890)).position


def test_anchor_resolves_through_subassembly_placement():
    unit = Assembly().with_anchor("datum", Location((10, 0, 0)))
    top = Assembly().with_subassembly(
        "m05", unit, location=Location((100, 0, 5))
    )
    pos = top.anchor("m05.datum").position
    assert abs(pos.X - 110) < 1e-9
    assert abs(pos.Z - 5) < 1e-9


def test_anchor_composes_joint_transform():
    # Anchor at sub-local (10, 0, 0) under a 90° local Z joint at the
    # sub origin: swings to sub-frame (0, 10, 0), then places at
    # parent (100, 10, 0) — same composition as placed parts.
    unit = Assembly().with_anchor("tip", Location((10, 0, 0)))
    top = Assembly().with_subassembly(
        "arm",
        unit,
        location=Location((100, 0, 0)),
        joint=RevoluteJoint(axis=Axis.Z, angle_deg=90.0, frame="local"),
    )
    pos = top.anchor("arm.tip").position
    assert abs(pos.X - 100) < 1e-9
    assert abs(pos.Y - 10) < 1e-9


def test_anchor_missing_name_raises_keyerror():
    a = Assembly().with_anchor("datum", Location())
    with pytest.raises(KeyError):
        a.anchor("nope")


def test_anchor_missing_subassembly_segment_raises_keyerror():
    a = Assembly().with_anchor("datum", Location())
    with pytest.raises(KeyError):
        a.anchor("ghost.datum")


def test_duplicate_anchor_name_raises():
    a = Assembly().with_anchor("datum", Location())
    with pytest.raises(ValueError):
        a.with_anchor("datum", Location((1, 0, 0)))


def test_anchor_name_with_dot_raises():
    with pytest.raises(ValueError):
        Assembly().with_anchor("a.b", Location())


def test_anchor_name_does_not_collide_with_part_name():
    a = (
        Assembly()
        .with_part("datum", _cube())
        .with_anchor("datum", Location((0, 0, 42)))
    )
    assert a.anchor("datum").position.Z == 42


def test_assert_anchors_coincident_fails_fast_on_missing_path():
    a = Assembly().with_anchor("datum", Location())
    with pytest.raises(KeyError):
        a.assert_anchors_coincident("datum", "ghost.datum")


def test_joint_angles_maps_dotted_paths_to_degrees():
    inner = Assembly().with_subassembly(
        "tilt", Assembly(), joint=RevoluteJoint(axis=Axis.Y, angle_deg=12.5)
    )
    a = Assembly().with_subassembly(
        "rotor", inner, joint=RevoluteJoint(axis=Axis.Z, angle_deg=90)
    )
    assert a.joint_angles == {"rotor": 90.0, "rotor.tilt": 12.5}


def test_joint_angles_walks_through_unjointed_levels():
    inner = Assembly().with_subassembly(
        "tilt", Assembly(), joint=RevoluteJoint(axis=Axis.Y, angle_deg=5)
    )
    a = Assembly().with_subassembly("frame", inner)
    assert a.joint_angles == {"frame.tilt": 5.0}


def test_joint_angles_is_empty_without_joints():
    assert Assembly().with_subassembly("frame", Assembly()).joint_angles == {}


def test_joint_angles_tracks_with_joint_angle():
    a = Assembly().with_subassembly(
        "rotor", Assembly(), joint=RevoluteJoint(axis=Axis.Z)
    )
    assert a.with_joint_angle("rotor", 45).joint_angles == {"rotor": 45.0}
