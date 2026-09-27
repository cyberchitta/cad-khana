from __future__ import annotations

from build123d import Compound, Shape
from ocp_vscode import show

from cad_khana.mechanism.assembly import Assembly, PlacedPart
from cad_khana.selection import paths

Entry = tuple[tuple[str, ...], Shape]


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
