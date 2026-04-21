from __future__ import annotations

from dataclasses import dataclass, replace

from build123d import Compound, Location, Part

from cad_khana.mechanism.assertions import (
    Assertion,
    Clearance,
    ExpectedInterference,
    NoInterference,
)


@dataclass(frozen=True)
class PlacedPart:
    name: str
    part: Part
    location: Location


@dataclass(frozen=True)
class Assembly:
    parts: tuple[PlacedPart, ...] = ()
    assertions: tuple[Assertion, ...] = ()

    def add(
        self,
        name: str,
        part: Part,
        location: Location | None = None,
    ) -> "Assembly":
        placed = PlacedPart(name, part, location or Location())
        return replace(self, parts=self.parts + (placed,))

    def assert_no_interference(
        self, a: str, b: str, name: str | None = None
    ) -> "Assembly":
        assertion = NoInterference(
            a=a, b=b, name=name or f"no_interference:{a}/{b}"
        )
        return replace(self, assertions=self.assertions + (assertion,))

    def assert_clearance(
        self,
        a: str,
        b: str,
        min_mm: float,
        name: str | None = None,
    ) -> "Assembly":
        assertion = Clearance(
            a=a,
            b=b,
            min_mm=min_mm,
            name=name or f"clearance:{a}/{b}>={min_mm}",
        )
        return replace(self, assertions=self.assertions + (assertion,))

    def assert_interference(
        self,
        a: str,
        b: str,
        reason: str | None = None,
        name: str | None = None,
    ) -> "Assembly":
        """Assert that `a` and `b` DO interfere — a regression alarm
        for a known, accepted overlap. Fails if the overlap disappears
        (volume ≤ epsilon), which forces this assertion to be removed
        when the underlying design gap gets fixed. Prefer
        `assert_no_interference` by default; reach for this only when
        an overlap is documented and expected.
        """
        assertion = ExpectedInterference(
            a=a,
            b=b,
            name=name or f"interference:{a}/{b}",
            reason=reason,
        )
        return replace(self, assertions=self.assertions + (assertion,))

    @property
    def compound(self) -> Compound:
        return Compound(children=[p.part.moved(p.location) for p in self.parts])
