# build123d quick reference

The bits of build123d that LLMs reliably get wrong. For the full API,
see the upstream
[cheat sheet](https://build123d.readthedocs.io/en/latest/cheat_sheet.html).
When unsure, `inspect.signature(Class)` beats guessing — build123d is
rich, and plausible-sounding names (`RoundedBox`, `Hexagon`,
`SubtractHole`) often don't exist.

## Implicit type conversions

build123d accepts shorthand for several common types. Use them.

| Type alias | Accepts |
|---|---|
| `VectorLike` | `Vector(x,y,z)` *or* `(x,y)` *or* `(x,y,z)` |
| `RotationLike` | `Rotation(rx,ry,rz)` *or* `(rx,ry,rz)` |
| `PlaneLike` | `Plane.XY`, a `Face`, a `Location` |
| `AxisLike` | `Axis.X` / `Axis.Y` / `Axis.Z`, or `Axis(origin, direction)` |

Pass `(0, 0, 5)` instead of `Vector(0, 0, 5)`. Pass `(0, 0, 90)`
instead of `Rotation(0, 0, 90)`.

## Selector operators

`part.edges()`, `part.faces()`, `part.vertices()` return collections.
The operator overloads sort, filter, and pick from them:

| Op | Meaning | Example |
|---|---|---|
| `>` | sort by, take max | `edges() > Axis.Z` → topmost edge |
| `<` | sort by, take min | `faces() < Axis.Z` → bottom face |
| `>>` | group by, take last group | `edges() >> Axis.Z` → all edges at the top |
| `<<` | group by, take first group | `faces() << Axis.Z` → all faces at the bottom |
| `\|` | filter by axis / plane / `GeomType` | `edges() \| Axis.Z` → edges parallel to Z |
| `@` | position at parameter `f ∈ [0,1]` on edge/wire | `edge @ 0.5` |
| `%` | tangent at parameter `f` | `edge % 0.5` |
| `^` | `Location` at parameter `f` | `edge ^ 0.5` |

Selectors compose: `(faces() > Axis.Z).edges() | Axis.X` picks
X-aligned edges of the topmost face.

For more control, the methods behind these operators —
`sort_by(...)`, `group_by(...)`, `filter_by(...)` — take callables
and `SortBy` enum values.

## Algebraic vs Builder mode

build123d offers two styles. cad-khana scripts mix them.

**Algebraic** — short shapes, primitive composition, simple
positioning. Default to this.

```python
part = Pos(0, 0, h/2) * (Box(w, w, h) - Cylinder(r, h))
```

| Op | Meaning |
|---|---|
| `+` | union |
| `-` | cut |
| `&` | intersect |
| `*` (Location ⋅ Shape) | apply Location to Shape |

`Pos(x, y, z)` is `Location((x, y, z))` with no rotation. `Rot(rx, ry, rz)`
is rotation-only. They compose: `Pos(0,0,5) * Rot(0,90,0) * Box(...)`.

**Builder** — sketches on workplanes, hole patterns, fillet/chamfer
of selected edges, anything wanting a stateful context.

```python
with BuildPart() as p:
    Box(w, w, h)
    with BuildSketch(p.faces() > Axis.Z) as s:
        Circle(r)
    extrude(amount=-depth, mode=Mode.SUBTRACT)
    fillet(p.edges() | Axis.Z, radius=1)
```

Reach for Builder when you need a workplane, a selector-driven
operation (`fillet`, `chamfer`, `extrude until=...`), or a Location
pattern (`GridLocations`, `PolarLocations`, `HexLocations`).

## Sticking to documented API

Verify before inventing:

```python
import inspect, build123d
inspect.signature(build123d.Box)
# (length: float, width: float, height: float, ...)
```

For "is there a thing for X" questions, grep the cheat sheet or the
package source rather than guessing a plausible name.
