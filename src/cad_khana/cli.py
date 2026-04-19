from importlib.metadata import version as _pkg_version
from typing import Annotated

import typer

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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
