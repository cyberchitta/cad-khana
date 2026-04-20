from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from build123d import Compound, Edge, GeomType
from build123d.exporters import Drawing
from PIL import Image, ImageDraw

from cad_khana.mechanism.assembly import Assembly

_auto_enabled = False
_auto_out: Path | None = None


def set_auto(enabled: bool, out: Path | None = None) -> None:
    global _auto_enabled, _auto_out
    _auto_enabled = enabled
    _auto_out = out


def auto_enabled() -> bool:
    return _auto_enabled


def auto_out() -> Path | None:
    return _auto_out


@dataclass(frozen=True)
class View:
    name: str
    look_from: tuple[float, float, float]
    look_up: tuple[float, float, float]


STANDARD_VIEWS: tuple[View, ...] = (
    View("front", look_from=(0, -1, 0), look_up=(0, 0, 1)),
    View("top", look_from=(0, 0, 1), look_up=(0, 1, 0)),
    View("right", look_from=(1, 0, 0), look_up=(0, 0, 1)),
    View("iso", look_from=(1, -1, 1), look_up=(0, 0, 1)),
)

IMAGE_SIZE_PX = 1200
SUPERSAMPLE = 2
MARGIN_FRACTION = 0.06
VISIBLE_COLOR = (0, 0, 0)
HIDDEN_COLOR = (170, 170, 170)
LINE_WIDTH_PX = 2
CURVE_SAMPLES = 48

Segment = tuple[tuple[float, float], ...]


def _sample(edge: Edge) -> Segment:
    n = 2 if edge.geom_type == GeomType.LINE else CURVE_SAMPLES
    return tuple((p.X, p.Y) for p in (edge @ (i / (n - 1)) for i in range(n)))


def _segments(compound: Compound) -> tuple[Segment, ...]:
    return tuple(_sample(e) for e in compound.edges())


def _bounds(segments: tuple[Segment, ...]) -> tuple[float, float, float, float]:
    xs = tuple(x for seg in segments for x, _ in seg)
    ys = tuple(y for seg in segments for _, y in seg)
    return min(xs), min(ys), max(xs), max(ys)


def _rasterize(
    visible: tuple[Segment, ...],
    hidden: tuple[Segment, ...],
) -> Image.Image:
    if not visible and not hidden:
        return Image.new("RGB", (IMAGE_SIZE_PX, IMAGE_SIZE_PX), (255, 255, 255))
    x0, y0, x1, y1 = _bounds(visible + hidden)
    w_model, h_model = max(x1 - x0, 1e-9), max(y1 - y0, 1e-9)
    super_px = IMAGE_SIZE_PX * SUPERSAMPLE
    usable = super_px * (1 - 2 * MARGIN_FRACTION)
    scale = min(usable / w_model, usable / h_model)
    ox = (super_px - w_model * scale) / 2 - x0 * scale
    oy = (super_px - h_model * scale) / 2 - y0 * scale

    def to_px(p: tuple[float, float]) -> tuple[float, float]:
        return (p[0] * scale + ox, super_px - (p[1] * scale + oy))

    img = Image.new("RGB", (super_px, super_px), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    width = LINE_WIDTH_PX * SUPERSAMPLE
    for seg in hidden:
        draw.line([to_px(p) for p in seg], fill=HIDDEN_COLOR, width=width, joint="curve")
    for seg in visible:
        draw.line([to_px(p) for p in seg], fill=VISIBLE_COLOR, width=width, joint="curve")
    return img.resize((IMAGE_SIZE_PX, IMAGE_SIZE_PX), Image.LANCZOS)


def _render_view(compound: Compound, view: View, out: Path) -> Path:
    drawing = Drawing(
        compound,
        look_from=view.look_from,
        look_up=view.look_up,
        with_hidden=True,
    )
    visible = _segments(drawing.visible_lines)
    hidden = _segments(drawing.hidden_lines)
    path = out / f"{view.name}.png"
    _rasterize(visible, hidden).save(path)
    return path


def render(
    assembly: Assembly,
    out: Path,
    views: tuple[View, ...] = STANDARD_VIEWS,
) -> tuple[Path, ...]:
    out.mkdir(parents=True, exist_ok=True)
    compound = assembly.compound
    return tuple(_render_view(compound, v, out) for v in views)
