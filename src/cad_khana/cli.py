import json
import runpy
import sys
import traceback
from collections.abc import Callable
from dataclasses import asdict
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Annotated

import typer

from cad_khana import _failures, environment
from cad_khana import draw as _draw
from cad_khana import viewer
from cad_khana.diff import NO_CHANGES, diff as compute_diff
from cad_khana.export import export_assembly
from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.check import _set_export_default, check as check_assembly
from cad_khana.mechanism.diagnostics import Diagnostics
from cad_khana.target import Target, TargetError, package_module_spec, resolve

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
    from cad_khana.mechanism.hints import match_hint
    out.mkdir(parents=True, exist_ok=True)
    diag = Diagnostics(status="error", error=error, hint=match_hint(error))
    (out / "mechanism.json").write_text(
        json.dumps(asdict(diag), indent=2) + "\n"
    )


ScriptArg = Annotated[
    Path,
    typer.Argument(
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Python script executed for effect (orchestration, not declarations).",
    ),
]

OutOpt = Annotated[
    Path | None,
    typer.Option(
        "--out",
        help=(
            "Directory to write error diagnostics if the script fails. "
            "Defaults to <script-dir>/outputs; an explicit value is taken "
            "as cwd-relative."
        ),
    ),
]

TargetArg = Annotated[
    str,
    typer.Argument(
        metavar="TARGET",
        help=(
            "Module path with an optional factory: `unit/assembly.py` or "
            "`unit/assembly.py:build_rotor`. A named factory is called with "
            "its defaults (= the master design); without one the module's "
            "`assembly` name is used — called if callable, accepted as a "
            "value otherwise."
        ),
    ),
]

TargetOutOpt = Annotated[
    Path | None,
    typer.Option(
        "--out",
        help=(
            "Directory for this target's outputs. Defaults to "
            "<module-dir>/outputs for a unit's `assembly.py`, and to "
            "<module-dir>/outputs/<slug> for any other target, so co-located "
            "targets never overwrite each other. An explicit value is taken "
            "as cwd-relative."
        ),
    ),
]


def _exec_script(script: Path) -> None:
    spec = package_module_spec(script)
    if spec is None:
        runpy.run_path(str(script), run_name="__main__")
    else:
        # Package members run with ``python -m`` semantics so their
        # relative imports resolve; alter_sys makes the module the
        # real ``__main__`` (out= anchoring reads its __file__).
        module, root = spec
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        runpy.run_module(module, run_name="__main__", alter_sys=True)


def _run_script(script: Path, out: Path | None, command: str) -> None:
    """Run a user script with failures deferred to this boundary.

    Every ``check()``/``inspect()`` in the script runs, so all of its
    diagnostics JSON is current when the agent reads it; the failures are
    rolled up here and exit nonzero once. Only the boundary can defer —
    see ``_failures``.
    """
    if out is None:
        out = script.resolve().parent / "outputs"
    _failures.defer()
    try:
        _exec_script(script)
    except SystemExit as exc:
        if exc.code:
            raise
    except typer.Exit:
        raise
    except BaseException as exc:
        tb = traceback.format_exc()
        typer.echo(tb, err=True)
        typer.echo(f"khana {command} failed: {type(exc).__name__}: {exc}", err=True)
        _write_error_diagnostics(out, tb)
        raise typer.Exit(code=1)
    finally:
        failed = _failures.take()
    if failed:
        typer.echo(
            f"khana {command}: {len(failed)} of the run's diagnostics failed:",
            err=True,
        )
        for f in failed:
            typer.echo(f"  {f.name} — {f.diagnostics}", err=True)
        raise typer.Exit(code=1)


def _run_target(
    spec: str,
    out: Path | None,
    command: str,
    verb: Callable[[Assembly, Path], None],
) -> None:
    """Import a target's module, resolve one member, run one verb.

    The error boundary of ``_run_script`` applies here too — a factory
    that raises still leaves ``status: "error"`` behind. Failure
    deferral does not: one member, one evaluation.
    """
    target = Target.parse(spec)
    if not target.path.is_file():
        typer.echo(f"error: no such file: {target.path}", err=True)
        raise typer.Exit(code=2)
    # Absolute up front: there is no running script for ``resolve_out``
    # to anchor a relative path to, and an explicit --out is user-typed
    # (cwd-relative) either way.
    out_path = target.default_out if out is None else Path.cwd() / out
    try:
        verb(resolve(target), out_path)
    except TargetError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2)
    except SystemExit as exc:
        if exc.code:
            raise
    except typer.Exit:
        raise
    except BaseException as exc:
        tb = traceback.format_exc()
        typer.echo(tb, err=True)
        typer.echo(f"khana {command} failed: {type(exc).__name__}: {exc}", err=True)
        _write_error_diagnostics(out_path, tb)
        raise typer.Exit(code=1)


