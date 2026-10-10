"""Named regions: a claim about one feature of a part.

The fixtures are shapes whose answers come from arithmetic. ``_table``
is a 40 x 40 x 2 slab carrying four 4 x 4 posts at (+-15, +-15), one
body; three posts reach z = 12 and the ``ne`` one stops 0.3 short. A
plate rests on the three. Each post has a region: a box round it from
z = 2.5 up, so a tall post holds 4 * 4 * 9.5 = 152 mm^3 of the body and
the short one 147.2.
"""

import json
from collections.abc import Callable, Iterable
from math import hypot, pi
from pathlib import Path

import pytest
from build123d import (
    Axis,
    Box,
    Compound,
    Cylinder,
    Location,
    Part,
    Plane,
    Pos,
    Rectangle,
    Solid,
    Sphere,
)

from cad_khana.mechanism import assertions
from cad_khana.mechanism.assembly import Assembly, DetailOverride, RevoluteJoint
from cad_khana.mechanism.assertions import (
    JointWindow,
    Measuring,
    NoInterference,
    evaluate,
)
from cad_khana.mechanism.check import check
from cad_khana.mechanism.diagnostics import AssertionResult, PoseCounts
from cad_khana.mechanism.hold import hold
from cad_khana.mechanism.motion import Motion

POSTS = {"sw": (-1, -1), "se": (1, -1), "nw": (-1, 1), "ne": (1, 1)}
SHORT = 0.3
BODY_MM3 = 40 * 40 * 2 + 3 * 160 + 16 * (10 - SHORT)


def _close(got: float | None, want: float, tol: float = 1e-6) -> bool:
    return got is not None and abs(got - want) < tol


def _detail(result: AssertionResult) -> str:
    assert result.detail is not None
    return result.detail


def _poses(result: AssertionResult) -> PoseCounts:
    assert result.poses is not None
    return result.poses


def _fused(pieces: list[Part]) -> Part:
    return Part((Part() + pieces).solids())


def _clear_of(
    assembly: Assembly,
    parts: str | Iterable[str],
    keepout: Compound | Solid,
    name: str,
    min_mm: float = 0.0,
    excluding: Iterable[str] = (),
) -> Assembly:
    return assembly.assert_clear_of(  # pyright: ignore[reportUnknownMemberType]
        parts, keepout, name=name, min_mm=min_mm, excluding=excluding
    )


def _post(sx: int, sy: int, top: float) -> Part:
    return Pos(sx * 15, sy * 15, (2 + top) / 2) * Box(4, 4, top - 2)


def _body(short: float = SHORT) -> Part:
    posts = [
        _post(sx, sy, 12 - (short if name == "ne" else 0))
        for name, (sx, sy) in POSTS.items()
    ]
    return _fused([Pos(0, 0, 1) * Box(40, 40, 2), *posts])


def _post_box(sx: int, sy: int) -> Part:
    return Pos(sx * 15, sy * 15, 7.75) * Box(6, 6, 10.5)


def _table(short: float = SHORT) -> Assembly:
    table = (
        Assembly()
        .with_part("body", _body(short))
        .with_part("plate", Box(40, 40, 2), location=Location((0, 0, 13)))
    )
    for name, (sx, sy) in POSTS.items():
        table = table.with_region("body", name, _post_box(sx, sy))
    return table


def _one(assembly: Assembly) -> AssertionResult:
    (result,) = evaluate(assembly)
    return result


# --- the false green the feature exists for --------------------------------


def test_the_whole_part_claim_is_green_on_three_posts_of_four():
    result = _one(_table().assert_tangent_contact("plate", "body"))
    assert result.passed
    assert _close(result.value, 0.0)
    assert result.detail is None


@pytest.mark.parametrize("post", sorted(POSTS))
def test_a_claim_per_post_fails_the_short_one(post: str):
    result = _one(_table().assert_tangent_contact("plate", f"body@{post}"))
    assert result.name == f"tangent_contact:plate/body@{post}"
    assert result.passed is (post != "ne")
    assert _close(result.value, SHORT if post == "ne" else 0.0)


