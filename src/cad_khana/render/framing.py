"""Camera framing strategies.

A ``FramingStrategy`` consumes a scene bounding box (plus aspect ratio
and ``world_up``) and emits a list of ``CameraConfig``s — one per
output frame. Strategies are pure data; ``bpy`` lives in ``render.py``.

Direction vectors stored on strategy instances are in a *canonical*
(Y-up) frame: +X right, +Y up, -Z toward viewer. At ``frames(...)``
time, directions are rotated to match the user's ``world_up`` so a
single named preset like ``HERO_3Q`` works for both Y-up (the render
default) and Z-up (typical CAD) scenes. Supported ``world_up`` axes
are ±Y and ±Z; other values fall through as identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi, radians, sin, tan
from typing import Protocol

from cad_khana.render.camera import BBox, Vec3


@dataclass(frozen=True)
class CameraConfig:
    """One frame's camera state.

    ``perspective=True`` ⇒ ``vertical_fov_deg`` set, ``ortho_scale`` is
    ``None``; ``perspective=False`` ⇒ the reverse. ``render.py`` reads
    this and wires it into the bpy camera.
    """

    location: Vec3
    target: Vec3
    perspective: bool
    vertical_fov_deg: float | None
    ortho_scale: float | None
    clip_start: float
    clip_end: float


class FramingStrategy(Protocol):
    def frames(
        self,
        bbox: BBox,
        aspect: float,
        world_up: Vec3,
    ) -> list[CameraConfig]: ...


def _normalize(v: Vec3) -> Vec3:
    mag = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) ** 0.5
    return (v[0] / mag, v[1] / mag, v[2] / mag)


def _world_direction(canonical: Vec3, world_up: Vec3) -> Vec3:
    """Rotate a canonical-frame direction into world coords.

    Y-up world: identity. Z-up world: swap Y and Z. Other ``world_up``
    axes (X-up, oblique) are unsupported and pass through unchanged.
    """
    cx, cy, cz = canonical
    if abs(world_up[2]) > 0.9:
        return (cx, cz, cy)
    return canonical


def _fit_distance(
    bbox: BBox, vertical_fov_deg: float, aspect: float, padding: float
) -> float:
    """Distance from bbox centre at which the bbox diagonal fits in frame.

    Conservative — uses the diagonal as a worst-case projected extent so
    the assembly fits regardless of view angle.
    """
    extent = bbox.diagonal * padding / 2
    half_v = tan(radians(vertical_fov_deg / 2))
    half_h = half_v * aspect
    return extent / min(half_v, half_h)


def _perp_basis(axis: Vec3) -> tuple[Vec3, Vec3]:
    """Two orthonormal vectors perpendicular to a unit ``axis``."""
    seed: Vec3 = (1.0, 0.0, 0.0) if abs(axis[0]) < 0.9 else (0.0, 1.0, 0.0)
    d = seed[0] * axis[0] + seed[1] * axis[1] + seed[2] * axis[2]
    p = _normalize(
        (
            seed[0] - d * axis[0],
            seed[1] - d * axis[1],
            seed[2] - d * axis[2],
        )
    )
    q = (
        axis[1] * p[2] - axis[2] * p[1],
        axis[2] * p[0] - axis[0] * p[2],
        axis[0] * p[1] - axis[1] * p[0],
    )
    return p, q


def _ortho_plane_dims(world_dir: Vec3, size: Vec3) -> tuple[float, float]:
    """In-plane (width, height) of a bbox seen from a cardinal-axis direction."""
    ax, ay = abs(world_dir[0]), abs(world_dir[1])
    if ax > 0.9:
        return size[1], size[2]
    if ay > 0.9:
        return size[0], size[2]
    return size[0], size[1]


@dataclass(frozen=True)
class AutoFrame:
    """Auto-fit a bbox from a fixed canonical direction."""

    direction: Vec3 = (1.0, 0.7, -1.0)
    vertical_fov_deg: float = 35.0
    padding: float = 1.15

    def frames(
        self,
        bbox: BBox,
        aspect: float,
        world_up: Vec3,
    ) -> list[CameraConfig]:
        target = bbox.center
        world_dir = _normalize(_world_direction(self.direction, world_up))
        distance = _fit_distance(bbox, self.vertical_fov_deg, aspect, self.padding)
        location = (
            target[0] + world_dir[0] * distance,
            target[1] + world_dir[1] * distance,
            target[2] + world_dir[2] * distance,
        )
        return [
            CameraConfig(
                location=location,
                target=target,
                perspective=True,
                vertical_fov_deg=self.vertical_fov_deg,
                ortho_scale=None,
                clip_start=max(distance * 0.01, 1e-3),
                clip_end=distance * 5.0,
            )
        ]


@dataclass(frozen=True)
class FixedPose:
    """Pin location, target, and FOV (or ortho scale) explicitly.

    The bbox is ignored. Set exactly one of ``vertical_fov_deg`` (perspective)
    or ``ortho_scale`` (orthographic).
    """

    location: Vec3
    target: Vec3 = (0.0, 0.0, 0.0)
    vertical_fov_deg: float | None = None
    ortho_scale: float | None = None
    clip_start: float = 0.1
    clip_end: float = 1000.0

    def frames(
        self,
        bbox: BBox,
        aspect: float,
        world_up: Vec3,
    ) -> list[CameraConfig]:
        return [
            CameraConfig(
                location=self.location,
                target=self.target,
                perspective=self.vertical_fov_deg is not None,
                vertical_fov_deg=self.vertical_fov_deg,
                ortho_scale=self.ortho_scale,
                clip_start=self.clip_start,
                clip_end=self.clip_end,
            )
        ]


@dataclass(frozen=True)
class Orbit:
    """``n`` perspective frames orbiting ``axis`` at fixed elevation.

    Default ``axis`` is canonical up, so the result is a turntable matching
    the scene's ``world_up``. Pass a different ``axis`` (in canonical
    coords) to orbit around another scene axis.
    """

    n: int = 24
    axis: Vec3 = (0.0, 1.0, 0.0)
    elevation_deg: float = 20.0
    vertical_fov_deg: float = 35.0
    padding: float = 1.15

    def frames(
        self,
        bbox: BBox,
        aspect: float,
        world_up: Vec3,
    ) -> list[CameraConfig]:
        target = bbox.center
        axis_world = _normalize(_world_direction(self.axis, world_up))
        right, front = _perp_basis(axis_world)
        distance = _fit_distance(bbox, self.vertical_fov_deg, aspect, self.padding)
        elev = radians(self.elevation_deg)
        cos_e, sin_e = cos(elev), sin(elev)
        configs: list[CameraConfig] = []
        for i in range(self.n):
            theta = 2.0 * pi * i / self.n
            cos_t, sin_t = cos(theta), sin(theta)
            offset = (
                cos_e * (cos_t * right[0] + sin_t * front[0]) + sin_e * axis_world[0],
                cos_e * (cos_t * right[1] + sin_t * front[1]) + sin_e * axis_world[1],
                cos_e * (cos_t * right[2] + sin_t * front[2]) + sin_e * axis_world[2],
            )
            location = (
                target[0] + offset[0] * distance,
                target[1] + offset[1] * distance,
                target[2] + offset[2] * distance,
            )
            configs.append(
                CameraConfig(
                    location=location,
                    target=target,
                    perspective=True,
                    vertical_fov_deg=self.vertical_fov_deg,
                    ortho_scale=None,
                    clip_start=max(distance * 0.01, 1e-3),
                    clip_end=distance * 5.0,
                )
            )
        return configs


# Six canonical view directions (camera-from-target). Order is
# front, back, right, left, top, bottom — frame_000 .. frame_005.
_SIX_VIEWS: tuple[Vec3, ...] = (
    (0.0, 0.0, -1.0),
    (0.0, 0.0, 1.0),
    (1.0, 0.0, 0.0),
    (-1.0, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, -1.0, 0.0),
)


@dataclass(frozen=True)
class SixOrtho:
    """Six orthographic views — front, back, right, left, top, bottom.

    Each view's ``ortho_scale`` is sized to fit the bbox extent in that
    view's plane. ``render.py`` sets ``sensor_fit='VERTICAL'`` for ortho
    cameras, so ``ortho_scale`` is the vertical extent.
    """

    padding: float = 1.15

    def frames(
        self,
        bbox: BBox,
        aspect: float,
        world_up: Vec3,
    ) -> list[CameraConfig]:
        target = bbox.center
        size = bbox.size
        distance = max(bbox.diagonal, 1.0) * 2.0
        configs: list[CameraConfig] = []
        for canonical_dir in _SIX_VIEWS:
            world_dir = _normalize(_world_direction(canonical_dir, world_up))
            location = (
                target[0] + world_dir[0] * distance,
                target[1] + world_dir[1] * distance,
                target[2] + world_dir[2] * distance,
            )
            w, h = _ortho_plane_dims(world_dir, size)
            ortho_scale = max(h, w / aspect) * self.padding
            configs.append(
                CameraConfig(
                    location=location,
                    target=target,
                    perspective=False,
                    vertical_fov_deg=None,
                    ortho_scale=ortho_scale,
                    clip_start=max(distance * 0.01, 1e-3),
                    clip_end=distance * 5.0,
                )
            )
        return configs


HERO_3Q: AutoFrame = AutoFrame(
    direction=(1.0, 0.7, -1.0), vertical_fov_deg=35.0, padding=0.85
)
"""3/4 view from front-right-up. Default for ``render(...)``.

``padding=0.85`` (under 1.0) is intentional: ``AutoFrame`` uses
``bbox.diagonal`` as a conservative worst-case extent, so the actual
projected silhouette is meaningfully smaller. 0.85 produces tight
hero-shot framing while still leaving headroom on cubic subjects.
"""

ORTHO_SIX: SixOrtho = SixOrtho()
"""Six orthographic views — front, back, right, left, top, bottom."""

TURNTABLE_24: Orbit = Orbit(n=24)
"""24-frame turntable around the scene's up axis at 20° elevation."""
