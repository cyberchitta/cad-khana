from __future__ import annotations

from dataclasses import dataclass
from math import asin, degrees

from build123d import Part, Vector

from cad_khana.core.tessellation import Triangle, _tessellate

BUILD_PLATE_EPSILON_MM = 1e-3


@dataclass(frozen=True)
class Overhang:
    area_mm2: float
    max_angle_deg: float


def _overhang_angle_deg(normal: Vector, up: Vector) -> float:
    downward = min(1.0, max(0.0, -normal.dot(up)))
    return degrees(asin(downward))


def _build_plate_level(part: Part, up: Vector) -> float:
    bb = part.bounding_box()
    corners = (
        Vector(bb.min.X, bb.min.Y, bb.min.Z),
        Vector(bb.max.X, bb.min.Y, bb.min.Z),
        Vector(bb.min.X, bb.max.Y, bb.min.Z),
        Vector(bb.max.X, bb.max.Y, bb.min.Z),
        Vector(bb.min.X, bb.min.Y, bb.max.Z),
        Vector(bb.max.X, bb.min.Y, bb.max.Z),
        Vector(bb.min.X, bb.max.Y, bb.max.Z),
        Vector(bb.max.X, bb.max.Y, bb.max.Z),
    )
    return min(c.dot(up) for c in corners)


def _on_build_plate(triangle: Triangle, up: Vector, min_up: float) -> bool:
    on_plane = abs(triangle.centroid.dot(up) - min_up) < BUILD_PLATE_EPSILON_MM
    faces_down = triangle.normal.dot(up) < -0.999
    return on_plane and faces_down


def detect_overhang(
    part: Part,
    *,
    up_axis: tuple[float, float, float] = (0, 0, 1),
    angle_threshold_deg: float = 45.0,
) -> Overhang | None:
    up = Vector(*up_axis).normalized()
    min_up = _build_plate_level(part, up)
    triangles = _tessellate(part)
    flagged = tuple(
        (t.area, ang)
        for t in triangles
        if (ang := _overhang_angle_deg(t.normal, up)) > angle_threshold_deg
        and not _on_build_plate(t, up, min_up)
    )
    if not flagged:
        return None
    return Overhang(
        area_mm2=sum(a for a, _ in flagged),
        max_angle_deg=max(ang for _, ang in flagged),
    )
