from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from build123d import Part

from cad_khana import _failures
from cad_khana._paths import resolve_out
from cad_khana.mechanism.diagnostics import (
    BOUND_EPSILON,
    SCHEMA_VERSION,
    AssertionResult,
    BBox,
    _bbox,
)
from cad_khana.printability.feature import Coverage, Failure, Feature, Refusal, cover
from cad_khana.printability.methods import FDM
from cad_khana.printability.overhangs import (
    Overhang,
    detect_overhang,
    regions_with_points,
)
from cad_khana.printability.waiver import Waiver
from cad_khana.printability.wall import (
    WEDGE_ALIGNMENT,
    WallSample,
    thinnest,
    wall_samples,
)

TRACEABLE_KINDS = ("wall_min", "overhang_max")


@dataclass(frozen=True)
class WarningEntry:
    """A non-fatal diagnostic surfaced in ``warnings``: a failure that
    was waived (``kind="waived_failure"``) or a waiver whose assertion
    now passes and should be removed (``kind="stale_waiver"``)."""

    kind: str
    assertion: str
    reason: str
    detail: str | None = None

    @property
    def line(self) -> str:
        return f"{self.kind}: {self.assertion} — {self.reason}"


@dataclass(frozen=True, kw_only=True)
class MultiSolid:
    """The part is more than one solid — a severed lip, a detached
    ring — which no wall, overhang or volume reading can see. Never
    fails a run: a part may be several solids on purpose."""

    kind: str = "multi_solid"
    part: str
    solid_count: int

    @property
    def line(self) -> str:
        return f"{self.kind}: {self.solid_count} solids"


@dataclass(frozen=True)
class PrintabilityDiagnostics:
    schema_version: str = SCHEMA_VERSION
    kind: str = "printability"
    status: str = "ok"
    name: str = "part"
    method: str = "FDM"
    method_params: dict[str, object] = field(default_factory=dict)
    bbox: BBox | None = None
    volume_mm3: float = 0.0
    surface_area_mm2: float = 0.0
    center_of_mass_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    is_valid: bool = True
    solid_count: int = 1
    min_wall_mm: float | None = None
    min_wall_at: tuple[float, float, float] | None = None
    min_wall_alignment: float | None = None
    overhang: Overhang | None = None
    assertions: tuple[AssertionResult, ...] = field(default_factory=tuple)
    warnings: tuple[WarningEntry | MultiSolid, ...] = field(default_factory=tuple)


def _point(at: tuple[float, float, float]) -> str:
    return ", ".join(f"{c:.2f}" for c in at)


def _wall_assertion(wall: WallSample | None, method: FDM) -> AssertionResult:
    name = f"wall_min:{method.wall_min_mm}"
    if wall is None:
        return AssertionResult(name, False, "min wall could not be computed")
    passed = wall.thickness_mm >= method.wall_min_mm - BOUND_EPSILON
    at = _point(wall.at)
    wedge = (
        ""
        if wall.alignment >= WEDGE_ALIGNMENT
        else " — the faces splay apart here, so this is the tip of a wedge "
        "feature rather than a wall between parallel faces"
    )
    detail = (
        None
        if passed
        else (
            f"min wall {wall.thickness_mm:.4f}mm below min "
            f"{method.wall_min_mm}mm at ({at}), "
            f"alignment {wall.alignment:.2f}{wedge}"
        )
    )
    return AssertionResult(name, passed, detail)


def _overhang_assertion(overhang: Overhang | None, method: FDM) -> AssertionResult:
    name = f"overhang_max:{method.overhang_max_deg}"
    if overhang is None:
        return AssertionResult(name, True, None)
    passed = overhang.max_angle_deg <= method.overhang_max_deg + BOUND_EPSILON
    detail = None if passed else _overhang_detail(overhang, method)
    return AssertionResult(name, passed, detail)


def _overhang_detail(overhang: Overhang, method: FDM) -> str:
    """A failure past the bound always has a region: the steepest facet
    is past the threshold, so it counts."""
    largest, count = overhang.regions[0], len(overhang.regions)
    at = _point(largest.centroid_mm)
    return (
        f"overhang {overhang.max_angle_deg:.4f}° exceeds max "
        f"{method.overhang_max_deg}° across {count} "
        f"region{'' if count == 1 else 's'}, largest "
        f"{largest.area_mm2:.2f}mm² at ({at})"
    )


