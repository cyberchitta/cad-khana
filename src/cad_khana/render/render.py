"""Render orchestrator. One of the bpy-using modules (see also
``export.py``); the rest of the library stays bpy-free so it remains
testable without booting Blender. Public surface:
``render(scene, out, ...)``.

The scene-build helpers ``_reset_scene`` and ``_add_part`` are
imported by ``export.py``; treat them as package-internal but stable
across the two consumers.
"""

from __future__ import annotations

from math import radians, tan
from pathlib import Path

from cad_khana._paths import resolve_out
from cad_khana.render import camera, lighting, materials, tessellation
from cad_khana.render.framing import HERO_3Q, CameraConfig, FramingStrategy
from cad_khana.render.scene import PlacedPart, Scene

DEFAULT_RESOLUTION = (1920, 1080)
DEFAULT_SAMPLES = 128


WORLD_UP: tuple[float, float, float] = (0.0, 1.0, 0.0)
"""World 'up' axis used to level the camera and orient sun lamps.

Default matches Build123d / cad-khana (+Y up). Z-up scenes pass
``world_up=(0, 0, 1)`` to ``render(...)``; the sun lamp and the framing
strategy's canonical direction both re-orient to match.
"""


def render(
    scene: Scene,
    out: str | Path = "renders",
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    samples: int = DEFAULT_SAMPLES,
    rig: lighting.StudioRig = lighting.DEFAULT,
    linear_tolerance_mm: float = tessellation.DEFAULT_LINEAR_TOLERANCE_MM,
    angular_tolerance_deg: float = tessellation.DEFAULT_ANGULAR_TOLERANCE_DEG,
    world_up: tuple[float, float, float] | None = None,
    framing: FramingStrategy = HERO_3Q,
    transparent_background: bool = False,
) -> list[Path]:
    """Render ``scene`` and return the path(s) written.

    Single-frame strategies (``HERO_3Q``, ``FixedPose(...)``) write
    ``<out>/render.png``. Multi-frame strategies (``TURNTABLE_24``,
    ``ORTHO_SIX``) write ``<out>/frame_NNN.png``. Resets the Blender
    scene before each call — leftover state from a prior render is
    not preserved.

    ``world_up`` selects the world axis the camera levels against
    (default: Build123d / cad-khana's +Y). Pass ``(0, 0, 1)`` for
    Z-up scenes; the sun lamp and the framing strategy's canonical
    direction re-orient to match.

    ``transparent_background=True`` writes RGBA PNGs with the world
    background masked out — for compositing the asset onto a page
    background. The world's color and strength still light the
    scene; only the *visibility* of the background is suppressed.
    """
    import bpy  # local: heavy import, only needed at render time

    up = world_up if world_up is not None else WORLD_UP
    out_path = resolve_out(out)
    out_path.mkdir(parents=True, exist_ok=True)
    aspect = resolution[0] / resolution[1]

    _reset_scene(bpy)
    bbox = _bbox_world(scene)
    for placed in scene.parts:
        _add_part(bpy, placed, linear_tolerance_mm, angular_tolerance_deg)

    configs = framing.frames(bbox, aspect, up)
    multi = len(configs) > 1
    # Create the camera before lighting so camera-parented lights have a
    # parent to attach to. _set_camera is idempotent: subsequent calls
    # (one per frame in multi-frame strategies) update the same camera
    # object so the parent link stays valid across the whole render.
    cam_obj = _set_camera(bpy, configs[0], world_up=up)
    _add_lighting(bpy, rig, world_up=up, cam_obj=cam_obj)
    written: list[Path] = []
    for i, config in enumerate(configs):
        png_path = out_path / (f"frame_{i:03d}.png" if multi else "render.png")
        if i > 0:
            _set_camera(bpy, config, world_up=up)
        _configure_render(bpy, resolution, samples, png_path, transparent_background)
        bpy.ops.render.render(write_still=True)
        written.append(png_path)
    return written


