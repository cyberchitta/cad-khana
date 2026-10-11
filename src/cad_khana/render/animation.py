"""Animation rendering — mp4 from a time-parameterized scene factory
or a pre-baked animated GLB.

Two entry points:

  * ``render_animation(factory, ts, ...)`` — *photo-real path*. Sweeps
    ``factory(t)`` over ``ts``, runs the render layer's full per-frame scene
    build (tessellate parts → apply Cycles materials → render). Slow
    but uses the same material catalog as ``render()``, so the look
    matches the static stills.

  * ``render_animation_from_glb(glb_path, camera, ...)`` — *fast path*.
    Loads a pre-baked animated GLB once, advances its imported timeline
    per frame, only renders. Per-frame cost is render-only; suitable
    when ``export_animated_glb`` already produced the artifact (e.g.
    the same GLB the project embeds in a ``<model-viewer>`` pane).

Both functions share the same camera-callable contract
(``camera(t) -> FixedPose``) and the same ffmpeg-mux step. The
camera-callable returns a per-frame ``FixedPose`` parameterized by
``t ∈ [0, 1]``; location, target, and vertical_fov_deg are all
sampled per frame (so dolly-zoom-style shots work — keyframe the
field of view alongside the move).

ffmpeg is required on ``PATH`` — the bpy-as-module flavour ships
without the FFmpeg muxer, so this module shells out to the system
binary.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from math import radians, tan
from pathlib import Path

from cad_khana._paths import resolve_out
from cad_khana.render import lighting, tessellation
from cad_khana.render.camera import BBox
from cad_khana.render.framing import FixedPose
from cad_khana.render.render import (
    WORLD_UP,
    _add_lighting,
    _add_part,
    _reset_scene,
    _set_camera,
)
from cad_khana.render.scene import Scene

Vec3 = tuple[float, float, float]

DEFAULT_RESOLUTION = (1080, 1080)
DEFAULT_FPS = 24
DEFAULT_SAMPLES = 32  # lower than render()'s 128 — animation budgets matter
DEFAULT_NAME = "animation.mp4"
DEFAULT_CRF = 20


# --- Public API -------------------------------------------------------


def render_animation(
    factory: Callable[[float], Scene],
    ts: Sequence[float],
    out: str | Path = "renders",
    name: str = DEFAULT_NAME,
    duration_s: float = 5.0,
    *,
    camera: Callable[[float], FixedPose],
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    samples: int = DEFAULT_SAMPLES,
    rig: lighting.StudioRig = lighting.DEFAULT,
    world_up: Vec3 | None = None,
    linear_tolerance_mm: float = tessellation.DEFAULT_LINEAR_TOLERANCE_MM,
    angular_tolerance_deg: float = tessellation.DEFAULT_ANGULAR_TOLERANCE_DEG,
) -> Path:
    """Render an mp4 by sweeping ``factory(t)`` over ``ts``.

    Photo-real path: each frame runs the full render pipeline
    (reset scene → tessellate ``factory(t)``'s parts → apply Cycles
    materials → render). The output looks identical to ``render()``
    on the same Scene; the cost is also per-frame Scene rebuild +
    Cycles render.

    Signature parallels cad-khana's ``export_animated_glb`` —
    positional ``factory, ts, out, name, duration_s`` so the two
    functions read as a pair. The ``camera`` callable is the new
    ingredient: it produces a ``FixedPose`` per ``t``, sampled at the
    same ``t`` values as the factory.

    ``ts`` is unitless ([0, 1] is conventional). ``duration_s`` sets
    wall-clock playback length; fps is ``len(ts) / duration_s``.

    Returns the absolute mp4 path.
    """
    import bpy

    ts_list = list(ts)
    if len(ts_list) < 2:
        raise ValueError("render_animation requires len(ts) >= 2")
    n_frames = len(ts_list)
    fps = max(1, round(n_frames / duration_s))
    up = world_up if world_up is not None else WORLD_UP
    aspect = resolution[0] / resolution[1]

    out_path = resolve_out(out)
    out_path.mkdir(parents=True, exist_ok=True)
    frames_dir = _frames_dir(out_path, name)

    for i, t in enumerate(ts_list):
        _reset_scene(bpy)
        scene_at_t = factory(t)
        for placed in scene_at_t.parts:
            _add_part(bpy, placed, linear_tolerance_mm, angular_tolerance_deg)
        # Camera before lighting so camera-parented lights (e.g.
        # DEFAULT_HDRI's fill) can attach. Per-frame reset means we
        # rebuild the parent each iteration — Blender handles it.
        cfg = _camera_config_from(camera, t, aspect, up)
        cam_obj = _set_camera(bpy, cfg, world_up=up)
        _add_lighting(bpy, rig, world_up=up, cam_obj=cam_obj)
        png_path = frames_dir / f"frame_{i + 1:04d}.png"
        _configure_render(bpy, resolution, samples, str(png_path))
        bpy.ops.render.render(write_still=True)

    mp4_path = out_path / name
    _mux_mp4(frames_dir, mp4_path, fps)
    return mp4_path


def render_animation_from_glb(
    glb_path: str | Path,
    camera: Callable[[float], FixedPose],
    out: str | Path = "renders",
    name: str = DEFAULT_NAME,
    *,
    duration_s: float | None = None,
    fps: int = DEFAULT_FPS,
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    samples: int = DEFAULT_SAMPLES,
    rig: lighting.StudioRig = lighting.DEFAULT,
    world_up: Vec3 | None = None,
) -> Path:
    """Render an mp4 from a pre-baked animated GLB.

    Geometry, materials (glTF PBR — round-tripped from a Cycles
    Principled BSDF if the GLB came from the render layer's ``export_glb``,
    flat sRGB if from cad-khana's ``export_animated_glb``), and motion
    all come from the GLB. The camera callable adds the cinematic
    move; the render layer's ``rig`` adds the lighting.

    Fast path: the GLB is imported once, then ``bpy.ops.render.render(
    animation=True)`` renders the whole sequence in one process. No
    per-frame Assembly rebuild or tessellation cost.

    ``duration_s=None`` reads the GLB's native animation length (the
    longest imported action). Pass an explicit value to compress or
    extend playback — keyframes scale linearly.

    ``camera(t)`` is sampled at ``t = i / (n_frames-1)`` for
    ``i ∈ [0, n_frames)``. Location, target, and ``vertical_fov_deg``
    are all keyframed per frame — pass a callable that varies any of
    them for orbit / dolly / dolly-zoom shots.

    Returns the absolute mp4 path.
    """
    import bpy

    glb = Path(glb_path)
    if not glb.exists():
        raise FileNotFoundError(f"GLB not found: {glb}")

    up = world_up if world_up is not None else WORLD_UP
    out_path = resolve_out(out)
    out_path.mkdir(parents=True, exist_ok=True)
    frames_dir = _frames_dir(out_path, name)

    _reset_scene(bpy)

    scene = bpy.context.scene
    scene.render.fps = fps
    bpy.ops.import_scene.gltf(filepath=str(glb))

    native_end = _max_action_frame(bpy)
    if duration_s is None:
        scene.frame_start = 1
        scene.frame_end = max(2, native_end)
    else:
        scene.frame_start = 1
        scene.frame_end = max(2, round(duration_s * fps))
        _rescale_actions(bpy, native_end, scene.frame_end)

    n_frames = scene.frame_end - scene.frame_start + 1

    cam_obj = _add_animated_camera(
        bpy, camera, n_frames, aspect=resolution[0] / resolution[1]
    )
    _add_lighting(bpy, rig, world_up=up, cam_obj=cam_obj)

    _configure_render(bpy, resolution, samples, str(frames_dir / "frame_"))
    bpy.ops.render.render(animation=True)

    mp4_path = out_path / name
    _mux_mp4(frames_dir, mp4_path, fps)
    return mp4_path


# --- Internal helpers -------------------------------------------------


def _frames_dir(out_path: Path, name: str) -> Path:
    """Per-mp4 PNG scratch dir. Wiped at start so re-runs don't leak
    stale frames into the next mux."""
    d = out_path / f"{Path(name).stem}.frames"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


def _camera_config_from(
    camera: Callable[[float], FixedPose],
    t: float,
    aspect: float,
    world_up: Vec3,
):
    """Sample the camera callable and pull out its CameraConfig.
    The FixedPose strategy ignores bbox; we pass a sentinel."""
    pose = camera(t)
    sentinel = BBox(min=(-1.0, -1.0, -1.0), max=(1.0, 1.0, 1.0))
    return pose.frames(sentinel, aspect, world_up)[0]


def _configure_render(bpy, resolution, samples: int, filepath: str) -> None:
    s = bpy.context.scene
    s.render.engine = "CYCLES"
    s.render.resolution_x = resolution[0]
    s.render.resolution_y = resolution[1]
    s.render.resolution_percentage = 100
    s.render.image_settings.file_format = "PNG"
    s.render.image_settings.color_mode = "RGB"
    s.render.filepath = filepath
    s.cycles.samples = samples


def _max_action_frame(bpy) -> int:
    """End of the longest imported Action — drives native animation length."""
    frame_end = 1
    for action in bpy.data.actions:
        end = int(round(action.frame_range[1]))
        if end > frame_end:
            frame_end = end
    return frame_end


def _rescale_actions(bpy, native_end: int, target_end: int) -> None:
    """Linearly rescale every Action's keyframe times so a native_end
    range maps onto target_end. Used when ``duration_s`` overrides
    the GLB's native length — compresses or stretches motion."""
    if native_end <= 1 or target_end == native_end:
        return
    scale = (target_end - 1) / (native_end - 1)
    for action in bpy.data.actions:
        for fcurves in _iter_fcurves(action):
            for fcurve in fcurves:
                for kp in fcurve.keyframe_points:
                    kp.co.x = 1.0 + (kp.co.x - 1.0) * scale
                    kp.handle_left.x = 1.0 + (kp.handle_left.x - 1.0) * scale
                    kp.handle_right.x = 1.0 + (kp.handle_right.x - 1.0) * scale


