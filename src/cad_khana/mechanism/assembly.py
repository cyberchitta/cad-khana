from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from build123d import (
    Axis,
    Color,
    Compound,
    Location,
    Part,
    Plane,
    Shape,
    ShapeList,
    Vector,
    VectorLike,
)

from cad_khana.mechanism.assertions import (
    AllowedContact,
    AnchorsCoincident,
    Assertion,
    Clearance,
    Distance,
    ExpectedInterference,
    JointWindow,
    NoInterference,
    ScalarClaim,
    TangentContact,
    drop_contact_shadowed,
)


def _normalize_pair_maps(
    known_overlaps: Iterable[tuple[str, str, str]],
    suppressed: Iterable[tuple[str, str]],
) -> tuple[dict[frozenset[str], str], set[frozenset[str]]]:
    """Order-independent lookup forms for the group-assertion options:
    ``known_overlaps`` triples ``(a, b, reason)`` → ``{frozenset: reason}``,
    ``suppressed`` pairs → ``{frozenset}``."""
    reasons = {frozenset((a, b)): reason for a, b, reason in known_overlaps}
    sup = {frozenset(p) for p in suppressed}
    return reasons, sup


def _pair_assertion(
    a: str, b: str, reasons: dict[frozenset[str], str]
) -> Assertion:
    """The assertion for one pair: ``ExpectedInterference`` when the pair
    is a documented known overlap, ``NoInterference`` otherwise. Names
    match the single-pair ``assert_*`` auto-names so group expansion is
    diff-identical to an equivalent hand-written loop."""
    key = frozenset((a, b))
    if key in reasons:
        return ExpectedInterference(
            a=a, b=b, name=f"interference:{a}/{b}", reason=reasons[key]
        )
    return NoInterference(
        a=a, b=b, name=f"no_interference:{a}/{b}", from_group=True
    )


_AXIS_DIRECTIONS: dict[str, tuple[float, float, float]] = {
    "X": (1, 0, 0),
    "Y": (0, 1, 0),
    "Z": (0, 0, 1),
    "-X": (-1, 0, 0),
    "-Y": (0, -1, 0),
    "-Z": (0, 0, -1),
}


def _direction(along: str | VectorLike) -> Vector:
    """Normalize an ``along=`` argument — an axis name (``"Z"``,
    ``"-X"``) or any VectorLike — to a unit ``Vector``."""
    if isinstance(along, str):
        key = along.upper().lstrip("+")
        if key not in _AXIS_DIRECTIONS:
            raise ValueError(
                f"along={along!r} — use one of {sorted(_AXIS_DIRECTIONS)} "
                f"or a direction vector"
            )
        return Vector(_AXIS_DIRECTIONS[key])
    return Vector(along).normalized()


def _plane_label(plane: Plane) -> str:
    n, o = plane.z_dir, plane.origin
    return f"plane(n=({n.X:.3g},{n.Y:.3g},{n.Z:.3g}),d={o.dot(n):.6g})"


def _distance_name(
    a: str,
    b: str | Plane,
    along: str | VectorLike | None,
    min_mm: float | None,
    max_mm: float | None,
) -> str:
    target = b if isinstance(b, str) else _plane_label(b)
    axis = (
        ""
        if along is None
        else f"@{along if isinstance(along, str) else Vector(along).to_tuple()}"
    )
    bounds = "".join(
        s
        for s, v in ((f">={min_mm}", min_mm), (f"<={max_mm}", max_mm))
        if v is not None
    )
    return f"distance:{a}/{target}{axis}{bounds}"


def _allowed_contact_name(
    a: str,
    b: str,
    min_mm3: float | None,
    max_mm3: float,
    during: JointWindow | None,
) -> str:
    bounds = "".join(
        s
        for s, v in ((f">={min_mm3}", min_mm3), (f"<={max_mm3}", max_mm3))
        if v is not None
    )
    # The phase is part of the claim's identity: one pair can carry a
    # different band in each phase, and the names must not collide.
    phase = "" if during is None else f"@{during.describe()}"
    return f"allowed_contact:{a}/{b}{bounds}{phase}"


