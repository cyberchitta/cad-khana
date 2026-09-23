# Diagnostics JSON: field meanings

Load before reading a field beyond `status`, `assertions[].passed`,
`skipped_counts` and `warnings`. Every warning kind is listed, with
what it means, in `SKILL.md` §Read `warnings` on every run — that list
is not repeated here.

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
- `parts[name].solid_count` — `1` for a part in one piece. Above `1`
  something is detached (or touches only along an edge); see
  `multi_solid` in `SKILL.md` §Read `warnings` on every run.
- `interferences` — list of overlapping part pairs with volume +
  centroid, **at the as-built pose only**, motion or no motion.
- `motions` — one entry per declared motion: `samples`, and per driven
  joint the range covered and `max_step`, the widest gap between
  adjacent samples. Empty means every green below is a one-pose green.
- `skipped_counts` — how many assertions were skipped, per class, every
  class always listed. **Read it on every green run**: a nonzero count
  is a claim that did not look. It should drop to zero at the root
  where the detail is applied; one that never does is a typo or an
  addition keyed to the wrong level.
- `assertions` — one entry per declared assertion; `passed` + `detail`
  + `value`. `passed` is `true`/`false`/`null`: `null` means the
  assertion was skipped because a part it references is absent from
  this run (`detail` names the missing parts) — normal for assertions
  against override-added detail parts in a standalone run. `skipped`
  classes the reason (`"absent_part"` | `"absent_joint"` |
  `"out_of_phase"` — a phased claim in phase at no pose looked at;
  `null` when the assertion was evaluated). Skips never fail the run; watch for an
  assertion that is *always* skipped, which usually means a typo'd
  part name. `value` is the measured/claimed scalar, recorded **even on
  pass** so `khana diff` reports its drift: the distance for
  `assert_distance`, the claimed number for `assert_scalar`, the gap in
  mm for `assert_tangent_contact`, the overlap in mm³ for
  `assert_allowed_contact`, the count for `assert_solid_count`. It is
  `null` for the boolean-only kinds — `assert_no_interference`,
  `assert_interference` and `assert_anchors_coincident` record **no
  measurement**, only a verdict.
  Held over a motion, `value` and `detail` are the **worst pose's**
  (least slack to the claim's own bound; for a kind with no measured
  value, the first failing pose — the onset).
- `assertions[].poses` — `evaluated` (poses the verdict covers: `1`
  means it looked once), `distinct` (evaluations actually run — `1`
  under a motion means **the motion never moves this claim**, so it
  tests nothing about it), `in_phase`, `failed`. Two kinds read
  `distinct: 1` under every motion and are right to: `assert_scalar`
  and `assert_solid_count` claim nothing a pose can change. You no
  longer have to audit this field by hand — `motions[].moved` /
  `.movable` roll it up per motion and exclude those two kinds.
  `moved` counts a claim the motion moved **or carried across a
  `during=` phase boundary**, so it can exceed the number of claims
  reading `distinct > 1`: a phased claim in phase at a single pose was
  exercised by the motion and is counted, though it was evaluated once.
  Don't reconcile a hand-audited count from before 0.13 against it.
- `assertions[].worst_at` — `{motion, t, joints_deg}` of the worst
  pose; `null` when that is the as-built pose. Re-create it with
  `assembly.posed(joints_deg)` to draw or inspect it.

- `warnings` — see `SKILL.md` §Read `warnings` on every run.

`<name>-printability.json` after every `inspect()`:

- `kind: "printability"` — identifies the file.
- `name`, `method` — for disambiguation when scripts inspect many parts.
- `volume_mm3`, `bbox` — basic part metrics.
- `solid_count` — `1` for a part in one piece; above `1` the file also
  carries a `multi_solid` warning unless `inspect(..., solid_count=N)`
  declared the count, in which case `assertions` carries
  `solid_count:N` instead.
- `min_wall_mm` — thinnest wall found by ray sampling; `null` if
  unmeasurable.
- `min_wall_at` — `[x, y, z]` surface point where the thinnest wall was
  measured (`null` when `min_wall_mm` is); use it to attribute a thin
  reading to a concrete feature instead of bisecting parameters. The
  failing `wall_min:…` assertion repeats it in its `detail`.
- `min_wall_alignment` — how parallel the two surfaces bounding the
  measurement are: `1.0` is a slab with parallel faces, falling toward
  `0` as they splay apart. Read it before writing a waiver. A low value
  (below ~0.7) means the minimum sits at the **tip of a wedge feature**
  — a knife edge, a V-groove root, a rib runout — where the material
  really is that thin but the number isn't a wall thickness. A value
  near `1.0` means two near-parallel faces genuinely are that far
  apart, so a tiny reading is a **real sliver in the model**, not a
  measurement artifact — investigate the geometry rather than waiving it.
  This one number decides the question because every reading is taken
  perpendicular to the face it starts from (see `SKILL.md` §Known limitations),
  so only the far side's angle is ever in doubt.
- `overhang` — `{area_mm2, max_angle_deg}`, or `null` when no face
  (off the build plate) points down at all. `max_angle_deg` is the
  steepest downward face **whatever the threshold**; `area_mm2` counts
  only faces past `overhang_max_deg`, so it is `0.0` when none are.
  Raising the threshold stops the failure, never the reading.
- `assertions` — `wall_min:…` and `overhang_max:…` entries, plus
  `solid_count:N` when the count was declared; `passed` + `detail`,
  plus `waived` (the rationale) when a failure was waived.

- `warnings` — see `SKILL.md` §Read `warnings` on every run.
