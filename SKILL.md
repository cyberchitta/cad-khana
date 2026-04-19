---
name: cad-khana
description: Diagnostics-first CAD wrapper around Build123d. Use when you need to design 3D-printable mechanisms (hinges, clasps, brackets, enclosures with moving parts), produce STL/STEP exports, or iterate on a design against measurable constraints (no interference, minimum clearance, minimum wall thickness, overhang detection). Write a Python script that declares parts and an `Assembly`, run `khana build`, read `diagnostics.json`, iterate.
---

# cad-khana

You author a Build123d script that composes an `Assembly`, call
`build(assembly, out=...)`, and run it through the `khana` CLI. The CLI
writes STL + STEP exports and a structured `diagnostics.json`. Every
assertion you declare on the assembly becomes a build failure when
violated — read the JSON to decide what to edit next.

## When to use this tool

- Designing a **multi-part mechanical assembly** that needs to fit
  together (hinges, snap-fits, sliders, clevis/pin joints, boxes with
  lids).
- Producing **printable geometry** where wall thickness, clearance, and
  overhangs matter.
- Iterating under **agent control** — `diagnostics.json` is the
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
khana build  <script>  # run script, export STL/STEP, write diagnostics.json
khana view   <script>  # build, then push assembly to the OCP VS Code viewer
khana render <script>  # build, then write PNG views under <out>/views/
khana --version
```

`diagnostics.json` is always written to `--out` (default `outputs/`),
even on failure — read it to diagnose errors. Exit code is nonzero on
any assertion failure or script exception.

## Script structure

Keep three sections, in order:

1. **Parameters + derived** — named constants at the top, so one change
   propagates through everything.
2. **Pure part functions** — each returns a `Part`. Take parameters with
   defaults; no hidden globals, no mutation.
3. **Assembly composition** — build an `Assembly` by chaining `.add()`
   and `.assert_*()` calls. End with `build(assembly, out="outputs")`.

See `references/examples/pin_hinge/assembly.py` for the canonical
example. Re-read it when you're unsure of the pattern.

## Minimal skeleton

```python
from build123d import Box, Cylinder, Location, Part, Pos, Rot

from cad_khana.core.assembly import Assembly
from cad_khana.core.build import build

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

# 3. assembly + assertions
assembly = (
    Assembly()
    .add("bracket", bracket())
    .add("pin", pin(), location=Location((0, 0, HEIGHT / 2)) * Rot(90, 0, 0))
    .assert_no_interference("pin", "bracket")
    .assert_min_wall("bracket", min_mm=1.5)
)

if __name__ == "__main__":
    build(assembly, out="outputs")
```

## Recommended style

These conventions make a script **re-editable** — the next session can
bump a parameter and the design updates consistently.

- **Parameters at the top, derived just below.** One logical source of
  truth. Never inline a dimension inside a part function when a named
  constant would do.
- **Pure part functions.** Each function takes everything it needs as
  parameters (with defaults), returns a `Part`, and doesn't touch
  globals or mutate anything. A part function should build the same
  geometry every time for the same inputs.
- **Default arguments = the intended top-level parameter.** `housing()`
  with no args should return the current design's housing. Callers who
  want to override a single dimension pass it by keyword.
- **Use `Location` on `.add()` for placement, not inside the part.**
  Part functions build geometry at a canonical pose (typically centered
  on origin); the assembly places each part in world coordinates.
- **Algebraic mode operators (`+`, `-`, `*`, `Pos`, `Rot`) read more
  cleanly than `BuildPart` for short shapes** — prefer them for the
  examples unless the BuildPart context buys something (sketches,
  workplanes, patterns).
- **Name parts with stable identifiers** when you add them — assertions
  reference these names, and `diagnostics.json` reports per-name data.

## Available assertions

Every assertion records a result in `diagnostics.json`. If any fail,
`khana build` exits nonzero. All failures are collected — you get every
problem in one pass, not just the first.

| Assertion | Checks |
|---|---|
| `.assert_no_interference(a, b)` | Parts `a` and `b` don't overlap (intersection volume ≤ 0.001 mm³). |
| `.assert_clearance(a, b, min_mm=…)` | Minimum distance between `a` and `b` is at least `min_mm`. |
| `.assert_min_wall(part, min_mm=…)` | Part's thinnest wall is at least `min_mm`. Approximate; see caveats below. |

Give assertions a `name=` when you'd benefit from a specific label in
the diagnostics; otherwise they get an auto-generated one.

## diagnostics.json essentials

Read these fields after every build:

- `status` — `"ok"`, `"error"`, or `"assertion_failed"`.
- `error` — traceback string if the script itself crashed.
- `parts[name].volume_mm3` — use this to sanity-check a part is not empty.
- `parts[name].bbox` — quick sanity check on size and placement.
- `parts[name].min_wall_mm` — thinnest wall found by ray sampling.
- `interferences` — list of overlapping part pairs with volume + centroid.
- `overhangs` — per-part total flagged area and max angle (> 45° from vertical).
- `assertions` — one entry per declared assertion; `passed` + `detail`.

## Known limitations

- **Min wall thickness is approximate.** Ray-sampling from tessellated
  faces; it can miss diagonal pinch points and can be noisy near sharp
  convex edges. See `references/printability.md` for details.
- **Overhangs ignore build-plate orientation.** The bottom face of a
  part resting on the bed gets flagged as a 90° overhang because the
  algorithm doesn't know the print orientation.
- **Interference check is O(n²)** over parts. Fine up to ~20 parts.
- **Tangent contact reads as zero clearance.** Two parts sharing a face
  (e.g., a lid sitting on a rim) have `distance_to == 0`, which fails
  `assert_clearance` by definition. Use `assert_no_interference` when
  parts are meant to touch.

## Workflow

1. Write the script. Use the canonical example as a template.
2. `khana build path/to/script.py`
3. Read `outputs/diagnostics.json`.
   - `status: "error"` → fix the Python error reported in `error`.
   - `status: "assertion_failed"` → read `assertions` for failing
     entries. `interferences` and `parts[*].min_wall_mm` often point
     directly at the root cause.
   - `status: "ok"` → design is clean. Consider whether you've asserted
     everything that matters (a silent passing build isn't proof; it's
     just no failures detected).
4. Edit parameters or geometry. Re-run. Repeat.
5. When a question is shape-level rather than scalar ("is the tang
   pointing the right way", "did that cut land where I expected"), run
   `khana render path/to/script.py` and read the PNGs under
   `outputs/views/`. Four views (`front`, `top`, `right`, `iso`) are
   produced as hidden-line engineering drawings — solid black for
   visible edges, gray for edges hidden behind geometry.
6. When diagnostics are clean, ask the human to view it via
   `khana view path/to/script.py` (which pushes to the OCP VS Code
   viewer).

## Reference files

- `references/examples/pin_hinge/assembly.py` — canonical three-part
  mechanism with all three assertion types.
- `references/printability.md` — how wall thickness and overhang
  detection work, and where they're unreliable.
- `references/build123d_cheatsheet.md` — the Build123d primitives used
  most often in scripts (planned; drop into Build123d docs for now).
