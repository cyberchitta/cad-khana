"""Schema facts documented for agents stay in step with the code.

Each fact has one home and is checked there, not in the skill's files
concatenated — a fact mentioned in passing elsewhere must not satisfy a
home that dropped it. Field meanings live in ``references/diagnostics.md``;
every warning kind is named in ``SKILL.md`` itself, because a warning
never fails a run and an agent that doesn't know the kind won't load a
reference to find it; the claim catalogue lives in
``references/assertions.md``; every name a script calls sits in
``SKILL.md``'s reference table, beside the file that documents it. ``CLAUDE.md`` carries only the schema
version and the maintainer's delta. These tests derive each enumerable
fact from the code and fail when its home omits one — the drift that
survived three schema bumps before ``55fab5a`` caught it by eye.
"""

import importlib
import inspect
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from build123d import Box, BuildPart, Location

from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.assertions import evaluate
from cad_khana.mechanism.diagnostics import SCHEMA_VERSION, SKIP_CLASSES

ROOT = Path(__file__).parent.parent
CLAUDE = (ROOT / "CLAUDE.md").read_text()
SKILL_DIR = ROOT / "skills/cad-khana"
SKILL = (SKILL_DIR / "SKILL.md").read_text()
DIAGNOSTICS = (SKILL_DIR / "references/diagnostics.md").read_text()
ASSERTIONS = (SKILL_DIR / "references/assertions.md").read_text()
SRC = ROOT / "src/cad_khana"

WARNING_KIND = re.compile(
    r'"kind": "(\w+)"|WarningEntry\(\s*"(\w+)"|kind: str = "(\w+)"'
)


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def _pair() -> Assembly:
    return (
        Assembly()
        .with_part("a", _cube(), location=Location((0, 0, 0)))
        .with_part("b", _cube(), location=Location((10, 0, 0)))
        .with_anchor("p", Location((0, 0, 0)))
        .with_anchor("q", Location((0, 0, 0)))
    )


# One call per public claim method: a new ``assert_*`` must be added here,
# which is what makes the value enumeration below complete.
CLAIMS: dict[str, Callable[[Assembly], Assembly]] = {
    "assert_no_interference": lambda x: x.assert_no_interference("a", "b"),
    "assert_distance": lambda x: x.assert_distance("a", "b", min_mm=0.0),
    "assert_clear_of": lambda x: x.assert_clear_of("a", Box(10, 10, 10), name="k"),
    "assert_scalar": lambda x: x.assert_scalar("s", 1.0),
    "assert_solid_count": lambda x: x.assert_solid_count("a"),
    "assert_tangent_contact": lambda x: x.assert_tangent_contact("a", "b"),
    "assert_allowed_contact": lambda x: x.assert_allowed_contact(
        "a", "b", max_overlap_mm3=1.0
    ),
    "assert_interference": lambda x: x.assert_interference("a", "b"),
    "assert_anchors_coincident": lambda x: x.assert_anchors_coincident("p", "q"),
    "assert_within": lambda x: x.assert_within("a", "b", along="Z"),
    "assert_no_interference_between": lambda x: x.assert_no_interference_between(
        ("a",), ("b",)
    ),
    "assert_no_interference_within": lambda x: x.assert_no_interference_within(
        ("a", "b")
    ),
}

GROUP_FORMS = {"assert_no_interference_between", "assert_no_interference_within"}


def _records_value(method: str) -> bool:
    (result,) = evaluate(CLAIMS[method](_pair()))
    return result.value is not None


def _value_bullet() -> str:
    start = DIAGNOSTICS.index("- `assertions` — one entry per declared assertion")
    return DIAGNOSTICS[start : DIAGNOSTICS.index("\n- `", start + 1)]


def _warning_kinds() -> set[str]:
    """Every ``kind`` literal in the source, less the printability file's
    own ``kind``, which shares the field name."""
    return {
        next(g for g in m.groups() if g)
        for path in SRC.rglob("*.py")
        for m in WARNING_KIND.finditer(path.read_text())
    } - {"printability"}


def test_every_public_claim_method_is_exercised_here():
    public = {n for n, _ in inspect.getmembers(Assembly) if n.startswith("assert_")}
    assert public == set(CLAIMS)


@pytest.mark.parametrize("method", sorted(CLAIMS))
def test_assertions_reference_documents_every_claim_method(method: str):
    assert f"{method}(" in ASSERTIONS


