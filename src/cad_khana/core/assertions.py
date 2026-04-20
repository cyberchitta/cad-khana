from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from build123d import Part

from cad_khana.core.diagnostics import (
    INTERFERENCE_VOLUME_EPSILON_MM3,
    AssertionResult,
    min_wall_mm,
)

if TYPE_CHECKING:
    from cad_khana.core.assembly import Assembly, PlacedPart


@dataclass(frozen=True)
class NoInterference:
    a: str
    b: str
    name: str

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        intersection = parts[self.a] & parts[self.b]
        volume = intersection.volume if intersection is not None else 0.0
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
class MinWall:
    part: str
    min_mm: float
    name: str

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        wall = min_wall_mm(parts[self.part])
        if wall is None:
            return AssertionResult(
                self.name, False, "min wall could not be computed"
            )
        passed = wall >= self.min_mm
        detail = (
            None
            if passed
            else f"min wall {wall:.4f}mm below min {self.min_mm}mm"
        )
        return AssertionResult(self.name, passed, detail)


Assertion = NoInterference | Clearance | MinWall


def _placed(p: PlacedPart) -> Part:
    return p.part.moved(p.location)


def evaluate(assembly: Assembly) -> tuple[AssertionResult, ...]:
    parts = {p.name: _placed(p) for p in assembly.parts}
    return tuple(a.evaluate(parts) for a in assembly.assertions)
