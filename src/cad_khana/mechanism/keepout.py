# OCP ships no type stubs, so these rules would flag every call into it.
# pyright: reportMissingTypeStubs=false, reportAttributeAccessIssue=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
"""Keep-out constructions — solids a claim needs that Build123d lacks.

This is the one place cad-khana builds geometry rather than measuring
it. A construction belongs here only when an assertion needs an exact
shape and Build123d has none, and each says what would retire it.

``swept`` is the volume a body passes through translating along a
vector — a draw-out or drop-in path for ``assert_clear_of``. A point is
in it when it is in the body at rest, or the segment back to rest
leaves the body through a face that faces the travel; so the sweep is
the body plus each travel-facing face extruded along the vector. A
curved face is first split along its silhouette, where it turns from
facing the travel to facing away, or its extrusion would fold over
itself. Exact — not sampled — but only where the silhouette is: on
planes and the quadrics, OCCT's outline of a face is a line or circle.
Elsewhere (a torus, a B-spline) it is an approximation, and the union
was seen to bulge 0.4 mm on a torus, so those faces are refused.

Retires when Build123d (or OCCT) ships a translational solid sweep.
Build123d 0.13's ``sweep`` takes a ``Solid`` but pipe-sweeps each face
separately; gumyr/build123d#1039 (*Add Solid.sweep*) is a different
operation, a section along a path.
"""

from __future__ import annotations

from build123d import Compound, Edge, Face, GeomType, Part, Vector, VectorLike, extrude
from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape, HLRBRep_TypeOfResultingEdge
from OCP.TopTools import TopTools_ListOfShape

EXACT_SILHOUETTES = frozenset(
    {GeomType.PLANE, GeomType.CYLINDER, GeomType.CONE, GeomType.SPHERE}
)
FACING_EPSILON = 1e-9


def swept(body: Part, by: VectorLike) -> Part:
    """The volume ``body`` passes through translating by ``by``, exactly.

    Raises ``ValueError`` naming any face kind other than a plane,
    cylinder, cone or sphere, rather than return an approximate path.
    """
    travel = Vector(by)
    direction = travel.normalized()
    refused = sorted(
        {f.geom_type.name for f in body.faces()} - {g.name for g in EXACT_SILHOUETTES}
    )
    if refused:
        raise ValueError(
            f"swept() is exact only on planes, cylinders, cones and spheres; "
            f"this body has {', '.join(refused)} faces. Fall back to stepped "
            f"copies of the body in a Compound, which is sampled."
        )
    prisms = [
        extrude(piece, amount=travel.length, dir=direction)
        for face in body.faces()
        for piece in _split_at_silhouette(face, direction)
        if _facing(piece, direction) > FACING_EPSILON
    ]
    return Part([body.fuse(*prisms).clean()])


def _split_at_silhouette(face: Face, direction: Vector) -> list[Face]:
    edges = [] if face.geom_type == GeomType.PLANE else _silhouette(face, direction)
    return _split(face, edges) if edges else [face]


def _silhouette(face: Face, direction: Vector) -> list[Edge]:
    algo = HLRBRep_Algo()
    algo.Add(face.wrapped)
    algo.Projector(
        HLRAlgo_Projector(
            gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(direction.X, direction.Y, direction.Z))
        )
    )
    algo.Update()
    algo.Hide()
    shapes = HLRBRep_HLRToShape(algo)
    outlines = (
        shapes.CompoundOfEdges(
            HLRBRep_TypeOfResultingEdge.HLRBRep_OutLine, visible, True
        )
        for visible in (True, False)
    )
    return [edge for c in outlines if not c.IsNull() for edge in Compound(c).edges()]


def _split(face: Face, edges: list[Edge]) -> list[Face]:
    splitter = BRepAlgoAPI_Splitter()
    arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    arguments.Append(face.wrapped)
    for edge in edges:
        tools.Append(edge.wrapped)
    splitter.SetArguments(arguments)
    splitter.SetTools(tools)
    splitter.Build()
    return Compound(splitter.Shape()).faces()


def _facing(face: Face, direction: Vector) -> float:
    """The outward normal's component along the travel, read inside the
    face — a mesh triangle's centroid, since a trimmed face's parametric
    centre can lie outside it. After the silhouette split one reading
    holds for the whole face."""
    vertices, triangles = face.tessellate(0.1)
    corners = max(
        (tuple(vertices[i] for i in t) for t in triangles),
        key=lambda c: (c[1] - c[0]).cross(c[2] - c[0]).length,
    )
    return face.normal_at(sum(corners, Vector()) / 3).dot(direction)
