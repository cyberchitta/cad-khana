import json
import runpy
import traceback
from dataclasses import asdict
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Annotated

import typer

from cad_khana.core.diagnostics import Diagnostics

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


@app.command()
def build(
    script: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Python script that composes an assembly and calls cad_khana.build().",
        ),
    ],
    out: Annotated[
        Path,
        typer.Option(
            "--out",
            help="Directory to write error diagnostics if the script fails.",
        ),
    ] = Path("outputs"),
) -> None:
    """Run a user script to compose an assembly and export geometry."""
    try:
        runpy.run_path(str(script), run_name="__main__")
    except (SystemExit, typer.Exit):
        raise
    except BaseException as exc:
        tb = traceback.format_exc()
        typer.echo(tb, err=True)
        typer.echo(f"khana build failed: {type(exc).__name__}: {exc}", err=True)
        _write_error_diagnostics(out, tb)
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
