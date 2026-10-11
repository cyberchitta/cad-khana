# Photo-real rendering (`cad_khana.render`)

`cad_khana.render` produces photo-real PNG renders of multi-part
Build123d assemblies with one function call. The rest of cad-khana
checks the geometry (diagnostics, hidden-line drawings); this layer
makes the staged, lit, materialed shot a human or website visitor
sees, from the same `Assembly` the claims were held on.

It is an optional extra, because Blender's wheel is about 700 MB:

```
uv add 'cad-khana[render]'
```

Without it every other `khana` verb still runs, and a render call
fails at `import bpy`.

## When to use this tool

- Producing a **photo-real render** of a finished Build123d assembly
  (printed plastic, anodized aluminium, steel hardware, rubber GT2
  belts, motor casings — the typical 3D-printed-mechanism subject).
- A **build-in-public artifact**: a portfolio shot, a hero image on a
  product site, a press image.
- The render needs to look real enough that humans recognize the
  materials at a glance.

## When not to use it

- **Diagnostics or geometry checks.** Use `khana check` and `khana
  draw`. Hidden-line PNGs are far cheaper and answer "is the tang
  pointing the right way" better than a photo-real render does.
- **Custom material authoring** beyond the built-in table. Add a new
  entry to `cad_khana.render.materials` rather than authoring inline.
- **CAM / toolpath visualization.** Out of scope.

## CLI

A render script is a command script, so it runs under `khana run`:

```
khana run <script>   # runs the script, writes <out>/render.png
```

It exits nonzero with a traceback if the script fails, and then also
writes `mechanism.json` with `status: "error"` beside the script, as
`khana run` does for any script.

**Output location.** A relative `out=` passed to `render()` inside a
script is anchored to the script file's directory, so `out="renders"`
lands next to the script regardless of the cwd you invoked `khana`
from. Pass an absolute path to override, or `--out-root <dir>` to move
every relative `out=` of the run under one directory.

## Script structure

Keep three sections, in order:

1. **Pure part functions** — each returns a `Part`. Take parameters
   with defaults; no hidden globals, no mutation.
2. **Scene composition** — build a `Scene` by chaining `.add()` calls
   that name each part, place it, and assign a material.
3. **Render call** — `render(scene, out="renders", resolution=…)`.

## Minimal skeleton

```python
from build123d import Box, Cylinder, Location, Part, Pos, Rot

from cad_khana.render.scene import Scene
from cad_khana.render.render import render

def bracket(w: float = 40, h: float = 20) -> Part:
    return Pos(0, 0, h / 2) * Box(w, w, h)

def pin(length: float = 40, d: float = 3) -> Part:
    return Cylinder(d / 2, length)

scene = (
    Scene()
    .add("bracket", bracket(), material="pla_matte", color=(0.85, 0.15, 0.15))
    .add("pin", pin(),
         location=Location((0, 0, 10)) * Rot(90, 0, 0),
         material="steel")
)

if __name__ == "__main__":
    render(scene, out="renders", resolution=(1920, 1080))
```

## Adapting an existing cad-khana assembly

If the design already lives in a `cad_khana.mechanism.assembly.Assembly`,
adapt it directly so the source of truth stays single:

```python
from cad_khana.mechanism.assembly import Assembly

from cad_khana.render.scene import Scene
from cad_khana.render.render import render

# `assembly` was built by the cad-khana script with .add()/.assert_*()
scene = Scene.from_assembly(assembly).with_materials({
    "bracket": "pla_matte",
    "pin":     "steel",
})
render(scene, out="renders", resolution=(1920, 1080))
```

The adapter copies names, parts, locations, and per-part `Color`. You
then attach materials by name. Anything without an explicit material
falls back to `pla_matte` in the part's color.

## Recommended style

These conventions make a render script **re-editable** — the next
session can bump a parameter or swap a material and the output updates
consistently.

- **One material per part.** This is a hard contract, not a
  recommendation: faces don't get individually painted.
- **Pick materials from the table.** Don't hand-author Cycles node
  graphs in the script. If a material is missing, add it to
  `cad_khana.render.materials` and reference it by name.
- **Color is a property of the placement, not the part.** Same as
  cad-khana: the part function builds canonical geometry; placement
  carries `material=` and `color=`. This lets the same `bracket()`
  appear four times in different colors without duplicating geometry
  code.
