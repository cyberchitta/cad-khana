"""The default rig's key, read off rendered pixels.

Needs ``bpy``; the bpy-free render tests are in ``test_smoke.py``.
"""

from dataclasses import replace
from pathlib import Path

import pytest
from build123d import Box, Location
from PIL import Image

from cad_khana.render import lighting
from cad_khana.render.render import render
from cad_khana.render.scene import PlacedPart, Scene

pytest.importorskip("bpy")

Y_UP = (0.0, 1.0, 0.0)
Z_UP = (0.0, 0.0, 1.0)
UNLIT = replace(lighting.DEFAULT, key=None)
CLIPPED = 250


def _rgb(
    tmp_path: Path, rig: lighting.StudioRig, up: tuple[float, float, float]
) -> bytes:
    scene = Scene(
        parts=(
            PlacedPart(
                "box",
                Box(40, 40, 40),
                Location((0, 0, 0)),
                "pla_matte",
                (0.8, 0.1, 0.1),
            ),
        )
    )
    (png,) = render(
        scene, out=tmp_path, resolution=(96, 54), samples=8, rig=rig, world_up=up
    )
    with Image.open(png) as image:
        return image.convert("RGB").tobytes()


@pytest.mark.parametrize("up", [Y_UP, Z_UP])
def test_default_key_lights_a_visible_face_without_clipping_it(
    tmp_path: Path, up: tuple[float, float, float]
):
    lit = _rgb(tmp_path / "lit", lighting.DEFAULT, up)
    unlit = _rgb(tmp_path / "unlit", UNLIT, up)
    assert max(lit[0::3]) > max(unlit[0::3]) + 20
    assert not [i for i in range(0, len(lit), 3) if min(lit[i : i + 3]) >= CLIPPED]
