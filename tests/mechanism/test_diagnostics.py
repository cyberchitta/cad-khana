from build123d import Box, BuildPart, Location
from pytest import approx

from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.diagnostics import SCHEMA_VERSION, compute


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def test_empty_assembly_has_no_parts_or_interferences():
    d = compute(Assembly())
    assert d.parts == {}
    assert d.interferences == ()


def test_schema_version_is_set():
    assert compute(Assembly()).schema_version == SCHEMA_VERSION


def test_default_status_is_ok():
    assert compute(Assembly()).status == "ok"


def test_part_bbox_reflects_placement():
    a = Assembly().add("cube", _cube(10), location=Location((100, 0, 0)))
    bbox = compute(a).parts["cube"].bbox
    assert bbox.min == approx((95.0, -5.0, -5.0))
    assert bbox.max == approx((105.0, 5.0, 5.0))


def test_part_volume_is_reported_in_mm3():
    d = compute(Assembly().add("cube", _cube(10)))
    assert d.parts["cube"].volume_mm3 == approx(1000.0)


def test_part_diagnostics_has_no_min_wall_field():
    d = compute(Assembly().add("cube", _cube(10)))
    assert not hasattr(d.parts["cube"], "min_wall_mm")


def test_diagnostics_has_no_overhangs_field():
    assert not hasattr(compute(Assembly()), "overhangs")


def test_non_overlapping_parts_have_no_interference():
    a = (
        Assembly()
        .add("a", _cube(10))
        .add("b", _cube(10), location=Location((20, 0, 0)))
    )
    assert compute(a).interferences == ()


def test_face_touching_parts_are_not_interfering():
    a = (
        Assembly()
        .add("a", _cube(10))
        .add("b", _cube(10), location=Location((10, 0, 0)))
    )
    assert compute(a).interferences == ()


def test_overlapping_parts_produce_interference():
    a = (
        Assembly()
        .add("a", _cube(10))
        .add("b", _cube(10), location=Location((5, 0, 0)))
    )
    interferences = compute(a).interferences
    assert len(interferences) == 1
    hit = interferences[0]
    assert (hit.a, hit.b) == ("a", "b")
    assert hit.volume_mm3 == approx(500.0)
    assert hit.centroid[0] == approx(2.5)
    assert hit.centroid[1] == approx(0.0, abs=1e-9)


def test_interference_pairs_are_unordered_combinations():
    a = (
        Assembly()
        .add("a", _cube(10))
        .add("b", _cube(10), location=Location((5, 0, 0)))
        .add("c", _cube(10), location=Location((5, 5, 0)))
    )
    pairs = {(i.a, i.b) for i in compute(a).interferences}
    assert pairs == {("a", "b"), ("a", "c"), ("b", "c")}


def test_assertions_default_empty():
    assert compute(Assembly().add("cube", _cube())).assertions == ()


def test_box_topology_counts():
    d = compute(Assembly().add("cube", _cube(10)))
    p = d.parts["cube"]
    assert p.face_count == 6
    assert p.edge_count == 12
    assert p.vertex_count == 8


def test_fused_box_topology_differs_from_single_box():
    from build123d import Box, BuildPart, Locations

    # L-shape: two overlapping boxes at offset positions
    with BuildPart() as p:
        Box(20, 10, 10)
        with Locations((5, 8, 0)):
            Box(10, 6, 10)
    fused = p.part

    single = _cube(10)
    d_fused = compute(Assembly().add("fused", fused))
    d_single = compute(Assembly().add("single", single))
    assert (
        d_fused.parts["fused"].face_count,
        d_fused.parts["fused"].edge_count,
        d_fused.parts["fused"].vertex_count,
    ) != (
        d_single.parts["single"].face_count,
        d_single.parts["single"].edge_count,
        d_single.parts["single"].vertex_count,
    )
