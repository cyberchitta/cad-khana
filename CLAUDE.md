# CLAUDE.md — cad-khana

You are building `cad-khana`, a CLI tool and agent skill for designing 3D-printable
mechanisms in Build123d. This file is the working context for the project.

## What this tool is

`cad-khana` wraps Build123d with a diagnostics-first workflow designed for LLM
agents. An agent (you, or another instance) writes Python scripts that declare
parts and assemblies using the `cad_khana` library, runs them via the `khana`
CLI, and reads structured JSON diagnostics to iterate until the design is clean.

The core insight: LLMs can reason about CAD geometry from code, but can't see
rendered output. So the tool closes that gap with computed diagnostics —
interferences, clearances, wall thickness, overhangs — returned as structured
JSON the agent reads after every build. Assertions make geometric constraints
first-class: a failed assertion is a build failure, not a silent geometry bug.

Humans view the geometry via the OCP CAD Viewer VS Code extension. The agent
never needs to see renders; diagnostics are sufficient for correctness, humans
are sufficient for taste.

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

## Architecture

```
cad-khana/
  SKILL.md                    # agent-facing instructions for using the tool
  README.md                   # human-facing install + viewer setup
  CLAUDE.md                   # this file
  NOTES.md                    # design rationale, open questions, history
  pyproject.toml              # uv-managed, entry point: khana = cad_khana.cli:main
  src/
    cad_khana/                # PEP 420 namespace package, no __init__.py
      core/
        assembly.py           # Assembly class: named parts + locations
        build.py              # build() orchestrator + BuildResult
        diagnostics.py        # interference, wall thickness, overhangs
        assertions.py         # assertion primitives + results collection
        export.py             # STL, STEP, 3MF
        viewer.py             # ocp_vscode push (only used by `khana view`)
      cli.py                  # typer CLI — thin dispatcher over core
      # mcp.py                # future: MCP server over the same core
  references/
    build123d_cheatsheet.md   # primitives agents use most
    printability.md           # design rules baked into diagnostics
    examples/
      hinged_box/             # canonical reference project
      snap_latch/
  tests/
```

**Discipline:** `core/` has no CLI or MCP dependencies. `cli.py` imports from
`core`. A future MCP layer does the same. Never put logic in the CLI module
that a different surface would also need.

## Public API shape

The package has no `__init__.py` (PEP 420 namespace). User scripts import
the public names directly from their submodules — no aliasing, no shim,
the structure speaks for itself.

```python
from build123d import *

from cad_khana.core.assembly import Assembly
from cad_khana.core.build import build


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
    .assert_min_wall("housing", min_mm=1.5)
)

build(assembly, out="outputs/")
```

The `build()` call runs the diagnostics, executes assertions, writes exports
and `diagnostics.json`, and exits nonzero if any assertion failed.

## CLI surface

```
khana build <path>              # run script, export, write diagnostics.json
khana check <path>              # diagnostics only, no export
khana view <path>               # build + push to OCP viewer
khana render <path> --views 4   # orthographic PNGs (for later)
khana diff <old> <new>          # diff two diagnostics.json files (for later)
```

Use `typer` for the CLI. Every command exits nonzero on failure. `build` and
`check` always write `diagnostics.json` even on failure, so the agent can
always read structured error info.

## diagnostics.json schema (v0.1)

Version this from day one. Agents depend on field stability.

```json
{
  "schema_version": "0.1",
  "status": "ok | error | assertion_failed",
  "error": null,
  "parts": {
    "<name>": {
      "bbox": {"min": [x,y,z], "max": [x,y,z]},
      "volume_mm3": 12403.2,
      "min_wall_mm": 1.8
    }
  },
  "interferences": [
    {"a": "lever", "b": "housing", "volume_mm3": 0.3, "centroid": [x,y,z]}
  ],
  "overhangs": [
    {"part": "housing", "area_mm2": 42.1, "max_angle_deg": 58}
  ],
  "assertions": [
    {"name": "lever_clears_housing", "passed": true, "detail": null},
    {"name": "pin_press_fit", "passed": false,
     "detail": "clearance 0.35mm exceeds max 0.1mm"}
  ],
  "exports": ["outputs/assembly.stl", "outputs/assembly.step"]
}
```

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

