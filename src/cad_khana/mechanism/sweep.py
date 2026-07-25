"""Sampled-motion diagnostics — what a part pair does *over* a motion,
not at one pose.

The primitive is a factory ``t -> Assembly``, not a joint plus an angle
range, because that is the shape motion actually takes in consumer
code: a dump cycle drives several joints at once from non-linear
schedules, which no single joint range can express. A single-joint
sweep is the degenerate case (``over_joint``).

Everything here is **sampled**, and sampling a motion is an inner
approximation: a pair reported ``never`` overlapped at none of the
sampled parameters, which is not the same as never. Nothing in this
module launders that distinction — ``classify`` reports what the
samples show and the field names say ``at_contact`` / the docstrings
say "sampled". A durable claim belongs in an assertion
(``assert_allowed_contact(..., during=...)``), which re-derives from
geometry on every run; these functions are for deriving the claim in
the first place.

Pure: no file I/O, no global state. Callers write the JSON.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import combinations

from build123d import BoundBox, Part

from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.diagnostics import (
    INTERFERENCE_VOLUME_EPSILON_MM3,
    intersection_volume,
)

Factory = Callable[[float], Assembly]
Pair = tuple[str, str]

ALWAYS = "always"
NEVER = "never"
TRANSIENT = "transient"


@dataclass(frozen=True)
class PairSamples:
    """One part pair's overlap volume at each sampled parameter,
    positionally aligned with ``SweepResult.ts``."""

    a: str
    b: str
    volumes_mm3: tuple[float, ...]

    @property
    def in_contact(self) -> tuple[bool, ...]:
        return tuple(
            v > INTERFERENCE_VOLUME_EPSILON_MM3 for v in self.volumes_mm3
        )


@dataclass(frozen=True)
class SweepResult:
    """Raw samples: the parameters swept, each frame's joint angles, and
    per-pair overlap volumes. Derived views (``classify``) are separate
    so the samples stay inspectable."""

    ts: tuple[float, ...]
    angles: tuple[dict[str, float], ...]
    pairs: tuple[PairSamples, ...]


@dataclass(frozen=True)
class PairPhase:
    """How a pair behaves across the sweep.

    ``kind`` is ``always`` / ``never`` / ``transient`` **at the sampled
    parameters**. ``t_intervals`` holds each maximal run of contacting
    samples separately rather than one first→last span: a contact that
    starts, releases and returns is two phases, and a single span would
    silently claim the clear stretch between them as contact.

    The angle maps are the same information in joint-angle space, which
    is where a ``JointWindow`` is written — and often simpler there,
    since a contact that recurs at several parameters usually recurs at
    the *same* angles. ``angles_at_contact`` is the inner bound (the
    angles actually observed in contact); ``angles_bracketing`` extends
    each run to the neighbouring clear samples, and is the outer bound
    the true phase lies within. Declare from the bracketing span: too
    wide only weakens the claim, while too narrow fails runs that were
    always fine.
    """

    a: str
    b: str
    kind: str
    t_intervals: tuple[tuple[float, float], ...]
    max_volume_mm3: float
    t_at_max: float | None
    angles_at_contact: dict[str, tuple[float, float]]
    angles_bracketing: dict[str, tuple[float, float]]


@dataclass(frozen=True)
class Onset:
    """Where a pair first comes into contact along the swept range.

    ``t`` is bisected to ``tol`` inside ``bracket``, the first
    clear→contact interval found among the samples. ``brackets`` counts
    every such interval: more than one means the predicate is not
    monotonic over the range, so ``t`` is the *first* onset, not the
    only one. ``bracket`` is ``None`` when the pair was already in
    contact at the first sample — the onset is then at or before the
    range start and this sweep cannot see it.
    """

    a: str
    b: str
    t: float | None
    bracket: tuple[float, float] | None
    brackets: int
    evaluations: int


def _bboxes_overlap(a: BoundBox, b: BoundBox) -> bool:
    return (
        a.min.X <= b.max.X
        and b.min.X <= a.max.X
        and a.min.Y <= b.max.Y
        and b.min.Y <= a.max.Y
        and a.min.Z <= b.max.Z
        and b.min.Z <= a.max.Z
    )


def _shapes(assembly: Assembly) -> dict[str, Part]:
    return {p.name: p.part.moved(p.location) for p in assembly.placed_parts}


def _bbox_candidates(shapes: dict[str, Part]) -> tuple[Pair, ...]:
    """Every pair whose bounding boxes overlap. The prefilter is exact
    in the direction that matters — disjoint boxes cannot intersect —
    so skipping the boolean for the rest costs no coverage, only the
    O(n^2) booleans that dominate a discovery sweep."""
    boxes = {n: s.bounding_box() for n, s in shapes.items()}
    return tuple(
        pair
        for pair in combinations(sorted(shapes), 2)
        if _bboxes_overlap(boxes[pair[0]], boxes[pair[1]])
    )


def _key(pair: Pair) -> Pair:
    a, b = pair
    return (a, b) if a <= b else (b, a)


def _frame_volumes(
    assembly: Assembly, pairs: Iterable[Pair] | None
) -> dict[Pair, float]:
    shapes = _shapes(assembly)
    candidates = _bbox_candidates(shapes) if pairs is None else tuple(pairs)
    return {
        _key(pair): intersection_volume(shapes[pair[0]], shapes[pair[1]])
        for pair in candidates
    }


def sweep(
    factory: Factory,
    ts: Iterable[float],
    pairs: Iterable[Pair] | None = None,
) -> SweepResult:
    """Sample ``factory`` at each ``t`` and measure pairwise overlap.

    With ``pairs``, only those pairs are measured — a named part
    missing from the assembly raises ``KeyError`` on its path. Without,
    every pair in the tree is a candidate, bbox-prefiltered per frame;
    a pair whose boxes are disjoint in some frame records ``0.0``
    there, which is a measurement rather than a default.
    """
    ts = tuple(ts)
    frames = tuple(factory(t) for t in ts)
    volumes = tuple(_frame_volumes(a, pairs) for a in frames)
    keys = sorted({k for v in volumes for k in v})
    return SweepResult(
        ts=ts,
        angles=tuple(a.joint_angles for a in frames),
        pairs=tuple(
            PairSamples(a, b, tuple(v.get((a, b), 0.0) for v in volumes))
            for a, b in keys
        ),
    )


def over_joint(
    assembly: Assembly, path: str, range_deg: tuple[float, float]
) -> Factory:
    """A factory driving one joint across ``range_deg`` as ``t`` runs
    0→1 — the single-DOF case of a motion, expressed in the same shape
    as a hand-written multi-joint factory."""
    lo, hi = range_deg
    return lambda t: assembly.with_joint_angle(path, lo + (hi - lo) * t)


def _runs(contact: tuple[bool, ...]) -> tuple[tuple[int, int], ...]:
    """Index of the first and last sample of each maximal run of
    contacting samples."""
    last = len(contact) - 1
    starts = (
        i for i, over in enumerate(contact) if over and (i == 0 or not contact[i - 1])
    )
    ends = (
        i
        for i, over in enumerate(contact)
        if over and (i == last or not contact[i + 1])
    )
    return tuple(zip(starts, ends))


def _angle_span(
    angles: tuple[dict[str, float], ...], indices: Iterable[int]
) -> dict[str, tuple[float, float]]:
    frames = [angles[i] for i in indices]
    if not frames:
        return {}
    return {
        path: (min(f[path] for f in frames), max(f[path] for f in frames))
        for path in sorted(frames[0])
    }


def _bracketing(
    runs: tuple[tuple[int, int], ...], n: int
) -> tuple[int, ...]:
    """Every contacting sample index, each run widened by the clear
    sample on either side — the outer bound on where contact really
    starts and ends."""
    return tuple(
        sorted(
            {
                i
                for lo, hi in runs
                for i in range(max(lo - 1, 0), min(hi + 1, n - 1) + 1)
            }
        )
    )


def _phase(result: SweepResult, samples: PairSamples) -> PairPhase:
    contact = samples.in_contact
    runs = _runs(contact)
    hits = tuple(i for i, over in enumerate(contact) if over)
    kind = (
        NEVER
        if not hits
        else ALWAYS
        if len(hits) == len(result.ts)
        else TRANSIENT
    )
    peak, t_at_peak = max(zip(samples.volumes_mm3, result.ts))
    return PairPhase(
        a=samples.a,
        b=samples.b,
        kind=kind,
        t_intervals=tuple(
            (result.ts[lo], result.ts[hi]) for lo, hi in runs
        ),
        max_volume_mm3=peak,
        t_at_max=t_at_peak if hits else None,
        angles_at_contact=_angle_span(result.angles, hits),
        angles_bracketing=_angle_span(
            result.angles, _bracketing(runs, len(result.ts))
        ),
    )


def classify(result: SweepResult) -> tuple[PairPhase, ...]:
    """Each swept pair as ``always`` / ``never`` / ``transient`` contact,
    with the joint-angle span it was in contact over. This is what
    replaces a hand-curated suppression list: the *list* becomes a
    property of the geometry, while the kinematic reason each pair is
    there stays human-written — it is a design statement, not something
    a sweep can derive."""
    return tuple(_phase(result, p) for p in result.pairs)


def _in_contact(assembly: Assembly, pair: Pair) -> bool:
    volume = next(iter(_frame_volumes(assembly, (pair,)).values()))
    return volume > INTERFERENCE_VOLUME_EPSILON_MM3


def onset(
    factory: Factory,
    pair: Pair,
    over: Iterable[float],
    *,
    tol: float = 1e-3,
) -> Onset:
    """The first parameter at which ``pair`` comes into contact.

    Scans ``over`` for the first clear→contact interval, then bisects
    inside it to ``tol``. Bisection alone would assume the predicate is
    monotonic; bracketing first does not, and ``Onset.brackets``
    reports how many transitions the samples actually showed, so a
    second contact phase is visible rather than silently discarded.
    """
    ts = tuple(over)
    a, b = pair
    samples = sweep(factory, ts, pairs=(pair,)).pairs[0]
    contact = samples.in_contact
    brackets = tuple(
        (ts[i], ts[i + 1])
        for i in range(len(ts) - 1)
        if not contact[i] and contact[i + 1]
    )
    if contact and contact[0]:
        return Onset(a, b, ts[0], None, len(brackets), len(ts))
    if not brackets:
        return Onset(a, b, None, None, 0, len(ts))
    lo, hi = brackets[0]
    evaluations = len(ts)
    while hi - lo > tol:
        mid = (lo + hi) / 2
        evaluations += 1
        if _in_contact(factory(mid), pair):
            hi = mid
        else:
            lo = mid
    return Onset(a, b, hi, (lo, hi), len(brackets), evaluations)