- **Don't author lighting in user scripts.** The default studio rig
  works for ~all CAD subjects; if you genuinely need a different rig,
  add a named preset to `cad_khana.render.lighting`. Two presets ship:
  `lighting.DEFAULT` (flat grey + world-fixed sun key — cheap,
  deterministic, no external dependencies) and `lighting.DEFAULT_HDRI`
  (Blender-bundled Polyhaven `studio_small_01.exr`, HDRI-only — no
  added sun lights because a multi-softbox HDRI already carries
  directional + omnidirectional energy, and adding SUN lamps on top
  stacks redundant energy that washes out metallic contrast). Switch
  by passing `rig=lighting.DEFAULT_HDRI` to `render(...)` /
  `render_animation(...)`. For a different bundled environment, build
  `StudioRig(..., world_hdri="interior")` — valid names live in
  `lighting.BUNDLED_HDRI_NAMES`. A custom .exr is `world_hdri=Path("…")`.
- **Key + fill slots are opt-in for the cases where they earn their
  keep.** `StudioRig.key` and `StudioRig.fill` are `KeyLight | None`;
  set them when (a) there's no HDRI and you need discrete lights, or
  (b) the HDRI is genuinely uniform (no built-in softbox structure)
  and the subject needs an added shadow direction. The fill light's
  `camera_parented=True` mode rigidly attaches it to the camera so
  its direction relative to the frame stays fixed through any
  animation — useful for "on-camera light" shots when key + fill is
  doing all the work without an HDRI.
- **Pick a framing strategy by name.** The default `HERO_3Q` auto-frames
  a 3/4 view of the bbox; pass `framing=FixedPose(...)`, `framing=ORTHO_SIX`,
  or `framing=TURNTABLE_24` from `cad_khana.render.framing` for sensor-pose
  shots, six-view ortho sheets, or turntables. Don't hand-author bpy
  cameras in user scripts.

## Material table (v0)

The table lives in `cad_khana.render.materials` and is intentionally small.
Reach for these names from a script:

- `pla_matte` — typical FDM/SLA finish; takes a `color=` from the
  placement.
- `pla_glossy` — lightly polished plastic; takes a `color=`.
- `aluminium_anodized` — brushed-aluminium look; color tints the
  anodize.
- `cast_aluminium_dark` — dark cast-aluminium / motor-casing finish;
  intrinsic color (not overridable).
- `steel` — bright machined steel hardware (bolts, shafts, pins).
- `rubber` — matte black rubber (GT2 belts, grommets, feet).
- `acrylic_clear` — clear cast acrylic; transmissive, IOR 1.49.
- `mirror_first_surface` — aluminised first-surface mirror (no
  double-image); intrinsic color.

Add new materials in `materials.py` rather than inline.

## Framing strategies

`render(...)` takes a `framing=` argument that drives the camera. The
named presets in `cad_khana.render.framing` cover the common cases:

- `HERO_3Q` *(default)* — auto-fits the bbox from a 3/4 front-right-up
  angle. One PNG → `<out>/render.png`.
- `ORTHO_SIX` — six orthographic views (front, back, right, left, top,
  bottom). Six PNGs → `<out>/frame_000.png` … `frame_005.png`.
- `TURNTABLE_24` — 24 perspective frames orbiting the scene's up axis
  at 20° elevation. → `frame_000.png` … `frame_023.png`.

For an explicit camera pose (e.g. matching a real sensor), construct a
`FixedPose`:

```python
from cad_khana.render.framing import FixedPose
from cad_khana.render.render import render

render(
    scene,
    framing=FixedPose(
        location=(0, -226.6, 105.7),
        target=(0, 0, 0),
        vertical_fov_deg=55.0,
    ),
    world_up=(0, 0, 1),
)
```

Strategy direction vectors are written in a *canonical* (Y-up) frame —
they auto-rotate to match `world_up`, so the same `HERO_3Q` works for
both Y-up (default) and Z-up scenes. `render(...)` returns a
`list[Path]`; single-frame strategies return a one-element list.

## Resolution presets

Pass `resolution=(W, H)` explicitly. Common targets:

- `(1920, 1080)` — full HD landscape, default for hero shots.
- `(1080, 1920)` — portrait, for mobile-first product pages.
- `(2048, 2048)` — square, for grid layouts.
- `(960, 540)` — half-HD draft for fast iteration.


