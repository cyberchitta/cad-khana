---
name: cad-khana
description: Diagnostics-first CAD wrapper around Build123d: assembly-level interference/clearance assertions plus optional per-part printability checks. Load BEFORE editing an `assembly.py` that uses the wrapper or interpreting its diagnostic JSON — SKILL.md has conventions the scripts rely on but don't restate. TRIGGER: about to run `khana check`/`build`/`view`/`render`, or editing a file that imports `cad_khana` or calls `Assembly()`/`check()`/`inspect()`.
---

# cad-khana

cad-khana splits geometric reasoning into two workflows:

- **Mechanism** — relational checks on an assembly (no interference,
  clearance between parts). Expressed via `Assembly.assert_*(...)` and
  evaluated by `check(assembly, out=...)`. Writes `mechanism.json`.
- **Printability** — per-part, per-manufacturing-method checks (min
  wall thickness, overhangs). Expressed via `inspect(part, method=...)`.
  Writes `<name>-printability.json`.

A script typically does both: composes an `Assembly`, calls `check()`,
then calls `inspect()` once per printed part.

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
  primary signal; `khana render` supplements it with PNGs you can read
  directly when shape-level questions come up.

## When not to use it

- Pure surface modeling, organic shapes, meshes from scans. Use
  Build123d directly or a mesh tool.
- CAM / toolpath generation. Out of scope.
- Full constraint solving (drive geometry from relationships). The tool
  uses *assertions* — they check, they don't drive.

## CLI

```
khana build  <script>          # run script, export STL/STEP, write JSON diagnostics
khana check  <script>          # run script, write JSON diagnostics only (no export)
khana view   <script>          # build, then push assembly to the OCP viewer (socket)
khana render <script> [--view <names>] [--part <name>] [--format png|svg|both] [--themeable]  # build, then write views under <out>/views/
khana diff   <before> <after>  # diff two JSON files (mechanism or printability)
khana status                   # JSON probe of versions + viewer reachability; exit nonzero if degraded
khana --version
```

Prefer `khana check` during fast iteration — it skips STL/STEP export
so the loop is tighter. Switch to `khana build` when you want the
exports on disk.

JSON diagnostics are always written to `--out` (default `outputs/`),
even on failure — read them to diagnose errors. Exit code is nonzero
on any assertion failure or script exception.

**Output location.** A relative `out=` passed to `check()` / `inspect()`
inside a script is anchored to the script file's directory, so
`out="outputs"` lands next to the script regardless of the cwd you
invoked `khana` from. Same for `khana`'s default `--out` (used for
error diagnostics if the script crashes before reaching `check()`).
Pass an absolute path, or an explicit `--out <dir>` (cwd-relative,
because you typed it), to override.

### Viewer: no editor required

`khana view` calls `ocp_vscode.show(...)`, which pushes geometry over
a local socket (default port 3939). The listener can be either the
**OCP CAD Viewer** VS Code extension *or* the **standalone viewer
server** that ships with `ocp_vscode`:

```
uv run python -m ocp_vscode          # opens a browser tab, listens on 3939
uv run khana view assembly.py        # pushes geometry to whichever listener is up
```

So you can drive the full `view` loop from any editor (or none at
all). For **Zed**, the pattern that matches the VS Code UX is a pair
of workspace tasks in `.zed/tasks.json` — one to start the viewer
server, one to push the current file to it:

```json
[
  {
    "label": "OCP viewer: start",
    "command": "uv",
    "args": ["run", "python", "-m", "ocp_vscode"],
    "cwd": "$ZED_WORKTREE_ROOT",
    "allow_concurrent_runs": false
  },
  {
    "label": "khana view (current file)",
    "command": "cd \"$ZED_DIRNAME\" && uv run khana view \"$ZED_FILE\""
  }
]
```

## Script structure

Keep four sections, in order:

1. **Parameters + derived** — named constants at the top, so one change
   propagates through everything.
2. **Pure part functions** — each returns a `Part`. Take parameters with
   defaults; no hidden globals, no mutation.
3. **Assembly composition** — build an `Assembly` by chaining `.add()`
   and `.assert_*()` calls. Call `check(assembly, out="outputs")`.
4. **Per-part printability** — one `inspect(part, method=FDM(), name=...)`
   call per printed part.

See `references/examples/pin_hinge/assembly.py` for the canonical
example.

## Designing a new mechanism

When starting from a blank file, do these steps **in this order**.
Out-of-order work — most often, rendering before scalars are clean —
burns cycles on geometry that the diagnostics would have rejected for
free.

