from pathlib import Path

from build123d import Box, BuildPart, Location

from cad_khana.core.assembly import Assembly
from cad_khana.core.build import build


def _cube(size: float = 10):
    with BuildPart() as p:
        Box(size, size, size)
    return p.part


def test_build_writes_stl_and_step(tmp_path: Path):
    assembly = (
        Assembly()
        .add("housing", _cube(20))
        .add("lid", _cube(20), location=Location((0, 0, 25)))
    )
    result = build(assembly, out=tmp_path)
    names = sorted(path.name for path in result.exports)
    assert names == ["assembly.step", "assembly.stl"]
    for path in result.exports:
        assert path.exists()
        assert path.stat().st_size > 0


def test_build_creates_missing_out_directory(tmp_path: Path):
    target = tmp_path / "nested" / "outputs"
    build(Assembly().add("a", _cube()), out=target)
    assert target.is_dir()
