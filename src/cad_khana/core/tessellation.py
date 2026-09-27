from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import accumulate, pairwise

from build123d import Face, Part, Vector
from OCP.BRep import BRep_Tool
from OCP.BRepGProp import BRepGProp_Face
from OCP.GeomAPI import GeomAPI_ProjectPointOnSurf
from OCP.gp import gp_Pnt, gp_Vec
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


def on_surface(face: Face, triangle: Triangle) -> Triangle:
    """A facet re-anchored on the surface it approximates: its centroid
    projected onto the face, carrying the face's outward normal there.

    A facet's own plane is only a chord. On a trimmed curved face the mesher
    spans long triangles between trim vertices at different heights, tilted
    well off the surface — 19 deg on a cylinder whose trim edges sit at
    different z. A ray along such a normal crosses the wall slantwise, and
    two such facets can fold concavely along a chord of a convex surface,
    which reads as a crease where the surface has none. The surface normal
    is what makes a facet ray perpendicular to its entry face, and what a
    crease is judged by.
    """
    u, v = GeomAPI_ProjectPointOnSurf(
        triangle.centroid.to_pnt(), face.geom_adaptor()
    ).LowerDistanceParameters()
    point, normal = gp_Pnt(), gp_Vec()
    BRepGProp_Face(face.wrapped).Normal(u, v, point, normal)
    return replace(triangle, centroid=Vector(point), normal=Vector(normal).normalized())
