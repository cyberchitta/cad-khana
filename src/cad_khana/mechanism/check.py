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
    compute,
    multi_solid_warnings,
    skipped_counts,
)
from cad_khana.mechanism.hold import hold


@dataclass(frozen=True)
class CheckResult:
    diagnostics: Diagnostics


def check(assembly: Assembly, out: str | Path = "outputs") -> CheckResult:
    """Compute diagnostics, hold every assertion over every declared
    motion, write ``mechanism.json``.

    Part diagnostics and ``interferences[]`` describe the as-built pose
    only; assertions are held at it and at each motion sample
    (``hold``). Warnings never fail a run.

    Diagnostics only. Each other verb performs its own effect at the CLI
    boundary — ``khana export`` (``export_assembly``), ``khana view``
    (``viewer.push``), ``khana draw`` (``draw.draw``) — so a declaration
    module is identical under all of them.
    """
    out_path = resolve_out(out)
    out_path.mkdir(parents=True, exist_ok=True)
    held = hold(assembly)
    assertion_results = held.assertions
    failed = any(a.passed is False for a in assertion_results)
    computed = compute(assembly)
    warnings = held.warnings + multi_solid_warnings(
        computed.parts, solid_count_claimed(assembly.all_assertions)
    )
    diagnostics = replace(
        computed,
        assertions=assertion_results,
        skipped_counts=skipped_counts(assertion_results),
        motions=held.motions,
        warnings=warnings,
        status="assertion_failed" if failed else "ok",
    )
    json_path = out_path / "mechanism.json"
    json_path.write_text(json.dumps(asdict(diagnostics), indent=2) + "\n")
    if warnings:
        kinds = Counter(w["kind"] for w in warnings)
        summary = ", ".join(f"{n} {kind}" for kind, n in kinds.items())
        print(f"warnings: {summary} — see {json_path}", file=sys.stderr)
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