1. **Declare parts as pure functions.** One function per distinct
   printed body, taking parameters with defaults. No globals, no
   placement inside the function.
2. **Wire the assembly with explicit `Location`s.** Compose with
   `Assembly().add(name, part(), location=…)`. Names are stable IDs
   the assertions and diagnostics reference.
3. **Add `assert_no_interference` between *every* candidate-overlap
   pair immediately** — before any clearance work. The cost of
   asserting a pair that will never collide is one line; the cost of
   *not* asserting a pair that silently overlaps is a printed part
   you can't assemble. Default to over-asserting.
4. **Add `assert_clearance(a, b, min_mm=…)` between every pair of
   parts that move relative to each other.** Pick a real number
   (≥ 0.2 mm for FDM at 0.4 mm nozzle) — not a placeholder you mean
   to revisit.
5. **Run `khana check` and iterate until all scalars are green.**
   Reading `mechanism.json` is the primary loop; do not render yet.
6. **Then** `khana render` for shape-level verification. See
   **Reading renders** for which view answers which kind of question.

The first pass at a new mechanism is the moment to be liberal with
assertions; pruning later (because one is provably redundant) is
cheap, but discovering a missing one downstream is expensive.

## Minimal skeleton

```python
from build123d import Box, Cylinder, Location, Part, Pos, Rot

from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.check import check
from cad_khana.printability.inspect import inspect
from cad_khana.printability.methods import FDM

# 1. parameters + derived
WIDTH = 40.0
HEIGHT = 20.0
PIN_D = 3.0
PIN_CLEARANCE = 0.25
PIN_HOLE_D = PIN_D + 2 * PIN_CLEARANCE

# 2. pure part functions
def bracket(w: float = WIDTH, h: float = HEIGHT) -> Part:
    return Pos(0, 0, h / 2) * Box(w, w, h)

def pin(length: float = WIDTH, d: float = PIN_D) -> Part:
    return Cylinder(d / 2, length)

# 3. assembly + mechanism assertions
assembly = (
    Assembly()
    .add("bracket", bracket())
    .add("pin", pin(), location=Location((0, 0, HEIGHT / 2)) * Rot(90, 0, 0))
    .assert_no_interference("pin", "bracket")
)

if __name__ == "__main__":
    check(assembly, out="outputs")
    # 4. printability checks for each printed part
    inspect(bracket(), method=FDM(), out="outputs", name="bracket")
```

## Recommended style

These conventions make a script **re-editable** — the next session can
bump a parameter and the design updates consistently.

For build123d's selector operators (`>`, `<`, `>>`, `<<`, `|`, `@`, `%`,
`^`), algebraic-vs-Builder choice, and the implicit type conversions
(tuples for `VectorLike` / `RotationLike`), load
`references/build123d_quickref.md`.

- **Parameters at the top, derived just below.** One logical source of
  truth. Never inline a dimension inside a part function when a named
  constant would do.
- **Pure part functions.** Each function takes everything it needs as
  parameters (with defaults), returns a `Part`, and doesn't touch
  globals or mutate anything.
- **Default arguments = the intended top-level parameter.** `housing()`
  with no args should return the current design's housing. Callers who
  want to override a single dimension pass it by keyword.
- **Use `Location` on `.add()` for placement, not inside the part.**
  Part functions build geometry at a canonical pose (typically centered
  on origin); the assembly places each part in world coordinates.
- **Colors are a viewer/render aid, set at the placement.** `.add()`
  takes an optional `color=Color(...)` that `khana view` honors. Set it
  at the placement when the same part function is reused multiple times
  with different colors (e.g. four identical brackets, one red per
  corner); set `part.color` inside the part function only when the
  geometry has one intrinsic color everywhere it's used. Colors do not
  affect diagnostics and are ignored by `khana render`'s hidden-line
  PNGs and by STEP export.
- **Material is a first-class field on `PlacedPart`, parallel to
  color.** `.add()` takes an optional `material="<token>"` string that
  downstream consumers (chitra-cad's photo-real renderer; future FEA /
  kinematics) resolve against their own catalogs. Same intrinsic-vs-
  placement rule as color: set it at the `.add()` site when the same
  part body gets placed with different materials (or when the parent
  is the natural place to bind it); push it inside the part-builder
  only if the part has one intrinsic material everywhere it's used;
  leave unset (`None`) when the answer is genuinely open and let the
  consumer's override layer supply the current best guess. For
  cross-consumer experiments (render + FEA both reading from the same
  assembly), use `Assembly.with_materials({name: token})`. For
  render-only sweeps, use the consumer's own override (e.g.
  chitra-cad's `Scene.with_materials({...})`).
