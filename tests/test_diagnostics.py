from build123d import Box, BuildPart, Location
from pytest import approx

from cad_khana.core.assembly import Assembly
from cad_khana.core.diagnostics import SCHEMA_VERSION, compute


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


def test_overhangs_and_assertions_are_empty_placeholders():
    d = compute(Assembly().add("cube", _cube()))
    assert d.overhangs == ()
    assert d.assertions == ()


def test_min_wall_mm_is_not_yet_computed():
    d = compute(Assembly().add("cube", _cube()))
    assert d.parts["cube"].min_wall_mm is None
