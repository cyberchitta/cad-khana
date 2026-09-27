from math import atan, cos, degrees, radians, sin, sqrt

from build123d import (
    Box,
    BuildPart,
    BuildSketch,
    Cylinder,
    Location,
    Locations,
    Mode,
    Plane,
    Polygon,
    Pos,
    Rot,
    Sphere,
    extrude,
)
from pytest import approx

from cad_khana.core.tessellation import _tessellate, _tessellate_faces
from cad_khana.printability.overhangs import detect_overhang


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def _box(x: float, y: float, z: float):
    with BuildPart() as p:
        Box(x, y, z)
    return p.part


def test_cube_bottom_face_is_not_flagged_as_overhang():
    # The bottom face rests on the build plate, so it must not be
    # reported as an overhang.
    assert detect_overhang(_cube(10)) is None


def test_down_facing_ledge_is_flagged():
    # An L-shape: a big cube with a smaller cube protruding off the +X
    # face at mid-height. The underside of the protrusion faces down and
    # is NOT at the build-plate level → should be flagged.
    part = _box(20, 20, 20) + Pos(15, 0, 5) * Box(10, 20, 4)
    overhang = detect_overhang(part)
    assert overhang is not None
    assert overhang.max_angle_deg == approx(90.0, abs=0.01)



def test_vertical_walls_are_not_an_overhang():
    # Tessellated cylinder walls carry ~1e-16° of solver noise.
    with BuildPart() as p:
        Cylinder(10, 30)
    assert detect_overhang(p.part) is None

def test_up_axis_rotates_what_counts_as_down():
    # With up_axis along +X, the cube's -X face becomes the build-plate
    # face and should not be flagged.
    assert detect_overhang(_cube(10), up_axis=(1, 0, 0)) is None


def test_an_oblique_up_axis_still_excludes_the_face_on_the_plate():
    # Tilted 30° about Y, up = the box's top-face normal: the 40 x 20
    # bottom face rests on the plate. The axis-aligned bbox's lowest
    # corner sits below every point of the part along this up, so the
    # plate face used to read as an 800 mm² ceiling at 90°.
    tilt = radians(30)
    up = (sin(tilt), 0, cos(tilt))
    assert detect_overhang(Rot(0, 30, 0) * Box(40, 20, 10), up_axis=up) is None
    # sorted-studs: a 20 x 10 face down under an up in the XY plane.
    up = (-0.5, sqrt(3) / 2, 0)
    assert detect_overhang(Rot(0, 0, 30) * Box(20, 6, 10), up_axis=up) is None


def test_an_oblique_up_axis_reads_only_the_genuine_overhang():
    # The 10 x 20 ledge underside is the only overhang, whatever the
    # rotation — the 20 x 20 bed face must not add to it.
    turn = Rot(20, 30, 40)
    up = tuple(Plane(turn).z_dir)
    part = turn * (_box(20, 20, 20) + Pos(15, 0, 5) * Box(10, 20, 4))
    overhang = detect_overhang(part, up_axis=up)
    assert overhang.area_mm2 == approx(200.0, rel=1e-6)
    assert overhang.max_angle_deg == approx(90.0, abs=0.01)
    assert len(overhang.regions) == 1


def test_threshold_does_not_erase_the_measurement():
    # Raising the threshold past every facet stops counting area, but the
    # steepest angle is still what the part has — a 90° setting used to
    # "keep the check informational" nulled the whole block instead.
    part = _box(20, 20, 20) + Pos(15, 0, 5) * Box(10, 20, 4)
    overhang = detect_overhang(part, angle_threshold_deg=95.0)
    assert overhang is not None
    assert overhang.area_mm2 == 0.0
    assert isinstance(overhang.area_mm2, float)  # the JSON reads 0.0, not 0
    assert overhang.max_angle_deg == approx(90.0, abs=0.01)


def test_area_counts_only_facets_past_the_threshold():
    # The ledge underside is 10 x 20 = 200 mm² at 90°.
    part = _box(20, 20, 20) + Pos(15, 0, 5) * Box(10, 20, 4)
    assert detect_overhang(part).area_mm2 == approx(200.0, rel=1e-6)
    assert detect_overhang(part, angle_threshold_deg=90.0).area_mm2 == 0.0