- **Two fidelity tiers — keep cheap geometry in the assembly,
  apply detail as an override layer.** The geometric-iteration
  loop (interference, clearance, printability) runs on cheap
  primitives — `Box(20, 20, L)` for a 2020 extrusion, no
  fasteners. That's the right model for assertions: it's fast to
  tessellate, and a real V-slot profile is a strict subset of a
  solid 20×20 so any clearance the cheap model passes the detailed
  one passes too. Detailed geometry (real `bd_warehouse` profiles,
  fasteners, finished shapes) lives in a `<module>/detail_variations.py`
  module as named bundles and applies via
  `Assembly.with_detailed_geometry(BUNDLE)` before the consumer
  (render / FEA / kinematics) reads the assembly. The override map
  handles **both swaps and additions**: a key matching an existing
  `PlacedPart.name` swaps the part shape (placement / material /
  color preserved); a key with no match appends a new `PlacedPart`
  from a `DetailOverride(part=…, location=…, material=…)`.
  Fasteners that the cheap model never created enter via additions
  — and each new fastener earns its own clearance assertion at the
  sub-assembly that owns the joint. Same intrinsic-vs-placement
  rule as materials: stable detail facts can move into the
  part-builder when they earn it; live as override entries until
  then. The two override layers (`with_materials`,
  `with_detailed_geometry`) compose — call them in either order
  before handing the assembly to the consumer.
- **Algebraic mode operators (`+`, `-`, `*`, `Pos`, `Rot`) read more
  cleanly than `BuildPart` for short shapes** — prefer them unless the
  BuildPart context buys something (sketches, workplanes, patterns).
- **Name parts with stable identifiers** when you add them — assertions
  reference these names, and the JSON diagnostics report per-name data.
- **Inspect only the parts you will actually print.** Stand-ins
  (extrusion stubs, shafts, fixed hardware) don't need `inspect()`;
  they are bought, not printed.
- **Document the coordinate frame in the module docstring** whenever
  the axes carry non-trivial meaning (radial vs tangential, hinge
  axis, floor datum, etc.). Without this, the next reader has to
  reverse-engineer axis conventions from the part math, and will
  often guess wrong. A 3-to-5-line block is enough:

  ```text
  Coordinate frame:
      origin = column axis ∩ floor datum
      +X     = radial outward toward the exit opening
      +Y     = tangent at the opening (hinge axis)
      +Z     = up
      z=0    = bearing/spider base
  ```

## Parametric standard parts: bd_warehouse

`bd_warehouse` is a Build123d-native companion library bundled as a
default dependency — fasteners, bearings, modeled threads, gears,
sprockets, pipes, flanges, and OpenBuilds extrusions. Reach for it
before hand-rolling any standard hardware. Each class subclasses
`BasePartObject`, so an instance *is* a `Part`. Wrap it in a thin pure
part function to keep script style consistent:

```python
from bd_warehouse.fastener import HexNut

def lock_nut(size: str = "M8-1.25") -> Part:
    return HexNut(size=size, fastener_type="iso4032")
```

Don't `inspect()` parts that come from `bd_warehouse` — they're bought,
not printed.

For what's in the library and how to discover available classes,
parameters, and valid type/size strings, load
`references/standard_parts.md`.

## Available mechanism assertions

Every assertion records a result in `mechanism.json`. If any fail,
`check()` raises `SystemExit(1)`. All failures are collected — you get
every problem in one pass, not just the first.

| Assertion | Checks |
|---|---|
| `.assert_no_interference(a, b)` | Parts `a` and `b` don't overlap (intersection volume ≤ 0.001 mm³). |
| `.assert_clearance(a, b, min_mm=…)` | Minimum distance between `a` and `b` is at least `min_mm`. |
| `.assert_interference(a, b, reason=…)` | Parts `a` and `b` **do** overlap (intersection volume > 0.001 mm³). Regression alarm for a documented, accepted overlap — fails if the overlap disappears, forcing the assertion to be removed when the design gap gets fixed. |

Give assertions a `name=` when you'd benefit from a specific label in
the diagnostics; otherwise they get an auto-generated one.

