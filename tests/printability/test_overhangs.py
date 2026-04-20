from build123d import Box, BuildPart, Location, Pos
from pytest import approx

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


def test_up_axis_rotates_what_counts_as_down():
    # With up_axis along +X, the cube's -X face becomes the build-plate
    # face and should not be flagged.
    assert detect_overhang(_cube(10), up_axis=(1, 0, 0)) is None


def test_custom_threshold_suppresses_shallow_overhangs():
    # Even a real overhang can be suppressed by raising the threshold.
    part = _box(20, 20, 20) + Pos(15, 0, 5) * Box(10, 20, 4)
    assert detect_overhang(part, angle_threshold_deg=95.0) is None
