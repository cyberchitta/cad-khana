"""Build123d Part -> triangle mesh, tuned for mechanical geometry.

Pure data transformation: takes a Build123d ``Part`` (already located
in world space) and returns vertices + triangle indices. ``render.py``
feeds the result into ``bpy``.
"""

from __future__ import annotations

from dataclasses import dataclass

from build123d import Part

# Defaults tuned for typical 3D-printed-mechanism geometry (small
# fasteners, fillets ~0.5–2 mm). Tighter than a game-asset pipeline,
# looser than CAM. Override per-render via ``render(..., tolerance=)``.
DEFAULT_LINEAR_TOLERANCE_MM = 0.05
DEFAULT_ANGULAR_TOLERANCE_DEG = 5.0

Vertex = tuple[float, float, float]
Triangle = tuple[int, int, int]


@dataclass(frozen=True)
class Mesh:
    vertices: tuple[Vertex, ...]
    triangles: tuple[Triangle, ...]


def tessellate(
    part: Part,
    linear_tolerance_mm: float = DEFAULT_LINEAR_TOLERANCE_MM,
    angular_tolerance_deg: float = DEFAULT_ANGULAR_TOLERANCE_DEG,
) -> Mesh:
    """Tessellate a ``Part`` into a triangle mesh.

    Uses Build123d's underlying ``Shape.tessellate(...)``. The angular
    tolerance is converted to radians at the boundary; Build123d
    expects radians.
    """
    from math import radians

    verts, tris = part.tessellate(
        tolerance=linear_tolerance_mm,
        angular_tolerance=radians(angular_tolerance_deg),
    )
    return Mesh(
        vertices=tuple((v.X, v.Y, v.Z) for v in verts),
        triangles=tuple(tris),
    )
