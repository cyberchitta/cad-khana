---
name: cad-khana
description: Diagnostics-first CAD wrapper around Build123d: assembly-level interference/clearance assertions plus optional per-part printability checks. Load BEFORE editing an `assembly.py` that uses the wrapper or interpreting its diagnostic JSON — SKILL.md has conventions the scripts rely on but don't restate. TRIGGER: about to run `khana check`/`build`/`view`/`draw`, or editing a file that imports `cad_khana` or calls `Assembly()`/`check()`/`inspect()`.
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

```
khana build  <script>          # run script, export STL/STEP, write JSON diagnostics
khana check  <script>          # run script, write JSON diagnostics only (no export)
khana view   <script>          # build, then push assembly to the OCP viewer (socket)
khana draw   <script> [--view <names>] [--part <name>] [--format png|svg|both] [--themeable]  # build, then write engineering drawings under <out>/views/
khana diff   <before> <after>  # diff two JSON files; exit 0 identical, 1 differences, 2 error
khana status                   # JSON probe of versions + viewer reachability; exit nonzero if degraded
khana --version
```

Prefer `khana check` during fast iteration — it skips STL/STEP export
so the loop is tighter. Switch to `khana build` when you want the
exports on disk.

A script that is a **package member** (its directory and every
ancestor up to the package root carry an `__init__.py`) runs with
`python -m` semantics: the package root's parent goes on `sys.path`
and the script's relative imports (`from .params import …`,
`from ..shared import …`) resolve. Plain standalone scripts run
exactly as before. This lets sub-assembly files in a package tree be
both imported by their composing parent and `khana check`-ed
standalone with no `sys.path` bootstrapping in the script itself.

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
3. **Assembly composition** — build an `Assembly` by chaining
   `.with_part()` / `.with_subassembly()` and `.assert_*()` calls.
   Call `check(assembly, out="outputs")`.
4. **Per-part printability** — one `inspect(part, method=FDM(), name=...)`
   call per printed part.

See `references/examples/pin_hinge/assembly.py` for the canonical
example.

## Designing a new mechanism

When starting from a blank file, do these steps **in this order**.
Out-of-order work — most often, drawing before scalars are clean —
burns cycles on geometry that the diagnostics would have rejected for
free.

1. **Declare parts as pure functions.** One function per distinct
   printed body, taking parameters with defaults. No globals, no
   placement inside the function.
2. **Wire the assembly with explicit `Location`s, along its
   rigid-body boundaries.** Every relocatable unit with its own local
   frame, and every joint, is a `with_subassembly` node — declared
   from the start (a joint at angle 0 is fine), not bolted on later
   when animation needs it. A multi-part unit gets a
   `build_<name>() -> Assembly` builder in its own canonical frame;
   the parent places it via `location=`. A trivial mechanism with no
   such boundaries is a flat chain of
   `with_part(name, part(), location=…)` calls — the degenerate case,
   not the default shape. Names are stable IDs the assertions and
   diagnostics reference.
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
   Reading `mechanism.json` is the primary loop; do not draw yet.
6. **Then** `khana draw` for shape-level verification. See
   **Reading drawings** for which view answers which kind of question.

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
    .with_part("bracket", bracket())
    .with_part("pin", pin(), location=Location((0, 0, HEIGHT / 2)) * Rot(90, 0, 0))
    .assert_no_interference("pin", "bracket")
)

if __name__ == "__main__":
    check(assembly, out="outputs")
    # 4. printability checks for each printed part
    inspect(bracket(), method=FDM(), out="outputs", name="bracket")