def test_a_passing_claim_says_how_much_of_the_part_it_looked_at():
    result = _one(_table().assert_tangent_contact("plate", "body@sw"))
    assert result.detail == f"body@sw: 152.0000mm^3 of body's {BODY_MM3:.4f}mm^3"


def test_a_failing_claim_keeps_the_label_after_its_failure():
    result = _one(_table().assert_tangent_contact("plate", "body@ne"))
    assert result.detail == (
        "no contact: gap 0.3000mm exceeds tol 0.001mm; "
        f"body@ne: 147.2000mm^3 of body's {BODY_MM3:.4f}mm^3"
    )


# --- each accepted claim kind ----------------------------------------------


def test_distance_reads_from_the_region_not_the_part():
    whole = _one(_table().assert_distance("plate", "body", min_mm=0))
    post = _one(_table().assert_distance("plate", "body@ne", min_mm=0.2, max_mm=0.4))
    assert _close(whole.value, 0.0)
    assert post.name == "distance:plate/body@ne>=0.2<=0.4"
    assert post.passed
    assert _close(post.value, SHORT)
    assert post.witness_mm is not None
    assert _close(post.witness_mm[1][2], 12 - SHORT)
    assert _detail(post).startswith("body@ne: 147.2000mm^3 of body's ")


def test_distance_takes_a_region_on_either_side_and_against_a_plane():
    a = (
        _table()
        .assert_distance("body@ne", "body@sw", min_mm=0, name="posts")
        .assert_distance("body@ne", Plane.XY.offset(13), along="Z", min_mm=0, name="up")
    )
    posts, up = evaluate(a)
    assert _close(posts.value, hypot(26, 26))
    assert _detail(posts).count("mm^3 of body's") == 2
    assert _close(up.value, 1 + SHORT)


def test_within_takes_a_region_as_the_inner_side():
    result = _one(_table().assert_within("body@sw", "plate", along="Z"))
    assert result.name == "within:body@sw/plate@Z"
    assert result.passed
    assert _close(result.value, 0.0)
    assert _detail(result).startswith("body@sw: 152.0000mm^3")


def test_within_takes_a_region_as_the_outer_side():
    """The slab covers the plate in plan, so the whole body does; the
    posts' own footprint is four 4 x 4 squares under a 40 x 40 plate."""
    whole = _one(_table().assert_within("plate", "body", along="Z"))
    table = _table().with_region("body", "posts", Pos(0, 0, 7.75) * Box(40, 40, 10.5))
    posts = _one(table.assert_within("plate", "body@posts", along="Z"))
    assert whole.passed and _close(whole.value, 0.0)
    assert posts.passed is False
    assert _close(posts.value, (1600 - 4 * 16) * 2)
    assert "plate outside body@posts's footprint" in _detail(posts)


def test_a_region_wholly_inside_the_other_part_reads_zero_and_says_so():
    """The pin's tip sits in the block's material and its head stands
    clear above it: the kernel's distance from the tip to the block's
    skin is 4 mm, and the claim reads 0."""
    a = (
        Assembly()
        .with_part("block", Box(20, 20, 20))
        .with_part("pin", Pos(0, 0, 8) * Box(2, 2, 16))
        .with_region("pin", "tip", Pos(0, 0, 3) * Box(4, 4, 6))
        .assert_distance("pin@tip", "block", min_mm=0.5)
    )
    result = _one(a)
    assert result.passed is False
    assert _close(result.value, 0.0)
    assert result.detail == (
        "distance 0.0000mm below min 0.5mm; pin@tip lies inside block; "
        "pin@tip: 24.0000mm^3 of pin's 64.0000mm^3"
    )


def _zone() -> Part:
    # 2 mm above the sw post's top, and 26 mm in x and in y from the ne one.
    return Pos(-15, -15, 16) * Box(4, 4, 4)


