from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from build123d import Location, Part, Plane, Vector

from cad_khana.mechanism.diagnostics import (
    BOUND_EPSILON,
    INTERFERENCE_VOLUME_EPSILON_MM3,
    AssertionResult,
    intersection_volume,
)

if TYPE_CHECKING:
    from cad_khana.mechanism.assembly import Assembly, PlacedPart


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
        return (
            self.min_deg is None or angle_deg >= self.min_deg - BOUND_EPSILON
        ) and (
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

    def qualified(self, prefix: str, location: Location) -> "NoInterference":
        return replace(
            self,
            a=f"{prefix}.{self.a}",
            b=f"{prefix}.{self.b}",
            name=f"{prefix}.{self.name}",
        )

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        volume = intersection_volume(parts[self.a], parts[self.b])
        passed = volume <= INTERFERENCE_VOLUME_EPSILON_MM3
        detail = None if passed else f"interference volume {volume:.4f}mm^3"
        return AssertionResult(self.name, passed, detail)


@dataclass(frozen=True)
class Clearance:
    a: str
    b: str
    min_mm: float
    name: str

    @property
    def part_refs(self) -> tuple[str, ...]:
        return (self.a, self.b)

    def qualified(self, prefix: str, location: Location) -> "Clearance":
        return replace(
            self,
            a=f"{prefix}.{self.a}",
            b=f"{prefix}.{self.b}",
            name=f"{prefix}.{self.name}",
        )

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        dist = parts[self.a].distance_to(parts[self.b])
        passed = dist >= self.min_mm - BOUND_EPSILON
        detail = (
            None
            if passed
            else f"clearance {dist:.4f}mm below min {self.min_mm}mm"
        )
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

    def qualified(self, prefix: str, location: Location) -> "TangentContact":
        return replace(
            self,
            a=f"{prefix}.{self.a}",
            b=f"{prefix}.{self.b}",
            name=f"{prefix}.{self.name}",
        )

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
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


@dataclass(frozen=True)
class AllowedContact:
    """Assert any overlap between ``a`` and ``b`` stays within bounds —
    design-intended contact (a press-fit modeled at its true
    interference) declared instead of fudged away. A gap passes:
    contact is allowed, not required. ``min_overlap_mm3`` makes
    engagement itself the claim — a press-fit that drifts back to a
    clearance fit fails rather than silently passing. The measured
    overlap volume is recorded in ``value`` even on pass, so runs are
    diffable. ``reason`` documents the intent and is appended to the
    failure detail.

    ``during`` narrows the claim to a kinematic phase: inside the
    window the overlap band stands, outside it contact is not allowed
    at all. That is the difference between declaring a contact and
    suppressing a pair — a suppressed pair is invisible at every frame,
    where a phased claim still fails if the contact shows up in the
    wrong phase."""

    a: str
    b: str
    name: str
    max_overlap_mm3: float
    min_overlap_mm3: float | None = None
    reason: str | None = None
    during: JointWindow | None = None

    @property
    def part_refs(self) -> tuple[str, ...]:
        return (self.a, self.b)

    def qualified(self, prefix: str, location: Location) -> "AllowedContact":
        return replace(
            self,
            a=f"{prefix}.{self.a}",
            b=f"{prefix}.{self.b}",
            name=f"{prefix}.{self.name}",
            during=(
                None
                if self.during is None
                else replace(self.during, path=f"{prefix}.{self.during.path}")
            ),
        )

    def for_angle(self, angle_deg: float) -> "AllowedContact":
        """This claim resolved against the joint's current angle, so it
        evaluates from ``parts`` alone like every other assertion.
        Inside the window the band is unchanged; outside it the band
        collapses to the interference epsilon — any real overlap in the
        wrong phase then fails, naming the window it fell outside."""
        window = self.during
        if window.contains(angle_deg):
            return replace(self, during=None)
        phase = (
            f"contact declared only during {window.describe()}, "
            f"joint at {angle_deg:g}deg"
        )
        return replace(
            self,
            during=None,
            max_overlap_mm3=INTERFERENCE_VOLUME_EPSILON_MM3,
            min_overlap_mm3=None,
            reason="; ".join(s for s in (self.reason, phase) if s),
        )

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
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
        detail = (
            f"{failure}; reason: {self.reason}"
            if failure and self.reason
            else failure
        )
        return AssertionResult(
            self.name, not (above or below), detail, value=overlap
        )


@dataclass(frozen=True)
class Distance:
    """Bounded distance from part ``a`` to target ``b`` — another part,
    or a datum ``Plane`` (infinite; declared in the asserting assembly's
    frame and composed through placements like everything else).

    Without ``along``: the minimum surface-to-surface distance (0 when
    touching or overlapping). With ``along`` (a unit direction from
    ``a`` toward ``b``): the directed gap between the projection
    intervals — how far ``a`` travels along ``along`` before first
    touching ``b``; negative when the projections already overlap.

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

    def qualified(self, prefix: str, location: Location) -> "Distance":
        b = (
            f"{prefix}.{self.b}"
            if isinstance(self.b, str)
            else _qualified_plane(self.b, location)
        )
        return replace(
            self, a=f"{prefix}.{self.a}", b=b, name=f"{prefix}.{self.name}"
        )

    def _measure(self, parts: dict[str, Part]) -> float:
        shape = parts[self.a]
        if isinstance(self.b, Plane):
            return _plane_distance(shape, self.b, self.along)
        other = parts[self.b]
        if self.along is None:
            return shape.distance_to(other)
        return _extent(other, self.along)[0] - _extent(shape, self.along)[1]

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        measured = self._measure(parts) - self.grow_a_mm - self.grow_b_mm
        below = self.min_mm is not None and measured < self.min_mm - BOUND_EPSILON
        above = self.max_mm is not None and measured > self.max_mm + BOUND_EPSILON
        detail = (
            f"distance {measured:.4f}mm below min {self.min_mm}mm"
            if below
            else f"distance {measured:.4f}mm above max {self.max_mm}mm"
            if above
            else None
        )
        return AssertionResult(
            self.name, not (below or above), detail, value=measured
        )


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

    def qualified(self, prefix: str, location: Location) -> "ScalarClaim":
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

    def qualified(self, prefix: str, location: Location) -> "ExpectedInterference":
        return replace(
            self,
            a=f"{prefix}.{self.a}",
            b=f"{prefix}.{self.b}",
            name=f"{prefix}.{self.name}",
        )

    def evaluate(self, parts: dict[str, Part]) -> AssertionResult:
        volume = intersection_volume(parts[self.a], parts[self.b])
        passed = volume > INTERFERENCE_VOLUME_EPSILON_MM3
        if passed:
            detail = None
        else:
            base = f"expected interference absent (volume {volume:.4f}mm^3)"
            detail = f"{base}; reason: {self.reason}" if self.reason else base
        return AssertionResult(self.name, passed, detail)


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

    def qualified(self, prefix: str, location: Location) -> "AnchorsCoincident":
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


Assertion = (
    NoInterference
    | Clearance
    | TangentContact
    | AllowedContact
    | ExpectedInterference
    | AnchorsCoincident
    | Distance
    | ScalarClaim
)


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
    contacts = {
        frozenset((a.a, a.b))
        for a in assertions
        if isinstance(a, AllowedContact)
    }
    return tuple(
        a
        for a in assertions
        if not (
            isinstance(a, NoInterference)
            and a.from_group
            and frozenset((a.a, a.b)) in contacts
        )
    )


def _placed(p: PlacedPart) -> Part:
    return p.part.moved(p.location)


def _evaluate_part_assertion(
    assertion: NoInterference
    | Clearance
    | TangentContact
    | AllowedContact
    | ExpectedInterference
    | Distance,
    parts: dict[str, Part],
) -> AssertionResult:
    """Skip (``passed=None``) instead of evaluating when a referenced
    part is absent. Absence is a legitimate run state, not an input
    error: detail geometry (fasteners, motors) is applied by an
    override, and a standalone sub-assembly run evaluates the same
    assertion list without those parts."""
    missing = sorted(n for n in assertion.part_refs if n not in parts)
    if missing:
        names = ", ".join(missing)
        return AssertionResult(
            assertion.name, None, f"skipped: part(s) absent from this run: {names}"
        )
    return assertion.evaluate(parts)


def _evaluate_one(
    assertion: Assertion,
    assembly: Assembly,
    parts: dict[str, Part],
    angles: dict[str, float],
) -> AssertionResult:
    if isinstance(assertion, AnchorsCoincident):
        return assertion.evaluate_on(assembly)
    if isinstance(assertion, ScalarClaim):
        return assertion.evaluate()
    if isinstance(assertion, AllowedContact) and assertion.during is not None:
        # A joint absent from this run is the same legitimate state as an
        # absent part — a sub-assembly checked standalone below the level
        # that owns the joint. Skip rather than guess a phase.
        path = assertion.during.path
        if path not in angles:
            return AssertionResult(
                assertion.name,
                None,
                f"skipped: joint absent from this run: {path}",
            )
        assertion = assertion.for_angle(angles[path])
    return _evaluate_part_assertion(assertion, parts)


def evaluate(assembly: Assembly) -> tuple[AssertionResult, ...]:
    parts = {p.name: _placed(p) for p in assembly.placed_parts}
    angles = assembly.joint_angles
    return tuple(
        _evaluate_one(a, assembly, parts, angles)
        for a in assembly.all_assertions
    )
