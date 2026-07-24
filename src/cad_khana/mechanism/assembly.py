from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from build123d import Axis, Color, Compound, Location, Part

from cad_khana.mechanism.assertions import (
    Assertion,
    Clearance,
    ExpectedInterference,
    NoInterference,
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
    return NoInterference(a=a, b=b, name=f"no_interference:{a}/{b}")


@dataclass(frozen=True)
class PlacedPart:
    name: str
    part: Part
    location: Location
    color: Color | None = None
    material: str | None = None


@dataclass(frozen=True)
class RevoluteJoint:
    """Single-DOF revolute joint between a parent ``Assembly`` and a
    ``SubAssembly``. ``axis`` is interpreted in the parent's frame;
    ``angle_deg`` is the animatable DOF (set per-frame by a factory).

    The composed transform applied to the sub-assembly's local frame is
    ``RevoluteJoint.transform * SubAssembly.location`` — the joint
    rotates the placed sub-assembly about ``axis`` in the parent frame.
    """

    axis: Axis
    angle_deg: float = 0.0

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
    becomes ``joint.transform * location``. The sub-assembly's parts
    (and any further-nested sub-assemblies) compose underneath.
    """

    name: str
    assembly: "Assembly"
    location: Location = Location()
    joint: RevoluteJoint | None = None

    @property
    def effective_location(self) -> Location:
        if self.joint is None:
            return self.location
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

    def with_part(
        self,
        name: str,
        part: Part,
        location: Location | None = None,
        color: Color | None = None,
        material: str | None = None,
    ) -> "Assembly":
        placed = PlacedPart(name, part, location or Location(), color, material)
        return replace(self, parts=self.parts + (placed,))

    def with_subassembly(
        self,
        name: str,
        assembly: "Assembly",
        location: Location | None = None,
        joint: RevoluteJoint | None = None,
    ) -> "Assembly":
        sub = SubAssembly(
            name=name,
            assembly=assembly,
            location=location or Location(),
            joint=joint,
        )
        return replace(self, subassemblies=self.subassemblies + (sub,))

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
        value in ``mapping``. Recurses into sub-assemblies. Parts not in
        the mapping are unchanged.

        Symmetric to ``chitra_cad.Scene.with_materials``: use this layer
        for cross-consumer experiments (render + FEA both read from the
        ``Assembly``); use the ``Scene`` layer for render-only sweeps.
        """
        new_parts = tuple(
            replace(p, material=mapping.get(p.name, p.material)) for p in self.parts
        )
        new_subs = tuple(
            replace(s, assembly=s.assembly.with_materials(mapping))
            for s in self.subassemblies
        )
        return replace(self, parts=new_parts, subassemblies=new_subs)

    def with_detailed_geometry(
        self, mapping: dict[str, "DetailOverride | Part"]
    ) -> "Assembly":
        """Return a copy with detailed geometry swapped or appended.

        Swaps recurse — a matching name anywhere in the hierarchy gets
        its part replaced in-place (preserving placement / material /
        color unless the override supplies them). Additions land at the
        top level only, and require an explicit ``location``.

        A bare ``Part`` value is shorthand for ``DetailOverride(part=p)``.
        """
        overrides: dict[str, DetailOverride] = {
            name: (v if isinstance(v, DetailOverride) else DetailOverride(part=v))
            for name, v in mapping.items()
        }
        swapped = self._swap_detail(overrides)
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

    def _swap_detail(self, overrides: dict[str, "DetailOverride"]) -> "Assembly":
        new_parts = tuple(
            replace(
                p,
                part=overrides[p.name].part,
                location=overrides[p.name].location or p.location,
                material=overrides[p.name].material or p.material,
                color=overrides[p.name].color or p.color,
            )
            if p.name in overrides
            else p
            for p in self.parts
        )
        new_subs = tuple(
            replace(s, assembly=s.assembly._swap_detail(overrides))
            for s in self.subassemblies
        )
        return replace(self, parts=new_parts, subassemblies=new_subs)

    def _all_part_names(self) -> set[str]:
        names = {p.name for p in self.parts}
        for s in self.subassemblies:
            names.update(s.assembly._all_part_names())
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
        """A group selector → concrete part names. A ``str`` is a dotted
        sub-assembly path and resolves to every part name under that
        subtree (sorted, for deterministic expansion order); any other
        iterable is taken as explicit part names in the given order."""
        if isinstance(group, str):
            sub = self._subassembly_at(group)
            return tuple(sorted(sub.assembly._all_part_names()))
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
        ``suppressed``, and name-stability semantics are exactly as in
        ``assert_no_interference_between``.
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
    def placed_parts(self) -> tuple[PlacedPart, ...]:
        """Flat walk over the assembly tree. Each yielded ``PlacedPart``
        carries the original part + name, with ``location`` composed
        through the parent chain so it reflects the world-frame placement
        regardless of nesting depth.

        Use this when a consumer needs the leaf view (interference checks,
        diagnostics, name-keyed lookups across the whole assembly). The
        underlying tree (``parts`` / ``subassemblies``) stays the source
        of truth for animation channels and hierarchy emission.
        """
        out: list[PlacedPart] = list(self.parts)
        for sub in self.subassemblies:
            eff = sub.effective_location
            for inner in sub.assembly.placed_parts:
                out.append(replace(inner, location=eff * inner.location))
        return tuple(out)

    @property
    def compound(self) -> Compound:
        children = [p.part.moved(p.location) for p in self.parts]
        for sub in self.subassemblies:
            children.append(sub.assembly.compound.moved(sub.effective_location))
        return Compound(children=children)
