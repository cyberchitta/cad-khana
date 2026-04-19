from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import TYPE_CHECKING

from build123d import Part

if TYPE_CHECKING:
    from cad_khana.core.assembly import Assembly, PlacedPart

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


def _placed(p: PlacedPart) -> Part:
    return p.part.moved(p.location)


def _bbox(part: Part) -> BBox:
    bb = part.bounding_box()
    return BBox(
        min=(bb.min.X, bb.min.Y, bb.min.Z),
        max=(bb.max.X, bb.max.Y, bb.max.Z),
    )


def _part_diagnostics(p: PlacedPart) -> PartDiagnostics:
    shape = _placed(p)
    return PartDiagnostics(bbox=_bbox(shape), volume_mm3=shape.volume)


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
    parts = {p.name: _part_diagnostics(p) for p in assembly.parts}
    interferences = tuple(
        r
        for a, b in combinations(assembly.parts, 2)
        if (r := _interference(a, b)) is not None
    )
    return Diagnostics(parts=parts, interferences=interferences)
