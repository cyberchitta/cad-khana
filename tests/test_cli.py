import json
from pathlib import Path

import pytest
from ocp_tessellate.convert import to_ocpgroup
from typer.testing import CliRunner

from cad_khana import environment, viewer
from cad_khana.cli import app
from cad_khana.mechanism.diagnostics import SCHEMA_VERSION

runner = CliRunner()


def test_version_prints_and_exits_zero():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "khana" in result.stdout


def test_run_runs_successful_script(tmp_path: Path):
    out = tmp_path / "out"
    script = tmp_path / "good.py"
    script.write_text(_cube_script(out))
    result = runner.invoke(app, ["run", str(script)])
    assert result.exit_code == 0, result.output
    data = json.loads((out / "mechanism.json").read_text())
    assert data["status"] == "ok"
    assert data["parts"]["cube"]["volume_mm3"] > 0


def test_view_pushes_named_parts_to_viewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[dict] = []

    def fake_show(*cad_objs, **kwargs):
        calls.append({"count": len(cad_objs), "names": kwargs.get("names")})

    monkeypatch.setattr(viewer, "show", fake_show)

    module = tmp_path / "asm.py"
    module.write_text(_two_part_module())
    result = runner.invoke(app, ["view", str(module)])
    assert result.exit_code == 0, result.output
    assert calls == [{"count": 2, "names": ["big", "small"]}]


def test_check_does_not_push_to_viewer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Each verb performs its own effect: pushing is `khana view`."""
    calls: list[None] = []
    monkeypatch.setattr(viewer, "show", lambda *a, **kw: calls.append(None))

    module = tmp_path / "asm.py"
    module.write_text(_cube_module())
    result = runner.invoke(app, ["check", str(module)])
    assert result.exit_code == 0, result.output
    assert calls == []


def test_run_writes_diagnostics_without_exports(tmp_path: Path):
    """`check()` under `khana run` is diagnostics-only: a command script
    gets no exports, and there is no field claiming otherwise."""
    out = tmp_path / "out"
    script = tmp_path / "good.py"
    script.write_text(_cube_script(out))
    result = runner.invoke(app, ["run", str(script)])
    assert result.exit_code == 0, result.output
    data = json.loads((out / "mechanism.json").read_text())
    assert data["status"] == "ok"
    assert "exports" not in data
    assert not (out / "assembly.stl").exists()
    assert not (out / "assembly.step").exists()


def test_build_is_retired_with_a_pointer_to_its_replacements(tmp_path: Path):
    """It survives only as a boundary error: an agent that types the old
    command gets told where its two halves went, not "no such command"."""
    script = tmp_path / "good.py"
    script.write_text(_cube_script(tmp_path / "out"))
    result = runner.invoke(app, ["build", str(script), "--out", "custom"])
    assert result.exit_code == 2
    assert "khana export" in result.output
    assert "khana run" in result.output
    assert not (tmp_path / "out").exists()


def test_draw_writes_png_views(tmp_path: Path):
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cube_module())
    result = runner.invoke(app, ["draw", str(module), "--views-dir", str(views)])
    assert result.exit_code == 0, result.output
    expected = {
        "top.png",
        "bottom.png",
        "front.png",
        "back.png",
        "left.png",
        "right.png",
        "iso_ne.png",
        "iso_nw.png",
        "iso_se.png",
        "iso_sw.png",
    }
    assert expected == {p.name for p in views.iterdir()}


def test_run_writes_error_diagnostics_on_script_failure(tmp_path: Path):
    script = tmp_path / "bad.py"
    script.write_text("raise RuntimeError('kaboom')\n")
    out = tmp_path / "out"
    result = runner.invoke(app, ["run", str(script), "--out", str(out)])
    assert result.exit_code == 1
    data = json.loads((out / "mechanism.json").read_text())
    assert data["status"] == "error"
    assert "kaboom" in data["error"]
    assert data["parts"] == {}


def test_inspect_runs_from_script(tmp_path: Path):
    out = tmp_path / "out"
    script = tmp_path / "asm.py"
    script.write_text(
        "from build123d import Box, BuildPart\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "from cad_khana.mechanism.check import check\n"
        "from cad_khana.printability.inspect import inspect\n"
        "from cad_khana.printability.methods import FDM\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"check(Assembly().with_part('cube', p.part), out=r'{out}')\n"
        f"inspect(p.part, method=FDM(wall_min_mm=1.0, overhang_max_deg=95.0), out=r'{out}', name='cube')\n"
    )
    result = runner.invoke(app, ["run", str(script)])
    assert result.exit_code == 0, result.output
    assert (out / "mechanism.json").exists()
    assert (out / "cube-printability.json").exists()


def test_relative_out_anchors_to_script_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A script's relative ``out=`` lands next to the script, not in cwd."""
    script_dir = tmp_path / "module"
    script_dir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    script = script_dir / "asm.py"
    script.write_text(
        "from build123d import Box, BuildPart\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "from cad_khana.mechanism.check import check\n"
        "from cad_khana.printability.inspect import inspect\n"
        "from cad_khana.printability.methods import FDM\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        "check(Assembly().with_part('cube', p.part), out='outputs')\n"
        "inspect(p.part, method=FDM(wall_min_mm=1.0, overhang_max_deg=95.0),"
        " out='outputs', name='cube')\n"
    )
    result = runner.invoke(app, ["run", str(script)])
    assert result.exit_code == 0, result.output
    assert (script_dir / "outputs" / "mechanism.json").exists()
    assert (script_dir / "outputs" / "cube-printability.json").exists()
    assert not (elsewhere / "outputs").exists()


def test_cli_default_error_diagnostics_anchored_to_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``khana run`` without ``--out`` writes error diagnostics next to the script."""
    script_dir = tmp_path / "module"
    script_dir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    script = script_dir / "bad.py"
    script.write_text("raise RuntimeError('kaboom')\n")
    result = runner.invoke(app, ["run", str(script)])
    assert result.exit_code == 1
    data = json.loads((script_dir / "outputs" / "mechanism.json").read_text())
    assert data["status"] == "error"
    assert "kaboom" in data["error"]
    assert not (elsewhere / "outputs").exists()


def test_cli_explicit_out_stays_cwd_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An explicit ``--out custom`` is taken cwd-relative (user-typed)."""
    script_dir = tmp_path / "module"
    script_dir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    script = script_dir / "bad.py"
    script.write_text("raise RuntimeError('kaboom')\n")
    result = runner.invoke(app, ["run", str(script), "--out", "custom"])
    assert result.exit_code == 1
    assert (elsewhere / "custom" / "mechanism.json").exists()


