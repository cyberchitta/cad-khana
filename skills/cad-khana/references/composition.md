# Composition: sub-assemblies, joints, anchors

Load before adding a sub-assembly, a joint or an anchor, or a claim
about two units. One idea runs through all of it: structure a unit so
its claims hold wherever it is placed and however it is posed.

## Identity is the tree path

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

## Declare assertions where the knowledge lives

Sub-assembly assertions **propagate**: a composed parent evaluates
every nested assertion with part/anchor paths, names, and datum-plane
targets qualified into its frame (a plane declared in a unit's local
frame moves with the unit's placement and joint). Declare each claim
once, at the sub-assembly that owns it — standalone runs evaluate it
directly, composed runs evaluate the qualified form (`u.distance:a/b>=5`),
and assertions against detail-only parts skip (`passed: null`) in runs
that lack them. Don't mirror an assertion at both levels; that just
evaluates it twice under two names.

**Claims about the *interaction* of units belong in a check module.**
A claim owned by no single model — probe cones against sightlines, a
merged fixture, two units' beliefs about a shared datum — has the
fixture as its owning level, so give the fixture a file. It imports
the product factories, composes them, declares the claims, and exposes
the result as a factory:

```
m03_scanner/
  assembly.py        # product factories (+ degenerate `assembly`)
  check_cones.py     # composes both, asserts, exposes a factory
```

`khana check` evaluates both kinds — the distinction is in how a claim
is *expressed*, not how it is run. (pytest is the proof: fixture-heavy
and three-line tests share one runner.)

**Geometry that exists only to be asserted against** comes in two
forms. A **keep-out**, a volume parts must stay out of (a driver's
corridor, a bolt's drop-in path, an RF zone), is an argument to
`assert_clear_of`, or a unit's named `with_keepout` asserted by path
(`assertions.md` §Keep-outs). It is never a part, so it can sit in the
product's own builder. A **probe** that other claims pair
with, or that you want drawn (a sightline cone checked with
`assert_no_interference`), is an ordinary `with_part` in a check module.
Nothing in the library marks it un-manufacturable, and it needs no special
handling, because **no exporter ever imports a check module**: `khana
export assembly.py` cannot see `check_cones.py`'s probes, and `khana
check check_cones.py` never exports. The probe lands in that file's
`parts[]`, which is honest: that file is a fixture run's output.

## Where a claim lives

The same claim call works at three levels. No rule picks one for you;
ask **when the claim has to hold**, and declare it where that is true.

- **In the product's builder**, for a promise the product makes whenever
  it exists: the clamp's M4 bolts drop in at every camera pose; no metal
  sits behind the coil. It runs on the product's default `khana check`,
  it is held over every declared motion, and it rides the unit into
  every parent that composes it.
- **In a check module**, for a claim about the product together with
  something that is not in it (a fixture, probe cones, a second unit's
  belief about a datum), or one too slow to run on every check.
- **In a check module for one assembly step**, for a claim that is true
  only partway through the build: a driver reaches the arc screws
  *before* the cover goes on. Compose the parts installed by that step,
  and declare the keep-out against them. In the finished product the
  cover blocks the path, and should. Name the file for the step
  (`check_step_arc_screws.py`).

**Which builder**, when the geometry is known low and the parts exist
high: a driver corridor's pose is a stage fact, while the bodies it must
clear are the machine's. A keep-out holds only parts of the assembly the
claim is declared in, so declare the keep-out where the geometry is
known (`stage.with_keepout("arc_screw_driver", driver)`) and assert it
where the parts are (`top.assert_clear_of([...],
"m02_chain.s1.arc_screw_driver")`), the way an anchor is exported low
and asserted high (§Named interface anchors). It rides the stage's
placement and joints into the claim at every pose.

A claim declared at the wrong level fails in one of two ways. Declared
in the builder, the step claim reads red on a correct design. Declared
in a check module, a product promise goes unchecked by the product's
default `khana check`.

Verify a cone-free export by **solid count**, not by grepping part
names: the STEP exporter writes no names.

## Named interface anchors

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

`part(path)` is the same resolution for a part: the `PlacedPart` at a
dotted path, in the frame of the assembly you call it on —
`top.part("turret.drive.bracket")` is the world placement,
`drive.part("bracket")` the unit-local one. Reach for it instead of
filtering the `placed_parts` property by name or re-typing a part's
constructor:
`inspect(build_chain().part("brace_head").part, …)` inspects the body
that is actually placed, and a detail addition keyed by its unit's
path takes its `location` from that unit's own `part(...)`.

## Joint primitives

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

## Composing animated assemblies

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

## Frames inside a sub-assembly

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
