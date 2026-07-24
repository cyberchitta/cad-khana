from __future__ import annotations

from dataclasses import dataclass

from build123d import Axis, Part, Vector

from cad_khana.core.tessellation import Triangle, _tessellate

RAY_OFFSET_MM = 1e-4
SLIVER_HIT_DISTANCE_MM = 0.05


@dataclass(frozen=True)
class WallSample:
    """One ray-sampled wall reading: the local thickness and the surface
    point (triangle centroid) the inward ray was cast from."""

    thickness_mm: float
    at: tuple[float, float, float]


def _wall_thickness_at(part: Part, triangle: Triangle) -> float | None:
    if triangle.area <= 0:
        return None
    inward = -triangle.normal
    origin = triangle.centroid + inward * RAY_OFFSET_MM
    axis = Axis(
        origin=(origin.X, origin.Y, origin.Z),
        direction=(inward.X, inward.Y, inward.Z),
    )
    forward = tuple(
        d
        for hit, _ in part.find_intersection_points(axis)
        if (d := (hit - origin).dot(inward)) > SLIVER_HIT_DISTANCE_MM
    )
    return min(forward) + RAY_OFFSET_MM if forward else None


def _sample(part: Part, triangle: Triangle) -> WallSample | None:
    thickness = _wall_thickness_at(part, triangle)
    if thickness is None:
        return None
    c: Vector = triangle.centroid
    return WallSample(thickness, (c.X, c.Y, c.Z))


def min_wall(part: Part) -> WallSample | None:
    samples = tuple(
        s for t in _tessellate(part) if (s := _sample(part, t)) is not None
    )
    return min(samples, key=lambda s: s.thickness_mm) if samples else None
