"""Held evaluation — every assertion over every declared motion.

``evaluate`` answers "does this claim hold at the pose the assembly was
built in". ``hold`` answers it at that pose *and* at each sample of each
declared ``Motion``, and rolls the poses up into one result per
assertion: failed if any pose failed, the worst pose's value and detail,
and counts that say how much was looked at.

**Sampled.** A motion is its samples; a claim that holds at every one
can still fail between two of them. The roll-up says how many poses it
covers and ``MotionSummary.max_step`` says how far apart they were —
it does not pretend to a bound.

What makes it affordable is that an assertion's result depends only on
where its own parts are, relative to each other, and on the phase it is
in. Poses that agree on both share one evaluation, and at each pose only
the assertions touching a part that moved (or a joint that turned) are
looked at again. That reuse is exact, not a heuristic: it keys on the
composed placements themselves. A datum-plane target or an ``along``
direction is absolute, so those key on absolute placement.

Pure: no file I/O. ``check()`` writes what this returns.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cached_property

from build123d import Location, Part, Plane

from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.assertions import (
    ABSENT_JOINT,
    IN,
    AllowedContact,
    AnchorsCoincident,
    Assertion,
    Contacts,
    Distance,
    Phased,
    ScalarClaim,
    TangentContact,
    contact_claims,
    core,
    evaluate_one,
    phase,
    resolved,
)
from cad_khana.mechanism.diagnostics import (
    AssertionResult,
    JointRange,
    MotionSummary,
    PoseCounts,
    WorstAt,
)
from cad_khana.mechanism.motion import Motion, Pose

Key = tuple[object, ...]
ABSENCES = ("absent_part", ABSENT_JOINT)
PLACEMENT_DECIMALS = 9


@dataclass(frozen=True)
class Held:
    assertions: tuple[AssertionResult, ...]
    motions: tuple[MotionSummary, ...]
    warnings: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class _Sample:
    """One pose looked at. ``motion`` is ``None`` for the as-built
    pose."""

    order: int
    motion: str | None
    t: float | None
    pose: Pose


@dataclass(frozen=True)
class _Visit:
    sample: _Sample
    key: Key
    state: str
    result: AssertionResult
    slack: float | None


def _signature(location: Location) -> tuple[float, ...]:
    """A placement as a comparable value: its transformation matrix,
    rounded well below any geometric tolerance and well above the noise
    of composing the same placements in a different order. Matrix
    entries rather than Euler angles, which jump at the wrap."""
    trsf = location.wrapped.Transformation()
    return tuple(
        round(trsf.Value(row, col), PLACEMENT_DECIMALS)
        for row in (1, 2, 3)
        for col in (1, 2, 3, 4)
    )


@dataclass(frozen=True)
class _Frame:
    """The assembly at one sample, with what evaluation needs derived
    once and only on demand."""

    sample: _Sample
    assembly: Assembly
    assertions: tuple[Assertion, ...]

    @cached_property
    def locations(self) -> dict[str, Location]:
        return {p.name: p.location for p in self.assembly.placed_parts}

    @cached_property
    def signatures(self) -> dict[str, tuple[float, ...]]:
        return {n: _signature(loc) for n, loc in self.locations.items()}

    @cached_property
    def parts(self) -> dict[str, Part]:
        return {
            p.name: p.part.moved(p.location)
            for p in self.assembly.placed_parts
        }

    @cached_property
    def values(self) -> dict[str, float]:
        return self.assembly.joint_angles


def _is_absolute(claim: Assertion) -> bool:
    return isinstance(claim, Distance) and (
        claim.along is not None or isinstance(claim.b, Plane)
    )


def _geometry(assertion: Assertion, frame: _Frame) -> Key:
    """What the claim's measurement depends on at this pose."""
    claim = core(assertion)
    if isinstance(claim, ScalarClaim):
        return ()
    if isinstance(claim, AnchorsCoincident):
        a, b = frame.assembly.anchor(claim.a), frame.assembly.anchor(claim.b)
        return _signature(a.inverse() * b)
    locations = frame.locations
    if any(n not in locations for n in claim.part_refs):
        return ("absent",)
    if _is_absolute(claim):
        target = (
            _signature(claim.b.location)
            if isinstance(claim.b, Plane)
            else frame.signatures[claim.b]
        )
        return frame.signatures[claim.a] + target
    return _signature(locations[claim.a].inverse() * locations[claim.b])