@app.command()
def check(target: TargetArg, out: TargetOutOpt = None) -> None:
    """Import a module, resolve its assembly, and write diagnostics.

    Computes diagnostics, evaluates every assertion the assembly (and
    anything it composes) declares, writes `mechanism.json`, and exits
    nonzero if any assertion failed. No export, no viewer push.
    """
    _run_target(target, out, "check", lambda a, o: check_assembly(a, out=o))


@app.command()
def export(target: TargetArg, out: TargetOutOpt = None) -> None:
    """Import a module, resolve its assembly, and write STL + STEP."""
    _run_target(target, out, "export", _write_exports)


def _write_exports(assembly: Assembly, out: Path) -> None:
    for path in export_assembly(assembly, out):
        typer.echo(str(path))


@app.command()
def view(target: TargetArg, out: TargetOutOpt = None) -> None:
    """Import a module and push its assembly to the OCP viewer."""
    _run_target(target, out, "view", lambda a, _out: viewer.push(a))


@app.command()
def run(script: ScriptArg, out: OutOpt = None) -> None:
    """Execute an orchestration script (sweeps, inspect() batches, exports).

    Declarations belong in modules the import-model commands consume;
    this is the escape hatch for genuinely imperative work. `check()`
    called from here writes diagnostics only.
    """
    _run_script(script, out, "run")


@app.command()
def build(script: ScriptArg, out: OutOpt = None) -> None:
    """Deprecated: execute a script and export geometry. Retires next release."""
    typer.echo(
        "khana build is deprecated and retires in the next release: use "
        "`khana export <target>` for STL/STEP and `khana run <script>` for "
        "orchestration.",
        err=True,
    )
    _set_export_default(True)
    try:
        _run_script(script, out, "build")
    finally:
        _set_export_default(False)


@app.command()
def draw(
    target: TargetArg,
    out: TargetOutOpt = None,
    views_dir: Annotated[
        Path | None,
        typer.Option(
            "--views-dir",
            help="Directory to write views. Defaults to <out>/views.",
        ),
    ] = None,
    format: Annotated[
        str,
        typer.Option("--format", help="Output format: png, svg, or both. Default: png."),
    ] = "png",
    themeable: Annotated[
        bool,
        typer.Option(
            "--themeable",
            help=(
                "SVG only: tag polylines with class='cad-visible'/'cad-hidden' "
                "alongside the default stroke. Lets consumer CSS recolor lines "
                "(e.g. for dark-mode theming) while non-CSS renderers fall back "
                "to the inline stroke."
            ),
        ),
    ] = False,
    view: Annotated[
        str | None,
        typer.Option(
            "--view",
            help=(
                "Comma-separated subset of view names. Default: all ten "
                "(top, bottom, front, back, left, right, iso_ne, iso_nw, "
                "iso_se, iso_sw)."
            ),
        ),
    ] = None,
    part: Annotated[
        str | None,
        typer.Option(
            "--part",
            help=(
                "Name of a single part in the assembly to scope drawing and "
                "framing to. Default: draw the whole assembly."
            ),
        ),
    ] = None,
) -> None:
    """Import a module and write orthographic + isometric engineering
    drawings (HLR line-art) for its assembly. For shaded photo-real PNGs
    use chitra-cad's `render` instead."""
    views = tuple(v.strip() for v in view.split(",")) if view else None
    if views is not None:
        unknown = tuple(v for v in views if v not in _draw.VIEW_PRESETS)
        if unknown:
            known = ", ".join(_draw.VIEW_PRESETS.keys())
            typer.echo(
                f"error: unknown --view name(s): {', '.join(unknown)}; known: {known}",
                err=True,
            )
            raise typer.Exit(code=2)
    _run_target(
        target,
        out,
        "draw",
        lambda a, o: _draw.draw(
            a,
            views_dir or o / "views",
            views=views,
            part=part,
            format=format,
            themeable=themeable,
        ),
    )


DiagArg = Annotated[
    Path,
    typer.Argument(
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to a mechanism.json or *-printability.json file.",
    ),
]


@app.command()
def status() -> None:
    """Print environment + viewer reachability as JSON; exit nonzero if degraded."""
    report = environment.probe()
    typer.echo(json.dumps(asdict(report), indent=2))
    if report.status != "ok":
        raise typer.Exit(code=1)


@app.command()
def diff(before: DiagArg, after: DiagArg) -> None:
    """Diff two diagnostics JSON files (mechanism or printability).

    Exits 0 when the files are equivalent, 1 when differences are
    found (like `diff` / `git diff`), 2 on error — so refactor
    harnesses can gate on the exit code.
    """
    old = json.loads(before.read_text())
    new = json.loads(after.read_text())
    try:
        text = compute_diff(old, new)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2)
    typer.echo(text, nl=False)
    if text != NO_CHANGES:
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
