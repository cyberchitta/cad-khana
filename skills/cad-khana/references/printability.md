# Printability diagnostics

How `cad_khana` computes wall thickness and overhangs, and where these
approximations break down. Keep this honest — false confidence from a
bad diagnostic is worse than no diagnostic.

Entry point: `inspect(part, method=FDM(), out="outputs", name=…)` from
`cad_khana.printability.inspect`. The `FDM` method object carries the
wall-thickness floor, overhang threshold, and print `up_axis`; see
`cad_khana.printability.methods`.

## Minimum wall thickness

### Algorithm

Tessellate the part (mesh tolerance `TESSELLATION_TOLERANCE_MM`,
angular tolerance `TESSELLATION_ANGULAR_TOLERANCE`, shared with the
overhang check in `cad_khana.core.tessellation`). For every triangle,
take its centroid and outward normal, and cast an `Axis` along the
inward normal — from an origin backed off `BACKOFF_MM` *outside* the
surface. Collect every crossing of the solid, classifying each by its
face's outward normal projected on the ray: negative is an **entry**
into material, positive an **exit**. The ray's *first* crossing is its
entry through the facet it was cast for; paired with the next exit,
that span is the local thickness of the wall the facet sits on. Each
ray contributes exactly that one sample.

Facet rays only measure a thin direction some facet *faces*. At a
sharp concave edge or point — a V-groove root, a conical pocket's apex
— none does, and the flat face opposite is a few large facets with no
centroid under the feature, so the thinnest material in the part would
go unsampled from both sides. Such **creases** are found in the mesh
(two facets sharing an edge or a corner, meeting concavely at more than
the angular tolerance) and get rays of their own: from points along the
crease, at most `CREASE_STEP_MM` apart, in a fan of directions between
the two facets' inward normals, no more than the angular tolerance
apart. Those are the rays a fillet's facets would have cast there, in
the limit of zero radius. Convex creases get none — thickness peaks at
a ridge, it does not dip. A fan direction is cast only if it also heads
inward of every *other* facet at the same mesh edge or corner: where a
groove runs out through a side face, or two blocks touch along a line,
the pair's concavity alone does not put material in front of the ray.

`min_wall_mm` is the minimum over all rays, `min_wall_at` the point
that minimum was measured from (the entry point of a facet ray, the
point on the crease for a crease ray), and `min_wall_alignment` the
exit face's projection there.

Three properties follow, and all three are deliberate:

- **A reading always spans material actually traversed.** The origin
  is backed off because a facet centroid sags into the void by up to
  the tessellation tolerance on curved faces; a ray started at the
  centroid re-hits the surface it came from within that distance,
  which reads as a wall a fraction of a millimetre thick. The error
  grows with the facet chord, so it got *worse* on larger radii — the
  source of the sub-0.2 mm readings on large-radius annuli that were
  historically waived as "ray-sampling artifacts". Pairing also
  removes a systematic underestimate on curved and tapered walls
  (a 1.2 mm wall on a Ø120 tube read 1.05 mm before; it now reads
  1.2004 mm).
- **Rays are rejected on geometric grounds only, never by magnitude.**
  There is no quantile, no robustness statistic and no alignment
  threshold, because every one of those trades a false positive for
  the chance of hiding a genuine thin region — the worse failure for
  a printability check. A thin reading is therefore always real
  material; `min_wall_alignment` tells you *what kind*.
- **A reading is always normal to the surface it starts from** —
  perpendicular to its facet, or within a crease's fan of normals. A
  ray carries on for the whole depth of the part, and each later entry
  is into some *other* feature downstream, crossed at whatever oblique
  angle the originating facet happens to make with it. Those chords are
  real material but say nothing about the feature's thickness, and a
  grazed corner yields an arbitrarily short one — an unrelated 20×6 mm
  plate clipped at 75° reported 0.09 mm. Counting only the originating
  span costs no coverage, because every face is sampled from its own
  facets. It is also what makes `min_wall_alignment` readable on its
  own: the entry angle is fixed at -1, so only the exit is in doubt. A
  crease ray starts on an edge, which has no entry angle, but the
  shortest span in its fan is the one meeting the face opposite most
  squarely, so it reads the same way — a 90° groove leaving a 0.5 mm web
  reads 0.5 at alignment 0.99–1.0 with the floor opposite level or
  tilted up to 60°.

### What it gets right

- Straight-walled prismatic parts: plates, shells, boxes, simple ribs.
- Any case where the thin dimension is bounded by two roughly-parallel
  faces.

### What it misses or over-reports

