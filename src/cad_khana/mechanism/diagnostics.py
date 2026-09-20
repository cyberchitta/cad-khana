from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import TYPE_CHECKING

from build123d import Part

if TYPE_CHECKING:
    from cad_khana.mechanism.assembly import Assembly, PlacedPart

SCHEMA_VERSION = "0.13"
INTERFERENCE_VOLUME_EPSILON_MM3 = 0.001

# Absolute tolerance on assertion bound comparisons, in the bound's own
# units (mm, deg, or a scalar claim's units). Consumers routinely derive
# geometry from the same constant they bound against, so the measured
# value lands exactly at the bound ± solver noise (1e-14 boolean noise,
# ~1e-7 bbox slop observed); exact comparison flips on that noise.
BOUND_EPSILON = 1e-6

Warning = dict[str, str | int]

# Why an assertion can come back ``passed=None``. Free-text ``detail``
# can't tell "expected here" from "typo"; the class can be counted.
# ``out_of_phase``: a phased claim that was in phase at no pose looked at.
SKIP_CLASSES = ("absent_part", "absent_joint", "out_of_phase")


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
    solid_count: int


@dataclass(frozen=True)
class Interference:
    a: str
    b: str
    volume_mm3: float
    centroid: tuple[float, float, float]


@dataclass(frozen=True)
class PoseCounts:
    """How much one assertion's verdict covers. ``evaluated`` — the
    poses it was held at: the as-built pose plus every sample of every
    declared motion, so ``1`` is a claim saying it was checked once.
    ``distinct`` — the geometric evaluations that took; poses that
    place the claim's parts identically share one, so ``1`` under a
    motion means the motion never moves this claim. ``in_phase`` — the
    poses inside the claim's ``during`` (all of them when it has none).
    ``failed`` — the poses it failed at. All zero when the assertion
    was skipped for an absent part or joint."""

    evaluated: int
    distinct: int
    in_phase: int
    failed: int


@dataclass(frozen=True)
class WorstAt:
    """The sampled pose an assertion's ``value`` and ``detail`` come
    from, when it is not the as-built pose. ``joints_deg`` holds the
    motion's scheduled joint values there."""

    motion: str
    t: float
    joints_deg: dict[str, float]


@dataclass(frozen=True)
class JointRange:
    """One driven joint across a motion's samples. ``max_step`` is the
    widest gap between adjacent samples — the resolution the motion was
    looked at, exactly, and nothing about what lies between them."""

    min: float
    max: float
    max_step: float


@dataclass(frozen=True)
class MotionSummary:
    """``moved`` — how many of this motion's ``movable`` claims it
    actually moved, i.e. reached more than one ``poses.distinct``
    evaluation under. ``movable`` excludes the kinds that are
    pose-invariant by construction (``assert_scalar``,
    ``assert_solid_count``), which no motion can move, and the claims
    skipped for an absent part or joint, which this run never held.
    ``moved: 0`` is a motion that tested nothing and draws a
    ``motion_moved_nothing`` warning; with ``movable: 0`` it says
    something different again — nothing in this tree could have been
    moved by any motion."""

    name: str
    samples: int
    joints_deg: dict[str, JointRange]
    moved: int
    movable: int


@dataclass(frozen=True)
class AssertionResult:
    """``passed`` is tri-state: ``True``/``False`` for an evaluated
    assertion, ``None`` when it was skipped because a referenced part
    or joint is absent from the run (``detail`` names what is
    missing). ``skipped`` classes that reason — one of ``SKIP_CLASSES``
    — and is ``None`` for every evaluated assertion.
    Skipped assertions never fail a run. ``value`` carries the
    measured/claimed scalar for value-carrying assertions
    (``assert_distance``, ``assert_scalar``, ``assert_tangent_contact``
    gap in mm, ``assert_allowed_contact`` overlap in mm³,
    ``assert_solid_count`` count) even on pass
    — so runs are diffable — and stays ``None`` for the boolean-only
    kinds.
    ``waived`` is the waiver rationale when a failure was waived
    (printability ``inspect(..., waive=...)``); ``passed`` stays
    honestly ``False`` — a waived failure just doesn't fail the run.

    Held over motions (``hold``), one result covers many poses:
    ``passed`` is false if any pose failed, ``value`` and ``detail``
    are the worst pose's, ``worst_at`` names it (``None`` for the
    as-built pose) and ``poses`` counts what was looked at. Both stay
    ``None`` on a single-pose ``evaluate`` and on printability
    assertions."""

    name: str
    passed: bool | None
    detail: str | None = None
    value: float | None = None
    waived: str | None = None
    skipped: str | None = None
    poses: PoseCounts | None = None
    worst_at: WorstAt | None = None


def skipped_counts(results: tuple[AssertionResult, ...]) -> dict[str, int]:
    """Skipped assertions per class — every class listed, zeros
    included, so the shape is stable under ``khana diff``."""
    return {
        kind: sum(r.skipped == kind for r in results) for kind in SKIP_CLASSES
    }


@dataclass(frozen=True)
class Diagnostics:
    schema_version: str = SCHEMA_VERSION
    status: str = "ok"
    error: str | None = None
    hint: str | None = None
    skipped_counts: dict[str, int] = field(
        default_factory=lambda: skipped_counts(())
    )
    motions: tuple[MotionSummary, ...] = ()
    parts: dict[str, PartDiagnostics] = field(default_factory=dict)
    interferences: tuple[Interference, ...] = ()
    assertions: tuple[AssertionResult, ...] = ()
    warnings: tuple[Warning, ...] = ()


def intersection_volume(a: Part, b: Part) -> float:
    """Volume of the boolean intersection `a & b`, tolerant to the
    several shapes build123d can return:
      - `None`                  — no overlap (new API, some versions).
      - A single `Shape`/`Part` — single-component intersection.
      - A `ShapeList` / iterable — multi-component intersection, or an
        empty list when one of the inputs is itself a multi-body
        compound. Sum the volumes.
    """
    intersection = a & b
    if intersection is None:
        return 0.0
    if hasattr(intersection, "volume"):
        return intersection.volume
    # ShapeList or other iterable container of shapes.
    return sum(s.volume for s in intersection)


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
        solid_count=len(shape.solids()),
    )


def multi_solid_warnings(
    parts: dict[str, PartDiagnostics], claimed: frozenset[str]
) -> tuple[Warning, ...]:
    """One warning per part that is more than one solid and that no
    solid-count claim speaks for. Volume, bbox, clearance and
    interference are all blind to whether a part is in one piece, so a
    severed part is otherwise a green run; a part that is several
    solids on purpose says so with ``assert_solid_count`` and is left
    alone."""
    return tuple(
        {"kind": "multi_solid", "part": name, "solid_count": p.solid_count}
        for name, p in parts.items()
        if p.solid_count > 1 and name not in claimed
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
