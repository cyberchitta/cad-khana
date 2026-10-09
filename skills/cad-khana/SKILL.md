---
name: cad-khana
description: Diagnostics-first CAD wrapper around Build123d: assembly-level interference/clearance assertions plus optional per-part printability checks. Load BEFORE editing an `assembly.py` that uses the wrapper or interpreting its diagnostic JSON — SKILL.md has conventions the scripts rely on but don't restate, including which of three file kinds you are editing, and names the reference file to load for each task. TRIGGER: about to run `khana check`/`export`/`view`/`draw`/`run`, or editing a file that imports `cad_khana` or calls `Assembly()`/`check()`/`inspect()`.
---

# cad-khana

cad-khana splits geometric reasoning into two workflows:

- **Mechanism** — relational checks on an assembly (no interference,
  clearance between parts). Expressed via `Assembly.assert_*(...)` and
  evaluated by `khana check`. Writes `mechanism.json`.
- **Printability** — per-part, per-manufacturing-method checks (min
  wall thickness, overhangs). Expressed via `inspect(part, method=...)`.
  Writes `<name>-printability.json`.

**Declarations are imported by verbs; effects live at the CLI
boundary.** A module that declares parts, assemblies and claims calls
nothing effectful — no `check()`, no `inspect()`, no export. `khana
check` imports it and evaluates; `khana export` imports the same file
and writes STL/STEP; `khana draw` draws it. Genuinely imperative work
(batches, sweeps) goes in a separate script behind `khana run`.

A declaration module therefore has **no `if __name__ == "__main__"`
block** — nothing executes it. See **The three file kinds**.

## Setup

If `khana --version` fails, follow `references/install.md` once before
proceeding.

## When to use this tool

- Designing a **multi-part mechanical assembly** that needs to fit
  together (hinges, snap-fits, sliders, clevis/pin joints, boxes with
  lids).
- Producing **printable geometry** where wall thickness, clearance, and
  overhangs matter.
- Iterating under **agent control** — the JSON diagnostics are the
  primary signal; `khana draw` supplements it with engineering-drawing
  PNGs (HLR line-art) you can read directly when shape-level questions
  come up.

## When not to use it

- Pure surface modeling, organic shapes, meshes from scans. Use
  Build123d directly or a mesh tool.
- CAM / toolpath generation. Out of scope.
- Full constraint solving (drive geometry from relationships). The tool
  uses *assertions* — they check, they don't drive.

## CLI

Two kinds of command. **Import-model verbs** take a *target*, import
the module, resolve one member, and do one thing to it. **Execute-model**
runs a script for effect.

```
khana check  <target>          # diagnostics + assertions → mechanism.json
khana export <target>          # STL + STEP
khana view   <target>          # push assembly to the OCP viewer (socket)
khana draw   <target> [--view <names>] [--part <name>] [--format png|svg|both] [--themeable]
khana run    <script>          # execute an orchestration script
khana diff   <before> <after>  # diff two JSON files; exit 0 identical, 1 differences, 2 error
khana show   <json> [--grep <re>] [--failed] [--skipped] [--sort value] [--group <re>] [--json]  # read one JSON; see references/cli.md
khana status                   # JSON probe of versions + viewer reachability; exit nonzero if degraded
khana --version
```

`khana check` is the primary loop. It never exports — STL/STEP come
from `khana export`, and the two read the *same* file, so there is no
toggle to get wrong and no way for check-only geometry to reach an
export.

JSON diagnostics are always written, even on failure — read them to
diagnose errors. Exit codes: **2** for a usage error (unresolvable
target, unknown `--view`), **1** for a failed run.

A target is `<module-path>[:<factory>]`; with no `:factory` the verb
uses the module's `assembly` member. How members resolve, where output
lands, how imports resolve and how to run the viewer without VS Code:
`references/cli.md`.

## The three file kinds

Name a file by what it *is*. The name is the whole tell — a reader
should know from it whether the file declares, verifies, or
orchestrates.