```

A two-part mechanism with no relocatable unit and no joint is the
degenerate flat case — anything with either composes sub-assemblies
(see **Designing a new mechanism** step 2 and **Animation**).

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
- **Use `Location` on `.with_part()` for placement, not inside the part.**
  Part functions build geometry at a canonical pose (typically centered
  on origin); the assembly places each part in world coordinates.
- **Colors are a viewer/render aid, set at the placement.**
  `.with_part()` takes an optional `color=Color(...)` that `khana view` honors. Set it
  at the placement when the same part function is reused multiple times
  with different colors (e.g. four identical brackets, one red per
  corner); set `part.color` inside the part function only when the
  geometry has one intrinsic color everywhere it's used. Colors do not
  affect diagnostics and are ignored by `khana draw`'s hidden-line
  drawings and by STEP export.
- **Material is a first-class field on `PlacedPart`, parallel to
  color.** `.with_part()` takes an optional `material="<token>"` string that
  downstream consumers (chitra-cad's photo-real renderer; future FEA /
  kinematics) resolve against their own catalogs. Same intrinsic-vs-
  placement rule as color: set it at the `.with_part()` site when the same
  part body gets placed with different materials (or when the parent
  is the natural place to bind it); push it inside the part-builder
  only if the part has one intrinsic material everywhere it's used;
  leave unset (`None`) when the answer is genuinely open and let the
  consumer's override layer supply the current best guess. For
  cross-consumer experiments (render + FEA both reading from the same
  assembly), use `Assembly.with_materials({path: token})` — keys are
  the qualified tree paths that `placed_parts` reports. For
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
  part's qualified path swaps the part shape (placement / material /
  color preserved); a key with no match appends a new root-level
  `PlacedPart` from a `DetailOverride(part=…, location=…, material=…)`.
  Fasteners that the cheap model never created enter via additions
  — and each new fastener earns its own clearance assertion at the
  sub-assembly that owns the joint. Declare those assertions freely:
  in a run without the detail applied they skip (`passed: null` in
  the JSON, with the missing part named) instead of crashing, and
  evaluate normally once the override adds the part. Same intrinsic-vs-placement
  rule as materials: stable detail facts can move into the
  part-builder when they earn it; live as override entries until
  then. The two override layers (`with_materials`,
  `with_detailed_geometry`) compose — call them in either order
  before handing the assembly to the consumer.
- **Algebraic mode operators (`+`, `-`, `*`, `Pos`, `Rot`) read more
  cleanly than `BuildPart` for short shapes** — prefer them unless the
  BuildPart context buys something (sketches, workplanes, patterns).
- **Name parts with stable identifiers** when you place them — assertions
  reference these names, and the JSON diagnostics report per-name data.
  **Identity is the tree path**: a part nested in sub-assemblies is
  addressed everywhere by its dotted path (`"turret.rotor.arm.spider"`;
  root-level parts keep their bare name). The local name is just the
  last segment, so don't bake hierarchy into it — `"frame"` inside
  `platform_image` beats `"platform_image_frame"`; two instances of one
  builder are distinguished by their subtree, not by name prefixes.
  A single-part sub-assembly yields a stuttered path (`rotor.rotor`) —
  accept it; renaming the leaf to something generic (`body`) buys no
  information and costs the searchable name.
  Sibling names must be unique within a level (`with_part` /
  `with_subassembly` enforce this) and sub-assembly names cannot
  contain `.`.
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
`check()` raises `SystemExit(1)` after printing one line per failure
(name + detail) to stderr — the terminal output alone names every
failing assertion; the JSON has the full context. All failures are
collected — you get every problem in one pass, not just the first.
`inspect()` failures print the same way, prefixed with the part name.

| Assertion | Checks |
|---|---|
| `.assert_no_interference(a, b)` | Parts `a` and `b` don't overlap (intersection volume ≤ 0.001 mm³). |
| `.assert_clearance(a, b, min_mm=…)` | Minimum distance between `a` and `b` is at least `min_mm`. |
| `.assert_distance(a, b, min_mm=…, max_mm=…)` | Bounded distance from part `a` to part `b` **or a datum `Plane`**. Either bound alone, or both for "close but not touching" (a gear mesh). See below for `along=` and `grow_*_mm`. |
| `.assert_scalar(name, value, ge=…, le=…)` | A named claim about a non-geometric scalar (friction budget, torque margin). No bounds = pure recorder. |
| `.assert_interference(a, b, reason=…)` | Parts `a` and `b` **do** overlap (intersection volume > 0.001 mm³). Regression alarm for a documented, accepted overlap — fails if the overlap disappears, forcing the assertion to be removed when the design gap gets fixed. |

Give assertions a `name=` when you'd benefit from a specific label in
the diagnostics; otherwise they get an auto-generated one.

`assert_interference` is the exception, not the rule. Use it only when
a real design constraint leaves an overlap that hasn't been resolved
yet (e.g., a junction whose bracket hasn't been designed). The
`reason=` string is included in the failure message when the overlap
goes away, so a future reader understands what the assertion was
guarding against. Default to `assert_no_interference` everywhere else.

### Distance and scalar claims

Don't hand-derive from constants what the geometry already knows: a
bare Python `assert` crashes the script (`status: "error"`) instead of
recording a named, diffable result. `assert_distance` /
`assert_scalar` turn those claims into first-class assertions, and
both record their **measured value** in the JSON even on pass, so
`khana diff` reports drift the pass/fail boolean can't see.

```python
# gear mesh: close but not touching (min AND max bound)
a = a.assert_distance("ring_gear", "pinion",
                      min_mm=BACKLASH, max_mm=BACKLASH + 0.1)

