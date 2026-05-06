import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cad_khana import render, viewer
from cad_khana.cli import app

runner = CliRunner()


def test_version_prints_and_exits_zero():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "khana" in result.stdout


def test_build_runs_successful_script(tmp_path: Path):
    out = tmp_path / "out"
    script = tmp_path / "good.py"
    script.write_text(
        "from build123d import Box, BuildPart\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "from cad_khana.mechanism.check import check\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"check(Assembly().add('cube', p.part), out=r'{out}')\n"
    )
    result = runner.invoke(app, ["build", str(script)])
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

    out = tmp_path / "out"
    script = tmp_path / "asm.py"
    script.write_text(
        "from build123d import Box, BuildPart, Location\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "from cad_khana.mechanism.check import check\n"
        "\n"
        "with BuildPart() as a:\n"
        "    Box(10, 10, 10)\n"
        "with BuildPart() as b:\n"
        "    Box(5, 5, 5)\n"
        "check(\n"
        "    Assembly()\n"
        "        .add('big', a.part)\n"
        "        .add('small', b.part, location=Location((20, 0, 0))),\n"
        f"    out=r'{out}',\n"
        ")\n"
    )
    result = runner.invoke(app, ["view", str(script)])
    assert result.exit_code == 0, result.output
    assert calls == [{"count": 2, "names": ["big", "small"]}]
    assert not viewer.auto_enabled(), "auto-view toggle must be cleared after view"


def test_build_does_not_push_to_viewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[None] = []
    monkeypatch.setattr(viewer, "show", lambda *a, **kw: calls.append(None))

    out = tmp_path / "out"
    script = tmp_path / "good.py"
    script.write_text(
        "from build123d import Box, BuildPart\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "from cad_khana.mechanism.check import check\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"check(Assembly().add('cube', p.part), out=r'{out}')\n"
    )
    result = runner.invoke(app, ["build", str(script)])
    assert result.exit_code == 0, result.output
    assert calls == []


def test_check_writes_diagnostics_without_exports(tmp_path: Path):
    out = tmp_path / "out"
    script = tmp_path / "good.py"
    script.write_text(
        "from build123d import Box, BuildPart\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "from cad_khana.mechanism.check import check\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"check(Assembly().add('cube', p.part), out=r'{out}')\n"
    )
    result = runner.invoke(app, ["check", str(script)])
    assert result.exit_code == 0, result.output
    data = json.loads((out / "mechanism.json").read_text())
    assert data["status"] == "ok"
    assert data["exports"] == []
    assert not (out / "assembly.stl").exists()
    assert not (out / "assembly.step").exists()


def test_build_after_check_still_exports(tmp_path: Path):
    out = tmp_path / "out"
    script = tmp_path / "good.py"
    script.write_text(
        "from build123d import Box, BuildPart\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "from cad_khana.mechanism.check import check\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"check(Assembly().add('cube', p.part), out=r'{out}')\n"
    )
    runner.invoke(app, ["check", str(script)])
    result = runner.invoke(app, ["build", str(script)])
    assert result.exit_code == 0, result.output
    assert (out / "assembly.stl").exists()
    assert (out / "assembly.step").exists()


def test_render_writes_png_views(tmp_path: Path):
    out = tmp_path / "out"
    views = tmp_path / "views"
    script = tmp_path / "asm.py"
    script.write_text(
        "from build123d import Box, BuildPart\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "from cad_khana.mechanism.check import check\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"check(Assembly().add('cube', p.part), out=r'{out}')\n"
    )
    result = runner.invoke(
        app, ["render", str(script), "--views-dir", str(views)]
    )
    assert result.exit_code == 0, result.output
    expected = {"front.png", "top.png", "right.png", "iso.png"}
    assert expected.issubset({p.name for p in views.iterdir()})
    assert not render.auto_enabled(), "render auto toggle must be cleared"


