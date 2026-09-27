import pytest

from cad_khana.selection import SelectionError, claims, paths

NAMES = ("frame", "s1.hub", "s1.arm.tip", "s1.arm.root", "s2.hub")


# --- claims: fnmatch globs over assertion names ---------------------------


def test_claims_keeps_names_matching_any_glob():
    names = ("clear_of:a", "clear_of:b", "distance:a/b>=0.2")
    assert claims(names, ("clear_of:*",)) == (True, True, False)
    assert claims(names, ("clear_of:a", "distance:*")) == (True, False, True)


def test_claims_is_case_sensitive():
    with pytest.raises(SelectionError):
        claims(("Clear",), ("clear",))


def test_claims_glob_matching_nothing_is_an_error_naming_it():
    """A typo'd glob that evaluates zero claims and exits 0 is the
    vacuous green — so every glob must match something, not just one."""
    with pytest.raises(SelectionError, match="'clera_of:\\*'"):
        claims(("clear_of:a",), ("clear_of:*", "clera_of:*"))


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
