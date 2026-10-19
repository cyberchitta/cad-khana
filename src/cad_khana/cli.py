import json
import re
import runpy
import subprocess
import traceback
from collections.abc import Callable
from dataclasses import asdict
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Annotated

import typer

from cad_khana import _failures, _paths, drive, environment, viewer
from cad_khana import draw as _draw
from cad_khana.diff import NO_CHANGES
from cad_khana.diff import diff as compute_diff
from cad_khana.export import export_assembly
from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.check import check as check_assembly
from cad_khana.mechanism.diagnostics import Diagnostics
from cad_khana.selection import SelectionError
from cad_khana.show import report, report_json, require_diagnostics
from cad_khana.target import (
    Target,
    TargetError,
    ensure_importable,
    package_module_spec,
    resolve,
    source_imports,
)

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
    (out / "mechanism.json").write_text(json.dumps(asdict(diag), indent=2) + "\n")


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
            "Defaults to <script-dir>/outputs, moved under --out-root when "
            "one is given; an explicit value is taken as cwd-relative."
        ),
    ),
]

OutRootOpt = Annotated[
    Path | None,
    typer.Option(
        "--out-root",
        envvar="KHANA_OUT_ROOT",
        help=(
            "Write every relative out= of the script's check()/inspect() "
            "calls under this directory, at the anchored path's place "
            "relative to the cwd (cad/m02/outputs -> <root>/cad/m02/outputs). "
            "Absolute out= paths are left alone. Cwd-relative."
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
    # A scratch probe outside the repo, run from the repo root, imports
    # the repo's packages — ``PYTHONPATH=. python probe.py`` semantics.
    # Inserted first so the script's own root, inserted below, precedes it.
    ensure_importable(Path.cwd())
    spec = package_module_spec(script)
    if spec is None:
        # ``python script.py`` semantics: the script's own directory is
        # importable, so a command script can import the declaration
        # module it sits beside. ``runpy.run_path`` does not do this on
        # its own, and the import-model verbs already do it via
        # ``target.load`` — without this the two runners disagree about
        # what a sibling import means.
        ensure_importable(script.resolve().parent)
        runpy.run_path(str(script), run_name="__main__")
    else:
        # Package members run with ``python -m`` semantics so their
        # relative imports resolve; alter_sys makes the module the
        # real ``__main__`` (out= anchoring reads its __file__).
        module, root = spec
        ensure_importable(root)
        runpy.run_module(module, run_name="__main__", alter_sys=True)


def _run_script(
    script: Path, out: Path | None, command: str, root: Path | None = None
) -> None:
    """Run a user script with failures deferred to this boundary.

    Every ``check()``/``inspect()`` in the script runs, so all of its
    diagnostics JSON is current when the agent reads it; the failures are
    rolled up here and exit nonzero once. Only the boundary can defer —
    see ``_failures``. An output root is the same kind of boundary
    switch: set for the run, reset after it — see ``_paths``.
    """
    _paths.set_root(None if root is None else Path.cwd() / root)
    if root is not None:
        typer.echo(f"khana {command}: relative out= written under {root}", err=True)
    if out is None:
        out = _paths.under_root(script.resolve().parent / "outputs")
    _failures.defer()
    try:
        with source_imports():
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
        raise typer.Exit(code=1) from None
    finally:
        failed = _failures.take()
        _paths.set_root(None)
    if failed:
        typer.echo(
            f"khana {command}: {len(failed)} of the run's diagnostics failed:",
            err=True,
        )
        for f in failed:
            typer.echo(f"  {f.name} — {f.diagnostics}", err=True)
        raise typer.Exit(code=1)


Verb = Callable[[Assembly, Path], object]


def _run_target(
    spec: str,
    out: Path | None,
    command: str,
    verb: Verb,
) -> None:
    """Import a target's module, resolve one member, run one verb.

    The error boundary of ``_run_script`` applies here too — a factory
    that raises still leaves ``status: "error"`` behind. Failure
    deferral does not: one member, one evaluation. A target naming no
    member, or a selection naming nothing, is a usage error (exit 2)
    that writes nothing, since nothing ran.
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
        with source_imports():
            verb(resolve(target), out_path)
    except (TargetError, SelectionError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from None
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
        raise typer.Exit(code=1) from None


@app.command()
def check(
    target: TargetArg,
    out: TargetOutOpt = None,
    only: Annotated[
        list[str] | None,
        typer.Option(
            "--only",
            help=(
                "Evaluate only assertions whose name matches this glob "
                "(fnmatch, case-sensitive; repeatable). A partial run: "
                "interferences are not computed, and the JSON records the "
                "selection and a partial_run warning. A glob matching no "
                "assertion exits 2."
            ),
        ),
    ] = None,
) -> None:
    """Import a module, resolve its assembly, and write diagnostics.

    Computes diagnostics, evaluates every assertion the assembly (and
    anything it composes) declares, writes `mechanism.json`, and exits
    nonzero if any assertion failed. No export, no viewer push.
    """
    globs = tuple(only or ())
    _run_target(target, out, "check", lambda a, o: check_assembly(a, out=o, only=globs))


@app.command()
def export(target: TargetArg, out: TargetOutOpt = None) -> None:
    """Import a module, resolve its assembly, and write STL + STEP."""
    _run_target(target, out, "export", _write_exports)


def _write_exports(assembly: Assembly, out: Path) -> None:
    for path in export_assembly(assembly, out):
        typer.echo(str(path))


@app.command()
def view(
    target: TargetArg,
    out: TargetOutOpt = None,
    page: Annotated[
        Path | None,
        typer.Option(
            "--page",
            help=(
                "Write the viewer page into this directory instead of "
                "`page/` under --out."
            ),
        ),
    ] = None,
    push: Annotated[
        bool,
        typer.Option(
            "--push",
            help=(
                "Push to a listening OCP viewer instead of writing a page "
                "(needs the `ocp` extra)."
            ),
        ),
    ] = False,
) -> None:
    """Import a module and write its assembly as a static viewer page,
    nested by sub-assembly, or push it to an OCP viewer. A page that
    cannot be built exits 2."""
    if push and page is not None:
        typer.echo("error: --push writes no page; give it or --page", err=True)
        raise typer.Exit(code=2)
    _run_target(
        target,
        out,
        "view",
        _pusher() if push else _pager(target, page),
    )


def _pusher() -> Verb:
    """The push, or exit 2 where ``ocp_vscode`` is not installed: it is
    the `ocp` extra, so the module that needs it is imported here."""
    try:
        import cad_khana.push as ocp
    except ImportError as exc:
        typer.echo(
            f"error: --push needs the OCP viewer client ({exc}); "
            "install `cad-khana[ocp]`",
            err=True,
        )
        raise typer.Exit(code=2) from None
    return lambda a, _out: ocp.push(a)


def _pager(spec: str, page: Path | None) -> Verb:
    built = _built_page()
    target = Target.parse(spec)
    return lambda a, out: _write_page(
        a,
        built,
        out / "page" if page is None else Path.cwd() / page,
        viewer.origin(target.path, target.factory),
    )


def _built_page() -> Path:
    """The viewer page, built here if these sources never were, before
    the target is imported: a machine that cannot build it has run
    nothing."""
    try:
        return viewer.built_page()
    except FileNotFoundError as exc:
        typer.echo(
            f"error: the viewer page could not be built ({exc}). `--page` "
            "builds it with bun the first time: https://bun.sh",
            err=True,
        )
    except subprocess.CalledProcessError as exc:
        typer.echo(
            f"error: building the viewer page failed: {' '.join(exc.cmd)}\n"
            f"{exc.stderr}",
            err=True,
        )
    raise typer.Exit(code=2)


def _write_page(
    assembly: Assembly,
    built: Path,
    out: Path,
    origin: viewer.Origin,
) -> None:
    for path in viewer.write_page(assembly, built, out, origin):
        typer.echo(str(path))


@app.command("resolve")
def resolve_moniker(
    moniker: Annotated[
        str,
        typer.Argument(help="A `khana://<project>/<target>[#part=<part>]` moniker."),
    ],
) -> None:
    """Say what a moniker names, by building its target: the target, and
    the part when it names one. Run from inside the moniker's project.
    Exits 1 when the part is no longer in the assembly, 2 when the
    moniker is malformed, names another project, or its target does not
    resolve."""
    try:
        named = viewer.Moniker.parse(moniker)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from None
    root = viewer.repository(Path.cwd())
    if root is None or root.name != named.project:
        here = "not in a repository" if root is None else f"this is {root.name}"
        typer.echo(
            f"error: {here}; run from inside {named.project}, which the moniker names",
            err=True,
        )
        raise typer.Exit(code=2)
    typer.echo(f"target: {named.target}")
    _run_target(str(root / named.target), None, "resolve", _part_named(named.part))


def _part_named(part: str | None) -> Verb:
    def say(assembly: Assembly, _out: Path) -> None:
        names = {p.name for p in assembly.placed_parts}
        if part is None:
            typer.echo(f"parts: {len(names)}")
        elif part in names:
            typer.echo(f"part: {part}")
        else:
            typer.echo(f"no part {part} in the assembly any more", err=True)
            raise typer.Exit(code=1)

    return say


@app.command()
def run(script: ScriptArg, out: OutOpt = None, out_root: OutRootOpt = None) -> None:
    """Execute an orchestration script (sweeps, inspect() batches, exports).

    Declarations belong in modules the import-model commands consume;
    this is the escape hatch for genuinely imperative work. `check()`
    called from here writes diagnostics only.
    """
    _run_script(script, out, "run", out_root)


@app.command(
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
def build(
    args: Annotated[list[str] | None, typer.Argument(hidden=True)] = None,
) -> None:
    """Retired: use `khana export <target>` and `khana run <script>`.

    Kept only so the old invocation lands on a boundary error naming its
    two replacements rather than typer's bare "no such command".
    """
    typer.echo(
        "error: khana build is retired — it ran a script and exported in one "
        "step. Use `khana export <target>` for STL/STEP, `khana check "
        "<target>` for diagnostics, and `khana run <script>` for "
        "orchestration.",
        err=True,
    )
    raise typer.Exit(code=2)


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
        typer.Option(
            "--format", help="Output format: png, svg, or both. Default: png."
        ),
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
    use `cad_khana.render` (the `render` extra) from a `khana run` script."""
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


viewer_app = typer.Typer(
    help=(
        "Ask an open viewer page what it shows, or change it. The page is "
        "the one `khana view` wrote, open in a host that carries these "
        "commands to it (Shala)."
    ),
    no_args_is_help=True,
)
app.add_typer(viewer_app, name="viewer")

ProjectOpt = Annotated[
    str | None,
    typer.Option(
        "--project",
        help=(
            "The project whose page to reach, as the host names it. "
            "Defaults to the folder name of the repository the cwd is in."
        ),
    ),
]


def _ask(project: str | None, body: drive.Body) -> drive.Answer:
    """One body to the page and its answer; exit 1 when the page or
    its host refused, 2 when neither could be reached."""
    name = project or drive.project(Path.cwd())
    if name is None:
        typer.echo(
            "error: not in a repository; name the project with --project", err=True
        )
        raise typer.Exit(code=2)
    try:
        return drive.ask(name, body)
    except drive.Refused as exc:
        typer.echo(f"refused: {exc}", err=True)
        raise typer.Exit(code=1) from None
    except drive.Unreachable as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from None


def _say(answer: drive.Answer, *lines: str) -> None:
    typer.echo(f"page: {answer.page}")
    for line in (*lines, *((answer.message,) if answer.message else ())):
        typer.echo(line)


def _page_parts(answer: drive.Answer) -> tuple[str, ...]:
    return tuple(str(p) for p in answer.result["parts"])  # pyright: ignore[reportGeneralTypeIssues,reportUnknownVariableType,reportUnknownArgumentType]


@viewer_app.command("parts")
def viewer_parts(project: ProjectOpt = None) -> None:
    """List the open page's parts by dotted tree path."""
    answer = _ask(project, drive.get("parts"))
    _say(answer, *_page_parts(answer))


@viewer_app.command("state")
def viewer_state(project: ProjectOpt = None) -> None:
    """Print what the open page is showing, as JSON: the part last
    picked, the view (camera, toggles, hidden parts) and its panes."""
    answer = _ask(project, drive.get("picked", "view", "frame"))
    shown = {k: v for k, v in answer.result.items() if k != "target"}
    _say(answer, json.dumps(shown, indent=2))


@viewer_app.command("show")
def viewer_show(
    part: Annotated[
        str | None,
        typer.Argument(help="Select this part (its dotted tree path)."),
    ] = None,
    direction: Annotated[
        str | None,
        typer.Option(
            "--direction", help=f"Look from one of {', '.join(drive.DIRECTIONS)}."
        ),
    ] = None,
    only: Annotated[
        list[str] | None,
        typer.Option(
            "--only",
            help=(
                "Show only this part or sub-assembly path and everything "
                "under it, hiding the rest (repeatable)."
            ),
        ),
    ] = None,
    hide: Annotated[
        list[str] | None,
        typer.Option(
            "--hide",
            help=(
                "Hide this part or sub-assembly path and everything under "
                "it (repeatable; applied after --only). Whatever these two "
                "do not hide is shown."
            ),
        ),
    ] = None,
    everything: Annotated[
        bool, typer.Option("--all", help="Show every part, hiding none.")
    ] = False,
    ortho: Annotated[
        bool | None, typer.Option("--ortho/--perspective", help="Projection.")
    ] = None,
    transparent: Annotated[
        bool | None, typer.Option("--transparent/--opaque", help="Part faces.")
    ] = None,
    black_edges: Annotated[
        bool | None,
        typer.Option("--black-edges/--no-black-edges", help="Edge colour."),
    ] = None,
    axes: Annotated[
        bool | None, typer.Option("--axes/--no-axes", help="The axes triad.")
    ] = None,
    project: ProjectOpt = None,
) -> None:
    """Select a part on the open page, turn the view, hide parts, or
    set its toggles. The page does all of it or none: an unknown part
    or path changes nothing and exits nonzero."""
    selection = (tuple(only or ()), tuple(hide or ()))
    if everything and any(selection):
        typer.echo("error: --all hides nothing; give it or --only/--hide", err=True)
        raise typer.Exit(code=2)
    if direction is not None and direction not in drive.DIRECTIONS:
        typer.echo(
            f"error: no direction {direction!r}; one of {', '.join(drive.DIRECTIONS)}",
            err=True,
        )
        raise typer.Exit(code=2)
    try:
        hidden = (
            drive.hidden(_page_parts(_ask(project, drive.get("parts"))), *selection)
            if any(selection)
            else []
            if everything
            else None
        )
    except SelectionError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from None
    body = drive.show(
        part,
        direction=direction,
        hidden=hidden,
        ortho=ortho,
        transparent=transparent,
        blackEdges=black_edges,
        axes=axes,
    )
    if not body["show"]:
        typer.echo("error: nothing to show; name a part or give an option", err=True)
        raise typer.Exit(code=2)
    answer = _ask(project, body)
    _say(
        answer,
        *(() if hidden is None else (f"hidden: {len(hidden)} parts",)),
    )


@viewer_app.command("panes")
def viewer_panes(
    tree: Annotated[
        bool | None, typer.Option("--tree/--no-tree", help="The part tree.")
    ] = None,
    info: Annotated[
        bool | None, typer.Option("--info/--no-info", help="The info pane.")
    ] = None,
    toolbar: Annotated[
        bool | None, typer.Option("--toolbar/--no-toolbar", help="The toolbar.")
    ] = None,
    project: ProjectOpt = None,
) -> None:
    """Show or hide the open page's own panes and toolbar. One not
    named keeps its state."""
    body = drive.panes(tree, info, toolbar)
    if not body["set"]:
        typer.echo("error: name a pane: --tree, --info or --toolbar", err=True)
        raise typer.Exit(code=2)
    _say(_ask(project, body))


@app.command()
def status() -> None:
    """Print the environment as JSON; exit nonzero if degraded (no bun,
    so `khana view` cannot build its page)."""
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
        raise typer.Exit(code=2) from None
    typer.echo(text, nl=False)
    if text != NO_CHANGES:
        raise typer.Exit(code=1)


@app.command()
def show(
    path: DiagArg,
    grep: Annotated[
        str | None,
        typer.Option("--grep", help="Regex searched in each assertion's name."),
    ] = None,
    failed: Annotated[
        bool,
        typer.Option(
            "--failed", help="Only failed assertions (a waived failure is not one)."
        ),
    ] = False,
    skipped: Annotated[
        bool,
        typer.Option(
            "--skipped", help="Only skipped assertions; with --failed, either."
        ),
    ] = False,
    sort: Annotated[
        str | None,
        typer.Option("--sort", help="`value`: ascending value, valueless claims last."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            help="Lines to print (default 50; 0 for all). With --json, "
            "unlimited unless given.",
        ),
    ] = None,
    group: Annotated[
        str | None,
        typer.Option(
            "--group",
            help="Regex whose match (or first capture group) keys one line "
            "per group: count, failed, waived, skipped, least value and its claim.",
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json", help="Print the matching assertions (or groups) as JSON."
        ),
    ] = False,
) -> None:
    """Read a diagnostics JSON: a summary, then its assertions filtered.

    Exits 0 whatever the file says; 2 when it cannot be read as a
    diagnostics file or an option is malformed. A file at an older
    schema_version is read as written, and the summary says so.
    """
    if sort not in (None, "value"):
        typer.echo(f"error: unknown --sort {sort!r}; known: value", err=True)
        raise typer.Exit(code=2)
    states = frozenset(s for s, on in (("failed", failed), ("skipped", skipped)) if on)
    render = report_json if as_json else report
    try:
        diag = require_diagnostics(json.loads(path.read_text()))
        text = render(
            diag, grep=grep, states=states, sort=sort, limit=limit, group_by=group
        )
    except (ValueError, UnicodeDecodeError, re.error) as exc:
        typer.echo(f"error: {path}: {exc}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(text, nl=False)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
