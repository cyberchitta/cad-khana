from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import TYPE_CHECKING

from build123d import Part

if TYPE_CHECKING:
    from cad_khana.mechanism.assembly import Assembly, PlacedPart

SCHEMA_VERSION = "0.1"
INTERFERENCE_VOLUME_EPSILON_MM3 = 0.001


@dataclass(frozen=True)
class BBox:
    min: tuple[float, float, float]
    max: tuple[float, float, float]


@dataclass(frozen=True)
class PartDiagnostics:
    bbox: BBox
    volume_mm3: float


@dataclass(frozen=True)
class Interference:
    a: str
    b: str
    volume_mm3: float
    centroid: tuple[float, float, float]


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
    assertions: tuple[AssertionResult, ...] = ()
    exports: tuple[str, ...] = ()


def _placed(p: PlacedPart) -> Part:
    return p.part.moved(p.location)


def _bbox(part: Part) -> BBox:
    bb = part.bounding_box()
    return BBox(
        min=(bb.min.X, bb.min.Y, bb.min.Z),
        max=(bb.max.X, bb.max.Y, bb.max.Z),
    )


def _part_diagnostics(shape: Part) -> PartDiagnostics:
    return PartDiagnostics(
        bbox=_bbox(shape),
        volume_mm3=shape.volume,
    )


def _interference(a: PlacedPart, b: PlacedPart) -> Interference | None:
    inter = _placed(a) & _placed(b)
    if inter is None:
        return None
    # `a & b` can return a `ShapeList` when one of the inputs is a
    # multi-body compound. Sum sub-volumes; pick the largest
    # sub-shape's centroid as a representative location.
    if hasattr(inter, "volume"):
        volume = inter.volume
        centroid_shape = inter
    else:
        shapes = list(inter)
        if not shapes:
            return None
        volume = sum(s.volume for s in shapes)
        centroid_shape = max(shapes, key=lambda s: s.volume)
    if volume <= INTERFERENCE_VOLUME_EPSILON_MM3:
        return None
    c = centroid_shape.center()
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
    return Diagnostics(parts=parts, interferences=interferences)
