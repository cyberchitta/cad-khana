import pytest

from cad_khana.diff import diff
from cad_khana.mechanism.diagnostics import SCHEMA_VERSION


def _empty_mech() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ok",
        "parts": {},
        "interferences": [],
        "assertions": [],
    }


def _empty_printability() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "printability",
        "status": "ok",
        "name": "part",
        "method": "FDM",
        "method_params": {
            "up_axis": [0, 0, 1],
            "wall_min_mm": 1.5,
            "overhang_max_deg": 45.0,
        },
        "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]},
        "volume_mm3": 1.0,
        "surface_area_mm2": 6.0,
        "center_of_mass_mm": [0.5, 0.5, 0.5],
        "is_valid": True,
        "min_wall_mm": 1.0,
        "overhang": None,
        "assertions": [],
    }


# --- mechanism diff -----------------------------------------------------


def test_identical_mechanism_reports_no_changes():
    assert diff(_empty_mech(), _empty_mech()) == "no changes\n"


def test_status_change_is_reported():
    old = _empty_mech()
    new = _empty_mech() | {"status": "assertion_failed"}
    out = diff(old, new)
    assert "status:" in out
    assert "ok → assertion_failed" in out


def test_part_added_and_removed():
    old = _empty_mech() | {"parts": {"a": {"volume_mm3": 10, "bbox": {}}}}
    new = _empty_mech() | {"parts": {"b": {"volume_mm3": 20, "bbox": {}}}}
    out = diff(old, new)
    assert "added: b" in out
    assert "removed: a" in out


def test_part_volume_delta_with_percent():
    old = _empty_mech() | {"parts": {"a": {"volume_mm3": 100, "bbox": {}}}}
    new = _empty_mech() | {"parts": {"a": {"volume_mm3": 120, "bbox": {}}}}
    out = diff(old, new)
    assert "changed: a" in out
    assert "volume_mm3" in out
    assert "+20.0%" in out


def test_interference_added():
    old = _empty_mech()
    new = _empty_mech() | {
        "interferences": [
            {"a": "pin", "b": "tang", "volume_mm3": 0.5, "centroid": [0, 0, 0]}
        ]
    }
    out = diff(old, new)
    assert "interferences:" in out
    assert "added: pin / tang" in out
    assert "0.5" in out


def test_assertion_regression_shows_detail():
    old = _empty_mech() | {"assertions": [{"name": "clr", "passed": True, "detail": None}]}
    new = _empty_mech() | {
        "assertions": [
            {"name": "clr", "passed": False, "detail": "distance 0.1mm below min 0.2mm"}
        ]
    }
    out = diff(old, new)
    assert "regressed: clr" in out
    assert "distance 0.1mm" in out


def test_assertion_fix_is_reported():
    old = _empty_mech() | {"assertions": [{"name": "clr", "passed": False, "detail": "x"}]}
    new = _empty_mech() | {"assertions": [{"name": "clr", "passed": True, "detail": None}]}
    out = diff(old, new)
    assert "fixed: clr" in out


def test_assertion_newly_skipped_is_reported():
    old = _empty_mech() | {"assertions": [{"name": "clr", "passed": True, "detail": None}]}
    new = _empty_mech() | {
        "assertions": [{"name": "clr", "passed": None, "detail": "skipped: part(s) absent from this run: bolt"}]
    }
    out = diff(old, new)
    assert "changed: clr passed → skipped" in out


def test_assertion_skip_to_failure_is_reported():
    old = _empty_mech() | {"assertions": [{"name": "clr", "passed": None, "detail": "skipped"}]}
    new = _empty_mech() | {"assertions": [{"name": "clr", "passed": False, "detail": "x"}]}
    out = diff(old, new)
    assert "changed: clr skipped → failed" in out


def test_assertion_added_as_skipped_is_reported():
    old = _empty_mech()
    new = _empty_mech() | {"assertions": [{"name": "clr", "passed": None, "detail": "skipped"}]}
    out = diff(old, new)
    assert "added: clr (skipped)" in out