# directed gap: how far `a` travels along the axis before touching `b`
# (negative once the projections overlap) — axis name or vector,
# read as the direction FROM a TOWARD b
a = a.assert_distance("pulley", "housing", along="Z", min_mm=1.0)

# datum plane target (declared in this assembly's frame; `along` must
# be parallel to the plane normal). Z-invariant claims need no sweep.
a = a.assert_distance("ramp", Plane.XY.offset(RIM_Z), along="-Z", min_mm=5.0)

# measure from an outward offset: tip circle over a modeled pitch
# cylinder (conservative — never reports more distance than the true
# offset body has)
a = a.assert_distance("pinion", "rails", min_mm=1.0, grow_a_mm=ADDENDUM)

# non-geometric scalar: recorded, diffable, optionally bounded
a = a.assert_scalar("ramp_slide_margin", tan(radians(RAMP_DEG)),
                    ge=MU_STATIC_BUDGET, detail="µ_s budget, ABS on PLA")
```

Bound comparisons carry a 1e-6 absolute tolerance, so placing or
sizing geometry *from* the same constant you bound against (gap ==
`MESH_BACKLASH` exactly) passes despite solver noise — no need to
hand-pad bounds with `- 0.01` margins.

Parameter-sanity checks with no geometric content (a deliberately
loose upper bound on a width) legitimately stay bare Python asserts.

### Declare assertions where the knowledge lives

Sub-assembly assertions **propagate**: a composed parent evaluates
every nested assertion with part/anchor paths, names, and datum-plane
targets qualified into its frame (a plane declared in a unit's local
frame moves with the unit's placement and joint). Declare each claim
once, at the sub-assembly that owns it — standalone runs evaluate it
directly, composed runs evaluate the qualified form (`u.clearance:a/b>=5`),
and assertions against detail-only parts skip (`passed: null`) in runs
that lack them. Don't mirror an assertion at both levels; that just
evaluates it twice under two names.

### Group assertions

When "assert every pair" is the intent, say so — don't hand-write the
double loop:

| Assertion | Expands to |
|---|---|
| `.assert_no_interference_between(group_a, group_b, …)` | One `assert_no_interference` per cross pair `(a, b)`. |
| `.assert_no_interference_within(group, …)` | One per unordered pair inside `group` (`i < j` in group order). |

A group is an iterable of part paths, or a **dotted sub-assembly path**
(`"turret.rotor"`) selecting every part under that subtree — expanded
to full paths from the asserting assembly's root
(`"turret.rotor.arm.spider"`), sorted. Expansion is a macro over the
current contents — parts added afterwards aren't covered, so declare
group assertions after composition.

Both take two keyword options:

- `known_overlaps=[(a, b, reason), …]` — downgrades those pairs
  (order-independent) to `assert_interference(reason=…)` regression
  alarms.
- `suppressed=[(a, b), …]` — skips those pairs entirely (e.g. a
  design-intended contact during motion with no clean per-frame
  predicate).

Expanded assertions are the plain single-pair forms with their usual
auto-names, so migrating a hand-written loop to a group call leaves
`mechanism.json` unchanged.

### Named interface anchors

When two units share a physical interface (a deck a frame rests on, a
column a bracket mates to, a delivery point), don't mirror the numbers
across unit boundaries — export the datum as an **anchor** and let the
composing parent derive placements and assert the interface:

```python
# each unit declares its interface points in its OWN frame
m05 = m05.with_anchor("deck_top", Pos(0, 0, DECK_TOP_Z))
chain = chain.with_anchor("deck_top", Pos(0, 0, DECK_TOP_Z_LOCAL))