def _cube_script(out: Path) -> str:
    """An orchestration script: executed for effect by `khana run`."""
    return (
        "from build123d import Box, BuildPart\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "from cad_khana.mechanism.check import check\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"check(Assembly().with_part('cube', p.part), out=r'{out}')\n"
    )


def _cube_module() -> str:
    """A declaration module: imported by a verb, calls nothing effectful."""
    return (
        "from build123d import Box, BuildPart\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        "assembly = Assembly().with_part('cube', p.part)\n"
    )


def test_draw_svg_format_writes_svg_views(tmp_path: Path):
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cube_module())
    result = runner.invoke(
        app, ["draw", str(module), "--views-dir", str(views), "--format", "svg"]
    )
    assert result.exit_code == 0, result.output
    expected = {
        "top.svg",
        "bottom.svg",
        "front.svg",
        "back.svg",
        "left.svg",
        "right.svg",
        "iso_ne.svg",
        "iso_nw.svg",
        "iso_se.svg",
        "iso_sw.svg",
    }
    actual = {p.name for p in views.iterdir()}
    assert expected == actual
    assert not any(p.suffix == ".png" for p in views.iterdir())


def test_draw_svg_files_are_valid_xml(tmp_path: Path):
    import xml.etree.ElementTree as ET

    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cube_module())
    runner.invoke(
        app, ["draw", str(module), "--views-dir", str(views), "--format", "svg"]
    )
    for svg_file in views.glob("*.svg"):
        ET.parse(svg_file)  # raises if invalid XML


def test_draw_both_format_writes_png_and_svg(tmp_path: Path):
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cube_module())
    result = runner.invoke(
        app, ["draw", str(module), "--views-dir", str(views), "--format", "both"]
    )
    assert result.exit_code == 0, result.output
    names = {p.name for p in views.iterdir()}
    for view in (
        "top",
        "bottom",
        "front",
        "back",
        "left",
        "right",
        "iso_ne",
        "iso_nw",
        "iso_se",
        "iso_sw",
    ):
        assert f"{view}.png" in names
        assert f"{view}.svg" in names


def test_draw_default_format_unchanged(tmp_path: Path):
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cube_module())
    result = runner.invoke(app, ["draw", str(module), "--views-dir", str(views)])
    assert result.exit_code == 0, result.output
    names = {p.name for p in views.iterdir()}
    assert any(n.endswith(".png") for n in names)
    assert not any(n.endswith(".svg") for n in names)


def test_draw_svg_themeable_adds_classes(tmp_path: Path):
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cube_module())
    result = runner.invoke(
        app,
        [
            "draw",
            str(module),
            "--views-dir",
            str(views),
            "--format",
            "svg",
            "--themeable",
        ],
    )
    assert result.exit_code == 0, result.output
    svg = (views / "front.svg").read_text()
    assert 'class="cad-visible"' in svg
    # Inline stroke must remain as a fallback for non-CSS renderers.
    assert 'stroke="rgb(0,0,0)"' in svg


def test_draw_svg_default_no_classes(tmp_path: Path):
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cube_module())
    runner.invoke(
        app, ["draw", str(module), "--views-dir", str(views), "--format", "svg"]
    )
    svg = (views / "front.svg").read_text()
    assert "class=" not in svg


def _cylinder_module() -> str:
    return (
        "from build123d import BuildPart, Cylinder\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Cylinder(radius=5, height=10)\n"
        "assembly = Assembly().with_part('cyl', p.part)\n"
    )


def test_draw_svg_cube_has_no_arcs(tmp_path: Path):
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cube_module())
    runner.invoke(
        app, ["draw", str(module), "--views-dir", str(views), "--format", "svg"]
    )
    svg = (views / "iso_se.svg").read_text()
    assert "<polyline" in svg
    assert "<path" not in svg


def test_draw_svg_cylinder_emits_arc_paths(tmp_path: Path):
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cylinder_module())
    result = runner.invoke(
        app, ["draw", str(module), "--views-dir", str(views), "--format", "svg"]
    )
    assert result.exit_code == 0, result.output
    iso = (views / "iso_se.svg").read_text()
    assert "<path d=" in iso
    assert " A " in iso


def test_draw_svg_cylinder_top_view_is_full_circle(tmp_path: Path):
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cylinder_module())
    runner.invoke(
        app, ["draw", str(module), "--views-dir", str(views), "--format", "svg"]
    )
    top = (views / "top.svg").read_text()
    import re

    paths = re.findall(r'<path d="([^"]+)"', top)
    assert paths, "top view of a cylinder should contain at least one arc path"
    full_circles = [d for d in paths if d.count(" A ") == 2]
    assert full_circles, (
        f"expected at least one two-arc full circle in top view, got: {paths}"
    )


def test_draw_svg_top_view_dedupes_silhouette(tmp_path: Path):
    """HLR emits the cylinder rim as both visible and hidden when looking
    down the axis; the draw pass must drop the hidden duplicate."""
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cylinder_module())
    runner.invoke(
        app, ["draw", str(module), "--views-dir", str(views), "--format", "svg"]
    )
    top = (views / "top.svg").read_text()
    import re

    paths = re.findall(r'<path d="([^"]+)"', top)
    # The cylinder's top rim is one closed circle; with dedupe we should
    # see exactly one path for it, not two coincident copies.
    assert len(paths) == 1, f"expected 1 deduped silhouette path, got {len(paths)}"


def test_draw_svg_cylinder_themeable_classes_on_paths(tmp_path: Path):
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cylinder_module())
    runner.invoke(
        app,
        [
            "draw",
            str(module),
            "--views-dir",
            str(views),
            "--format",
            "svg",
            "--themeable",
        ],
    )
    svg = (views / "iso_se.svg").read_text()
    assert "<path" in svg
    import re

    for path_tag in re.findall(r"<path[^/]*/>", svg):
        assert 'class="cad-' in path_tag, path_tag


