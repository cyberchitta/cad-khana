# Motion: declared motions, sweeps, animated export

Load before anything that moves or animates. Joints and how a jointed
sub-assembly is composed are in `composition.md`.

Beyond static assertions, `Assembly` can express **motion**: a
`RevoluteJoint` on a `with_subassembly(...)` exposes a single
animatable DOF, and a `t → Assembly` factory function (the project's
animation primitive) drives the joints from a time parameter.

Use this when:

- A mechanism's clearance / interference depends on a joint angle —
  not just the rest pose. Declare the motion (§Declared motions) and
  `khana check` holds every claim over it.
- You're producing a multi-frame artifact (GLB exhibit, animated
  preview). `export_animated_glb` consumes the same factory.

Skip when the assembly's motion isn't relevant to the question
you're answering: pure static fit / printability runs faster on a
plain flat `Assembly`.

## The `t → Assembly` factory

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
TRS lerp would chord through curved paths). The node sits on its
joint's axis and nests under its parent joint's node, so the arc is
true wherever the axis is and however many joints move at once. Any
motion the joint *doesn't* account for (a jointed sub whose
`location=` also changes with `t`) is exact at keyframes and lerped
between them.

## One-frame static first

A bad joint axis costs the same at
  1 frame as at 97, and a 97-frame sweep is minutes of wall time.
  Validate any geometry or joint-wiring change via `factory(0.0)` +
  `khana check` (or a single `export_glb`) before fanning out to
  the full animated sweep.

## Declared motions: claims held over the motion, on every check

A claim checked at one pose says nothing about the poses between. A
turning ramp that clears its columns as built and ploughs through them
14° later is a green `mechanism.json` — unless the assembly **declares
the motion**, in which case `khana check` holds every assertion over it:

```python
from cad_khana.mechanism.motion import Motion

def build_floor() -> Assembly:
    return (
        Assembly()
        ...
        .with_subassembly("rotating", rotating(), joint=RevoluteJoint(axis=Axis.Z))
        .assert_no_interference_between("rotating", "columns")
        .with_motion(Motion.over_joint("stack_turn", "rotating", 0, 358, step=2))
    )
```

`Motion.over_joint(name, joint_path, lo, hi, step)` samples both ends
and never steps wider than `step`. Motion that drives several joints
from a schedule is the general form — a function `t -> {joint path:
value}` plus the `t` values to sample; joints a pose leaves out stay as
built:

```python
Motion("dump_cycle", lambda t: {"rotor": rotor_deg(t), "rotor.platform": tilt_deg(t)},
       ts=tuple(i / 160 for i in range(161)))
```

What `check()` then does, and what it costs:

- Every assertion is evaluated at the as-built pose **and at each
  sample of each motion** (each motion on its own, the rest of the tree
  as built). One result per assertion: failed if *any* pose failed,
  `value` / `detail` from the worst pose, `worst_at` naming it.
- Poses that place a claim's parts identically share one evaluation, so
  only the claims that span a driven joint multiply. A unit check stays
  fast; a whole-machine root holding a 180-sample motion is minutes.
- **A unit's motion is held at every root that composes the unit**,
  like its assertions. If that is too slow at a large root, declare the
  motion on the unit's own check target rather than inside the factory
  the root composes.
- **Once a motion is declared, every unphased claim is a claim about
  the whole motion.** A distance that is only true at rest will redden —
  give it a `during=` window (`assertions.md` §Contact claims). This is the point, not a side
  effect: it is what was silently unchecked before.
- `interferences[]` and part diagnostics still describe the as-built
  pose only (`warnings` says so). A pair nobody asserted is not held.
- It is **sampled**: a claim green at every sample can still fail
  between two of them. `motions[].joints_deg.<joint>.max_step` is the
  resolution you looked at; choose `step` against the smallest feature
  that could slip through.

Use one declaration for both jobs — derive a window with
`sweep(over_motion(assembly, motion), motion.ts)`, then hold it with
`during=` under the same `Motion`.

## Sweep diagnostics: what touches what, and when

`cad_khana.mechanism.sweep` answers questions about a *motion* rather
than a pose. All three take the same `factory(t) -> Assembly`:

```python
from cad_khana.mechanism.sweep import classify, onset, sweep

result = sweep(build_at, ts)                    # every pair, bbox-prefiltered
result = sweep(build_at, ts, pairs=[(a, b)])    # just these pairs

for phase in classify(result):
    print(phase.kind, phase.t_intervals, phase.angles_bracketing)

o = onset(build_at, ("pad", "block"), over=ts)  # first contact, bisected
```

`classify` labels each pair `always` / `never` / `transient` and reports
the `t` intervals and joint-angle spans it was in contact over. Use it
to **replace a hand-curated suppression list**: the list of pairs
becomes a property of the geometry, while the kinematic reason each
pair is there stays human-written — that's a design statement, not
something a sweep can derive. Feed `angles_bracketing` straight into a
`during=` window.

`onset` finds where contact begins. It scans for the first
clear→contact interval and bisects inside it — bisection alone would
assume contact only ever starts once, and `Onset.brackets` tells you
how many transitions the samples actually showed.

**A sweep is never a substitute for holding the claims.** The two look
alike from outside — both are "the mechanism at N poses" — and are
opposite in kind: `sweep` measures raw pairwise overlap volumes and
`classify` labels phases, but **neither evaluates a single assertion**,
and neither writes a `mechanism.json` you can diff. To have the
declared claims re-checked at every pose, declare the motion
(`with_motion`, above) and `khana check` does it on every run. A
command script looping `check(factory(t), out=...)` is only for motion
a schedule of joint values can't express (geometry that changes, a part
that moves without a joint). Swapping either for `sweep` deletes the
regression net.

**All of this is sampled, and sampling a motion is an inner
approximation.** `never` means "at none of the sampled parameters",
which is not the same as never — a real m03 sweep at 9 frames saw one
contact frame where 37 frames show two whole contact phases. So:
sweeps are for *deriving* a claim, assertions are for *holding* it.
Once you know the window, declare it with
`assert_allowed_contact(..., during=...)`, which re-derives from
geometry on every `khana check` instead of depending on which `t`
values someone sampled. Use `angles_bracketing` (the outer bound), not
`angles_at_contact` (the inner one): too wide only weakens the claim,
too narrow reddens runs that were always fine.

Before feeding a bracket into a `during=`, **read the per-frame
overlaps and check the profile rises and falls once** across the span.
That is what makes the bracket safe: finer sampling can then only find
contact *inside* it. Overlap that dips back to zero mid-span means the
samples straddle more than one contact event, and the bracket edges say
nothing about where the second one really starts — re-sample denser, or
window each event separately. The field can't signal this; only the
table can.

## glTF / GLB export

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
top-level motion. See the factory section above and `composition.md`
§Frames inside a sub-assembly for how to shape the assembly.

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
