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
        motion.py             # Motion: a schedule of poses, declared as data
        hold.py               # held evaluation: assertions over every motion
        sweep.py              # sampled-motion queries: sweep/classify/onset
        check.py              # check() orchestrator + CheckResult
      printability/
        methods.py            # FDM dataclass (up_axis, wall_min, overhang_max)
        wall.py               # min_wall()
        overhangs.py          # detect_overhang() — honors FDM.up_axis
        inspect.py            # inspect() orchestrator + PrintabilityDiagnostics
      core/
        tessellation.py       # shared mesh utilities (wall + overhangs)
      export.py               # STL, STEP (used by `khana export`)
      draw.py                 # HLR engineering drawings (PNG + SVG)
      viewer.py               # ocp_vscode push (used by `khana view`)
      diff.py                 # dispatches on file kind (mechanism/printability)
      target.py               # <module>[:<factory>] → Assembly (import-model verbs)
      cli.py                  # typer CLI — thin dispatcher
      # mcp.py                # future: MCP server over the same primitives
  tests/
    mechanism/                # per-module tests for mechanism.*
    printability/             # per-module tests for printability.*
    test_cli.py, test_diff.py, test_target.py  # cross-cutting tests
    test_docs.py              # SKILL.md schema facts derived from code
```

**Discipline:** the library modules (`mechanism/*`, `printability/*`) have
no CLI or MCP dependencies. `cli.py` imports from them. A future MCP layer
does the same. Never put logic in the CLI module that a different surface
would also need.

## Public API shape

The package has no `__init__.py` (PEP 420 namespace). User modules import
the public names directly from their submodules — no aliasing, no shim,
the structure speaks for itself.

A **declaration module** — what `khana check|export|view|draw` import.
Its public surface is its parameterized factories; it calls nothing
effectful.

```python
from build123d import *

from cad_khana.mechanism.assembly import Assembly


def housing() -> Part:
    with BuildPart() as p:
        Box(40, 30, 20)
    return p.part


def lever() -> Part:
    with BuildPart() as p:
        Box(25, 5, 3)
    return p.part


def build_mechanism(lift_mm: float = 12.0) -> Assembly:
    return (
        Assembly()
        .with_part("housing", housing(), location=Location((0, 0, 0)))
        .with_part("lever",   lever(),   location=Location((0, 0, lift_mm)))
        .assert_no_interference("lever", "housing")
        .assert_clearance("lever", "housing", min_mm=0.2)
    )


assembly = build_mechanism()   # degenerate form — a memoized master
```

A **command script** — what `khana run` executes. Orchestration only:
loops, batches, and the effectful calls the verbs don't cover.

```python
from cad_khana.printability.inspect import inspect
from cad_khana.printability.methods import FDM

from .assembly import housing, lever

inspect(housing(), method=FDM(), out="outputs/", name="housing")
inspect(lever(),   method=FDM(), out="outputs/", name="lever")
```

`check()` runs mechanism diagnostics, executes assertions, writes
`mechanism.json`, and exits nonzero if any assertion failed — it does
**not** export (`export_assembly` / `khana export` does). `inspect()`
does the same for one part and writes `<name>-printability.json`.

## CLI surface

Two kinds of command. **Import-model verbs** take a target —
`<module-path>[:<factory>]` — import the module, resolve one member,
and do one thing to it. **Execute-model** commands run a script for
effect.

```
khana check  <target>           # diagnostics + assertions, write mechanism.json
khana export <target>           # STL + STEP
khana view   <target>           # push to OCP viewer
khana draw   <target> --format png|svg|both   # orthographic/iso HLR line-art
khana run    <script>           # execute an orchestration script
khana diff <old> <new>          # diff two diagnostics JSON files
```

A target's member is the named factory called with its defaults, or —
with no `:factory` — the module's `assembly` name, called if callable
and accepted as a bare value otherwise (the degenerate, transitional
form). Anything else is a boundary error listing the module's public
`-> Assembly` factories. `--out` defaults to `<module-dir>/outputs` for
a unit's `assembly.py` and `<module-dir>/outputs/<stem>[-<factory>]`
for any other target, so co-located targets never overwrite each
other's `mechanism.json`.

Use `typer` for the CLI; resolution lives in `target.py`, not in the
CLI module. Every command exits nonzero on failure: **2** for a usage
error (unresolvable target, unknown `--view`) and **1** for a failed
run. Any command that imports or executes user code writes
`mechanism.json` (and `<name>-printability.json` per `inspect()` call)
even on failure, so the agent can always read structured error info.
`diff` follows the `diff`/`git diff` contract: exit 0 when the files
are equivalent, 1 when differences are found, 2 on error.

Declarations are imported by verbs; effects live at the CLI boundary.
A module the import-model verbs consume never calls `check()`,
`inspect()`, or an exporter — that is what `khana run` is for. The
full design, its phases, and what is still owed:
`_notes/draft-script-decomposition.md`.

## Diagnostics JSON schemas (v0.14)

Version these from day one. Agents depend on field stability.

**What each field means is written once, in `skills/cad-khana/SKILL.md`
§JSON diagnostics essentials** — the surface every consumer reads. This
section holds only the shapes and the maintainer's delta: the contract,
and why things are the way they are. `tests/test_docs.py` derives the
enumerable facts from the code — the schema version, every warning
kind, every skip class, which claim kinds carry `value` — and fails when
SKILL.md omits one. **A schema change edits SKILL.md and bumps
`SCHEMA_VERSION`**; restating a field meaning here is how the two drifted
for three bumps.

`mechanism.json` — written by `check()`:

```json
{
  "schema_version": "0.14",
  "status": "ok | error | assertion_failed",
  "error": null,
  "hint": "Missing .part accessor — use `with BuildPart() as p: ...; return p.part`.",
  "skipped_counts": {"absent_part": 0, "absent_joint": 0, "out_of_phase": 0},
  "motions": [
    {"name": "stack_turn", "samples": 180,
     "joints_deg": {"rotating": {"min": 0.0, "max": 358.0, "max_step": 2.0}},
     "moved": 28, "movable": 2082}
  ],
  "parts": {
    "<name>": {
      "bbox": {"min": [x,y,z], "max": [x,y,z]},
      "volume_mm3": 12403.2,
      "surface_area_mm2": 3210.5,
      "center_of_mass_mm": [x, y, z],
      "is_valid": true,
      "face_count": 6,
      "edge_count": 12,
      "vertex_count": 8,
      "solid_count": 1
    }
  },
  "interferences": [
    {"a": "lever", "b": "housing", "volume_mm3": 0.3, "centroid": [x,y,z]}
  ],
  "assertions": [
    {"name": "lever_clears_housing", "passed": true, "detail": null, "value": null, "waived": null, "skipped": null,
     "poses": {"evaluated": 181, "distinct": 46, "in_phase": 181, "failed": 0},
     "worst_at": {"motion": "stack_turn", "t": 0.0333, "joints_deg": {"rotating": 12.0}}}
  ],
  "warnings": [
    {"kind": "joint_never_driven", "joint": "rotor"},
    {"kind": "never_in_phase", "assertion": "pad_engages"},
    {"kind": "motion_moved_nothing", "motion": "lift", "moved": 0, "movable": 2082},
    {"kind": "interferences_rest_pose_only"},
    {"kind": "multi_solid", "part": "glow_band", "solid_count": 5}
  ]
}
```

Maintainer facts behind those fields:

- **Held evaluation** (`mechanism/hold.py`) holds every assertion at the
  as-built pose and at each sample of each declared motion, each motion
  on its own. Reuse across poses is exact, not heuristic: it keys on the
  composed relative placement of a claim's parts (absolute for a datum
  plane or `along`) plus its phase state, so a window on a joint that
  moves neither part is still re-resolved. It is sampled and claims no
  bound between samples. Printability assertions share the
  `AssertionResult` dataclass and always carry `skipped`, `poses` and
  `worst_at` as `null`.
- **`during=` and held evaluation ship together**: held evaluation
  without phases would silently widen every rest-only claim to the whole
  motion. A requirement lapses outside its phase; a permission lapses to
  the default it was an exception to. Windows are joint angles, not `t`,
  and are derived via `mechanism.sweep`, never guessed.
- **`motions[].moved` warns on zero and only on zero.** Any threshold
  between "some" and "not enough" is the magnitude filter the
  false-green rule forbids; the count is what answers "enough".
  `movable` excludes the pose-invariant kinds (`_pose_invariant` is the
  one predicate, also used by `_geometry`) and absent-skipped claims.
  `moved` keeps skipped visits where `poses.distinct` drops them — that
  is what makes a `during=` crossing count, and why `moved` can exceed
  the number of claims reading `distinct > 1`. `check()` prints one
  stderr line per declared motion; `khana diff` reports a changed
  `moved`.
- **Connectivity**: `multi_solid` is a warning, not a failure, because a
  part can be several solids on purpose — `assert_solid_count` /
  `inspect(..., solid_count=N)` both bound and declare, and always take
  the number, never a bare suppression. The printability form exists
  because that file's `warnings[]` holds `stale_waiver`, and a warning
  nobody can answer trains readers to skim the block that must not be
  skimmed.
- **`detail` on a pass carries labels, never failure hypotheses.**
  `assert_scalar`'s `detail=` and a contact claim's `reason=`
  (`assert_allowed_contact`, `assert_interference`, `known_overlaps`)
  are true whether the claim holds, so they show on a pass (0.14 for
  `reason`, after a consumer misread a green file's overlap with no
  explanation anywhere in it). `assert_solid_count`'s `detail=` is
  failure-only: on a green `eq=2` it would read as a report of the
  failure it is green about.
- `mechanism/sweep.py` is pure and sampled — an inner approximation
  (`never` means "at none of the sampled parameters"). Its primitive is
  a `factory(t) -> Assembly` because real motion drives several joints
  from non-linear schedules. Sweeps derive a claim; assertions hold it.
- Sub-assembly assertions and motions qualify into every composing root
  (`Assembly.all_assertions`, `Assembly.all_motions`).
- Bound comparisons carry `BOUND_EPSILON` (1e-6 in the bound's units):
  consumers derive geometry from the constant they bound against, so
  exact comparison flips on solver noise.

`<name>-printability.json` — written by each `inspect()`:

```json
{
  "schema_version": "0.14",
  "kind": "printability",
  "status": "ok | assertion_failed",
  "name": "housing",
  "method": "FDM",
  "bbox": {"min": [x,y,z], "max": [x,y,z]},
  "volume_mm3": 12403.2,
  "surface_area_mm2": 3210.5,
  "center_of_mass_mm": [x, y, z],
  "is_valid": true,
  "solid_count": 1,
  "min_wall_mm": 1.8,
  "min_wall_at": [x, y, z],
  "min_wall_alignment": 1.0,
  "overhang": {"area_mm2": 42.1, "max_angle_deg": 58},
  "assertions": [
    {"name": "wall_min:1.5", "passed": false, "detail": "min wall 0.31mm below min 1.5mm at (x, y, z), alignment 0.24 — the faces splay apart here, so this is the tip of a wedge feature rather than a wall between parallel faces", "waived": "knife-edge runout at the star ridge, alignment 0.24"}
  ],
  "warnings": [
    {"kind": "waived_failure", "assertion": "wall_min:1.5", "reason": "knife-edge runout at the star ridge, alignment 0.24", "detail": "min wall 0.31mm below min 1.5mm at (x, y, z), alignment 0.24 — ..."},
    {"kind": "multi_solid", "part": "housing", "solid_count": 2}
  ]
}
```

Wall thickness is measured by pairing a ray's **entry** into material
with its next **exit**, so a reading always spans material actually
traversed. This matters because a tessellation facet centroid sags into
the void by up to the tessellation tolerance on curved faces: a ray
started there re-hits the surface it came from, which is what produced
the sub-0.2 mm readings on large-radius annuli that consumers had been
waiving as "ray-sampling artifacts". Each ray contributes exactly one
sample — the span through the facet it was cast for, which it meets
perpendicular by construction. Later spans along the same ray are
chords through *unrelated* features at oblique angles, so a grazed
corner reads arbitrarily thin; those features are measured properly by
rays cast from their own facets, so dropping the chords costs no
coverage. One place has no facet of its own: a sharp concave edge or
point (a V-groove root, a conical pocket's apex), where no facet faces
the thin direction and the flat face opposite has no centroid beneath
it. Those creases are found in the mesh and cast a fan of rays between
their two facets' inward normals, at the angular tolerance — what a
fillet there would have cast, in the limit of zero radius. It is a
sampling change, not a filter: it can only add readings. A crease ray has
no entry face, so it does not meet perpendicular; its alignment still
reads like a facet ray's, because the fan's shortest span meets the face
opposite most squarely. Rays are rejected only on geometric grounds — **never** by
magnitude, and there is no quantile or robustness statistic, because
hiding a genuine thin region is a worse failure than reporting a wedge
tip.

Waivers are keyed by assertion **kind** (the part before the `:`), so
thresholds stay honest and a waiver survives a threshold change; a
waived failure keeps `passed: false` — the measurement is what it is.
**A threshold decides `passed` and what area counts, never whether the
reading exists** (0.14): `overhang.max_angle_deg` is reported whatever
`overhang_max_deg` says, because consumers raised it to 90° to keep the
check "informational" and it erased the measurement instead.

Diagnostic JSONs are **ephemeral**: rewritten in full on every
`check()` / `inspect()` run. `khana diff` requires both inputs at the
current `schema_version` and raises on mismatch — regenerate the
files by re-running the script. No back-compat coercion lives in the
codebase. Schema bumps are therefore free, and the rule's scope
is exactly these two files: it does **not** extend to exported
`.stl` / `.step` / `.glb`, which a user may keep, nor to anything
serialized for cross-session resumption (there is none today).

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
  `mechanism.check`, `printability.inspect`, and the CLI. Each verb
  performs its own effect at the boundary — `view` pushes, `draw`
  draws, `export` exports — so a declaration module is identical under
  all of them. `check()` writes `mechanism.json` and nothing else: no
  export, no viewer push, no draw, and no toggle to re-couple them.
- **Error handling at the boundary.** Uncaught exceptions from user
  scripts and from imported modules/factories are caught at the CLI and
  written to `mechanism.json` with `status: "error"` and the traceback
  in `error`. Never crash without leaving a diagnostic behind. A target
  that names no resolvable member is the one exception: it is a usage
  error (exit 2, no JSON), because nothing ran. Inside the library,
  trust inputs — no defensive checks.
- **Assertions collect, don't short-circuit.** Evaluate every assertion
  and record all results; the agent wants every failure at once. This
  holds *across* calls too: under the CLI, a failing `check()`/`inspect()`
  records the failure and returns, the script runs to completion so every
  diagnostics JSON on disk is current, and `cli._run_script` rolls the
  failures up and exits nonzero once. Deferral is a boundary decision
  (`_failures`), never the library's — outside the CLI these still raise
  on the first failure, because nothing else is positioned to exit
  nonzero afterwards and a silent green run is the worse failure.
  `atexit` cannot do it: a `SystemExit` raised from an exit handler is
  reported as "Exception ignored" and the process still exits 0.

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

