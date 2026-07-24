from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from cad_khana import draw, viewer
from cad_khana._paths import resolve_out
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
    out_path = resolve_out(out)
    out_path.mkdir(parents=True, exist_ok=True)
    do_export = _export_default if export is None else export
    exports = export_assembly(assembly, out_path) if do_export else ()
    assertion_results = evaluate_assertions(assembly)
    failed = any(a.passed is False for a in assertion_results)
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
    if draw.auto_enabled():
        draw.draw(
            assembly,
            draw.auto_out() or out_path / "views",
            views=draw.auto_views(),
            part=draw.auto_part(),
            format=draw.auto_fmt(),
            themeable=draw.auto_themeable(),
        )
    result = CheckResult(exports=exports, diagnostics=diagnostics)
    if failed:
        for a in assertion_results:
            if a.passed is False:
                print(
                    f"assertion failed: {a.name} — {a.detail}",
                    file=sys.stderr,
                )
        print(f"see {out_path / 'mechanism.json'}", file=sys.stderr)
        raise SystemExit(1)
    return result
