from __future__ import annotations

from dataclasses import dataclass

from build123d import Axis, Part, Vector

from cad_khana.core.tessellation import (
    TESSELLATION_TOLERANCE_MM,
    Triangle,
    _tessellate,
)

BACKOFF_MM = 4 * TESSELLATION_TOLERANCE_MM
MIN_SPAN_MM = 1e-4
WEDGE_ALIGNMENT = 0.7


@dataclass(frozen=True)
class WallSample:
    """One ray-measured wall reading.

    `alignment` is the exit face's outward normal projected on the ray:
    1.0 is a slab with parallel faces, falling toward 0 as the two surfaces
    splay apart. A minimum reported at low alignment is the tip of a
    wedge-shaped feature rather than a wall — real material, but not a wall
    thickness. It is reported, never filtered.

    It characterises the reading on its own because the entry alignment is
    -1 by construction: a sample only ever spans the facet its ray was cast
    for (see `_wall_span`).
    """

    thickness_mm: float
    at: tuple[float, float, float]
    alignment: float


def _crossings(part: Part, triangle: Triangle) -> list[tuple[float, Vector, float]]:
    """Distance, point and signed exit alignment for every surface crossing
    along the inward normal, ordered away from the origin.

    The origin is backed off *outside* the surface: on curved faces a facet
    centroid sags up to the tessellation tolerance into the void, and a ray
    started there re-hits the very surface it came from within that distance.
    """
    inward = -triangle.normal
    origin = triangle.centroid - inward * BACKOFF_MM
    axis = Axis(
        origin=(origin.X, origin.Y, origin.Z),
        direction=(inward.X, inward.Y, inward.Z),
    )
    return sorted(
        ((hit - origin).dot(inward), hit, normal.normalized().dot(inward))
        for hit, normal in part.find_intersection_points(axis)
    )


def _wall_span(crossings: list[tuple[float, Vector, float]]) -> WallSample | None:
    """Measure the one span that starts at the facet the ray was cast for:
    its first crossing (an entry, `alignment < 0`) paired with the next exit.

    Only that span is a thickness — the ray is normal to its entry face by
    construction. A ray carries on for the whole depth of the part, and every
    later entry is into some *other* feature downstream, crossed at whatever
    oblique angle the originating facet happens to make with it. Those chords
    are real material but not wall thicknesses, and a grazed corner yields an
    arbitrarily short one. Restricting to the originating span costs no
    coverage: every face is sampled from its own facets, so every wall is
    measured by a ray normal to it.

    A ray whose first crossing is an exit started inside material — the
    backed-off origin fell in a crevice narrower than the backoff — and never
    entered here, so it contributes nothing. The rejection stays geometric,
    never by magnitude.
    """
    forward = [c for c in crossings if c[0] >= 0]
    if not forward or forward[0][2] >= 0:
        return None
    entered, at, _ = forward[0]
    leaving = next(((d, a) for d, _, a in forward[1:] if a > 0), None)
    if leaving is None:
        return None
    span, alignment = leaving[0] - entered, leaving[1]
    return (
        WallSample(span, (at.X, at.Y, at.Z), alignment)
        if span > MIN_SPAN_MM
        else None
    )


def _sample(part: Part, triangle: Triangle) -> WallSample | None:
    return _wall_span(_crossings(part, triangle)) if triangle.area > 0 else None


def min_wall(part: Part) -> WallSample | None:
    samples = (
        s for t in _tessellate(part) if (s := _sample(part, t)) is not None
    )
    return min(samples, key=lambda s: s.thickness_mm, default=None)
