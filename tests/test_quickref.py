"""Every trap in ``references/build123d_quickref.md`` still reproduces.

Each entry there states what build123d does on the locked version. Each
test here asserts that behaviour, so an upstream fix turns the test red
and says to retire or reword the entry. ``ENTRIES`` ties every test to
the entry it backs; ``test_every_entry_has_a_test`` holds the doc and
this file to each other in both directions, and goes red when the lock
moves off the version the entries name — the cue to re-probe them.
"""

import sys
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path

from build123d import (
    Axis,
    Box,
    BuildPart,
    BuildSketch,
    Compound,
    Cylinder,
    Face,
    GeomType,
    Hole,
    Plane,
    Polygon,
    Pos,
    Rectangle,
    Rot,
    ShapeList,
    Vector,
    extrude,
    offset,
    revolve,
)

QUICKREF = (
    Path(__file__).parent.parent / "skills/cad-khana/references/build123d_quickref.md"
).read_text()

TOL = 1e-6
CLOCKWISE = ((0, 0), (0, 10), (10, 10), (10, 0))


def _near(a: Vector, b: tuple[float, float, float]) -> bool:
    return (a - Vector(*b)).length < TOL


def _flat(v: Vector) -> Vector:
    return Vector(v.X, v.Y, 0)


def _profile() -> ShapeList[Face]:
    return (Pos(10, 0) * Rectangle(4, 4, align=None)).faces()


def test_sector_apex_leaves_axis() -> None:
    sector = Cylinder(10, 5, arc_size=90)
    box = sector.bounding_box()
    assert _near(box.min, (-5, -5, -2.5))
    assert _near(box.max, (5, 5, 2.5))
    assert any(_near(v.center(), (-5, -5, -2.5)) for v in sector.vertices())
    # build123d's annotation omits None, which the entry's fix passes
    apexed = Cylinder(10, 5, arc_size=90, align=None)  # pyright: ignore[reportArgumentType]
    assert _near(apexed.bounding_box().min, (0, 0, 0))


def test_location_times_compound_is_a_compound() -> None:
    """The entry names 0.11.1 as returning a ``list``; on the locked version
    it is fixed, so this pins the fix — a regression goes red too."""
    pair = Compound([Box(1, 1, 1), Pos(3, 0, 0) * Box(1, 1, 1)])
    assert isinstance(Pos(1, 0, 0) * pair, Compound)


def test_rot_composes_x_outermost() -> None:
    unit = Pos(1, 0, 0)
    assert _near((Rot(90, 90, 0) * unit).position, (0, 1, 0))
    assert _near((Rot(90, 0, 0) * Rot(0, 90, 0) * unit).position, (0, 1, 0))
    assert _near((Rot(0, 90, 0) * Rot(90, 0, 0) * unit).position, (0, 0, -1))


def test_cylinder_face_center_is_on_surface() -> None:
    side = Cylinder(5, 10).faces().filter_by(GeomType.CYLINDER)[0]
    assert _near(side.center(), (-5, 0, 0))
    axis = side.axis_of_rotation
    assert axis is not None
    assert _near(axis.direction, (0, 0, 1))
    assert _near(_flat(axis.position), (0, 0, 0))
    with BuildPart() as drilled:
        Box(20, 20, 10)
        Hole(3)
    assert drilled.part is not None
    bore = drilled.part.faces().filter_by(GeomType.CYLINDER)[0]
    assert abs(_flat(bore.center()).length - 3) < TOL


def test_clockwise_extrude_grows_down() -> None:
    algebraic = extrude(Polygon(*CLOCKWISE, align=None), 5).bounding_box()
    directed = extrude(Polygon(*CLOCKWISE, align=None), 5, dir=(0, 0, 1))
    with BuildPart() as builder:
        with BuildSketch():
            Polygon(*CLOCKWISE, align=None)
        extrude(amount=5)
    assert _near(algebraic.min, (0, 0, -5))
    assert _near(algebraic.max, (10, 10, 0))
    assert _near(directed.bounding_box().max, (10, 10, 5))
    assert builder.part is not None
    assert _near(builder.part.bounding_box().max, (10, 10, 5))


