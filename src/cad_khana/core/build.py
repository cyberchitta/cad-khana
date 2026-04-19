from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cad_khana.core.assembly import Assembly
from cad_khana.core.export import export_assembly


@dataclass(frozen=True)
class BuildResult:
    exports: tuple[Path, ...]


def build(assembly: Assembly, out: str | Path = "outputs") -> BuildResult:
    exports = export_assembly(assembly, Path(out))
    return BuildResult(exports=exports)
