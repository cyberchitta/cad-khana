from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from cad_khana.core.assembly import Assembly
from cad_khana.core.assertions import evaluate as evaluate_assertions
from cad_khana.core.diagnostics import Diagnostics, compute
from cad_khana.core.export import export_assembly
from cad_khana.core import render, viewer


@dataclass(frozen=True)
class BuildResult:
    exports: tuple[Path, ...]
    diagnostics: Diagnostics


_export_enabled = True


def set_export_enabled(enabled: bool) -> None:
    global _export_enabled
    _export_enabled = enabled


def build(assembly: Assembly, out: str | Path = "outputs") -> BuildResult:
    out_path = Path(out)
    out_path.mkdir(parents=True, exist_ok=True)
    exports = export_assembly(assembly, out_path) if _export_enabled else ()
    assertion_results = evaluate_assertions(assembly)
    failed = any(not a.passed for a in assertion_results)
    diagnostics = replace(
        compute(assembly),
        exports=tuple(str(p) for p in exports),
        assertions=assertion_results,
        status="assertion_failed" if failed else "ok",
    )
    (out_path / "diagnostics.json").write_text(
        json.dumps(asdict(diagnostics), indent=2) + "\n"
    )
    if viewer.auto_enabled():
        viewer.push(assembly)
    if render.auto_enabled():
        render.render(assembly, render.auto_out() or out_path / "views")
    result = BuildResult(exports=exports, diagnostics=diagnostics)
    if failed:
        raise SystemExit(1)
    return result
