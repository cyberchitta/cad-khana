from __future__ import annotations

from ocp_vscode import show

from cad_khana.mechanism.assembly import Assembly

def push(assembly: Assembly) -> None:
    placed = assembly.placed_parts
    parts = [p.part.moved(p.location) for p in placed]
    names = [p.name for p in placed]
    colors = [p.color or p.part.color for p in placed]
    extras = {"colors": colors} if any(c is not None for c in colors) else {}
    show(*parts, names=names, **extras)