@dataclass(frozen=True)
class PlacedPart:
    name: str
    part: Part
    location: Location
    color: Color | None = None
    material: str | None = None


@dataclass(frozen=True)
class Anchor:
    """A named datum ``Location`` in the owning assembly's local frame.

    Anchors are a unit's exported interface points (a deck top face, a
    mating column top, a delivery centroid): the unit declares where
    the interface is *in its own frame*, and a parent resolves the
    anchor through the tree (``Assembly.anchor``) — composed through
    sub-assembly placements and joints exactly like part locations —
    to derive placements or assert coincidence
    (``assert_anchors_coincident``). Anchors carry no geometry and are
    ignored by exports and interference checks; they live in their own
    namespace, separate from part / sub-assembly names.
    """

    name: str
    location: Location


@dataclass(frozen=True)
class RevoluteJoint:
    """Single-DOF revolute joint between a parent ``Assembly`` and a
    ``SubAssembly``. ``angle_deg`` is the animatable DOF (set per-frame
    by a factory).

    ``frame`` says which frame ``axis`` is expressed in:

    * ``"local"`` — the sub-assembly's own frame (build123d's
      joint-on-the-part convention; preferred). The composed transform
      is ``SubAssembly.location * RevoluteJoint.transform``: the sub
      rotates about its own axis, then gets placed. Identical
      sub-assemblies placed at different poses (e.g. stations around a
      hub) share one axis declaration — the placement rotates the axis
      with the sub.
    * ``"parent"`` (default, for compatibility) — the owning parent
      Assembly's frame. The composed transform is
      ``RevoluteJoint.transform * SubAssembly.location``: the placed
      sub is rotated about a fixed axis of the parent. Each differently
      posed instance needs its own hand-computed axis.

    The two are interchangeable: a local axis ``A`` behaves exactly as
    the parent-frame axis ``location * A``.
    """

    axis: Axis
    angle_deg: float = 0.0
    frame: str = "parent"

    def __post_init__(self):
        if self.frame not in ("parent", "local"):
            raise ValueError(
                f"RevoluteJoint frame must be 'parent' or 'local', "
                f"got {self.frame!r}"
            )

    def with_angle(self, angle_deg: float) -> "RevoluteJoint":
        return replace(self, angle_deg=angle_deg)

    @property
    def transform(self) -> Location:
        """Rotation by ``angle_deg`` about ``axis`` as a build123d
        ``Location`` — conjugated by ``axis.position`` so the rotation
        is about the axis line, not about the parallel line through
        the origin.

        Build123d's three-arg ``Location((x,y,z), (dx,dy,dz), a)``
        builds a rigid transform that rotates by ``a`` about the line
        ``(dx,dy,dz)`` *through the origin* and then translates by
        ``(x,y,z)`` — so passing ``axis.position`` there gives a
        screw-like motion, not a rotation about the axis. The correct
        rotation-about-an-arbitrary-axis is ``T(p) · R(d, a) · T(-p)``.
        Reduces to a plain rotation when ``axis.position`` is the
        origin, so callers using ``Axis.Z`` and friends are unaffected.
        """
        pos = self.axis.position
        d = self.axis.direction
        pivot = Location((pos.X, pos.Y, pos.Z))
        rotation = Location((0, 0, 0), (d.X, d.Y, d.Z), self.angle_deg)
        return pivot * rotation * pivot.inverse()


@dataclass(frozen=True)
class SubAssembly:
    """A nested ``Assembly`` placed in its parent's frame.

    ``location`` is the rigid placement of the sub-assembly's local
    frame origin in the parent frame. ``joint``, if present, layers an
    animatable DOF on top: the sub-assembly's effective transform
    becomes ``location * joint.transform`` for a ``frame="local"``
    joint, ``joint.transform * location`` for a ``frame="parent"`` one
    (see ``RevoluteJoint``). The sub-assembly's parts (and any
    further-nested sub-assemblies) compose underneath.
    """

    name: str
    assembly: "Assembly"
    location: Location = Location()
    joint: RevoluteJoint | None = None

    @property
    def effective_location(self) -> Location:
        if self.joint is None:
            return self.location
        if self.joint.frame == "local":
            return self.location * self.joint.transform
        return self.joint.transform * self.location