def test_clear_of_takes_a_region_among_its_parts():
    whole = _one(_clear_of(_table(), "body", _zone(), "zone", min_mm=1))
    post = _one(_clear_of(_table(), ["body@ne"], _zone(), "zone", min_mm=1))
    assert _close(whole.value, 2.0)
    assert post.passed
    near = hypot(26, 26, 2 + SHORT)
    assert _close(post.value, near)
    assert post.measured == 1
    assert post.detail == (
        f"nearest of 1: body@ne at {near:.4f}mm; "
        f"body@ne: 147.2000mm^3 of body's {BODY_MM3:.4f}mm^3"
    )


def test_a_region_claim_fails_like_any_other():
    result = _one(_clear_of(_table(), "body@sw", _zone(), "zone", min_mm=3))
    assert result.passed is False
    assert _detail(result).startswith(
        "1 of 1 parts: body@sw distance 2.0000mm below min 3mm at ("
    )


# --- excluding: the part less the region -----------------------------------


def _drilled() -> Assembly:
    """A 20 mm cube and, through its middle along Z, a radius-1 rod that
    is the keep-out: the cube overlaps it by 20 * pi mm^3. ``plug`` is a
    radius-3 cylinder on the same axis, so the cube less the plug stands
    2 mm off the rod and has lost 9 * pi * 20 mm^3."""
    return (
        Assembly()
        .with_part("box", Box(20, 20, 20))
        .with_part("far", Box(2, 2, 2), location=Location((50, 0, 0)))
        .with_region("box", "plug", Cylinder(3, 30))
    )


ROD = Cylinder(1, 40)
LEFT_MM3 = 8000 - 9 * pi * 20


def test_the_whole_box_overlaps_the_rod():
    result = _one(_clear_of(_drilled(), "box", ROD, "rod"))
    assert result.passed is False
    assert f"overlaps the keep-out by {20 * pi:.4f}mm^3" in _detail(result)


def test_excluding_a_region_holds_the_rest_of_the_part():
    result = _one(
        _clear_of(
            _drilled(), ["box", "far"], ROD, "rod", min_mm=1, excluding=["box@plug"]
        )
    )
    assert result.name == "clear_of:rod>=1"
    assert result.passed
    assert _close(result.value, 2.0)
    assert result.measured == 2  # the box is still held
    assert result.detail == (
        "nearest of 2: box at 2.0000mm; "
        f"excluding box@plug: {LEFT_MM3:.4f}mm^3 of box's 8000.0000mm^3 held"
    )


def test_the_part_less_its_region_still_fails_inside_the_margin():
    result = _one(
        _clear_of(_drilled(), "box", ROD, "rod", min_mm=2.5, excluding=["box@plug"])
    )
    assert result.passed is False
    assert "box distance 2.0000mm below min 2.5mm" in _detail(result)
    assert "excluding box@plug" in _detail(result)


def test_material_outside_the_excluded_region_is_caught():
    """A plug narrower than the rod leaves a sleeve of the box in it:
    (1 - 0.25) * pi * 20 mm^3."""
    a = _drilled().with_region("box", "pilot", Cylinder(0.5, 30))
    result = _one(_clear_of(a, "box", ROD, "rod", excluding=["box@pilot"]))
    assert result.passed is False
    assert f"box overlaps the keep-out by {0.75 * pi * 20:.4f}mm^3" in _detail(result)


def test_several_regions_excluded_from_one_part_are_all_dropped():
    a = _drilled().with_region("box", "corner", Pos(10, 10, 10) * Box(4, 4, 4))
    result = _one(_clear_of(a, "box", ROD, "rod", excluding=["box@plug", "box@corner"]))
    assert result.passed
    assert _detail(result).endswith(
        f"excluding box@plug, box@corner: {LEFT_MM3 - 8:.4f}mm^3 of box's "
        "8000.0000mm^3 held"
    )


def test_an_excluded_region_must_be_on_a_part_the_claim_holds():
    with pytest.raises(ValueError, match="box@plug.*is not among the parts held"):
        _clear_of(_drilled(), "far", ROD, "rod", excluding=["box@plug"])
    with pytest.raises(ValueError, match="is not among the parts held"):
        _clear_of(_drilled(), ["box", "far"], ROD, "rod", excluding=["box", "box@plug"])


