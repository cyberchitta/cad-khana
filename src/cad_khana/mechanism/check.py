from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from cad_khana import render, viewer
from cad_khana.export import export_assembly
from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.assertions import evaluate as evaluate_assertions
from cad_khana.mechanism.diagnostics import Diagnostics, compute


@dataclass(frozen=True)
class CheckResult:
    exports: tuple[Path, ...]
    diagnostics: Diagnostics


_export_default = True


def _set_export_default(enabled: bool) -> None:
    global _export_default
    _export_default = enabled


def check(
    assembly: Assembly,
    out: str | Path = "outputs",
    *,
    export: bool | None = None,
) -> CheckResult:
    out_path = Path(out)
    out_path.mkdir(parents=True, exist_ok=True)
    do_export = _export_default if export is None else export
    exports = export_assembly(assembly, out_path) if do_export else ()
    assertion_results = evaluate_assertions(assembly)
    failed = any(not a.passed for a in assertion_results)
    diagnostics = replace(
        compute(assembly),
        exports=tuple(str(p) for p in exports),
        assertions=assertion_results,
        status="assertion_failed" if failed else "ok",
    )
    (out_path / "mechanism.json").write_text(
        json.dumps(asdict(diagnostics), indent=2) + "\n"
    )
    if viewer.auto_enabled():
        viewer.push(assembly)
    if render.auto_enabled():
        render.render(assembly, render.auto_out() or out_path / "views")
    result = CheckResult(exports=exports, diagnostics=diagnostics)
    if failed:
        raise SystemExit(1)
    return result
