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

**Geometry that exists only to be asserted against** — a sightline
cone, a tool-access envelope — is an ordinary `with_part`; nothing in
the library marks it un-manufacturable. It needs no special handling,
because **no exporter ever imports a check module**: `khana export
assembly.py` cannot see `check_cones.py`'s probes, and `khana check
check_cones.py` never exports. The probe lands in that file's `parts[]`,
which is honest — that file is a fixture run's output.

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