def test_build_writes_error_diagnostics_on_script_failure(tmp_path: Path):
    script = tmp_path / "bad.py"
    script.write_text("raise RuntimeError('kaboom')\n")
    out = tmp_path / "out"
    result = runner.invoke(app, ["build", str(script), "--out", str(out)])
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
        f"check(Assembly().add('cube', p.part), out=r'{out}')\n"
        f"inspect(p.part, method=FDM(wall_min_mm=1.0, overhang_max_deg=95.0), out=r'{out}', name='cube')\n"
    )
    result = runner.invoke(app, ["check", str(script)])
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
        "check(Assembly().add('cube', p.part), out='outputs')\n"
        "inspect(p.part, method=FDM(wall_min_mm=1.0, overhang_max_deg=95.0),"
        " out='outputs', name='cube')\n"
    )
    result = runner.invoke(app, ["check", str(script)])
    assert result.exit_code == 0, result.output
    assert (script_dir / "outputs" / "mechanism.json").exists()
    assert (script_dir / "outputs" / "cube-printability.json").exists()
    assert not (elsewhere / "outputs").exists()


def test_cli_default_error_diagnostics_anchored_to_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """``khana build`` without ``--out`` writes error diagnostics next to the script."""
    script_dir = tmp_path / "module"
    script_dir.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    script = script_dir / "bad.py"
    script.write_text("raise RuntimeError('kaboom')\n")
    result = runner.invoke(app, ["build", str(script)])
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
    result = runner.invoke(app, ["build", str(script), "--out", "custom"])
    assert result.exit_code == 1
    assert (elsewhere / "custom" / "mechanism.json").exists()


def _cube_script(out: Path) -> str:
    return (
        "from build123d import Box, BuildPart\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "from cad_khana.mechanism.check import check\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"check(Assembly().add('cube', p.part), out=r'{out}')\n"
    )


def test_render_svg_format_writes_svg_views(tmp_path: Path):
    out = tmp_path / "out"
    views = tmp_path / "views"
    script = tmp_path / "asm.py"
    script.write_text(_cube_script(out))
    result = runner.invoke(
        app, ["render", str(script), "--views-dir", str(views), "--format", "svg"]
    )
    assert result.exit_code == 0, result.output
    expected = {"front.svg", "top.svg", "right.svg", "iso.svg"}
    actual = {p.name for p in views.iterdir()}
    assert expected.issubset(actual)
    assert not any(p.suffix == ".png" for p in views.iterdir())


def test_render_svg_files_are_valid_xml(tmp_path: Path):
    import xml.etree.ElementTree as ET

    out = tmp_path / "out"
    views = tmp_path / "views"
    script = tmp_path / "asm.py"
    script.write_text(_cube_script(out))
    runner.invoke(
        app, ["render", str(script), "--views-dir", str(views), "--format", "svg"]
    )
    for svg_file in views.glob("*.svg"):
        ET.parse(svg_file)  # raises if invalid XML


def test_render_both_format_writes_png_and_svg(tmp_path: Path):
    out = tmp_path / "out"
    views = tmp_path / "views"
    script = tmp_path / "asm.py"
    script.write_text(_cube_script(out))
    result = runner.invoke(
        app, ["render", str(script), "--views-dir", str(views), "--format", "both"]
    )
    assert result.exit_code == 0, result.output
    names = {p.name for p in views.iterdir()}
    for view in ("front", "top", "right", "iso"):
        assert f"{view}.png" in names
        assert f"{view}.svg" in names


def test_render_default_format_unchanged(tmp_path: Path):
    out = tmp_path / "out"
    views = tmp_path / "views"
    script = tmp_path / "asm.py"
    script.write_text(_cube_script(out))
    result = runner.invoke(
        app, ["render", str(script), "--views-dir", str(views)]
    )
    assert result.exit_code == 0, result.output
    names = {p.name for p in views.iterdir()}
    assert {"front.png", "top.png", "right.png", "iso.png"}.issubset(names)
    assert not any(n.endswith(".svg") for n in names)
