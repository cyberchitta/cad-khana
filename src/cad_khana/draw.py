from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from build123d import Compound, Edge, GeomType
from build123d.exporters import Drawing
from PIL import Image, ImageDraw

from cad_khana.mechanism.assembly import Assembly

_auto_enabled = False
_auto_out: Path | None = None
_auto_fmt: str = "png"
_auto_themeable: bool = False
_auto_views: tuple[str, ...] | None = None
_auto_part: str | None = None


def set_auto(
    enabled: bool,
    out: Path | None = None,
    fmt: str = "png",
    themeable: bool = False,
    views: tuple[str, ...] | None = None,
    part: str | None = None,
) -> None:
    global _auto_enabled, _auto_out, _auto_fmt, _auto_themeable
    global _auto_views, _auto_part
    _auto_enabled = enabled
    _auto_out = out
    _auto_fmt = fmt
    _auto_themeable = themeable
    _auto_views = views
    _auto_part = part


def auto_enabled() -> bool:
    return _auto_enabled


def auto_out() -> Path | None:
    return _auto_out


def auto_fmt() -> str:
    return _auto_fmt


def auto_themeable() -> bool:
    return _auto_themeable


def auto_views() -> tuple[str, ...] | None:
    return _auto_views


def auto_part() -> str | None:
    return _auto_part


@dataclass(frozen=True)
class View:
    name: str
    look_from: tuple[float, float, float]
    look_up: tuple[float, float, float]


VIEW_PRESETS: dict[str, View] = {
    "top":    View("top",    look_from=( 0,  0,  1), look_up=( 0,  1,  0)),
    "bottom": View("bottom", look_from=( 0,  0, -1), look_up=( 0,  1,  0)),
    "front":  View("front",  look_from=( 0, -1,  0), look_up=( 0,  0,  1)),
    "back":   View("back",   look_from=( 0,  1,  0), look_up=( 0,  0,  1)),
    "right":  View("right",  look_from=( 1,  0,  0), look_up=( 0,  0,  1)),
    "left":   View("left",   look_from=(-1,  0,  0), look_up=( 0,  0,  1)),
    "iso_ne": View("iso_ne", look_from=( 1,  1,  1), look_up=( 0,  0,  1)),
    "iso_nw": View("iso_nw", look_from=(-1,  1,  1), look_up=( 0,  0,  1)),
    "iso_se": View("iso_se", look_from=( 1, -1,  1), look_up=( 0,  0,  1)),
    "iso_sw": View("iso_sw", look_from=(-1, -1,  1), look_up=( 0,  0,  1)),
}

DEFAULT_VIEW_NAMES: tuple[str, ...] = tuple(VIEW_PRESETS.keys())
STANDARD_VIEWS: tuple[View, ...] = tuple(VIEW_PRESETS.values())

CAMERA_DISTANCE_FACTOR = 2.5

IMAGE_SIZE_PX = 1200
SUPERSAMPLE = 2
MARGIN_FRACTION = 0.06
VISIBLE_COLOR = (0, 0, 0)
HIDDEN_COLOR = (170, 170, 170)
LINE_WIDTH_PX = 2
CURVE_SAMPLES = 48

Segment = tuple[tuple[float, float], ...]
Point = tuple[float, float]


def _sample(edge: Edge) -> Segment:
    n = 2 if edge.geom_type == GeomType.LINE else CURVE_SAMPLES
    return tuple((p.X, p.Y) for p in (edge @ (i / (n - 1)) for i in range(n)))


def _segments(compound: Compound) -> tuple[Segment, ...]:
    return tuple(_sample(e) for e in compound.edges())


def _edge_key(e: Edge) -> tuple:
    """Orientation-invariant fingerprint for HLR-produced edges.

    For circles/ellipses we key off the underlying geometry (center +
    radii) so different parameterizations of the same conic collapse to
    one entry; partial conic arcs include length + midpoint to keep the
    short and long arcs distinct.
    """
    gt = e.geom_type
    if gt in (GeomType.CIRCLE, GeomType.ELLIPSE):
        adaptor = e.geom_adaptor()
        if gt == GeomType.CIRCLE:
            c = adaptor.Circle()
            loc = c.Location()
            geom = ("CIRCLE", round(loc.X(), 4), round(loc.Y(), 4), round(c.Radius(), 4))
        else:
            el = adaptor.Ellipse()
            loc = el.Location()
            xd = el.XAxis().Direction()
            geom = (
                "ELLIPSE",
                round(loc.X(), 4),
                round(loc.Y(), 4),
                round(el.MajorRadius(), 4),
                round(el.MinorRadius(), 4),
                round(xd.X(), 4),
                round(xd.Y(), 4),
            )
        if adaptor.IsClosed():
            return (*geom, "closed")
        pm = e @ 0.5
        return (
            *geom,
            (round(pm.X, 4), round(pm.Y, 4)),
            round(e.length, 4),
        )
    p0 = e @ 0
    p1 = e @ 1
    pm = e @ 0.5
    k0 = (round(p0.X, 4), round(p0.Y, 4))
    k1 = (round(p1.X, 4), round(p1.Y, 4))
    return (str(gt), frozenset((k0, k1)), (round(pm.X, 4), round(pm.Y, 4)))


