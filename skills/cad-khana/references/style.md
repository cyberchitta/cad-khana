# Authoring style

Load before writing a new part function or declaration module. These
conventions are what make a script re-editable; nothing enforces them.

## Declaration module

Parameters, pure part functions, and **parameterized factories**
returning `Assembly` with their claims attached. Calls nothing
effectful. Four sections, in order:

1. **Parameters + derived** — named constants at the top, so one change
   propagates through everything.
2. **Pure part functions** — each returns a `Part`. Take parameters with
   defaults; no hidden globals, no mutation.
3. **Factories** — `build_<name>(...) -> Assembly`, chaining
   `.with_part()` / `.with_subassembly()` and `.assert_*()` calls.
   Defaults are the master design.
4. Optionally `assembly = build_<name>()` — the degenerate memoized
   master, so `khana check <file>` resolves without a `:factory`.

**The standalone composition is a factory too.** A unit usually has a
composition that exists only *outside* a parent — the product subtree
plus the stubs, press fits and group asserts that a parent would
otherwise supply. Nothing imports it, so nothing pressures it into a
name, and it silently becomes a run of module-level rebinds with
real import-time effects. Give it one: `build_<unit>_standalone()`.

**A declaration module binds `assembly` exactly once.** That is the
invariant — not "avoid rebinding", which sounds like style. Sequential
module-level bindings and a `for` loop appending asserts both defeat a
`grep` for `x = x.`, and both mean the module's meaning depends on
import-time statement order rather than on a factory you can call
twice and get the same answer from.

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
- **Assembly factories are parameterized like part functions.** The
  defaults are the master design; a variant is an alternate call, not a
  second module. This covers the case where *instances of one unit
  differ*: a motor's azimuth around its axis, a floor's role in a
  stack. Thread it as a factory argument — the unit's own claims hold
  at any value, `@cache` keys on it, and the parent passes it per
  placement. Do **not** reach for a `with_detailed_geometry` override
  here: the mesh moves with this parameter, so it is not detail. The
  converse is the trap — a design choice fixed in a module-level
  constant is computed at import and unreachable from a command
  script, so sweeping it needs `sed` rather than a loop.
- **In a multi-unit project, constants have a hierarchy.** A
  project-root `params.py` holds the constants that cross unit
  boundaries (shared interfaces, datums, stock sizes); each unit's own
  `assembly.py` holds the rest. A constant that only one unit reads
  does not belong at the root, and a constant two units must agree on
  does not belong in either of them. (Where the shared value is a
  *place* rather than a number, prefer an anchor — see `composition.md` §Named
  interface anchors.)
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
  the qualified tree paths the `placed_parts` **property** reports
  (a property, not a method — `top.placed_parts()` raises
  `TypeError: 'tuple' object is not callable`). For
  render-only sweeps, use the consumer's own override (e.g.
  chitra-cad's `Scene.with_materials({...})`).
- **Two fidelity tiers — keep cheap geometry in the assembly,
  apply detail as an override layer.** The geometric-iteration
  loop (interference, clearance, printability) runs on cheap
  primitives — `Box(20, 20, L)` for a 2020 extrusion, no
  fasteners. That's the right model for assertions: it's fast to
  tessellate, and a real V-slot profile is a strict subset of a
  solid 20×20 so any clearance the cheap model passes the detailed
  one passes too. **That guarantee has a precondition: the cheap
  proxy must be an *outer envelope* of the detailed part.** It holds
  for an extrusion (the real profile only removes material) and
  inverts the moment the detail sticks *out* — a gear modeled by its
  pitch cylinder, a thread by its minor diameter, a knurl or spline
  by its root. There the cheap clearance is optimistic, which is the
  one failure this tool must never produce: model the proxy at the
  tip circle / major diameter, or grow it at the claim with
  `assert_distance(..., grow_a_mm=…)`. Detailed geometry (real `bd_warehouse` profiles,
  fasteners, finished shapes) lives in a `<module>/detail_variations.py`
  module as named bundles and applies via
  `Assembly.with_detailed_geometry(BUNDLE)` before the consumer
  (render / FEA / kinematics) reads the assembly. The override map
  handles **both swaps and additions**: a key matching an existing
  part's qualified path swaps the part shape (placement / material /
  color preserved); a key with no match appends a new `PlacedPart`
  from a `DetailOverride(part=…, location=…, material=…)` **at the
  level the key names, in that level's frame** —
  `"turret.drive.foot_bolt"` adds `foot_bolt` to the `drive` unit, a
  bare name adds a root-level part, and a prefix naming no
  sub-assembly raises `KeyError`.
  Fasteners that the cheap model never created enter via additions
  — and each new fastener earns its own clearance assertion at the
  sub-assembly that owns the joint. **Key the addition with that
  unit's path from the root being detailed** (bare only when the unit
  itself is the root), not a bare name everywhere: the unit's claim
  qualifies to
  `<unit path>.<part>` at every composed root, so a bare-keyed
  addition lands at the root and leaves the claim skipped forever,
  while a path-keyed one evaluates at any root and rides the unit's
  joints. Its `location` is then the unit-local one. Declare those
  assertions freely:
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

Reach for `bd_warehouse` before hand-rolling any standard hardware —
`references/standard_parts.md` has its contents, discovery, and the
thin-wrapper pattern.
