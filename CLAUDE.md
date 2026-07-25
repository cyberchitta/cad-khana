# CLAUDE.md — cad-khana

You are building `cad-khana`, a CLI tool and agent skill for designing 3D-printable
mechanisms in Build123d. This file is the working context for the project.

## What this tool is

`cad-khana` wraps Build123d with a diagnostics-first workflow designed for LLM
agents. An agent (you, or another instance) writes Python scripts that declare
parts and assemblies using the `cad_khana` library, runs them via the `khana`
CLI, and reads structured JSON diagnostics to iterate until the design is clean.

The core insight: LLMs can reason about CAD geometry from code, but need
explicit feedback on the things a human would catch visually. The tool
provides that through two channels:

1. **Computed diagnostics** — interferences, clearances, wall thickness,
   overhangs — returned as structured JSON the agent reads after every
   build. Cheap, scalar, and the primary iteration signal.
2. **Engineering drawings** — orthographic and isometric HLR line-art
   PNGs (and optional SVG) produced by `khana draw` on demand.
   Multimodal harnesses feed these back to the model for shape-level
   questions that scalars express poorly ("is the tang pointing the
   right way", "did that cut land where I expected").

Assertions make geometric constraints first-class: a failed assertion is
a build failure, not a silent geometry bug.

Humans view live geometry via the OCP CAD Viewer VS Code extension. The
rendered PNGs are primarily for the agent; the viewer is primarily for
humans.

## Non-goals

- Not a constraint solver. Relationships are declared via assertions, not
  maintained by a solver. Keep it simple.
- Not a replacement for Build123d. `cad_khana` is a thin library on top.
  Users drop into raw Build123d for anything the library doesn't cover.
- Not an MCP server in v0. CLI only. MCP may come later; structure code so
  it's possible without rewrites.
- Not a GUI. The VS Code extension is a human convenience, documented in the
  README. The tool doesn't manage or depend on it at runtime beyond the
  `ocp_vscode` Python client library.
- Not a style enforcer for user scripts. The library accepts any Build123d
  `Part`. Recommended style for user-authored scripts (functional patterns,
  pure part functions, declarative assemblies) is a SKILL.md concern, not a
  runtime constraint.

## Demand-driven development

cad-khana changes only when a live consumer need drives it. Today the
consumer is **sorted-studs**; that grounding is what keeps the library
honest.

- **A feature starts from an observed need** — a field-note, an
  adoption-inventory row, or a bug — never from the idea backlog
  alone. Survey-sourced rows in `_notes/research/ideas.md` are
  accepted *in intent* and wait for a driver to surface in the
  consumer (geometric diff is the standing example: Impact H, parked
  until a sorted-studs driver appears).
- **Discovery is a demand-side sweep, not brainstorming.** When
  sequencing is unclear, sweep sorted-studs' `cad/` for sites where a
  putative feature would fit — existing workarounds mapped to the
  call shape the consumer wishes it could write. The pattern is
  `_notes/adoption-inventory.md` (2026-07-24): each mapped site
  doubles as the feature's ready-made exercise slice.
- **The exercise slice closes the loop.** A feature's row closes only
  when its consumer sites are actually converted in sorted-studs —
  code shipped here is "done" only after real use over there.
- **Bugs are exempt** — fix immediately (see the promotion policy's
  bug exception). The gate shapes features and defaults, never delays
  fixes.

## Architecture

```
cad-khana/
  README.md                   # human-facing install + viewer setup
  CLAUDE.md                   # this file
  _notes/                     # working notes, gitignored — see below
  pyproject.toml              # uv-managed, entry point: khana = cad_khana.cli:main
  skills/
    cad-khana/
      SKILL.md                # agent-facing instructions for using the tool
      references/
        install.md            # one-shot install steps, linked from SKILL.md
        printability.md       # design rules baked into printability checks
        standard_parts.md     # bd_warehouse contents and discovery
        examples/
          pin_hinge/          # canonical reference project (clevis-tang-pin)
  src/
    cad_khana/                # PEP 420 namespace package, no __init__.py
      mechanism/
        assembly.py           # Assembly class: named parts + locations
        assertions.py         # NoInterference, Clearance + evaluate()
        diagnostics.py        # bbox, volume, interferences
        check.py              # check() orchestrator + CheckResult
      printability/
        methods.py            # FDM dataclass (up_axis, wall_min, overhang_max)
        wall.py               # min_wall()
        overhangs.py          # detect_overhang() — honors FDM.up_axis
        inspect.py            # inspect() orchestrator + PrintabilityDiagnostics
      core/
        tessellation.py       # shared mesh utilities (wall + overhangs)
      export.py               # STL, STEP (used by mechanism check)
      draw.py                 # HLR engineering drawings (PNG + SVG)
      viewer.py               # ocp_vscode push (used by `khana view`)
      diff.py                 # dispatches on file kind (mechanism/printability)
      cli.py                  # typer CLI — thin dispatcher
      # mcp.py                # future: MCP server over the same primitives
  tests/
    mechanism/                # per-module tests for mechanism.*
    printability/             # per-module tests for printability.*
    test_cli.py, test_diff.py # cross-cutting tests
```

**Discipline:** the library modules (`mechanism/*`, `printability/*`) have
no CLI or MCP dependencies. `cli.py` imports from them. A future MCP layer
does the same. Never put logic in the CLI module that a different surface
would also need.

## Public API shape

The package has no `__init__.py` (PEP 420 namespace). User scripts import
the public names directly from their submodules — no aliasing, no shim,
the structure speaks for itself.

```python
from build123d import *

from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.check import check
from cad_khana.printability.inspect import inspect
from cad_khana.printability.methods import FDM


def housing():
    with BuildPart() as p:
        Box(40, 30, 20)
    return p.part


def lever():
    with BuildPart() as p:
        Box(25, 5, 3)
    return p.part


assembly = (
    Assembly()
    .add("housing", housing(), location=Location((0, 0, 0)))
    .add("lever",   lever(),   location=Location((0, 0, 12)))
    .assert_no_interference("lever", "housing")
    .assert_clearance("lever", "housing", min_mm=0.2)
)

check(assembly, out="outputs/")
inspect(housing(), method=FDM(), out="outputs/", name="housing")
inspect(lever(),   method=FDM(), out="outputs/", name="lever")
```

`check()` runs mechanism diagnostics, executes assertions, writes exports
and `mechanism.json`, and exits nonzero if any assertion failed.
`inspect()` does the same for one part and writes
`<name>-printability.json`.

## CLI surface

```
khana build <path>              # run script, export, write diagnostics JSON
khana check <path>              # diagnostics only, no export
khana view <path>               # build + push to OCP viewer
khana draw <path> --format png|svg|both     # orthographic/iso engineering drawings (HLR line-art)
khana diff <old> <new>          # diff two diagnostics JSON files
```

Use `typer` for the CLI. Every command exits nonzero on failure. `diff`
follows the `diff`/`git diff` contract: exit 0 when the files are
equivalent, 1 when differences are found, 2 on error. `build` and
`check` always write `mechanism.json` (and `<name>-printability.json` per
`inspect()` call) even on failure, so the agent can always read structured
error info.

## Diagnostics JSON schemas (v0.7)

Version these from day one. Agents depend on field stability.

`mechanism.json` — written by `check()`:

```json
{
  "schema_version": "0.7",
  "status": "ok | error | assertion_failed",
  "error": null,
  "hint": "Missing .part accessor — use `with BuildPart() as p: ...; return p.part`.",
  "parts": {
    "<name>": {
      "bbox": {"min": [x,y,z], "max": [x,y,z]},
      "volume_mm3": 12403.2,
      "surface_area_mm2": 3210.5,
      "center_of_mass_mm": [x, y, z],
      "is_valid": true,
      "face_count": 6,
      "edge_count": 12,
      "vertex_count": 8
    }
  },
  "interferences": [
    {"a": "lever", "b": "housing", "volume_mm3": 0.3, "centroid": [x,y,z]}
  ],
  "assertions": [
    {"name": "lever_clears_housing", "passed": true, "detail": null, "value": null, "waived": null}
  ],
  "exports": ["outputs/assembly.stl", "outputs/assembly.step"]
}
```

`assertions[].passed` is tri-state: `true`/`false` for an evaluated
assertion, `null` when it was skipped because a referenced part is
absent from the run (`detail` names the missing parts — the standalone
sub-assembly case, where detail-override parts aren't applied). Skipped
assertions never set `status: "assertion_failed"`.

`assertions[].value` carries the measured/claimed scalar for
value-carrying assertions (`assert_distance`, `assert_scalar`,
`assert_tangent_contact` gap in mm, `assert_allowed_contact` overlap
in mm³) even on pass — `khana diff` reports drift the boolean can't
see — and is `null` for the boolean-only kinds.

Sub-assembly assertion lists propagate: a composed parent evaluates
every nested assertion with part/anchor paths, names, and datum-plane
targets qualified into its frame (`Assembly.all_assertions`), so a
unit declares each claim once at the level that owns the knowledge.

Assertion bound comparisons carry a small absolute tolerance
(`BOUND_EPSILON`, 1e-6 in the bound's units): consumers routinely
derive geometry from the same constant they bound against, so exact
comparison flips on solver noise.

`<name>-printability.json` — written by each `inspect()`:

```json
{
  "schema_version": "0.7",
  "kind": "printability",
  "status": "ok | assertion_failed",
  "name": "housing",
  "method": "FDM",
  "bbox": {"min": [x,y,z], "max": [x,y,z]},
  "volume_mm3": 12403.2,
  "surface_area_mm2": 3210.5,
  "center_of_mass_mm": [x, y, z],
  "is_valid": true,
  "min_wall_mm": 1.8,
  "min_wall_at": [x, y, z],
  "overhang": {"area_mm2": 42.1, "max_angle_deg": 58},
  "assertions": [
    {"name": "wall_min:1.5", "passed": false, "detail": "min wall 0.17mm below min 1.5mm at (x, y, z)", "waived": "ray-sampling artifact at thin annulus edges"}
  ],
  "warnings": [
    {"kind": "waived_failure", "assertion": "wall_min:1.5", "reason": "ray-sampling artifact at thin annulus edges", "detail": "min wall 0.17mm below min 1.5mm at (x, y, z)"}
  ]
}
```

Waivers: `inspect(..., waive={"wall_min": "reason", "overhang_max":
"reason"})`, keyed by assertion **kind** (the part before the `:`), so
thresholds stay honest and waivers survive threshold changes. A waived
failure keeps `passed: false` (the measurement is what it is), records
the rationale in `waived`, lands in `warnings[]` as a
`waived_failure`, and doesn't fail the run. A waiver whose assertion
passes becomes a `stale_waiver` warning; an unknown waive key raises.

Diagnostic JSONs are **ephemeral**: rewritten in full on every
`check()` / `inspect()` run. `khana diff` requires both inputs at the
current `schema_version` and raises on mismatch — regenerate the
files by re-running the script. No back-compat coercion lives in the
codebase.

`kind` is absent on mechanism files and `"printability"` on printability
files — that's how `diff` disambiguates.

Field naming convention: boolean fields are `passed` (not `status`, not `ok`).
Units are always in the field name (`_mm`, `_mm3`, `_deg`). No ambiguity.

## Code style

Follow these rigorously. They apply to every code change inside the `cad_khana`
library and CLI.

### Universal principles

- **Functional first.** Prefer pure functions and immutable data. Design for
  method chaining through immutable transformations. Prefer conditional
  expressions over statements when possible.
- **Self-documenting code.** Good names make comments superfluous. Compose
  complex operations from small, focused functions.
- **Object design.** Keep `__init__` trivial. Use `@staticmethod create()` for
  complex construction. Methods return new instances rather than mutating.
  Default to frozen dataclasses.
- **Error handling — natural failure over validation.** Validate only at
  application boundaries (CLI input, user scripts, external data). Internal
  functions assume valid inputs and fail fast via built-in mechanisms
  (TypeError, KeyError, etc.). No defensive checks in core logic.
- **Composition over inheritance.** No static dependencies — inject for
  testability. Separate pure logic from side effects; keep side effects at
  the edges.

### Python specifics

- **Pythonic patterns.** Comprehensions over loops. Single-pass operations
  (`sum(x for x in items if cond)`, not filter-then-sum). Tuple unpacking.
  Conditional expressions for simple branches.
- **Type system.** Comprehensive type hints. Specific types: `list[str]`,
  `dict[str, int]`. Avoid `Any`.
- **Classes.** `@dataclass(frozen=True)` by default. `@property` for computed
  attributes. `@staticmethod create()` for non-trivial construction.
- **Imports.** Always at module top. Order: stdlib, third-party, local. No
  function-level imports except documented lazy-loading (none expected here).
- **Idioms.** `isinstance()` for type checks. `enumerate()` and `zip()` for
  iteration. Context managers for resources. `pathlib.Path` over string paths.

### Pre-flight checklist (run mentally before every code change)

1. Are functions pure? Do they return new data instead of mutating?
2. Are names concise but expressive? Avoid verbose parameters (`threshold`,
   not `coverage_threshold`).
3. Are data structures immutable? Can operations chain?
4. Can this be written more elegantly with comprehensions or functional
   patterns?
5. Are all parameters and returns typed?

**Red flags:** functions that mutate inputs, verbose parameter names,
imperative loops where comprehensions fit, missing or vague type hints,
nested conditionals where guard clauses would work, defensive validation
inside internal functions.

When in doubt, prefer elegance and functional patterns over apparent
convenience.

## Key dependencies

- `build123d` — CAD kernel (wraps OCCT)
- `bd_warehouse` — Build123d-native parametric standard parts (fasteners,
  bearings, threads, gears, V-slot extrusions, etc.). Bundled by default
  so user scripts can import standard hardware without setup. The library
  itself does not import it; user scripts do.
- `ocp_vscode` — viewer client (Python side only; VS Code extension is a
  human prerequisite, documented separately)
- `pygltflib` — JSON-level glTF read/write. Used by
  `export.py::export_animated_glb` to inject animation samplers onto
  an existing GLB.
- `typer` — CLI

External CLI tool (not a Python dep — shelled out to from
`export.py`):

- `gltf-transform` (`bun install -g @gltf-transform/cli`) — used for
  `join` (mandatory primitive-merging post-pass) and `draco`
  (optional mesh compression). The join pass collapses the
  per-face-style primitive explosion OCP's `RWGltf_CafWriter` writes
  (~30 primitives per shape), which dominates glTF JSON size.
  Together: typical ~10× shrink. No Python equivalent for the join
  pass exists; we'd have to write it ourselves (~100 lines on
  pygltflib) to drop this dep.

Diagnostics use plain `@dataclass(frozen=True)` + `dataclasses.asdict()` +
stdlib `json` for serialization. Don't reach for pydantic unless we actually
need to parse incoming JSON (e.g., `khana diff` reading prior runs).

Install via `uv`. Project uses `uv sync` for dev, `uv tool install cad-khana`
for end-user install, `uvx khana ...` for ephemeral use.

## Invariants

- **Side effect isolation.** `mechanism.diagnostics`, `mechanism.assertions`,
  `printability.wall`, `printability.overhangs`, and `diff.py` are pure —
  take data, return data. File I/O lives in `export.py`, `draw.py`,
  `mechanism.check`, `printability.inspect`, and the CLI. Viewer and draw
  pushes are gated on module-level toggles set by the CLI command, so user
  scripts stay identical across `build`/`view`/`draw`/`check`.
- **Error handling at the boundary.** Uncaught exceptions from user
  scripts are caught at the CLI and written to `mechanism.json` with
  `status: "error"` and the traceback in `error`. Never crash without
  leaving a diagnostic behind. Inside the library, trust inputs — no
  defensive checks.
- **Assertions collect, don't short-circuit.** Evaluate every assertion
  and record all results; the agent wants every failure at once.

## References

- Build123d docs: https://build123d.readthedocs.io/
- PartCAD: https://partcad.readthedocs.io/ — adjacent project, good for
  importable parts later.
- CIP paper (Aug 2025, arxiv.org/html/2508.01031v1) — prior art validating
  structured diagnostics for LLM-driven CAD. Worth reading before iterating
  on the diagnostics layer.

## What not to do

- Don't invent semantic primitives (Shaft, Gear, Bearing) in v0. Wait until
  real usage surfaces the patterns. Build123d primitives + named assembly
  parts are enough to start.
- Don't build a constraint solver.
- Don't add a web UI or a chat interface.
- Don't make `core/` depend on `typer` or any CLI framework.
- Don't enforce user-script style in the library API. Functional patterns
  for user scripts are a SKILL.md recommendation, not a runtime constraint.
  `Assembly` accepts any Build123d `Part` regardless of how it was built.
- Don't mutate inputs to functions. Return new values.
- Don't add defensive validation inside `core/`. Validate at the CLI boundary
  and trust internal callers.
- Don't add dependencies casually. Every dep is a support burden.
- Don't reproduce copyrighted code from other projects. Write originals.

## Working notes (gitignored)

Tracked separately in the private `working-notes` repo, symlinked at `_notes/`;
invisible to the `Grep`/`Glob` tools (global `CLAUDE.md` has the `rg` forms).
Read directly when relevant:

- `_notes/NOTES.md` — design rationale, open questions, history
- `_notes/worklist.md` — the continuing-state file: feature-program
  sequencing and status (implementation driven in tandem with sorted-studs)
- `_notes/field-notes.md` — real-use friction from consumer sessions
- `_notes/implementation-log.md` — session log
- `_notes/research/ideas.md` — prioritized idea backlog from the ~30-repo survey
- `_notes/research/repos/` — per-repo survey notes

Speculative unless stated otherwise. Do not implement from these without asking.

## Field-notes promotion policy

`_notes/field-notes.md` (gitignored) collects real-use friction
from consumer sessions — anything an agent flagged as awkward, buggy,
missing, or surprising while using cad-khana. The SKILL.md "Feedback"
section tells consumers to log freely without self-filtering, so
expect entries to be a mix of one-off project quirks, half-formed
observations, and genuine patterns. Triage it when working in this
repo.

The promotion mechanism — the 2–3-occurrence threshold and its
rationale, the bug exception, field-note resonance with surveyed ideas,
delete-on-promotion — is the global `repo-research` skill; load it when
triaging. What is cad-khana-specific is where a promoted fix lands:

- `src/cad_khana/mechanism/` — Assembly API, assertion semantics, or
  diagnostics fields (new assertion type, new `mechanism.json` field,
  changed default tolerance).
- `src/cad_khana/printability/` — `FDM` defaults, new method dataclass,
  wall/overhang algorithm tweaks, new printability assertion.
- `src/cad_khana/core/` — shared tessellation tolerances or mesh
  utilities used by both wall and overhang checks.
- `src/cad_khana/draw.py` — default views, projection style, framing
  heuristics for hidden-line PNGs/SVGs.
- `src/cad_khana/cli.py` — flag changes, default `--out` resolution,
  or new subcommands. Keep logic in the library; the CLI stays a thin
  dispatcher.
- `skills/cad-khana/SKILL.md` body — conventions consumers should
  follow when authoring scripts (parameter layout, naming, coordinate
  frames, multi-sub-assembly composition).
- `_notes/NOTES.md` — design rationale (why a default exists, a trade-off
  taken, an open question).
- `_notes/research/ideas.md` — the prioritized idea backlog distilled from
  the ~30-repo survey. When a field-note **resonates with an idea
  already mined from another repo**, that's where it lands: add or
  bump the matching row and set its `FN:` link — resonance can promote
  ahead of the threshold (e.g. the kinematic
  `sweep`/`onset`/`inspect-placed` cluster resonates with hedless's
  interference `suggested_fix` and faust-machines's per-mutation deltas).