def test_assertion_skip_names_its_class():
    old = _empty_mech() | {"assertions": [{"name": "clr", "passed": True, "skipped": None}]}
    new = _empty_mech() | {"assertions": [{"name": "clr", "passed": None, "skipped": "absent_part"}]}
    assert "changed: clr passed → skipped (absent_part)" in diff(old, new)


def test_assertion_skip_class_change_is_reported():
    old = _empty_mech() | {"assertions": [{"name": "clr", "passed": None, "skipped": "absent_part"}]}
    new = _empty_mech() | {"assertions": [{"name": "clr", "passed": None, "skipped": "absent_joint"}]}
    assert (
        "changed: clr skipped (absent_part) → skipped (absent_joint)"
        in diff(old, new)
    )


def test_assertion_stably_skipped_is_not_reported():
    skipped = {"assertions": [{"name": "clr", "passed": None, "detail": "skipped"}]}
    assert diff(_empty_mech() | skipped, _empty_mech() | skipped) == "no changes\n"


def test_assertion_newly_waived_is_reported():
    failing = {"name": "wall_min:1.5", "passed": False, "detail": "x"}
    old = _empty_printability() | {"assertions": [failing | {"waived": None}]}
    new = _empty_printability() | {"assertions": [failing | {"waived": "artifact"}]}
    out = diff(old, new)
    assert "changed: wall_min:1.5 unwaived → waived (artifact)" in out


def test_assertion_stably_waived_is_not_reported():
    waived = {
        "assertions": [
            {"name": "wall_min:1.5", "passed": False, "detail": "x", "waived": "artifact"}
        ],
        "warnings": [
            {"kind": "waived_failure", "assertion": "wall_min:1.5", "reason": "artifact", "detail": "x"}
        ],
    }
    assert (
        diff(_empty_printability() | waived, _empty_printability() | waived)
        == "no changes\n"
    )


def test_warning_added_and_removed():
    old = _empty_printability() | {
        "warnings": [
            {"kind": "stale_waiver", "assertion": "overhang_max:45.0", "reason": "old", "detail": None}
        ]
    }
    new = _empty_printability() | {
        "warnings": [
            {"kind": "waived_failure", "assertion": "wall_min:1.5", "reason": "artifact", "detail": "x"}
        ]
    }
    out = diff(old, new)
    assert "warnings:" in out
    assert "added: waived_failure: wall_min:1.5 — artifact" in out
    assert "removed: stale_waiver: overhang_max:45.0" in out


# --- mechanism diff: motions and warnings ---------------------------------


def _motion(
    samples: int = 180,
    max_step: float = 2.0,
    moved: int = 28,
    movable: int = 2095,
) -> dict:
    return {
        "name": "stack_turn",
        "samples": samples,
        "joints_deg": {
            "rotating": {"min": 0.0, "max": 358.0, "max_step": max_step}
        },
        "moved": moved,
        "movable": movable,
    }


def test_a_motion_no_longer_declared_is_reported():
    """The run that stopped looking must not diff as clean."""
    old = {**_empty_mech(), "motions": [_motion()]}
    out = diff(old, _empty_mech())
    assert "motions:" in out
    assert "removed: stack_turn (180 samples)" in out


def test_a_motion_declared_is_reported():
    new = {**_empty_mech(), "motions": [_motion()]}
    assert "added: stack_turn (180 samples)" in diff(_empty_mech(), new)


def test_a_motion_sampled_more_coarsely_is_reported():
    old = {**_empty_mech(), "motions": [_motion()]}
    new = {**_empty_mech(), "motions": [_motion(samples=90, max_step=4.0)]}
    out = diff(old, new)
    assert "changed: stack_turn samples 180 → 90" in out
    assert "changed: stack_turn rotating max_step 2.0 → 4.0" in out


