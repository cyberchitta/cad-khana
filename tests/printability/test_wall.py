from build123d import Box, BuildPart
from pytest import approx

from cad_khana.printability.wall import min_wall_mm


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def _plate(x: float, y: float, z: float):
    with BuildPart() as p:
        Box(x, y, z)
    return p.part


def test_min_wall_reports_thinnest_dimension():
    assert min_wall_mm(_plate(20, 20, 2)) == approx(2.0, abs=0.05)


def test_min_wall_for_cube_equals_edge_length():
    assert min_wall_mm(_cube(10)) == approx(10.0, abs=0.05)


def test_min_wall_returns_float_for_solid_part():
    assert isinstance(min_wall_mm(_cube(5)), float)
