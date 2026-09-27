from __future__ import annotations

from dataclasses import dataclass
from itertools import accumulate, pairwise

from build123d import Part, Vector
from OCP.BRep import BRep_Tool
from OCP.TopLoc import TopLoc_Location

TESSELLATION_TOLERANCE_MM = 0.1
TESSELLATION_ANGULAR_TOLERANCE = 0.3


@dataclass(frozen=True)
class Triangle:
    corners: tuple[Vector, Vector, Vector]
    centroid: Vector
    normal: Vector
    area: float


def _triangle(a: Vector, b: Vector, c: Vector) -> Triangle:
    cross = (b - a).cross(c - a)
    length = cross.length
    return Triangle(
        corners=(a, b, c),
        centroid=(a + b + c) / 3,
        normal=cross / length if length > 0 else cross,
        area=length / 2,
    )


def _tessellate(part: Part) -> tuple[Triangle, ...]:
    verts, tris = part.tessellate(
        TESSELLATION_TOLERANCE_MM, TESSELLATION_ANGULAR_TOLERANCE
    )
    return tuple(_triangle(verts[a], verts[b], verts[c]) for a, b, c in tris)



def _tessellate_faces(part: Part) -> tuple[tuple[Triangle, ...], ...]:
    """``_tessellate``'s facets, grouped by the B-rep face each lies on.
    ``Shape.tessellate`` concatenates face by face in ``faces()`` order,
    so each face's triangle count slices the one mesh — re-meshing a face
    on its own would triangulate it differently."""
    triangles = _tessellate(part)
    counts = tuple(
        BRep_Tool.Triangulation_s(face.wrapped, TopLoc_Location()).NbTriangles()
        for face in part.faces()
    )
    bounds = (0, *accumulate(counts))
    return tuple(triangles[a:b] for a, b in pairwise(bounds))
