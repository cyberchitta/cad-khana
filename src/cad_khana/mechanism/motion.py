"""A declared motion — the poses a mechanism passes through, as data.

A pose is a dict of joint values keyed by dotted joint path
(``Assembly.joint_angles``' keys); a motion is a schedule ``t -> pose``
plus the parameters it is sampled at. The schedule is a function rather
than a joint and a range because real motion drives several joints at
once from non-linear schedules; one joint across a range is the
degenerate case (``Motion.over_joint``).

Values are unit-neutral here — degrees for a revolute joint, because the
unit belongs to the joint kind, not to the pose.

Sampled, like everything in ``sweep``: a motion is the poses at its
``ts`` and nothing in between.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil

Pose = dict[str, float]
Schedule = Callable[[float], Pose]


@dataclass(frozen=True)
class Motion:
    name: str
    schedule: Schedule
    ts: tuple[float, ...]

    @staticmethod
    def over_joint(
        name: str, path: str, lo: float, hi: float, step: float
    ) -> "Motion":
        """One joint driven from ``lo`` to ``hi`` as ``t`` runs 0→1, both
        ends sampled. ``step`` is the widest gap allowed between
        adjacent samples: a range it doesn't divide gets more samples,
        never a wider step."""
        if step <= 0:
            raise ValueError(f"Motion.over_joint step must be > 0, got {step}")
        n = ceil(abs(hi - lo) / step - 1e-9)
        ts = tuple(i / n for i in range(n + 1)) if n else (0.0,)
        return Motion(name, lambda t: {path: lo + (hi - lo) * t}, ts)

    @property
    def poses(self) -> tuple[Pose, ...]:
        return tuple(self.schedule(t) for t in self.ts)