@pytest.mark.parametrize("method", sorted(set(CLAIMS) - GROUP_FORMS))
def test_value_bullet_names_every_claim_kind_on_the_right_side(method: str):
    bullet = _value_bullet()
    boolean_only = bullet.index("`null` for the boolean-only kinds")
    at = bullet.find(f"`{method}`")
    assert at != -1, f"{method} missing from diagnostics.md's `value` bullet"
    assert (at < boolean_only) == _records_value(method), (
        f"{method} is listed on the wrong side of the value/boolean split"
    )


def _measured_bullet() -> str:
    start = DIAGNOSTICS.index("- `assertions[].measured`")
    return DIAGNOSTICS[start : DIAGNOSTICS.index("\n- `", start + 1)]


@pytest.mark.parametrize("method", sorted(CLAIMS))
def test_measured_bullet_names_exactly_the_kinds_that_record_a_count(method: str):
    (result,) = evaluate(CLAIMS[method](_pair()))
    assert (f"`{method}`" in _measured_bullet()) == (result.measured is not None)


def _witness_bullet() -> str:
    start = DIAGNOSTICS.index("- `assertions[].witness_mm`")
    return DIAGNOSTICS[start : DIAGNOSTICS.index("\n- `", start + 1)]


@pytest.mark.parametrize("method", sorted(CLAIMS))
def test_witness_bullet_names_exactly_the_kinds_that_record_points(method: str):
    (result,) = evaluate(CLAIMS[method](_pair()))
    assert (f"`{method}`" in _witness_bullet()) == (result.witness_mm is not None)


@pytest.mark.parametrize("method", sorted(GROUP_FORMS))
def test_group_forms_record_no_value(method: str):
    assert not _records_value(method)


@pytest.mark.parametrize("kind", sorted(_warning_kinds()))
def test_skill_documents_every_warning_kind(kind: str):
    assert f"`{kind}`" in SKILL


@pytest.mark.parametrize("cls", SKIP_CLASSES)
def test_diagnostics_reference_documents_every_skip_class(cls: str):
    assert f'`"{cls}"`' in DIAGNOSTICS


def test_warning_kinds_are_found_at_all():
    assert {"multi_solid", "stale_waiver", "motion_moved_nothing"} <= _warning_kinds()


@pytest.mark.parametrize(
    "doc",
    [CLAUDE, SKILL, DIAGNOSTICS],
    ids=["CLAUDE.md", "SKILL.md", "diagnostics.md"],
)
def test_documented_schema_version_is_current(doc: str):
    stated = set(re.findall(r'"schema_version": "([\d.]+)"', doc)) | set(
        re.findall(r"schemas? \(v([\d.]+)\)", doc)
    )
    assert stated <= {SCHEMA_VERSION}


# The library surface a script calls, derived from the code: every
# ``with_*`` builder, plus each script-facing module's public functions
# and classes. Machinery a script never calls (``joint_angles``,
# ``compound``, the result dataclasses) is out of scope.
SCRIPT_MODULES = {
    "cad_khana.mechanism.motion": ("Motion",),
    "cad_khana.mechanism.keepout": ("swept",),
    "cad_khana.mechanism.sweep": (
        "sweep",
        "over_joint",
        "over_motion",
        "classify",
        "onset",
    ),
    "cad_khana.printability.inspect": ("inspect",),
    "cad_khana.printability.methods": ("FDM",),
    "cad_khana.printability.waiver": ("Waiver",),
    "cad_khana.printability.feature": ("Feature",),
    "cad_khana.export": ("export_assembly", "export_glb", "export_animated_glb"),
}
SURFACE_ROW = re.compile(r"^\| `(references/[\w./]+)` \| .* \| (.*) \|$", re.M)


def _surface_rows() -> dict[str, set[str]]:
    section = SKILL.split("## Reference files", 1)[1].split("\n## ", 1)[0]
    return {
        ref: set(re.findall(r"`(\w+)", names))
        for ref, names in SURFACE_ROW.findall(section)
    }


def test_every_builder_and_script_name_is_on_the_skill_index():
    listed = set().union(*_surface_rows().values())
    builders = {n for n in dir(Assembly) if n.startswith("with_")}
    named = {n for names in SCRIPT_MODULES.values() for n in names}
    stale = [
        (module, n)
        for module, names in SCRIPT_MODULES.items()
        for n in names
        if not hasattr(importlib.import_module(module), n)
    ]
    assert not stale, stale
    assert builders | named <= listed, sorted((builders | named) - listed)


def test_each_listed_name_is_documented_in_its_row_file():
    rows = _surface_rows()
    missing = [
        (ref, name)
        for ref, names in rows.items()
        for name in names - {"every"}
        if name not in (SKILL_DIR / ref).read_text()
    ]
    assert not missing, missing
