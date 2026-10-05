from collections.abc import Callable
from math import cos, hypot, pi, radians, sin

import pytest
from build123d import Box, Cone, Cylinder, Part, Pos, Sphere, Torus, Vector, fillet

from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.assertions import evaluate
from cad_khana.mechanism.keepout import swept

TILT = radians(30)
Travel = tuple[float, float, float]


def _box() -> Part:
    return Box(10, 20, 30)


def _notched() -> Part:
    return Part([Box(10, 20, 30) - Box(12, 6, 10)])


def _cylinder() -> Part:
    return Cylinder(5, 20)


def _sphere() -> Part:
    return Sphere(5)


def _cone() -> Part:
    return Cone(6, 2, 10)


# Each case's true volume is the body's plus the travel times the body's
# area projected along the travel — a translation's swept volume, for a
# body every line along the travel meets in one interval.
VOLUME_CASES: dict[str, tuple[Callable[[], Part], Travel, float]] = {
    "box along x": (_box, (50, 0, 0), 6000 + 50 * 600),
    "box diagonal": (_box, (30, 40, 0), 6000 + 50 * 30 * (10 * 0.8 + 20 * 0.6)),
    "notched box through its notch": (_notched, (50, 0, 0), (600 - 60) * 60),
    "cylinder along its axis": (_cylinder, (0, 0, 50), pi * 25 * 70),
    "cylinder across its axis": (_cylinder, (50, 0, 0), pi * 25 * 20 + 50 * 10 * 20),
    "cylinder tilted to the travel": (
        _cylinder,
        (50 * sin(TILT), 0, 50 * cos(TILT)),
        pi * 25 * 20 + 50 * (pi * 25 * cos(TILT) + 10 * 20 * sin(TILT)),
    ),
    "sphere": (_sphere, (0, 30, 0), 4 / 3 * pi * 125 + 30 * pi * 25),
    "cone across its axis": (_cone, (40, 0, 0), pi * 10 / 3 * (36 + 12 + 4) + 40 * 80),
}


@pytest.mark.parametrize("case", VOLUME_CASES)
def test_swept_volume_matches_the_analytic_sweep(case: str):
    body, travel, expected = VOLUME_CASES[case]
    result = swept(body(), travel)
    assert result.is_valid
    assert abs(result.volume - expected) < 1e-3


def test_swept_volume_of_a_filleted_box_matches_its_rounded_outline():
    body = Part([fillet(Box(10, 20, 30).edges(), 2)])
    result = swept(body, (50, 0, 0))
    # a 2 mm fillet takes (4 - pi) r^2 off each corner of the 20 x 30 outline
    assert abs(result.volume - (body.volume + 50 * (600 - (4 - pi) * 4))) < 1e-3


# Membership against geometry, not volume alone: a sweep run backwards
# has the right volume in the wrong place. A point is in the sweep when
# the travel segment ending at it meets the body. Each body here is
# convex, so a dense sample of the segment decides it; points within
# MARGIN of the boundary are left out, where sampling cannot.
MARGIN = 0.2
STEPS = 400


def _cylinder_depth(p: Vector) -> float:
    return max(hypot(p.X, p.Y) - 5, abs(p.Z) - 10)


def _sphere_depth(p: Vector) -> float:
    return p.length - 5


# _cone's radius falls from 6 at z = -5 to 2 at z = 5; dividing by the
# slant keeps the side's depth a distance, as the margin assumes.
def _cone_depth(p: Vector) -> float:
    return max((hypot(p.X, p.Y) - (4 - 0.4 * p.Z)) / hypot(1, 0.4), abs(p.Z) - 5)


MEMBERSHIP_CASES: dict[
    str, tuple[Callable[[], Part], Callable[[Vector], float], Travel]
] = {
    "cylinder across its axis": (_cylinder, _cylinder_depth, (50, 0, 0)),
    "cylinder tilted to the travel": (
        _cylinder,
        _cylinder_depth,
        (50 * sin(TILT), 0, 50 * cos(TILT)),
    ),
    "sphere": (_sphere, _sphere_depth, (0, 30, 0)),
    "cone across its axis": (_cone, _cone_depth, (40, 0, 0)),
    "cone tilted to the travel": (
        _cone,
        _cone_depth,
        (40 * sin(TILT), 0, 40 * cos(TILT)),
    ),
}


def _grid(lo: Vector, hi: Vector, n: int) -> list[Vector]:
    span = hi - lo
    return [
        Vector(lo.X + span.X * i / n, lo.Y + span.Y * j / n, lo.Z + span.Z * k / n)
        for i in range(n + 1)
        for j in range(n + 1)
        for k in range(n + 1)
    ]


@pytest.mark.parametrize("case", MEMBERSHIP_CASES)
def test_swept_holds_exactly_the_points_the_body_passes_through(case: str):
    body, depth, travel = MEMBERSHIP_CASES[case]
    d = Vector(travel)
    result = swept(body(), travel)
    box = result.bounding_box()
    pad = Vector(2, 2, 2)

    def reach(p: Vector) -> float:
        return min(depth(p - d * (t / STEPS)) for t in range(STEPS + 1))

    decided = [
        (p, r < 0)
        for p in _grid(box.min - pad, box.max + pad, 10)
        if abs(r := reach(p)) > MARGIN
    ]
    wrong = [p for p, inside in decided if result.is_inside(p) != inside]
    assert len(decided) > 500
    assert not wrong, wrong[:5]


def test_swept_refuses_a_face_it_cannot_sweep_exactly():
    with pytest.raises(ValueError, match="TORUS"):
        swept(Torus(20, 4), (0, 0, 30))


# The case the construction exists for: an obstacle the body clears at
# rest and at the end of its travel, but crosses on the way.
def _obstacle_at(y: float) -> Assembly:
    return Assembly().with_part("post", Pos(25, y, 0) * Box(4, 4, 4))


def test_a_swept_keepout_fails_an_obstacle_crossed_only_mid_travel():
    path = swept(_box(), (50, 0, 0))
    a = _obstacle_at(0).assert_clear_of("post", path, name="draw_out")  # pyright: ignore[reportUnknownMemberType] — keepout is typed Shape[Unknown]
    (result,) = evaluate(a)
    assert not result.passed


def test_a_swept_keepout_reads_the_clearance_beside_the_path():
    path = swept(_box(), (50, 0, 0))
    a = _obstacle_at(15).assert_clear_of("post", path, name="draw_out")  # pyright: ignore[reportUnknownMemberType] — keepout is typed Shape[Unknown]
    (result,) = evaluate(a)
    assert result.passed
    assert result.value is not None and abs(result.value - 3.0) < 1e-6
