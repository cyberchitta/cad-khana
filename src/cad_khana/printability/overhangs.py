from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import pairwise
from math import asin, degrees

from build123d import Face, Part, Plane, Vector

from cad_khana.core.tessellation import Triangle, _tessellate_faces, normals, on_surface
from cad_khana.mechanism.diagnostics import BOUND_EPSILON, BBox

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
    """A facet with the face's angle at its three corners, then under its
    centroid. A counted piece of one keeps the whole facet's angles."""

    triangle: Triangle
    angles_deg: tuple[float, ...]

    @property
    def angle_deg(self) -> float:
        return max(self.angles_deg)


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


def _surface_angles_deg(
    face: Face, triangle: Triangle, up: Vector
) -> tuple[float, ...]:
    """What the face reads over one facet. The facet's own plane is a
    chord: a cone meshes into long triangles tilted off it, whose normals
    read 46.7° on a 45° cone and scatter to both sides of it, so the
    angles are the surface's — at the facet's corners as well as its
    middle, since a curved face is steepest at one end of a facet. Where
    the surface has no normal the facet's steepest reading stands in."""
    read = tuple(
        None if n is None else _overhang_angle_deg(n, up)
        for n in normals(face, triangle)
    )
    steepest = max((a for a in read if a is not None), default=0.0)
    return tuple(steepest if a is None else a for a in read)


def _facing_down(part: Part, up: Vector) -> tuple[tuple[_Facet, ...], ...]:
    min_up = _build_plate_level(part, up)
    return tuple(
        tuple(
            facet
            for t in facets
            if (facet := _Facet(t, _surface_angles_deg(face, t, up))).angle_deg
            > FACING_DOWN_EPSILON_DEG
            and not _on_build_plate(t, up, min_up)
        )
        for face, facets in zip(part.faces(), _tessellate_faces(part), strict=True)
    )


def _above(
    points: tuple[Vector, ...], angles: tuple[float, ...], limit: float
) -> tuple[Triangle, ...]:
    """The part of one triangle where the angle, taken as linear between
    its corners, is past ``limit``."""
    ring = tuple(zip(points, angles, strict=True))
    kept = tuple(
        v
        for (p, a), (q, b) in zip(ring, ring[1:] + ring[:1], strict=True)
        for v in (
            *((p,) if a > limit else ()),
            *(
                (p + (q - p) * ((limit - a) / (b - a)),)
                if (a > limit) != (b > limit)
                else ()
            ),
        )
    )
    return tuple(Triangle.create(kept[0], b, c) for b, c in pairwise(kept[1:]))


def _counted(facet: _Facet, limit: float) -> tuple[Triangle, ...]:
    """The part of a facet past ``limit``. A facet straddling it is cut
    where the angle crosses, in the three triangles its centroid makes
    with its edges: counted whole, the same bore read 4.7% or 14.2% over
    as the mesh seam turned, and the centroid's own reading is what sees
    a crown narrower than the facet across it."""
    *corners, middle = facet.angles_deg
    return (
        (facet.triangle,)
        if min(facet.angles_deg) > limit
        else ()
        if facet.angle_deg <= limit
        else tuple(
            piece
            for i, j in ((0, 1), (1, 2), (2, 0))
            for piece in _above(
                (
                    facet.triangle.corners[i],
                    facet.triangle.corners[j],
                    facet.triangle.centroid,
                ),
                (corners[i], corners[j], middle),
                limit,
            )
        )
    )


def _past(facets: tuple[_Facet, ...], threshold: float) -> tuple[_Facet, ...]:
    """What counts toward area, as facets and cut pieces of facets: past
    the threshold by more than the tolerance ``passed`` is judged with,
    so a face at the threshold counts none."""
    return tuple(
        replace(f, triangle=piece)
        for f in facets
        for piece in _counted(f, threshold + BOUND_EPSILON)
    )


def _over(
    facing_down: tuple[tuple[_Facet, ...], ...], threshold: float
) -> tuple[tuple[_Facet, ...], ...]:
    return tuple(counted for face in facing_down if (counted := _past(face, threshold)))


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
    what lies past the threshold counts toward ``area_mm2`` and is grouped
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
                for face, facets in zip(part.faces(), facing_down, strict=True)
                if (counted := _past(facets, angle_threshold_deg))
            ),
            key=lambda pair: -pair[0].area_mm2,
        )
    )
