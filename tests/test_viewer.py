import json
from pathlib import Path

import pytest
from build123d import Box

from cad_khana import viewer
from cad_khana.mechanism.assembly import Assembly


def _source(root: Path, script: str = "export {};") -> Path:
    (root / "src").mkdir(parents=True)
    (root / "node_modules" / "dep").mkdir(parents=True)
    (root / "build.ts").write_text("// build")
    (root / "src" / "page.ts").write_text(script)
    (root / "node_modules" / "dep" / "index.js").write_text("// fetched")
    return root


def _fake_bun(calls: list[tuple[list[str], Path]]) -> viewer.Run:
    """Stands in for `bun`: records each call, and writes a page where
    the build is told to."""

    def run(args: list[str], *, cwd: Path, **_kwargs: object) -> None:
        calls.append((args, cwd))
        if args[1] == "run":
            out = Path(args[-1])
            out.mkdir()
            (out / "index.html").write_text((cwd / "src" / "page.ts").read_text())

    return run


def test_page_key_follows_the_sources_and_not_what_bun_fetched(tmp_path: Path):
    source = _source(tmp_path / "viewer")
    key = viewer.page_key(source)
    (source / "node_modules" / "dep" / "index.js").write_text("// fetched again")
    assert viewer.page_key(source) == key
    (source / "src" / "page.ts").write_text("export const changed = 1;")
    assert viewer.page_key(source) != key


def test_built_page_builds_once_per_source_state(tmp_path: Path):
    """The first call installs and builds in a copy of the sources; a
    second is answered from the cache; changed sources build again,
    beside the page they replaced."""
    source = _source(tmp_path / "viewer", "first")
    cache = tmp_path / "cache"
    calls: list[tuple[list[str], Path]] = []
    bun = _fake_bun(calls)

    first = viewer.built_page(source, cache, bun)
    assert (first / "index.html").read_text() == "first"
    assert [args[:2] for args, _ in calls] == [["bun", "install"], ["bun", "run"]]
    assert all(source not in cwd.parents and cwd != source for _, cwd in calls)

    assert viewer.built_page(source, cache, bun) == first
    assert len(calls) == 2

    (source / "src" / "page.ts").write_text("second")
    second = viewer.built_page(source, cache, bun)
    assert second != first
    assert (second / "index.html").read_text() == "second"
    assert (first / "index.html").read_text() == "first"
    assert {p.name for p in cache.iterdir()} == {first.name, second.name}


def test_built_page_failed_build_leaves_no_page(tmp_path: Path):
    source = _source(tmp_path / "viewer")
    cache = tmp_path / "cache"

    def no_bun(_args: list[str], **_kwargs: object) -> None:
        raise FileNotFoundError("bun")

    with pytest.raises(FileNotFoundError):
        viewer.built_page(source, cache, no_bun)
    assert not any(cache.iterdir())


def test_defining_line_prefers_the_definition_to_a_mention():
    source = (
        "# assembly is built below\n"
        "from parts import build_lid\n"
        "def build_unit(\n    lift: float = 1.0,\n) -> Assembly:\n    return build_lid()\n"
        "assembly: Assembly = build_unit()\n"
    )
    assert viewer.defining_line(source, "build_unit") == "def build_unit("
    assert (
        viewer.defining_line(source, "assembly") == "assembly: Assembly = build_unit()"
    )
    assert viewer.defining_line(source, "build_lid") == "from parts import build_lid"
    assert viewer.defining_line(source, "build") is None


def test_origin_is_relative_to_the_repository(tmp_path: Path):
    """The target reads as `khana view` would be given it from the
    repository root; outside one there is nothing to point at."""
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    module = tmp_path / "repo" / "cad" / "unit.py"
    module.parent.mkdir()
    module.write_text("def build_unit() -> Assembly:\n    ...\n")
    assert viewer.origin(module, "build_unit", "build_unit") == viewer.Origin(
        "cad/unit.py:build_unit", "cad/unit.py", "def build_unit() -> Assembly:"
    )
    assert viewer.origin(module, "assembly") == viewer.Origin(
        "cad/unit.py", "cad/unit.py", None
    )
    loose = tmp_path / "loose.py"
    loose.write_text("assembly = 1\n")
    assert viewer.origin(loose, "assembly") == viewer.Origin(str(loose))


def test_write_page_says_where_the_assembly_was_declared(tmp_path: Path):
    built = tmp_path / "built"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html>")
    origin = viewer.Origin("cad/unit.py:build_unit", "cad/unit.py", "def build_unit(")
    out = tmp_path / "page"
    written = viewer.write_page(
        Assembly().with_part("lid", Box(1, 1, 1)), built, out, origin=origin
    )
    assert {p.name for p in written} == {"index.html", "shapes.json", "page.json"}
    assert json.loads((out / "page.json").read_text()) == {
        "target": "cad/unit.py:build_unit",
        "path": "cad/unit.py",
        "anchor": "def build_unit(",
    }
