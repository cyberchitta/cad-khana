from build123d import Box, BuildPart, Location

from cad_khana.core.assembly import Assembly


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
