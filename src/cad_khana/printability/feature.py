from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from build123d import Compound, Shape, Vector

from cad_khana.core.tessellation import TESSELLATION_TOLERANCE_MM
from cad_khana.printability.waiver import Waiver

# A mesh vertex lies on its surface; a point sampled along a curved crease
# sags off the true edge by up to the tessellation tolerance.
TRACE_TOLERANCE_MM = TESSELLATION_TOLERANCE_MM

Point = tuple[float, float, float]
Readings = Callable[[tuple["Failure", ...]], dict[str, float | None]]


@dataclass(frozen=True)
class Feature:
    """A piece of the part's construction — a cutter or a block, in the
    inspected body's frame — and the waivers for failures it produces.
    ``waive`` is keyed by assertion kind, like ``inspect``'s."""

    shape: Shape
    waive: dict[str, str | Waiver] = field(default_factory=dict)

    def waiver(self, kind: str) -> Waiver | None:
        return Waiver.create(self.waive[kind]) if kind in self.waive else None


@dataclass(frozen=True)
class Failure:
    """One failure of a check. ``ends`` are the point sets that say which
    surfaces it lies on: one for an overhang region (its facet corners),
    two for a wall reading (where it enters material and where it leaves)."""

    ends: tuple[tuple[Point, ...], ...]
    reading: float
    where: str


@dataclass(frozen=True)
class Coverage:
    """What the features waive of one check's failures. ``uncovered``
    pairs each failure no feature set waives with why; ``covering``
    names the features that waived at least one; ``stale`` those whose
    waiver of this kind no failure traces to."""

    uncovered: tuple[tuple[Failure, str], ...]
    covering: tuple[str, ...]
    stale: tuple[str, ...]


@dataclass(frozen=True)
class _Surface:
    faces: Compound
    lo: Vector
    hi: Vector

    @staticmethod
    def create(shape: Shape) -> _Surface:
        box = shape.bounding_box()
        pad = Vector(TRACE_TOLERANCE_MM, TRACE_TOLERANCE_MM, TRACE_TOLERANCE_MM)
        return _Surface(Compound(shape.faces()), box.min - pad, box.max + pad)

    def holds(self, points: tuple[Point, ...]) -> bool:
        """Every point within tolerance of this surface — on it, not merely
        inside the solid: a later cutter leaves no face inside a block, but
        a bore crown inside a block's volume is the cutter's surface."""
        return all(
            self.lo.X <= x <= self.hi.X
            and self.lo.Y <= y <= self.hi.Y
            and self.lo.Z <= z <= self.hi.Z
            for x, y, z in points
        ) and all(
            self.faces.distance_to(Vector(*p)) <= TRACE_TOLERANCE_MM for p in points
        )


def _traced(
    failure: Failure, surfaces: dict[str, _Surface]
) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(name for name, s in surfaces.items() if s.holds(end))
        for end in failure.ends
    )


def _refusal(
    ends: tuple[tuple[str, ...], ...], kind: str, features: dict[str, Feature]
) -> str | None:
    untraced = next((i for i, names in enumerate(ends) if not names), None)
    refuses = next(
        (n for names in ends for n in names if features[n].waiver(kind) is None),
        None,
    )
    return (
        "traces to no feature"
        if untraced is not None and len(ends) == 1
        else "one side traces to no feature"
        if untraced is not None
        else f"traces to {refuses}, which does not waive {kind}"
        if refuses is not None
        else None
    )


def cover(
    kind: str,
    failures: tuple[Failure, ...],
    features: dict[str, Feature],
    readings: Readings,
) -> Coverage:
    """A failure is waived only when every surface it lies on traces to a
    feature and every feature it traces to waives ``kind`` — within that
    waiver's bounds, which read the failures traced to that feature alone."""
    surfaces = {name: _Surface.create(f.shape) for name, f in features.items()}
    traced = tuple(_traced(f, surfaces) for f in failures)
    names = tuple(frozenset(n for end in ends for n in end) for ends in traced)
    refusals = tuple(_refusal(ends, kind, features) for ends in traced)
    waiving = tuple(n for n, f in features.items() if f.waiver(kind) is not None)
    breaches = {
        n: breach
        for n in waiving
        if (
            breach := "; ".join(
                features[n].waiver(kind).breaches(
                    readings(
                        tuple(
                            f
                            for f, fn, r in zip(failures, names, refusals)
                            if r is None and n in fn
                        )
                    )
                )
            )
        )
    }
    reasons = tuple(
        r
        if r is not None
        else next(
            (f"{n}'s waiver not applied: {breaches[n]}" for n in sorted(fn) if n in breaches),
            None,
        )
        for fn, r in zip(names, refusals)
    )
    traced_to = frozenset(n for fn in names for n in fn)
    return Coverage(
        uncovered=tuple(
            (f, r) for f, r in zip(failures, reasons) if r is not None
        ),
        covering=tuple(
            n
            for n in waiving
            if any(r is None and n in fn for fn, r in zip(names, reasons))
        ),
        stale=tuple(n for n in waiving if n not in traced_to),
    )