def test_mechanism_warnings_are_diffed():
    old = {
        **_empty_mech(),
        "warnings": [{"kind": "joint_never_driven", "joint": "rotor"}],
    }
    new = {
        **_empty_mech(),
        "warnings": [
            {"kind": "never_in_phase", "assertion": "pad_engages"},
            {"kind": "interferences_rest_pose_only"},
        ],
    }
    out = diff(old, new)
    assert "warnings:" in out
    assert "removed: joint_never_driven: rotor" in out
    assert "added: never_in_phase: pad_engages" in out
    assert "added: interferences_rest_pose_only" in out


def test_value_drift_names_the_pose_it_came_from():
    def held(value, t):
        return {
            **_empty_mech(),
            "assertions": [
                {
                    "name": "d",
                    "passed": True,
                    "detail": None,
                    "value": value,
                    "worst_at": {
                        "motion": "stack_turn",
                        "t": t,
                        "joints_deg": {"rotating": 360 * t},
                    },
                }
            ],
        }

    out = diff(held(0.35, 0.1), held(0.30, 0.25))
    assert "changed: d value" in out
    assert "(worst at stack_turn t=0.25)" in out


# --- printability diff --------------------------------------------------


def test_identical_printability_reports_no_changes():
    assert diff(_empty_printability(), _empty_printability()) == "no changes\n"


def _with_params(**params) -> dict:
    base = _empty_printability()
    return base | {"method_params": base["method_params"] | params}


def test_printability_up_axis_change_is_reported():
    out = diff(_with_params(), _with_params(up_axis=[0, -1, 0]))
    assert "method_params:" in out
    assert "up_axis: [0, 0, 1] → [0, -1, 0]" in out


def test_printability_threshold_param_change_is_reported():
    out = diff(_with_params(), _with_params(overhang_max_deg=90.0))
    assert "method_params:" in out
    assert "overhang_max_deg: 45 → 90" in out


def test_printability_param_added_or_removed_is_reported():
    old = _empty_printability()
    new = _with_params(nozzle_mm=0.4)
    assert "nozzle_mm: None → 0.4" in diff(old, new)
    assert "nozzle_mm: 0.4 → None" in diff(new, old)


def test_equivalent_up_axis_spelled_as_float_is_no_change():
    assert diff(_with_params(), _with_params(up_axis=[0.0, 0.0, 1.0])) == "no changes\n"


def test_printability_volume_delta():
    old = _empty_printability()
    new = _empty_printability() | {"volume_mm3": 1.5}
    out = diff(old, new)
    assert "volume_mm3" in out
    assert "+50" in out


def test_printability_min_wall_delta():
    old = _empty_printability() | {"min_wall_mm": 1.0}
    new = _empty_printability() | {"min_wall_mm": 2.0}
    out = diff(old, new)
    assert "min_wall_mm" in out


def test_printability_min_wall_witness_move():
    old = _empty_printability() | {"min_wall_at": [0.0, 0.0, 1.0]}
    new = _empty_printability() | {"min_wall_at": [5.0, 0.0, 1.0]}
    out = diff(old, new)
    assert "min_wall_at" in out


def test_printability_overhang_added():
    old = _empty_printability()
    new = _empty_printability() | {
        "overhang": {"area_mm2": 100.0, "max_angle_deg": 90.0, "regions": []}
    }
    out = diff(old, new)
    assert "overhang:" in out
    assert "added" in out


def test_printability_overhang_removed():
    old = _empty_printability() | {
        "overhang": {"area_mm2": 100.0, "max_angle_deg": 90.0, "regions": []}
    }
    new = _empty_printability()
    out = diff(old, new)
    assert "overhang:" in out
    assert "removed" in out


def _region(area: float, at: list[float]) -> dict:
    return {
        "area_mm2": area,
        "max_angle_deg": 90.0,
        "centroid_mm": at,
        "bbox": {"min": at, "max": at},
    }


