from build123d import Box, BuildPart, Locations
from pytest import approx

from cad_khana.printability.wall import min_wall


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