# the parent resolves anchors to derive placement …
deck = m05_assy.anchor("deck_top").position
pose = Pos(0, 250, deck.Z - floor_bottom.Z)

# … and, after composition, asserts the units' beliefs coincide
top = top.assert_anchors_coincident("chain.deck_top", "m05.deck_top")
```

`with_anchor(name, location)` declares a named `Location` in the
assembly's local frame (own namespace — no collision with part names;
no `.` in the name). `anchor(path)` resolves a dotted path
(`"m05.deck_top"`) through the tree, composing each sub-assembly's
placement and joint like part locations — an anchor under a jointed
subtree moves with the joint. `assert_anchors_coincident(a, b,
tol_mm=1e-6)` compares resolved **positions** (orientation ignored);
paths are checked at declaration (fail-fast on typos) and re-resolved
at `check()` time.

The pattern replaces mirror-constant + drift-assert pairs: a unit that
must build standalone keeps its local numbers, but *exports where it
believes the shared datum is* — if a mirror drifts, the two beliefs
stop coinciding and the parent's `check()` fails loudly, instead of
the drift silently desyncing the machine. Anchors carry no geometry;
exports and interference checks ignore them.

## Animation: joints + time-parameterized assembly

Beyond static assertions, `Assembly` can express **motion**: a
`RevoluteJoint` on a `with_subassembly(...)` exposes a single
animatable DOF, and a `t → Assembly` factory function (the project's
animation primitive) drives the joints from a time parameter.

Use this when:

- A mechanism's clearance / interference depends on a joint angle —
  not just the rest pose. Sample `factory(t)` at several `t` and
  call `check()` on each to catch mid-motion overlaps.
- You're producing a multi-frame artifact (GLB exhibit, animated
  preview). `export_animated_glb` consumes the same factory.

Skip when the assembly's motion isn't relevant to the question
you're answering: pure static fit / printability runs faster on a
plain flat `Assembly`.

### Joint primitives

Today the library exposes one joint type:

```python
from build123d import Axis
from cad_khana.mechanism.assembly import RevoluteJoint

joint = RevoluteJoint(
    axis=Axis((px, py, pz), (dx, dy, dz)),   # in the SUB-ASSEMBLY'S frame
    angle_deg=0.0,                            # animatable DOF
    frame="local",
)
```

**Prefer `frame="local"`** — the axis is written in the jointed
sub-assembly's own frame (build123d's joint-on-the-part convention),
and the `location=` placement carries it to the parent. Identical
sub-assemblies placed at different poses (four platforms around a
hub) then share one joint declaration instead of a hand-computed
per-instance axis table.

The default is `frame="parent"` (compatibility): the axis is
interpreted in the owning parent `Assembly`'s frame, and each
differently-posed instance needs its own axis. The two are
interchangeable — a local axis `A` ≡ the parent-frame axis
`location * A`. `angle_deg` is the value the animation factory
updates per frame.

### Composing animated assemblies

A jointed sub-assembly is added with
`with_subassembly(name, sub, location=..., joint=...)`. The
sub-assembly is itself a full `Assembly` (it can contain parts,
sub-sub-assemblies, joints) — nest as deeply as the mechanism needs.
Reach into the tree with dotted paths:

```python
turret = (
    Assembly()
    .with_subassembly(
        "rotor",
        rotor_internals,                              # an Assembly
        location=Pos(0, 0, 0),
        joint=RevoluteJoint(axis=Axis.Z, frame="local"),   # rotor's own Z
    )
    .with_subassembly(
        "kicker_lever",
        lever_internals,
        joint=RevoluteJoint(
            axis=Axis((px, 0, pz), (0, -1, 0)),       # in lever-local
            frame="local",
        ),
    )
)
# later — animation hook:
turret = turret.with_joint_angle("rotor", 45.0)
turret = turret.with_joint_angle("rotor.platform_dump", 12.5)  # nested
```

`with_joint(path, joint)` is the alternative shape: attach (or
replace) the joint on an already-composed sub-assembly instead of
passing `joint=` at `with_subassembly` time. Same dotted-path form
as `with_joint_angle`; raises `KeyError` if any segment is missing.

`with_joint_angle` raises if the path doesn't reach a jointed
sub-assembly.

### The `t → Assembly` factory

A function `factory(t: float) -> Assembly` that returns the static
assembly at parameter `t` is the project's animation primitive.
Motion is expressed *in user code* as math (`angle = f(t)`); the
library samples `factory(t)` and emits glTF or runs per-frame
checks.

```python
def build_at(t: float) -> Assembly:
    a = build_static()
    a = a.with_joint_angle("rotor", 360.0 * t)
    a = a.with_joint_angle("kicker_lever", lift_schedule(t))
    return a
