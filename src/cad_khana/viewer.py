from __future__ import annotations

import shutil
from pathlib import Path

from build123d import Compound, Shape
from ocp_tessellate.convert import (  # pyright: ignore[reportMissingTypeStubs]
    export_three_cad_viewer_js,  # pyright: ignore[reportUnknownVariableType]
)
from ocp_vscode import show

from cad_khana.mechanism.assembly import Assembly, PlacedPart
from cad_khana.selection import paths

Entry = tuple[tuple[str, ...], Shape]

PAGE = Path(__file__).parent / "_page"
ROOT = "assembly"


def _leaf(p: PlacedPart) -> Shape:
    shape = p.part.moved(p.location)
    shape.label = p.name.rpartition(".")[2]
    color = p.color or p.part.color
    if color is not None:
        shape.color = color
    return shape


def _node(label: str, members: tuple[Entry, ...]) -> Shape:
    """A part, or a sub-assembly as a labelled ``Compound`` of its
    members — the group ``ocp_vscode`` lists as one collapsible row."""
    if len(members) == 1 and members[0][0] == ():
        return members[0][1]
    return Compound(children=list(nest(members)), label=label)


def nest(entries: tuple[Entry, ...]) -> tuple[Shape, ...]:
    """One node per first path segment, in first-seen order. Sibling
    names are unique across parts and sub-assemblies, so a segment is
    either a leaf or a group, never both."""
    heads = dict.fromkeys(path[0] for path, _ in entries)
    return tuple(
        _node(h, tuple((path[1:], s) for path, s in entries if path[0] == h))
        for h in heads
    )


def tree(
    assembly: Assembly, only: tuple[str, ...] = (), hide: tuple[str, ...] = ()
) -> tuple[Shape, ...]:
    """The selected parts, placed, nested by dotted tree path."""
    placed = assembly.placed_parts
    kept = frozenset(paths(tuple(p.name for p in placed), only, hide))
    return nest(
        tuple((tuple(p.name.split(".")), _leaf(p)) for p in placed if p.name in kept)
    )


def push(
    assembly: Assembly, only: tuple[str, ...] = (), hide: tuple[str, ...] = ()
) -> None:
    nodes = tree(assembly, only, hide)
    show(*nodes, names=[n.label for n in nodes])


def shapes(
    assembly: Assembly, only: tuple[str, ...] = (), hide: tuple[str, ...] = ()
) -> str:
    """The selected parts as three-cad-viewer's ``Shapes`` JSON. A part's
    ``id`` is the root's ``id``, then its tree path with ``/`` for ``.``:
    the parts go in under one root of ours, since the tessellator makes a
    lone top-level sub-assembly the root and its name leaves every path."""
    root = Compound(children=tree(assembly, only, hide), label=ROOT)
    return str(export_three_cad_viewer_js(None, root, names=[ROOT]))  # pyright: ignore[reportUnknownArgumentType]


def write_page(
    assembly: Assembly,
    out: Path,
    only: tuple[str, ...] = (),
    hide: tuple[str, ...] = (),
) -> tuple[Path, ...]:
    """A static page showing the selected parts: the files of ``PAGE``
    and a ``shapes.json`` beside them. Any static file server hosts it."""
    data = shapes(assembly, only, hide)
    out.mkdir(parents=True, exist_ok=True)
    copied = tuple(Path(shutil.copy(f, out)) for f in sorted(PAGE.iterdir()))
    (out / "shapes.json").write_text(data)
    return (*copied, out / "shapes.json")