def _split_edges(drawing: Drawing) -> tuple[list[Edge], list[Edge]]:
    """Visible and hidden edges from an HLR Drawing, with duplicates
    collapsed both within each set and across sets (visible wins)."""
    seen: set = set()
    visible: list[Edge] = []
    for e in drawing.visible_lines.edges():
        k = _edge_key(e)
        if k in seen:
            continue
        seen.add(k)
        visible.append(e)
    hidden: list[Edge] = []
    for e in drawing.hidden_lines.edges():
        k = _edge_key(e)
        if k in seen:
            continue
        seen.add(k)
        hidden.append(e)
    return visible, hidden


@dataclass(frozen=True)
class _Polyline:
    samples: Segment


@dataclass(frozen=True)
class _EllipseArc:
    """Math-frame (y-up) description of a circular or elliptical arc."""

    center: Point
    rx: float
    ry: float
    rotation_rad: float
    start: Point
    end: Point
    mid: Point
    quarter: Point
    three_quarter: Point
    closed: bool
    samples: Segment


_Primitive = _Polyline | _EllipseArc


def _arc_primitive(edge: Edge) -> _EllipseArc:
    curve = edge.geom_adaptor()
    if edge.geom_type == GeomType.CIRCLE:
        c = curve.Circle()
        rx = ry = c.Radius()
        loc = c.Location()
        x_dir = c.XAxis().Direction()
    else:
        e = curve.Ellipse()
        rx = e.MajorRadius()
        ry = e.MinorRadius()
        loc = e.Location()
        x_dir = e.XAxis().Direction()
    p_start = edge @ 0
    p_quarter = edge @ 0.25
    p_mid = edge @ 0.5
    p_three_quarter = edge @ 0.75
    p_end = edge @ 1
    closed = math.hypot(p_start.X - p_end.X, p_start.Y - p_end.Y) < 1e-7
    return _EllipseArc(
        center=(loc.X(), loc.Y()),
        rx=rx,
        ry=ry,
        rotation_rad=math.atan2(x_dir.Y(), x_dir.X()),
        start=(p_start.X, p_start.Y),
        end=(p_end.X, p_end.Y),
        mid=(p_mid.X, p_mid.Y),
        quarter=(p_quarter.X, p_quarter.Y),
        three_quarter=(p_three_quarter.X, p_three_quarter.Y),
        closed=closed,
        samples=_sample(edge),
    )


def _primitive(edge: Edge) -> _Primitive:
    if edge.geom_type in (GeomType.CIRCLE, GeomType.ELLIPSE):
        return _arc_primitive(edge)
    return _Polyline(samples=_sample(edge))


def _primitives(compound: Compound) -> tuple[_Primitive, ...]:
    return tuple(_primitive(e) for e in compound.edges())


def _bounds(segments: tuple[Segment, ...]) -> tuple[float, float, float, float]:
    xs = tuple(x for seg in segments for x, _ in seg)
    ys = tuple(y for seg in segments for _, y in seg)
    return min(xs), min(ys), max(xs), max(ys)


def _transform(
    segments: tuple[Segment, ...],
    canvas_px: int,
) -> tuple[float, float, float]:
    x0, y0, x1, y1 = _bounds(segments)
    w_model = max(x1 - x0, 1e-9)
    h_model = max(y1 - y0, 1e-9)
    usable = canvas_px * (1 - 2 * MARGIN_FRACTION)
    scale = min(usable / w_model, usable / h_model)
    ox = (canvas_px - w_model * scale) / 2 - x0 * scale
    oy = (canvas_px - h_model * scale) / 2 - y0 * scale
    return scale, ox, oy


def _to_px(
    p: tuple[float, float],
    scale: float,
    ox: float,
    oy: float,
    canvas_px: int,
) -> tuple[float, float]:
    return (p[0] * scale + ox, canvas_px - (p[1] * scale + oy))


