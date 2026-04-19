from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from math import asin, degrees
from typing import TYPE_CHECKING

from build123d import Axis, Part, Vector

if TYPE_CHECKING:
    from cad_khana.core.assembly import Assembly, PlacedPart

SCHEMA_VERSION = "0.1"
INTERFERENCE_VOLUME_EPSILON_MM3 = 0.001
OVERHANG_ANGLE_THRESHOLD_DEG = 45.0
TESSELLATION_TOLERANCE_MM = 0.1
TESSELLATION_ANGULAR_TOLERANCE = 0.3
RAY_OFFSET_MM = 1e-4
SLIVER_HIT_DISTANCE_MM = 0.05


@dataclass(frozen=True)
class BBox:
    min: tuple[float, float, float]
    max: tuple[float, float, float]


@dataclass(frozen=True)
class PartDiagnostics:
    bbox: BBox
    volume_mm3: float
    min_wall_mm: float | None = None


@dataclass(frozen=True)
class Interference:
    a: str
    b: str
    volume_mm3: float
    centroid: tuple[float, float, float]


@dataclass(frozen=True)
class Overhang:
    part: str
    area_mm2: float
    max_angle_deg: float


@dataclass(frozen=True)
class AssertionResult:
    name: str
    passed: bool
    detail: str | None = None


@dataclass(frozen=True)
class Diagnostics:
    schema_version: str = SCHEMA_VERSION
    status: str = "ok"
    error: str | None = None
    parts: dict[str, PartDiagnostics] = field(default_factory=dict)
    interferences: tuple[Interference, ...] = ()
    overhangs: tuple[Overhang, ...] = ()
    assertions: tuple[AssertionResult, ...] = ()
    exports: tuple[str, ...] = ()


@dataclass(frozen=True)
class Triangle:
    centroid: Vector
    normal: Vector
    area: float


def _placed(p: PlacedPart) -> Part:
    return p.part.moved(p.location)


def _bbox(part: Part) -> BBox:
    bb = part.bounding_box()
    return BBox(
        min=(bb.min.X, bb.min.Y, bb.min.Z),
        max=(bb.max.X, bb.max.Y, bb.max.Z),
    )


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


def _overhang_angle_deg(normal: Vector) -> float:
    downward = min(1.0, max(0.0, -normal.Z))
    return degrees(asin(downward))


def _overhang(name: str, triangles: tuple[Triangle, ...]) -> Overhang | None:
    flagged = tuple(
        (t.area, ang)
        for t in triangles
        if (ang := _overhang_angle_deg(t.normal)) > OVERHANG_ANGLE_THRESHOLD_DEG
    )
    if not flagged:
        return None
    return Overhang(
        part=name,
        area_mm2=sum(a for a, _ in flagged),
        max_angle_deg=max(ang for _, ang in flagged),
    )


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


def _part_diagnostics(shape: Part) -> PartDiagnostics:
    return PartDiagnostics(
        bbox=_bbox(shape),
        volume_mm3=shape.volume,
        min_wall_mm=min_wall_mm(shape),
    )


def _interference(a: PlacedPart, b: PlacedPart) -> Interference | None:
    inter = _placed(a) & _placed(b)
    volume = inter.volume
    if volume <= INTERFERENCE_VOLUME_EPSILON_MM3:
        return None
    c = inter.center()
    return Interference(
        a=a.name,
        b=b.name,
        volume_mm3=volume,
        centroid=(c.X, c.Y, c.Z),
    )


def compute(assembly: Assembly) -> Diagnostics:
    shapes = {p.name: _placed(p) for p in assembly.parts}
    parts = {name: _part_diagnostics(shape) for name, shape in shapes.items()}
    interferences = tuple(
        r
        for a, b in combinations(assembly.parts, 2)
        if (r := _interference(a, b)) is not None
    )
    overhangs = tuple(
        o
        for name, shape in shapes.items()
        if (o := _overhang(name, _tessellate(shape))) is not None
    )
    return Diagnostics(
        parts=parts,
        interferences=interferences,
        overhangs=overhangs,
    )
