from __future__ import annotations

from ocp_vscode import (  # pyright: ignore[reportMissingTypeStubs]
    show,  # pyright: ignore[reportUnknownVariableType]
)

from cad_khana.mechanism.assembly import Assembly
from cad_khana.viewer import (
    tree,  # pyright: ignore[reportUnknownVariableType]  (build123d's Shape is generic)
)


def push(
    assembly: Assembly, only: tuple[str, ...] = (), hide: tuple[str, ...] = ()
) -> None:
    """Sends the selected parts to a listening OCP viewer. The one
    module that needs ``ocp_vscode``, which is the ``ocp`` extra."""
    nodes = tree(assembly, only, hide)  # pyright: ignore[reportUnknownVariableType]
    show(*nodes, names=[str(n.label) for n in nodes])  # pyright: ignore[reportUnknownVariableType]
