"""glTF / GLB export from a ``Scene``. Sibling to ``render.py``.

``render()`` produces a PNG (single moment); ``export_glb()`` produces
a glTF 2.0 binary suitable for web embedding (e.g. Google's
``<model-viewer>``). Both pass the same ``Scene`` through the render layer's
material catalog → Cycles Principled BSDF shader graphs; Blender's
built-in glTF exporter then bakes those shaders to glTF PBR via the
Principled-BSDF → glTF translator.

Reuses the bpy scene-build helpers from ``render.py``
(``_reset_scene``, ``_add_part``) — same path, different terminal op.
"""

from __future__ import annotations

from pathlib import Path

from cad_khana._paths import resolve_out
from cad_khana.render import tessellation
from cad_khana.render.render import _add_part, _reset_scene
from cad_khana.render.scene import Scene


def export_glb(
    scene: Scene,
    out: str | Path = "renders",
    name: str = "model.glb",
    linear_tolerance_mm: float = tessellation.DEFAULT_LINEAR_TOLERANCE_MM,
    angular_tolerance_deg: float = tessellation.DEFAULT_ANGULAR_TOLERANCE_DEG,
    draco_compression: bool = True,
    draco_level: int = 6,
) -> Path:
    """Export ``scene`` as glTF 2.0 binary at ``<out>/<name>``.

    Materials come from the render layer's catalog the same way ``render()``
    consumes them — the per-part Principled BSDF is baked to glTF PBR
    by Blender's exporter (baseColor, metallic-roughness, IOR,
    transmission). Lighting / camera / framing don't apply: glTF is
    geometry + materials, viewers light it themselves.

    ``draco_compression`` (default on) typically shrinks CAD GLBs
    5–10×; ``<model-viewer>`` and three.js ship Draco decoders by
    default. ``draco_level`` 0–10 trades encode time and file size
    (6 is the sweet spot for static CAD).

    Returns the absolute path written.
    """
    import bpy

    out_path = resolve_out(out)
    out_path.mkdir(parents=True, exist_ok=True)
    glb_path = out_path / name

    _reset_scene(bpy)
    for placed in scene.parts:
        _add_part(bpy, placed, linear_tolerance_mm, angular_tolerance_deg)
    _apply_glb_transparency_fallback(bpy)

    bpy.ops.export_scene.gltf(
        filepath=str(glb_path),
        export_format="GLB",
        export_yup=True,
        export_apply=True,
        use_selection=False,
        use_visible=False,
        export_draco_mesh_compression_enable=draco_compression,
        export_draco_mesh_compression_level=draco_level,
    )
    return glb_path


def _apply_glb_transparency_fallback(bpy) -> None:
    """For each material with non-zero Principled BSDF transmission,
    flag the material as alphaMode=BLEND with reduced baseColor alpha.

    Mirrors ``render.py``'s ``cycles.film_transparent_glass`` tweak:
    that flag lets the alpha-masked world show through transmissive
    surfaces in PNG output. For GLB the equivalent is encoding the
    transparency intent into the material itself — ``KHR_materials_-
    transmission`` alone is honored only by transmission-aware viewers
    and only renders visibly with a strong environment map. Setting
    ``blend_method=BLEND`` makes Blender's exporter emit
    ``alphaMode: BLEND``, so basic alpha-blend viewers (and model-
    viewer setups without an env image) still read the surface as
    see-through.
    """
    for mat in bpy.data.materials:
        if not mat.use_nodes:
            continue
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf is None:
            continue
        t_input = bsdf.inputs.get("Transmission Weight") or bsdf.inputs.get(
            "Transmission"
        )
        if t_input is None or t_input.default_value <= 0.0:
            continue
        mat.blend_method = "BLEND"
        alpha_input = bsdf.inputs.get("Alpha")
        if alpha_input is not None:
            alpha_input.default_value = max(0.05, 1.0 - t_input.default_value * 0.7)