def _slack(assertion: Assertion, state: str, result: AssertionResult) -> float | None:
    claim = resolved(assertion, state)
    return (
        claim.slack(result.value)
        if result.value is not None
        and isinstance(claim, Distance | TangentContact | AllowedContact)
        else None
    )


@dataclass(frozen=True)
class _Index:
    """Which assertions a pose can change: by part moved, by joint
    turned, and the few that must be looked at every time (a datum
    plane or an anchor moves with a subtree, not with a named part)."""

    by_part: dict[str, frozenset[int]]
    by_joint: dict[str, frozenset[int]]
    always: frozenset[int]

    @staticmethod
    def create(assertions: tuple[Assertion, ...], contacts: Contacts) -> "_Index":
        by_part: dict[str, set[int]] = {}
        by_joint: dict[str, set[int]] = {}
        always: set[int] = set()
        for i, a in enumerate(assertions):
            claim = core(a)
            if isinstance(claim, AnchorsCoincident) or (
                isinstance(claim, Distance) and isinstance(claim.b, Plane)
            ):
                always.add(i)
            for name in getattr(claim, "part_refs", ()):
                by_part.setdefault(name, set()).add(i)
            for path in _phase_joints(a, contacts):
                by_joint.setdefault(path, set()).add(i)
        return _Index(
            {k: frozenset(v) for k, v in by_part.items()},
            {k: frozenset(v) for k, v in by_joint.items()},
            frozenset(always),
        )

    def affected(self, rest: _Frame, frame: _Frame) -> tuple[int, ...]:
        moved = (
            n
            for n, sig in frame.signatures.items()
            if rest.signatures[n] != sig
        )
        turned = (j for j, v in frame.values.items() if rest.values[j] != v)
        return tuple(
            sorted(
                self.always.union(
                    *(self.by_part.get(n, frozenset()) for n in moved),
                    *(self.by_joint.get(j, frozenset()) for j in turned),
                )
            )
        )


def _phase_joints(assertion: Assertion, contacts: Contacts) -> set[str]:
    """Every joint the claim's phase can turn on — its own windows, and
    for a contact claim those of every sibling on the pair, since a
    sibling coming into phase is what governs it."""
    if not isinstance(assertion, Phased):
        return set()
    claims = (
        contacts[frozenset(assertion.part_refs)]
        if isinstance(assertion.inner, AllowedContact)
        else (assertion,)
    )
    return {
        w.path for c in claims if isinstance(c, Phased) for w in c.during
    }


def _rank(visit: _Visit) -> tuple[int, float, int]:
    """Worst first: a failing pose, then a passing one, then a lapsed
    one; within those the least slack to the claim's own bound; then
    the first looked at."""
    passed = visit.result.passed
    return (
        0 if passed is False else 1 if passed else 2,
        visit.slack if visit.slack is not None else float("inf"),
        visit.sample.order,
    )


def _where(sample: _Sample) -> str:
    return (
        "the as-built pose"
        if sample.motion is None
        else f"{sample.motion} t={sample.t:g}"
    )


def _rolled(rest: _Visit, later: tuple[_Visit, ...], total: int) -> AssertionResult:
    """One result from every pose. ``later`` holds only the poses that
    could differ from the as-built one; the rest of ``total`` share its
    verdict."""
    if rest.result.skipped in ABSENCES:
        return replace(rest.result, poses=PoseCounts(0, 0, 0, 0))
    weighted = ((rest, total - len(later)),) + tuple((v, 1) for v in later)
    visits = (rest,) + later
    failed = sum(n for v, n in weighted if v.result.passed is False)
    counts = PoseCounts(
        evaluated=total,
        distinct=len({v.key for v in visits if v.result.skipped is None}),
        in_phase=sum(n for v, n in weighted if v.state == IN),
        failed=failed,
    )
    worst = min(visits, key=_rank)
    sample = worst.sample
    # Without a measured slack the failing poses can't be ranked, so
    # the one reported is the first — the onset, not the deepest.
    ordinal = "first" if worst.slack is None else "worst"
    detail = (
        f"{worst.result.detail} — failed at {failed} of {total} poses; "
        f"{ordinal} at {_where(sample)}"
        if failed and total > 1
        else worst.result.detail
    )
    return replace(
        worst.result,
        detail=detail,
        poses=counts,
        worst_at=(
            None
            if sample.motion is None
            else WorstAt(sample.motion, sample.t, dict(sample.pose))
        ),
    )