| kind | name | addressed by | imported by others? |
|---|---|---|---|
| **declaration module** | `assembly.py`, `animated_assembly.py` | `khana check` / `export` / `view` / `draw` | yes — this is the product |
| **check module** | `check_*.py` | `khana check` | **never** |
| **command script** | a descriptive noun — `printability.py`, `role_sweep.py` | `khana run` | never |

What goes in a declaration module, in order, is in
`references/style.md`; a family of members the CLI can't address one
by one (roles, frames) is a command script — `references/cli.md`
§Parametrized families.

### Check module

An ordinary assembly module whose *purpose* is verification. It imports
product factories, composes a fixture, declares claims about the
interaction, and exposes the result as a factory. Prefix `check_`.

**The never-imported rule: product modules never import check
modules** — the same rule that keeps test files out of shipped code.
That is what makes assertion-only geometry free
(`references/composition.md`).

A claim belongs in the builder, a check module, or a check module for
one assembly step, depending on when it has to hold
(`references/composition.md` §Where a claim lives).

### Command script

Orchestration only: loops, batches, and the effectful calls the verbs
don't cover. Never a claim that a verb could have evaluated.

- **`printability.py`** is the name for a unit's `inspect()` batch. It
  names its output, it is a noun, and it can't be mistaken for a
  `check_*.py`.
- **`<family>_sweep.py`** for a parametrized family the CLI cannot
  address (`role_sweep.py`, `frame_sweep.py`).
- **No `run_` prefix** — `khana run .../run_printability.py` stutters,
  and the directory position already says what the file is.
- **Open the docstring with its own invocation line**, then a sentence
  saying which member `khana check` on the sibling `assembly.py`
  covers and which it does not. That sentence is load-bearing: without
  it, "I ran `khana check`, it was green" silently means one role, one
  frame, or no printability at all.

See `references/examples/pin_hinge/` for a worked declaration module
plus command script.

### Vacuous green

`khana check` on a module that declares **no assertions** exits 0 and
writes `"assertions": []`. That is not a passing design; it is an
unasked question, and an agent will read it as success. Modules that
strip assertions by design (an exhibit or render-only variant) should
say so in the first line of the docstring and carry a name that marks
them — a reader who sees `animated_exhibit_assembly.py` go green
should already know that means nothing. Check `assertions` is
non-empty before believing a green run on an unfamiliar file.

## Minimal skeleton

`assembly.py` — the declaration module. Note what is *absent*: no
`check()`, no `inspect()`, no `__main__`.

```python
from build123d import Box, Cylinder, Location, Part, Pos, Rot

from cad_khana.mechanism.assembly import Assembly

# 1. parameters + derived
WIDTH = 40.0
HEIGHT = 20.0
PIN_D = 3.0
PIN_GAP = 0.4                      # rest gap between pin and bracket top
PIN_Z = HEIGHT + PIN_D / 2 + PIN_GAP

# 2. pure part functions
def bracket(w: float = WIDTH, h: float = HEIGHT) -> Part:
    return Pos(0, 0, h / 2) * Box(w, w, h)

def pin(length: float = WIDTH, d: float = PIN_D) -> Part:
    return Cylinder(d / 2, length)

# 3. factory — defaults are the master design
def build_mount(pin_gap: float = PIN_GAP) -> Assembly:
    pin_z = HEIGHT + PIN_D / 2 + pin_gap
    return (
        Assembly()
        .with_part("bracket", bracket())
        .with_part("pin", pin(), location=Location((0, 0, pin_z)) * Rot(90, 0, 0))
        .assert_no_interference("pin", "bracket")
        .assert_distance("pin", "bracket", min_mm=pin_gap * 0.9)
    )

# 4. degenerate memoized master, so `khana check <file>` resolves
assembly = build_mount()
```

`printability.py` — the command script beside it:

```python
"""Per-part printability.

    khana run unit/printability.py

`khana check` on the sibling `assembly.py` covers the mechanism claims.
It does not cover anything in this file.
"""
from cad_khana.printability.inspect import inspect
from cad_khana.printability.methods import FDM

from assembly import bracket

inspect(bracket(), method=FDM(), out="outputs", name="bracket")
```

