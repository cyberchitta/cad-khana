from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from itertools import chain, combinations, groupby
from math import acos, ceil, cos, sin

from build123d import Axis, Part, Vector

from cad_khana.core.tessellation import (
    TESSELLATION_ANGULAR_TOLERANCE,
    TESSELLATION_TOLERANCE_MM,
    Triangle,
    _tessellate,
)

BACKOFF_MM = 4 * TESSELLATION_TOLERANCE_MM
MIN_SPAN_MM = 1e-4
WEDGE_ALIGNMENT = 0.7
CREASE_STEP_MM = 1.0
CREASE_NUDGE = 1e-3

Crossing = tuple[float, Vector, float]
Corner = tuple[float, float, float]


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
    for (see `_wall_span`), or starts at a crease along a direction the
    crease's own normals span (see `_crease_samples`).
    """

    thickness_mm: float
    at: tuple[float, float, float]
    alignment: float


def _ray(part: Part, origin: Vector, direction: Vector) -> list[Crossing]:
    """Signed distance, point and exit alignment for every surface crossing
    on the line through `origin`, ordered along `direction`."""
    axis = Axis(
        origin=(origin.X, origin.Y, origin.Z),
        direction=(direction.X, direction.Y, direction.Z),
    )
    return sorted(
        (
            ((hit - origin).dot(direction), hit, normal.normalized().dot(direction))
            for hit, normal in part.find_intersection_points(axis)
        ),
        key=lambda crossing: crossing[0],
    )


def _crossings(part: Part, triangle: Triangle) -> list[Crossing]:
    """Crossings along a facet's inward normal.

    The origin is backed off *outside* the surface: on curved faces a facet
    centroid sags up to the tessellation tolerance into the void, and a ray
    started there re-hits the very surface it came from within that distance.
    """
    inward = -triangle.normal
    return _ray(part, triangle.centroid - inward * BACKOFF_MM, inward)


def _wall_span(crossings: list[Crossing]) -> WallSample | None:
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


def _corner(v: Vector) -> Corner:
    return (round(v.X, 6), round(v.Y, 6), round(v.Z, 6))


def _creased(a: Triangle, b: Triangle) -> bool:
    """Two facets meeting concavely at more than the angular tolerance — each
    rises out of the other's plane on the void side."""
    return (
        a.normal.dot(b.normal) < cos(TESSELLATION_ANGULAR_TOLERANCE)
        and (b.centroid - a.centroid).dot(a.normal) > 0
        and (a.centroid - b.centroid).dot(b.normal) > 0
    )


def _corners(triangles: tuple[Triangle, ...]) -> dict[Corner, tuple[int, ...]]:
    """Facet indices meeting at each mesh corner, matched by position: the
    tessellation indexes each B-rep face separately, so facets either side of
    an edge share no vertex index."""
    tagged = sorted((_corner(c), i) for i, t in enumerate(triangles) for c in t.corners)
    return {
        corner: tuple(sorted({i for _, i in group}))
        for corner, group in groupby(tagged, key=lambda pair: pair[0])
    }


def _creases(
    triangles: tuple[Triangle, ...], corners: dict[Corner, tuple[int, ...]]
) -> Iterator[tuple[int, int, tuple[Corner, ...]]]:
    """Creased facet pairs, by index, with the corners they share: two for a
    crease edge, one for a crease point such as a conical pocket's apex."""
    meetings = sorted(
        (i, j, corner)
        for corner, members in corners.items()
        for i, j in combinations(members, 2)
        if _creased(triangles[i], triangles[j])
    )
    return (
        (i, j, tuple(corner for _, _, corner in shared))
        for (i, j), shared in groupby(meetings, key=lambda m: m[:2])
    )


def _fan(a: Triangle, b: Triangle) -> tuple[Vector, ...]:
    """Inward directions strictly between two creased facets' own, no more
    than the angular tolerance apart — the rays the facets of a fillet would
    have cast here, in the limit of zero radius."""
    theta = acos(max(-1.0, min(1.0, a.normal.dot(b.normal))))
    steps = ceil(theta / TESSELLATION_ANGULAR_TOLERANCE)
    return tuple(
        -(a.normal * sin((1 - k / steps) * theta) + b.normal * sin(k / steps * theta))
        / sin(theta)
        for k in range(1, steps)
    )


