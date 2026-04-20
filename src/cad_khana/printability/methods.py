from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FDM:
    up_axis: tuple[float, float, float] = (0, 0, 1)
    wall_min_mm: float = 1.5
    overhang_max_deg: float = 45.0
