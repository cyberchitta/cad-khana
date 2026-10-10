from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from build123d import Compound, Keep, Location, Part, Plane, Shape, Solid, Vector

# OCP ships no type stubs.
from OCP.BRepClass3d import (  # pyright: ignore[reportMissingTypeStubs]
    BRepClass3d_SolidClassifier,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
)
from OCP.gp import (  # pyright: ignore[reportMissingTypeStubs]
    gp_Pnt,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
)
from OCP.TopAbs import (  # pyright: ignore[reportMissingTypeStubs]
    TopAbs_State,  # pyright: ignore[reportAttributeAccessIssue, reportUnknownVariableType]
)

from cad_khana.mechanism.diagnostics import (
    BOUND_EPSILON,
    INTERFERENCE_VOLUME_EPSILON_MM3,
    AssertionResult,
    Point,
    Witness,
    box_holds,
    has_surface,
    intersection_volume,
    part_bbox,
    surface_faces,
)
from cad_khana.mechanism.keepout import inexact_faces, swept

if TYPE_CHECKING:
    from cad_khana.mechanism.assembly import Assembly, PlacedPart


def _with_reason(failure: str | None, reason: str | None) -> str | None:
    """A contact claim's ``detail``: the failure if any, then the reason,
    which is recorded on a pass as well."""
    return "; ".join(s for s in (failure, reason and f"reason: {reason}") if s) or None


def _surfaces(parts: dict[str, Part], names: Iterable[str]) -> str | None:
    """Why an overlap through these parts cannot be measured, or ``None``
    when it can: a part with a surface bounds no material, so its boolean
    is empty however deep it sinks — a zero that would pass every
    no-overlap claim. The claim fails instead; distance is still defined."""
    surfaces = tuple(n for n in names if has_surface(parts[n]))
    return (
        f"overlap is undefined for a surface ({', '.join(surfaces)} has faces "
        "outside any solid, so no material to intersect); measure it with "
        "assert_distance"
        if surfaces
        else None
    )


def _extent(shape: Part, d: Vector) -> tuple[float, float]:
    """Projection interval of ``shape`` onto the unit direction ``d``:
    ``(min, max)`` of ``p . d`` over the shape's points. Computed by
    rebasing the shape into a frame whose Z axis is ``d`` and reading
    the bounding box, so it is exact for any direction."""
    bb = Plane(origin=(0, 0, 0), z_dir=d).to_local_coords(shape).bounding_box()
    return bb.min.Z, bb.max.Z


def _plane_distance(shape: Part, plane: Plane, along: Vector | None) -> float:
    """Distance from ``shape`` to the infinite datum ``plane``. With
    ``along`` (parallel to the plane normal): the directed gap — how far
    the shape travels along ``along`` before touching the plane
    (negative once past it). Without: the unsigned distance from the
    nearest point, 0 if the shape crosses the plane."""
    if along is not None:
        return plane.origin.dot(along) - _extent(shape, along)[1]
    n = plane.z_dir
    lo, hi = _extent(shape, n)
    offset = plane.origin.dot(n)
    return max(lo - offset, offset - hi, 0.0)


def _qualified_plane(plane: Plane, location: Location) -> Plane:
    return Plane(location * plane.location)


def _qualified_direction(d: Vector, location: Location) -> Vector:
    return _qualified_plane(Plane(origin=(0, 0, 0), z_dir=d), location).z_dir


@dataclass(frozen=True)
class JointWindow:
    """The kinematic phase a claim applies in: the named revolute
    joint's angle within ``[min_deg, max_deg]`` (either bound optional,
    both ``BOUND_EPSILON``-tolerant).

    Gating on a joint angle rather than on an animation parameter is
    deliberate — the joint is the physical DOF, so re-timing or
    re-sampling the animation cannot invalidate the claim, and a
    standalone run of the owning sub-assembly reads the same state.
    ``path`` is a dotted sub-assembly path (``Assembly.joint_angles``),
    qualified into the parent frame along with the rest of the
    assertion.
    """

    path: str
    min_deg: float | None = None
    max_deg: float | None = None

    def contains(self, angle_deg: float) -> bool:
        return (self.min_deg is None or angle_deg >= self.min_deg - BOUND_EPSILON) and (
            self.max_deg is None or angle_deg <= self.max_deg + BOUND_EPSILON
        )

    def describe(self) -> str:
        bounds = (
            f"[{self.min_deg:g}, {self.max_deg:g}]deg"
            if self.min_deg is not None and self.max_deg is not None
            else f">={self.min_deg:g}deg"
            if self.min_deg is not None
            else f"<={self.max_deg:g}deg"
            if self.max_deg is not None
            else "any angle"
        )
        return f"{self.path} {bounds}"


