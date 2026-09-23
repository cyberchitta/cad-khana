# Reading drawings

`khana draw <path>` writes ten views to `outputs/views/`: six
orthographic (`top`, `bottom`, `front`, `back`, `left`, `right`) and
four isometric (`iso_ne`, `iso_nw`, `iso_se`, `iso_sw`, named by the
camera octant in +Z-up / +Y-forward space). They're hidden-line
engineering drawings: visible edges in black, hidden in light grey.

The files cost only disk; the token cost is paid when you `Read` one
into context. So load only the view that answers your question:

- "Is this aligned along Z?" → `top` (or `bottom`).
- "Did the cut land where I expected?" → the orthographic view
  perpendicular to the cut axis.
- "Does the shape look right at a glance?" → one isometric is enough;
  `iso_ne` is a good default.
- "Is the underside clean?" → `bottom`, then the relevant side view if
  something looks off.

Don't load all ten by default. If one view doesn't answer, ask for a
second — not the whole set.

Two flags trim what gets written when you already know the answer
won't need ten views:

- `--view <names>` — comma-separated subset, e.g. `--view top,iso_ne`.
  Generation cost drops linearly; consumption cost only changes if
  you `Read` fewer files.
- `--part <name>` — frame and render only that one named part from
  the assembly (in its assembled position). Useful when one part is
  small and far from the others and the default whole-assembly framing
  shrinks it to a few pixels.

Default format is PNG; pass
`--format svg` for lossless vector output (diffable, inspectable
as text), or `--format both` to get both. Pass `--themeable` with
`svg`/`both` to additionally tag polylines with
`class="cad-visible"` / `class="cad-hidden"`; the default inline
stroke stays as a fallback, so non-CSS renderers see the same
drawing while a CSS consumer (e.g. a website embedding the SVG
inline) can restyle the two classes for dark-mode or brand colors.
