from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from cad_khana import _failures
from cad_khana._paths import resolve_out
from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.assertions import solid_count_claimed
from cad_khana.mechanism.diagnostics import (
    Diagnostics,
    Selection,
    Warning,
    compute,
    multi_solid_warnings,
    not_solid_warnings,
    skipped_counts,
)
from cad_khana.mechanism.hold import hold


@dataclass(frozen=True)
class CheckResult:
    diagnostics: Diagnostics


def _partial(
    only: tuple[str, ...], declared: int, evaluated: int
) -> tuple[Selection | None, tuple[Warning, ...]]:
    """A partial run's record: the selection field, and the warning that
    puts it where a green is read."""
    return (
        (None, ())
        if not only
        else (
            Selection(only=only, declared=declared, evaluated=evaluated),
            ({"kind": "partial_run", "evaluated": evaluated, "declared": declared},),
        )
    )


def check(
    assembly: Assembly,
    out: str | Path = "outputs",
    only: tuple[str, ...] = (),
) -> CheckResult:
    """Compute diagnostics, hold every assertion over every declared
    motion, write ``mechanism.json``.

    With ``only`` (name globs; each must match an assertion, or
    ``SelectionError`` is raised before anything is written) it is a
    **partial run**: only the matching assertions are held, the
    all-pairs interference pass is skipped (``interferences: null``),
    and the file records the selection and a ``partial_run`` warning,
    so the result cannot be read as the whole model's.

    Part diagnostics and ``interferences[]`` describe the as-built pose
    only; assertions are held at it and at each motion sample
    (``hold``). Warnings never fail a run.

    Diagnostics only. Each other verb performs its own effect at the CLI
    boundary — ``khana export`` (``export_assembly``), ``khana view``
    (``viewer.push``), ``khana draw`` (``draw.draw``) — so a declaration
    module is identical under all of them.
    """
    held = hold(assembly, only)
    out_path = resolve_out(out)
    out_path.mkdir(parents=True, exist_ok=True)
    assertion_results = held.assertions
    failed = any(a.passed is False for a in assertion_results)
    computed = compute(assembly, pairs=not only)
    selection, partial = _partial(only, held.declared, len(assertion_results))
    # The rest-pose caveat is about ``interferences[]``; a partial run
    # left that field null, so the caveat would describe nothing.
    held_warnings = tuple(
        w
        for w in held.warnings
        if not (only and w["kind"] == "interferences_rest_pose_only")
    )
    claimed = solid_count_claimed(assembly.all_assertions)
    warnings = (
        partial
        + held_warnings
        + multi_solid_warnings(computed.parts, claimed)
        + not_solid_warnings(computed.parts, claimed)
    )
    diagnostics = replace(
        computed,
        selection=selection,
        assertions=assertion_results,
        skipped_counts=skipped_counts(assertion_results),
        motions=held.motions,
        warnings=warnings,
        status="assertion_failed" if failed else "ok",
    )
    json_path = out_path / "mechanism.json"
    json_path.write_text(json.dumps(asdict(diagnostics), indent=2) + "\n")
    # The failure path already says "failed at 8 of 181 poses"; a green
    # under a motion said nothing at all, so a motion that tested
    # nothing read exactly like one that tested everything.
    for m in held.motions:
        print(
            f"{m.name}: {m.samples} poses, moved {m.moved} of {m.movable} claims",
            file=sys.stderr,
        )
    if warnings:
        kinds = Counter(w["kind"] for w in warnings)
        summary = ", ".join(f"{n} {kind}" for kind, n in kinds.items())
        print(f"warnings: {summary} — see {json_path}", file=sys.stderr)
    if selection is not None:
        print(
            f"partial run: {selection.evaluated} of {selection.declared} "
            f"assertions (only {', '.join(only)}); interferences not "
            "computed — not a whole-model result",
            file=sys.stderr,
        )
    if failed:
        for a in assertion_results:
            if a.passed is False:
                print(
                    f"assertion failed: {a.name} — {a.detail}",
                    file=sys.stderr,
                )
        print(f"see {json_path}", file=sys.stderr)
        _failures.fail(_failures.Failure("mechanism", json_path))
    return CheckResult(diagnostics=diagnostics)