@dataclass(frozen=True)
class NoInterference:
    """Assert ``a`` and ``b`` don't overlap. ``from_group`` marks a pair
    emitted by a group expansion rather than declared by hand: a
    blanket pair yields to an ``AllowedContact`` on the same pair
    (``drop_contact_shadowed``), where a hand-written one stands and
    contradicts it loudly."""

    a: str
    b: str
    name: str
    from_group: bool = False

    @property
    def part_refs(self) -> tuple[str, ...]:
        return (self.a, self.b)

    def qualified(self, prefix: str, location: Location) -> NoInterference:
        return replace(
            self,
            a=f"{prefix}.{self.a}",
            b=f"{prefix}.{self.b}",
            name=f"{prefix}.{self.name}",
        )

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        if undefined := _surfaces(parts, self.part_refs):
            return AssertionResult(self.name, False, undefined)
        volume = intersection_volume(parts[self.a], parts[self.b])
        passed = volume <= INTERFERENCE_VOLUME_EPSILON_MM3
        detail = None if passed else f"interference volume {volume:.4f}mm^3"
        return AssertionResult(self.name, passed, detail)


@dataclass(frozen=True)
class TangentContact:
    """Assert ``a`` and ``b`` touch: surface gap ≤ ``tol_mm`` and no
    real overlap (intersection volume ≤ epsilon). The required-contact
    face of the contact pair — where ``assert_no_interference`` on a
    tangent rest would also pass with the parts floating 3mm apart,
    this fails on the gap. The measured gap is recorded in ``value``
    even on pass, so ``khana diff`` sees a rest drifting within
    tolerance."""

    a: str
    b: str
    name: str
    tol_mm: float = 1e-3

    @property
    def part_refs(self) -> tuple[str, ...]:
        return (self.a, self.b)

    def qualified(self, prefix: str, location: Location) -> TangentContact:
        return replace(
            self,
            a=f"{prefix}.{self.a}",
            b=f"{prefix}.{self.b}",
            name=f"{prefix}.{self.name}",
        )

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        if undefined := _surfaces(parts, self.part_refs):
            return AssertionResult(self.name, False, undefined)
        overlap = intersection_volume(parts[self.a], parts[self.b])
        if overlap > INTERFERENCE_VOLUME_EPSILON_MM3:
            return AssertionResult(
                self.name,
                False,
                f"contact overlaps: volume {overlap:.4f}mm^3",
                value=0.0,
            )
        gap = parts[self.a].distance_to(parts[self.b])
        passed = gap <= self.tol_mm + BOUND_EPSILON
        detail = (
            None
            if passed
            else f"no contact: gap {gap:.4f}mm exceeds tol {self.tol_mm}mm"
        )
        return AssertionResult(self.name, passed, detail, value=gap)

    def slack(self, value: float) -> float:
        return self.tol_mm - value


@dataclass(frozen=True)
class AllowedContact:
    """Assert any overlap between ``a`` and ``b`` stays within bounds —
    design-intended contact (a press-fit modeled at its true
    interference) declared instead of fudged away. A gap passes:
    contact is allowed, not required. ``min_overlap_mm3`` makes
    engagement itself the claim — a press-fit that drifts back to a
    clearance fit fails rather than silently passing. The measured
    overlap volume is recorded in ``value`` even on pass, so runs are
    diffable. ``reason`` documents the intent and is recorded in
    ``detail`` on a pass too (appended to the failure otherwise): it
    labels the claim, and a label is as true when the claim holds.

    A contact claim is a *permission*, and under ``Phased`` it lapses
    differently from a requirement: what lies beneath a permission is
    the default it was an exception to, so outside its phase the pair
    is held to no contact at all (``forbidden``). That is the
    difference between declaring a contact and suppressing a pair — a
    suppressed pair is invisible at every frame, where a phased claim
    still fails if the contact shows up in the wrong phase."""

    a: str
    b: str
    name: str
    max_overlap_mm3: float
    min_overlap_mm3: float | None = None
    reason: str | None = None

    @property
    def part_refs(self) -> tuple[str, ...]:
        return (self.a, self.b)

    def qualified(self, prefix: str, location: Location) -> AllowedContact:
        return replace(
            self,
            a=f"{prefix}.{self.a}",
            b=f"{prefix}.{self.b}",
            name=f"{prefix}.{self.name}",
        )

    def forbidden(self, phase: str) -> AllowedContact:
        """This claim outside its phase: the band collapses to the
        interference epsilon, so any real overlap fails, with ``phase``
        (the window it fell outside) in the reason."""
        return replace(
            self,
            max_overlap_mm3=INTERFERENCE_VOLUME_EPSILON_MM3,
            min_overlap_mm3=None,
            reason="; ".join(
                s for s in (self.reason, f"contact declared only during {phase}") if s
            ),
        )

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        if undefined := _surfaces(parts, self.part_refs):
            return AssertionResult(
                self.name, False, _with_reason(undefined, self.reason)
            )
        overlap = intersection_volume(parts[self.a], parts[self.b])
        above = overlap > self.max_overlap_mm3 + BOUND_EPSILON
        below = (
            self.min_overlap_mm3 is not None
            and overlap < self.min_overlap_mm3 - BOUND_EPSILON
        )
        failure = (
            f"overlap {overlap:.4f}mm^3 above max {self.max_overlap_mm3}mm^3"
            if above
            else f"overlap {overlap:.4f}mm^3 below min {self.min_overlap_mm3}mm^3"
            if below
            else None
        )
        return AssertionResult(
            self.name,
            not (above or below),
            _with_reason(failure, self.reason),
            value=overlap,
        )

    def slack(self, value: float) -> float:
        return min(
            self.max_overlap_mm3 - value,
            value - self.min_overlap_mm3
            if self.min_overlap_mm3 is not None
            else float("inf"),
        )


