"""Studio-rig presets for the render layer.

Pure data: each preset describes the lights and environment to set up.
``render.py`` consumes the preset and instantiates real ``bpy``
objects. Keeping this module ``bpy``-free means tests can compare
preset choices without booting Blender.

Two world-background modes are supported:

- **Flat color.** ``world_color`` + ``world_strength`` drive a solid
  Background node. No environmental reflections. Cheapest; useful for
  diagnostic-style renders and offline tests.
- **HDRI.** ``world_hdri`` names a Polyhaven CC0 .exr that ships with
  Blender (``studio``, ``interior``, ``courtyard``, …) or a path to a
  custom .exr/.hdr. Provides real environmental reflections on
  metallic/glossy materials — the difference between "CAD render" and
  "product shot." When set, ``world_color`` / ``world_strength`` are
  ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

Vec3 = tuple[float, float, float]


BUNDLED_HDRI_NAMES = frozenset(
    {
        "city",
        "courtyard",
        "forest",
        "interior",
        "night",
        "studio",
        "sunrise",
        "sunset",
    }
)
"""Names of the Polyhaven CC0 world HDRIs Blender ships in
``<bpy datafiles>/studiolights/world/``. ``world_hdri`` can be any of
these strings to use the bundled .exr without shipping a separate
asset, or a ``Path`` to a custom file."""


@dataclass(frozen=True)
class KeyLight:
    """A directional (SUN) light with optional camera parenting.

    ``direction`` is a unit-ish vector pointing *toward* the subject —
    the direction the light travels. When ``camera_parented=False``
    (default), ``direction`` is in the canonical Y-up frame the framing
    strategies use, and is re-oriented to the scene's ``world_up`` with
    them, so a key from above stays above in a Z-up scene. When True, it
    is interpreted in the camera's local frame (Blender convention:
    camera looks down its local -Z, +X is right in the image, +Y is
    up); the light is parented to the camera so its direction relative
    to the camera stays fixed through any animation.

    ``strength_w_m2`` is a sun lamp's strength, the irradiance it lays
    on a surface facing it, and not a lamp's radiant power in watts: a
    sun has no falloff, so the reading does not depend on the size of
    the scene. Around 3 exposes a matte face fully; in the hundreds
    every lit face clips to white.
    """

    direction: Vec3
    strength_w_m2: float
    angle_deg: float = 5.0
    camera_parented: bool = False


@dataclass(frozen=True)
class StudioRig:
    """World background + optional key + optional camera-mounted fill.

    Three lighting roles, each independently optional:

    - **Environment**: ``world_hdri`` (HDRI .exr/.hdr) gives ambient
      fill + reflections; falls back to flat ``world_color`` /
      ``world_strength`` if None.
    - **Key**: world-fixed SUN lamp giving the dominant shadow
      direction. Sets the scene's "where's noon" feel. ``camera_parented``
      typically False.
    - **Fill**: camera-mounted SUN lamp that lifts the camera-side
      shadows so the subject never goes too dark from the camera's
      POV. Typical energy ≈ 30–50 % of key. ``camera_parented`` typically
      True so the fill direction stays consistent through a camera move.

    Two-light setup (key + fill) on top of HDRI is the standard
    product-photography rig and ``DEFAULT_HDRI`` ships it out of the
    box.
    """

    world_color: Vec3
    world_strength: float
    key: KeyLight | None
    fill: KeyLight | None = None
    world_hdri: str | Path | None = None
    """``None`` (flat color), a bundled name from
    ``BUNDLED_HDRI_NAMES``, or a ``Path`` to a custom .exr / .hdr."""
    world_hdri_strength: float = 1.0
    """Multiplier on the HDRI's emission. The Blender-bundled studio
    HDRIs are calibrated near 1.0; drop to ~0.5 if reflections wash
    out highlights, raise for dim environments like ``night``."""
    world_hdri_rotation_deg: float = 0.0
    """Yaw rotation of the HDRI around ``world_up``, in degrees. Tilts
    the dominant reflection direction without moving the key lamp."""


DEFAULT = StudioRig(
    world_color=(0.85, 0.85, 0.85),
    world_strength=0.25,
    key=KeyLight(
        # Y-up convention: light comes from above-front-left of the
        # subject, so the direction the light *travels* is downward
        # (-Y), slightly toward the back (+Z), and slightly toward
        # the right (+X). Matches the camera's front-right-up framing.
        direction=(0.3, -1.0, 0.4),
        strength_w_m2=3.0,
        angle_deg=8.0,
    ),
)
"""Flat-grey background + single sun key. Zero external dependencies
and stable for diagnostic-style renders. Prefer ``DEFAULT_HDRI`` for
product-shot output where metallic / glossy materials need real
environmental reflections."""


DEFAULT_HDRI = StudioRig(
    world_color=(0.85, 0.85, 0.85),  # ignored when world_hdri is set
    world_strength=0.25,
    key=None,
    fill=None,
    world_hdri="studio",
    world_hdri_strength=1.0,
    world_hdri_rotation_deg=0.0,
)
"""Polyhaven ``studio_small_01`` (CC0) bundled with Blender — HDRI only.