- **Wedge tips read as thin walls.** Where two faces meet at a sharp
  convex edge — a knife-edge runout, a cone rim — the
  material path across the wedge near its tip really is short, so the
  minimum lands there and is *not* a measurement error. It is also not
  a wall thickness. `min_wall_alignment` is the discriminator: below
  ~0.7 the bounding faces splay apart and the reading is a wedge tip;
  near 1.0 they are parallel and the reading is a genuine wall (or, if
  it is tiny, a genuine sliver in the model). Filtering these out was
  measured and rejected — the alignment threshold that suppresses a
  cone rim (0.87) also discards a legitimate 45°-tapered rib.
- **A floor at `MIN_SPAN_MM` (1e-4 mm).** Spans below it are dropped as
  tangency noise. Far below any printable feature, but it is a floor.
- **Non-perpendicular thinness.** If a wall's thinnest cross-section is
  not aligned with any surface normal at either end (e.g., a diagonal
  pinch between two convex edges), ray-casting overestimates thickness.
  A medial-axis approach would catch these; v0 does not. Sharp concave
  edges and points *are* covered, by the crease rays above — before
  them a 90° V-groove leaving 0.5 mm of a 4 mm plate read 2.36 mm.
- **Crease rays are sampled along the crease.** Where the material
  under a straight crease thins along its length — a groove running
  downhill toward the opposite face, two grooves crossing back to back
  — the reading is high by up to half of `CREASE_STEP_MM` times the
  slope. A crease parallel to the face opposite, the usual score-line
  or living-hinge case, reads exactly.
- **Coarse mesh in curved regions.** At the default tolerance, tight
  curvature (small holes, fillet roots) is represented by few
  triangles. Sample coverage is correspondingly sparse; thinness in
  those regions may be under-sampled.
- **Open or non-manifold shapes.** Behavior is undefined. The library
  assumes a valid closed solid.

### When to trust it

Use `min_wall_mm` as a floor, not a ceiling: if it reports 0.4 mm on a
part you think has 2 mm walls, investigate — and read
`min_wall_alignment` first, since it says what you are looking for:
near 1.0, two parallel faces really are that close, a sliver to fix;
low, the tip of a wedge. It does not say whether the wedge matters. Two
faces meeting at 48° is an ordinary edge; a wall that runs out to a
knife edge over its whole height is a feathered fin. Both read low. Look at the witness point before waiving. If
it reports 2 mm on a part with a hidden diagonal pinch, it may still be
wrong.

## Overhangs

### Algorithm

Tessellate each part. For each triangle with outward normal `N` and
print-orientation up vector `u` (from `FDM.up_axis`), compute the
overhang angle from vertical:

```
overhang_angle = asin(max(0, -N · u))
```

A vertical wall gives 0°, a horizontal downward-facing ceiling gives
90°. Two kinds of triangle are dropped first: the build-plate face —
triangles whose centroid lies on the minimum-`u` plane and whose normal
points straight along `-u` — and triangles within
`FACING_DOWN_EPSILON_DEG` (1e-6°) of vertical, which is solver noise on
a wall (a tessellated cylinder reads ~1e-16°), not a face pointing
down. Over what remains, the diagnostic reports `max_angle_deg`, the
steepest downward-facing triangle **whatever the threshold**, and
`area_mm2`, the area of triangles with `overhang_angle >
FDM.overhang_max_deg` (default 45°) — `0.0` when none are. The
threshold decides the pass and which area counts, never whether the
reading exists: raising it to 90° leaves a ceiling reading
`max_angle_deg: 90.0` with no area. The block is `null` only when no
triangle faces down at all.

### What it gets right

- Catches horizontal ceilings, steep overhangs, and downward-slanted
  faces past the threshold.
- **Build-plate face excluded.** Triangles whose centroids lie on the
  min-`up_axis` plane and whose normals point straight into it are
  recognized as the build-plate face and not flagged.

### What it misses or over-reports

- **No support-from-below check.** A downward-facing face with solid
  material directly beneath it (e.g., the ceiling of an enclosed
  cavity printed last) is still flagged. Most slicers also flag these
  for safety, so the false positive is usually harmless.
- **Build-plate test is centroid-based.** Tessellated triangles of a
  curved bottom face have centroids slightly above the minimum of the
  bounding box; those triangles are still flagged. Truly flat bottoms
  (axis-aligned with `up_axis`) are handled cleanly.
- **Threshold is per-part, not global.** Set via
  `FDM(overhang_max_deg=…)`. 45° is a common default but printer- and
  material-specific.
- **Area aggregation is coarse.** A single per-part entry tells you
  there's an overhang but not where. Callers who need location
  information should iterate the tessellation themselves.

### When to trust it

Useful as a first-pass "did I accidentally design a ceiling?" check.
Not a substitute for a slicer's support-generation preview.