def _solid_count_assertion(count: int, eq: int) -> AssertionResult:
    passed = count == eq
    detail = None if passed else f"{count} solids, expected {eq}"
    return AssertionResult(f"solid_count:{eq}", passed, detail, value=float(count))


def _assertion_kind(name: str) -> str:
    return name.split(":", 1)[0]


def _check_waivers(
    kinds: set[str], waive: dict[str, Waiver], features: dict[str, Feature]
) -> None:
    """Unknown kinds, bounds on another kind, and a feature waiving a check
    no failure of which has a place are caller errors."""
    keyed = {
        **{kind: w for kind, w in waive.items()},
        **{
            f"{kind} (feature {name})": w
            for name, f in features.items()
            for kind in f.waive
            if (w := f.waiver(kind))
        },
    }
    unknown = sorted(k for k in keyed if k.split(" ")[0] not in kinds)
    if unknown:
        raise ValueError(
            f"waive keys match no assertion kind: {', '.join(unknown)}; "
            f"known kinds: {', '.join(sorted(kinds))}"
        )
    placeless = sorted(
        f"{kind} (feature {name})"
        for name, f in features.items()
        for kind in f.waive
        if kind not in TRACEABLE_KINDS
    )
    if placeless:
        raise ValueError(
            f"a feature can waive only {', '.join(TRACEABLE_KINDS)} — "
            f"{', '.join(placeless)} has no place to trace"
        )
    foreign = [
        f"{key}: {', '.join(bounds)}"
        for key, w in keyed.items()
        if (bounds := w.foreign_bounds(key.split(" ")[0]))
    ]
    if foreign:
        raise ValueError(f"waiver bounds belong to another kind — {'; '.join(foreign)}")


def _apply_waivers(
    assertions: tuple[AssertionResult, ...],
    waive: dict[str, Waiver],
    readings: dict[str, float | None],
    features: dict[str, Feature],
    coverages: dict[str, Coverage],
) -> tuple[AssertionResult, ...]:
    """Attach waiver rationales to failed assertions, matched by
    assertion kind (``wall_min``, ``overhang_max``) — not the full
    ``kind:threshold`` name, so waivers survive threshold changes and
    thresholds stay honest. A waiver whose bounds the reading has left
    does not apply: the failure counts, and its detail says which bound
    broke. A kind some feature waives goes by what the features cover
    first; the body-wide waiver, if any, takes what is left."""
    return tuple(
        a
        if a.passed is not False
        else _featured(a, kind, coverages[kind], features, waive.get(kind), readings)
        if (kind := _assertion_kind(a.name)) in coverages
        else _waived(a, waive[kind], readings)
        if kind in waive
        else a
        for a in assertions
    )


def _limits(name: str, waiver: Waiver) -> str:
    bounds = ", ".join(f"{n} {v}" for n, v in waiver.bounds.items())
    return f"{name} ({bounds})" if bounds else name


def _featured(
    a: AssertionResult,
    kind: str,
    coverage: Coverage,
    features: dict[str, Feature],
    body: Waiver | None,
    readings: dict[str, float | None],
) -> AssertionResult:
    waivers = {n: features[n].waiver(kind) for n in coverage.covering}
    by = ", ".join(_limits(n, w) for n, w in waivers.items())
    reasons = "; ".join(f"{n}: {w.reason}" for n, w in waivers.items())
    if not coverage.uncovered:
        return replace(a, waived=reasons, detail=f"{a.detail} — waived by feature {by}")
    count = len(coverage.uncovered)
    left = (
        f"{count} {_noun[kind]}{'' if count == 1 else 's'} no feature waives, "
        f"worst {_refused(_worst[kind](coverage.uncovered))}"
    )
    rest = replace(a, detail=f"{a.detail}; {left}")
    if body is None:
        return replace(rest, detail=f"{a.detail}; not waived: {left}")
    held = _waived(rest, body, readings)
    return (
        replace(held, waived=f"{reasons}; {held.waived}")
        if held.waived is not None and reasons
        else held
    )