def _reset_scene(bpy) -> None:
    """Wipe everything so each render starts from a clean slate."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for collection in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.lights,
        bpy.data.cameras,
    ):
        for item in list(collection):
            collection.remove(item)


def _bbox_world(scene: Scene) -> camera.BBox:
    """Compute the world-space AABB of all placed parts via Build123d."""
    placed_parts = tuple(p.part.moved(p.location) for p in scene.parts)
    if not placed_parts:
        return camera.BBox(min=(-1, -1, -1), max=(1, 1, 1))
    boxes = tuple(part.bounding_box() for part in placed_parts)
    return camera.BBox(
        min=(
            min(bb.min.X for bb in boxes),
            min(bb.min.Y for bb in boxes),
            min(bb.min.Z for bb in boxes),
        ),
        max=(
            max(bb.max.X for bb in boxes),
            max(bb.max.Y for bb in boxes),
            max(bb.max.Z for bb in boxes),
        ),
    )


def _add_part(
    bpy,
    placed: PlacedPart,
    linear_tolerance_mm: float,
    angular_tolerance_deg: float,
) -> None:
    """Tessellate one part, import as a bpy mesh, attach material."""
    part_world = placed.part.moved(placed.location)
    mesh = tessellation.tessellate(
        part_world,
        linear_tolerance_mm=linear_tolerance_mm,
        angular_tolerance_deg=angular_tolerance_deg,
    )
    bmesh = bpy.data.meshes.new(name=f"{placed.name}_mesh")
    bmesh.from_pydata(list(mesh.vertices), [], list(mesh.triangles))
    bmesh.update()
    obj = bpy.data.objects.new(placed.name, bmesh)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(_build_material(bpy, placed))


def _build_material(bpy, placed: PlacedPart):
    """Build a Cycles Principled BSDF material from a recipe + override."""
    recipe = materials.get(placed.material)
    base_color = (
        placed.color
        if (placed.color is not None and recipe.color_overridable)
        else recipe.base_color
    )
    mat = bpy.data.materials.new(name=f"{placed.name}_{placed.material}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
        bsdf.inputs["Metallic"].default_value = recipe.metallic
        bsdf.inputs["Roughness"].default_value = recipe.roughness
        # Transmission Weight is the Blender 4.x+ socket name (was
        # "Transmission" in 3.x). IOR drives refraction when transmission
        # > 0; harmless to set otherwise.
        if "Transmission Weight" in bsdf.inputs:
            bsdf.inputs["Transmission Weight"].default_value = recipe.transmission
        elif "Transmission" in bsdf.inputs:
            bsdf.inputs["Transmission"].default_value = recipe.transmission
        if "IOR" in bsdf.inputs:
            bsdf.inputs["IOR"].default_value = recipe.ior
    return mat


def _add_lighting(
    bpy,
    rig: lighting.StudioRig,
    world_up: tuple[float, float, float] = WORLD_UP,
    cam_obj=None,
) -> None:
    """World background (flat color or HDRI) + optional key and fill lights.

    Pass ``cam_obj`` so camera-parented lights can attach to it; without
    it, a camera-parented light raises a clear error rather than
    silently rendering at the wrong reference frame.
    """
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        bpy.context.scene.world = world
    world.use_nodes = True
    if rig.world_hdri is not None:
        _set_world_hdri(bpy, world, rig, world_up=world_up)
    else:
        bg = world.node_tree.nodes.get("Background")
        if bg is not None:
            bg.inputs["Color"].default_value = (*rig.world_color, 1.0)
            bg.inputs["Strength"].default_value = rig.world_strength
    if rig.key is not None:
        _add_sun_light(bpy, rig.key, name="key", world_up=world_up, cam_obj=cam_obj)
    if rig.fill is not None:
        _add_sun_light(bpy, rig.fill, name="fill", world_up=world_up, cam_obj=cam_obj)


def _add_sun_light(
    bpy,
    spec: lighting.KeyLight,
    name: str,
    world_up: tuple[float, float, float],
    cam_obj,
) -> None:
    """Create one SUN lamp from a ``KeyLight`` spec; parent to ``cam_obj``
    when ``spec.camera_parented`` is True."""
    light_data = bpy.data.lights.new(name=name, type="SUN")
    light_data.energy = spec.energy_w
    light_data.angle = radians(spec.angle_deg)
    light_obj = bpy.data.objects.new(name=name, object_data=light_data)
    bpy.context.collection.objects.link(light_obj)
    if spec.camera_parented:
        if cam_obj is None:
            raise ValueError(
                f"Light {name!r} is camera_parented but no camera object "
                f"was passed to _add_lighting. The camera must exist "
                f"before camera-parented lights can attach."
            )
        light_obj.parent = cam_obj
        # Local rotation is interpreted in the camera's frame: -Z is the
        # camera's "forward toward subject" direction, +X right, +Y up.
        # Reusing _direction_to_euler with the camera's local axes gives
        # the right rotation for a SUN aimed along ``direction`` in that
        # frame.
        light_obj.rotation_euler = _direction_to_euler(
            spec.direction, world_up=(0.0, 1.0, 0.0)
        )
    else:
        light_obj.rotation_euler = _direction_to_euler(
            spec.direction, world_up=world_up
        )


def _set_world_hdri(
    bpy,
    world,
    rig: lighting.StudioRig,
    world_up: tuple[float, float, float],
) -> None:
    """Replace the world's default Background-with-flat-color with a
    TexCoord → Mapping → EnvTexture → Background → Output chain so the
    scene reads the HDRI .exr for both visible background and lighting.

    The Mapping node's rotation does two jobs at once: aligns the
    HDRI's canonical Z-up zenith with ``world_up`` (Blender bundles
    HDRIs as Z-up; a Y-up scene needs a 90° X-rotation), then adds the
    caller's ``world_hdri_rotation_deg`` yaw around ``world_up``.
    """
    hdri_path = lighting.resolve_hdri_path(rig.world_hdri)
    if not hdri_path.is_file():
        raise FileNotFoundError(
            f"world_hdri resolved to a missing file: {hdri_path}. "
            f"Valid bundled names: {sorted(lighting.BUNDLED_HDRI_NAMES)}"
        )
    tree = world.node_tree
    for node in list(tree.nodes):
        tree.nodes.remove(node)
    out = tree.nodes.new(type="ShaderNodeOutputWorld")
    bg = tree.nodes.new(type="ShaderNodeBackground")
    env = tree.nodes.new(type="ShaderNodeTexEnvironment")
    mapping = tree.nodes.new(type="ShaderNodeMapping")
    coord = tree.nodes.new(type="ShaderNodeTexCoord")
    bg.inputs["Strength"].default_value = rig.world_hdri_strength
    env.image = bpy.data.images.load(str(hdri_path), check_existing=True)
    mapping.inputs["Rotation"].default_value = _hdri_rotation_euler(
        world_up, rig.world_hdri_rotation_deg
    )
    tree.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    tree.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    tree.links.new(env.outputs["Color"], bg.inputs["Color"])
    tree.links.new(bg.outputs["Background"], out.inputs["Surface"])


def _hdri_rotation_euler(
    world_up: tuple[float, float, float],
    yaw_deg: float,
) -> tuple[float, float, float]:
    """Euler XYZ (radians) for the Mapping node.

    Aligns the HDRI's canonical Z-up zenith with ``world_up`` and then
    applies ``yaw_deg`` around that axis. v0 covers the two standard
    cases (+Z up and +Y up); other ``world_up`` axes fall back to no
    alignment (zenith stays at canonical +Z) which still produces a
    valid render, just one where the HDRI's horizon line may not match
    the scene's horizon.
    """
    yaw = radians(yaw_deg)
    if world_up == (0.0, 0.0, 1.0):
        return (0.0, 0.0, yaw)
    if world_up == (0.0, 1.0, 0.0):
        return (radians(90.0), 0.0, yaw)
    return (0.0, 0.0, yaw)


def _direction_to_euler(direction, world_up=WORLD_UP):
    """Convert a unit-ish direction vector to Euler angles for a sun lamp.

    Sun lamps emit along their local -Z. Reuses ``_look_at`` by treating
    ``direction`` as the vector from a (0,0,0) lamp toward an imagined
    target along ``direction``.
    """
    return _look_at((0.0, 0.0, 0.0), direction, world_up=world_up)


def _set_camera(
    bpy,
    config: CameraConfig,
    world_up: tuple[float, float, float] = WORLD_UP,
):
    """Get-or-create the scene camera with ``config`` applied; return it.

    Idempotent: subsequent calls update the same camera object in place
    rather than destroying and recreating it. This keeps any parent
    relationships (e.g. camera-mounted fill lights) valid across the
    full render loop.
    """
    cam_obj = bpy.data.objects.get("camera")
    if cam_obj is None or cam_obj.type != "CAMERA":
        cam_data = bpy.data.cameras.new(name="camera")
        cam_obj = bpy.data.objects.new(name="camera", object_data=cam_data)
        bpy.context.collection.objects.link(cam_obj)
    cam_data = cam_obj.data
    # sensor_fit='VERTICAL' makes vertical_fov_deg / ortho_scale interpret
    # the vertical axis directly, regardless of resolution aspect.
    cam_data.sensor_fit = "VERTICAL"
    if config.perspective:
        cam_data.type = "PERSP"
        cam_data.lens = cam_data.sensor_height / (
            2.0 * tan(radians(config.vertical_fov_deg / 2.0))
        )
    else:
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = config.ortho_scale
    cam_data.clip_start = config.clip_start
    cam_data.clip_end = config.clip_end
    cam_obj.location = config.location
    cam_obj.rotation_euler = _look_at(config.location, config.target, world_up=world_up)
    bpy.context.scene.camera = cam_obj
    return cam_obj


def _look_at(loc, target, world_up: tuple[float, float, float] = WORLD_UP):
    """Euler XYZ rotation that points a Blender camera's local -Z at
    ``target`` while keeping its local +Y aligned with ``world_up``
    (no roll).

    Builds the rotation matrix from the right/up/back basis directly so
    arbitrary world-up axes are handled correctly. The previous
    closed-form yaw/pitch implementation was 180° off and assumed Z-up.
    """
    from mathutils import Matrix, Vector

    forward = (Vector(target) - Vector(loc)).normalized()
    up_world = Vector(world_up).normalized()
    right = forward.cross(up_world).normalized()
    up = right.cross(forward).normalized()
    # Camera local axes in world: +X = right, +Y = up, +Z = -forward.
    mat = Matrix(
        (
            (right.x, up.x, -forward.x),
            (right.y, up.y, -forward.y),
            (right.z, up.z, -forward.z),
        )
    )
    return tuple(mat.to_euler("XYZ"))


def _configure_render(
    bpy,
    resolution,
    samples: int,
    png_path: Path,
    transparent_background: bool,
) -> None:
    s = bpy.context.scene
    s.render.engine = "CYCLES"
    s.render.resolution_x = resolution[0]
    s.render.resolution_y = resolution[1]
    s.render.resolution_percentage = 100
    s.render.image_settings.file_format = "PNG"
    # PNG alpha only ends up in the file when both flags agree: film_transparent
    # masks the world out of the alpha channel, color_mode="RGBA" carries it
    # through to disk. Setting color_mode unconditionally avoids leaking RGBA
    # into a later opaque render in the same process. film_transparent_glass
    # extends the same treatment through transmissive surfaces (acrylic_clear,
    # any future glass) so the world doesn't bleed through as colored fill —
    # default roughness threshold (0.1) covers our clear materials.
    s.render.film_transparent = transparent_background
    s.cycles.film_transparent_glass = transparent_background
    s.render.image_settings.color_mode = "RGBA" if transparent_background else "RGB"
    s.render.filepath = str(png_path)
    s.cycles.samples = samples