def test_plane_xz_normal_is_minus_y() -> None:
    with BuildPart() as slab:
        with BuildSketch(Plane.XZ):
            Rectangle(4, 4)
        extrude(amount=5)
    assert _near(Plane.XZ.z_dir, (0, -1, 0))
    assert _near(Plane.XZ.y_dir, (0, 0, 1))
    assert _near(Plane.YZ.z_dir, (1, 0, 0))
    assert _near((Plane.XZ * Pos(1, 2, 3)).position, (1, -3, 2))
    assert slab.part is not None
    assert _near(slab.part.bounding_box().min, (-2, -5, -2))


def test_offset_past_half_returns_solid_unchanged() -> None:
    block = Box(10, 10, 10)
    top = block.faces().sort_by(Axis.Z)[-1]
    shelled = offset(block, amount=-6, openings=top)
    assert abs(shelled.volume - 1000) < TOL
    assert shelled.is_valid
    assert abs(offset(block, amount=-4, openings=top).volume - 976) < TOL


def test_revolve_arc_wraps_and_zero_is_full() -> None:
    profile = _profile()
    full = revolve(profile, Axis.Y, 360).volume
    assert abs(revolve(profile, Axis.Y, 0).volume - full) < TOL
    assert abs(revolve(profile, Axis.Y, 450).volume - full / 4) < TOL


def test_revolve_about_normal_is_valid_and_empty() -> None:
    flat = revolve(_profile(), Axis.Z, 90)
    assert abs(flat.volume) < TOL
    assert flat.is_valid


def test_degenerate_inputs_build_invalid_shapes() -> None:
    assert not Polygon((0, 0), (5, 0), (10, 0), align=None).is_valid
    assert not Polygon((0, 0), (10, 10), (10, 0), (0, 10), align=None).is_valid
    assert not Cylinder(5, 10, arc_size=0).is_valid
    assert not Cylinder(5, 10, arc_size=450).is_valid


# Each entry's opening words, and the tests that hold it.
ENTRIES: dict[str, tuple[Callable[[], None], ...]] = {
    "A sector's default alignment moves its apex off the axis": (
        test_sector_apex_leaves_axis,
    ),
    "`Location * Compound` can return a plain `list`": (
        test_location_times_compound_is_a_compound,
    ),
    "`Rot(rx, ry, rz)` applies its three angles as `Rx·Ry·Rz`": (
        test_rot_composes_x_outermost,
    ),
    "`.center()` on a cylindrical face is a point on the surface": (
        test_cylinder_face_center_is_on_surface,
    ),
    "Algebraic `extrude` grows along the face normal": (
        test_clockwise_extrude_grows_down,
    ),
    "`Plane.XZ`'s normal is −Y": (test_plane_xz_normal_is_minus_y,),
    "## Inputs built instead of refused": (
        test_offset_past_half_returns_solid_unchanged,
        test_revolve_arc_wraps_and_zero_is_full,
        test_revolve_about_normal_is_valid_and_empty,
        test_degenerate_inputs_build_invalid_shapes,
    ),
}


def test_every_entry_has_a_test() -> None:
    """Each entry names the locked version exactly once, so the count of
    that version in the doc is the count of entries."""
    flat = " ".join(QUICKREF.split())
    tests = {
        name
        for name, member in vars(sys.modules[__name__]).items()
        if name.startswith("test_") and callable(member)
    } - {"test_every_entry_has_a_test"}
    held = {test.__name__ for group in ENTRIES.values() for test in group}
    assert [e for e in ENTRIES if e not in flat] == []
    assert QUICKREF.count(version("build123d")) == len(ENTRIES)
    assert tests == held