# A point within the kernel's own coincidence tolerance of a solid's
# boundary is on it, and a point on it is not inside: parts that touch
# can read a gap of solver noise, and a vertex resting on the other's
# face must not then be found in its material.
ON_BOUNDARY_MM = 1e-7


def _probes(part: Part) -> tuple[tuple[str, Point], ...]:
    """One point on each piece of ``part`` that can lie in another
    part's material, with the piece's kind: every solid, and every face
    outside any solid. A vertex, so it is on the piece's own boundary."""
    pieces = (
        *(("solid", s) for s in part.solids()),
        *(("face", f) for f in surface_faces(part)),
    )
    return tuple((kind, _point(piece.vertices()[0].center())) for kind, piece in pieces)


def _in_material(solid: Solid, point: Point) -> bool:
    """``point`` strictly inside ``solid``'s material: not on its
    boundary, and not in a cavity, which is outside it."""
    classifier = BRepClass3d_SolidClassifier(solid.wrapped)  # pyright: ignore[reportUnknownVariableType]
    classifier.Perform(gp_Pnt(*point), ON_BOUNDARY_MM)  # pyright: ignore[reportUnknownMemberType]
    return classifier.State() == TopAbs_State.TopAbs_IN  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]


@dataclass(frozen=True)
class _Enclosure:
    """A piece of ``inner`` lying in ``outer``'s material, found ``at``
    a point of both. ``piece`` is its kind when ``inner`` is several
    pieces, ``None`` when it is the whole part."""

    inner: str
    outer: str
    piece: str | None
    at: Point

    def describe(self) -> str:
        whole = "" if self.piece is None else f"a {self.piece} of "
        return f"{whole}{self.inner} lies inside {self.outer}"


def _enclosed(inner: str, outer: str, parts: dict[str, Part]) -> _Enclosure | None:
    """Where a piece of ``inner`` lies in a solid of ``outer``, given
    that their boundaries do not meet. A piece is connected, so with no
    boundary to cross it is in a solid's material wholly or not at all,
    and one point of it decides. The box test is exact: a point outside
    a solid's box is outside the solid."""
    probes = _probes(parts[inner])
    solids = tuple((s, part_bbox(s)) for s in parts[outer].solids())
    return next(
        (
            _Enclosure(inner, outer, kind if len(probes) > 1 else None, at)
            for kind, at in probes
            for solid, box in solids
            if box_holds(box, at) and _in_material(solid, at)
        ),
        None,
    )