# --- regions: where the area sits ----------------------------------------


def _two_ledges():
    # The +X ledge underside is 10 x 20 = 200 mm² at z=3, centred on
    # (15, 0); the -X ledge underside is 6 x 10 = 60 mm² at z=-1,
    # centred on (-13, 0).
    return (
        _box(20, 20, 20)
        + Pos(15, 0, 5) * Box(10, 20, 4)
        + Pos(-13, 0, 0) * Box(6, 10, 2)
    )


def _sloped_ledge():
    # A prism off the +X face whose underside runs from (10, z=-2) to
    # (20, z=2) across y in [-10, 10]: overhang angle atan(10/4), area
    # 20 * sqrt(116), centroid (15, 0, 0).
    with BuildPart() as p:
        Box(20, 20, 20)
        with BuildSketch(Plane.XZ):
            Polygon((10, -2), (20, 2), (10, 2), align=None)
        extrude(amount=10, both=True)
    return p.part


def test_a_ledge_is_one_region_with_its_area_angle_centroid_and_bbox():
    part = _box(20, 20, 20) + Pos(15, 0, 5) * Box(10, 20, 4)
    (region,) = detect_overhang(part).regions
    assert region.area_mm2 == approx(200.0, rel=1e-6)
    assert region.max_angle_deg == approx(90.0, abs=1e-6)
    assert region.centroid_mm == approx((15.0, 0.0, 3.0), abs=1e-6)
    assert region.bbox.min == approx((10.0, -10.0, 3.0), abs=1e-6)
    assert region.bbox.max == approx((20.0, 10.0, 3.0), abs=1e-6)


def test_separate_ledges_are_separate_regions_largest_first():
    overhang = detect_overhang(_two_ledges())
    areas = [r.area_mm2 for r in overhang.regions]
    assert areas == approx([200.0, 60.0], rel=1e-6)
    assert overhang.regions[1].centroid_mm == approx((-13.0, 0.0, -1.0), abs=1e-6)
    assert sum(areas) == approx(overhang.area_mm2, rel=1e-12)


def test_a_sloped_ceiling_region_reads_its_analytic_area_and_angle():
    overhang = detect_overhang(_sloped_ledge())
    (region,) = overhang.regions
    assert region.area_mm2 == approx(20 * sqrt(116), rel=1e-6)
    assert region.max_angle_deg == approx(degrees(atan(10 / 4)), abs=1e-6)
    assert region.centroid_mm == approx((15.0, 0.0, 0.0), abs=1e-6)
    assert overhang.area_mm2 == approx(region.area_mm2, rel=1e-12)


def test_regions_hold_only_area_past_the_threshold():
    # 68.2° counts at 45° and not at 70°; the reading stays either way.
    assert detect_overhang(_sloped_ledge(), angle_threshold_deg=70.0).regions == ()


def test_the_build_plate_face_is_never_a_region():
    overhang = detect_overhang(_two_ledges())
    assert all(r.bbox.min[2] > -10.0 for r in overhang.regions)


def test_regions_sum_to_the_aggregate_on_curved_geometry():
    with BuildPart() as p:
        Box(30, 30, 30)
        with Locations((0, 0, 0)):
            Sphere(12, mode=Mode.SUBTRACT)
        Cylinder(4, 40, rotation=(90, 0, 0), mode=Mode.SUBTRACT)
    overhang = detect_overhang(p.part)
    assert len(overhang.regions) > 1
    assert sum(r.area_mm2 for r in overhang.regions) == approx(
        overhang.area_mm2, rel=1e-12
    )
    areas = [r.area_mm2 for r in overhang.regions]
    assert areas == sorted(areas, reverse=True)


def test_per_face_facets_are_exactly_the_whole_part_facets():
    # Re-meshing a face on its own triangulates it differently, which
    # would let the regions drift from the aggregate on curved parts.
    part = Box(30, 30, 30) - Sphere(12) - Rot(90, 0, 0) * Cylinder(4, 40)
    whole = _tessellate(part)
    grouped = _tessellate_faces(part)
    assert len(grouped) == len(part.faces())
    assert [tuple(t.centroid) for face in grouped for t in face] == [
        tuple(t.centroid) for t in whole
    ]