# --- empty: a fail, never a skip or a pass ---------------------------------

MISS = Pos(100, 0, 0) * Box(4, 4, 4)

EMPTY_CLAIMS: dict[str, Callable[[Assembly], Assembly]] = {
    "tangent_contact": lambda a: a.assert_tangent_contact("plate", "body@miss"),
    "distance": lambda a: a.assert_distance("plate", "body@miss", max_mm=500),
    "within_inner": lambda a: a.assert_within("body@miss", "plate", along="Z"),
    "within_outer": lambda a: a.assert_within("plate", "body@miss", along="Z"),
    "clear_of": lambda a: _clear_of(a, ["plate", "body@miss"], _zone(), "z"),
}


@pytest.mark.parametrize("kind", sorted(EMPTY_CLAIMS))
def test_a_region_that_misses_its_part_fails_the_claim(kind: str):
    result = _one(EMPTY_CLAIMS[kind](_table().with_region("body", "miss", MISS)))
    assert result.passed is False
    assert result.skipped is None
    assert result.detail == (
        "region body@miss holds no material of body: its solid misses the part"
    )


def test_an_empty_region_fails_the_run(tmp_path: Path):
    a = _table().with_region("body", "miss", MISS)
    with pytest.raises(SystemExit):
        check(a.assert_distance("plate", "body@miss", max_mm=500), out=tmp_path)
    written = json.loads((tmp_path / "mechanism.json").read_text())
    assert written["status"] == "assertion_failed"
    assert written["skipped_counts"] == {
        "absent_part": 0,
        "absent_joint": 0,
        "out_of_phase": 0,
    }
    assert sorted(written["parts"]) == ["body", "plate"]


def test_a_part_left_empty_by_an_exclusion_fails_the_claim():
    a = _drilled().with_region("box", "all", Box(30, 30, 30))
    result = _one(_clear_of(a, ["box", "far"], ROD, "rod", excluding=["box@all"]))
    assert result.passed is False
    assert result.skipped is None
    assert result.measured == 2
    assert result.detail == "excluding box@all leaves nothing of box to hold clear"


def _with_a_stray_face() -> Part:
    """A 10 mm cube and, 20 mm above it, a face in no solid: the part's
    nearest point to anything overhead is on the face."""
    return Part([Box(10, 10, 10), *(Pos(0, 0, 25) * Rectangle(10, 10)).faces()])


def test_a_region_of_a_part_with_a_surface_fails_rather_than_drop_the_surface():
    """Cut to its solids, the part would read 34.5 mm to the lid from
    the cube's top (40 from the cube less the region); the face is 14.5
    below the lid. Whole, the keep-out claim refuses the part for its
    surface."""
    lid = Pos(0, 0, 40) * Box(10, 10, 1)
    a = (
        Assembly()
        .with_part("mixed", _with_a_stray_face())
        .with_part("lid", lid)
        .with_region("mixed", "all", Box(60, 60, 60))
        .with_region("mixed", "base", Pos(0, 0, -4) * Box(12, 12, 4))
    )
    whole = _one(a.assert_distance("mixed", "lid", min_mm=20))
    assert whole.passed is False and _close(whole.value, 14.5)
    region = _one(a.assert_distance("mixed@all", "lid", min_mm=20))
    assert region.passed is False and region.value is None
    assert region.detail == (
        "mixed has faces outside any solid, so a region of it would leave them "
        "out; a region is cut from material"
    )
    less = _one(_clear_of(a, "mixed", lid, "lid", min_mm=20, excluding=["mixed@base"]))
    assert less.passed is False
    assert "mixed has faces outside any solid" in _detail(less)


