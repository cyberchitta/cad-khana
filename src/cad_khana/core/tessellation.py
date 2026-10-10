from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import accumulate, pairwise

from build123d import Face, GeomType, Part, Vector
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

    @staticmethod
    def create(a: Vector, b: Vector, c: Vector) -> Triangle:
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
    return tuple(Triangle.create(verts[a], verts[b], verts[c]) for a, b, c in tris)


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
    foot = _projected(face, triangle)
    return replace(foot, normal=foot.normal.normalized())


def _projected(face: Face, triangle: Triangle) -> Triangle:
    """``triangle`` with its centroid projected onto ``face``'s surface and
    the face's outward normal there, unnormalised: it has no length where
    the surface has no normal, at a cone's apex or a sphere's pole."""
    u, v = GeomAPI_ProjectPointOnSurf(
        triangle.centroid.to_pnt(), face.geom_adaptor()
    ).LowerDistanceParameters()
    point, normal = gp_Pnt(), gp_Vec()
    BRepGProp_Face(face.wrapped).Normal(u, v, point, normal)
    return replace(triangle, centroid=Vector(point), normal=Vector(normal))


def normals(face: Face, triangle: Triangle) -> tuple[Vector | None, ...]:
    """The face's outward normals over one facet: at its three corners,
    which the mesher put on the surface, then at its centroid's
    projection. A planar face has the facet's own normal throughout.
    ``None`` where the surface has no normal."""
    at = (
        _projected(face, replace(triangle, centroid=p)).normal
        for p in (*triangle.corners, triangle.centroid)
    )
    return (
        (triangle.normal,) * 4
        if face.geom_type == GeomType.PLANE
        else tuple(n.normalized() if n.length > 0 else None for n in at)
    )
