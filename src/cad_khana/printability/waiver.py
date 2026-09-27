from __future__ import annotations

from dataclasses import dataclass, fields

from cad_khana.mechanism.diagnostics import BOUND_EPSILON


@dataclass(frozen=True)
class _Bound:
    """What a waiver bound limits: the assertion kind it belongs to, the
    reading it is compared against (by its JSON name), and which side
    of that reading the waiver was written for."""

    kind: str
    reading: str
    upper: bool
    precision: int


_BOUNDS: dict[str, _Bound] = {
    "min_wall_mm": _Bound("wall_min", "min_wall_mm", upper=False, precision=4),
    "max_area_mm2": _Bound("overhang_max", "area_mm2", upper=True, precision=2),
    "max_regions": _Bound("overhang_max", "regions", upper=True, precision=0),
}


@dataclass(frozen=True, kw_only=True)
class Waiver:
    """A waiver that states the reading it was written against. It
    applies only while the current reading stays inside every bound
    given; outside one, the failure counts. A reading that improved
    past the bound still applies — ``stale_waiver`` covers the check
    that passes outright. A bare reason string is a ``Waiver`` with no
    bounds."""

    reason: str
    min_wall_mm: float | None = None
    max_area_mm2: float | None = None
    max_regions: int | None = None

    @staticmethod
    def create(waiver: str | Waiver) -> Waiver:
        return waiver if isinstance(waiver, Waiver) else Waiver(reason=waiver)

    @property
    def bounds(self) -> dict[str, float]:
        return {
            f.name: value
            for f in fields(self)
            if f.name in _BOUNDS and (value := getattr(self, f.name)) is not None
        }

    def foreign_bounds(self, kind: str) -> tuple[str, ...]:
        return tuple(name for name in self.bounds if _BOUNDS[name].kind != kind)

    def breaches(self, readings: dict[str, float | None]) -> tuple[str, ...]:
        return tuple(
            breach
            for name, limit in self.bounds.items()
            if (breach := _breach(name, limit, readings[_BOUNDS[name].reading]))
        )

    @property
    def within(self) -> str:
        return (
            f" — within the waiver's "
            f"{', '.join(f'{n} {v}' for n, v in self.bounds.items())}"
            if self.bounds
            else ""
        )


def _breach(name: str, limit: float, reading: float | None) -> str | None:
    bound = _BOUNDS[name]
    if reading is None:
        return f"{bound.reading} not measured, so its {name} {limit} cannot hold"
    held = (
        reading <= limit + BOUND_EPSILON
        if bound.upper
        else reading >= limit - BOUND_EPSILON
    )
    word = "exceeds" if bound.upper else "below"
    return (
        None
        if held
        else f"{bound.reading} {reading:.{bound.precision}f} {word} its {name} {limit}"
    )
