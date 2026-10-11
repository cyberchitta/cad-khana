from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from build123d import Color, Location, Part

if TYPE_CHECKING:
    from cad_khana.mechanism.assembly import Assembly


RGB = tuple[float, float, float]


@dataclass(frozen=True)
class PlacedPart:
    name: str
    part: Part
    location: Location
    material: str
    color: RGB | None = None


def _srgb_to_linear(c: float) -> float:
    """sRGB-encoded channel value → linear-light value.

    Approximation: ``c ** 2.2`` matches the standard sRGB transfer
    function closely enough across 0..1 to be indistinguishable from
    the piecewise form at material-pick precision. Cycles' Principled
    BSDF ``Base Color`` is interpreted as linear light, so build123d
    ``Color`` values (which we treat as sRGB-encoded — the way humans
    pick colors from web tools, design pickers, and CSS) must be
    converted here before reaching Blender.
    """
    return c**2.2


def _color_to_rgb(color: Color | None) -> RGB | None:
    """Convert a build123d ``Color`` (sRGB-encoded) to linear-light
    RGB for Blender Cycles.

    The sRGB-encoded convention matches how palettes are authored in
    the consumer (warm-cream #e0ddd8 maps to ``Color(0.878, 0.867,
    0.847)`` straight from the design picker, no manual linearization).
    The catalog ``Material.base_color`` values in ``materials.py`` are
    already linear (visually tuned in Cycles) and bypass this path.
    """
    if color is None:
        return None
    r, g, b, _a = tuple(color)
    return (_srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b))


@dataclass(frozen=True)
class Scene:
    """Named, materialed, placed parts ready to render.

    Built up immutably via ``.add(...)``. Convert from a cad-khana
    ``Assembly`` via ``Scene.from_assembly(...)`` and attach materials
    via ``.with_materials({name: material})``.
    """

    parts: tuple[PlacedPart, ...] = ()

    def add(
        self,
        name: str,
        part: Part,
        location: Location | None = None,
        material: str = "pla_matte",
        color: RGB | None = None,
    ) -> Scene:
        placed = PlacedPart(
            name=name,
            part=part,
            location=location or Location(),
            material=material,
            color=color,
        )
        return replace(self, parts=self.parts + (placed,))

    def with_materials(self, mapping: dict[str, str]) -> Scene:
        """Return a copy with each named part's material replaced by the
        value in ``mapping``. Parts not in the mapping are unchanged.

        Render-only override layer — useful for sweeping finishes for a
        hero shot without touching the assembly. For overrides that
        should also flow to non-render consumers (FEA, kinematics), set
        the material on the upstream ``Assembly`` instead via
        ``cad_khana.mechanism.assembly.Assembly.with_materials({...})``.
        """
        updated = tuple(
            replace(p, material=mapping.get(p.name, p.material)) for p in self.parts
        )
        return replace(self, parts=updated)

    @staticmethod
    def from_assembly(assembly: Assembly) -> Scene:
        """Adapt a cad-khana ``Assembly`` into a ``Scene``.

        Names, parts, locations, per-part ``Color``, and per-part
        material carry over. Parts whose ``material`` is unset on the
        assembly fall back to ``pla_matte``; override either upstream
        (``Assembly.with_materials``) or here (``Scene.with_materials``).

        Walks ``Assembly.placed_parts`` — the recursive flat view in
        world coordinates — so parts nested inside ``SubAssembly``
        nodes (animated joints, relocatable units) reach the render
        pipeline. Reading ``assembly.parts`` directly would silently
        drop everything under any ``with_subassembly`` call.
        """
        placed = tuple(
            PlacedPart(
                name=p.name,
                part=p.part,
                location=p.location,
                material=p.material or "pla_matte",
                color=_color_to_rgb(p.color),
            )
            for p in assembly.placed_parts
        )
        return Scene(parts=placed)