@dataclass(frozen=True)
class DetailOverride:
    """One entry in an ``Assembly.with_detailed_geometry`` mapping.

    A bare ``Part`` may be passed instead of a ``DetailOverride`` —
    treated as ``DetailOverride(part=p)`` (swap-only; no addition,
    since additions need a ``location``).
    """

    part: Part
    location: Location | None = None
    material: str | None = None
    color: Color | None = None


@dataclass(frozen=True)
class Assembly:
    parts: tuple[PlacedPart, ...] = ()
    subassemblies: tuple[SubAssembly, ...] = ()
    assertions: tuple[Assertion, ...] = ()
    anchors: tuple[Anchor, ...] = ()

    def _check_sibling_name(self, name: str) -> None:
        """Sibling names must be unique at each tree level — they are
        the segments of the qualified part paths that ``placed_parts``
        and the diagnostics report, so a duplicate would make two
        parts silently shadow each other in every ``{path: part}``
        consumer (assertions, diff, renders)."""
        if any(p.name == name for p in self.parts) or any(
            s.name == name for s in self.subassemblies
        ):
            raise ValueError(
                f"duplicate sibling name {name!r} — part and "
                f"sub-assembly names must be unique within one level "
                f"(they qualify into tree paths)"
            )

    def with_part(
        self,
        name: str,
        part: Part,
        location: Location | None = None,
        color: Color | None = None,
        material: str | None = None,
    ) -> "Assembly":
        if not isinstance(part, Shape):
            # Boundary check: builders can silently hand back a
            # `ShapeList` (a `+` of disjoint pieces, an extrusion on a
            # shifted plane), which only crashes much later inside
            # assertion evaluation with no part context.
            fix = (
                " — a boolean of disjoint pieces or an extrusion on a "
                "shifted plane can return a ShapeList; fuse into a "
                "single shape first (e.g. `Part() + pieces`)"
                if isinstance(part, ShapeList)
                else ""
            )
            raise TypeError(
                f"with_part({name!r}): expected a build123d Part, got "
                f"{type(part).__name__}{fix}"
            )
        self._check_sibling_name(name)
        placed = PlacedPart(name, part, location or Location(), color, material)
        return replace(self, parts=self.parts + (placed,))

    def with_subassembly(
        self,
        name: str,
        assembly: "Assembly",
        location: Location | None = None,
        joint: RevoluteJoint | None = None,
    ) -> "Assembly":
        if "." in name:
            raise ValueError(
                f"sub-assembly name {name!r} contains '.' — reserved "
                f"as the tree-path separator"
            )
        self._check_sibling_name(name)
        sub = SubAssembly(
            name=name,
            assembly=assembly,
            location=location or Location(),
            joint=joint,
        )
        return replace(self, subassemblies=self.subassemblies + (sub,))

    def with_anchor(self, name: str, location: Location) -> "Assembly":
        """Declare a named datum ``Location`` in this assembly's local
        frame (see ``Anchor``). Names cannot contain ``.`` (reserved as
        the tree-path separator) and must be unique among this level's
        anchors; they do not collide with part or sub-assembly names.
        """
        if "." in name:
            raise ValueError(
                f"anchor name {name!r} contains '.' — reserved as the "
                f"tree-path separator"
            )
        if any(a.name == name for a in self.anchors):
            raise ValueError(f"duplicate anchor name {name!r}")
        return replace(self, anchors=self.anchors + (Anchor(name, location),))

    def anchor(self, path: str) -> Location:
        """Resolve a dotted anchor ``path`` to a ``Location`` in this
        assembly's frame. Every segment but the last names a
        sub-assembly; the last names an anchor at that level
        (``"m05.deck_top"``; bare name for a root-level anchor). The
        result composes each sub-assembly's ``effective_location``
        (placement + joint) on the way up, so an anchor under a jointed
        subtree moves with the joint. Raises ``KeyError`` if any
        segment is missing."""
        head, _, rest = path.partition(".")
        if rest:
            for s in self.subassemblies:
                if s.name == head:
                    return s.effective_location * s.assembly.anchor(rest)
            raise KeyError(f"no sub-assembly named {head!r}")
        for a in self.anchors:
            if a.name == head:
                return a.location
        raise KeyError(f"no anchor named {head!r}")

    def with_joint(self, path: str, joint: RevoluteJoint) -> "Assembly":
        """Set the joint on the named sub-assembly. The joint's axis is
        interpreted in the owning parent Assembly's frame. ``path`` is
        either a single sub-assembly name or a dotted path
        (``"rotor.platform_dump"``) for nested sub-assemblies — the
        joint then attaches to the leaf at the end of the path, with
        each intermediate frame interpreting its own segment. Raises
        ``KeyError`` if any segment is missing."""
        head, _, rest = path.partition(".")
        updated, found = [], False
        for s in self.subassemblies:
            if s.name == head:
                if rest:
                    new_sub = replace(
                        s, assembly=s.assembly.with_joint(rest, joint)
                    )
                    updated.append(new_sub)
                else:
                    updated.append(replace(s, joint=joint))
                found = True
            else:
                updated.append(s)
        if not found:
            raise KeyError(f"no sub-assembly named {head!r}")
        return replace(self, subassemblies=tuple(updated))

    def with_joint_angle(self, path: str, angle_deg: float) -> "Assembly":
        """Animation hook — update the angle on the named sub-assembly's
        joint. ``path`` accepts the same dotted-path form as
        ``with_joint`` for reaching nested joints. Raises ``KeyError``
        if any segment is missing, ``ValueError`` if the leaf has no
        joint yet."""
        head, _, rest = path.partition(".")
        updated, found = [], False
        for s in self.subassemblies:
            if s.name == head:
                if rest:
                    new_sub = replace(
                        s,
                        assembly=s.assembly.with_joint_angle(rest, angle_deg),
                    )
                    updated.append(new_sub)
                else:
                    if s.joint is None:
                        raise ValueError(
                            f"sub-assembly {head!r} has no joint to update"
                        )
                    updated.append(
                        replace(s, joint=s.joint.with_angle(angle_deg))
                    )
                found = True
            else:
                updated.append(s)
        if not found:
            raise KeyError(f"no sub-assembly named {head!r}")
        return replace(self, subassemblies=tuple(updated))

    def with_materials(self, mapping: dict[str, str]) -> "Assembly":
        """Return a copy with each named part's material replaced by the
        value in ``mapping``. Keys are qualified tree paths — the same
        names ``placed_parts`` reports (``"turret.rotor.arm.spider"``;
        bare names for root-level parts). Parts not in the mapping are
        unchanged.

        Symmetric to ``chitra_cad.Scene.with_materials``: use this layer
        for cross-consumer experiments (render + FEA both read from the
        ``Assembly``); use the ``Scene`` layer for render-only sweeps.
        """
        return self._with_materials(mapping, "")

    def _with_materials(
        self, mapping: dict[str, str], prefix: str
    ) -> "Assembly":
        new_parts = tuple(
            replace(p, material=mapping.get(f"{prefix}{p.name}", p.material))
            for p in self.parts
        )
        new_subs = tuple(
            replace(
                s,
                assembly=s.assembly._with_materials(
                    mapping, f"{prefix}{s.name}."
                ),
            )
            for s in self.subassemblies
        )
        return replace(self, parts=new_parts, subassemblies=new_subs)

    def with_detailed_geometry(
        self, mapping: dict[str, "DetailOverride | Part"]
    ) -> "Assembly":
        """Return a copy with detailed geometry swapped or appended.

        Keys are qualified tree paths (the names ``placed_parts``
        reports). A key matching a part anywhere in the hierarchy gets
        its part replaced in-place (preserving placement / material /
        color unless the override supplies them). Keys with no match
        are additions: they land at the top level only, require an
        explicit ``location``, and their name becomes a root-level
        part name.

        A bare ``Part`` value is shorthand for ``DetailOverride(part=p)``.
        """
        overrides: dict[str, DetailOverride] = {
            name: (v if isinstance(v, DetailOverride) else DetailOverride(part=v))
            for name, v in mapping.items()
        }
        swapped = self._swap_detail(overrides, "")
        all_names = swapped._all_part_names()
        additions: list[PlacedPart] = []
        for name, ov in overrides.items():
            if name in all_names:
                continue
            if ov.location is None:
                raise ValueError(
                    f"with_detailed_geometry: addition {name!r} requires "
                    "an explicit location"
                )
            additions.append(
                PlacedPart(
                    name=name,
                    part=ov.part,
                    location=ov.location,
                    color=ov.color,
                    material=ov.material,
                )
            )
        return replace(swapped, parts=swapped.parts + tuple(additions))

    def _swap_detail(
        self, overrides: dict[str, "DetailOverride"], prefix: str
    ) -> "Assembly":
        new_parts = tuple(
            replace(
                p,
                part=overrides[f"{prefix}{p.name}"].part,
                location=overrides[f"{prefix}{p.name}"].location or p.location,
                material=overrides[f"{prefix}{p.name}"].material or p.material,
                color=overrides[f"{prefix}{p.name}"].color or p.color,
            )
            if f"{prefix}{p.name}" in overrides
            else p
            for p in self.parts
        )
        new_subs = tuple(
            replace(
                s,
                assembly=s.assembly._swap_detail(
                    overrides, f"{prefix}{s.name}."
                ),
            )
            for s in self.subassemblies
        )
        return replace(self, parts=new_parts, subassemblies=new_subs)

    def _all_part_names(self) -> set[str]:
        """Qualified tree paths of every part in the tree — the same
        names ``placed_parts`` reports."""
        names = {p.name for p in self.parts}
        for s in self.subassemblies:
            names.update(
                f"{s.name}.{n}" for n in s.assembly._all_part_names()
            )
        return names

    def assert_no_interference(
        self, a: str, b: str, name: str | None = None
    ) -> "Assembly":
        assertion = NoInterference(
            a=a, b=b, name=name or f"no_interference:{a}/{b}"
        )
        return replace(self, assertions=self.assertions + (assertion,))

    def assert_clearance(
        self,
        a: str,
        b: str,
        min_mm: float,
        name: str | None = None,
    ) -> "Assembly":
        assertion = Clearance(
            a=a,
            b=b,
            min_mm=min_mm,
            name=name or f"clearance:{a}/{b}>={min_mm}",
        )
        return replace(self, assertions=self.assertions + (assertion,))

    def assert_distance(
        self,
        a: str,
        b: str | Plane,
        *,
        min_mm: float | None = None,
        max_mm: float | None = None,
        along: str | VectorLike | None = None,
        grow_a_mm: float = 0.0,
        grow_b_mm: float = 0.0,
        name: str | None = None,
    ) -> "Assembly":
        """Assert a bounded distance from part ``a`` to ``b`` — another
        part, or a datum ``Plane`` declared in this assembly's frame.

        Without ``along``: minimum surface-to-surface distance. With
        ``along`` (an axis name like ``"-Z"`` or a vector, read as the
        direction from ``a`` toward ``b``): the directed gap between
        the two projection intervals — negative once they overlap
        along that axis. A ``Plane`` target with ``along`` requires
        the direction parallel to the plane normal.

        ``min_mm`` / ``max_mm`` bound the measurement (at least one
        required; both together express "close but not touching").
        ``grow_a_mm`` / ``grow_b_mm`` measure from an outward offset
        of that side (a tip circle over a modeled pitch cylinder). The
        measured value is recorded in the result even on pass, so
        ``khana diff`` sees drift.
        """
        if min_mm is None and max_mm is None:
            raise ValueError("assert_distance needs min_mm and/or max_mm")
        d = None if along is None else _direction(along)
        if (
            isinstance(b, Plane)
            and d is not None
            and abs(d.dot(b.z_dir)) < 1 - 1e-9
        ):
            raise ValueError(
                "assert_distance: along must be parallel to the plane "
                "normal — any other direction never closes on an "
                "infinite plane"
            )
        assertion = Distance(
            a=a,
            b=b,
            name=name or _distance_name(a, b, along, min_mm, max_mm),
            min_mm=min_mm,
            max_mm=max_mm,
            along=d,
            grow_a_mm=grow_a_mm,
            grow_b_mm=grow_b_mm,
        )
        return replace(self, assertions=self.assertions + (assertion,))

    def assert_scalar(
        self,
        name: str,
        value: float,
        *,
        ge: float | None = None,
        le: float | None = None,
        detail: str | None = None,
    ) -> "Assembly":
        """Record a named claim about a non-geometric scalar (a
        friction budget, a torque margin). The value lands in
        ``mechanism.json`` and diff either way; ``ge`` / ``le`` bounds
        make it pass/fail, with neither it is a pure recorder.
        ``detail`` is context carried into the result."""
        assertion = ScalarClaim(
            name=name, value=value, ge=ge, le=le, detail=detail
        )
        return replace(self, assertions=self.assertions + (assertion,))

    def assert_tangent_contact(
        self,
        a: str,
        b: str,
        *,
        tol_mm: float = 1e-3,
        name: str | None = None,
    ) -> "Assembly":
        """Assert ``a`` and ``b`` touch: surface gap ≤ ``tol_mm`` and
        no real overlap. The required-contact claim for tangent rests
        (foot-on-rail, plate-on-flange) — ``assert_no_interference``
        alone also passes with the parts floating apart; this fails on
        the gap. ``tol_mm`` absorbs placement/solver noise, not design
        gaps. The measured gap is recorded in the result even on pass,
        so ``khana diff`` sees drift."""
        assertion = TangentContact(
            a=a, b=b, tol_mm=tol_mm, name=name or f"tangent_contact:{a}/{b}"
        )
        return replace(self, assertions=self.assertions + (assertion,))

    def assert_allowed_contact(
        self,
        a: str,
        b: str,
        *,
        max_overlap_mm3: float,
        min_overlap_mm3: float | None = None,
        reason: str | None = None,
        during: JointWindow | None = None,
        name: str | None = None,
    ) -> "Assembly":
        """Assert any overlap between ``a`` and ``b`` stays within
        bounds — declare design-intended contact (a press-fit modeled
        at its true interference) instead of fudging the model to
        appease ``assert_no_interference``. A gap passes: contact is
        allowed, not required. ``min_overlap_mm3`` makes engagement
        itself the claim — the fit failing back to a clearance fit
        then fails loudly. The measured overlap volume is recorded in
        the result even on pass, so ``khana diff`` sees drift.
        ``reason`` documents the intent, appended to failure detail.

        ``during`` (a ``JointWindow``) confines the claim to a
        kinematic phase — the contact a lifter makes with the part it
        lifts, allowed while the lifter is raised and a real fault at
        rest. Outside the window the pair is held to plain
        no-interference, so the claim keeps its teeth at every other
        frame instead of going blind like a suppressed pair. Use
        ``khana``'s ``sweep``/``classify`` to derive the window from
        geometry rather than guessing it.

        Group ``assert_no_interference_*`` calls covering this pair
        skip it on the strength of this declaration — declaring the
        contact is the whole of it, with no matching ``suppressed=``
        entry to keep in step."""
        assertion = AllowedContact(
            a=a,
            b=b,
            max_overlap_mm3=max_overlap_mm3,
            min_overlap_mm3=min_overlap_mm3,
            reason=reason,
            during=during,
            name=name
            or _allowed_contact_name(
                a, b, min_overlap_mm3, max_overlap_mm3, during
            ),
        )
        return replace(self, assertions=self.assertions + (assertion,))

    def assert_interference(
        self,
        a: str,
        b: str,
        reason: str | None = None,
        name: str | None = None,
    ) -> "Assembly":
        """Assert that `a` and `b` DO interfere — a regression alarm
        for a known, accepted overlap. Fails if the overlap disappears
        (volume ≤ epsilon), which forces this assertion to be removed
        when the underlying design gap gets fixed. Prefer
        `assert_no_interference` by default; reach for this only when
        an overlap is documented and expected.
        """
        assertion = ExpectedInterference(
            a=a,
            b=b,
            name=name or f"interference:{a}/{b}",
            reason=reason,
        )
        return replace(self, assertions=self.assertions + (assertion,))

    def assert_anchors_coincident(
        self,
        a: str,
        b: str,
        tol_mm: float = 1e-6,
        name: str | None = None,
    ) -> "Assembly":
        """Assert the anchors at dotted paths ``a`` and ``b`` resolve to
        the same position (within ``tol_mm``; orientation is ignored).

        This is the cross-unit interface contract: each unit exports
        where it believes a shared datum is, in its own frame, and the
        composing parent asserts the beliefs coincide after placement —
        so a drifted mirror constant inside one unit fails loudly here
        instead of silently desyncing the machine. Both paths are
        resolved once at declaration time to fail fast on a typo'd
        path; evaluation re-resolves at ``check()`` time, so joint
        angles applied later are honored.
        """
        self.anchor(a)
        self.anchor(b)
        assertion = AnchorsCoincident(
            a=a,
            b=b,
            tol_mm=tol_mm,
            name=name or f"anchors_coincident:{a}/{b}",
        )
        return replace(self, assertions=self.assertions + (assertion,))

    def _subassembly_at(self, path: str) -> SubAssembly:
        """The ``SubAssembly`` at a dotted ``path`` (same form as
        ``with_joint`` / ``with_joint_angle``). Raises ``KeyError`` if
        any segment is missing."""
        head, _, rest = path.partition(".")
        for s in self.subassemblies:
            if s.name == head:
                return s.assembly._subassembly_at(rest) if rest else s
        raise KeyError(f"no sub-assembly named {head!r}")

    def _resolve_group(self, group: str | Iterable[str]) -> tuple[str, ...]:
        """A group selector → concrete part paths. A ``str`` is a dotted
        sub-assembly path and resolves to every part under that subtree,
        as qualified paths from *this* assembly's root (sorted, for
        deterministic expansion order); any other iterable is taken as
        explicit part paths in the given order."""
        if isinstance(group, str):
            sub = self._subassembly_at(group)
            return tuple(
                sorted(
                    f"{group}.{n}" for n in sub.assembly._all_part_names()
                )
            )
        return tuple(group)

    def assert_no_interference_between(
        self,
        group_a: str | Iterable[str],
        group_b: str | Iterable[str],
        *,
        known_overlaps: Iterable[tuple[str, str, str]] = (),
        suppressed: Iterable[tuple[str, str]] = (),
    ) -> "Assembly":
        """Assert no interference for every cross pair ``(a, b)`` with
        ``a`` from ``group_a`` and ``b`` from ``group_b``.

        Groups are explicit name iterables, or a dotted sub-assembly
        path selecting every part under that subtree. Expansion is a
        macro over the *current* group contents — parts added to a
        subtree afterwards are not covered.

        ``known_overlaps`` triples ``(a, b, reason)`` downgrade that
        pair (order-independent) to ``assert_interference(reason=…)`` —
        a regression alarm that self-fails when the overlap disappears.
        ``suppressed`` pairs (order-independent) are skipped entirely;
        a suppressed pair absent from the cross product is silently
        unused. Same-name pairs are skipped, and if the groups overlap
        each unordered pair is emitted once (first encounter's order).

        Pairs carrying an ``AllowedContact`` anywhere in the assembled
        tree are dropped too, without being listed: the contact
        assertion already holds the pair at every frame — inside its
        window to the overlap band, outside it to plain
        no-interference — so re-emitting ``NoInterference`` here could
        only contradict it. Restating them in ``suppressed`` was double
        bookkeeping that also went *wider* than the claim, since a
        suppression is blind at every frame where a phased claim is
        not. The drop happens over the assembled set
        (``all_assertions``), so it doesn't matter whether the contact
        is declared before or after this call, or above it. Name the
        pair in ``known_overlaps`` to override it — a known overlap
        emits ``ExpectedInterference``, which is never dropped.

        Emitted assertions are the plain single-pair forms with their
        usual auto-names, so replacing a hand-written double loop with
        this call leaves ``mechanism.json`` unchanged.
        """
        a_names = self._resolve_group(group_a)
        b_names = self._resolve_group(group_b)
        reasons, sup = _normalize_pair_maps(known_overlaps, suppressed)
        new: list[Assertion] = []
        seen: set[frozenset[str]] = set()
        for a in a_names:
            for b in b_names:
                if a == b:
                    continue
                key = frozenset((a, b))
                if key in sup or key in seen:
                    continue
                seen.add(key)
                new.append(_pair_assertion(a, b, reasons))
        return replace(self, assertions=self.assertions + tuple(new))

    def assert_no_interference_within(
        self,
        group: str | Iterable[str],
        *,
        known_overlaps: Iterable[tuple[str, str, str]] = (),
        suppressed: Iterable[tuple[str, str]] = (),
    ) -> "Assembly":
        """Assert no interference for every unordered pair within
        ``group`` (pair order follows the group's order: ``(names[i],
        names[j])`` for ``i < j``). Group selectors, ``known_overlaps``,
        ``suppressed``, the ``AllowedContact`` skip, and name-stability
        semantics are exactly as in ``assert_no_interference_between``.
        """
        names = self._resolve_group(group)
        reasons, sup = _normalize_pair_maps(known_overlaps, suppressed)
        new: list[Assertion] = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                if a == b or frozenset((a, b)) in sup:
                    continue
                new.append(_pair_assertion(a, b, reasons))
        return replace(self, assertions=self.assertions + tuple(new))

    @property
    def all_assertions(self) -> tuple[Assertion, ...]:
        """This level's assertions plus every sub-assembly's,
        recursively, qualified into this frame — the assertion-side
        mirror of ``placed_parts``. Part and anchor paths (and names)
        gain the sub-assembly path prefix; datum-plane targets are
        moved by each level's ``effective_location`` (joint included),
        so a plane declared in a sub's local frame tracks its
        placement. This is what lets a unit declare an assertion once,
        at the level that owns the knowledge: standalone runs evaluate
        it directly, composed runs evaluate the qualified form, and
        the absent-part skip covers detail-only references either way.

        This is also where a group expansion's blanket pairs yield to a
        declared ``AllowedContact`` on the same pair
        (``drop_contact_shadowed``) — over the assembled set, so the
        exclusion is free of declaration order.
        """
        nested = tuple(
            a.qualified(s.name, s.effective_location)
            for s in self.subassemblies
            for a in s.assembly.all_assertions
        )
        return drop_contact_shadowed(self.assertions + nested)

    @property
    def joint_angles(self) -> dict[str, float]:
        """Dotted sub-assembly path → joint angle in degrees, for every
        jointed sub-assembly in the tree — the kinematic-state mirror of
        ``placed_parts``, and what resolves an assertion's
        ``JointWindow`` phase. Unjointed sub-assemblies contribute
        nothing but are still walked through.
        """
        own = {
            s.name: s.joint.angle_deg
            for s in self.subassemblies
            if s.joint is not None
        }
        nested = {
            f"{s.name}.{k}": v
            for s in self.subassemblies
            for k, v in s.assembly.joint_angles.items()
        }
        return own | nested

    @property
    def placed_parts(self) -> tuple[PlacedPart, ...]:
        """Flat walk over the assembly tree. Each yielded ``PlacedPart``
        carries the original part with its ``name`` qualified into the
        dotted tree path (``"turret.rotor.arm.spider"``; root-level
        parts keep their bare name) and ``location`` composed through
        the parent chain so it reflects the world-frame placement
        regardless of nesting depth. The path is the part's identity:
        assertions, diagnostics, diff, exports, and the override layers
        (``with_materials`` / ``with_detailed_geometry``) all key on it.

        Use this when a consumer needs the leaf view (interference checks,
        diagnostics, path-keyed lookups across the whole assembly). The
        underlying tree (``parts`` / ``subassemblies``) stays the source
        of truth for animation channels and hierarchy emission; inside
        the tree, ``PlacedPart.name`` is the local segment only.
        """
        out: list[PlacedPart] = list(self.parts)
        for sub in self.subassemblies:
            eff = sub.effective_location
            for inner in sub.assembly.placed_parts:
                out.append(
                    replace(
                        inner,
                        name=f"{sub.name}.{inner.name}",
                        location=eff * inner.location,
                    )
                )
        return tuple(out)

    @property
    def compound(self) -> Compound:
        children = [p.part.moved(p.location) for p in self.parts]
        for sub in self.subassemblies:
            children.append(sub.assembly.compound.moved(sub.effective_location))
        return Compound(children=children)