A two-part mechanism with no relocatable unit and no joint is the
degenerate flat case — anything with either composes sub-assemblies
(see `references/workflow.md` §Designing a new mechanism, step 2, and
`references/composition.md`).

## What a green check does not mean

Exit 0 means *no interference and printability passed, for the claims
you declared, at the poses you built*. Each of the following is a real
defect class a green check cannot see. When a slice depends on one of
them, the check is not your evidence — find the one that is.

- **Unasserted geometry.** A dimension consumed only by cosmetic
  geometry never earns an assertion, so it silently tracks whatever it
  was derived from. Nothing here measures appearance, and nothing sees
  a camera. `khana draw` is how you find the claims you forgot to make
  — draw a view before believing a green on a part whose parameters
  moved. Check `assertions` is non-empty first (see **Vacuous green**).
- **Orientation.** A wrong outward normal is not an overlap: a part
  placed facing backwards passes every clearance claim. When facing
  carries function, `assert_tangent_contact` against the surface it
  must face — that pins the orientation too.
- **One pose.** A claim with `poses.evaluated: 1` looked once, at the
  pose you built. It says nothing about the sign of a motion (a
  docstring claiming kinematics is not evidence — check at a non-rest
  pose), nothing about a service or removal path, and nothing about the
  pose where the envelope is actually worst. Declare a `Motion` and the
  claims are held at every sample; where you can't, say beside the
  assert which pose the numbers came from, or it expires silently when
  the parameter moves.
- **Promotion widens a claim's scope.** A bare `assert` over constants
  is frozen at that pose; a declared `assert_distance` is re-evaluated
  at every pose a motion builds. Promoting a rest-pose claim therefore
  reddens frames where nothing is wrong. Ask which poses the claim was
  ever true at, scope it with `during=`, and run the motion — not just
  the unit's own `khana check`.
- **A standalone green is a weaker claim than a top-level green.**
  Claims referencing parts a run doesn't contain are skipped, not
  failed: read `skipped_counts`, not just the exit code. A detail tier
  that isn't applied skips the claims that were written for it.
- **Cross-unit physical reality.** Two independently floor-standing
  units pass every cross-unit check while being unbuildable — they
  share one bench, and nothing infers that. Export the shared datum as
  an anchor and `assert_anchors_coincident` at the top
  (`references/composition.md` §Named interface anchors).

One habit that keeps the rest honest: **turn every fixed interference
into a named regression assert**, and write a known-bad overlap as
`assert_interference(reason=…)` rather than deleting the claim. A
positive assertion self-fails the moment the redesign lands, so it
cannot rot into folklore.

### Read `warnings` on every run

Both files carry a `warnings[]` that **never fails a run** — which is
exactly why it is where a green says what it did not look at. Read it
before believing an exit 0. Every kind:

- `joint_never_driven` — a joint no declared motion moves; everything
  about it is a rest-pose green.
- `never_in_phase` — a phased claim whose `during=` window no pose
  entered: widen the motion or fix the window.
- `motion_moved_nothing` (`motion`, `moved`, `movable`) — a declared
  motion that moved **no** claim: the sweep is vacuous and the green
  means nothing, so check the joint path drives something a claim
  references; with `movable: 0` no claim in the tree could have moved.
- `interferences_rest_pose_only` — a motion is declared, and
  `interferences[]` did not follow it: unasserted pairs are checked at
  the as-built pose only.
- `partial_run` (`evaluated`, `declared`) — `khana check --only` held
  a subset and computed no interferences: a green here is not the model's.
- `multi_solid` (`part`, `solid_count`) — a part in several pieces that
  no `assert_solid_count` / `inspect(..., solid_count=N)` speaks for:
  bound it or declare it. Nothing else sees a severed part.
- `waived_failure` (printability) — a failed check you waived; carries
  the reason and the failure detail. The reading is still a failure.
- `stale_waiver` (printability) — a waiver whose check now passes:
  delete it.

Next to `warnings`, read `skipped_counts` (a claim that did not look)
and each assertion's `poses.evaluated` (`1` means it looked once). The
rest of both files' fields: `references/diagnostics.md`.

