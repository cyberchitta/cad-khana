from __future__ import annotations

from dataclasses import dataclass

from build123d import Part, Vector

TESSELLATION_TOLERANCE_MM = 0.1
TESSELLATION_ANGULAR_TOLERANCE = 0.3


@dataclass(frozen=True)
class Triangle:
    centroid: Vector
    normal: Vector
    area: float


def _triangle(a: Vector, b: Vector, c: Vector) -> Triangle:
    cross = (b - a).cross(c - a)
    length = cross.length
    return Triangle(
        centroid=(a + b + c) / 3,
        normal=cross / length if length > 0 else cross,
        area=length / 2,
    )


def _tessellate(part: Part) -> tuple[Triangle, ...]:
    verts, tris = part.tessellate(
        TESSELLATION_TOLERANCE_MM, TESSELLATION_ANGULAR_TOLERANCE
    )
    return tuple(_triangle(verts[a], verts[b], verts[c]) for a, b, c in tris)
