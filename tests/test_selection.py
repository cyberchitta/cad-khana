import pytest

from cad_khana.selection import SelectionError, claims, paths

NAMES = ("frame", "s1.hub", "s1.arm.tip", "s1.arm.root", "s2.hub")


# --- claims: fnmatch globs over assertion names ---------------------------


def test_claims_keeps_names_matching_any_glob():
    names = ("clear_of:a", "clear_of:b", "distance:a/b>=0.2")
    assert claims(names, ("clear_of:*",)) == (True, True, False)
    assert claims(names, ("clear_of:a", "distance:*")) == (True, False, True)


def test_claims_globs_reach_a_region_operand_in_a_name():
    names = (
        "tangent_contact:plate/body",
        "tangent_contact:plate/body@sw",
        "u.within:ring/spider@seat@Z",
        "no_interference:a/b@swing [0, 10]deg",
    )
    assert claims(names, ("*body@sw",)) == (False, True, False, False)
    assert claims(names, ("*@seat@*",)) == (False, False, True, False)
    assert claims(names, ("tangent_contact:plate/body",)) == (True, False, False, False)
    with pytest.raises(SelectionError, match="'\\*body@ws'"):
        claims(names, ("*body@ws",))


def test_claims_is_case_sensitive():
    with pytest.raises(SelectionError):
        claims(("Clear",), ("clear",))


def test_claims_glob_matching_nothing_is_an_error_naming_it():
    """A typo'd glob that evaluates zero claims and exits 0 is the
    vacuous green — so every glob must match something, not just one."""
    with pytest.raises(SelectionError, match="'clera_of:\\*'"):
        claims(("clear_of:a",), ("clear_of:*", "clera_of:*"))


def test_claims_glob_missing_the_kind_prefix_names_the_claim():
    """The sorted-studs typo: the declared name without its kind prefix.
    Names containing the glob's literal core are the near matches."""
    names = ("clear_of:base_fall_path>=1", "clear_of:tray>=0.5", "distance:a/b>=0.2")
    with pytest.raises(
        SelectionError,
        match="'base_fall_path\\*' — close: clear_of:base_fall_path>=1 \\(of 3",
    ):
        claims(names, ("base_fall_path*",))


def test_claims_misspelled_glob_names_close_matches():
    with pytest.raises(SelectionError, match="'clera_of:a\\*'.*close: clear_of:a"):
        claims(("clear_of:a", "distance:a/b>=0.2"), ("clera_of:a*",))


def test_claims_near_matches_are_capped_with_a_count():
    names = tuple(f"clear_of:pin_{i}>=1" for i in range(5))
    with pytest.raises(
        SelectionError, match="close: .*_0.*_1.*_2.*\\(5 contain 'pin_'\\)"
    ):
        claims(names, ("pin_*",))


# --- paths: dotted part / sub-assembly paths ------------------------------


def test_only_keeps_a_subtree():
    assert paths(NAMES, only=("s1",)) == ("s1.hub", "s1.arm.tip", "s1.arm.root")


def test_only_is_a_path_not_a_prefix():
    assert paths(("s1.hub", "s10.hub"), only=("s1",)) == ("s1.hub",)


def test_only_accepts_a_leaf_and_a_nested_group():
    assert paths(NAMES, only=("frame", "s1.arm")) == (
        "frame",
        "s1.arm.tip",
        "s1.arm.root",
    )


def test_hide_drops_a_subtree_after_only():
    assert paths(NAMES, only=("s1",), hide=("s1.arm",)) == ("s1.hub",)
    assert paths(NAMES, hide=("s1", "s2")) == ("frame",)


def test_no_selection_keeps_everything():
    assert paths(NAMES) == NAMES


def test_unknown_path_is_an_error_with_close_matches():
    with pytest.raises(SelectionError, match="'s1.arn'.*s1.arm"):
        paths(NAMES, hide=("s1.arn",))


def test_selecting_nothing_is_an_error():
    with pytest.raises(SelectionError, match="nothing"):
        paths(NAMES, only=("s1",), hide=("s1",))