```

`cad_khana.export.export_animated_glb(factory, ts, out, ...)`
sweeps the factory over a sequence of `t` values, tessellates
geometry once from `factory(ts[0])`, and injects animation samplers
per jointed sub-assembly. Each jointed `with_subassembly(...)`
becomes one `animgroup_N` node in the GLB scene graph whose
children are the group's parts — the parent carries a slerp'd
rotation that traces the true arc between keyframes (per-channel
TRS lerp would chord through curved paths).

### Conventions that matter

- **Parts in canonical local frame.** Inside an animated
  sub-assembly, a `Part` returned by your part function must have
  identity `part.location` — orientation and translation belong at
  the `with_part(name, part, location=...)` site, not baked into
  the geometry. `export_animated_glb` enforces this on dynamic
  parts and raises with the offender's name. Reason: the per-frame
  TRS sampler only reads `PlacedPart.location`, so a non-identity
  intrinsic `Location` renders correctly at frame 0 then gets
  silently dropped from frame 1 onward.

- **Placement is parent-local for parts inside a sub-assembly.**
  When a part lives inside a sub-assembly, the `location=` passed
  to `with_part(...)` is in the sub-assembly's local frame, not
  world. The composition through the joint and the outer
  `with_subassembly` placement brings it to world automatically.

- **One-frame static first.** A bad joint axis costs the same at
  1 frame as at 97, and a 97-frame sweep is minutes of wall time.
  Validate any geometry or joint-wiring change via `factory(0.0)` +
  `khana check` (or a single `export_glb`) before fanning out to
  the full animated sweep.

### glTF / GLB export

`cad_khana.export.export_glb(assembly, out, ...)` writes a static
GLB; each `PlacedPart` becomes a named scene node with its
build123d `Color` baked as the glTF baseColor. No PBR, no lighting
— the geometry-truth artifact. For PBR materials baked from
`chitra-cad`'s catalog use `chitra_cad.export.export_glb` instead.

```python
from pathlib import Path

from cad_khana.export import export_glb

from assembly import assembly  # the top-level Assembly

export_glb(assembly, out=Path("subsite/assets"), name="rig.glb")
```

`cad_khana.export.export_animated_glb(factory, ts, out, ...)`
sweeps a `t → Assembly` factory and emits an animation block on top
of the static geometry path. One `animgroup_N` node per jointed
sub-assembly; per-channel TRS samplers fall through for any
top-level motion. See the factory + conventions sections above for
how to shape the assembly.

```python
from pathlib import Path

from cad_khana.export import export_animated_glb

from animated_assembly import build_at  # def build_at(t: float) -> Assembly