## glTF / GLB export

`cad_khana.render.export.export_glb(scene, ...)` writes the same `Scene` you'd
pass to `render()` as a glTF 2.0 binary, suitable for embedding via
Google's `<model-viewer>` or three.js. Materials come through the same
Cycles Principled BSDF path; Blender's built-in exporter bakes them to
glTF PBR (baseColor / metallic-roughness / IOR / transmission).

```python
from cad_khana.render.export import export_glb
from cad_khana.render.scene import Scene

scene = Scene().add(...).add(...).with_materials(...)
export_glb(scene, out="renders", name="model.glb")
```

`draco_compression=True` (default) typically shrinks a CAD GLB 5–10×
with no visible quality loss; `<model-viewer>` and three.js ship Draco
decoders, so consumers get the decompression for free.
`draco_level` 0–10 trades encode time and size (default 6 is the sweet
spot for static CAD).

## Animation (mp4)

Two entry points in `cad_khana.render.animation`, both producing an mp4:

```python
from cad_khana.render.animation import render_animation, render_animation_from_glb
from cad_khana.render.framing import FixedPose
```

**Photo-real path — `render_animation(factory, ts, ...)`.** Mirrors
cad-khana's `export_animated_glb` signature. Sweeps `factory(t)` over
`ts`, rebuilds the scene per frame, renders each with the
full material catalog under Cycles. The look matches `render()` on
the same Scene; the cost is also per-frame Cycles render + per-frame
Scene rebuild.

```python
def scene_at(t: float) -> Scene:
    return build_my_scene(t)              # returns a render Scene

def cam(t: float) -> FixedPose:
    return FixedPose(location=orbit(t), target=(0, 0, 30),
                     vertical_fov_deg=42)

render_animation(
    scene_at, ts=[i / 120 for i in range(120)],
    out="renders", name="hero.mp4", duration_s=5.0,
    camera=cam, resolution=(720, 720), samples=32,
)
```

**Fast path — `render_animation_from_glb(glb_path, camera, ...)`.**
When the geometry animation is already baked into a GLB (e.g. one
produced by cad-khana's `export_animated_glb` for a `<model-viewer>`
pane), this path imports it once and only the render runs per frame.
No factory rebuild, no per-frame tessellation. Materials are
whatever the GLB carries — glTF PBR, round-tripped from the render layer's
Principled BSDF if the GLB came from `export_glb`, or cad-khana's
flat sRGB if from `export_animated_glb`.

```python
render_animation_from_glb(
    "subsite/assets/animated.glb", camera=cam,
    out="renders", name="hero.mp4",
    duration_s=None,          # None = use GLB's native length
    fps=24, resolution=(720, 720), samples=32,
)
```

`camera(t)` is sampled at `t = i / (n_frames - 1)` for each frame.
Location, target, and `vertical_fov_deg` are all keyframed per
frame, so orbit / dolly / dolly-zoom all work. Track-to constraint
keeps the camera aimed at the target; no Euler-interpolation
weirdness on large azimuth sweeps.

**ffmpeg is required on PATH** — the bpy-as-module flavour ships
without the FFmpeg muxer, so both functions shell out to the system
binary for the final mux.

## Workflow

1. Write the script. Use the minimal skeleton above as a template.
2. `khana run path/to/script.py` (drop resolution to `(960, 540)`
   while iterating to keep the loop tight).
3. Open `renders/render.png`, evaluate.
4. Adjust the material assignments and per-part colors. Re-run.
5. When the look is right, bump resolution and produce the final.

## Known limitations (v0)

- **Material library is fixed at install time.** Adding a material
  means editing `cad_khana.render.materials`.
- **Tessellation is part-level, not feature-aware.** Very tight curvature
  may show faceting; raise `tessellation` tolerance in `render()` if
  you see it on a hero shot.
- **No compositor passes.** No depth, AO, or normal output — just
  the beauty pass. (Alpha / transparent background *is* available
  via `render(..., transparent_background=True)` for compositing
  the asset onto a page background.)
- **Headless only.** No interactive Blender preview; the only feedback
  is the PNG.

## Feedback

Log render friction the way `SKILL.md`'s Feedback section says: the
same field-notes file, or the same issue tracker.

A pattern only emerges when individual observations are recorded
honestly, so log first and worry about whether it generalizes later.