def _with_regions(*regions: dict) -> dict:
    return _empty_printability() | {
        "overhang": {
            "area_mm2": sum(r["area_mm2"] for r in regions),
            "max_angle_deg": 90.0,
            "regions": list(regions),
        }
    }


def test_printability_overhang_region_added_and_removed():
    ledge = _region(200.0, [15.0, 0.0, 3.0])
    old = _with_regions(ledge, _region(60.0, [-13.0, 0.0, -1.0]))
    new = _with_regions(ledge, _region(0.83, [4.0, 4.0, 0.2]))
    out = diff(old, new)
    assert "region added: 0.83 mm² at (4.00, 4.00, 0.20)" in out
    assert "region removed: 60 mm² at (-13.00, 0.00, -1.00)" in out
    assert "15.00, 0.00, 3.00" not in out


def test_printability_overhang_region_area_change_at_the_same_place():
    old = _with_regions(_region(200.0, [15.0, 0.0, 3.0]))
    new = _with_regions(_region(150.0, [15.0, 0.0, 3.0]))
    out = diff(old, new)
    assert "region changed: at (15.00, 0.00, 3.00) area 200 → 150 (-25.0%)" in out


def test_printability_overhang_region_centroid_noise_is_no_change():
    old = _with_regions(_region(200.0, [15.0, 0.0, 3.0]))
    new = _with_regions(_region(200.0 + 1e-9, [15.0 + 1e-9, 0.0, 3.0]))
    assert "region" not in diff(old, new)


def test_printability_overhang_added_counts_its_regions():
    new = _with_regions(_region(200.0, [15.0, 0.0, 3.0]), _region(60.0, [0, 0, 0]))
    out = diff(_empty_printability(), new)
    assert "added: area=260 mm² max_angle=90° regions=2" in out


def test_printability_assertion_regression():
    old = _empty_printability() | {
        "assertions": [{"name": "wall_min:1.5", "passed": True, "detail": None}]
    }
    new = _empty_printability() | {
        "assertions": [
            {"name": "wall_min:1.5", "passed": False, "detail": "min wall 1.0mm below min 1.5mm"}
        ]
    }
    out = diff(old, new)
    assert "regressed: wall_min:1.5" in out


# --- dispatch errors ----------------------------------------------------


def test_diff_across_kinds_raises():
    with pytest.raises(ValueError):
        diff(_empty_mech(), _empty_printability())


def test_diff_across_kinds_raises_reverse():
    with pytest.raises(ValueError):
        diff(_empty_printability(), _empty_mech())


# --- schema enforcement -------------------------------------------------


def test_mismatched_schema_version_raises_with_regenerate_hint():
    old = _empty_mech() | {"schema_version": "0.1"}
    new = _empty_mech()
    with pytest.raises(ValueError, match="regenerate"):
        diff(old, new)


def test_both_stale_schema_versions_also_raise():
    old = _empty_mech() | {"schema_version": "0.1"}
    new = _empty_mech() | {"schema_version": "0.1"}
    with pytest.raises(ValueError, match="regenerate"):
        diff(old, new)


def test_printability_schema_mismatch_raises():
    old = _empty_printability() | {"schema_version": "0.1"}
    new = _empty_printability()
    with pytest.raises(ValueError, match="regenerate"):
        diff(old, new)


# --- new mechanism part fields -----------------------------------------


def test_part_surface_area_delta():
    old = _empty_mech() | {
        "parts": {"a": {"volume_mm3": 100, "surface_area_mm2": 60, "bbox": {}}}
    }
    new = _empty_mech() | {
        "parts": {"a": {"volume_mm3": 100, "surface_area_mm2": 72, "bbox": {}}}
    }
    out = diff(old, new)
    assert "surface_area_mm2" in out
    assert "+20.0%" in out