def _iter_fcurves(action):
    """Yield each fcurve collection on an Action across Blender 4/5.

    Blender 5.x moved fcurves into a per-slot ``channelbag`` nested
    under ``action.layers[i].strips[i]``; Blender 4.x exposes them
    directly as ``action.fcurves``. Probe both so a single
    install works against either Blender version it was built for."""
    if hasattr(action, "fcurves") and len(action.fcurves):
        yield action.fcurves
    if hasattr(action, "layers"):
        for layer in action.layers:
            for strip in layer.strips:
                if hasattr(strip, "channelbags"):
                    for cb in strip.channelbags:
                        yield cb.fcurves


def _add_animated_camera(
    bpy,
    camera: Callable[[float], FixedPose],
    n_frames: int,
    *,
    aspect: float,
):
    """One camera with a track-to constraint at a keyframed empty,
    location keyframed per frame, and lens keyframed when the pose's
    vertical_fov_deg varies. Track-to avoids Euler-interpolation
    pathologies that hit large azimuth sweeps. Returns the camera
    object so camera-parented lights can attach."""
    scene = bpy.context.scene

    cam_data = bpy.data.cameras.new("anim_cam")
    cam_data.sensor_fit = "VERTICAL"
    cam_data.clip_start = 1.0
    cam_data.clip_end = 100000.0
    cam_obj = bpy.data.objects.new("anim_cam", cam_data)
    scene.collection.objects.link(cam_obj)
    scene.camera = cam_obj

    target_empty = bpy.data.objects.new("anim_cam_target", None)
    scene.collection.objects.link(target_empty)
    tt = cam_obj.constraints.new(type="TRACK_TO")
    tt.target = target_empty
    tt.track_axis = "TRACK_NEGATIVE_Z"
    tt.up_axis = "UP_Y"

    sensor_h = cam_data.sensor_height
    for i in range(n_frames):
        s = i / (n_frames - 1) if n_frames > 1 else 0.0
        pose = camera(s)
        cam_obj.location = pose.location
        target_empty.location = pose.target
        cam_obj.keyframe_insert(data_path="location", frame=i + 1)
        target_empty.keyframe_insert(data_path="location", frame=i + 1)
        if pose.vertical_fov_deg is not None:
            cam_data.lens = sensor_h / (2.0 * tan(radians(pose.vertical_fov_deg / 2.0)))
            cam_data.keyframe_insert(data_path="lens", frame=i + 1)
    return cam_obj


def _mux_mp4(frames_dir: Path, mp4_path: Path, fps: int) -> None:
    """ffmpeg subprocess. yuv420p + faststart for web/mobile playback."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            f"ffmpeg not found on PATH; cannot mux PNGs into {mp4_path}. "
            f"Frames are at {frames_dir}; install ffmpeg or mux manually."
        )
    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(fps),
        "-i",
        str(frames_dir / "frame_%04d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        str(DEFAULT_CRF),
        "-movflags",
        "+faststart",
        str(mp4_path),
    ]
    subprocess.run(cmd, check=True)
