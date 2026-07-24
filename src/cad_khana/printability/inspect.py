from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from build123d import Part

from cad_khana._paths import resolve_out
from cad_khana.mechanism.diagnostics import (
    SCHEMA_VERSION,
    AssertionResult,
    BBox,
    _bbox,
)
from cad_khana.printability.methods import FDM
from cad_khana.printability.overhangs import Overhang, detect_overhang
from cad_khana.printability.wall import WallSample, min_wall


@dataclass(frozen=True)
class PrintabilityDiagnostics:
    schema_version: str = SCHEMA_VERSION
    kind: str = "printability"
    status: str = "ok"
    name: str = "part"
    method: str = "FDM"
    bbox: BBox | None = None
    volume_mm3: float = 0.0
    surface_area_mm2: float = 0.0
    center_of_mass_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    is_valid: bool = True
    min_wall_mm: float | None = None
    min_wall_at: tuple[float, float, float] | None = None
    overhang: Overhang | None = None
    assertions: tuple[AssertionResult, ...] = field(default_factory=tuple)


def _wall_assertion(wall: WallSample | None, method: FDM) -> AssertionResult:
    name = f"wall_min:{method.wall_min_mm}"
    if wall is None:
        return AssertionResult(name, False, "min wall could not be computed")
    passed = wall.thickness_mm >= method.wall_min_mm
    at = ", ".join(f"{c:.2f}" for c in wall.at)
    detail = (
        None
        if passed
        else (
            f"min wall {wall.thickness_mm:.4f}mm below min "
            f"{method.wall_min_mm}mm at ({at})"
        )
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
    out_path = resolve_out(out)
    out_path.mkdir(parents=True, exist_ok=True)
    wall = min_wall(part)
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
    com = part.center()
    diagnostics = PrintabilityDiagnostics(
        name=name,
        method=type(method).__name__,
        bbox=_bbox(part),
        volume_mm3=part.volume,
        surface_area_mm2=part.area,
        center_of_mass_mm=(com.X, com.Y, com.Z),
        is_valid=part.is_valid,
        min_wall_mm=wall.thickness_mm if wall else None,
        min_wall_at=wall.at if wall else None,
        overhang=overhang,
        assertions=assertions,
        status="assertion_failed" if failed else "ok",
    )
    json_path = out_path / f"{name}-printability.json"
    json_path.write_text(json.dumps(asdict(diagnostics), indent=2) + "\n")
    if failed:
        for a in assertions:
            if a.passed is False:
                print(
                    f"{name}: assertion failed: {a.name} — {a.detail}",
                    file=sys.stderr,
                )
        print(f"see {json_path}", file=sys.stderr)
        raise SystemExit(1)
    return diagnostics
