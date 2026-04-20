from __future__ import annotations

from ocp_vscode import show

from cad_khana.mechanism.assembly import Assembly

_auto_enabled = False


def set_auto(enabled: bool) -> None:
    global _auto_enabled
    _auto_enabled = enabled


def auto_enabled() -> bool:
    return _auto_enabled


def push(assembly: Assembly) -> None:
    parts = [p.part.moved(p.location) for p in assembly.parts]
    names = [p.name for p in assembly.parts]
    show(*parts, names=names)
