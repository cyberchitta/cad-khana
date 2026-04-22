---
name: cad-khana
description: Diagnostics-first CAD wrapper around Build123d: assembly-level interference/clearance assertions plus optional per-part printability checks. Load BEFORE running any `khana` command or editing an `assembly.py` that uses the wrapper — SKILL.md has conventions (CWD-relative `outputs/`, diagnostic JSON keys) the scripts rely on but don't restate. TRIGGER: about to run `khana check`/`build`/`view`/`render`, or editing a file that imports `cad_khana` or calls `Assembly()`/`check()`/`inspect()`.
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
khana render <script>          # build, then write PNG views under <out>/views/
khana diff   <before> <after>  # diff two JSON files (mechanism or printability)
khana --version
```

Prefer `khana check` during fast iteration — it skips STL/STEP export
so the loop is tighter. Switch to `khana build` when you want the
exports on disk.

JSON diagnostics are always written to `--out` (default `outputs/`),
even on failure — read them to diagnose errors. Exit code is nonzero
on any assertion failure or script exception.

**CWD matters.** `--out` is resolved relative to the current
directory, so `outputs/` lands wherever you invoked `khana` from. Run
`khana` from the module directory (the one containing the script), or
pass an explicit `--out <module>/outputs`, so artifacts live next to
the script rather than at the repo root. The `out=` argument to
`check()` / `inspect()` inside the script's `__main__` block is
CWD-relative for the same reason.

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

`inspect(part, method=FDM(), out="outputs", name="bracket")` writes
`outputs/bracket-printability.json` and raises `SystemExit(1)` on
failure. Each call is independent — pass a different `name=` per
printed part.

## JSON diagnostics essentials

`mechanism.json` after every `check()`:

- `status` — `"ok"`, `"error"`, or `"assertion_failed"`.
- `error` — traceback string if the script itself crashed.
- `parts[name].volume_mm3` — sanity-check a part is not empty.
- `parts[name].bbox` — sanity-check on size and placement.
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
   - `status: "error"` → fix the Python error reported in `error`.
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
   `khana render path/to/script.py` and read the PNGs under
   `outputs/views/`. Four views (`front`, `top`, `right`, `iso`) are
   produced as hidden-line engineering drawings.
6. When diagnostics are clean, ask the human to view it via
   `khana view path/to/script.py` (which pushes to the OCP VS Code
   viewer).

## Reference files

- `references/examples/pin_hinge/assembly.py` — canonical three-part
  mechanism with mechanism assertions and per-part `inspect()` calls.
- `references/printability.md` — how wall thickness and overhang
  detection work, and where they're unreliable.
