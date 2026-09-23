# Mechanism assertions

Load before writing or changing any `assert_*`. What a green run does
*not* tell you is in `SKILL.md` §What a green check does not mean;
field meanings are in `diagnostics.md`.

Every assertion records a result in `mechanism.json`. If any fail,
`check()` prints one line per failure (name + detail) to stderr — the
terminal output alone names every failing assertion; the JSON has the
full context. All failures are collected — you get every problem in one
pass, not just the first. `inspect()` failures print the same way,
prefixed with the part name.

**Under the `khana` CLI the whole script runs, then it exits nonzero
once.** A red part no longer aborts the run, so a script that checks or
inspects many parts leaves *every* diagnostics JSON current in one pass,
and the CLI ends with a roll-up naming each failure and its JSON path.
Run the same script with a bare interpreter and the old behaviour
applies — the first failure raises `SystemExit(1)` — because nothing
there can exit nonzero after the fact. **Prefer `khana check` for
multi-part scripts**; a bare run stops early and leaves the later parts'
JSON stale from a previous run while it still reads as current.

| Assertion | Checks |
|---|---|
| `.assert_no_interference(a, b)` | Parts `a` and `b` don't overlap (intersection volume ≤ 0.001 mm³). |
| `.assert_distance(a, b, min_mm=…, max_mm=…)` | Bounded distance from part `a` to part `b` **or a datum `Plane`**. Either bound alone, or both for "close but not touching" (a gear mesh). See below for `along=` and `grow_*_mm`. |
| `.assert_scalar(name, value, ge=…, le=…)` | A named claim about a non-geometric scalar (friction budget, torque margin). No bounds = pure recorder. |
| `.assert_tangent_contact(a, b, tol_mm=…)` | Parts `a` and `b` **touch**: surface gap ≤ `tol_mm` (default 1e-3, noise allowance — not a design gap) and no real overlap. A gap fails, an overlap fails. See below. |
| `.assert_allowed_contact(a, b, max_overlap_mm3=…, min_overlap_mm3=…)` | Design-intended overlap stays within bounds (a press-fit modeled at its true interference). A gap passes unless `min_overlap_mm3` makes engagement itself the claim. See below. |
| `.assert_solid_count(part, eq=1)` | `part` is exactly `eq` solids. The only claim about **connectivity** — a cut that severs a part leaves its volume, bbox, clearances and every drawn view plausible. `eq=N` declares a part that is several solids on purpose. See below. |
| `.assert_interference(a, b, reason=…)` | Parts `a` and `b` **do** overlap (intersection volume > 0.001 mm³). Regression alarm for a documented, accepted overlap — fails if the overlap disappears, forcing the assertion to be removed when the design gap gets fixed. |
| `.assert_anchors_coincident(a, b, tol_mm=1e-6)` | Two named anchors resolve to the same **position** (orientation ignored) — two units' beliefs about a shared datum agree. See `composition.md` §Named interface anchors. |

Give assertions a `name=` when you'd benefit from a specific label in
the diagnostics; otherwise they get an auto-generated one.

## One piece, or several on purpose

Every part reports `solid_count`, and `khana check` **warns**
(`multi_solid`, never a failure) about any part that is more than one
solid and that no claim speaks for. Nothing else sees this: a pocket
cut one millimetre too deep can detach a lip into a free ring with every
scalar green and every `khana draw` view unchanged. Answer the warning
one of two ways:

```python
a = a.assert_solid_count("body",             # must be one piece — red if severed
                         detail="above 1 the glow band has cut the lip off — "
                                "check the five bridges")
a = a.assert_solid_count("glow_band", eq=5)  # five segments by design; warning goes
```

`detail=` is appended to the count **when the claim fails**, and only
then. Use it: this is the one failure whose cause no drawing shows, so
write it as the failure hypothesis, in the imperative — what would have
severed the part and where to look. It stays out of a passing result
on purpose: on a green `eq=2` the same sentence would read as a report
of the failure. (`assert_scalar`'s `detail` is different — it labels a
value, so it shows either way.)

Derive `eq` from the **design intent the count expresses** (a spoke
count, which sector carries the opening) rather than typing the
number — and **never from the feature whose removal is the red
test**. `eq=len(BRIDGE_DEGS)` tracks the injection: empty the list and
the claim moves with it and stays green, a rubber stamp that looks
identical to a real claim before and after. Where the count has no
source independent of the geometry under test, state the number and
say why in a comment.

`inspect()` answers the same warning in the printability file:

