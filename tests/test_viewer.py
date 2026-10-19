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


def test_a_moniker_reads_back_as_it_was_written():
    """The target keeps its path and factory; a part rides the fragment,
    and a name a URL cannot carry as it is comes back whole."""
    for named in (
        viewer.Moniker("sorted-studs", "cad/m03/assembly.py:build_exhibit"),
        viewer.Moniker(
            "sorted-studs", "cad/m03/assembly.py", "f2.baskets.basket_315_12"
        ),
        viewer.Moniker("my repo", "cad/a b.py:build", "odd #part name"),
    ):
        assert viewer.Moniker.parse(str(named)) == named
    assert (
        str(viewer.Moniker("sorted-studs", "cad/unit.py:build_unit", "f2.rail"))
        == "khana://sorted-studs/cad/unit.py:build_unit#part=f2.rail"
    )
    assert " " not in str(viewer.Moniker("my repo", "cad/a b.py", "odd name"))


@pytest.mark.parametrize(
    "text",
    [
        "cad/unit.py",
        "shala://sorted-studs/cad/unit.py",
        "khana://sorted-studs",
        "khana://sorted-studs/",
        "khana:///cad/unit.py",
        "khana://sorted-studs/cad/unit.py#f2.rail",
        "khana://sorted-studs/cad/unit.py#part=",
    ],
)
def test_what_is_not_a_moniker_says_so(text: str):
    with pytest.raises(ValueError, match="khana://<project>/<target>"):
        viewer.Moniker.parse(text)


def test_origin_is_relative_to_the_repository(tmp_path: Path):
    """The target reads as `khana view` would be given it from the
    repository root, and the moniker names it in that repository;
    outside one there is nothing to name it by."""
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    module = tmp_path / "repo" / "cad" / "unit.py"
    module.parent.mkdir()
    module.write_text("def build_unit() -> Assembly:\n    ...\n")
    assert viewer.origin(module, "build_unit") == viewer.Origin(
        "cad/unit.py:build_unit", "khana://repo/cad/unit.py:build_unit"
    )
    assert viewer.origin(module) == viewer.Origin(
        "cad/unit.py", "khana://repo/cad/unit.py"
    )
    loose = tmp_path / "loose.py"
    loose.write_text("assembly = 1\n")
    assert viewer.origin(loose) == viewer.Origin(str(loose))


def test_write_page_says_where_the_assembly_was_declared(tmp_path: Path):
    built = tmp_path / "built"
    built.mkdir()
    (built / "index.html").write_text("<!doctype html>")
    origin = viewer.Origin(
        "cad/unit.py:build_unit", "khana://repo/cad/unit.py:build_unit"
    )
    out = tmp_path / "page"
    written = viewer.write_page(
        Assembly().with_part("lid", Box(1, 1, 1)), built, out, origin=origin
    )
    assert {p.name for p in written} == {"index.html", "shapes.json", "page.json"}
    assert json.loads((out / "page.json").read_text()) == {
        "target": "cad/unit.py:build_unit",
        "moniker": "khana://repo/cad/unit.py:build_unit",
    }


def test_the_page_claims_the_khana_scheme():
    """Shala reads the claim from the built index.html on disk; it is how
    a reveal of a khana moniker reaches the page."""
    html = (viewer.SOURCE / "src" / "index.html").read_text()
    assert f'<meta name="shala-scheme" content="{viewer.SCHEME}" />' in html
