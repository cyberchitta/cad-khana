from build123d import Axis, Box, BuildPart, Location

from cad_khana.mechanism.assembly import Assembly, RevoluteJoint
from cad_khana.mechanism.sweep import (
    ALWAYS,
    NEVER,
    TRANSIENT,
    classify,
    onset,
    over_joint,
    sweep,
)


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def _slider(offset: float) -> Assembly:
    """``offset`` mm apart along X — cubes of size 10 overlap below 10."""
    return (
        Assembly()
        .with_part("a", _cube())
        .with_part("b", _cube(), location=Location((offset, 0, 0)))
    )


def _approaching(t: float) -> Assembly:
    """Clear at t=0 (20mm apart), deeply overlapped at t=1 (0mm)."""
    return _slider(20 * (1 - t))


def _hinged(angle_deg: float) -> Assembly:
    """A cube on a revolute joint about Z at the origin, starting clear
    of a fixed cube and swinging into it."""
    arm = Assembly().with_part("arm", _cube(), location=Location((20, 0, 0)))
    return (
        Assembly()
        .with_part("post", _cube(), location=Location((0, 20, 0)))
        .with_subassembly(
            "swing",
            arm,
            joint=RevoluteJoint(axis=Axis.Z, angle_deg=angle_deg),
        )
    )


def test_sweep_records_a_volume_per_sample():
    result = sweep(_approaching, (0.0, 0.5, 1.0), pairs=(("a", "b"),))
    (samples,) = result.pairs
    assert result.ts == (0.0, 0.5, 1.0)
    assert len(samples.volumes_mm3) == 3


def test_sweep_volumes_grow_as_parts_converge():
    (samples,) = sweep(_approaching, (0.0, 0.75, 1.0), pairs=(("a", "b"),)).pairs
    assert samples.volumes_mm3[0] == 0.0
    assert samples.volumes_mm3[1] < samples.volumes_mm3[2]


def test_sweep_discovers_pairs_without_being_told():
    result = sweep(_approaching, (0.0, 1.0))
    assert [(p.a, p.b) for p in result.pairs] == [("a", "b")]


def test_sweep_pair_key_order_is_stable_regardless_of_argument_order():
    (samples,) = sweep(_approaching, (1.0,), pairs=(("b", "a"),)).pairs
    assert (samples.a, samples.b) == ("a", "b")


def test_sweep_records_joint_angles_per_frame():
    result = sweep(over_joint(_hinged(0), "swing", (0, 90)), (0.0, 1.0))
    assert [a["swing"] for a in result.angles] == [0.0, 90.0]


def test_classify_reports_never_when_no_sample_overlaps():
    result = sweep(lambda t: _slider(20), (0.0, 0.5, 1.0), pairs=(("a", "b"),))
    (phase,) = classify(result)
    assert phase.kind == NEVER
    assert phase.t_intervals == ()
    assert phase.angles_at_contact == {}


def test_classify_reports_always_when_every_sample_overlaps():
    result = sweep(lambda t: _slider(2), (0.0, 1.0), pairs=(("a", "b"),))
    assert classify(result)[0].kind == ALWAYS


def test_classify_reports_transient_with_its_contact_range():
    result = sweep(_approaching, (0.0, 0.25, 0.75, 1.0), pairs=(("a", "b"),))
    (phase,) = classify(result)
    assert phase.kind == TRANSIENT
    assert phase.t_intervals == ((0.75, 1.0),)


def test_classify_separates_a_contact_that_releases_and_returns():
    """Two contact phases with a clear stretch between them — the m03
    lifter pad touches its drop block on the way up and again on the way
    down, but not at peak tilt. One first->last span would claim the
    clear middle as contact."""
    touching = (1.0, 4.0)
    result = sweep(
        lambda t: _slider(2 if t in touching else 20),
        (0.0, 1.0, 2.0, 3.0, 4.0, 5.0),
        pairs=(("a", "b"),),
    )
    (phase,) = classify(result)
    assert phase.kind == TRANSIENT
    assert phase.t_intervals == ((1.0, 1.0), (4.0, 4.0))


def test_classify_merges_adjacent_contacting_samples_into_one_interval():
    result = sweep(
        lambda t: _slider(2 if t in (1.0, 2.0, 3.0) else 20),
        (0.0, 1.0, 2.0, 3.0, 4.0),
        pairs=(("a", "b"),),
    )
    assert classify(result)[0].t_intervals == ((1.0, 3.0),)


def test_classify_brackets_the_angle_window_wider_than_the_observed_one():
    factory = over_joint(_hinged(0), "swing", (0, 90))
    phase = classify(sweep(factory, (0.0, 0.25, 0.5, 0.75, 1.0)))[0]
    inner = phase.angles_at_contact["swing"]
    outer = phase.angles_bracketing["swing"]
    assert outer[0] <= inner[0] and inner[1] <= outer[1]
    assert outer != inner


def test_classify_reports_the_peak_overlap_and_where_it_happened():
    result = sweep(_approaching, (0.0, 0.75, 1.0), pairs=(("a", "b"),))
    (phase,) = classify(result)
    assert phase.t_at_max == 1.0
    assert phase.max_volume_mm3 == max(result.pairs[0].volumes_mm3)


def test_classify_reports_the_joint_angle_span_of_the_contact():
    factory = over_joint(_hinged(0), "swing", (0, 90))
    phase = classify(sweep(factory, (0.0, 0.25, 0.5, 0.75, 1.0)))[0]
    assert phase.kind == TRANSIENT
    lo, hi = phase.angles_at_contact["swing"]
    assert 0 < lo <= hi <= 90


def test_onset_brackets_then_bisects_the_first_contact():
    result = onset(_approaching, ("a", "b"), (0.0, 0.25, 0.5, 0.75, 1.0))
    # Overlap begins where the parts are 10mm apart: t = 0.5.
    assert result.bracket[0] <= 0.5 <= result.bracket[1]
    assert abs(result.t - 0.5) < 1e-2
    assert result.brackets == 1


def test_onset_reports_none_when_the_pair_never_touches():
    result = onset(lambda t: _slider(20), ("a", "b"), (0.0, 0.5, 1.0))
    assert result.t is None
    assert result.bracket is None
    assert result.brackets == 0


def test_onset_flags_contact_already_present_at_the_range_start():
    result = onset(lambda t: _slider(2), ("a", "b"), (0.0, 0.5, 1.0))
    assert result.t == 0.0
    assert result.bracket is None


def test_onset_counts_every_transition_so_a_second_phase_is_visible():
    # Contact at t=1 and t=3 only — two separate clear->contact edges.
    factory = lambda t: _slider(2 if t in (1.0, 3.0) else 20)  # noqa: E731
    result = onset(factory, ("a", "b"), (0.0, 1.0, 2.0, 3.0))
    assert result.brackets == 2


def test_onset_evaluations_exceed_the_sample_count_when_it_bisects():
    result = onset(_approaching, ("a", "b"), (0.0, 1.0), tol=1e-3)
    assert result.evaluations > 2
