"""Material table for the render layer.

Each entry describes a real-world material — today via Cycles
Principled BSDF parameters consumed by ``render.py``. Defining them as
plain data keeps this module ``bpy``-free, so it can be imported and
tested without booting Blender. Mechanical / dynamics facets (density,
modulus, friction) get added as new consumers (FEA, kinematics) appear.

Token naming: ``<material>`` for entries with one finish in this
catalog (e.g. ``steel``); ``<material>_<finish>`` when more than one
finish of the same underlying material is needed (e.g. ``pla_matte``,
``pla_glossy``). The ``material`` and ``finish`` fields on
``Material`` carry the structured split so a future non-render
consumer can look up by material alone (ignoring finish) or query
"all finishes of pla".

Adding a material: add an entry to ``MATERIALS``. Reference it from a
user script by name (string).
"""

from __future__ import annotations

from dataclasses import dataclass

RGB = tuple[float, float, float]


@dataclass(frozen=True)
class Material:
    """A real-world material, described today by its render facet
    (Cycles Principled BSDF parameters) plus a structured
    material/finish split so the catalog stays queryable when a
    non-render consumer (FEA, kinematics) shows up.

    Color is overridable per-placement — when a ``Scene.add(...,
    color=...)`` is set, ``render.py`` overrides ``base_color`` with
    that value. Materials whose color is intrinsic (e.g. ``steel``)
    ignore the placement color.

    ``transmission`` (0..1) routes light through the surface — 1.0 is
    full glass / clear acrylic, 0.0 is opaque. ``ior`` is the index of
    refraction used when transmission > 0 (1.49 for cast acrylic,
    1.52 for soda-lime glass; 1.45 is a neutral default).
    """

    material: str
    finish: str
    base_color: RGB
    metallic: float
    roughness: float
    specular: float = 0.5
    color_overridable: bool = True
    transmission: float = 0.0
    ior: float = 1.45


MATERIALS: dict[str, Material] = {
    "pla_matte": Material(
        material="pla",
        finish="matte",
        base_color=(0.8, 0.8, 0.8),
        metallic=0.0,
        roughness=0.7,
    ),
    "pla_glossy": Material(
        material="pla",
        finish="glossy",
        base_color=(0.8, 0.8, 0.8),
        metallic=0.0,
        roughness=0.25,
    ),
    "aluminium_anodized": Material(
        material="aluminium",
        finish="anodized",
        base_color=(0.55, 0.57, 0.60),
        metallic=0.9,
        roughness=0.35,
    ),
    "steel": Material(
        material="steel",
        finish="default",
        base_color=(0.78, 0.78, 0.80),
        metallic=1.0,
        roughness=0.25,
        color_overridable=False,
    ),
    "rubber": Material(
        material="rubber",
        finish="default",
        base_color=(0.04, 0.04, 0.04),
        metallic=0.0,
        roughness=0.85,
        color_overridable=False,
    ),
    "cast_aluminium_dark": Material(
        material="cast_aluminium_dark",
        finish="default",
        base_color=(0.12, 0.12, 0.13),
        metallic=0.7,
        roughness=0.45,
        color_overridable=False,
    ),
    "acrylic_clear": Material(
        material="acrylic",
        finish="clear",
        base_color=(0.95, 0.97, 0.98),
        metallic=0.0,
        roughness=0.05,
        transmission=1.0,
        ior=1.49,
    ),
    "mirror_first_surface": Material(
        # Aluminised first-surface mirror (reflective coating on the
        # front face, no glass in front to double-image). Spectral
        # reflectance of aluminium is ~91% across the visible band.
        material="mirror",
        finish="first_surface",
        base_color=(0.91, 0.92, 0.92),
        metallic=1.0,
        roughness=0.0,
        color_overridable=False,
    ),
}


def get(name: str) -> Material:
    """Look up a material by name. Raises ``KeyError`` with a helpful
    message if the name is unknown.
    """
    if name not in MATERIALS:
        known = ", ".join(sorted(MATERIALS))
        raise KeyError(f"unknown material '{name}'. known materials: {known}")
    return MATERIALS[name]
