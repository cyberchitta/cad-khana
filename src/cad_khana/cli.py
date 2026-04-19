import json
import runpy
import traceback
from dataclasses import asdict
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Annotated

import typer

from cad_khana.core import render as _render
from cad_khana.core import viewer
from cad_khana.core.build import set_export_enabled
from cad_khana.core.diagnostics import Diagnostics
from cad_khana.core.diff import diff as compute_diff

app = typer.Typer(
    name="khana",
    help="Diagnostics-first CAD wrapper around Build123d.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"khana {_pkg_version('cad-khana')}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    pass


def _write_error_diagnostics(out: Path, error: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    diag = Diagnostics(status="error", error=error)
    (out / "diagnostics.json").write_text(
        json.dumps(asdict(diag), indent=2) + "\n"
    )


ScriptArg = Annotated[
    Path,
    typer.Argument(
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Python script that composes an assembly and calls cad_khana.build().",
    ),
]

OutOpt = Annotated[
    Path,
    typer.Option(
        "--out",
        help="Directory to write error diagnostics if the script fails.",
    ),
]


def _run_script(script: Path, out: Path, command: str) -> None:
    try:
        runpy.run_path(str(script), run_name="__main__")
    except (SystemExit, typer.Exit):
        raise
    except BaseException as exc:
        tb = traceback.format_exc()
        typer.echo(tb, err=True)
        typer.echo(f"khana {command} failed: {type(exc).__name__}: {exc}", err=True)
        _write_error_diagnostics(out, tb)
        raise typer.Exit(code=1)


@app.command()
def build(script: ScriptArg, out: OutOpt = Path("outputs")) -> None:
    """Run a user script to compose an assembly and export geometry."""
    _run_script(script, out, "build")


@app.command()
def check(script: ScriptArg, out: OutOpt = Path("outputs")) -> None:
    """Run a user script and write diagnostics only (no STL/STEP export)."""
    set_export_enabled(False)
    try:
        _run_script(script, out, "check")
    finally:
        set_export_enabled(True)


@app.command()
def view(script: ScriptArg, out: OutOpt = Path("outputs")) -> None:
    """Run a user script and push the resulting assembly to the OCP viewer."""
    viewer.set_auto(True)
    try:
        _run_script(script, out, "view")
    finally:
        viewer.set_auto(False)


@app.command()
def render(
    script: ScriptArg,
    out: OutOpt = Path("outputs"),
    views_dir: Annotated[
        Path | None,
        typer.Option(
            "--views-dir",
            help="Directory to write PNG views. Defaults to <out>/views.",
        ),
    ] = None,
) -> None:
    """Run a user script and write orthographic + isometric PNG views."""
    _render.set_auto(True, views_dir)
    try:
        _run_script(script, out, "render")
    finally:
        _render.set_auto(False)


DiagArg = Annotated[
    Path,
    typer.Argument(
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to a diagnostics.json file.",
    ),
]


@app.command()
def diff(before: DiagArg, after: DiagArg) -> None:
    """Diff two diagnostics.json files and print a summary of changes."""
    old = json.loads(before.read_text())
    new = json.loads(after.read_text())
    typer.echo(compute_diff(old, new), nl=False)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