def test_draw_view_subset_writes_only_requested(tmp_path: Path):
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cube_module())
    result = runner.invoke(
        app,
        ["draw", str(module), "--views-dir", str(views), "--view", "top,iso_ne"],
    )
    assert result.exit_code == 0, result.output
    names = {p.name for p in views.iterdir()}
    assert names == {"top.png", "iso_ne.png"}


def test_draw_view_unknown_name_fails(tmp_path: Path):
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cube_module())
    result = runner.invoke(
        app,
        ["draw", str(module), "--views-dir", str(views), "--view", "isometric"],
    )
    assert result.exit_code == 2
    assert "isometric" in result.output


def _two_part_module() -> str:
    return (
        "from build123d import Box, BuildPart, Location\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "with BuildPart() as a:\n"
        "    Box(40, 40, 40)\n"
        "with BuildPart() as b:\n"
        "    Box(2, 2, 2)\n"
        "assembly = (\n"
        "    Assembly()\n"
        "    .with_part('big', a.part)\n"
        "    .with_part('small', b.part, location=Location((100, 0, 0)))\n"
        ")\n"
    )


def test_draw_part_scopes_to_named_part(tmp_path: Path):
    """`--part small` should frame and draw only `small`, not the big
    box 100mm away. The post-projection canvas-fit transform makes this
    observable: the lines in `small`'s view should occupy most of the
    canvas instead of a tiny corner."""
    views_all = tmp_path / "views_all"
    views_part = tmp_path / "views_part"
    module = tmp_path / "asm.py"
    module.write_text(_two_part_module())

    runner.invoke(
        app,
        [
            "draw",
            str(module),
            "--views-dir",
            str(views_all),
            "--format",
            "svg",
            "--view",
            "front",
        ],
    )
    result = runner.invoke(
        app,
        [
            "draw",
            str(module),
            "--views-dir",
            str(views_part),
            "--format",
            "svg",
            "--view",
            "front",
            "--part",
            "small",
        ],
    )
    assert result.exit_code == 0, result.output
    # Both runs produce a front.svg; the two SVGs must differ in their
    # polyline coordinates because one frames a 100mm-wide spread, the
    # other a 2mm cube.
    svg_all = (views_all / "front.svg").read_text()
    svg_part = (views_part / "front.svg").read_text()
    assert svg_all != svg_part


def _fake_report(viewer_reachable: bool) -> environment.EnvironmentReport:
    return environment.EnvironmentReport(
        cad_khana="0.0.0",
        python="3.13.0",
        build123d="0.10.0",
        bd_warehouse="0.2.0",
        ocp_vscode=environment.ViewerStatus(
            importable=True,
            reachable=viewer_reachable,
            error=None if viewer_reachable else "no listener on port 3939",
        ),
        schema_version=SCHEMA_VERSION,
        status="ok" if viewer_reachable else "degraded",
    )


