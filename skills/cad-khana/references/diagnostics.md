# Diagnostics JSON: field meanings

Load before reading a field beyond `status`, `assertions[].passed`,
`skipped_counts` and `warnings`. Every warning kind is listed, with
what it means, in `SKILL.md` §Read `warnings` on every run — that list
is not repeated here.

`khana show <file>` reads either file from the shell — a summary, then
its claims filtered, sorted or grouped; see `references/cli.md`.

`mechanism.json` after every `check()`:

- `status` — `"ok"`, `"error"`, or `"assertion_failed"`.
- `error` — traceback string if the script itself crashed.
- `hint` — short pattern-matched repair suggestion when `status` is
  `"error"`; `null` otherwise. Read this first before parsing the
  traceback — it resolves the most common errors in one line.
- `selection` — `null` on a whole-model run. On a **partial run**
  (`khana check --only <glob>`), `{only, declared, evaluated,
  not_computed}`: the name globs as given, the tree's assertion count
  and how many the globs kept, and the fields left `null` —
  `["interferences"]`. `assertions`, `skipped_counts` and
  `motions[].moved` / `.movable` then cover the selected claims only,
  and `status: "ok"` means *those* held. The file also carries a
  `partial_run` warning; `khana diff` refuses it against a file of a
  different selection.
- `parts[name].volume_mm3` — sanity-check a part is not empty.
- `parts[name].bbox` — sanity-check on size and placement.
- `parts[name].face_count` / `edge_count` / `vertex_count` — cheapest
  way to verify a boolean operation changed geometry: counts shift on
  success, stay the same on a silent no-op or OCCT failure.
- `parts[name].solid_count` — `1` for a part in one piece. Above `1`
  something is detached (or touches only along an edge); see
  `multi_solid` in `SKILL.md` §Read `warnings` on every run.
- `interferences` — list of overlapping part pairs with volume +
  centroid, **at the as-built pose only**, motion or no motion. `null`
  on a partial run: the all-pairs pass did not run, which `[]` (ran,
  found none) would misstate.
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
  `assert_distance` (0 when overlapping), the least distance over the
  claim's parts for `assert_clear_of` (0 when one overlaps; measured past
  the seat under `seat=`, and `null` when no part has material there),
  the claimed number for `assert_scalar`, the gap in
  mm for `assert_tangent_contact`, the overlap in mm³ for
  `assert_allowed_contact`, the count for `assert_solid_count`. It is
  `null` for the boolean-only kinds — `assert_no_interference`,
  `assert_interference` and `assert_anchors_coincident` record **no
  measurement**, only a verdict.
  Held over a motion, `value` and `detail` are the **worst pose's**
  (least slack to the claim's own bound; for a kind with no measured
  value, the first failing pose — the onset).
- `assertions[].measured` — how many parts a claim that folds several
  into one result measured: the selection size for `assert_clear_of`,
  on pass and fail alike (`excluding` applied, parts wholly on the
  seat side counted). `null` for every other kind and on a skip. A
  selection that shrank — a renamed subtree, a wider `excluding` —
  keeps the claim green; `khana diff` reports the count's change.
- `assertions[].witness_mm` — the nearest pair a distance was read
  between, `[[x, y, z] on a, [x, y, z] on b]` in the root frame at the
  reported pose (`worst_at`'s, or as built), for `assert_distance`
  between two parts with no `along=`; pass and fail alike, on the
  modelled surfaces (before any `grow_*_mm`). `null` for every other
  kind, and for a directed or datum-plane distance, which is read off a
  projection rather than between two points. A feature that becomes
  the nearest pair can leave the value nearly where it was and the
  claim green while it now measures something else; `khana diff` shows
  the points beside a value change, and alone when only they moved.
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
- `method_params` — every field of the method the script passed, as
  declared: for `FDM`, `{up_axis, wall_min_mm, overhang_max_deg}`.
  `up_axis` is the vector as written (not normalised), so this is where
  a green says which way up it was measured — an on-its-side pass
  (`up_axis: [0, -1, 0]`) reads differently from an as-placed one.
  `khana diff` lists each parameter that changed under `method_params:`.
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
- `overhang` — `{area_mm2, max_angle_deg, regions}`, or `null` when no face
  (off the build plate) points down at all. `max_angle_deg` is the
  steepest downward face **whatever the threshold**; `area_mm2` counts
  only faces past `overhang_max_deg`, so it is `0.0` when none are.
  Raising the threshold stops the failure, never the reading.
  `regions` says where that area sits: one entry per B-rep face with
  area past the threshold — `{area_mm2, max_angle_deg, centroid_mm,
  bbox}` over that face's counted facets — largest first. Every face is
  listed, however small (a 0.42 mm² first-layer sliver shows as what it
  is), so the regions' `area_mm2` sum to the block's. Regions follow
  the model's faces, so a crown that is two faces there is two regions.
  `[]` when `area_mm2` is `0.0`. The failing `overhang_max` assertion's
  `detail` names the region count and the largest region's area and
  centroid. `khana diff` matches regions by centroid to 0.01 mm: one
  that kept its place and changed area reads `region changed`; one that
  moved reads as `region removed` plus `region added`.
- `assertions` — `wall_min:…` and `overhang_max:…` entries, plus
  `solid_count:N` when the count was declared; `passed` + `detail`,
  plus `waived` (the rationale) when a failure was waived. A `Waiver`
  with bounds appends to `detail`: `— within the waiver's …` when it
  applied, `; waiver not applied: …` naming each broken bound when it
  did not (then `waived` is `null` and the failure counts). Under
  `features=`, `waived` joins each covering feature's reason
  (`seat: …; pin_bores: …`) and `detail` ends `— waived by feature …`;
  what the features leave is counted in `detail`, `; not waived: N
  regions no feature waives, worst …`, naming each end of the worst with
  the features it traces to, then every reason (see `printability.md`).

- `warnings` — see `SKILL.md` §Read `warnings` on every run.
