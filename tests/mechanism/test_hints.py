import json
from pathlib import Path

from typer.testing import CliRunner

from cad_khana.cli import app
from cad_khana.mechanism.hints import match_hint

runner = CliRunner()


def test_no_match_returns_none():
    assert match_hint("completely unrelated error message") is None


def test_matches_missing_part_accessor():
    hint = match_hint("'NoneType' object has no attribute 'part'")
    assert hint is not None
    assert "BuildPart" in hint


def test_matches_missing_volume():
    hint = match_hint("'NoneType' object has no attribute 'volume'")
    assert hint is not None
    assert "assert_no_interference" in hint


def test_matches_location_typeerror():
    hint = match_hint("TypeError: Location() got unexpected keyword argument 'x'")
    assert hint is not None
    assert "Location" in hint


def test_matches_occt_boolean_failure():
    hint = match_hint("BRep_API: command not done")
    assert hint is not None
    assert "boolean" in hint.lower()


def test_matches_occt_fillet_failure():
    hint = match_hint("StdFail_NotDone during chamfer operation")
    assert hint is not None
    assert "radius" in hint.lower()


def test_matches_missing_module():
    hint = match_hint("ModuleNotFoundError: No module named 'numpy'")
    assert hint is not None
    assert "build123d" in hint


def test_hint_in_error_diagnostics_on_script_failure(tmp_path: Path):
    script = tmp_path / "bad.py"
    script.write_text(
        "x = None\n"
        "_ = x.part  # AttributeError: 'NoneType' object has no attribute 'part'\n"
    )
    out = tmp_path / "out"
    result = runner.invoke(app, ["build", str(script), "--out", str(out)])
    assert result.exit_code == 1
    data = json.loads((out / "mechanism.json").read_text())
    assert data["status"] == "error"
    assert data["hint"] is not None
    assert "BuildPart" in data["hint"]


def test_no_hint_on_unrecognized_error(tmp_path: Path):
    script = tmp_path / "bad.py"
    script.write_text("raise RuntimeError('totally unexpected kaboom')\n")
    out = tmp_path / "out"
    result = runner.invoke(app, ["build", str(script), "--out", str(out)])
    assert result.exit_code == 1
    data = json.loads((out / "mechanism.json").read_text())
    assert data["status"] == "error"
    assert data["hint"] is None
