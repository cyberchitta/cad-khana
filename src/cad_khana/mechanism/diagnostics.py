from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import TYPE_CHECKING

from build123d import Part

if TYPE_CHECKING:
    from cad_khana.mechanism.assembly import Assembly, PlacedPart

SCHEMA_VERSION = "0.7"
INTERFERENCE_VOLUME_EPSILON_MM3 = 0.001

# Absolute tolerance on assertion bound comparisons, in the bound's own
# units (mm, deg, or a scalar claim's units). Consumers routinely derive
# geometry from the same constant they bound against, so the measured
# value lands exactly at the bound ± solver noise (1e-14 boolean noise,
# ~1e-7 bbox slop observed); exact comparison flips on that noise.
BOUND_EPSILON = 1e-6


@dataclass(frozen=True)
class BBox:
    min: tuple[float, float, float]
    max: tuple[float, float, float]


@dataclass(frozen=True)
class PartDiagnostics:
    bbox: BBox
    volume_mm3: float
    surface_area_mm2: float
    center_of_mass_mm: tuple[float, float, float]
    is_valid: bool
    face_count: int
    edge_count: int
    vertex_count: int


@dataclass(frozen=True)
class Interference:
    a: str
    b: str
    volume_mm3: float
    centroid: tuple[float, float, float]


@dataclass(frozen=True)
class AssertionResult:
    """``passed`` is tri-state: ``True``/``False`` for an evaluated
    assertion, ``None`` when it was skipped because a referenced part
    is absent from the run (``detail`` names the missing parts).
    Skipped assertions never fail a build. ``value`` carries the
    measured/claimed scalar for value-carrying assertions
    (``assert_distance``, ``assert_scalar``, ``assert_tangent_contact``
    gap in mm, ``assert_allowed_contact`` overlap in mm³) even on pass
    — so runs are diffable — and stays ``None`` for the boolean-only
    kinds.
    ``waived`` is the waiver rationale when a failure was waived
    (printability ``inspect(..., waive=...)``); ``passed`` stays
    honestly ``False`` — a waived failure just doesn't fail the run."""

    name: str
    passed: bool | None
    detail: str | None = None
    value: float | None = None
    waived: str | None = None


@dataclass(frozen=True)
class Diagnostics:
    schema_version: str = SCHEMA_VERSION
    status: str = "ok"
    error: str | None = None
    hint: str | None = None
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
    com = shape.center()
    return PartDiagnostics(
        bbox=_bbox(shape),
        volume_mm3=shape.volume,
        surface_area_mm2=shape.area,
        center_of_mass_mm=(com.X, com.Y, com.Z),
        is_valid=shape.is_valid,
        face_count=len(shape.faces()),
        edge_count=len(shape.edges()),
        vertex_count=len(shape.vertices()),
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
    placed = assembly.placed_parts
    shapes = {p.name: _placed(p) for p in placed}
    parts = {name: _part_diagnostics(shape) for name, shape in shapes.items()}
    interferences = tuple(
        r
        for a, b in combinations(placed, 2)
        if (r := _interference(a, b)) is not None
    )
    return Diagnostics(parts=parts, interferences=interferences)