def _rasterize(
    visible: tuple[Segment, ...],
    hidden: tuple[Segment, ...],
) -> Image.Image:
    if not visible and not hidden:
        return Image.new("RGB", (IMAGE_SIZE_PX, IMAGE_SIZE_PX), (255, 255, 255))
    super_px = IMAGE_SIZE_PX * SUPERSAMPLE
    scale, ox, oy = _transform(visible + hidden, super_px)
    img = Image.new("RGB", (super_px, super_px), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    width = LINE_WIDTH_PX * SUPERSAMPLE
    for seg in hidden:
        draw.line(
            [_to_px(p, scale, ox, oy, super_px) for p in seg],
            fill=HIDDEN_COLOR,
            width=width,
            joint="curve",
        )
    for seg in visible:
        draw.line(
            [_to_px(p, scale, ox, oy, super_px) for p in seg],
            fill=VISIBLE_COLOR,
            width=width,
            joint="curve",
        )
    return img.resize((IMAGE_SIZE_PX, IMAGE_SIZE_PX), Image.LANCZOS)


def _classify_arc(
    start: Point,
    ref: Point,
    end: Point,
    center: Point,
    rx: float,
    ry: float,
    rotation_rad: float,
) -> tuple[int, int]:
    """SVG (large_arc_flag, sweep_flag) for an arc passing through ``ref``.

    All inputs are in the same pixel coordinate frame; rotation is the
    angle of the ellipse's major axis from +x in that frame.
    """
    c, s = math.cos(-rotation_rad), math.sin(-rotation_rad)

    def u(p: Point) -> float:
        dx = p[0] - center[0]
        dy = p[1] - center[1]
        lx = dx * c - dy * s
        ly = dx * s + dy * c
        return math.atan2(ly / ry, lx / rx)

    two_pi = 2 * math.pi
    du_ref = (u(ref) - u(start)) % two_pi
    du_end = (u(end) - u(start)) % two_pi
    if du_ref < du_end:
        return (1 if du_end > math.pi else 0, 1)
    return (1 if (two_pi - du_end) > math.pi else 0, 0)


def _arc_d(arc: _EllipseArc, scale: float, ox: float, oy: float, canvas_px: int) -> str:
    rx_px = arc.rx * scale
    ry_px = arc.ry * scale
    rot_px_rad = -arc.rotation_rad
    rot_deg = math.degrees(rot_px_rad)
    start = _to_px(arc.start, scale, ox, oy, canvas_px)
    end = _to_px(arc.end, scale, ox, oy, canvas_px)
    mid = _to_px(arc.mid, scale, ox, oy, canvas_px)
    center = _to_px(arc.center, scale, ox, oy, canvas_px)
    if arc.closed:
        quarter = _to_px(arc.quarter, scale, ox, oy, canvas_px)
        three_q = _to_px(arc.three_quarter, scale, ox, oy, canvas_px)
        _, sweep_a = _classify_arc(start, quarter, mid, center, rx_px, ry_px, rot_px_rad)
        _, sweep_b = _classify_arc(mid, three_q, end, center, rx_px, ry_px, rot_px_rad)
        return (
            f"M {start[0]:.2f} {start[1]:.2f} "
            f"A {rx_px:.2f} {ry_px:.2f} {rot_deg:.2f} 0 {sweep_a} "
            f"{mid[0]:.2f} {mid[1]:.2f} "
            f"A {rx_px:.2f} {ry_px:.2f} {rot_deg:.2f} 0 {sweep_b} "
            f"{end[0]:.2f} {end[1]:.2f}"
        )
    large, sweep = _classify_arc(start, mid, end, center, rx_px, ry_px, rot_px_rad)
    return (
        f"M {start[0]:.2f} {start[1]:.2f} "
        f"A {rx_px:.2f} {ry_px:.2f} {rot_deg:.2f} {large} {sweep} "
        f"{end[0]:.2f} {end[1]:.2f}"
    )


def _polyline_points(samples: Segment, scale: float, ox: float, oy: float, canvas_px: int) -> str:
    return " ".join(
        f"{px[0]:.2f},{px[1]:.2f}"
        for px in (_to_px(p, scale, ox, oy, canvas_px) for p in samples)
    )


def _emit_svg_element(
    prim: _Primitive,
    category: str,
    themeable: bool,
    scale: float,
    ox: float,
    oy: float,
    canvas_px: int,
) -> str:
    stroke, width = (
        ("rgb(0,0,0)", "1.5") if category == "visible" else ("rgb(170,170,170)", "1")
    )
    cls = f' class="cad-{category}"' if themeable else ""
    if isinstance(prim, _EllipseArc):
        d = _arc_d(prim, scale, ox, oy, canvas_px)
        return (
            f'  <path d="{d}"{cls} stroke="{stroke}" '
            f'stroke-width="{width}" fill="none"/>'
        )
    pts = _polyline_points(prim.samples, scale, ox, oy, canvas_px)
    return (
        f'  <polyline points="{pts}"{cls} stroke="{stroke}" '
        f'stroke-width="{width}" fill="none"/>'
    )


def _to_svg(
    visible: tuple[_Primitive, ...],
    hidden: tuple[_Primitive, ...],
    themeable: bool = False,
) -> str:
    size = IMAGE_SIZE_PX
    all_prims = visible + hidden
    if not all_prims:
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{size}" height="{size}" viewBox="0 0 {size} {size}"/>'
        )
    scale, ox, oy = _transform(tuple(p.samples for p in all_prims), size)
    hidden_lines = "\n".join(
        _emit_svg_element(p, "hidden", themeable, scale, ox, oy, size) for p in hidden
    )
    visible_lines = "\n".join(
        _emit_svg_element(p, "visible", themeable, scale, ox, oy, size) for p in visible
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" viewBox="0 0 {size} {size}">\n'
        f"{hidden_lines}\n{visible_lines}\n</svg>"
    )