def _cast_points(shared: tuple[Corner, ...]) -> tuple[Vector, ...]:
    """The shared corner of a crease point; for a crease edge, the midpoints
    of equal segments no longer than `CREASE_STEP_MM` — a long mesh edge is a
    straight one, with nothing in between to stand in for it."""
    start, end = Vector(*shared[0]), Vector(*shared[-1])
    count = max(1, ceil((end - start).length / CREASE_STEP_MM))
    return tuple(start + (end - start) * ((i + 0.5) / count) for i in range(count))


def _crease_span(point: Vector, crossings: list[Crossing]) -> WallSample | None:
    """Measure from a crease to the next exit.

    The cast point is on the surface with the ray heading into material, so
    the span needs no entry crossing to open it — a ray through an edge may
    report one, two, or contradictory ones. An entry within the backoff of
    the point replaces it: a point sampled along a curved crease sags off the
    true edge by up to the tessellation tolerance, either way. An entry
    further on means the ray crossed a void first, and what follows is a
    downstream chord (see `_wall_span`) — rejected on the same grounds.
    """
    leaving = next((c for c in crossings if c[0] > MIN_SPAN_MM and c[2] > 0), None)
    if leaving is None:
        return None
    entries = [
        d for d, _, a in crossings if a < 0 and -BACKOFF_MM <= d < leaving[0]
    ]
    if entries and entries[-1] > BACKOFF_MM:
        return None
    span = leaving[0] - (entries[-1] if entries else 0.0)
    return (
        WallSample(span, (point.X, point.Y, point.Z), leaving[2])
        if span > MIN_SPAN_MM
        else None
    )


def _open_fan(
    pair: tuple[int, int],
    shared: tuple[Corner, ...],
    triangles: tuple[Triangle, ...],
    corners: dict[Corner, tuple[int, ...]],
) -> tuple[Vector, ...]:
    """The part of a crease's fan that heads inward of every bystander — each
    other facet on the same mesh edge, or at the same corner."""
    bystanders = tuple(
        triangles[k]
        for k in set.intersection(*(set(corners[c]) for c in shared)) - set(pair)
    )
    return tuple(
        direction
        for direction in _fan(triangles[pair[0]], triangles[pair[1]])
        if all(direction.dot(t.normal) < 0 for t in bystanders)
    )


def _crease_samples(part: Part, triangles: tuple[Triangle, ...]) -> Iterator[WallSample]:
    """Readings from sharp concave edges and points.

    A facet ray only measures a thin direction some facet faces. Under a
    V-groove root or a conical pocket's apex none does, and the flat face
    opposite is a few large facets with no centroid beneath the feature, so
    the thinnest material in the part goes unsampled from both sides. Convex
    creases need nothing: thickness peaks at a ridge, it does not dip.

    Two facets being concave to each other settles that their fan heads into
    material only where nothing else bounds it. Other facets usually do: a
    groove running out through a side face ends at a corner that face shares,
    and two blocks touching along a line put four facets on one edge. A
    direction counts only if it heads inward of every such bystander;
    otherwise it leaves through one of them microns away and reads as a
    sliver that is not there.

    Each cast point is nudged onto one facet so that no ray runs through the
    crease itself — the kernel cannot take a normal at a cone's apex.
    """
    corners = _corners(triangles)
    return (
        sample
        for i, j, shared in _creases(triangles, corners)
        for direction in _open_fan((i, j), shared, triangles, corners)
        for point in _cast_points(shared)
        if (
            sample := _crease_span(
                point,
                _ray(
                    part,
                    point + (triangles[i].centroid - point) * CREASE_NUDGE,
                    direction,
                ),
            )
        )
        is not None
    )


def min_wall(part: Part) -> WallSample | None:
    triangles = _tessellate(part)
    facet_samples = (s for t in triangles if (s := _sample(part, t)) is not None)
    return min(
        chain(facet_samples, _crease_samples(part, triangles)),
        key=lambda s: s.thickness_mm,
        default=None,
    )
