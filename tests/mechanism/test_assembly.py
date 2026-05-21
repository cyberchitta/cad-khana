import pytest
from build123d import Axis, Box, BuildPart, Color, Location, Pos

from cad_khana.mechanism.assembly import (
    Assembly,
    DetailOverride,
    RevoluteJoint,
)


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


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
    assert placed[0].name == "inner"
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
    overridden = parent.with_materials({"inner": "steel", "outer": "aluminium"})
    assert overridden.parts[0].material == "aluminium"
    assert overridden.subassemblies[0].assembly.parts[0].material == "steel"