```python
inspect(glow_band(), method=FDM(), name="glow_band", solid_count=5)
```

Declared, the count is a claim like `wall_min` — a `solid_count:5`
entry in `assertions[]` with the count in `value`, a mismatch fails the
run (waivable under kind `solid_count`), and the warning is gone.
Undeclared, a part above one solid keeps warning. There is no way to
silence it without stating the number.

The assembly claim and the `inspect()` claim state one fact twice, so
give them **one derivation**: a constant or a small function in the
declaration module (`sector_solid_count(k, height)`), imported by the
printability script — not the expression copied, which leaves the two
free to drift.

Bodies that touch only along an edge or at a point count as separate
solids — they share no material, and will not print as one part.
**Red-test the claim by removing the bridge, not by shrinking it:** a
0.001 mm bridge is still a bridge, so an epsilon injection leaves it
green. (A bridge that thin is `min_wall`'s to catch, not this claim's.)
It takes no `during=` — the count is the same at every pose.

`assert_interference` is the exception, not the rule. Use it only when
a real design constraint leaves an overlap that hasn't been resolved
yet (e.g., a junction whose bracket hasn't been designed). The
`reason=` string is recorded in `detail` on every run — after the
failure when the overlap goes away — so a reader of a green file sees
why the overlap is there. The same holds for `assert_allowed_contact`
and group `known_overlaps`. Default to `assert_no_interference`
everywhere else.

## Distance and scalar claims

Don't hand-derive from constants what the geometry already knows: a
bare Python `assert` crashes the script (`status: "error"`) instead of
recording a named, diffable result. `assert_distance` /
`assert_scalar` turn those claims into first-class assertions, and
both record their **measured value** in the JSON even on pass, so
`khana diff` reports drift the pass/fail boolean can't see.

Promoting a bare assert is not free, though: it **widens the claim's
scope** from the one pose its constants came from to every pose a
motion builds. See `SKILL.md` §What a green check does not mean.

```python
# gear mesh: close but not touching (min AND max bound)
a = a.assert_distance("ring_gear", "pinion",
                      min_mm=BACKLASH, max_mm=BACKLASH + 0.1)

# directed gap: how far `a` travels along the axis before touching `b`
# (negative once the projections overlap) — axis name or vector,
# read as the direction FROM a TOWARD b, in this assembly's frame (it
# turns with the unit when a parent places it rotated)
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

## Contact claims

Two contact assertions, split by what the design intends:

- **Required contact** — a tangent rest (foot-on-rail, plate-on-flange,
  gear-on-collar) where the parts must touch. `assert_no_interference`
  alone is a trap here: it also passes with the parts floating 3 mm
  apart, so nothing asserts the contact *exists*. Use
  `assert_tangent_contact` — a gap beyond `tol_mm` fails and a real
  overlap fails. When a part must rest against a specific surface,
  assert the tangent contact against the surface it must face; that
  pins the orientation too.
- **Allowed contact** — a press-fit or interference fit. Model the
  **true** interference (don't oversize a bore to appease
  `assert_no_interference` — the model then lies about the fit) and
  declare it with `assert_allowed_contact`. `min_overlap_mm3` makes
  the engagement itself the claim, so the fit drifting back to a
  clearance fit fails loudly.

```python
# tangent rest: must touch, must not overlap (tol is noise allowance)
a = a.assert_tangent_contact("foot", "rail")

# press-fit modeled at true interference. The band comes from one
# honest run, not from arithmetic: overlap volume is interference ×
# diameter × engagement length, so a realistic fit is single-digit mm³
# and a guessed band is wrong by an order of magnitude.
a = a.assert_allowed_contact("drive_pulley_shaft", "hub_shaft_stub",
                             min_overlap_mm3=1.5, max_overlap_mm3=2.6,
                             reason="press fit, 0.02 mm diametral on Ø8")
```

Both record a measured value in the JSON even on pass (`tangent`: the
gap in mm; `allowed`: the overlap volume in mm³), so `khana diff` sees
drift. A tangent pair has no overlap, so it coexists with group
`assert_no_interference_*` checks; an allowed-contact pair genuinely
overlaps, and group checks skip it automatically — the declaration is
the whole of it, with no `suppressed=` entry to keep in step (see
[Group assertions](#group-assertions)).

**Contact that only happens in one phase of a motion** — a lifter pad
against the platform it lifts, a cam against its follower — takes a
`during=` window instead of being suppressed at every frame:

```python
from cad_khana.mechanism.assertions import JointWindow

a = a.assert_allowed_contact(
    "platform.frame", "servo_arm.arm", max_overlap_mm3=20,
    during=JointWindow("rotor.platform", 5.4, 22.5),
    reason="servo pad lifts the platform's drop block",
)
```

Inside the window the overlap band applies; **outside it the pair is
held to plain no-interference**, so the same contact appearing at rest
fails instead of passing unnoticed. That is the whole difference
between declaring a contact and suppressing a pair: a suppressed pair
is blind at every frame.

Window the **joint angle, not `t`**. The joint is the physical DOF, so
re-timing the animation can't invalidate the claim — and a contact that
recurs at several parameters (a pad touched on the way up and again on
the way down) is usually *one* angle window even though it is two
disjoint `t` intervals. Derive the window from geometry with
`classify` (`motion.md` §Sweep diagnostics) rather than guessing it; if the joint is absent from
a run, the assertion skips like an absent part.

**`during=` works on every part-referencing assertion** — the
single-pair forms and both group forms — and takes one `JointWindow` or
a tuple that must *all* hold (a claim true only "with the platform
level **and** the arm down" is two joints). What "outside the window"
means follows from the kind of claim:

- A **requirement** (`assert_no_interference`, `assert_distance`,
  `assert_tangent_contact`, `assert_interference`)
  **lapses**: `passed: null`, `skipped: "out_of_phase"`. Use it for a
  claim that is only meant at rest — without `during=`, a claim held
  over a motion is a claim about *every* pose of it.
- A **permission** (`assert_allowed_contact`) lapses to the default it
  was an exception to — no contact — **unless another contact claim on
  the same pair is in phase there**, which then governs. Phased contact
  claims on one pair partition the motion:

```python
a = (
    a.assert_allowed_contact(pad, block, max_overlap_mm3=20,
                             during=JointWindow("rotor.platform", 5.4, 22.5))
    .assert_allowed_contact(pad, block, min_overlap_mm3=4, max_overlap_mm3=20,
                            during=JointWindow("rotor.platform", 12.0, 18.0))
)   # may touch in the wide window, MUST engage in the narrow one
```

The phase is part of an auto-generated name (`…@rotor.platform
[5.4, 22.5]deg`), so claims on one pair in different phases don't
collide.

## Group assertions

When "assert every pair" is the intent, say so — don't hand-write the
double loop:

| Assertion | Expands to |
|---|---|
| `.assert_no_interference_between(group_a, group_b, …)` | One `assert_no_interference` per cross pair `(a, b)`. |
| `.assert_no_interference_within(group, …)` | One per unordered pair inside `group` (`i < j` in group order). |

A group is an iterable of part paths, or a **dotted sub-assembly path**
(`"turret.rotor"`) selecting every part under that subtree — expanded
to full paths from the asserting assembly's root
(`"turret.rotor.arm.spider"`), sorted. The two mix: a sub-assembly
path inside the iterable expands in place. Expansion is a macro over the
current contents — parts added afterwards aren't covered, so declare
group assertions after composition.

Both take two keyword options:

- `known_overlaps=[(a, b, reason), …]` — downgrades those pairs
  (order-independent) to `assert_interference(reason=…)` regression
  alarms.
- `suppressed=[(a, b), …]` — skips those pairs entirely (e.g. a
  design-intended contact during motion with no clean per-frame
  predicate).

Pairs carrying an `assert_allowed_contact` are skipped **without being
listed** — the contact assertion already holds the pair at every frame
(inside its window to the overlap band, outside it to plain
no-interference), so re-emitting `no_interference` there could only
contradict it. Don't restate them in `suppressed=`: that is
bookkeeping to keep in step, and it goes *wider* than the claim — a
suppression is blind at every frame where a phased claim is not.
Naming the pair in `known_overlaps=` overrides the skip, if you want
the regression alarm too.

The skip is resolved over the whole assembled assertion set, so the
contact may be declared anywhere — before or after the group call, at
this level or a nested one. Unlike group *membership*, it is not a
macro over the state at the call, and adds no ordering rule beyond
"after composition". A hand-written `assert_no_interference` on a
contact pair is never skipped: that contradiction is yours to see.

Expanded assertions are the plain single-pair forms with their usual
auto-names, so migrating a hand-written loop to a group call leaves
`mechanism.json` unchanged — provided the loop wrote each pair in the
order the group emits it (`_between`: `group_a` side first; `_within`:
list order; a subtree path: sorted). A name is `no_interference:a/b`, so
a reversed pair renames the claim and `khana diff` reports it.