def test_a_region_that_swallows_the_part_reads_as_the_whole_part():
    table = _table().with_region("body", "all", Box(100, 100, 100))

    def claims(body: str) -> Assembly:
        held = (
            table.assert_tangent_contact("plate", body)
            .assert_distance(body, "plate", min_mm=0)
            .assert_within("plate", body, along="Z")
        )
        return _clear_of(held, body, _zone(), "zone")

    whole, region = evaluate(claims("body")), evaluate(claims("body@all"))
    assert [r.passed for r in region] == [r.passed for r in whole] == [True] * 4
    assert all(
        w.value is not None and _close(r.value, w.value)
        for r, w in zip(region, whole, strict=True)
    )
    assert f"body@all: {BODY_MM3:.4f}mm^3 of body's {BODY_MM3:.4f}mm^3" in (
        _detail(region[0])
    )


# --- refused: the claims about the whole part or the pair ------------------

REFUSED: dict[str, Callable[[Assembly], Assembly]] = {
    "assert_no_interference": lambda a: a.assert_no_interference("plate", "body@sw"),
    "assert_allowed_contact": lambda a: a.assert_allowed_contact(
        "body@sw", "plate", max_overlap_mm3=1.0
    ),
    "assert_interference": lambda a: a.assert_interference("plate", "body@sw"),
    "assert_solid_count": lambda a: a.assert_solid_count("body@sw"),
    "assert_no_interference_between": lambda a: a.assert_no_interference_between(
        ["plate"], ["body@sw"]
    ),
    "assert_no_interference_within": lambda a: a.assert_no_interference_within(
        ["plate", "body@sw"]
    ),
}


@pytest.mark.parametrize("method", sorted(REFUSED))
def test_a_claim_about_the_whole_part_refuses_a_region(method: str):
    with pytest.raises(ValueError, match=rf"{method}: .*body@sw.*not accepted"):
        REFUSED[method](_table())


KNOWN = [("plate", "body@sw", "rests on it")]
SUPPRESSED = [("plate", "body@sw")]
GROUP_OPTIONS: dict[str, Callable[[Assembly], Assembly]] = {
    "between/known_overlaps": lambda a: a.assert_no_interference_between(
        ["plate"], ["body"], known_overlaps=KNOWN
    ),
    "between/suppressed": lambda a: a.assert_no_interference_between(
        ["plate"], ["body"], suppressed=SUPPRESSED
    ),
    "within/known_overlaps": lambda a: a.assert_no_interference_within(
        ["plate", "body"], known_overlaps=KNOWN
    ),
    "within/suppressed": lambda a: a.assert_no_interference_within(
        ["plate", "body"], suppressed=SUPPRESSED
    ),
}


@pytest.mark.parametrize("case", sorted(GROUP_OPTIONS))
def test_a_group_option_refuses_a_region(case: str):
    form = case.split("/")[0]
    with pytest.raises(ValueError, match=rf"assert_no_interference_{form}: .*body@sw"):
        GROUP_OPTIONS[case](_table())


def test_a_group_selector_refuses_a_region():
    top = Assembly().with_subassembly("t", _table())
    with pytest.raises(ValueError, match="assert_no_interference_within: .*t@sw"):
        top.assert_no_interference_within("t@sw")


def test_a_pair_claim_cannot_be_built_with_a_region_by_hand():
    with pytest.raises(ValueError, match="assert_no_interference: .*not accepted"):
        NoInterference(a="plate", b="body@sw", name="by_hand")


def test_no_region_reaches_the_contact_grouping():
    """The contact grouping keys on part pairs; every claim that takes a
    region reports the bare part there."""
    pair = (
        _drilled()
        .with_region("far", "tip", Box(1, 1, 1))
        .assert_tangent_contact("far", "box@plug")
        .assert_distance("far@tip", "box", min_mm=0)
        .assert_within("box@plug", "far", along="Z")
    )
    a = _clear_of(
        pair, ["far@tip", "box"], Pos(0, 0, 90) * ROD, "r", excluding=["box@plug"]
    )
    top = Assembly().with_subassembly("t", a)
    refs = {
        ref
        for claim in top.all_assertions
        if isinstance(claim, Measuring)
        for ref in claim.part_refs
    }
    assert len(top.all_assertions) == 4
    assert refs == {"t.far", "t.box"}