@dataclass(frozen=True)
class Distance:
    """Bounded distance from part ``a`` to target ``b`` — another part,
    or a datum ``Plane`` (infinite). A plane and an ``along`` direction
    are both declared in the asserting assembly's frame and composed
    through placements like everything else.

    Without ``along``: the minimum surface-to-surface distance (0 when
    touching or overlapping). One part wholly inside another's material
    is past contact, so it reads 0 too, though no surfaces meet: the
    kernel's distance between two compounds is positive there, and a
    ``min_mm`` would pass. ``detail`` then names the inner part, on a
    pass as well, and ``witness_mm`` is a point of it twice over. A part
    in another's cavity is clear of its material and keeps its distance;
    a surface has no material, so nothing is inside one.
    With ``along`` (a unit direction from
    ``a`` toward ``b``): the directed gap between the projection
    intervals — ``a``'s far extent to ``b``'s near extent, whatever
    their footprints across ``along``; negative when the projections
    already overlap. It is how far ``a`` travels before touching ``b``
    when ``a``'s leading point lines up with ``b``'s nearest point along
    ``along``; otherwise that travel is longer (or never ends) and the
    gap is a lower bound on it. A ``min_mm`` is therefore safe; a
    ``max_mm`` reads an extreme point ``b`` may not be under, so it
    cannot say "rests on".

    ``grow_a_mm`` / ``grow_b_mm`` shrink the measured distance by an
    outward offset of the named side — measuring from a tip circle
    while the modeled body stays a pitch cylinder. Exact for a uniform
    (ball) offset in both metrics, and conservative (never reports more
    distance than the true offset body has) otherwise.

    ``min_mm`` / ``max_mm`` bound the result; either alone or both
    together ("close but not touching"). The measured value is recorded
    in the result's ``value`` even on pass, so runs are diffable.
    Bound comparisons carry ``BOUND_EPSILON`` so geometry constructed
    *from* the bound constant doesn't flip on solver noise.
    """

    a: str
    b: str | Plane
    name: str
    min_mm: float | None = None
    max_mm: float | None = None
    along: Vector | None = None
    grow_a_mm: float = 0.0
    grow_b_mm: float = 0.0

    @property
    def part_refs(self) -> tuple[str, ...]:
        return (self.a,) if isinstance(self.b, Plane) else (self.a, self.b)

    def qualified(self, prefix: str, location: Location) -> Distance:
        b = (
            f"{prefix}.{self.b}"
            if isinstance(self.b, str)
            else _qualified_plane(self.b, location)
        )
        along = (
            None if self.along is None else _qualified_direction(self.along, location)
        )
        return replace(
            self,
            a=f"{prefix}.{self.a}",
            b=b,
            along=along,
            name=f"{prefix}.{self.name}",
        )

    def _measure(
        self, parts: dict[str, Part]
    ) -> tuple[float, Witness | None, str | None]:
        """The distance, the nearest pair when it is read between two
        points rather than off a projection, and what put it at 0 when
        that was one part inside the other."""
        shape = parts[self.a]
        if isinstance(self.b, Plane):
            return _plane_distance(shape, self.b, self.along), None, None
        other = parts[self.b]
        if self.along is not None:
            gap = _extent(other, self.along)[0] - _extent(shape, self.along)[1]
            return gap, None, None
        # build123d leaves Shape's type parameter unbound in this signature
        gap, on_a, on_b = shape.distance_to_with_closest_points(other)  # pyright: ignore[reportUnknownMemberType]
        # A positive gap is between boundaries that do not meet, which
        # is all the kernel reads between two compounds.
        inside = (
            _enclosed(self.a, self.b, parts) or _enclosed(self.b, self.a, parts)
            if gap > 0.0
            else None
        )
        return (
            (gap, (_point(on_a), _point(on_b)), None)
            if inside is None
            else (0.0, (inside.at, inside.at), inside.describe())
        )

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        gap, witness, inside = self._measure(parts)
        measured = gap - self.grow_a_mm - self.grow_b_mm
        below = self.min_mm is not None and measured < self.min_mm - BOUND_EPSILON
        above = self.max_mm is not None and measured > self.max_mm + BOUND_EPSILON
        failure = (
            f"distance {measured:.4f}mm below min {self.min_mm}mm"
            if below
            else f"distance {measured:.4f}mm above max {self.max_mm}mm"
            if above
            else None
        )
        return AssertionResult(
            self.name,
            not (below or above),
            "; ".join(s for s in (failure, inside) if s) or None,
            value=measured,
            witness_mm=witness,
        )

    def slack(self, value: float) -> float:
        return min(
            value - self.min_mm if self.min_mm is not None else float("inf"),
            self.max_mm - value if self.max_mm is not None else float("inf"),
        )


def _point(v: Vector) -> Point:
    return (v.X, v.Y, v.Z)


def _at(v: Vector) -> str:
    return ", ".join(f"{c:.2f}" for c in v)


def _largest(common: Shape | Iterable[Shape]) -> Shape:
    """The overlap's largest piece: ``a & b`` is a ``ShapeList`` when an
    input is a multi-body compound."""
    return common if isinstance(common, Shape) else max(common, key=lambda s: s.volume)


# Material within this height of a seat plane counts as the seat: the
# face a keep-out stands on is coplanar with the keep-out's base, and
# clipping exactly at the plane would leave that face, at distance 0.
SEAT_EPSILON_MM = 1e-3


def _past(shape: Shape, seat: Plane) -> Shape | None:
    """The part of ``shape`` strictly on the keep-out side of ``seat``
    (its normal side), or ``None`` when nothing of it is."""
    kept = shape.split(seat.offset(SEAT_EPSILON_MM), keep=Keep.TOP)
    return Compound(kept) if isinstance(kept, list) else kept


@dataclass(frozen=True)
class _Reading:
    """One part against a keep-out. ``distance`` is ``None`` for a part
    with nothing past the seat: its contact is the seat's."""

    part: str
    overlap: float
    distance: float | None
    measured: Shape | None

    def failure(self, keepout: Shape, min_mm: float) -> str | None:
        return (
            f"{self.part} overlaps the keep-out by {self.overlap:.4f}mm^3 "
            f"centred at ({_at(_largest(self.measured & keepout).center())})"
            if self.overlap > INTERFERENCE_VOLUME_EPSILON_MM3
            else f"{self.part} distance {self.distance:.4f}mm below min "
            f"{min_mm}mm at ({_at(self.measured.closest_points(keepout)[0])})"
            if self.distance is not None and self.distance < min_mm - BOUND_EPSILON
            else None
        )


def _reading(part: str, shape: Shape, keepout: Shape, seat: Plane | None) -> _Reading:
    overlap = intersection_volume(shape, keepout)
    if overlap > 0.0:
        return _Reading(part, overlap, 0.0, shape)
    past = shape if seat is None else _past(shape, seat)
    return _Reading(
        part, overlap, None if past is None else past.distance_to(keepout), past
    )


