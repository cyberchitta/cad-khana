"""Bounding-box primitive used by framing strategies.

Pure data — no ``bpy``. Strategies in ``framing.py`` consume ``BBox``
and emit ``CameraConfig``s; ``render.py`` consumes those.
"""

from __future__ import annotations

from dataclasses import dataclass

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class BBox:
    min: Vec3
    max: Vec3

    @property
    def center(self) -> Vec3:
        return tuple((a + b) / 2 for a, b in zip(self.min, self.max, strict=True))  # type: ignore[return-value]

    @property
    def size(self) -> Vec3:
        return tuple(b - a for a, b in zip(self.min, self.max, strict=True))  # type: ignore[return-value]

    @property
    def diagonal(self) -> float:
        sx, sy, sz = self.size
        return (sx * sx + sy * sy + sz * sz) ** 0.5
