"""``bpy`` is an optional extra: importing the package never loads it.

Each case runs in a fresh interpreter, because ``sys.modules`` in the
test process already holds whatever an earlier test imported.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RENDER = Path(__file__).parents[2] / "src/cad_khana/render"
RENDER_MODULES = (
    "cad_khana.render",
    *(f"cad_khana.render.{p.stem}" for p in sorted(RENDER.glob("[!_]*.py"))),
)


@pytest.mark.parametrize("module", ("cad_khana.cli", *RENDER_MODULES))
def test_import_does_not_load_bpy(module: str):
    probe = f"import sys, {module}; sys.exit('bpy' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", probe], check=False).returncode == 0


def test_render_modules_are_found_at_all():
    assert "cad_khana.render.render" in RENDER_MODULES