@dataclass(frozen=True)
class KeepOut:
    """The parts ``parts`` stay out of ``keepout`` — a solid that is not
    a part: a driver's corridor, a bolt's drop-in path, an RF zone. It is
    never exported or drawn, because it is not a part. ``keepout`` is
    either the solid, declared in the asserting assembly's frame and
    composed through placements like a datum ``Plane``, or the dotted
    path of a keep-out a unit declared by name (``with_keepout``),
    resolved against the tree at each pose (``bound``) like an anchor.

    One claim, one result. Any overlap fails, whatever ``min_mm``: a
    distance of 0 cannot tell touching from inside. Otherwise every
    part's distance must reach ``min_mm``, so the default 0 allows
    touching. ``value`` is the least distance over the parts, 0 when
    one overlaps. ``detail`` names the nearest part on a pass (a label,
    true either way) and, on a failure, every failing part with its
    reading and a witness: its point nearest the keep-out, or the
    centroid of the overlap.

    ``seat`` is a plane whose normal points into the keep-out — the face
    it stands on, declared and composed with it. Contact there is the
    design, so distance is measured from each part's material strictly
    past the seat (``SEAT_EPSILON_MM``); the overlap test still takes the
    whole part. A part with nothing past the seat has no distance, and
    when no part has any, ``value`` is ``None``.

    A part in ``parts`` absent from the run skips the whole claim as
    ``absent_part``, as for every claim naming its parts: a minimum
    taken over the parts that happen to be present would read as
    covering the ones it never looked at."""

    parts: tuple[str, ...]
    keepout: Shape | str
    name: str
    min_mm: float = 0.0
    seat: Plane | None = None

    @property
    def part_refs(self) -> tuple[str, ...]:
        return self.parts

    def qualified(self, prefix: str, location: Location) -> KeepOut:
        return replace(
            self,
            parts=tuple(f"{prefix}.{n}" for n in self.parts),
            keepout=(
                f"{prefix}.{self.keepout}"
                if isinstance(self.keepout, str)
                else self.keepout.moved(location)
            ),
            seat=None if self.seat is None else _qualified_plane(self.seat, location),
            name=f"{prefix}.{self.name}",
        )

    def bound(self, assembly: Assembly) -> KeepOut:
        """This claim with a named keep-out resolved to its solid and
        seat where the assembly stands now."""
        if not isinstance(self.keepout, str):
            return self
        zone = assembly.keepout(self.keepout)
        return replace(self, keepout=zone.solid, seat=zone.seat)

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        if undefined := _surfaces(parts, self.parts):
            return AssertionResult(
                self.name, False, undefined, measured=len(self.parts)
            )
        readings = tuple(
            _reading(n, parts[n], self.keepout, self.seat) for n in self.parts
        )
        read = tuple(r for r in readings if r.distance is not None)
        nearest = min(read, key=lambda r: r.distance, default=None)
        failures = tuple(
            f
            for r in sorted(read, key=lambda r: (r.distance, -r.overlap))
            if (f := r.failure(self.keepout, self.min_mm))
        )
        detail = (
            f"{len(failures)} of {len(readings)} parts: " + "; ".join(failures)
            if failures
            else f"none of the {len(readings)} selected parts has material past the seat"
            if nearest is None
            else f"nearest of {len(readings)}: {nearest.part} at {nearest.distance:.4f}mm"
        )
        return AssertionResult(
            self.name,
            not failures,
            detail,
            value=None if nearest is None else nearest.distance,
            measured=len(readings),
        )

    def slack(self, value: float) -> float:
        return value - self.min_mm


# How far past the inner part's extent the footprint prism reaches at
# each end, so its caps never coincide with the inner part's faces. Any
# positive length gives the same prism over that extent.
FOOTPRINT_MARGIN_MM = 1.0


def _footprint(outer: Part, along: Vector, span: tuple[float, float]) -> Part:
    """``outer`` swept both ways along ``along`` far enough to cover
    ``span`` (a projection interval on it): every point within ``span``
    whose line along the axis meets ``outer`` lies in it."""
    lo, hi = span
    o_lo, o_hi = _extent(outer, along)
    start = lo - o_hi - FOOTPRINT_MARGIN_MM
    travel = (hi - lo) + (o_hi - o_lo) + 2 * FOOTPRINT_MARGIN_MM
    return swept(outer.moved(Location(tuple(along * start))), along * travel)


def _protrusion(name: str, outer: str, along: Vector, pieces: list[Solid]) -> str:
    volume = sum(p.volume for p in pieces)
    largest = max(pieces, key=lambda p: p.volume)
    box = largest.bounding_box()
    count = f"{len(pieces)} piece{'' if len(pieces) == 1 else 's'}"
    return (
        f"{name} outside {outer}'s footprint along ({_at(along)}): "
        f"{volume:.4f}mm^3 in {count}; largest centred at "
        f"({_at(largest.center())}), spanning ({_at(box.min)}) to ({_at(box.max)})"
    )