def test_status_emits_required_keys(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(environment, "probe", lambda: _fake_report(False))
    result = runner.invoke(app, ["status"])
    data = json.loads(result.stdout)
    assert {
        "cad_khana",
        "python",
        "build123d",
        "bd_warehouse",
        "ocp_vscode",
        "schema_version",
        "status",
    } <= data.keys()
    assert data["status"] in {"ok", "degraded"}
    assert {"importable", "reachable", "error"} == data["ocp_vscode"].keys()


def test_status_exits_zero_when_viewer_reachable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(environment, "probe", lambda: _fake_report(True))
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "ok"


def test_status_exits_nonzero_when_viewer_unreachable(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(environment, "probe", lambda: _fake_report(False))
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["status"] == "degraded"
    assert data["ocp_vscode"]["reachable"] is False


def test_status_real_probe_runs_and_returns_json():
    """Smoke test: actually probe the environment. Viewer probably isn't
    listening in CI, so exit code may be 1; the JSON must still parse and
    carry all required keys."""
    result = runner.invoke(app, ["status"])
    assert result.exit_code in (0, 1), result.output
    data = json.loads(result.stdout)
    assert data["schema_version"] == SCHEMA_VERSION
    assert isinstance(data["ocp_vscode"]["reachable"], bool)


def test_status_stdout_is_json_when_port_discovery_prints(
    monkeypatch: pytest.MonkeyPatch,
):
    """ocp_vscode print()s "Using port N" when it finds a live viewer —
    only where one is listening, so CI never sees it."""

    def chatty_get_port() -> int:
        print("Using port 3939")
        return 3939

    monkeypatch.setattr("ocp_vscode.get_port", chatty_get_port)
    result = runner.invoke(app, ["status"])
    assert json.loads(result.stdout)["schema_version"] == SCHEMA_VERSION


def _pkg_tree(tmp_path: Path, name: str) -> Path:
    """A two-level package tree whose leaf script needs BOTH relative
    import forms: ``.params`` (sibling) and ``..shared`` (package root).
    Distinct *name* per test — run_module leaves the package cached in
    this process's ``sys.modules``, so a reused name would resolve to a
    prior test's tree."""
    root = tmp_path / "proj"
    (root / name / "unit").mkdir(parents=True)
    (root / name / "__init__.py").write_text("")
    (root / name / "unit" / "__init__.py").write_text("")
    (root / name / "shared.py").write_text("PREFIX = 'cube'\n")
    (root / name / "unit" / "params.py").write_text("SIZE = 10\n")
    (root / name / "unit" / "asm.py").write_text(
        "from build123d import Box\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "from cad_khana.mechanism.check import check\n"
        "\n"
        "from ..shared import PREFIX\n"
        "from .params import SIZE\n"
        "\n"
        "check(Assembly().with_part(PREFIX, Box(SIZE, SIZE, SIZE)), out='outputs')\n"
    )
    return root


def test_run_executes_package_member_with_relative_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A script inside a package runs with ``python -m`` semantics:
    relative imports resolve and relative ``out=`` still lands next to
    the script, from an unrelated cwd."""
    root = _pkg_tree(tmp_path, "pkgok")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    script = root / "pkgok" / "unit" / "asm.py"
    result = runner.invoke(app, ["run", str(script)])
    assert result.exit_code == 0, result.output
    data = json.loads((script.parent / "outputs" / "mechanism.json").read_text())
    assert data["status"] == "ok"
    assert data["parts"]["cube"]["volume_mm3"] > 0
    assert not (elsewhere / "outputs").exists()


def test_run_lets_a_standalone_script_import_its_sibling_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A command script imports the declaration module it sits beside —
    the two-file shape the skill recommends. ``runpy.run_path`` does not
    put the script's directory on ``sys.path`` on its own, so without
    the fix this raises ModuleNotFoundError while ``khana check`` on a
    module in the same directory resolves the same import fine."""
    unit = tmp_path / "sibling_unit"
    unit.mkdir()
    # A distinct module name: ``target.load`` caches standalone modules
    # in ``sys.modules`` under the file stem, so reusing ``assembly``
    # would resolve to another test's file in the same process.
    (unit / "hinge_decl.py").write_text("SIZE = 10\n")
    script = unit / "printability.py"
    # The script asserts the imported value itself: resolving the *wrong*
    # sibling (a stale ``sys.modules`` entry) would exit 0 otherwise.
    script.write_text(
        "from hinge_decl import SIZE\n"
        "\n"
        "assert SIZE == 10, f'imported the wrong sibling: {SIZE}'\n"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = runner.invoke(app, ["run", str(script)])
    assert result.exit_code == 0, result.output


def test_run_lets_a_scratch_script_import_packages_under_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A scratch probe outside the repo, run from the repo root, imports
    the repo's packages — what ``PYTHONPATH=. python probe.py`` gives.
    Without cwd on ``sys.path`` only the script's own directory is
    importable and this raises ModuleNotFoundError."""
    repo = tmp_path / "repo"
    (repo / "cwdpkg").mkdir(parents=True)
    (repo / "cwdpkg" / "__init__.py").write_text("")
    (repo / "cwdpkg" / "part.py").write_text("SIZE = 7\n")
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    script = scratch / "probe.py"
    script.write_text(
        "from cwdpkg.part import SIZE\n"
        "\n"
        "assert SIZE == 7, f'imported the wrong package: {SIZE}'\n"
    )
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["run", str(script)])
    assert result.exit_code == 0, result.output


def test_package_member_failure_writes_error_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = _pkg_tree(tmp_path, "pkgbad")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    bad = root / "pkgbad" / "unit" / "bad.py"
    bad.write_text("from .params import SIZE\nraise RuntimeError(f'kaboom {SIZE}')\n")
    result = runner.invoke(app, ["run", str(bad)])
    assert result.exit_code == 1
    data = json.loads((bad.parent / "outputs" / "mechanism.json").read_text())
    assert data["status"] == "error"
    assert "kaboom 10" in data["error"]


def test_plain_script_beside_init_free_dir_keeps_run_path(tmp_path: Path):
    """No ``__init__.py`` in the script's directory → the old run_path
    behavior, even when a sibling directory IS a package."""
    (tmp_path / "somepkg").mkdir()
    (tmp_path / "somepkg" / "__init__.py").write_text("")
    out = tmp_path / "out"
    script = tmp_path / "plain.py"
    script.write_text(_cube_script(out))
    result = runner.invoke(app, ["run", str(script)])
    assert result.exit_code == 0, result.output
    assert json.loads((out / "mechanism.json").read_text())["status"] == "ok"


def test_draw_part_unknown_name_fails(tmp_path: Path):
    """An unknown --part is a ValueError from draw(), surfaced by the
    CLI as a nonzero exit. The mechanism diagnostics themselves still
    landed correctly before the draw step ran, so we assert on the
    CLI failure and the diagnostic message rather than overwritten JSON."""
    views = tmp_path / "views"
    module = tmp_path / "asm.py"
    module.write_text(_cube_module())
    result = runner.invoke(
        app,
        ["draw", str(module), "--views-dir", str(views), "--part", "nope"],
    )
    assert result.exit_code == 1
    assert "nope" in result.output


# --- import-model targets -------------------------------------------------


def _factory_module() -> str:
    return (
        "from build123d import Box\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "\n"
        "def build_rotor(size: float = 10.0) -> Assembly:\n"
        "    return Assembly().with_part('rotor', Box(size, size, size))\n"
        "\n"
        "\n"
        "def build_stator() -> Assembly:\n"
        "    return Assembly().with_part('stator', Box(4, 4, 4))\n"
    )


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_check_resolves_the_degenerate_assembly_value(tmp_path: Path):
    """A module-level ``assembly`` value is the tolerated transitional
    form — every existing consumer module already satisfies it."""
    module = _write(tmp_path / "assembly.py", _cube_module())
    result = runner.invoke(app, ["check", str(module)])
    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / "outputs" / "mechanism.json").read_text())
    assert data["status"] == "ok"
    assert data["parts"]["cube"]["volume_mm3"] > 0
    assert "exports" not in data, "check never exports"


def test_check_calls_a_callable_assembly(tmp_path: Path):
    module = _write(
        tmp_path / "assembly.py",
        "from build123d import Box\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "\n"
        "def assembly() -> Assembly:\n"
        "    return Assembly().with_part('cube', Box(10, 10, 10))\n",
    )
    result = runner.invoke(app, ["check", str(module)])
    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / "outputs" / "mechanism.json").read_text())
    assert "cube" in data["parts"]


def test_check_selects_a_named_factory(tmp_path: Path):
    """``:factory`` names a member; it is called with its defaults, so
    the defaults are the master design."""
    module = _write(tmp_path / "assembly.py", _factory_module())
    result = runner.invoke(app, ["check", f"{module}:build_stator"])
    assert result.exit_code == 0, result.output
    data = json.loads(
        (tmp_path / "outputs" / "assembly-build_stator" / "mechanism.json").read_text()
    )
    assert set(data["parts"]) == {"stator"}


def test_check_imports_a_package_member_with_relative_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Import-model commands get ``python -m`` semantics too: a module
    inside a package resolves both relative import forms."""
    root = _pkg_tree(tmp_path, "pkgimp")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    module = root / "pkgimp" / "unit" / "assembly.py"
    module.write_text(
        "from build123d import Box\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "from ..shared import PREFIX\n"
        "from .params import SIZE\n"
        "\n"
        "assembly = Assembly().with_part(PREFIX, Box(SIZE, SIZE, SIZE))\n"
    )
    result = runner.invoke(app, ["check", str(module)])
    assert result.exit_code == 0, result.output
    data = json.loads((module.parent / "outputs" / "mechanism.json").read_text())
    assert data["parts"]["cube"]["volume_mm3"] > 0
    assert not (elsewhere / "outputs").exists()


def test_check_exits_nonzero_on_a_failed_assertion(tmp_path: Path):
    module = _write(
        tmp_path / "assembly.py",
        "from build123d import Box, Location\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "assembly = (\n"
        "    Assembly()\n"
        "    .with_part('a', Box(10, 10, 10))\n"
        "    .with_part('b', Box(10, 10, 10), location=Location((2, 0, 0)))\n"
        "    .assert_no_interference('a', 'b')\n"
        ")\n",
    )
    result = runner.invoke(app, ["check", str(module)])
    assert result.exit_code == 1
    data = json.loads((tmp_path / "outputs" / "mechanism.json").read_text())
    assert data["status"] == "assertion_failed"


def test_export_writes_stl_and_step(tmp_path: Path):
    module = _write(tmp_path / "assembly.py", _cube_module())
    result = runner.invoke(app, ["export", str(module)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "outputs" / "assembly.stl").exists()
    assert (tmp_path / "outputs" / "assembly.step").exists()
    assert "assembly.stl" in result.output
    assert not (tmp_path / "outputs" / "mechanism.json").exists()


def test_default_out_separates_co_located_targets(tmp_path: Path):
    """A unit's ``assembly.py`` owns ``outputs/``; every other target in
    the same directory gets its own subdirectory, so a check module
    cannot overwrite the product's ``mechanism.json``."""
    _write(tmp_path / "assembly.py", _cube_module())
    _write(
        tmp_path / "check_cones.py",
        "from build123d import Box\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "assembly = Assembly().with_part('cone', Box(1, 1, 1))\n",
    )
    assert runner.invoke(app, ["check", str(tmp_path / "assembly.py")]).exit_code == 0
    assert (
        runner.invoke(app, ["check", str(tmp_path / "check_cones.py")]).exit_code == 0
    )
    product = json.loads((tmp_path / "outputs" / "mechanism.json").read_text())
    fixture = json.loads(
        (tmp_path / "outputs" / "check_cones" / "mechanism.json").read_text()
    )
    assert set(product["parts"]) == {"cube"}
    assert set(fixture["parts"]) == {"cone"}


def test_explicit_out_overrides_the_default_and_stays_cwd_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    module = _write(tmp_path / "assembly.py", _cube_module())
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    result = runner.invoke(app, ["check", str(module), "--out", "custom"])
    assert result.exit_code == 0, result.output
    assert (elsewhere / "custom" / "mechanism.json").exists()


def test_missing_member_lists_the_modules_factories(tmp_path: Path):
    module = _write(tmp_path / "unit.py", _factory_module())
    result = runner.invoke(app, ["check", str(module)])
    assert result.exit_code == 2
    assert "build_rotor" in result.output and "build_stator" in result.output


def test_missing_member_with_no_factories_says_so(tmp_path: Path):
    module = _write(tmp_path / "unit.py", "SIZE = 10\n")
    result = runner.invoke(app, ["check", str(module)])
    assert result.exit_code == 2
    assert "no public factory returning Assembly" in result.output


def test_unknown_factory_name_is_a_boundary_error(tmp_path: Path):
    module = _write(tmp_path / "assembly.py", _factory_module())
    result = runner.invoke(app, ["check", f"{module}:build_nothing"])
    assert result.exit_code == 2
    assert "build_nothing" in result.output
    assert "build_rotor" in result.output


def test_non_assembly_member_is_a_boundary_error(tmp_path: Path):
    module = _write(tmp_path / "assembly.py", "assembly = 42\n")
    result = runner.invoke(app, ["check", str(module)])
    assert result.exit_code == 2
    assert "int" in result.output


def test_factory_returning_a_non_assembly_is_a_boundary_error(tmp_path: Path):
    module = _write(
        tmp_path / "assembly.py",
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "\n"
        "def assembly() -> Assembly:\n"
        "    return 'not an assembly'\n",
    )
    result = runner.invoke(app, ["check", str(module)])
    assert result.exit_code == 2
    assert "expected an Assembly" in result.output


def test_factory_that_raises_leaves_error_diagnostics(tmp_path: Path):
    module = _write(
        tmp_path / "assembly.py",
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "\n"
        "def assembly() -> Assembly:\n"
        "    raise RuntimeError('kaboom')\n",
    )
    result = runner.invoke(app, ["check", str(module)])
    assert result.exit_code == 1
    data = json.loads((tmp_path / "outputs" / "mechanism.json").read_text())
    assert data["status"] == "error"
    assert "kaboom" in data["error"]


def test_import_time_failure_leaves_error_diagnostics(tmp_path: Path):
    module = _write(tmp_path / "assembly.py", "raise RuntimeError('kaboom')\n")
    result = runner.invoke(app, ["check", str(module)])
    assert result.exit_code == 1
    data = json.loads((tmp_path / "outputs" / "mechanism.json").read_text())
    assert data["status"] == "error"
    assert "kaboom" in data["error"]


def test_missing_target_file_exits_two(tmp_path: Path):
    result = runner.invoke(app, ["check", str(tmp_path / "nope.py")])
    assert result.exit_code == 2
    assert "no such file" in result.output


# --- diff exit codes ------------------------------------------------------


def _mech_json(tmp_path: Path, name: str, **overrides) -> Path:
    base = {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "parts": {},
        "interferences": [],
        "assertions": [],
    }
    path = tmp_path / name
    path.write_text(json.dumps(base | overrides))
    return path


def _sweep_script(out: Path, thicknesses: tuple[float, ...]) -> str:
    # One inspect() per plate, thinnest first, so anything that stops at
    # the first failure leaves the later parts unwritten.
    return (
        "from build123d import Box, BuildPart\n"
        "from cad_khana.printability.inspect import inspect\n"
        "from cad_khana.printability.methods import FDM\n"
        "def plate(t):\n"
        "    with BuildPart() as p:\n"
        "        Box(20, 20, t)\n"
        "    return p.part\n"
        f"for i, t in enumerate({thicknesses!r}):\n"
        "    inspect(plate(t), method=FDM(wall_min_mm=1.5),\n"
        f"            out={str(out)!r}, name=f'p{{i}}')\n"
    )


def test_failing_part_does_not_abort_the_rest_of_the_sweep(tmp_path: Path):
    """A red part must not stop the run: the agent needs every part's JSON
    current in one pass, and the files a stopped run leaves behind are
    stale while still reading as this run's output."""
    script = tmp_path / "sweep.py"
    script.write_text(_sweep_script(tmp_path, (0.4, 3.0, 4.0)))
    result = runner.invoke(app, ["run", str(script), "--out", str(tmp_path)])

    assert result.exit_code == 1
    written = {
        p.stem: json.loads(p.read_text()) for p in tmp_path.glob("*-printability.json")
    }
    assert set(written) == {"p0-printability", "p1-printability", "p2-printability"}
    assert written["p0-printability"]["status"] == "assertion_failed"
    assert written["p1-printability"]["status"] == "ok"
    assert written["p2-printability"]["status"] == "ok"


def test_boundary_rolls_up_every_failure_with_its_json_path(tmp_path: Path):
    script = tmp_path / "sweep.py"
    script.write_text(_sweep_script(tmp_path, (0.4, 0.5, 4.0)))
    result = runner.invoke(app, ["run", str(script), "--out", str(tmp_path)])

    assert result.exit_code == 1
    assert "2 of the run's diagnostics failed" in result.output
    assert "p0 — " in result.output and "p1 — " in result.output
    assert "p2" not in result.output.split("diagnostics failed")[1]


def test_clean_sweep_still_exits_zero(tmp_path: Path):
    script = tmp_path / "sweep.py"
    script.write_text(_sweep_script(tmp_path, (3.0, 4.0)))
    result = runner.invoke(app, ["run", str(script), "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output


def test_deferral_does_not_leak_between_runs(tmp_path: Path):
    """A failed run must not colour the next one — the collector is reset
    at the boundary, not left for the next invocation to inherit."""
    bad, good = tmp_path / "bad.py", tmp_path / "good.py"
    bad.write_text(_sweep_script(tmp_path, (0.4,)))
    good.write_text(_sweep_script(tmp_path, (3.0,)))

    assert runner.invoke(app, ["run", str(bad), "--out", str(tmp_path)]).exit_code == 1
    result = runner.invoke(app, ["run", str(good), "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output


def test_script_raising_its_own_nonzero_exit_is_not_masked(tmp_path: Path):
    script = tmp_path / "s.py"
    script.write_text("raise SystemExit(3)\n")
    result = runner.invoke(app, ["run", str(script), "--out", str(tmp_path)])
    assert result.exit_code == 3


def test_diff_identical_exits_zero(tmp_path: Path):
    a = _mech_json(tmp_path, "a.json")
    b = _mech_json(tmp_path, "b.json")
    result = runner.invoke(app, ["diff", str(a), str(b)])
    assert result.exit_code == 0, result.output
    assert "no changes" in result.stdout


def test_diff_differences_exit_one(tmp_path: Path):
    a = _mech_json(tmp_path, "a.json")
    b = _mech_json(tmp_path, "b.json", status="assertion_failed")
    result = runner.invoke(app, ["diff", str(a), str(b)])
    assert result.exit_code == 1
    assert "status:" in result.stdout


def test_diff_schema_mismatch_exits_two(tmp_path: Path):
    a = _mech_json(tmp_path, "a.json", schema_version="0.1")
    b = _mech_json(tmp_path, "b.json")
    result = runner.invoke(app, ["diff", str(a), str(b)])
    assert result.exit_code == 2


def _rooted_script(out: str) -> str:
    """A script whose check() and inspect() both write to one ``out=``."""
    return (
        "from build123d import Box, BuildPart\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "from cad_khana.mechanism.check import check\n"
        "from cad_khana.printability.inspect import inspect\n"
        "from cad_khana.printability.methods import FDM\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        "check(Assembly().with_part('cube', p.part), out=" + repr(out) + ")\n"
        "inspect(p.part, method=FDM(), out=" + repr(out) + ", name='cube')\n"
    )


def _unit_script(repo: Path, unit: str, out: str = "outputs") -> Path:
    (repo / unit).mkdir(parents=True)
    script = repo / unit / "probe.py"
    script.write_text(_rooted_script(out))
    return script


def test_out_root_moves_relative_out_under_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``--out-root`` mirrors the cwd-relative path of each anchored
    ``out=``, so two scripts' ``outputs/`` stay apart under one root."""
    repo, root = tmp_path / "repo", tmp_path / "root"
    a, b = _unit_script(repo, "cad/m02"), _unit_script(repo, "cad/m03")
    monkeypatch.chdir(repo)
    for script in (a, b):
        result = runner.invoke(app, ["run", str(script), "--out-root", str(root)])
        assert result.exit_code == 0, result.output
    for unit in ("cad/m02", "cad/m03"):
        assert (root / unit / "outputs" / "mechanism.json").exists()
        assert (root / unit / "outputs" / "cube-printability.json").exists()
        assert not (repo / unit / "outputs").exists()


def test_out_root_normalises_parent_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, root = tmp_path / "repo", tmp_path / "root"
    script = _unit_script(repo, "cad/m02", out="../shared")
    monkeypatch.chdir(repo)
    result = runner.invoke(app, ["run", str(script), "--out-root", str(root)])
    assert result.exit_code == 0, result.output
    assert (root / "cad" / "shared" / "mechanism.json").exists()


def test_out_root_mirrors_an_anchor_outside_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, root, scratch = tmp_path / "repo", tmp_path / "root", tmp_path / "scratch"
    repo.mkdir()
    script = _unit_script(scratch, "probe")
    monkeypatch.chdir(repo)
    result = runner.invoke(app, ["run", str(script), "--out-root", str(root)])
    assert result.exit_code == 0, result.output
    mirrored = root / script.parent.resolve().relative_to("/") / "outputs"
    assert (mirrored / "mechanism.json").exists()
    assert not (script.parent / "outputs").exists()


def test_out_root_leaves_an_absolute_out_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo, root, fixed = tmp_path / "repo", tmp_path / "root", tmp_path / "fixed"
    script = _unit_script(repo, "cad/m02", out=str(fixed))
    monkeypatch.chdir(repo)
    result = runner.invoke(app, ["run", str(script), "--out-root", str(root)])
    assert result.exit_code == 0, result.output
    assert (fixed / "mechanism.json").exists()
    assert (fixed / "cube-printability.json").exists()
    assert not root.exists()


def test_out_root_absent_keeps_out_beside_the_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = tmp_path / "repo"
    script = _unit_script(repo, "cad/m02")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("KHANA_OUT_ROOT", raising=False)
    result = runner.invoke(app, ["run", str(script)])
    assert result.exit_code == 0, result.output
    assert (repo / "cad/m02/outputs/mechanism.json").exists()
    assert (repo / "cad/m02/outputs/cube-printability.json").exists()


def test_out_root_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo, root = tmp_path / "repo", tmp_path / "root"
    script = _unit_script(repo, "cad/m02")
    monkeypatch.chdir(repo)
    monkeypatch.setenv("KHANA_OUT_ROOT", str(root))
    result = runner.invoke(app, ["run", str(script)])
    assert result.exit_code == 0, result.output
    assert (root / "cad/m02/outputs/mechanism.json").exists()


def test_out_root_places_error_diagnostics_and_does_not_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Without ``--out``, the error diagnostics follow the root too; and
    the root is reset at the boundary, like failure deferral."""
    repo, root = tmp_path / "repo", tmp_path / "root"
    (repo / "cad/m02").mkdir(parents=True)
    bad = repo / "cad/m02/bad.py"
    bad.write_text("raise RuntimeError('kaboom')\n")
    monkeypatch.chdir(repo)
    result = runner.invoke(app, ["run", str(bad), "--out-root", str(root)])
    assert result.exit_code == 1
    assert (
        "kaboom"
        in json.loads((root / "cad/m02/outputs/mechanism.json").read_text())["error"]
    )
    assert not (repo / "cad/m02/outputs").exists()

    good = _unit_script(repo, "cad/m03")
    assert runner.invoke(app, ["run", str(good)]).exit_code == 0
    assert (repo / "cad/m03/outputs/mechanism.json").exists()


# --- show -----------------------------------------------------------------


def _show_json(tmp_path: Path, count: int = 3) -> Path:
    """``count`` assertions: the second fails, the rest pass with a value."""
    assertions = [
        {
            "name": f"claim_{i:02d}",
            "passed": i != 1,
            "detail": "too close" if i == 1 else None,
            "value": float(count - i),
            "waived": None,
            "skipped": None,
        }
        for i in range(count)
    ]
    return _mech_json(tmp_path, "m.json", assertions=assertions, warnings=[])


def test_show_prints_summary_then_rows(tmp_path: Path):
    result = runner.invoke(app, ["show", str(_show_json(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "3 assertions: 2 passed, 1 failed" in result.stdout
    assert "claim_00" in result.stdout and "claim_02" in result.stdout


def test_show_failed_lists_only_failures(tmp_path: Path):
    result = runner.invoke(app, ["show", str(_show_json(tmp_path)), "--failed"])
    assert result.exit_code == 0, result.output
    rows = [line for line in result.stdout.splitlines() if "claim_" in line]
    assert len(rows) == 1 and rows[0].startswith("FAIL")


def test_show_limits_rows_by_default_and_says_how_many_it_left_out(tmp_path: Path):
    path = _show_json(tmp_path, count=60)
    result = runner.invoke(app, ["show", str(path)])
    assert sum("claim_" in line for line in result.stdout.splitlines()) == 50
    assert "10 more" in result.stdout
    everything = runner.invoke(app, ["show", str(path), "--limit", "0"])
    assert sum("claim_" in line for line in everything.stdout.splitlines()) == 60


def test_show_sort_value_then_limit_gives_the_smallest(tmp_path: Path):
    result = runner.invoke(
        app, ["show", str(_show_json(tmp_path)), "--sort", "value", "--limit", "1"]
    )
    rows = [line for line in result.stdout.splitlines() if "claim_" in line]
    assert len(rows) == 1 and "claim_02" in rows[0]


def test_show_json_is_the_filtered_assertions_unlimited(tmp_path: Path):
    path = _show_json(tmp_path, count=60)
    result = runner.invoke(app, ["show", str(path), "--json", "--grep", "claim_0"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert [a["name"] for a in data] == [f"claim_{i:02d}" for i in range(10)]


def test_show_group_prints_one_line_per_group(tmp_path: Path):
    result = runner.invoke(
        app, ["show", str(_show_json(tmp_path, count=12)), "--group", r"claim_\d"]
    )
    assert result.exit_code == 0, result.output
    lines = [line for line in result.stdout.splitlines() if line.startswith("claim_")]
    assert lines[0].startswith("claim_0 ") and "n=10" in lines[0]
    assert "failed=1" in lines[0] and "min=3" in lines[0]
    assert lines[1].startswith("claim_1 ") and "n=2" in lines[1]


def test_show_reads_an_old_schema_and_says_so(tmp_path: Path):
    path = _mech_json(tmp_path, "old.json", schema_version="0.1")
    result = runner.invoke(app, ["show", str(path)])
    assert result.exit_code == 0, result.output
    assert f"schema 0.1, current {SCHEMA_VERSION}" in result.output


@pytest.mark.parametrize(
    "content", ["{not json", '{"foo": 1}', "[]"], ids=["malformed", "foreign", "list"]
)
def test_show_unreadable_file_exits_two(tmp_path: Path, content: str):
    path = tmp_path / "bad.json"
    path.write_text(content)
    result = runner.invoke(app, ["show", str(path)])
    assert result.exit_code == 2


def test_show_missing_file_exits_two(tmp_path: Path):
    result = runner.invoke(app, ["show", str(tmp_path / "nope.json")])
    assert result.exit_code == 2


def test_show_bad_regex_exits_two(tmp_path: Path):
    result = runner.invoke(app, ["show", str(_show_json(tmp_path)), "--grep", "("])
    assert result.exit_code == 2


# --- check --only / view --only --hide -------------------------------------


def _claims_module() -> str:
    return (
        "from build123d import Box, BuildPart, Location\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        "assembly = (\n"
        "    Assembly()\n"
        "    .with_part('a', p.part)\n"
        "    .with_part('b', p.part, location=Location((5, 0, 0)))\n"
        "    .with_part('c', p.part, location=Location((50, 0, 0)))\n"
        "    .assert_no_interference('a', 'b', name='clear_a_b')\n"
        "    .assert_no_interference('a', 'c', name='clear_a_c')\n"
        "    .assert_distance('a', 'c', min_mm=1.0, name='gap_a_c')\n"
        ")\n"
    )


def test_check_only_evaluates_matching_claims_and_writes_the_json(tmp_path: Path):
    module = tmp_path / "asm.py"
    module.write_text(_claims_module())
    out = tmp_path / "out"
    result = runner.invoke(
        app, ["check", str(module), "--out", str(out), "--only", "gap_*"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads((out / "mechanism.json").read_text())
    assert [a["name"] for a in data["assertions"]] == ["gap_a_c"]
    assert data["selection"]["only"] == ["gap_*"]
    assert "partial run: 1 of 3 assertions" in result.output


def test_check_only_is_repeatable_and_goes_red_on_a_selected_failure(tmp_path: Path):
    module = tmp_path / "asm.py"
    module.write_text(_claims_module())
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "check",
            str(module),
            "--out",
            str(out),
            "--only",
            "gap_*",
            "--only",
            "clear_a_b",
        ],
    )
    assert result.exit_code == 1, result.output
    data = json.loads((out / "mechanism.json").read_text())
    assert [a["name"] for a in data["assertions"]] == ["clear_a_b", "gap_a_c"]
    assert data["status"] == "assertion_failed"


def test_check_only_matching_nothing_is_a_usage_error(tmp_path: Path):
    """A typo that evaluates zero claims must not exit 0."""
    module = tmp_path / "asm.py"
    module.write_text(_claims_module())
    out = tmp_path / "out"
    result = runner.invoke(
        app, ["check", str(module), "--out", str(out), "--only", "gpa_*"]
    )
    assert result.exit_code == 2, result.output
    assert "'gpa_*'" in result.output
    assert not (out / "mechanism.json").exists()


def _tree_module() -> str:
    return (
        "from build123d import Box, BuildPart, Color, Location\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "def cube():\n"
        "    with BuildPart() as p:\n"
        "        Box(2, 2, 2)\n"
        "    return p.part\n"
        "\n"
        "arm = Assembly().with_part('tip', cube()).with_part(\n"
        "    'root', cube(), location=Location((5, 0, 0)), color=Color('red'))\n"
        "s1 = Assembly().with_part('hub', cube()).with_subassembly(\n"
        "    'arm', arm, location=Location((0, 10, 0)))\n"
        "assembly = (\n"
        "    Assembly()\n"
        "    .with_part('frame', cube())\n"
        "    .with_subassembly('s1', s1, location=Location((20, 0, 0)))\n"
        ")\n"
    )


def _leaves(nodes) -> list[str]:
    return [
        leaf
        for n in nodes
        for leaf in (
            [f"{n.label}.{x}" for x in _leaves(n.children)] if n.children else [n.label]
        )
    ]


def _captured_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *flags: str
) -> tuple[object, list[dict]]:
    calls: list[dict] = []
    monkeypatch.setattr(
        viewer, "show", lambda *objs, **kw: calls.append({"objs": objs, **kw})
    )
    module = tmp_path / "tree.py"
    module.write_text(_tree_module())
    return runner.invoke(app, ["view", str(module), *flags]), calls


def test_view_nests_sub_assemblies_by_dotted_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    result, calls = _captured_view(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    (call,) = calls
    assert call["names"] == ["frame", "s1"]
    assert _leaves(call["objs"]) == ["frame", "s1.hub", "s1.arm.tip", "s1.arm.root"]


def test_view_nesting_is_the_tree_ocp_converts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``show`` hands its objects to ``ocp_tessellate``'s ``to_ocpgroup``;
    the group tree it builds is what the viewer's tree panel lists. The
    render itself is not checked here."""
    _, (call,) = _captured_view(tmp_path, monkeypatch)
    group, _ = to_ocpgroup(*call["objs"], names=call["names"])

    def walk(g) -> list[str]:
        kids = getattr(g, "objects", None) or []
        return (
            [g.name] if not kids else [f"{g.name}/{w}" for k in kids for w in walk(k)]
        )

    leaves = [w.split("/", 1)[1] for w in walk(group)]
    assert leaves == ["frame", "s1/hub", "s1/arm/tip", "s1/arm/root"]


def test_view_keeps_part_colors_through_nesting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _, (call,) = _captured_view(tmp_path, monkeypatch)
    s1 = call["objs"][1]
    arm = next(c for c in s1.children if c.label == "arm")
    root = next(c for c in arm.children if c.label == "root")
    assert root.color is not None and tuple(root.color)[:3] == (1.0, 0.0, 0.0)


def test_view_only_pushes_a_subtree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    result, (call,) = _captured_view(tmp_path, monkeypatch, "--only", "s1.arm")
    assert result.exit_code == 0, result.output
    assert _leaves(call["objs"]) == ["s1.arm.tip", "s1.arm.root"]


def test_view_hide_drops_a_subtree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    result, (call,) = _captured_view(
        tmp_path, monkeypatch, "--hide", "s1.arm", "--hide", "frame"
    )
    assert result.exit_code == 0, result.output
    assert _leaves(call["objs"]) == ["s1.hub"]


def test_view_unknown_path_is_a_usage_error_with_close_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    result, calls = _captured_view(tmp_path, monkeypatch, "--hide", "s1.amr")
    assert result.exit_code == 2, result.output
    assert "s1.arm" in result.output
    assert calls == []


def test_diff_refuses_a_partial_run_against_a_full_one(tmp_path: Path):
    module = tmp_path / "asm.py"
    module.write_text(_claims_module())
    full, part = tmp_path / "full", tmp_path / "part"
    assert runner.invoke(app, ["check", str(module), "--out", str(full)]).exit_code == 1
    only = ["check", str(module), "--out", str(part), "--only", "gap_*"]
    assert runner.invoke(app, only).exit_code == 0
    result = runner.invoke(
        app, ["diff", str(full / "mechanism.json"), str(part / "mechanism.json")]
    )
    assert result.exit_code == 2, result.output
    assert "cannot diff a partial run" in result.output


def test_diff_reads_two_partial_runs_of_the_same_selection(tmp_path: Path):
    module = tmp_path / "asm.py"
    module.write_text(_claims_module())
    one, two = tmp_path / "one", tmp_path / "two"
    for out in (one, two):
        only = ["check", str(module), "--out", str(out), "--only", "gap_*"]
        assert runner.invoke(app, only).exit_code == 0
    result = runner.invoke(
        app, ["diff", str(one / "mechanism.json"), str(two / "mechanism.json")]
    )
    assert result.exit_code == 0, result.output
