from __future__ import annotations

from dataclasses import dataclass, replace

from build123d import Color, Compound, Location, Part

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
    color: Color | None = None
    material: str | None = None


@dataclass(frozen=True)
class DetailOverride:
    """One entry in an ``Assembly.with_detailed_geometry`` mapping.

    A bare ``Part`` may be passed instead of a ``DetailOverride`` —
    treated as ``DetailOverride(part=p)`` (swap-only; no addition,
    since additions need a ``location``).
    """

    part: Part
    location: Location | None = None
    material: str | None = None
    color: Color | None = None


@dataclass(frozen=True)
class Assembly:
    parts: tuple[PlacedPart, ...] = ()
    assertions: tuple[Assertion, ...] = ()

    def add(
        self,
        name: str,
        part: Part,
        location: Location | None = None,
        color: Color | None = None,
        material: str | None = None,
    ) -> "Assembly":
        placed = PlacedPart(name, part, location or Location(), color, material)
        return replace(self, parts=self.parts + (placed,))

    def with_materials(self, mapping: dict[str, str]) -> "Assembly":
        """Return a copy with each named part's material replaced by the
        value in ``mapping``. Parts not in the mapping are unchanged.

        Symmetric to ``chitra_cad.Scene.with_materials``: use this layer
        for cross-consumer experiments (render + FEA both read from the
        ``Assembly``); use the ``Scene`` layer for render-only sweeps.
        """
        updated = tuple(
            replace(p, material=mapping.get(p.name, p.material)) for p in self.parts
        )
        return replace(self, parts=updated)

    def with_detailed_geometry(
        self, mapping: dict[str, "DetailOverride | Part"]
    ) -> "Assembly":
        """Return a copy with detailed geometry swapped or appended.

        Used for high-fidelity passes (render, FEA, kinematics) that
        need real profiles or fasteners over the cheap primitives
        (``Box``, ``Cylinder``) the geometric-iteration loop runs on.
        Parallel to ``with_materials``: same recursion at every level,
        single concern per layer.

        Names that match an existing ``PlacedPart`` swap the part
        shape. ``location`` / ``material`` / ``color`` on the existing
        placement are preserved unless the override explicitly supplies
        them. Names with no match append a new ``PlacedPart`` — for
        additions, ``location`` is required (material/color optional).

        A bare ``Part`` value is shorthand for
        ``DetailOverride(part=p)`` — convenient for the common
        swap-only case where placement carries through.
        """
        overrides: dict[str, DetailOverride] = {
            name: (v if isinstance(v, DetailOverride) else DetailOverride(part=v))
            for name, v in mapping.items()
        }
        existing = {p.name for p in self.parts}
        swapped = tuple(
            replace(
                p,
                part=overrides[p.name].part,
                location=overrides[p.name].location or p.location,
                material=overrides[p.name].material or p.material,
                color=overrides[p.name].color or p.color,
            )
            if p.name in overrides
            else p
            for p in self.parts
        )
        additions: list[PlacedPart] = []
        for name, ov in overrides.items():
            if name in existing:
                continue
            if ov.location is None:
                raise ValueError(
                    f"with_detailed_geometry: addition {name!r} requires "
                    "an explicit location"
                )
            additions.append(
                PlacedPart(
                    name=name,
                    part=ov.part,
                    location=ov.location,
                    color=ov.color,
                    material=ov.material,
                )
            )
        return replace(self, parts=swapped + tuple(additions))

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