@dataclass(frozen=True)
class Within:
    """``a``'s footprint along ``along`` lies within ``b``'s: what is
    left of ``a`` once the prism of ``b`` swept along the axis across
    all of ``a``'s extent is cut away is empty. A plan-view claim — a
    foot resting *on* a rail stays on it, a ring stays over its seat —
    so ``a`` need not overlap ``b`` at all, and holes in ``b``'s
    footprint count: a ring reaching inside a seat's bore fails where a
    bounding-box comparison would pass.

    ``value`` is the protrusion's volume in mm³, on a pass too; up to
    ``INTERFERENCE_VOLUME_EPSILON_MM3`` it is within. ``along`` is
    declared in the asserting assembly's frame and composed through
    placements, as for ``Distance``. The prism is ``keepout.swept``,
    exact only on planes and the quadrics; a ``b`` with any other face
    fails naming it rather than read an approximate footprint."""

    a: str
    b: str
    name: str
    along: Vector

    @property
    def part_refs(self) -> tuple[str, ...]:
        return (self.a, self.b)

    def qualified(self, prefix: str, location: Location) -> Within:
        return replace(
            self,
            a=f"{prefix}.{self.a}",
            b=f"{prefix}.{self.b}",
            along=_qualified_direction(self.along, location),
            name=f"{prefix}.{self.name}",
        )

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        if undefined := _surfaces(parts, self.part_refs):
            return AssertionResult(self.name, False, undefined)
        inner, outer = parts[self.a], parts[self.b]
        if refused := inexact_faces(outer):
            return AssertionResult(
                self.name,
                False,
                f"{self.b}'s footprint cannot be swept exactly: it has "
                f"{', '.join(refused)} faces (swept() takes planes, cylinders, "
                "cones and spheres)",
            )
        prism = _footprint(outer, self.along, _extent(inner, self.along))
        pieces = list((inner - prism).solids())
        volume = sum(p.volume for p in pieces)
        passed = volume <= INTERFERENCE_VOLUME_EPSILON_MM3
        detail = None if passed else _protrusion(self.a, self.b, self.along, pieces)
        return AssertionResult(self.name, passed, detail, value=volume)

    def slack(self, value: float) -> float:
        return INTERFERENCE_VOLUME_EPSILON_MM3 - value


@dataclass(frozen=True)
class ScalarClaim:
    """A named, recorded claim about a non-geometric scalar (a friction
    budget, a torque margin) — the value lands in diagnostics and diff
    either way; ``ge`` / ``le`` bounds make it a pass/fail assertion,
    with neither it is a pure recorder. ``detail`` is context carried
    into the result (alone on pass, appended to the bound violation on
    failure)."""

    name: str
    value: float
    ge: float | None = None
    le: float | None = None
    detail: str | None = None

    def qualified(self, prefix: str, location: Location) -> ScalarClaim:
        return replace(self, name=f"{prefix}.{self.name}")

    def evaluate(self) -> AssertionResult:
        below = self.ge is not None and self.value < self.ge - BOUND_EPSILON
        above = self.le is not None and self.value > self.le + BOUND_EPSILON
        failure = (
            f"value {self.value:.6g} below ge {self.ge}"
            if below
            else f"value {self.value:.6g} above le {self.le}"
            if above
            else None
        )
        detail = "; ".join(s for s in (failure, self.detail) if s) or None
        return AssertionResult(
            self.name, not (below or above), detail, value=self.value
        )


@dataclass(frozen=True)
class SolidCount:
    """Assert ``part`` is exactly ``eq`` solids — the one claim about
    connectivity. Volume, bbox, clearance and interference cannot tell
    a part in one piece from one a cut has severed, and neither can a
    drawing. ``eq=1`` bounds it; any other ``eq`` declares a part that
    is several solids on purpose, which is also what keeps it out of
    the ``multi_solid`` warnings. A topological claim, so it has no
    phase: the count is the same at every pose. ``detail`` is the
    failure hypothesis — what would have severed it, which no drawing
    shows — appended to the count on failure and absent on a pass: on
    a green ``eq=2`` it would read as a report of the failure itself."""

    part: str
    eq: int
    name: str
    detail: str | None = None

    @property
    def part_refs(self) -> tuple[str, ...]:
        return (self.part,)

    def qualified(self, prefix: str, location: Location) -> SolidCount:
        return replace(self, part=f"{prefix}.{self.part}", name=f"{prefix}.{self.name}")

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        count = len(parts[self.part].solids())
        passed = count == self.eq
        failure = f"{count} solids, expected {self.eq}"
        detail = None if passed else "; ".join(s for s in (failure, self.detail) if s)
        return AssertionResult(self.name, passed, detail, value=float(count))


