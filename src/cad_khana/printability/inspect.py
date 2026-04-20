from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from build123d import Part

from cad_khana.mechanism.diagnostics import (
    SCHEMA_VERSION,
    AssertionResult,
    BBox,
    _bbox,
)
from cad_khana.printability.methods import FDM
from cad_khana.printability.overhangs import Overhang, detect_overhang
from cad_khana.printability.wall import min_wall_mm


@dataclass(frozen=True)
class PrintabilityDiagnostics:
    schema_version: str = SCHEMA_VERSION
    kind: str = "printability"
    status: str = "ok"
    name: str = "part"
    method: str = "FDM"
    bbox: BBox | None = None
    volume_mm3: float = 0.0
    min_wall_mm: float | None = None
    overhang: Overhang | None = None
    assertions: tuple[AssertionResult, ...] = field(default_factory=tuple)


def _wall_assertion(wall: float | None, method: FDM) -> AssertionResult:
    name = f"wall_min:{method.wall_min_mm}"
    if wall is None:
        return AssertionResult(name, False, "min wall could not be computed")
    passed = wall >= method.wall_min_mm
    detail = (
        None
        if passed
        else f"min wall {wall:.4f}mm below min {method.wall_min_mm}mm"
    )
    return AssertionResult(name, passed, detail)


def _overhang_assertion(
    overhang: Overhang | None, method: FDM
) -> AssertionResult:
    name = f"overhang_max:{method.overhang_max_deg}"
    if overhang is None:
        return AssertionResult(name, True, None)
    passed = overhang.max_angle_deg <= method.overhang_max_deg
    detail = (
        None
        if passed
        else (
            f"overhang {overhang.max_angle_deg:.4f}° exceeds max "
            f"{method.overhang_max_deg}°"
        )
    )
    return AssertionResult(name, passed, detail)


def inspect(
    part: Part,
    *,
    method: FDM,
    out: str | Path = "outputs",
    name: str = "part",
) -> PrintabilityDiagnostics:
    out_path = Path(out)
    out_path.mkdir(parents=True, exist_ok=True)
    wall = min_wall_mm(part)
    overhang = detect_overhang(
        part,
        up_axis=method.up_axis,
        angle_threshold_deg=method.overhang_max_deg,
    )
    assertions = (
        _wall_assertion(wall, method),
        _overhang_assertion(overhang, method),
    )
    failed = any(not a.passed for a in assertions)
    diagnostics = PrintabilityDiagnostics(
        name=name,
        method=type(method).__name__,
        bbox=_bbox(part),
        volume_mm3=part.volume,
        min_wall_mm=wall,
        overhang=overhang,
        assertions=assertions,
        status="assertion_failed" if failed else "ok",
    )
    (out_path / f"{name}-printability.json").write_text(
        json.dumps(asdict(diagnostics), indent=2) + "\n"
    )
    if failed:
        raise SystemExit(1)
    return diagnostics
