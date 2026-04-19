from __future__ import annotations

from pathlib import Path

from build123d import export_step, export_stl

from cad_khana.core.assembly import Assembly


def export_assembly(
    assembly: Assembly,
    out: Path,
    stem: str = "assembly",
) -> tuple[Path, ...]:
    out.mkdir(parents=True, exist_ok=True)
    compound = assembly.compound
    stl_path = out / f"{stem}.stl"
    step_path = out / f"{stem}.step"
    export_stl(compound, str(stl_path))
    export_step(compound, str(step_path))
    return (stl_path, step_path)
