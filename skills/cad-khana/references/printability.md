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
into material, positive an **exit**. Each entry paired with its next
exit is one local thickness. `min_wall_mm` is the minimum over all
such spans, `min_wall_at` the entry point that minimum was measured
from, and `min_wall_alignment` the exit face's projection there.

Two properties follow, and both are deliberate:

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

### What it gets right

- Straight-walled prismatic parts: plates, shells, boxes, simple ribs.
- Any case where the thin dimension is bounded by two roughly-parallel
  faces.

### What it misses or over-reports

- **Wedge tips read as thin walls.** Where two faces meet at a sharp
  edge — a knife-edge runout, a V-groove root, a cone rim — the
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
  not aligned with any face's outward normal (e.g., diagonal pinch
  points), ray-casting inward from face centroids will overestimate
  thickness. A medial-axis approach would catch these; v0 does not.
- **Coarse mesh in curved regions.** At the default tolerance, tight
  curvature (small holes, fillet roots) is represented by few
  triangles. Sample coverage is correspondingly sparse; thinness in
  those regions may be under-sampled.
- **Open or non-manifold shapes.** Behavior is undefined. The library
  assumes a valid closed solid.

### When to trust it

Use `min_wall_mm` as a floor, not a ceiling: if it reports 0.4 mm on a
part you think has 2 mm walls, investigate — and read
`min_wall_alignment` first, since it decides whether "investigate"
means *fix the model* (alignment near 1.0: two parallel faces really
are that close) or *accept a feature tip* (low alignment). If it
reports 2 mm on a part with a hidden diagonal pinch, it may still be
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
90°. Triangles with `overhang_angle > FDM.overhang_max_deg` (default
45°) are candidates. The build-plate face — triangles whose centroid
lies on the minimum-`u` plane and whose normal points straight along
`-u` — is filtered out before reporting. Per part, the diagnostic
reports total flagged area and the maximum overhang angle observed.

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
