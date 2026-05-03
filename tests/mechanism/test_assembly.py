from build123d import Box, BuildPart, Color, Location

from cad_khana.mechanism.assembly import Assembly


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def test_empty_assembly_has_no_parts():
    assert Assembly().parts == ()


def test_add_returns_new_assembly():
    original = Assembly()
    extended = original.add("cube", _cube())
    assert original.parts == ()
    assert len(extended.parts) == 1
    assert extended.parts[0].name == "cube"


def test_chained_adds_preserve_order():
    assembly = (
        Assembly()
        .add("a", _cube())
        .add("b", _cube(), location=Location((0, 0, 20)))
    )
    assert [p.name for p in assembly.parts] == ["a", "b"]


def test_default_location_is_origin():
    assembly = Assembly().add("a", _cube())
    assert assembly.parts[0].location.position == Location().position


def test_compound_includes_all_placed_parts():
    assembly = (
        Assembly()
        .add("a", _cube(10))
        .add("b", _cube(4), location=Location((0, 0, 8)))
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
    assembly = Assembly().add("a", _cube())
    assert assembly.parts[0].color is None


def test_add_accepts_per_placement_color():
    bracket = _cube()
    assembly = (
        Assembly()
        .add("a", bracket, color=Color("red"))
        .add("b", bracket, location=Location((0, 0, 20)), color=Color("blue"))
    )
    assert assembly.parts[0].color is not None
    assert assembly.parts[1].color is not None
    assert assembly.parts[0].part is assembly.parts[1].part


def test_default_material_is_none():
    assembly = Assembly().add("a", _cube())
    assert assembly.parts[0].material is None


def test_add_accepts_material():
    assembly = Assembly().add("a", _cube(), material="aluminium_anodized")
    assert assembly.parts[0].material == "aluminium_anodized"


def test_with_materials_overrides_named_parts():
    assembly = (
        Assembly()
        .add("a", _cube(), material="plastic_matte")
        .add("b", _cube(), material="plastic_matte")
        .add("c", _cube())
    )
    overridden = assembly.with_materials({"a": "steel", "c": "aluminium_anodized"})
    assert overridden.parts[0].material == "steel"
    assert overridden.parts[1].material == "plastic_matte"
    assert overridden.parts[2].material == "aluminium_anodized"
    # original is unchanged
    assert assembly.parts[0].material == "plastic_matte"
    assert assembly.parts[2].material is None