def _refused(r: Refusal) -> str:
    """Each end's point and the features it traces to, then every reason:
    ``wall 0.8000mm from (…) [pocket_b] to (…) [none]: …``."""
    ends = tuple(
        f"({_point(p)}) [{', '.join(names) or 'none'}]"
        for p, names in zip(r.failure.at, r.traced, strict=True)
    )
    place = f"from {ends[0]} to {ends[1]}" if len(ends) == 2 else f"at {ends[0]}"
    return f"{r.failure.label} {place}: {'; '.join(r.reasons)}"


_noun = {"overhang_max": "region", "wall_min": "reading"}
_worst = {
    "overhang_max": lambda u: max(u, key=lambda r: r.failure.reading),
    "wall_min": lambda u: min(u, key=lambda r: r.failure.reading),
}


def _overhang_failures(part: Part, method: FDM) -> tuple[Failure, ...]:
    return tuple(
        Failure(
            ends=(tuple((p.X, p.Y, p.Z) for p in points),),
            at=(region.centroid_mm,),
            reading=region.area_mm2,
            label=f"region {region.area_mm2:.2f}mm²",
        )
        for region, points in regions_with_points(
            part, up_axis=method.up_axis, angle_threshold_deg=method.overhang_max_deg
        )
    )


def _wall_failures(samples: tuple[WallSample, ...], method: FDM) -> tuple[Failure, ...]:
    return tuple(
        Failure(
            ends=((s.at,), (s.exit_at,)),
            at=(s.at, s.exit_at),
            reading=s.thickness_mm,
            label=f"wall {s.thickness_mm:.4f}mm",
        )
        for s in samples
        if s.thickness_mm < method.wall_min_mm - BOUND_EPSILON
    )


def _overhang_readings(failures: tuple[Failure, ...]) -> dict[str, float | None]:
    return {
        "area_mm2": sum((f.reading for f in failures), 0.0),
        "regions": len(failures),
        "min_wall_mm": None,
    }


def _wall_readings(failures: tuple[Failure, ...]) -> dict[str, float | None]:
    return {
        "min_wall_mm": min((f.reading for f in failures), default=None),
        "area_mm2": 0.0,
        "regions": 0,
    }


def _coverages(
    assertions: tuple[AssertionResult, ...],
    features: dict[str, Feature],
    part: Part,
    samples: tuple[WallSample, ...],
    method: FDM,
) -> dict[str, Coverage]:
    """Trace the failures of each failed check some feature waives. A kind
    whose check passed has nothing to trace: every waiver of it is stale."""
    failed = {_assertion_kind(a.name) for a in assertions if a.passed is False}
    waived = {k for f in features.values() for k in f.waive}
    traced = {
        "overhang_max": lambda: cover(
            "overhang_max",
            _overhang_failures(part, method),
            features,
            _overhang_readings,
        ),
        "wall_min": lambda: cover(
            "wall_min", _wall_failures(samples, method), features, _wall_readings
        ),
    }
    return {kind: traced[kind]() for kind in TRACEABLE_KINDS if kind in failed & waived}


def _waived(
    a: AssertionResult, waiver: Waiver, readings: dict[str, float | None]
) -> AssertionResult:
    breaches = waiver.breaches(readings)
    return (
        replace(a, detail=f"{a.detail}; waiver not applied: {'; '.join(breaches)}")
        if breaches
        else replace(a, waived=waiver.reason, detail=f"{a.detail}{waiver.within}")
    )


def _warnings(
    assertions: tuple[AssertionResult, ...],
    waive: dict[str, Waiver],
    features: dict[str, Feature],
    coverages: dict[str, Coverage],
) -> tuple[WarningEntry, ...]:
    waived = tuple(
        WarningEntry("waived_failure", a.name, a.waived, a.detail)
        for a in assertions
        if a.waived is not None
    )
    stale = tuple(
        WarningEntry(
            "stale_waiver",
            a.name,
            waive[_assertion_kind(a.name)].reason,
            "assertion passed; remove the waiver",
        )
        for a in assertions
        if a.passed is True and _assertion_kind(a.name) in waive
    )
    stale_features = tuple(
        WarningEntry(
            "stale_waiver",
            a.name,
            waiver.reason,
            f"assertion passed; remove feature {name}'s waiver"
            if a.passed is True
            else f"no failure traces to feature {name}; remove its waiver",
        )
        for a in assertions
        for name, f in features.items()
        if (waiver := f.waiver(kind := _assertion_kind(a.name))) is not None
        and (a.passed is True or (kind in coverages and name in coverages[kind].stale))
    )
    return waived + stale + stale_features