def _summary(motion: Motion, poses: tuple[Pose, ...], rest: Pose) -> MotionSummary:
    """A joint the schedule leaves out at some sample sits at its
    as-built value there."""
    series = {
        path: tuple(p.get(path, rest[path]) for p in poses)
        for path in dict.fromkeys(k for p in poses for k in p)
    }
    return MotionSummary(
        name=motion.name,
        samples=len(poses),
        joints_deg={
            path: JointRange(
                min=min(vs),
                max=max(vs),
                max_step=max(
                    (abs(b - a) for a, b in zip(vs, vs[1:])), default=0.0
                ),
            )
            for path, vs in series.items()
        },
    )


def _warnings(
    assertions: tuple[Assertion, ...],
    results: tuple[AssertionResult, ...],
    summaries: tuple[MotionSummary, ...],
    rest: Pose,
) -> tuple[dict[str, str], ...]:
    driven = {path for s in summaries for path in s.joints_deg}
    return (
        tuple(
            {"kind": "joint_never_driven", "joint": j}
            for j in rest
            if j not in driven
        )
        + tuple(
            {"kind": "never_in_phase", "assertion": r.name}
            for a, r in zip(assertions, results)
            if isinstance(a, Phased)
            and r.skipped not in ABSENCES
            and r.poses.in_phase == 0
        )
        + (({"kind": "interferences_rest_pose_only"},) if summaries else ())
    )


def hold(assembly: Assembly) -> Held:
    motions = assembly.all_motions
    schedules = tuple((m, m.poses) for m in motions)
    samples = (_Sample(0, None, None, {}),) + tuple(
        _Sample(order, m.name, t, pose)
        for order, (m, t, pose) in enumerate(
            (
                (m, t, pose)
                for m, poses in schedules
                for t, pose in zip(m.ts, poses)
            ),
            start=1,
        )
    )
    rest = _Frame(samples[0], assembly, assembly.all_assertions)
    assertions = rest.assertions
    contacts = contact_claims(assertions)
    index = _Index.create(assertions, contacts)
    # A datum plane is qualified through the joints above it, so a tree
    # that declares one re-derives its assertions per pose; otherwise
    # the list is the same at every pose.
    replanes = any(
        isinstance(core(a), Distance) and isinstance(core(a).b, Plane)
        for a in assertions
    )
    evaluated: dict[tuple[int, Key], tuple[AssertionResult, float | None]] = {}

    def visit(i: int, frame: _Frame) -> _Visit:
        assertion = frame.assertions[i]
        state = phase(assertion, frame.values, contacts)
        key = (state, _geometry(assertion, frame))
        if (i, key) not in evaluated:
            result = evaluate_one(
                assertion, frame.assembly, frame.parts, frame.values, contacts
            )
            evaluated[i, key] = (result, _slack(assertion, state, result))
        return _Visit(frame.sample, key, state, *evaluated[i, key])

    at_rest = tuple(visit(i, rest) for i in range(len(assertions)))
    later: dict[int, list[_Visit]] = {}
    for sample in samples[1:]:
        posed = assembly.posed(sample.pose)
        frame = _Frame(
            sample, posed, posed.all_assertions if replanes else assertions
        )
        for i in index.affected(rest, frame):
            later.setdefault(i, []).append(visit(i, frame))

    results = tuple(
        _rolled(v, tuple(later.get(i, ())), len(samples))
        for i, v in enumerate(at_rest)
    )
    summaries = tuple(_summary(m, poses, rest.values) for m, poses in schedules)
    return Held(
        assertions=results,
        motions=summaries,
        warnings=_warnings(assertions, results, summaries, rest.values),
    )
