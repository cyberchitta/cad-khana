from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from cad_khana.core.assembly import Assembly
from cad_khana.core.diagnostics import Diagnostics, compute
from cad_khana.core.export import export_assembly


@dataclass(frozen=True)
class BuildResult:
    exports: tuple[Path, ...]
    diagnostics: Diagnostics


def build(assembly: Assembly, out: str | Path = "outputs") -> BuildResult:
    out_path = Path(out)
    exports = export_assembly(assembly, out_path)
    diagnostics = replace(
        compute(assembly),
        exports=tuple(str(p) for p in exports),
    )
    (out_path / "diagnostics.json").write_text(
        json.dumps(asdict(diagnostics), indent=2) + "\n"
    )
    return BuildResult(exports=exports, diagnostics=diagnostics)
