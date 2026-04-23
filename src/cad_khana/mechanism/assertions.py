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


Assertion = NoInterference | Clearance | ExpectedInterference


def _placed(p: PlacedPart) -> Part:
    return p.part.moved(p.location)


def evaluate(assembly: Assembly) -> tuple[AssertionResult, ...]:
    parts = {p.name: _placed(p) for p in assembly.parts}
    return tuple(a.evaluate(parts) for a in assembly.assertions)
