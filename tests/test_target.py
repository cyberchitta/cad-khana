from pathlib import Path

import pytest

from cad_khana.mechanism.assembly import Assembly
from cad_khana.target import Target, TargetError, factories, load, resolve


def _module(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def test_parse_plain_path():
    assert Target.parse("cad/unit/assembly.py") == Target(
        Path("cad/unit/assembly.py"), None
    )


def test_parse_named_factory():
    assert Target.parse("cad/unit/assembly.py:build_rotor") == Target(
        Path("cad/unit/assembly.py"), "build_rotor"
    )


def test_parse_leaves_a_non_identifier_suffix_in_the_path():
    """Only an identifier after the colon is a factory — a colon inside a
    path is not a member selector."""
    assert Target.parse("odd:name.py") == Target(Path("odd:name.py"), None)


def test_default_out_for_a_units_assembly_module(tmp_path: Path):
    target = Target.parse(str(tmp_path / "assembly.py"))
    assert target.default_out == tmp_path / "outputs"


def test_default_out_for_a_co_located_target(tmp_path: Path):
    target = Target.parse(str(tmp_path / "check_cones.py"))
    assert target.default_out == tmp_path / "outputs" / "check_cones"


def test_default_out_separates_named_factories(tmp_path: Path):
    target = Target.parse(str(tmp_path / "assembly.py") + ":build_rotor")
    assert target.default_out == tmp_path / "outputs" / "assembly-build_rotor"


_FACTORY_MODULE = (
    "from __future__ import annotations\n"
    "\n"
    "from build123d import Box\n"
    "\n"
    "from cad_khana.mechanism.assembly import Assembly\n"
    "from cad_khana.mechanism.check import check\n"
    "\n"
    "\n"
    "def build_rotor(size: float = 10.0) -> Assembly:\n"
    "    return Assembly().with_part('rotor', Box(size, size, size))\n"
    "\n"
    "\n"
    "def _private() -> Assembly:\n"
    "    return Assembly()\n"
    "\n"
    "\n"
    "def describe() -> None:\n"
    "    return None\n"
)


def test_factories_finds_string_annotated_functions(tmp_path: Path):
    """``from __future__ import annotations`` makes every annotation a
    string; discovery has to survive that, since it is the error
    message that teaches an agent a module's members."""
    module = load(_module(tmp_path, "unit.py", _FACTORY_MODULE))
    assert factories(module) == ("build_rotor",)


def test_factories_ignores_imported_names(tmp_path: Path):
    """``check`` and ``Assembly`` are imported, not this module's surface."""
    module = load(_module(tmp_path, "unit.py", _FACTORY_MODULE))
    assert "check" not in factories(module)
    assert "Assembly" not in factories(module)


def test_resolve_calls_a_named_factory_with_its_defaults(tmp_path: Path):
    path = _module(tmp_path, "unit.py", _FACTORY_MODULE)
    assembly = resolve(Target(path, "build_rotor"))
    assert isinstance(assembly, Assembly)
    (placed,) = assembly.placed_parts
    assert placed.name == "rotor"
    assert placed.part.bounding_box().size.X == pytest.approx(10.0)


def test_resolve_accepts_the_degenerate_value(tmp_path: Path):
    path = _module(
        tmp_path,
        "unit.py",
        "from build123d import Box\n"
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "assembly = Assembly().with_part('cube', Box(1, 1, 1))\n",
    )
    assert isinstance(resolve(Target(path)), Assembly)


def test_resolve_rejects_a_named_non_callable(tmp_path: Path):
    """An explicit ``:factory`` must name a factory — the degenerate
    value form is only tolerated for the default member."""
    path = _module(
        tmp_path,
        "unit.py",
        "from cad_khana.mechanism.assembly import Assembly\n"
        "\n"
        "asm = Assembly()\n",
    )
    with pytest.raises(TargetError, match="not a factory"):
        resolve(Target(path, "asm"))