def test_part_center_of_mass_change_reported():
    old = _empty_mech() | {
        "parts": {"a": {"volume_mm3": 100, "center_of_mass_mm": [0, 0, 0], "bbox": {}}}
    }
    new = _empty_mech() | {
        "parts": {"a": {"volume_mm3": 100, "center_of_mass_mm": [1, 0, 0], "bbox": {}}}
    }
    out = diff(old, new)
    assert "center_of_mass_mm" in out


def test_part_is_valid_regression_reported():
    old = _empty_mech() | {
        "parts": {"a": {"volume_mm3": 100, "is_valid": True, "bbox": {}}}
    }
    new = _empty_mech() | {
        "parts": {"a": {"volume_mm3": 100, "is_valid": False, "bbox": {}}}
    }
    out = diff(old, new)
    assert "is_valid" in out
    assert "True → False" in out


# --- new printability fields -------------------------------------------


def test_printability_surface_area_delta():
    old = _empty_printability()
    new = _empty_printability() | {"surface_area_mm2": 9.0}
    out = diff(old, new)
    assert "surface_area_mm2" in out
    assert "+50" in out


def test_printability_is_valid_regression():
    old = _empty_printability()
    new = _empty_printability() | {"is_valid": False}
    out = diff(old, new)
    assert "is_valid" in out


def _mech_with_part(com_x: float) -> dict:
    d = _empty_mech()
    d["parts"] = {
        "p": {
            "volume_mm3": 100.0,
            "surface_area_mm2": 130.0,
            "bbox": {"min": [0, 0, 0], "max": [1, 1, 1]},
            "center_of_mass_mm": [com_x, 0.5, 0.5],
            "is_valid": True,
        }
    }
    return d


def test_part_ulp_noise_is_not_reported():
    old = _mech_with_part(0.5)
    new = _mech_with_part(0.5 + 1e-12)
    assert diff(old, new) == "no changes\n"


def test_part_real_move_is_reported():
    old = _mech_with_part(0.5)
    new = _mech_with_part(0.501)
    assert "center_of_mass_mm" in diff(old, new)


def test_assertion_value_drift_reported_when_state_unchanged():
    old = _empty_mech() | {
        "assertions": [
            {"name": "distance:gear/pinion>=0.15", "passed": True, "detail": None, "value": 0.2}
        ]
    }
    new = _empty_mech() | {
        "assertions": [
            {"name": "distance:gear/pinion>=0.15", "passed": True, "detail": None, "value": 0.24}
        ]
    }
    out = diff(old, new)
    assert "changed: distance:gear/pinion>=0.15 value" in out
    assert "0.2 → 0.24" in out


def test_assertion_value_noise_below_tolerance_not_reported():
    old = _empty_mech() | {
        "assertions": [{"name": "d", "passed": True, "detail": None, "value": 0.2}]
    }
    new = _empty_mech() | {
        "assertions": [{"name": "d", "passed": True, "detail": None, "value": 0.2 + 1e-9}]
    }
    assert diff(old, new) == "no changes\n"


def test_regressed_assertion_not_double_reported_as_value_change():
    old = _empty_mech() | {
        "assertions": [{"name": "d", "passed": True, "detail": None, "value": 0.2}]
    }
    new = _empty_mech() | {
        "assertions": [
            {"name": "d", "passed": False, "detail": "below min", "value": 0.1}
        ]
    }
    out = diff(old, new)
    assert "regressed: d" in out
    assert "value" not in out


# --- solid_count --------------------------------------------------------


def test_mechanism_part_solid_count_change_is_reported():
    old = _empty_mech() | {"parts": {"a": {"volume_mm3": 100, "solid_count": 1, "bbox": {}}}}
    new = _empty_mech() | {"parts": {"a": {"volume_mm3": 100, "solid_count": 2, "bbox": {}}}}
    assert "solid_count: 1 → 2" in diff(old, new)


def test_mechanism_multi_solid_warning_is_labelled_by_part():
    new = _empty_mech() | {
        "warnings": [{"kind": "multi_solid", "part": "pair", "solid_count": 2}]
    }
    assert "added: multi_solid: pair" in diff(_empty_mech(), new)