@dataclass(frozen=True)
class ExpectedInterference:
    """Assert that two parts DO interfere — a regression alarm for a
    known, accepted overlap. Fails if the overlap disappears, so the
    assertion can't go stale once the underlying design gap is fixed.
    Use sparingly: the default is `assert_no_interference`; reach for
    this only when a real-world design constraint leaves a documented
    overlap that hasn't been resolved yet.
    """

    a: str
    b: str
    name: str
    reason: str | None = None

    @property
    def part_refs(self) -> tuple[str, ...]:
        return (self.a, self.b)

    def qualified(self, prefix: str, location: Location) -> ExpectedInterference:
        return replace(
            self,
            a=f"{prefix}.{self.a}",
            b=f"{prefix}.{self.b}",
            name=f"{prefix}.{self.name}",
        )

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        if undefined := _surfaces(parts, self.part_refs):
            return AssertionResult(
                self.name, False, _with_reason(undefined, self.reason)
            )
        volume = intersection_volume(parts[self.a], parts[self.b])
        passed = volume > INTERFERENCE_VOLUME_EPSILON_MM3
        failure = (
            None
            if passed
            else f"expected interference absent (volume {volume:.4f}mm^3)"
        )
        return AssertionResult(self.name, passed, _with_reason(failure, self.reason))


@dataclass(frozen=True)
class AnchorsCoincident:
    """Assert two named anchors resolve to the same position (within
    ``tol_mm``; orientation is ignored). ``a`` / ``b`` are dotted
    anchor paths resolved against the asserting assembly at evaluation
    time (``Assembly.anchor``), so the check reflects placements and
    joint angles as of ``check()``. Unlike the part assertions, this
    needs the assembly (not the placed-parts dict) to evaluate.
    """

    a: str
    b: str
    tol_mm: float
    name: str

    def qualified(self, prefix: str, location: Location) -> AnchorsCoincident:
        return replace(
            self,
            a=f"{prefix}.{self.a}",
            b=f"{prefix}.{self.b}",
            name=f"{prefix}.{self.name}",
        )

    def evaluate_on(self, assembly: Assembly) -> AssertionResult:
        pa = assembly.anchor(self.a).position
        pb = assembly.anchor(self.b).position
        dist = (pa - pb).length
        passed = dist <= self.tol_mm
        detail = (
            None
            if passed
            else (
                f"anchors differ by {dist:.6f}mm (tol {self.tol_mm}mm): "
                f"{self.a} at ({pa.X:.6f}, {pa.Y:.6f}, {pa.Z:.6f}), "
                f"{self.b} at ({pb.X:.6f}, {pb.Y:.6f}, {pb.Z:.6f})"
            )
        )
        return AssertionResult(self.name, passed, detail)


PartAssertion = (
    NoInterference
    | TangentContact
    | AllowedContact
    | ExpectedInterference
    | Distance
    | KeepOut
    | Within
)


@dataclass(frozen=True)
class Phased:
    """``inner`` held only during a kinematic phase — every window in
    ``during`` containing its joint's value. The one phase mechanism:
    ``during=`` on each ``assert_*`` wraps the claim in this.

    Outside the phase a claim says nothing, and what "nothing" means
    follows from its kind. A *requirement* (no-interference, distance, tangent
    contact, expected interference, footprint) lapses —
    ``passed: null``, skip class ``out_of_phase``. A *permission*
    (``AllowedContact``) lapses to the default it was an exception to,
    no contact — unless another contact claim on the same pair is in
    phase, in which case that one governs and this one is
    ``out_of_phase``. Phased permissions on a pair partition the
    motion; where none applies, contact is forbidden.
    """

    inner: PartAssertion
    during: tuple[JointWindow, ...]

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def part_refs(self) -> tuple[str, ...]:
        return self.inner.part_refs

    def qualified(self, prefix: str, location: Location) -> Phased:
        return Phased(
            self.inner.qualified(prefix, location),
            tuple(replace(w, path=f"{prefix}.{w.path}") for w in self.during),
        )

    def describe(self) -> str:
        return " & ".join(w.describe() for w in self.during)

    def absent_joints(self, values: dict[str, float]) -> tuple[str, ...]:
        return tuple(w.path for w in self.during if w.path not in values)

    def in_phase(self, values: dict[str, float]) -> bool:
        return all(w.contains(values[w.path]) for w in self.during)

    def state(self, values: dict[str, float]) -> str:
        """Where the joints stand against the windows, for a detail
        line: ``"swing at 90deg"``."""
        return ", ".join(f"{w.path} at {values[w.path]:g}deg" for w in self.during)


Assertion = PartAssertion | Phased | AnchorsCoincident | ScalarClaim | SolidCount

# Where a claim stands at one pose. ``FORBID`` is a permission outside
# its phase with no sibling permission in force; ``OUT`` is a lapsed
# requirement, or a permission another one governs.
IN = "in"
OUT = "out_of_phase"
FORBID = "forbid"
ABSENT_JOINT = "absent_joint"

Contacts = dict[frozenset[str], tuple["AllowedContact | Phased", ...]]


def core(assertion: Assertion) -> Assertion:
    """The claim itself, with any phase wrapper removed."""
    return assertion.inner if isinstance(assertion, Phased) else assertion


