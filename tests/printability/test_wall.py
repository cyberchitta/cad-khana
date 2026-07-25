from build123d import (
    Box,
    BuildPart,
    Cone,
    Cylinder,
    Location,
    Locations,
    Mode,
)
from pytest import approx

from cad_khana.core.tessellation import _tessellate
from cad_khana.printability.wall import _crossings, min_wall


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def _plate(x: float, y: float, z: float):
    with BuildPart() as p:
        Box(x, y, z)
    return p.part


def test_min_wall_reports_thinnest_dimension():
    assert min_wall(_plate(20, 20, 2)).thickness_mm == approx(2.0, abs=0.05)


def test_min_wall_for_cube_equals_edge_length():
    assert min_wall(_cube(10)).thickness_mm == approx(10.0, abs=0.05)


def test_min_wall_returns_sample_for_solid_part():
    sample = min_wall(_cube(5))
    assert isinstance(sample.thickness_mm, float)
    assert len(sample.at) == 3


def test_min_wall_witness_lands_on_thin_feature():
    # 10 mm cube with a 1 mm-thick fin off its +X face: the witness
    # must land on the fin (x > 5, on a z = ±0.5 face), not the cube.
    with BuildPart() as p:
        Box(10, 10, 10)
        with Locations((10, 0, 0)):
            Box(10, 4, 1)
    sample = min_wall(p.part)
    assert sample.thickness_mm == approx(1.0, abs=0.05)
    x, _, z = sample.at
    assert x > 5.0
    assert abs(z) == approx(0.5, abs=0.05)


def _tube(r_outer: float, wall: float, height: float):
    with BuildPart() as p:
        Cylinder(r_outer, height)
        Cylinder(r_outer - wall, height, mode=Mode.SUBTRACT)
    return p.part


def test_curved_wall_is_not_underestimated_by_facet_sag():
    # A facet centroid on a curved face sags into the void by up to the
    # tessellation tolerance; a ray started there re-hits the surface it
    # came from. Before entry/exit pairing this read 0.146 mm.
    assert min_wall(_tube(60, 1.2, 6)).thickness_mm == approx(1.2, abs=0.02)


def test_facet_sag_error_does_not_grow_with_radius():
    # The re-hit distance scales with the facet chord, so the artifact got
    # worse on larger radii while the true wall stayed put.
    small, large = min_wall(_tube(10, 1.5, 5)), min_wall(_tube(120, 1.5, 5))
    assert small.thickness_mm == approx(1.5, abs=0.02)
    assert large.thickness_mm == approx(1.5, abs=0.02)


def test_tapered_wall_measures_perpendicular_thickness():
    # Cone shells offset 1.2 mm radially over a 14.9 deg taper: the true
    # perpendicular wall is 1.2 * cos(14.9 deg). Read 0.99 mm before pairing.
    with BuildPart() as p:
        Cone(20, 12, 30)
        Cone(18.8, 10.8, 30, mode=Mode.SUBTRACT)
    assert min_wall(p.part).thickness_mm == approx(1.16, abs=0.02)


def test_thin_feature_of_small_area_is_never_discarded():
    # The false-negative guard: rejection is geometric (a ray that never
    # entered material), never by magnitude or by how little area is thin.
    with BuildPart() as p:
        Box(40, 30, 10)
        with Locations((0, 0, 0.3)):
            Box(4, 30, 9.4, mode=Mode.SUBTRACT)
    sample = min_wall(p.part)
    assert sample.thickness_mm == approx(0.6, abs=0.02)
    assert sample.alignment == approx(1.0, abs=0.05)


def test_slab_reads_full_alignment():
    assert min_wall(_plate(20, 20, 2)).alignment == approx(1.0, abs=0.05)


def _corner_clip():
    # Two disjoint 4 mm plates. The ray cast from the facet centred on
    # (-3.333, -2, -1) crosses its own plate (span 4 mm), travels ~47 mm
    # through air, and clips the far corner of the second plate — entering
    # its long face and leaving through the end face 0.1 mm later. The
    # second plate is placed and rotated so that chord is a near miss.
    with BuildPart() as p:
        Box(20, 4, 6)
        with Locations(Location((-7.8283, 40, 0), (0, 0, 75))):
            Box(20, 4, 6)
    return p.part


def _clipping_ray(part):
    triangle = next(
        t
        for t in _tessellate(part)
        if abs(t.centroid.X + 10 / 3) < 0.01 and abs(t.centroid.Y + 2) < 0.01
    )
    return _crossings(part, triangle)


def test_fixture_still_grazes_the_far_corner():
    # Guards the regression test below: if the tessellation ever shifts the
    # ray off the corner, this fails loudly rather than passing vacuously.
    crossings = _clipping_ray(_corner_clip())
    forward = [c for c in crossings if c[0] >= 0]
    assert len(forward) == 4
    assert forward[3][0] - forward[2][0] == approx(0.1, abs=0.01)


def test_downstream_chord_is_not_a_wall_thickness():
    # Both plates are 4 mm thick. The 0.1 mm corner chord is real material
    # but not a wall: the ray enters it at 75 deg, so its length says nothing
    # about the plate. Measuring only the originating span reports 4 mm; the
    # far corner is measured properly by rays cast from its own facets.
    sample = min_wall(_corner_clip())
    assert sample.thickness_mm == approx(4.0, abs=0.02)


def test_grazing_chord_reads_as_high_alignment():
    # Why the chord cannot be screened out after the fact: its exit alignment
    # is 0.97, indistinguishable from a genuine sliver between parallel faces.
    # Only the entry — the facet the ray was cast for — separates the cases.
    crossings = _clipping_ray(_corner_clip())
    forward = [c for c in crossings if c[0] >= 0]
    assert forward[2][2] == approx(-0.259, abs=0.01)
    assert forward[3][2] == approx(0.966, abs=0.01)


def test_wedge_tip_is_reported_with_low_alignment():
    # A solid cone has no wall, but the rim is a genuine wedge of material.
    # It is reported (never filtered), and low alignment is the tell that
    # the minimum sits at a feature tip rather than between parallel faces.
    with BuildPart() as p:
        Cone(5.0, 0.0, 8.0)
    sample = min_wall(p.part)
    assert sample.thickness_mm < 0.5
    assert sample.alignment < 0.7