def _readings(
    wall: WallSample | None, overhang: Overhang | None
) -> dict[str, float | None]:
    return {
        "min_wall_mm": wall.thickness_mm if wall else None,
        "area_mm2": overhang.area_mm2 if overhang else 0.0,
        "regions": len(overhang.regions) if overhang else 0,
    }


def inspect(
    part: Part,
    *,
    method: FDM,
    out: str | Path = "outputs",
    name: str = "part",
    waive: dict[str, str | Waiver] | None = None,
    solid_count: int | None = None,
    features: dict[str, Feature] | None = None,
) -> PrintabilityDiagnostics:
    """``solid_count`` declares how many solids the part is meant to be.
    Undeclared, a part above one solid draws a ``multi_solid`` warning;
    declared, the count is a claim like the others — it lands in
    ``assertions`` with the count in ``value``, a mismatch fails the run
    (or is waived under kind ``solid_count``), and the warning has
    nothing left to say.

    ``features`` names the cutters and blocks the part was built from, each
    with its own waivers. A failure is waived only when every surface it
    lies on traces to a feature and every feature it traces to waives it;
    ``waive`` stays the body-wide fallback for whatever they leave."""
    out_path = resolve_out(out)
    out_path.mkdir(parents=True, exist_ok=True)
    samples = wall_samples(part)
    wall = thinnest(samples)
    overhang = detect_overhang(
        part,
        up_axis=method.up_axis,
        angle_threshold_deg=method.overhang_max_deg,
    )
    waivers = {kind: Waiver.create(w) for kind, w in (waive or {}).items()}
    features = features or {}
    solids = len(part.solids())
    checked = (
        _wall_assertion(wall, method),
        _overhang_assertion(overhang, method),
    ) + (() if solid_count is None else (_solid_count_assertion(solids, solid_count),))
    _check_waivers({_assertion_kind(a.name) for a in checked}, waivers, features)
    coverages = _coverages(checked, features, part, samples, method)
    assertions = _apply_waivers(
        checked, waivers, _readings(wall, overhang), features, coverages
    )
    warnings = _warnings(assertions, waivers, features, coverages) + (
        (MultiSolid(part=name, solid_count=solids),)
        if solid_count is None and solids > 1
        else ()
    )
    failed = any(a.passed is False and a.waived is None for a in assertions)
    com = part.center()
    diagnostics = PrintabilityDiagnostics(
        name=name,
        method=type(method).__name__,
        method_params=asdict(method),
        bbox=_bbox(part),
        volume_mm3=part.volume,
        surface_area_mm2=part.area,
        center_of_mass_mm=(com.X, com.Y, com.Z),
        is_valid=part.is_valid,
        solid_count=solids,
        min_wall_mm=wall.thickness_mm if wall else None,
        min_wall_at=wall.at if wall else None,
        min_wall_alignment=wall.alignment if wall else None,
        overhang=overhang,
        assertions=assertions,
        warnings=warnings,
        status="assertion_failed" if failed else "ok",
    )
    json_path = out_path / f"{name}-printability.json"
    json_path.write_text(json.dumps(asdict(diagnostics), indent=2) + "\n")
    for w in warnings:
        print(f"{name}: warning: {w.line}", file=sys.stderr)
    if failed:
        for a in assertions:
            if a.passed is False and a.waived is None:
                print(
                    f"{name}: assertion failed: {a.name} — {a.detail}",
                    file=sys.stderr,
                )
        print(f"see {json_path}", file=sys.stderr)
        _failures.fail(_failures.Failure(name, json_path))
    return diagnostics