N_FRAMES = 61
ts = [i / (N_FRAMES - 1) for i in range(N_FRAMES)]
export_animated_glb(
    build_at,
    ts=ts,
    out=Path("subsite/assets"),
    name="rig-animated.glb",
    duration_s=8.0,
)
```

Tessellation runs once on `factory(ts[0])`; subsequent frames only
sample `PlacedPart.location` per part. `ts` closing the loop
(`ts[-1]` reproduces `ts[0]`'s pose) lets `<model-viewer autoplay>`
loop the animation in `duration_s` seconds without a visible cut.

**Color-space convention.** `PlacedPart.color` is treated as
sRGB-encoded throughout the cad-khana export path (OCP labels it
`Quantity_TOC_sRGB` and converts to linear before writing
glTF). Pass colors authored the way humans pick them (CSS hex,
design tokens). Pre-linearizing (`r ** 2.2`) double-converts and
crushes the rendered output to near-black. Downstream consumers
that need linear (e.g. chitra-cad → Blender Cycles) linearize at
their own input boundary.

Both pipelines require `gltf-transform` on `PATH`:
`bun install -g @gltf-transform/cli`.

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
  default-loosen to silence the check — waive instead (below), so the
  threshold keeps catching real overhangs.

`inspect(part, method=FDM(), out="outputs", name="bracket")` writes
`outputs/bracket-printability.json` and raises `SystemExit(1)` on
failure. Each call is independent — pass a different `name=` per
printed part.

**Waiving a known-benign failure.** When a check fails for a reason
you've verified is an artifact or an accepted trade-off (a sharp-edge
sampling artifact, a 90° ceiling you'll print with supports), waive it
with the rationale inline instead of loosening the threshold or
wrapping the call in `try/except SystemExit`:

```python
inspect(
    rotor(), method=FDM(), out="outputs", name="rotor",
    waive={
        "wall_min": "star-ridge sampling artifact; verified via min_wall_at",
        "overhang_max": "accepted 90° ceiling, printed with supports",
    },
)
```

Keys are assertion *kinds* (`"wall_min"`, `"overhang_max"` — no
threshold suffix). A waived failure keeps `passed: false` in the JSON,
records your reason in `waived`, adds a `waived_failure` entry to
`warnings[]`, and doesn't fail the run; unwaived failures still exit 1.
If the waived check starts passing, a `stale_waiver` warning tells you
to delete the waiver — don't leave waivers that no longer waive
anything. Cite evidence in the reason (`min_wall_at` witness, a print
plan), not just an assertion that it's fine.

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
- `assertions` — one entry per declared assertion; `passed` + `detail`
  + `value`. `passed` is `true`/`false`/`null`: `null` means the
  assertion was skipped because a part it references is absent from
  this run (`detail` names the missing parts) — normal for assertions
  against override-added detail parts in a standalone run. Skips never
  fail the build; watch for an assertion that is *always* skipped,
  which usually means a typo'd part name. `value` is the measured/
  claimed scalar for `assert_distance` / `assert_scalar` (recorded
  even on pass; `khana diff` reports its drift) and `null` otherwise.

`<name>-printability.json` after every `inspect()`:

- `kind: "printability"` — identifies the file.
- `name`, `method` — for disambiguation when scripts inspect many parts.
- `volume_mm3`, `bbox` — basic part metrics.
- `min_wall_mm` — thinnest wall found by ray sampling; `null` if
  unmeasurable.
- `min_wall_at` — `[x, y, z]` surface point where the thinnest wall was
  measured (`null` when `min_wall_mm` is); use it to attribute a thin
  reading to a concrete feature instead of bisecting parameters. The
  failing `wall_min:…` assertion repeats it in its `detail`.
- `overhang` — `null` or `{area_mm2, max_angle_deg}`.
- `assertions` — `wall_min:…` and `overhang_max:…` entries; `passed` +
  `detail`, plus `waived` (the rationale) when a failure was waived.
- `warnings` — non-fatal notices: `waived_failure` (a failed check that
  was waived; carries the reason and the failure detail) and
  `stale_waiver` (a waiver whose check now passes — remove it).

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
   `khana draw path/to/script.py` and read the views under
   `outputs/views/`. See **Reading drawings** below for which view
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

## Reading drawings

`khana draw <path>` writes ten views to `outputs/views/`: six
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
append a short entry to `<cad-khana-repo>/_notes/field-notes.md` — that
file's header has the entry format. When installed as a tool from
git, file an issue at https://github.com/cyberchitta/cad-khana/issues
with the same content.

A pattern only emerges when individual observations are recorded
honestly, so log first and worry about whether it generalizes later.