A multi-softbox HDRI already carries its own directional energy
(specular highlights, dominant shadow direction) AND its own
omnidirectional fill, so adding a SUN key on top stacks redundant
directional energy and adding a SUN fill on top stacks redundant
omnidirectional energy. Both wash out the metallic contrast the HDRI
delivers in the first place.

The ``key`` and ``fill`` slots stay available on ``StudioRig`` for
the cases where they do earn their keep — a uniform HDRI (or no HDRI)
needs a key to create a shadow direction; a key without an HDRI needs
a fill to lift camera-side shadows. ``DEFAULT`` (flat-grey, no HDRI)
keeps its world key for that reason."""


def resolve_hdri_path(name_or_path: str | Path) -> Path:
    """Normalize a ``world_hdri`` field to a filesystem path.

    Bundled names resolve to Blender's ``datafiles/studiolights/world/``.
    Anything else is treated as a path and returned as ``Path(...)``;
    existence is *not* checked here (caller checks at render time so
    bpy-free imports still work).
    """
    if isinstance(name_or_path, Path):
        return name_or_path
    if name_or_path in BUNDLED_HDRI_NAMES:
        # Late import: bpy is heavy and not available in test contexts.
        import bpy

        datafiles = Path(bpy.utils.system_resource("DATAFILES"))
        return datafiles / "studiolights" / "world" / f"{name_or_path}.exr"
    return Path(name_or_path)


@dataclass(frozen=True)
class HdriScan:
    """Equator-band luminance scan of an HDRI.

    Azimuths are expressed in the world frame the render layer's mapping
    produces at ``world_hdri_rotation_deg=0`` (Z-up scenes): 0° = +X,
    90° = +Y, 180° = −X, 270° = −Y.
    """

    dark_azimuth_deg: float
    """World azimuth (deg) of the darkest single column under yaw=0 —
    typically a shadow corner, equipment side, or a narrow gap between
    softboxes. **Rarely what you want behind a product** — see
    ``backdrop_azimuth_deg`` instead."""
    bright_azimuth_deg: float
    """World azimuth (deg) of the brightest single column under yaw=0 —
    typically the centre of a softbox or spotlight (a narrow intense
    spike, not a wide region)."""
    backdrop_azimuth_deg: float
    """World azimuth (deg) of the centre of the widest uniformly-bright
    region under yaw=0 — the photographer's intended backdrop wall.
    Found by ``argmax`` of a wide-window 25th-percentile field
    (default 25% kernel ≈ 90° azimuth), which rewards wide uniformly-
    bright regions and penalises narrow softbox spikes. This is the
    right target for product / portfolio shots: aligning it behind
    the subject gives a clean, uniform background regardless of
    camera drift, because the wall *is* uniform by construction (the
    studio photographer made it so)."""
    backdrop_width_deg: float
    """Angular width (deg) of the backdrop. Contiguous span of columns
    around ``backdrop_azimuth_deg`` whose wide-window p25 value is at
    least half the peak p25 (the half-maximum width). Use this to
    bound camera HFOV + drift so the wall fully covers the swept
    azimuth range. For uniform HDRIs (studio_small_08) this approaches
    360°; for directional photo-studio HDRIs (studio_small_01/_03) it
    is typically 50–80°."""
    contrast_ratio: float
    """``max_luminance / min_luminance`` across the equator band. Below
    ~1000× the HDRI reads as near-uniform (e.g. ``studio_small_08``);
    above ~10000× there is a strong directional studio geometry
    (e.g. ``studio_small_01`` / ``studio_small_03``)."""
    width: int
    height: int

    def recommend_framing(
        self,
        hfov_deg_pref: float = 42.0,
        drift_deg_pref: float = 10.0,
        *,
        hfov_deg_min: float = 24.0,
        safety_margin_deg: float = 2.0,
    ) -> tuple[float, float]:
        """Return ``(hfov_deg, drift_deg)`` that fit inside the backdrop's
        angular width, with a small safety margin so the wall edge
        doesn't graze the frame edge at peak drift.

        Policy: narrow ``hfov`` first (keeps the camera move alive),
        only reduce drift once HFOV is at ``hfov_deg_min``. If the
        backdrop is wider than ``hfov_pref + 2 × drift_pref``, returns
        the preferences unchanged. For near-uniform HDRIs (backdrop
        width approaches 360°), this is a no-op.
        """
        budget = max(0.0, self.backdrop_width_deg - safety_margin_deg)
        sweep_pref = hfov_deg_pref + 2.0 * drift_deg_pref
        if sweep_pref <= budget:
            return (hfov_deg_pref, drift_deg_pref)
        hfov = budget - 2.0 * drift_deg_pref
        if hfov >= hfov_deg_min:
            return (hfov, drift_deg_pref)
        hfov = hfov_deg_min
        drift = max(0.0, (budget - hfov) / 2.0)
        return (hfov, drift)

    def yaw_to_align(
        self,
        *,
        backdrop_at: float | None = None,
        dark_at: float | None = None,
        bright_at: float | None = None,
    ) -> float:
        """Return the ``world_hdri_rotation_deg`` that places the
        selected feature at a target world azimuth (degrees, 0–360).

        Exactly one of ``backdrop_at`` / ``dark_at`` / ``bright_at``
        must be set — a single yaw can only align one feature, not
        several at once. For a typical product / portfolio shot,
        ``backdrop_at = camera_az + 180°`` (the look-through-subject
        azimuth) is what you want: the photographer's backdrop sits
        behind the rig, the softboxes end up wherever the source
        HDRI's wall↔softbox spacing puts them (usually ~180° away,
        i.e. roughly behind the camera).

        ``dark_at`` and ``bright_at`` are kept for diagnostic use —
        e.g. deliberately framing against a black corner or putting
        a softbox in shot for a hard-light look.
        """
        targets = [
            ("backdrop", backdrop_at, self.backdrop_azimuth_deg),
            ("dark", dark_at, self.dark_azimuth_deg),
            ("bright", bright_at, self.bright_azimuth_deg),
        ]
        chosen = [(n, t, s) for n, t, s in targets if t is not None]
        if len(chosen) != 1:
            raise ValueError("set exactly one of backdrop_at / dark_at / bright_at")
        _, target, source = chosen[0]
        return (source - target) % 360.0


def scan_hdri(
    path: str | Path,
    *,
    equator_band: float = 0.20,
    smooth_window_frac: float = 0.05,
    backdrop_window_frac: float = 0.25,
    backdrop_percentile: float = 25.0,
) -> HdriScan:
    """Per-column luminance scan of an HDRI's equator band.

    Useful for picking a deterministic ``world_hdri_rotation_deg`` —
    real-studio HDRIs (``studio_small_01`` / ``_03`` / Polyhaven's
    photo studios) have a backdrop wall on one side and softboxes
    aimed at it from the opposite side, with arbitrary orientation
    baked in by the photographer. Aligning the backdrop to the
    camera-look-through azimuth gives a uniform background.

    ``equator_band`` is the half-width of the latitude band sampled
    around the horizon (default ±20% → 40%-tall central strip).
    ``smooth_window_frac`` is the rolling-mean width for finding the
    single darkest/brightest column (default 5% ≈ 18° azimuth).

    ``backdrop_window_frac`` and ``backdrop_percentile`` together
    define the backdrop detector: for each column, take the window
    of ``backdrop_window_frac × W`` columns centred on it, and
    compute the value at ``backdrop_percentile`` of the window's
    luminance distribution. ``argmax`` of that field picks the
    column whose *lower quartile* (default 25%) is brightest. This
    correctly rewards wide uniformly-bright regions (the wall — its
    lower 25% is still bright because most of its window is wall)
    and penalises narrow spikes (a softbox — its lower 25% is the
    surrounding dark, even though its peak is much brighter than
    the wall). Defaults of 25% width (≈90° azimuth at 1024-wide
    EXR) + 25th percentile cleanly distinguish wall from softbox
    in real photo-studio HDRIs.

    Late-imports ``bpy`` (uses Blender's EXR reader) and ``numpy``.
    Both are present whenever ``bpy`` is.
    """
    import bpy
    import numpy as np

    p = Path(path)
    img = bpy.data.images.load(str(p), check_existing=False)
    try:
        W, H = img.size[0], img.size[1]
        pixels = np.array(img.pixels[:]).reshape(H, W, 4)
        lum = (
            0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]
        )
        v_lo = int((0.5 - equator_band) * H)
        v_hi = int((0.5 + equator_band) * H)
        col_lum = lum[v_lo:v_hi, :].mean(axis=0)

        def col_to_az(col: int) -> float:
            # Cycles' Equirectangular projection (intern/cycles/kernel
            # svm_image_env): u = -atan2(y, x) / (2π) + 0.5. Inverting
            # this gives azimuth(u) = (0.5 - u) * 360°, so:
            # u=0.5 → +X (az 0°), u=0.25 → +Y (az 90°),
            # u=0/1 → −X (az 180°), u=0.75 → −Y (az 270°).
            u = (col + 0.5) / W
            return ((0.5 - u) * 360.0) % 360.0

        # Narrow smoothing: find the single darkest/brightest column.
        narrow_win = max(1, int(smooth_window_frac * W))
        narrow_smooth = _wrap_mean_filter(col_lum, narrow_win)
        dark_col = int(np.argmin(narrow_smooth))
        bright_col = int(np.argmax(narrow_smooth))

        # Wide percentile: find the backdrop. The pNN-over-wide-window
        # field rewards regions where most of the window is bright
        # (wall) and penalises regions where only a small fraction is
        # bright (softbox spike).
        wide_win = max(3, int(backdrop_window_frac * W) | 1)
        wide_pNN = _wrap_percentile_filter(col_lum, wide_win, backdrop_percentile)
        backdrop_col = int(np.argmax(wide_pNN))

        # Backdrop angular width: the contiguous wraparound span of
        # columns around backdrop_col whose p25 is at least half the
        # peak p25 (half-maximum width). For a wide bright wall this
        # gives the wall extent; for a uniform HDRI it approaches W
        # (full 360°); for a narrow spike it stays small.
        peak = float(wide_pNN[backdrop_col])
        threshold = 0.5 * peak
        # Walk left and right from backdrop_col with wraparound.
        above = wide_pNN >= threshold
        # Distance walked left until below threshold.
        left = 0
        for k in range(1, W):
            if not above[(backdrop_col - k) % W]:
                break
            left += 1
        right = 0
        for k in range(1, W):
            if not above[(backdrop_col + k) % W]:
                break
            right += 1
        width_cols = min(W, 1 + left + right)
        backdrop_width_deg = float(width_cols) * 360.0 / W

        return HdriScan(
            dark_azimuth_deg=col_to_az(dark_col),
            bright_azimuth_deg=col_to_az(bright_col),
            backdrop_azimuth_deg=col_to_az(backdrop_col),
            backdrop_width_deg=backdrop_width_deg,
            contrast_ratio=float(col_lum.max() / max(col_lum.min(), 1e-6)),
            width=W,
            height=H,
        )
    finally:
        bpy.data.images.remove(img)


def _wrap_mean_filter(arr, win: int):
    """1-D rolling-mean over a circular array. ``arr`` is treated as
    wrap-around at the seam (column 0 ≡ column W)."""
    import numpy as np

    if win <= 1:
        return arr.copy()
    kernel = np.ones(win) / win
    pad_l = arr[-(win // 2) :] if win // 2 else arr[:0]
    pad_r = arr[: win - win // 2 - 1] if win > 1 else arr[:0]
    padded = np.concatenate([pad_l, arr, pad_r])
    return np.convolve(padded, kernel, mode="valid")[: len(arr)]


def _wrap_percentile_filter(arr, win: int, percentile: float):
    """1-D rolling percentile over a circular array. O(N·W·log(W)) —
    fine for 1024-wide HDRIs at a 256-wide window (~100 ms)."""
    import numpy as np

    if win <= 1:
        return arr.copy()
    half = win // 2
    n = len(arr)
    padded = np.concatenate([arr[-half:], arr, arr[:half]])
    out = np.empty(n, dtype=arr.dtype)
    for i in range(n):
        out[i] = np.percentile(padded[i : i + win], percentile)
    return out