## Known limitations

- **Min wall thickness is approximate.** Rays are cast from tessellated
  faces against the exact solid, and each ray measures only where it
  crosses the face it was cast from — perpendicular to that face, so
  the reading is a thickness of *that* wall. It can still miss diagonal
  pinch points. Readings at sharp features are *real* short material
  paths rather than noise — check `min_wall_alignment` to tell a wedge
  tip from a wall. See `references/printability.md`.
- **Overhang detection excludes the build-plate face.** Faces coplanar
  with the min-`up_axis` plane aren't flagged. Faces that face downward
  but sit above the build plate (ledge undersides, cavity ceilings) are
  still flagged.
- **Interference check is O(n²)** over parts. Fine up to ~20 parts.
- **Tangent contact reads as zero clearance.** Two parts sharing a face
  (e.g., a lid sitting on a rim) have `distance_to == 0`, which fails
  any `assert_distance(min_mm=…)` above zero by definition. Use
  `assert_no_interference` when parts are meant to touch.

## Reference files

Load each when its trigger applies — they are not optional reading
for the task they cover. Every library name a script needs is in the
last column, beside the file that documents it: a name you can't find
here isn't in the library, and one you can is already documented, so
load that file before proposing a feature.

| Load | before | names |
|---|---|---|
| `references/workflow.md` | starting a mechanism from a blank file, or the same failure surviving three fix attempts — design order, the check-then-draw loop, when to stop and escalate with `HUMAN_REVIEW:` |  |
| `references/cli.md` | addressing a `:factory`, looking for an output file, keeping a script's outputs apart (before/after baselines, parallel runs), an import failing under `khana`, the viewer, or checking several members of a family | `check`, `export_assembly` |
| `references/style.md` | writing or restructuring a declaration module — a part function, helper or factory, or adding, moving or deriving a parameter (changing an existing parameter's value alone doesn't fire it) | `Assembly`, `with_part`, `with_materials`, `with_detailed_geometry` |
| `references/assertions.md` | writing or changing any `assert_*` — the catalogue, solid count, distance/scalar, contact claims and `during=`, group assertions | every `assert_*`, `with_keepout`, `swept` |
| `references/composition.md` | adding a sub-assembly, joint or anchor, a claim about two units, or querying a composed assembly from a script (posing a joint, finding a placed part) | `with_subassembly`, `part(path)`, `placed_parts`, `with_anchor`, `anchor`, `with_joint`, `with_joint_angle` |
| `references/motion.md` | anything that moves or animates — declared motions, sweeps, GLB export | `Motion`, `with_motion`, `posed`, `over_joint`, `over_motion`, `sweep`, `classify`, `onset`, `export_glb`, `export_animated_glb` |
| `references/printability.md` | an `inspect()` call, a waiver, a printability JSON, or choosing a print orientation | `inspect`, `FDM`, `Waiver`, `Feature` |
| `references/diagnostics.md` | reading any JSON field beyond `status`, `passed`, `skipped_counts` and `warnings` |  |
| `references/drawings.md` | `khana draw` — which view answers which question |  |
| `references/build123d_quickref.md` | selector operators, algebraic vs Builder mode, type-conversion shortcuts |  |
| `references/standard_parts.md` | any standard hardware (bd_warehouse) |  |
| `references/examples/pin_hinge/` | a worked three-part mechanism with assertions and `inspect()` calls |  |

## Feedback

cad-khana is young — actively log feedback whenever something is
awkward, buggy, missing, surprising, or took more work than it
should. Don't filter; the maintainer triages.

When cad-khana is editably installed (e.g.
`[tool.uv.sources] cad-khana = { path = "../cad-khana", editable = true }`),
append a short entry to `<cad-khana-repo>/_notes/field-notes.md` — that
file's header has the entry format. When installed as a tool from
git, file an issue at https://github.com/cyberchitta/cad-khana/issues
with the same content.

A pattern only emerges when individual observations are recorded
honestly, so log first and worry about whether it generalizes later.