def test_printability_solid_count_change_is_reported():
    old = _empty_printability() | {"solid_count": 1}
    new = _empty_printability() | {
        "solid_count": 2,
        "warnings": [{"kind": "multi_solid", "part": "pair", "solid_count": 2}],
    }
    out = diff(old, new)
    assert "solid_count" in out and "1 → 2" in out
    assert "added: multi_solid: pair" in out


# --- a motion's moved count (V4, V5) ---


def _counted_motion(name: str, moved: int, movable: int) -> dict:
    return {
        "name": name,
        "samples": 10,
        "joints_deg": {"j": {"min": 0.0, "max": 90.0, "max_step": 10.0}},
        "moved": moved,
        "movable": movable,
    }


def test_a_motion_that_stops_moving_claims_is_reported():
    """The regression nobody would otherwise see: same samples, same
    joint range, and the sweep quietly stopped testing anything."""
    old = _empty_mech() | {"motions": [_counted_motion("turn", 28, 2095)]}
    new = _empty_mech() | {"motions": [_counted_motion("turn", 0, 2095)]}
    out = diff(old, new)
    assert "moved 28 of 2095 claims → 0 of 2095" in out


def test_a_motion_whose_counts_hold_reports_nothing():
    old = _empty_mech() | {"motions": [_counted_motion("turn", 28, 2095)]}
    assert diff(old, old) == "no changes\n"


def test_two_vacuous_motions_are_labelled_apart():
    """`motion_moved_nothing` carries `motion`, not `assertion` or
    `part`, so the warning label has to know that field or both
    motions collapse into one line."""
    vacuous = [
        {"kind": "motion_moved_nothing", "motion": n, "moved": 0, "movable": 4}
        for n in ("turn", "nudge")
    ]
    out = diff(_empty_mech(), _empty_mech() | {"warnings": vacuous})
    assert "added: motion_moved_nothing: turn" in out
    assert "added: motion_moved_nothing: nudge" in out


# --- partial runs -----------------------------------------------------------


def _partial(only: list[str]) -> dict:
    return {
        **_empty_mech(),
        "interferences": None,
        "selection": {
            "only": only,
            "declared": 3,
            "evaluated": 1,
            "not_computed": ["interferences"],
        },
    }


def test_diff_refuses_a_partial_run_against_a_full_one():
    """Claims the partial run left out would read as removed."""
    with pytest.raises(ValueError, match="cannot diff a partial run"):
        diff(_empty_mech(), _partial(["gap_*"]))
    with pytest.raises(ValueError, match="cannot diff a partial run"):
        diff(_partial(["gap_*"]), _empty_mech())


def test_diff_refuses_two_different_selections():
    with pytest.raises(ValueError, match="cannot diff a partial run"):
        diff(_partial(["gap_*"]), _partial(["clear_*"]))


def test_diff_compares_two_runs_of_one_selection():
    assert diff(_partial(["gap_*"]), _partial(["gap_*"])) == "no changes\n"


def test_diff_reports_a_changed_declared_count_under_one_selection():
    grown = _partial(["gap_*"])
    grown["selection"] = {**grown["selection"], "declared": 4}
    assert "declared 3 → 4" in diff(_partial(["gap_*"]), grown)


def test_a_keepout_measuring_fewer_parts_is_reported_while_it_still_passes():
    """One result per keep-out folds its parts into a count; a selection
    that shrank (a renamed subtree, a wider ``excluding``) must still
    show, as the dropped per-part rows once did."""
    claim = {"name": "clear_of:driver>=0.5", "passed": True, "detail": None, "value": 9.5}
    old = _empty_mech() | {"assertions": [claim | {"measured": 357}]}
    new = _empty_mech() | {"assertions": [claim | {"measured": 345}]}
    assert "changed: clear_of:driver>=0.5 measured 357 → 345" in diff(old, new)
