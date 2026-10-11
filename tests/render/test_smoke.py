"""Smoke tests that don't require booting Blender.

These exercise the `bpy`-free modules: scene composition, material
table lookup, framing strategy math, and tessellation defaults. The
actual ``render()`` path needs `bpy` and is exercised manually via
``khana run`` on a render script.
"""

from __future__ import annotations

from pathlib import Path

from build123d import Box, Location

from cad_khana.render import camera, framing, lighting, materials
from cad_khana.render.scene import Scene


def test_scene_add_is_immutable():
    s0 = Scene()
    s1 = s0.add("a", Box(10, 10, 10))
    assert s0.parts == ()
    assert len(s1.parts) == 1
    assert s1.parts[0].name == "a"
    assert s1.parts[0].material == "pla_matte"


def test_scene_with_materials_overrides():
    s = (
        Scene()
        .add("a", Box(10, 10, 10), material="pla_matte")
        .add("b", Box(5, 5, 5), material="pla_matte")
        .with_materials({"a": "steel"})
    )
    by_name = {p.name: p.material for p in s.parts}
    assert by_name == {"a": "steel", "b": "pla_matte"}


def test_scene_add_carries_location_and_color():
    loc = Location((1, 2, 3))
    s = Scene().add("a", Box(1, 1, 1), location=loc, color=(0.1, 0.2, 0.3))
    p = s.parts[0]
    assert p.location == loc
    assert p.color == (0.1, 0.2, 0.3)


def test_materials_lookup_known():
    r = materials.get("steel")
    assert r.metallic == 1.0
    assert r.color_overridable is False
    assert r.material == "steel"
    assert r.finish == "default"


def test_materials_split_material_and_finish():
    pla_matte = materials.get("pla_matte")
    pla_glossy = materials.get("pla_glossy")
    assert pla_matte.material == pla_glossy.material == "pla"
    assert pla_matte.finish == "matte"
    assert pla_glossy.finish == "glossy"
    # Same material, different finish → same base_color, different roughness.
    assert pla_matte.base_color == pla_glossy.base_color
    assert pla_matte.roughness != pla_glossy.roughness


def test_materials_lookup_unknown_lists_known():
    try:
        materials.get("not_a_material")
    except KeyError as exc:
        assert "steel" in str(exc)
    else:
        raise AssertionError("expected KeyError")


def test_hero_3q_centers_target_on_bbox():
    bbox = camera.BBox(min=(-10, -10, 0), max=(10, 10, 20))
    configs = framing.HERO_3Q.frames(bbox, aspect=16 / 9, world_up=(0, 1, 0))
    assert len(configs) == 1
    cfg = configs[0]
    assert cfg.target == (0.0, 0.0, 10.0)
    assert cfg.location != cfg.target
    assert cfg.perspective is True
    assert cfg.vertical_fov_deg == 35.0
    assert cfg.ortho_scale is None


def test_hero_3q_z_up_swaps_y_and_z_components():
    bbox = camera.BBox(min=(-10, -10, -10), max=(10, 10, 10))
    cfg_y = framing.HERO_3Q.frames(bbox, 16 / 9, world_up=(0, 1, 0))[0]
    cfg_z = framing.HERO_3Q.frames(bbox, 16 / 9, world_up=(0, 0, 1))[0]
    # Both target the bbox centre.
    assert cfg_y.target == (0.0, 0.0, 0.0)
    assert cfg_z.target == (0.0, 0.0, 0.0)
    # Z-up swaps the Y and Z components of the canonical direction, so
    # the camera location's Y and Z swap relative to Y-up.
    yx, yy, yz = cfg_y.location
    zx, zy, zz = cfg_z.location
    assert abs(zx - yx) < 1e-9
    assert abs(zy - yz) < 1e-9
    assert abs(zz - yy) < 1e-9


def test_fixed_pose_passes_through():
    bbox = camera.BBox(min=(-1, -1, -1), max=(1, 1, 1))
    pose = framing.FixedPose(
        location=(0, -200, 100),
        target=(0, 0, 0),
        vertical_fov_deg=82.0,
    )
    configs = pose.frames(bbox, 16 / 9, world_up=(0, 0, 1))
    assert len(configs) == 1
    cfg = configs[0]
    assert cfg.location == (0, -200, 100)
    assert cfg.target == (0, 0, 0)
    assert cfg.perspective is True
    assert cfg.vertical_fov_deg == 82.0
    assert cfg.ortho_scale is None


def test_fixed_pose_orthographic():
    bbox = camera.BBox(min=(-1, -1, -1), max=(1, 1, 1))
    pose = framing.FixedPose(
        location=(0, -200, 0),
        target=(0, 0, 0),
        ortho_scale=50.0,
    )
    cfg = pose.frames(bbox, 16 / 9, world_up=(0, 0, 1))[0]
    assert cfg.perspective is False
    assert cfg.vertical_fov_deg is None
    assert cfg.ortho_scale == 50.0


def test_six_ortho_emits_six_frames():
    bbox = camera.BBox(min=(-10, -5, -2), max=(10, 5, 2))
    configs = framing.ORTHO_SIX.frames(bbox, 16 / 9, world_up=(0, 0, 1))
    assert len(configs) == 6
    assert all(cfg.perspective is False for cfg in configs)
    assert all(cfg.ortho_scale is not None and cfg.ortho_scale > 0 for cfg in configs)


def test_default_rig_is_flat_color_no_hdri():
    rig = lighting.DEFAULT
    assert rig.world_hdri is None
    assert rig.key is not None


def test_default_hdri_rig_names_bundled_studio():
    rig = lighting.DEFAULT_HDRI
    assert rig.world_hdri == "studio"
    assert rig.world_hdri in lighting.BUNDLED_HDRI_NAMES
    assert rig.world_hdri_strength == 1.0


def test_resolve_hdri_path_passes_explicit_path_through():
    # An explicit Path is returned as-is; existence is not enforced.
    custom = Path("/tmp/nonexistent_custom.exr")
    assert lighting.resolve_hdri_path(custom) == custom


def test_resolve_hdri_path_treats_unknown_string_as_path():
    # Unknown strings fall through to Path() rather than raising —
    # callers handle missing-file errors at render time.
    out = lighting.resolve_hdri_path("/some/local/file.exr")
    assert isinstance(out, Path)
    assert str(out) == "/some/local/file.exr"


def test_turntable_24_emits_24_frames_at_one_radius():
    bbox = camera.BBox(min=(-10, -10, 0), max=(10, 10, 20))
    configs = framing.TURNTABLE_24.frames(bbox, 16 / 9, world_up=(0, 0, 1))
    assert len(configs) == 24
    target = (0.0, 0.0, 10.0)
    radii = [
        (
            (c.location[0] - target[0]) ** 2
            + (c.location[1] - target[1]) ** 2
            + (c.location[2] - target[2]) ** 2
        )
        ** 0.5
        for c in configs
    ]
    assert all(abs(r - radii[0]) < 1e-6 for r in radii)
