import json
from pathlib import Path

from typer.testing import CliRunner

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
