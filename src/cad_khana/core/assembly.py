from __future__ import annotations

from dataclasses import dataclass, replace

from build123d import Compound, Location, Part


@dataclass(frozen=True)
class PlacedPart:
    name: str
    part: Part
    location: Location


@dataclass(frozen=True)
class Assembly:
    parts: tuple[PlacedPart, ...] = ()

    def add(
        self,
        name: str,
        part: Part,
        location: Location | None = None,
    ) -> "Assembly":
        placed = PlacedPart(name, part, location or Location())
        return replace(self, parts=self.parts + (placed,))

    @property
    def compound(self) -> Compound:
        return Compound(children=[p.part.moved(p.location) for p in self.parts])