`assert_interference` is the exception, not the rule. Use it only when
a real design constraint leaves an overlap that hasn't been resolved
yet (e.g., a junction whose bracket hasn't been designed). The
`reason=` string is included in the failure message when the overlap
goes away, so a future reader understands what the assertion was
guarding against. Default to `assert_no_interference` everywhere else.

## Printability: `inspect(part, method=…)`

The method object carries manufacturing parameters. Today only
`FDM` exists:

```python
from cad_khana.printability.methods import FDM

FDM(
    up_axis=(0, 0, 1),     # part-local "up" direction during printing
    wall_min_mm=1.5,       # fail if a wall is thinner than this
    overhang_max_deg=45.0, # fail if a face overhangs past this
)
```

**Why these defaults.** Tuned for the common case — 0.4 mm nozzle,
PLA, default cooling — so a script with no overrides reflects real
printability constraints rather than placeholders:

- `wall_min_mm=1.5` ≈ three perimeter widths at a 0.4 mm nozzle. Thinner
  walls slice as one or two perimeters with no infill room, which
  under-extrude into single-ribbon walls or fail to bond. Bump up for a
  0.6 mm nozzle (≈ 2.0 mm) or rigid load-bearing parts; bump down only
  after a printed test wall confirms the slicer/printer combo holds
  together at the new floor.
- `overhang_max_deg=45.0` is the long-standing PLA-with-cooling rule of
  thumb — steeper faces need support or active bridging. Materials with
  weaker cooling (ABS, PETG without a part fan) want a tighter threshold
  (35–40°); ASA / a well-cooled PLA / a slicer with aggressive overhang
  modifiers can go to 50–55°. Adjust intentionally per material, don't
  default-loosen to silence the check.

`inspect(part, method=FDM(), out="outputs", name="bracket")` writes
`outputs/bracket-printability.json` and raises `SystemExit(1)` on
failure. Each call is independent — pass a different `name=` per
printed part.

## JSON diagnostics essentials

`mechanism.json` after every `check()`:

- `status` — `"ok"`, `"error"`, or `"assertion_failed"`.
- `error` — traceback string if the script itself crashed.
- `hint` — short pattern-matched repair suggestion when `status` is
  `"error"`; `null` otherwise. Read this first before parsing the
  traceback — it resolves the most common errors in one line.
- `parts[name].volume_mm3` — sanity-check a part is not empty.
- `parts[name].bbox` — sanity-check on size and placement.
- `parts[name].face_count` / `edge_count` / `vertex_count` — cheapest
  way to verify a boolean operation changed geometry: counts shift on
  success, stay the same on a silent no-op or OCCT failure.
- `interferences` — list of overlapping part pairs with volume + centroid.
- `assertions` — one entry per declared assertion; `passed` + `detail`.

`<name>-printability.json` after every `inspect()`:

- `kind: "printability"` — identifies the file.
- `name`, `method` — for disambiguation when scripts inspect many parts.
- `volume_mm3`, `bbox` — basic part metrics.
- `min_wall_mm` — thinnest wall found by ray sampling; `null` if
  unmeasurable.
- `overhang` — `null` or `{area_mm2, max_angle_deg}`.
- `assertions` — `wall_min:…` and `overhang_max:…` entries; `passed` +
  `detail`.

## Known limitations

- **Min wall thickness is approximate.** Ray-sampling from tessellated
  faces; it can miss diagonal pinch points and can be noisy near sharp
  convex edges. See `references/printability.md` for details.
- **Overhang detection excludes the build-plate face.** Faces coplanar
  with the min-`up_axis` plane aren't flagged. Faces that face downward
  but sit above the build plate (ledge undersides, cavity ceilings) are
  still flagged.
- **Interference check is O(n²)** over parts. Fine up to ~20 parts.
- **Tangent contact reads as zero clearance.** Two parts sharing a face
  (e.g., a lid sitting on a rim) have `distance_to == 0`, which fails
  `assert_clearance` by definition. Use `assert_no_interference` when
  parts are meant to touch.

## Workflow

1. Write the script. Use the canonical example as a template.
2. `khana check path/to/script.py`
3. Read `outputs/mechanism.json` and each `outputs/<name>-printability.json`.
   - `status: "error"` → check `hint` first; if non-null it resolves the
     most common cases without reading the full traceback in `error`.
   - `status: "assertion_failed"` in mechanism → read `assertions` for
     failing entries. `interferences` often points directly at the
     root cause.
   - `status: "assertion_failed"` in a printability file → look at
     `min_wall_mm` and `overhang`; adjust the part's geometry or the
     `FDM` threshold.
   - All `status: "ok"` → design is clean. Consider whether you've
     asserted everything that matters (a silent passing check isn't
     proof; it's just no failures detected).
4. Edit parameters or geometry. Re-run. Repeat.
5. When a question is shape-level rather than scalar ("is the tang
   pointing the right way", "did that cut land where I expected"), run
   `khana render path/to/script.py` and read the views under
   `outputs/views/`. See **Reading renders** below for which view
   answers which kind of question. Default format is PNG; pass
   `--format svg` for lossless vector output (diffable, inspectable
   as text), or `--format both` to get both. Pass `--themeable` with
   `svg`/`both` to additionally tag polylines with
   `class="cad-visible"` / `class="cad-hidden"`; the default inline
   stroke stays as a fallback, so non-CSS renderers see the same
   drawing while a CSS consumer (e.g. a website embedding the SVG
   inline) can restyle the two classes for dark-mode or brand colors.
6. When diagnostics are clean, ask the human to view it via
   `khana view path/to/script.py` (which pushes to the OCP VS Code
   viewer).

## When to stop iterating

Bounded loop: cap the repair cycle at **3–5 attempts** on the same
failure before stepping out. The cost of looping past that point is
context drift — earlier reasoning falls off, fixes start contradicting
each other, and the agent burns tokens re-deriving state it already
had.

Inside the loop, **feed the failure back into the next attempt**.
On a retry, the next prompt should carry forward the previous failing
script, the relevant `mechanism.json` (or `<name>-printability.json`)
slice, and the original task statement. Don't restart from scratch —
each iteration should be strictly more informed than the last.

When you hit the cap without convergence, **stop and escalate**: emit
a single line of the form

```
HUMAN_REVIEW: <one-sentence why> — last failure: <assertion or error>
```

and exit. Looping silently past 5 attempts wastes the human's
turnaround time and produces a worse handoff than a clean
"stuck-here-because-X" message. Common reasons to escalate:

- The same assertion fails after three substantive geometry edits
  (the constraint may be infeasible, or the spec needs to change).
- `status: "error"` repeats with the same `hint` after the suggested
  fix has been applied (the hint may be wrong for this case).
- Two assertions trade off against each other — fixing one breaks the
  other — and no clearance/wall budget exists that satisfies both.

Escalation is a feature, not a failure mode. A clean stop with
context beats a long thrash every time.

## Reading renders

`khana render <path>` writes ten views to `outputs/views/`: six
orthographic (`top`, `bottom`, `front`, `back`, `left`, `right`) and
four isometric (`iso_ne`, `iso_nw`, `iso_se`, `iso_sw`, named by the
camera octant in +Z-up / +Y-forward space). They're hidden-line
engineering drawings: visible edges in black, hidden in light grey.

The files cost only disk; the token cost is paid when you `Read` one
into context. So load only the view that answers your question:

- "Is this aligned along Z?" → `top` (or `bottom`).
- "Did the cut land where I expected?" → the orthographic view
  perpendicular to the cut axis.
- "Does the shape look right at a glance?" → one isometric is enough;
  `iso_ne` is a good default.
- "Is the underside clean?" → `bottom`, then the relevant side view if
  something looks off.

Don't load all ten by default. If one view doesn't answer, ask for a
second — not the whole set.

Two flags trim what gets written when you already know the answer
won't need ten views:

- `--view <names>` — comma-separated subset, e.g. `--view top,iso_ne`.
  Generation cost drops linearly; consumption cost only changes if
  you `Read` fewer files.
- `--part <name>` — frame and render only that one named part from
  the assembly (in its assembled position). Useful when one part is
  small and far from the others and the default whole-assembly framing
  shrinks it to a few pixels.

## Reference files

- `references/examples/pin_hinge/assembly.py` — canonical three-part
  mechanism with mechanism assertions and per-part `inspect()` calls.
- `references/printability.md` — how wall thickness and overhang
  detection work, and where they're unreliable.
- `references/standard_parts.md` — bd_warehouse contents and how to
  discover available classes, parameters, and valid type/size strings.
- `references/build123d_quickref.md` — selector operators, algebraic
  vs Builder mode, type-conversion shortcuts.

## Feedback

cad-khana is young — actively log feedback whenever something is
awkward, buggy, missing, surprising, or took more work than it
should. Don't filter; the maintainer triages.

When cad-khana is editably installed (e.g.
`[tool.uv.sources] cad-khana = { path = "../cad-khana", editable = true }`),
append a short entry to `<cad-khana-repo>/field-notes.md` — that
file's header has the entry format. When installed as a tool from
git, file an issue at https://github.com/cyberchitta/cad-khana/issues
with the same content.

A pattern only emerges when individual observations are recorded
honestly, so log first and worry about whether it generalizes later.
