from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from build123d import Part

from cad_khana.mechanism.diagnostics import (
    INTERFERENCE_VOLUME_EPSILON_MM3,
    AssertionResult,
)

if TYPE_CHECKING:
    from cad_khana.mechanism.assembly import Assembly, PlacedPart


def _intersection_volume(a: Part, b: Part) -> float:
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


@dataclass(frozen=True)
class NoInterference:
    a: str
    b: str
    name: str

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        volume = _intersection_volume(parts[self.a], parts[self.b])
        passed = volume <= INTERFERENCE_VOLUME_EPSILON_MM3
        detail = None if passed else f"interference volume {volume:.4f}mm^3"
        return AssertionResult(self.name, passed, detail)


@dataclass(frozen=True)
class Clearance:
    a: str
    b: str
    min_mm: float
    name: str

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        dist = parts[self.a].distance_to(parts[self.b])
        passed = dist >= self.min_mm
        detail = (
            None
            if passed
            else f"clearance {dist:.4f}mm below min {self.min_mm}mm"
        )
        return AssertionResult(self.name, passed, detail)


@dataclass(frozen=True)
class ExpectedInterference:
    """Assert that two parts DO interfere — a regression alarm for a
    known, accepted overlap. Fails if the overlap disappears, so the
    assertion can't go stale once the underlying design gap is fixed.
    Use sparingly: the default is `assert_no_interference`; reach for
    this only when a real-world design constraint leaves a documented
    overlap that hasn't been resolved yet.
    """
    a: str
    b: str
    name: str
    reason: str | None = None

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        volume = _intersection_volume(parts[self.a], parts[self.b])
        passed = volume > INTERFERENCE_VOLUME_EPSILON_MM3
        if passed:
            detail = None
        else:
            base = f"expected interference absent (volume {volume:.4f}mm^3)"
            detail = f"{base}; reason: {self.reason}" if self.reason else base
        return AssertionResult(self.name, passed, detail)


@dataclass(frozen=True)
class AnchorsCoincident:
    """Assert two named anchors resolve to the same position (within
    ``tol_mm``; orientation is ignored). ``a`` / ``b`` are dotted
    anchor paths resolved against the asserting assembly at evaluation
    time (``Assembly.anchor``), so the check reflects placements and
    joint angles as of ``check()``. Unlike the part assertions, this
    needs the assembly (not the placed-parts dict) to evaluate.
    """

    a: str
    b: str
    tol_mm: float
    name: str

    def evaluate_on(self, assembly: Assembly) -> AssertionResult:
        pa = assembly.anchor(self.a).position
        pb = assembly.anchor(self.b).position
        dist = (pa - pb).length
        passed = dist <= self.tol_mm
        detail = (
            None
            if passed
            else (
                f"anchors differ by {dist:.6f}mm (tol {self.tol_mm}mm): "
                f"{self.a} at ({pa.X:.6f}, {pa.Y:.6f}, {pa.Z:.6f}), "
                f"{self.b} at ({pb.X:.6f}, {pb.Y:.6f}, {pb.Z:.6f})"
            )
        )
        return AssertionResult(self.name, passed, detail)


Assertion = NoInterference | Clearance | ExpectedInterference | AnchorsCoincident


def _placed(p: PlacedPart) -> Part:
    return p.part.moved(p.location)


def _evaluate_part_assertion(
    assertion: NoInterference | Clearance | ExpectedInterference,
    parts: dict[str, Part],
) -> AssertionResult:
    """Skip (``passed=None``) instead of evaluating when a referenced
    part is absent. Absence is a legitimate run state, not an input
    error: detail geometry (fasteners, motors) is applied by an
    override, and a standalone sub-assembly run evaluates the same
    assertion list without those parts."""
    missing = sorted(n for n in (assertion.a, assertion.b) if n not in parts)
    if missing:
        names = ", ".join(missing)
        return AssertionResult(
            assertion.name, None, f"skipped: part(s) absent from this run: {names}"
        )
    return assertion.evaluate(parts)


def evaluate(assembly: Assembly) -> tuple[AssertionResult, ...]:
    parts = {p.name: _placed(p) for p in assembly.placed_parts}
    return tuple(
        a.evaluate_on(assembly)
        if isinstance(a, AnchorsCoincident)
        else _evaluate_part_assertion(a, parts)
        for a in assembly.assertions
    )