def drop_contact_shadowed(
    assertions: tuple[Assertion, ...],
) -> tuple[Assertion, ...]:
    """Drop group-derived ``NoInterference`` pairs that also carry an
    ``AllowedContact`` in the same set: the contact claim already holds
    the pair at every frame — inside its window to the overlap band,
    outside it to plain no-interference — so a blanket pair from a
    group expansion could only contradict it.

    Derived over the assembled set rather than at expansion time so it
    is order-free: a contact declared *after* the group call, or at a
    level above it, wins just the same. Reading it at expansion made a
    same-level contact declared below the group call invisible, and the
    pair then failed as a plain interference — a real press fit reading
    as a broken one, with nothing pointing at declaration order.
    """
    contacts = contact_claims(assertions)
    return tuple(
        a
        for a in assertions
        if not (
            isinstance(claim := core(a), NoInterference)
            and claim.from_group
            and frozenset(a.part_refs) in contacts
        )
    )


def solid_count_claimed(assertions: tuple[Assertion, ...]) -> frozenset[str]:
    """The parts a solid-count claim speaks for."""
    return frozenset(a.part for a in assertions if isinstance(a, SolidCount))


def contact_claims(assertions: tuple[Assertion, ...]) -> Contacts:
    """Every contact claim, phased or not, by the pair it is about."""
    claims: Contacts = {}
    for a in assertions:
        if isinstance(core(a), AllowedContact):
            pair = frozenset(a.part_refs)
            claims[pair] = claims.get(pair, ()) + (a,)
    return claims


def _placed(p: PlacedPart) -> Part:
    return p.part.moved(p.location)


def _in_force(claim: Assertion, values: dict[str, float]) -> bool:
    return not isinstance(claim, Phased) or (
        not claim.absent_joints(values) and claim.in_phase(values)
    )


def phase(assertion: Assertion, values: dict[str, float], contacts: Contacts) -> str:
    if not isinstance(assertion, Phased):
        return IN
    if assertion.absent_joints(values):
        return ABSENT_JOINT
    if assertion.in_phase(values):
        return IN
    if not isinstance(assertion.inner, AllowedContact):
        return OUT
    governed = any(
        claim != assertion and _in_force(claim, values)
        for claim in contacts[frozenset(assertion.part_refs)]
    )
    return OUT if governed else FORBID


def resolved(assertion: Assertion, state: str) -> Assertion:
    """The claim as it stands in ``state`` — itself, or for a permission
    out of phase, its forbidding form."""
    return (
        assertion.inner.forbidden(assertion.describe())
        if state == FORBID
        and isinstance(assertion, Phased)
        and isinstance(assertion.inner, AllowedContact)
        else core(assertion)
    )


def bound(assertion: Assertion, assembly: Assembly) -> Assertion:
    """The claim with anything it names in the tree — a named keep-out —
    resolved where the assembly stands, phase wrapper kept."""
    claim = core(assertion)
    if not isinstance(claim, KeepOut):
        return assertion
    return (
        replace(assertion, inner=claim.bound(assembly))
        if isinstance(assertion, Phased)
        else claim.bound(assembly)
    )


def _skipped(name: str, kind: str, detail: str) -> AssertionResult:
    return AssertionResult(name, None, f"skipped: {detail}", skipped=kind)


def evaluate_one(
    assertion: Assertion,
    assembly: Assembly,
    parts: dict[str, Part],
    values: dict[str, float],
    contacts: Contacts,
) -> AssertionResult:
    """One assertion at one pose. Absence — of a joint, then of a part —
    is reported ahead of the phase: it is the same at every pose, and a
    typo'd name must not hide behind a skip class that reads as
    expected. Absence is a legitimate run state, not an input error:
    detail geometry is applied by an override, and a standalone
    sub-assembly run evaluates the same list below the level that owns
    the joint."""
    if isinstance(assertion, AnchorsCoincident):
        return assertion.evaluate_on(assembly)
    if isinstance(assertion, ScalarClaim):
        return assertion.evaluate()
    assertion = bound(assertion, assembly)
    state = phase(assertion, values, contacts)
    if isinstance(assertion, Phased) and state == ABSENT_JOINT:
        joints = ", ".join(assertion.absent_joints(values))
        return _skipped(
            assertion.name,
            "absent_joint",
            f"joint absent from this run: {joints}",
        )
    missing = sorted(n for n in assertion.part_refs if n not in parts)
    if missing:
        return _skipped(
            assertion.name,
            "absent_part",
            f"part(s) absent from this run: {', '.join(missing)}",
        )
    if isinstance(assertion, Phased) and state == OUT:
        return _skipped(
            assertion.name,
            OUT,
            f"out of phase — holds only during {assertion.describe()}; "
            f"{assertion.state(values)}",
        )
    result = resolved(assertion, state).evaluate(parts)
    return (
        replace(result, detail=f"{result.detail}; {assertion.state(values)}")
        if state == FORBID and result.detail and isinstance(assertion, Phased)
        else result
    )


def evaluate(assembly: Assembly) -> tuple[AssertionResult, ...]:
    """Every assertion at the pose the assembly is in. ``hold`` is the
    same over every declared motion."""
    parts = {p.name: _placed(p) for p in assembly.placed_parts}
    values = assembly.joint_angles
    assertions = assembly.all_assertions
    contacts = contact_claims(assertions)
    return tuple(evaluate_one(a, assembly, parts, values, contacts) for a in assertions)
