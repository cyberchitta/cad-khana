from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import quote, unquote

from build123d import Compound, Shape
from ocp_tessellate.convert import (  # pyright: ignore[reportMissingTypeStubs]
    export_three_cad_viewer_js,  # pyright: ignore[reportUnknownVariableType]
)

from cad_khana.mechanism.assembly import Assembly, PlacedPart

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
SCHEME = "khana"
PART = "part="
FORM = "khana://<project>/<target>[#part=<dotted path>]"


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


def tree(assembly: Assembly) -> tuple[Shape, ...]:
    """The parts, placed, nested by dotted tree path."""
    return nest(
        tuple((tuple(p.name.split(".")), _leaf(p)) for p in assembly.placed_parts)
    )


def shapes(assembly: Assembly) -> str:
    """The parts as three-cad-viewer's ``Shapes`` JSON. A part's
    ``id`` is the root's ``id``, then its tree path with ``/`` for ``.``:
    the parts go in under one root of ours, since the tessellator makes a
    lone top-level sub-assembly the root and its name leaves every path."""
    root = Compound(children=tree(assembly), label=ROOT)
    return str(export_three_cad_viewer_js(None, root, names=[ROOT]))  # pyright: ignore[reportUnknownArgumentType]


@dataclass(frozen=True)
class Moniker:
    """What a page shows, named so a host can point at it and anyone can
    resolve it without one: ``khana://<project>/<target>`` for the
    assembly, then ``#part=<dotted path>`` for one part of it.
    ``project`` is the repository's folder name, ``target`` what `khana
    view` is given from the repository's root."""

    project: str
    target: str
    part: str | None = None

    def __str__(self) -> str:
        whole = (
            f"{SCHEME}://{quote(self.project, safe='')}/{quote(self.target, safe='/:')}"
        )
        return (
            whole if self.part is None else f"{whole}#{PART}{quote(self.part, safe='')}"
        )

    @staticmethod
    def parse(text: str) -> Moniker:
        """The moniker ``text`` spells; ``ValueError`` saying what is
        wrong when it spells none."""
        scheme, sep, rest = text.partition("://")
        project, slash, path = rest.partition("/")
        target, hashed, fragment = path.partition("#")
        if scheme != SCHEME or not (sep and project and slash and target):
            raise ValueError(f"not a khana moniker: {text!r} ({FORM})")
        if hashed and not (fragment.startswith(PART) and len(fragment) > len(PART)):
            raise ValueError(f"after `#` a moniker names a part: {text!r} ({FORM})")
        part = unquote(fragment.removeprefix(PART)) if hashed else None
        return Moniker(unquote(project), unquote(target), part)


@dataclass(frozen=True)
class Origin:
    """Where a page's assembly was declared: the target as `khana view`
    would be given it from the repository root, and the moniker a host
    points at it by. Outside a repository there is no project and no
    root to be relative to, so no moniker."""

    target: str
    moniker: str | None = None


def repository(path: Path) -> Path | None:
    """The root of the git repository ``path`` is in."""
    here = path.resolve()
    return next((p for p in (here, *here.parents) if (p / ".git").exists()), None)


def origin(module: Path, factory: str | None = None) -> Origin:
    """The origin of ``module``'s assembly, addressed as ``factory`` when
    the target named one."""
    root = repository(module)
    suffix = "" if factory is None else f":{factory}"
    if root is None:
        return Origin(f"{module}{suffix}")
    target = f"{module.resolve().relative_to(root).as_posix()}{suffix}"
    return Origin(target, str(Moniker(root.name, target)))


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
    origin: Origin | None = None,
) -> tuple[Path, ...]:
    """A static page showing the parts: the files of the built
    ``page``, a ``shapes.json`` beside them, and a ``page.json`` saying
    where the assembly was declared. Any static file server hosts it."""
    data = shapes(assembly)
    out.mkdir(parents=True, exist_ok=True)
    copied = tuple(Path(shutil.copy(f, out)) for f in sorted(page.iterdir()))
    written = {
        "shapes.json": data,
        "page.json": json.dumps(asdict(origin or Origin(""))) + "\n",
    }
    for name, text in written.items():
        (out / name).write_text(text)
    return (*copied, *(out / name for name in written))
