from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from cad_khana import _failures
from cad_khana._paths import resolve_out
from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.assertions import evaluate as evaluate_assertions
from cad_khana.mechanism.diagnostics import Diagnostics, compute


@dataclass(frozen=True)
class CheckResult:
    diagnostics: Diagnostics


def check(assembly: Assembly, out: str | Path = "outputs") -> CheckResult:
    """Compute diagnostics, evaluate every assertion, write ``mechanism.json``.

    Diagnostics only. Each other verb performs its own effect at the CLI
    boundary — ``khana export`` (``export_assembly``), ``khana view``
    (``viewer.push``), ``khana draw`` (``draw.draw``) — so a declaration
    module is identical under all of them.
    """
    out_path = resolve_out(out)
    out_path.mkdir(parents=True, exist_ok=True)
    assertion_results = evaluate_assertions(assembly)
    failed = any(a.passed is False for a in assertion_results)
    diagnostics = replace(
        compute(assembly),
        assertions=assertion_results,
        status="assertion_failed" if failed else "ok",
    )
    json_path = out_path / "mechanism.json"
    json_path.write_text(json.dumps(asdict(diagnostics), indent=2) + "\n")
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