## Build order

Each step must ship something usable before moving on.

1. **Scaffolding.** `pyproject.toml` with `uv`, package skeleton,
   `khana --version` works. No CAD logic yet.
2. **Assembly + export.** `Assembly` class, STL + STEP export via Build123d.
   `khana build` produces files. No diagnostics yet.
3. **Basic diagnostics.** Bounding boxes, volumes, interference check (pairwise
   boolean intersection, volume > epsilon). `diagnostics.json` written.
4. **Assertions.** `assert_no_interference`, `assert_clearance`, `assert_min_wall`.
   Build exits nonzero on failure, diagnostics.json captures results.
5. **Viewer.** `khana view` pushes to `ocp_vscode`. Build first, push second,
   so agent sees clean designs.
6. **Wall thickness + overhangs.** Start with cheap approximations. Document
   their limitations in references/printability.md.
7. **SKILL.md + hinged-box example.** Makes the repo installable as a skill.
   Include user-script style guidance: pure part functions, declarative
   assembly composition, derived dimensions, `Location` for placement. Frame
   the recommendation around re-editability — the next edit session should be
   able to change a top-level parameter and see the design update
   consistently.
8. **Polish commands.** `khana check`, `khana diff`, `khana render`.

Stop at any step and the tool is still useful.

## Key dependencies

- `build123d` — CAD kernel (wraps OCCT)
- `ocp_vscode` — viewer client (Python side only; VS Code extension is a
  human prerequisite, documented separately)
- `typer` — CLI

Diagnostics use plain `@dataclass(frozen=True)` + `dataclasses.asdict()` +
stdlib `json` for serialization. Don't reach for pydantic unless we actually
need to parse incoming JSON (e.g., `khana diff` reading prior runs).

Install via `uv`. Project uses `uv sync` for dev, `uv tool install cad-khana`
for end-user install, `uvx khana ...` for ephemeral use.

## Implementation notes

- **Assembly model.** `Assembly` should be a frozen dataclass where `add()`
  returns a new Assembly with the part appended. The user script composes an
  assembly by chaining `add()` calls; `ck.build()` takes the final immutable
  value. Assertions are recorded the same way — `assert_no_interference()`
  returns a new Assembly with the assertion added to its list.
- **Interference check.** Iterate pairs, compute `part_a.intersect(part_b)`,
  report volume if above epsilon (0.001 mm³ to ignore FP noise). O(n²) is
  fine at mechanism scale (< 20 parts). No need to optimize.
- **Min wall thickness (v0).** Point-sampling approximation: sample points on
  each face, ray-cast inward along the normal, record shortest hit distance.
  Document as approximate in `references/printability.md`; a medial-axis
  approach is a later refinement.
- **Overhang detection.** Iterate faces of the mesh tessellation, compute
  angle between normal and +Z, flag faces below threshold (default 45°) that
  lack support from below.
- **Assertion execution.** Assertions are declarative records on the Assembly,
  evaluated during `ck.build`. Collect all results; never raise on first
  failure. The agent wants every failure at once.
- **Error handling at the boundary.** The CLI is the true application
  boundary. Uncaught exceptions from the user script get caught at the CLI,
  written to `diagnostics.json` with `status: "error"` and traceback in
  `error`. Never crash without leaving a diagnostic behind. Inside `core/`,
  functions fail fast on bad inputs without defensive checks.
- **Side effect isolation.** `core/diagnostics.py` and `core/assertions.py`
  should be pure (take an Assembly, return results). File I/O lives in
  `core/export.py` and the CLI. Viewer calls live in `core/viewer.py` and
  are only invoked by `khana view`.

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

## Current status

[Update this section as work progresses.]

- [x] Step 1: scaffolding
- [x] Step 2: assembly + export
- [x] Step 3: basic diagnostics
- [x] Step 4: assertions (no-interference + clearance; `assert_min_wall` deferred to step 6)
- [x] Step 5: viewer
- [x] Step 6: wall thickness + overhangs (+ `assert_min_wall`)
- [ ] Step 7: SKILL.md + example
- [ ] Step 8: polish commands