def _scoped_compound(assembly: Assembly, part: str | None) -> Compound:
    if part is None:
        return assembly.compound
    placed = assembly.placed_parts
    matches = tuple(p for p in placed if p.name == part)
    if not matches:
        names = ", ".join(repr(p.name) for p in placed) or "(none)"
        raise ValueError(
            f"--part {part!r} not in assembly; have: {names}"
        )
    return Compound(children=[p.part.moved(p.location) for p in matches])


def _bbox_extent(compound: Compound) -> tuple[tuple[float, float, float], float]:
    """Return (center_xyz, max_extent) for an arbitrary compound."""
    bb = compound.bounding_box()
    center = ((bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2, (bb.min.Z + bb.max.Z) / 2)
    extent = max(bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z)
    return center, extent


def _camera_look_from(
    direction: tuple[float, float, float],
    center: tuple[float, float, float],
    extent: float,
) -> tuple[float, float, float]:
    """Camera position at ``center + direction_unit * (extent * 2.5)``.

    Build123d's HLR Drawing is orthographic, so the distance is a no-op
    for the projection; the bbox-scaled position is still the right
    shape if perspective ever lands and makes per-frame sizing matter.
    """
    n = math.sqrt(sum(d * d for d in direction)) or 1.0
    d = extent * CAMERA_DISTANCE_FACTOR
    return tuple(center[i] + direction[i] / n * d for i in range(3))  # type: ignore[return-value]


def _resolve_views(names: tuple[str, ...] | None) -> tuple[View, ...]:
    if names is None:
        return STANDARD_VIEWS
    unknown = tuple(n for n in names if n not in VIEW_PRESETS)
    if unknown:
        known = ", ".join(VIEW_PRESETS.keys())
        raise ValueError(
            f"unknown view name(s): {', '.join(unknown)}; known: {known}"
        )
    return tuple(VIEW_PRESETS[n] for n in names)


def _drawing(
    compound: Compound,
    view: View,
    center: tuple[float, float, float],
    extent: float,
) -> Drawing:
    return Drawing(
        compound,
        look_at=center,
        look_from=_camera_look_from(view.look_from, center, extent),
        look_up=view.look_up,
        with_hidden=True,
    )


def _draw_view(
    compound: Compound,
    view: View,
    center: tuple[float, float, float],
    extent: float,
    out: Path,
) -> Path:
    drawing = _drawing(compound, view, center, extent)
    vis_edges, hid_edges = _split_edges(drawing)
    visible = tuple(_sample(e) for e in vis_edges)
    hidden = tuple(_sample(e) for e in hid_edges)
    path = out / f"{view.name}.png"
    _rasterize(visible, hidden).save(path)
    return path


def _draw_view_svg(
    compound: Compound,
    view: View,
    center: tuple[float, float, float],
    extent: float,
    out: Path,
    themeable: bool = False,
) -> Path:
    drawing = _drawing(compound, view, center, extent)
    vis_edges, hid_edges = _split_edges(drawing)
    visible = tuple(_primitive(e) for e in vis_edges)
    hidden = tuple(_primitive(e) for e in hid_edges)
    path = out / f"{view.name}.svg"
    path.write_text(_to_svg(visible, hidden, themeable=themeable))
    return path


def draw(
    assembly: Assembly,
    out: Path,
    views: tuple[str, ...] | None = None,
    part: str | None = None,
    format: str = "png",
    themeable: bool = False,
) -> tuple[Path, ...]:
    """Write orthographic + isometric engineering drawings (HLR
    line-art, no fills or shading) for ``assembly`` under ``out``.

    For shaded photo-real PNGs use ``chitra_cad.render.render`` instead;
    for an interactive shape-truth view use ``export_glb`` and serve the
    GLB in ``<model-viewer>``.
    """
    out.mkdir(parents=True, exist_ok=True)
    compound = _scoped_compound(assembly, part)
    center, extent = _bbox_extent(compound)
    selected = _resolve_views(views)
    paths: list[Path] = []
    for v in selected:
        if format in ("png", "both"):
            paths.append(_draw_view(compound, v, center, extent, out))
        if format in ("svg", "both"):
            paths.append(_draw_view_svg(compound, v, center, extent, out, themeable=themeable))
    return tuple(paths)
