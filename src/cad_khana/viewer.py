from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from build123d import Compound, Shape
from ocp_tessellate.convert import (  # pyright: ignore[reportMissingTypeStubs]
    export_three_cad_viewer_js,  # pyright: ignore[reportUnknownVariableType]
)

from cad_khana.mechanism.assembly import Assembly, PlacedPart
from cad_khana.selection import paths

Entry = tuple[tuple[str, ...], Shape]

Run = Callable[..., object]

PACKAGED = Path(__file__).parent / "_viewer"
SOURCE = PACKAGED if PACKAGED.is_dir() else Path(__file__).parents[2] / "viewer"
CACHE = (
    Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    / "cad-khana"
    / "page"
)
FETCHED = "node_modules"
INSTALL = ("install", "--frozen-lockfile", "--production")
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
    members — the group a viewer lists as one collapsible row."""
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


def shapes(
    assembly: Assembly, only: tuple[str, ...] = (), hide: tuple[str, ...] = ()
) -> str:
    """The selected parts as three-cad-viewer's ``Shapes`` JSON. A part's
    ``id`` is the root's ``id``, then its tree path with ``/`` for ``.``:
    the parts go in under one root of ours, since the tessellator makes a
    lone top-level sub-assembly the root and its name leaves every path."""
    root = Compound(children=tree(assembly, only, hide), label=ROOT)
    return str(export_three_cad_viewer_js(None, root, names=[ROOT]))  # pyright: ignore[reportUnknownArgumentType]


def page_key(source: Path) -> str:
    """Names one state of the page's sources: every file but the
    packages bun fetched, by path and content."""
    files = sorted(
        f.relative_to(source)
        for f in source.rglob("*")
        if f.is_file() and FETCHED not in f.relative_to(source).parts
    )
    return hashlib.sha256(
        b"\0".join(
            part for f in files for part in (bytes(f), (source / f).read_bytes())
        )
    ).hexdigest()[:16]


def built_page(
    source: Path = SOURCE, cache: Path = CACHE, run: Run = subprocess.run
) -> Path:
    """The page built from ``source``, built the first time these
    sources are asked for and kept under their key after. Building
    needs ``bun`` on the PATH, and the registry unless bun has the
    packages already."""
    page = cache / page_key(source)
    return page if (page / "index.html").is_file() else _build(source, page, run)


def _build(source: Path, page: Path, run: Run) -> Path:
    """Builds in a copy beside the cache entry, since an installed
    package's own directory may not be writable, and moves the page into
    place only once it is whole."""
    page.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=page.parent) as tmp:
        work, built = Path(tmp) / "work", Path(tmp) / "page"
        shutil.copytree(source, work, ignore=shutil.ignore_patterns(FETCHED))
        for args in (INSTALL, ("run", "build.ts", str(built))):
            run(["bun", *args], cwd=work, check=True, capture_output=True, text=True)
        shutil.rmtree(page, ignore_errors=True)
        built.rename(page)
    return page


def write_page(
    assembly: Assembly,
    page: Path,
    out: Path,
    only: tuple[str, ...] = (),
    hide: tuple[str, ...] = (),
) -> tuple[Path, ...]:
    """A static page showing the selected parts: the files of the built
    ``page`` and a ``shapes.json`` beside them. Any static file server
    hosts it."""
    data = shapes(assembly, only, hide)
    out.mkdir(parents=True, exist_ok=True)
    copied = tuple(Path(shutil.copy(f, out)) for f in sorted(page.iterdir()))
    (out / "shapes.json").write_text(data)
    return (*copied, out / "shapes.json")
