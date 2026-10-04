from __future__ import annotations

from dataclasses import dataclass
from math import asin, degrees

from build123d import Part, Plane, Vector

from cad_khana.core.tessellation import Triangle, _tessellate_faces, on_surface
from cad_khana.mechanism.diagnostics import BBox

BUILD_PLATE_EPSILON_MM = 1e-3
# Below this a facet is a vertical wall carrying solver noise (a
# tessellated cylinder reads ~1e-16°), not a face that points down.
FACING_DOWN_EPSILON_DEG = 1e-6


@dataclass(frozen=True)
class OverhangRegion:
    """The facets of one B-rep face that count toward ``area_mm2`` —
    where the area sits, as a waiver text names it ("the Ø5.4 pin bore
    crown")."""

    area_mm2: float
    max_angle_deg: float
    centroid_mm: tuple[float, float, float]
    bbox: BBox


@dataclass(frozen=True)
class Overhang:
    area_mm2: float
    max_angle_deg: float
    regions: tuple[OverhangRegion, ...]


@dataclass(frozen=True)
class _Facet:
    triangle: Triangle
    angle_deg: float


def _overhang_angle_deg(normal: Vector, up: Vector) -> float:
    downward = min(1.0, max(0.0, -normal.dot(up)))
    return degrees(asin(downward))


def _build_plate_level(part: Part, up: Vector) -> float:
    """The part's lowest point along ``up``: its bbox in a frame whose Z
    is ``up``. The world bbox's lowest corner lies below every point of
    the part once ``up`` is oblique, so nothing matched the plate. Not
    the lowest mesh vertex: on a curved bottom that sits above the true
    lowest point and drops the contact strip, moving axis-aligned readings."""
    frame = Plane(origin=(0, 0, 0), z_dir=up)
    return frame.to_local_coords(part).bounding_box().min.Z


def _on_build_plate(triangle: Triangle, up: Vector, min_up: float) -> bool:
    on_plane = abs(triangle.centroid.dot(up) - min_up) < BUILD_PLATE_EPSILON_MM
    faces_down = triangle.normal.dot(up) < -0.999
    return on_plane and faces_down


def _region(facets: tuple[_Facet, ...]) -> OverhangRegion:
    area = sum(f.triangle.area for f in facets)
    centroid = (
        sum((f.triangle.centroid * f.triangle.area for f in facets), Vector()) / area
    )
    corners = tuple(c for f in facets for c in f.triangle.corners)
    return OverhangRegion(
        area_mm2=area,
        max_angle_deg=max(f.angle_deg for f in facets),
        centroid_mm=(centroid.X, centroid.Y, centroid.Z),
        bbox=BBox(
            min=(
                min(c.X for c in corners),
                min(c.Y for c in corners),
                min(c.Z for c in corners),
            ),
            max=(
                max(c.X for c in corners),
                max(c.Y for c in corners),
                max(c.Z for c in corners),
            ),
        ),
    )


def _facing_down(part: Part, up: Vector) -> tuple[tuple[_Facet, ...], ...]:
    min_up = _build_plate_level(part, up)
    return tuple(
        tuple(
            _Facet(t, ang)
            for t in face
            if (ang := _overhang_angle_deg(t.normal, up)) > FACING_DOWN_EPSILON_DEG
            and not _on_build_plate(t, up, min_up)
        )
        for face in _tessellate_faces(part)
    )


def _over(
    facing_down: tuple[tuple[_Facet, ...], ...], threshold: float
) -> tuple[tuple[_Facet, ...], ...]:
    return tuple(
        counted
        for face in facing_down
        if (counted := tuple(f for f in face if f.angle_deg > threshold))
    )


def _largest_first(
    over: tuple[tuple[_Facet, ...], ...],
) -> tuple[OverhangRegion, ...]:
    return tuple(sorted((_region(face) for face in over), key=lambda r: -r.area_mm2))


def detect_overhang(
    part: Part,
    *,
    up_axis: tuple[float, float, float] = (0, 0, 1),
    angle_threshold_deg: float = 45.0,
) -> Overhang | None:
    """Every down-facing facet off the build plate sets ``max_angle_deg``;
    those past the threshold count toward ``area_mm2`` and are grouped
    by B-rep face into ``regions``, largest first — every region, with
    no size floor, so the regions' areas sum to ``area_mm2``."""
    facing_down = _facing_down(part, Vector(*up_axis).normalized())
    regions = _largest_first(_over(facing_down, angle_threshold_deg))
    return (
        Overhang(
            area_mm2=sum((r.area_mm2 for r in regions), 0.0),
            max_angle_deg=max(f.angle_deg for face in facing_down for f in face),
            regions=regions,
        )
        if any(facing_down)
        else None
    )


def regions_with_points(
    part: Part,
    *,
    up_axis: tuple[float, float, float] = (0, 0, 1),
    angle_threshold_deg: float = 45.0,
) -> tuple[tuple[OverhangRegion, tuple[Vector, ...]], ...]:
    """``detect_overhang``'s regions, largest first, each with the points
    that say which surface it lies on: its facets' corners, and their
    centroids projected onto the face. Corners alone sit on the face's
    boundary — a bore's long facets span it end to end, so every corner
    also lies on the faces the bore passes through."""
    facing_down = _facing_down(part, Vector(*up_axis).normalized())
    return tuple(
        sorted(
            (
                (
                    _region(counted),
                    tuple(c for f in counted for c in f.triangle.corners)
                    + tuple(on_surface(face, f.triangle).centroid for f in counted),
                )
                for face, facets in zip(part.faces(), facing_down)
                if (
                    counted := tuple(
                        f for f in facets if f.angle_deg > angle_threshold_deg
                    )
                )
            ),
            key=lambda pair: -pair[0].area_mm2,
        )
    )