# --- declaring a region ----------------------------------------------------


def test_a_region_is_not_a_part():
    bare = Assembly().with_part("body", _body())
    with_regions = _table()
    assert [p.name for p in with_regions.placed_parts] == ["body", "plate"]
    assert len(with_regions.compound.solids()) == 2
    assert with_regions.part("body").part is with_regions.parts[0].part
    assert [r.name for r in with_regions.part("body").regions] == list(POSTS)
    assert bare.part("body").regions == ()


def test_a_region_name_is_one_segment_and_unique_on_its_part():
    with pytest.raises(ValueError, match="duplicate region name 'sw' on 'body'"):
        _table().with_region("body", "sw", MISS)
    for bad in ("a.b", "a@b", ""):
        with pytest.raises(ValueError, match="region name"):
            _table().with_region("body", bad, MISS)
    # the same name on another part is another region
    assert _table().with_region("plate", "sw", MISS).part("plate").regions


def test_a_region_needs_its_part():
    with pytest.raises(KeyError, match="no part named 'bdoy'"):
        _table().with_region("bdoy", "x", MISS)


@pytest.mark.parametrize("operand", ["body@", "@sw", "body@sw@x", "body@s.w"])
def test_a_malformed_region_operand_is_refused(operand: str):
    with pytest.raises(ValueError, match="<part path>@<region name>"):
        _table().assert_tangent_contact("plate", operand)


def test_an_undeclared_region_is_caught_where_it_is_asserted():
    with pytest.raises(
        KeyError, match="no region named 'ws' on 'body'.*ne, nw, se, sw"
    ):
        _table().assert_tangent_contact("plate", "body@ws")
    with pytest.raises(KeyError, match="no region named 'ws' on 'body'"):
        _clear_of(_table(), "plate", _zone(), "z", excluding=["body@ws"])


def test_a_region_on_a_subassembly_is_refused():
    top = Assembly().with_subassembly("t", _table())
    with pytest.raises(ValueError, match="'t' is a sub-assembly"):
        _clear_of(top, "t@sw", _zone(), "z")


def test_part_and_subassembly_names_cannot_hold_the_separator():
    with pytest.raises(ValueError, match="'a@b' contains '@'"):
        Assembly().with_part("a@b", Box(1, 1, 1))
    with pytest.raises(ValueError, match="'a@b' contains '@'"):
        Assembly().with_subassembly("a@b", Assembly())


def test_a_region_on_an_absent_part_skips_like_any_absent_part():
    result = _one(_table().assert_tangent_contact("plate", "bracket@lug"))
    assert result.passed is None
    assert result.skipped == "absent_part"
    assert "bracket" in _detail(result) and "bracket@lug" not in _detail(result)


def test_a_region_missing_from_a_part_added_later_fails_the_claim():
    """Declared while the part was absent, so nothing could check the
    region then; the part arrives without it."""
    a = _table().assert_tangent_contact("plate", "bracket@lug")
    bracket = DetailOverride(part=Box(2, 2, 2), location=Location((0, 0, 30)))
    result = _one(a.with_detailed_geometry({"bracket": bracket}))
    assert result.passed is False
    assert result.skipped is None
    assert result.detail == "bracket has no region named 'lug' (declared: none)"


# --- through the tree ------------------------------------------------------


def test_a_units_region_claim_qualifies_into_its_parent():
    unit = _table().assert_tangent_contact("plate", "body@ne")
    top = Assembly().with_subassembly("t", unit, location=Location((5, 6, 7)))
    result = _one(top)
    assert result.name == "t.tangent_contact:plate/body@ne"
    assert result.passed is False
    assert _close(result.value, SHORT)
    assert _detail(result).endswith(
        f"t.body@ne: 147.2000mm^3 of t.body's {BODY_MM3:.4f}mm^3"
    )


