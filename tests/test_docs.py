"""Schema facts documented for agents stay in step with the code.

``SKILL.md`` §JSON diagnostics essentials is the single place field
meanings are written down; ``CLAUDE.md`` carries only the schema version
and the maintainer's delta. These tests derive each enumerable fact from
the code and fail when the documentation omits one — the drift that
survived three schema bumps before ``55fab5a`` caught it by eye.
"""

import inspect
import re
from pathlib import Path

import pytest
from build123d import Box, BuildPart, Location

from cad_khana.mechanism.assembly import Assembly
from cad_khana.mechanism.assertions import evaluate
from cad_khana.mechanism.diagnostics import SCHEMA_VERSION, SKIP_CLASSES

ROOT = Path(__file__).parent.parent
CLAUDE = (ROOT / "CLAUDE.md").read_text()
SKILL = (ROOT / "skills/cad-khana/SKILL.md").read_text()
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
CLAIMS = {
    "assert_no_interference": lambda x: x.assert_no_interference("a", "b"),
    "assert_distance": lambda x: x.assert_distance("a", "b", min_mm=0.0),
    "assert_scalar": lambda x: x.assert_scalar("s", 1.0),
    "assert_solid_count": lambda x: x.assert_solid_count("a"),
    "assert_tangent_contact": lambda x: x.assert_tangent_contact("a", "b"),
    "assert_allowed_contact": lambda x: x.assert_allowed_contact(
        "a", "b", max_overlap_mm3=1.0
    ),
    "assert_interference": lambda x: x.assert_interference("a", "b"),
    "assert_anchors_coincident": lambda x: x.assert_anchors_coincident("p", "q"),
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
    start = SKILL.index("- `assertions` — one entry per declared assertion")
    return SKILL[start : SKILL.index("\n- `", start + 1)]


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
def test_skill_documents_every_claim_method(method: str):
    assert f"{method}(" in SKILL


@pytest.mark.parametrize("method", sorted(set(CLAIMS) - GROUP_FORMS))
def test_value_bullet_names_every_claim_kind_on_the_right_side(method: str):
    bullet = _value_bullet()
    boolean_only = bullet.index("`null` for the boolean-only kinds")
    at = bullet.find(f"`{method}`")
    assert at != -1, f"{method} missing from SKILL.md's `value` bullet"
    assert (at < boolean_only) == _records_value(method), (
        f"{method} is listed on the wrong side of the value/boolean split"
    )


@pytest.mark.parametrize("method", sorted(GROUP_FORMS))
def test_group_forms_record_no_value(method: str):
    assert not _records_value(method)


@pytest.mark.parametrize("kind", sorted(_warning_kinds()))
def test_skill_documents_every_warning_kind(kind: str):
    assert f"`{kind}`" in SKILL


@pytest.mark.parametrize("cls", SKIP_CLASSES)
def test_skill_documents_every_skip_class(cls: str):
    assert f'`"{cls}"`' in SKILL


def test_warning_kinds_are_found_at_all():
    assert {"multi_solid", "stale_waiver", "motion_moved_nothing"} <= _warning_kinds()


@pytest.mark.parametrize("doc", [CLAUDE, SKILL], ids=["CLAUDE.md", "SKILL.md"])
def test_documented_schema_version_is_current(doc: str):
    stated = set(re.findall(r'"schema_version": "([\d.]+)"', doc)) | set(
        re.findall(r"schemas? \(v([\d.]+)\)", doc)
    )
    assert stated <= {SCHEMA_VERSION}
