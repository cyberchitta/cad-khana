from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

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


def _spans(crossings: list[tuple[float, Vector, float]]) -> Iterator[WallSample]:
    """Pair each entry into material with the next exit out of it.

    A crossing whose face points back along the ray (`alignment < 0`) is an
    entry, one whose face points away (`alignment > 0`) an exit. Pairing them
    measures material actually traversed, so a ray that never entered
    contributes nothing — the rejection is geometric, never by magnitude.
    """
    entry: tuple[float, Vector] | None = None
    for distance, point, alignment in crossings:
        if distance < 0:
            continue
        if alignment < 0:
            entry = (distance, point)
        elif entry is not None:
            span, at = distance - entry[0], entry[1]
            if span > MIN_SPAN_MM:
                yield WallSample(span, (at.X, at.Y, at.Z), alignment)
            entry = None


def _samples(part: Part, triangle: Triangle) -> Iterator[WallSample]:
    return _spans(_crossings(part, triangle)) if triangle.area > 0 else iter(())


def min_wall(part: Part) -> WallSample | None:
    samples = tuple(s for t in _tessellate(part) for s in _samples(part, t))
    return min(samples, key=lambda s: s.thickness_mm) if samples else None