def test_a_region_is_in_its_parts_own_frame():
    """The part is placed turned and shifted; the region, written where
    the builder drew the post, still holds the post."""
    placed = Location((100, -40, 7), (0, 0, 1), 37.0)
    a = (
        Assembly()
        .with_part("body", _body(), location=placed)
        .with_part("plate", Box(40, 40, 2), location=placed * Location((0, 0, 13)))
        .with_region("body", "ne", _post_box(1, 1))
        .assert_tangent_contact("plate", "body@ne")
    )
    result = _one(a)
    assert _close(result.value, SHORT)
    assert "body@ne: 147.2000mm^3" in _detail(result)


def test_a_parent_declares_a_region_on_a_part_below_it_by_path():
    top = (
        Assembly()
        .with_subassembly("t", Assembly().with_part("body", _body()))
        .with_part("plate", Box(40, 40, 2), location=Location((0, 0, 13)))
        .with_region("t.body", "ne", _post_box(1, 1))
        .assert_tangent_contact("plate", "t.body@ne")
    )
    assert _close(_one(top).value, SHORT)
    with pytest.raises(KeyError, match="no sub-assembly named 'u'"):
        top.with_region("u.body", "x", MISS)
    with pytest.raises(ValueError, match="duplicate region name 'ne' on 'body'"):
        top.with_region("t.body", "ne", MISS)


def test_a_phased_region_claim_carries_both_in_its_name():
    arm = Assembly().with_part("tip", Box(2, 2, 2))
    a = (
        _table()
        .with_subassembly("swing", arm, joint=RevoluteJoint(axis=Axis.Z))
        .assert_tangent_contact(
            "plate", "body@sw", during=JointWindow("swing", 0.0, 10.0)
        )
    )
    result = _one(a)
    assert result.name == "tangent_contact:plate/body@sw@swing [0, 10]deg"
    assert result.passed


# --- held over a motion ----------------------------------------------------


def _nub_arm() -> Part:
    """A bar along +X from the pivot with a nub halfway along its -Y
    side, so the bar's tip, not the nub, is what swings nearest the
    post."""
    return _fused([Pos(20, 0, 0) * Box(40, 4, 4), Pos(20, -4, 0) * Box(4, 4, 4)])


NUB = Pos(20, -4.5, 0) * Box(6, 4, 6)  # the nub from y = -2.5 out: 4 * 3.5 * 4
ANGLES = tuple(range(0, 91, 15))


def _swung() -> Assembly:
    arm = Assembly().with_part("arm", _nub_arm(), location=Location((2, 0, 0)))
    arm = arm.with_region("arm", "nub", NUB)
    return (
        Assembly()
        .with_part("post", Sphere(3), location=Location((0, 60, 0)))
        .with_subassembly(
            "swing", arm, location=Location((0, 0, 5)), joint=RevoluteJoint(axis=Axis.Z)
        )
        .with_motion(Motion.over_joint("swing_in", "swing", 0.0, 90.0, 15.0))
    )


def _by_hand(angle: float) -> float:
    """The nub cut out of the arm in the arm's frame, then placed where
    the tree puts the arm at ``angle``."""
    nub = _nub_arm() & NUB
    where = (
        Location((0, 0, 5))
        * Location((0, 0, 0), (0, 0, 1), angle)
        * Location((2, 0, 0))
    )
    post = Pos(0, 60, 0) * Sphere(3)
    # build123d leaves Shape's type parameter unbound in this signature
    return nub.moved(where).distance_to(post)  # pyright: ignore[reportUnknownMemberType]


def test_a_region_under_a_joint_reads_as_the_hand_built_cut_at_every_pose():
    a = _swung().assert_distance("swing.arm@nub", "post", min_mm=0)
    by_hand = [_by_hand(angle) for angle in ANGLES]
    for angle, expected in zip(ANGLES, by_hand, strict=True):
        posed = _one(a.with_joint_angle("swing", float(angle)))
        assert _close(posed.value, expected)
    (result,) = hold(a).assertions
    assert _close(result.value, min(by_hand))
    assert _poses(result).distinct == len(ANGLES)
    assert result.worst_at is not None
    assert _close(result.worst_at.joints_deg["swing"], 90.0)
    assert "swing.arm@nub: 56.0000mm^3 of swing.arm's 704.0000mm^3" in _detail(result)
    # the whole arm reads nearer at the worst pose: the claim is the nub's
    (whole,) = hold(_swung().assert_distance("swing.arm", "post", min_mm=0)).assertions
    assert whole.value is not None and result.value is not None
    assert whole.value < result.value - 10.0


