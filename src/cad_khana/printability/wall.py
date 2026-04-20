from __future__ import annotations

from build123d import Axis, Part

from cad_khana.core.tessellation import Triangle, _tessellate

RAY_OFFSET_MM = 1e-4
SLIVER_HIT_DISTANCE_MM = 0.05


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


def min_wall_mm(part: Part) -> float | None:
    triangles = _tessellate(part)
    hits = tuple(
        d for t in triangles if (d := _wall_thickness_at(part, t)) is not None
    )
    return min(hits) if hits else None
