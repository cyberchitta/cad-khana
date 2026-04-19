import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cad_khana.cli import app
from cad_khana.core import render, viewer

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
        "from cad_khana.core.assembly import Assembly\n"
        "from cad_khana.core.build import build\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"build(Assembly().add('cube', p.part), out=r'{out}')\n"
    )
    result = runner.invoke(app, ["build", str(script)])
    assert result.exit_code == 0, result.output
    data = json.loads((out / "diagnostics.json").read_text())
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
        "from cad_khana.core.assembly import Assembly\n"
        "from cad_khana.core.build import build\n"
        "\n"
        "with BuildPart() as a:\n"
        "    Box(10, 10, 10)\n"
        "with BuildPart() as b:\n"
        "    Box(5, 5, 5)\n"
        "build(\n"
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
        "from cad_khana.core.assembly import Assembly\n"
        "from cad_khana.core.build import build\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"build(Assembly().add('cube', p.part), out=r'{out}')\n"
    )
    result = runner.invoke(app, ["build", str(script)])
    assert result.exit_code == 0, result.output
    assert calls == []


def test_check_writes_diagnostics_without_exports(tmp_path: Path):
    out = tmp_path / "out"
    script = tmp_path / "good.py"
    script.write_text(
        "from build123d import Box, BuildPart\n"
        "from cad_khana.core.assembly import Assembly\n"
        "from cad_khana.core.build import build\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"build(Assembly().add('cube', p.part), out=r'{out}')\n"
    )
    result = runner.invoke(app, ["check", str(script)])
    assert result.exit_code == 0, result.output
    data = json.loads((out / "diagnostics.json").read_text())
    assert data["status"] == "ok"
    assert data["exports"] == []
    assert not (out / "assembly.stl").exists()
    assert not (out / "assembly.step").exists()


def test_build_after_check_still_exports(tmp_path: Path):
    out = tmp_path / "out"
    script = tmp_path / "good.py"
    script.write_text(
        "from build123d import Box, BuildPart\n"
        "from cad_khana.core.assembly import Assembly\n"
        "from cad_khana.core.build import build\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"build(Assembly().add('cube', p.part), out=r'{out}')\n"
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
        "from cad_khana.core.assembly import Assembly\n"
        "from cad_khana.core.build import build\n"
        "\n"
        "with BuildPart() as p:\n"
        "    Box(10, 10, 10)\n"
        f"build(Assembly().add('cube', p.part), out=r'{out}')\n"
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
    data = json.loads((out / "diagnostics.json").read_text())
    assert data["status"] == "error"
    assert "kaboom" in data["error"]
    assert data["parts"] == {}