def test_held_evaluation_cuts_a_region_once_not_once_per_pose(
    monkeypatch: pytest.MonkeyPatch,
):
    cuts: list[bool] = []
    real = assertions._boolean  # pyright: ignore[reportPrivateUsage] — the one boolean

    def counted(
        part: Part, tools: tuple[Compound | Solid, ...], inside: bool
    ) -> list[Solid]:
        cuts.append(inside)
        return real(part, tools, inside)

    monkeypatch.setattr(assertions, "_boolean", counted)
    read = _swung().assert_distance("swing.arm@nub", "post", min_mm=0)
    near = _clear_of(read, "swing.arm@nub", Pos(0, 60, 0) * Box(2, 2, 2), "zone")
    far = Pos(0, 80, 0) * Box(2, 2, 2)
    a = _clear_of(near, "swing.arm", far, "far", excluding=["swing.arm@nub"])
    held = hold(a).assertions
    assert [_poses(r).distinct for r in held] == [len(ANGLES)] * 3
    assert cuts == [True, False]  # one intersection shared, one subtraction


def test_one_solid_declared_on_two_parts_is_cut_from_each():
    """One solid object is the region of two parts in one run: a full
    table and one whose ne post is short. Each claim reads its own
    part's post."""
    shared = _post_box(1, 1)
    a = (
        Assembly()
        .with_part("full", _body(0.0))
        .with_part("short", _body())
        .with_part("plate", Box(40, 40, 2), location=Location((0, 0, 13)))
        .with_region("full", "ne", shared)
        .with_region("short", "ne", shared)
        .assert_distance("plate", "full@ne", min_mm=0)
        .assert_distance("plate", "short@ne", min_mm=0)
    )
    full, short = hold(a).assertions
    assert _close(full.value, 0.0) and _close(short.value, SHORT)
    assert "full@ne: 152.0000mm^3" in _detail(full)
    assert "short@ne: 147.2000mm^3" in _detail(short)


def test_a_failing_pose_of_a_region_claim_is_reported_over_the_motion():
    by_hand = [_by_hand(angle) for angle in ANGLES]
    limit = (min(by_hand) + max(by_hand)) / 2
    a = _swung().assert_distance("swing.arm@nub", "post", min_mm=limit)
    (result,) = hold(a).assertions
    assert result.passed is False
    assert _poses(result).failed == sum(d < limit for d in by_hand)
    assert 0 < _poses(result).failed < len(ANGLES)


# --- detail geometry swapped under a region --------------------------------


def test_a_region_is_cut_from_the_geometry_the_claim_runs_on():
    """The base model's ne post is short; the detail body's is full
    height. The region stays, and reads whichever body is in the run."""
    a = _table().assert_tangent_contact("plate", "body@ne")
    base, detailed = hold(a), hold(a.with_detailed_geometry({"body": _body(0.0)}))
    assert base.assertions[0].passed is False
    assert _close(base.assertions[0].value, SHORT)
    assert detailed.assertions[0].passed
    assert _close(detailed.assertions[0].value, 0.0)
    assert "body@ne: 152.0000mm^3" in _detail(detailed.assertions[0])


def test_a_detail_body_that_loses_the_feature_empties_its_region():
    a = _table().assert_tangent_contact("plate", "body@ne")
    flat = _fused([Pos(0, 0, 1) * Box(40, 40, 2)])
    result = _one(a.with_detailed_geometry({"body": flat}))
    assert result.passed is False
    assert "region body@ne holds no material of body" in _detail(result)
