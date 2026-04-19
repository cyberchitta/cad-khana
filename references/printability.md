# Printability diagnostics

How `cad_khana` computes wall thickness and overhangs, and where these
approximations break down. Keep this honest — false confidence from a
bad diagnostic is worse than no diagnostic.

## Minimum wall thickness

### Algorithm

Tessellate each part (mesh tolerance `TESSELLATION_TOLERANCE_MM`,
angular tolerance `TESSELLATION_ANGULAR_TOLERANCE`). For every triangle,
take its centroid and outward normal; cast an `Axis` from a point just
inside the surface along the inward normal; take the nearest forward
hit on the part as the local wall thickness. The part's `min_wall_mm`
is the minimum over all samples.

### What it gets right

- Straight-walled prismatic parts: plates, shells, boxes, simple ribs.
- Any case where the thin dimension is bounded by two roughly-parallel
  faces.

### What it misses or over-reports

- **Sliver triangles near edges.** Tessellation near convex edges can
  produce small triangles whose centroid is close to an adjacent face.
  The inward ray may hit that adjacent face at a short distance and
  report a misleadingly small wall — especially for chamfered or
  filleted edges. Expect some noise at sharp geometric transitions.
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
part you think has 2 mm walls, investigate. If it reports 2 mm on a
part with a hidden diagonal pinch, it may still be wrong.

## Overhangs

### Algorithm

Tessellate each part. For each triangle with outward normal `N`,
compute the overhang angle from vertical:

```
overhang_angle = asin(max(0, -N_z))
```

A vertical wall gives 0°, a horizontal downward-facing ceiling gives
90°. Triangles with `overhang_angle > OVERHANG_ANGLE_THRESHOLD_DEG`
(default 45°) are flagged. Per part, the diagnostic reports total
flagged area and the maximum overhang angle observed.

### What it gets right

- Catches horizontal ceilings, steep overhangs, and downward-slanted
  faces past the threshold.

### What it misses or over-reports

- **No build-plate awareness.** A part's bottom face (resting on the
  plate) is flagged as a 90° overhang even though the printer
  supports it. The diagnostic does not know the orientation the user
  intends to print in.
- **No support-from-below check.** A downward-facing face with solid
  material directly beneath it (e.g., the ceiling of an enclosed
  cavity printed last) is still flagged. Most slicers also flag these
  for safety, so the false positive is usually harmless.
- **Threshold is fixed.** 45° is a common default but printer- and
  material-specific. A follow-up should make this configurable per
  build.
- **Area aggregation is coarse.** A single per-part entry tells you
  there's an overhang but not where. Callers who need location
  information should iterate the tessellation themselves.

### When to trust it

Useful as a first-pass "did I accidentally design a ceiling?" check.
Not a substitute for a slicer's support-generation preview.
