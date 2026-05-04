# Design notes

Context and decisions for `cad-khana`. `CLAUDE.md` has the operational
instructions; this file has the reasoning. Future contributors (human or
agent) should be able to read this and understand why the project is shaped
the way it is, without re-deriving the decisions.

## Origin

Started from a conversation about what CAD tooling built for LLMs would look
like, given that current tools (OpenSCAD, CadQuery, Build123d) all assume a
human with a render window. The thesis: LLMs can reason about geometry from
code, but have blind spots around things a human would catch visually —
interferences, clearances, wall thickness, overhangs. A diagnostics-first
wrapper closes that gap by computing those checks and returning structured
JSON the agent can read after every build.

Rendered views are a complementary channel, not a human-only one. Modern
agent harnesses are multimodal, so PNGs fed back to the model handle the
shape-level questions that scalars express poorly. `khana render` is built
for the agent first; humans have the OCP viewer.

## Prior art worth knowing

- **CADAM** (github.com/Adam-CAD/CADAM) — browser text-to-CAD using OpenSCAD.
  Validated that code-as-design-representation works for LLMs. Missing the
  diagnostics layer; the LLM has no feedback beyond what the user describes.
- **CIP / CADDesigner** (arxiv.org/html/2508.01031v1, Aug 2025) — research
  showing that structured error diagnostics materially improve LLM iteration
  over CadQuery. Their ablation confirms that removing detailed error
  feedback slows convergence significantly. Direct validation of the
  diagnostics-layer thesis.
- **PartCAD** (partcad.readthedocs.io) — package manager for CAD models,
  Build123d-native. Adjacent project; could eventually be a source of
  importable parts but isn't competing.
- **Build123d-Cookbook** (github.com/khaledelhady44/Build123d-Cookbook) —
  community effort to build a training dataset for LLM CAD generation.
  Signals the community knows LLMs matter; work is on training, not runtime
  tooling.
- **llmcad** (pypi.org/project/llmcad/, GitHub URL currently 404; source
  read from `llmcad-0.3.0` sdist, ~1.4k LOC). Closest peer in shape — a
  minimal Python CAD library for LLMs, wrapping OCP directly. Bets purely
  on multimodal vision: zero structured diagnostics, no interference
  checks, no assertions; the entire feedback channel is `snapshot()` PNGs
  plus `print()`. That's a meaningful philosophical divergence — they
  trust the model's eyes; we trust cheap scalars first, vision second.
  Their existence is mild validation that the LLM-CAD-library category is
  real; their omission of diagnostics is mild validation that our bet is
  differentiated. Specific ideas worth revisiting if patterns emerge in
  field-notes:
  - **Multi-view 2x2 PNG with view-name overlays, 3-light Phong, parallel
    projection, edges sampled from topology.** `llmcad/_render.py`,
    `debug.py:snapshot`. Concrete polish for `khana render`; `--views 4`
    already exists, this is shape-for-shape what they do, just better-lit.
  - **Face-local `offset(dx, dy)` / `inset(dx, dy)` on a `Position` that
    knows its parent face's `(x_dir, y_dir, normal)`.** `llmcad/position.py`,
    `face.py`. Build123d has the primitives (`Plane`, `Location`) but
    requires explicit construction; this is strictly more ergonomic.
    Doesn't violate the no-semantic-primitives stance — it's a coordinate
    helper, not a domain abstraction. Candidate for a `mechanism.frame`
    helper if 2–3 user scripts hit awkward global-coord math.
  - **Named-faces convention** (`top`, `bottom`, `wall`, `_start`, `_end`)
    with auto-transfer through booleans (`llmcad/_naming.py`,
    `body.py:transfer_face_names`). The naming convention is borrowable;
    the transfer machinery probably isn't, because Build123d already has
    `face.sort_by(Axis.Z)[-1]` / `filter_by(Plane.XY)`. If this becomes a
    pattern, it belongs in SKILL.md as a scripting convention, not in the
    library.
  - **`measure(a, b)` print-and-return helper.** Trivial; only worth
    adding if scripts repeatedly want it.

  Skipped: their `RevoluteJoint` is a fields-only stub with no kinematics
  (violates no-semantic-primitives anyway); their `Box(diameter=, height=)`
  parameter renames clash with Build123d conventions our users know;
  operator booleans (`+`, `-`, `&`) are already in Build123d.
- **CADialogue** (github.com/Hiram31/CADialogue, doi 10.1016/j.cad.2025.104006)
  — chat-UI assistant for FreeCAD. Reviewed for prompt ideas; their
  system prompts are one-liners with no CAD-domain conventions, and
  their reported success rate comes from the self-refinement loop + image
  fallback (both harness concerns) rather than prompt sophistication.
  Nothing borrowable for SKILL.md. Logging the negative result so we
  don't re-mine.
- **FreeCAD AI** (github.com/ghbalf/freecad-ai) — most-developed of the
  chat-UI shortlist (workbench plugin, plan/act, vision, tool calling).
  Reviewed; most of their CAD content is FreeCAD/PartDesign-API footgun
  documentation (Body-required-before-PartDesign, Sketcher
  over-constraint, Revolution-with-full-circle, coplanar-boolean
  offsets) that build123d's algebraic mode simply doesn't need.
  Single weak candidate worth noting: a **`list_faces`-style helper**
  (`freecad_tools.py:1756-1885`) that returns faces by human label
  ("top", "front", "cylindrical R=10.0") so an agent can reference them
  without guessing edge indices. Build123d already supports the
  selection; the borrowable bit is the labeling layer. Defer until
  consumer scripts hit awkward face-selection.
- **TalkCAD** (github.com/outerreaches/talkcad) — Electron app for
  conversational OpenSCAD modeling. Substantially more substantive than
  the other chat UIs; ahead of us on intent capture, behind on
  diagnostic structure — the two are complementary. Concrete ideas
  worth revisiting if patterns emerge:
  - **Value-level spec record** (`agent-definitions.ts:281-305`,
    `verification.ts`). `set_spec(key, value, unit, critical, note)` with
    dotted-key namespaces (`internal_thread.diameter`,
    `body.shape`) records every named dimension as a traceable claim,
    not just as a value buried in the script. Would slot cleanly into
    `mechanism.json` as a `specs` array; orthogonal to our relational
    assertions and our per-part `inspect()` calls. Most actionable
    single idea from the whole prior-art scan.
  - **`critical=` flag on assertions** so scripts can mark
    structural-must-pass vs nice-to-have without changing exit
    semantics, and `khana diff` can surface critical regressions first.
  - **`note=` / `reason=` extension across all assertions and printability
    calls.** We already have `reason=` on the interference-allowance
    path; generalizing the pattern is a tiny API change with high
    traceability value.
  - **`FDM(material="PLA")` deriving a default `clearance_mm`** from a
    shrinkage table (PLA 0.3 % / PETG 0.5 % / ABS 0.8 % / TPU 1–2 %,
    `resources/skills/design-rules/fdm-printing.md`). Better default than
    "you must pass `min_mm` explicitly".
  - **Spatial-vocabulary translation block** for the agent-facing side
    of SKILL.md (`agent-definitions.ts:196-237`): an explicit axis
    diagram + a "user says X → axis Y" table so the agent can ground
    "front near bottom right" without re-deriving it. Our existing
    coordinate-frame guidance is for *user scripts*; this is the
    inverse, for the *agent reading user requests*.

  Skipped: their negotiation personalities (chat UX), researcher/builder
  agent split (driven by their web-scraping for components, which we
  delegate to `bd_warehouse`), OpenSCAD-specific footguns
  (`$fn`/`$fa`/`$fs`, epsilon overshoot), and the ISO 273 clearance-hole
  table (covered by `bd_warehouse` for fasteners; not worth duplicating).
- **CQAsk** (github.com/OpenOrion/CQAsk) — web UI + CadQuery generation,
  ~2024. Reviewed; their entire prompt is a CadQuery API cheat sheet
  with no parameter conventions, units guidance, sketch discipline, or
  structuring rules. Behind our SKILL.md on every axis. Nothing
  borrowable. Logged so we don't re-mine.

## Key decisions

**Build123d over CadQuery or OpenSCAD.** Build123d has active community
momentum, a proper B-rep kernel (OCCT), a clean Pythonic API, and is the
successor in spirit to CadQuery. OpenSCAD is mesh-based and can't do proper
fillets; CadQuery works but development has slowed relative to Build123d.

**Python implementation.** Considered Rust and Go for single-binary CLIs
with fast startup. Rejected because the tool's logic is entirely "call
Build123d, inspect the result" — a non-Python wrapper would add an IPC
boundary without adding capability. `uv` gives us the clean-install story
that previously motivated non-Python choices (`uv tool install cad-khana`,
`uvx khana ...`).

**CLI, not MCP, for v0.** MCP's verbosity earns its keep for auth, remote
servers, and multi-client distribution. None apply here. Agent harnesses
shell out to CLIs perfectly well. MCP can be added later over the same
`core/` modules without rewrites — hence the discipline of keeping CLI
logic out of `core/`.

**Diagnostics over constraint solving.** A real constraint solver is a
large project and not obviously better for the LLM loop than "compute what's
wrong and report it." Assertions give us constraint-like guarantees (build
fails if violated) without solver machinery.

**Immutable Assembly with method chaining.** Assembly is a frozen dataclass;
`add()` and `assert_*()` return new instances. This matches the functional
style expected throughout the codebase and makes the user-facing API pleasant
to read. Method chaining is idiomatic in the Build123d community (algebraic
mode already uses it) and fits naturally for a declarative assembly model.

**No semantic primitives in v0.** Resisted the temptation to ship `Shaft`,
`Gear`, `Bearing` classes. Those abstractions should grow from observed
patterns in real use, not be invented upfront. Build123d primitives plus
named assembly parts are the starting vocabulary.

**Mechanism and printability are separate workflows.** `Assembly` captures
relational constraints (interference, clearance). Printability is per-part
and depends on manufacturing method (FDM orientation, wall/overhang
thresholds). Conflating them on `Assembly` created three concrete problems
while using the tool on sorted-studs:
(1) `assert_min_wall` ran on non-printed stand-ins (extrusion stubs,
shafts), producing spurious numbers;
(2) `assert_min_wall` lived on `Assembly` even though it was a property of
one part, not the mechanism;
(3) overhang detection had no build-plate awareness, because the part's
print orientation didn't belong anywhere — you can't declare "this part
is printed with +Z up" on an assembly that has 20 parts.
The split — `mechanism.assembly.Assembly` + `mechanism.check.check()` for
relations, `printability.inspect.inspect(part, method=FDM())` for
per-part manufacturing — fixes all three. Build-plate orientation is now
a property of `FDM`, so the bottom-face false-positive disappears.

**User-script style is recommended, not enforced.** The library accepts any
Build123d `Part`. `SKILL.md` recommends functional patterns (pure part
functions, declarative assemblies, derived dimensions) because the agent
will be the primary author and functional scripts are more re-editable. But
a stateful or imported part should still work without friction.

**`bd_warehouse` bundled as a default dependency.** It's the Build123d-native
companion library for standard parts (fasteners, bearings, threads, gears,
V-slot extrusions, OpenBuilds hardware). The install cost is one
pure-Python package with no extra transitive deps beyond what `build123d`
already pulls in, and the whole point of cad-khana is friction-free agent
CAD — "agent stops mid-design to figure out installation" is exactly the
friction we want to avoid. cad-khana itself does not import it; user
scripts do. Idiom: wrap a `bd_warehouse` class call in a thin pure part
function so the script style stays consistent. The class-based parametric-
component idiom of `bd_warehouse` is fine to *consume* but not to
propagate into user scripts.

## Open questions

- **Min wall thickness accuracy.** Ray-cast point-sampling is the v0
  approximation. When does it fail badly enough to need a real medial-axis
  implementation? Record failure cases here as they come up.
  - 2026-04-25 — sorted-studs ran into sub-mm artifacts on multiple
    parts: 0.09 mm at faceted-frustum star-ridges (`m02 rotor`), 0.17–
    0.20 mm at thin annular bearing/spider edges (`m05 ramp_mechanism`),
    0.10 mm at a 45°-V-cone inner edge (`m02 stator`). All real walls
    were ≥ 1.5 mm by construction. Frequency was high enough that the
    project developed a local waiver pattern (see `field-notes.md`
    2026-04-25 entry). Suggests the FDM threshold ergonomics deserve
    first-class waiver support before medial-axis becomes priority.
- **Overhang threshold.** 45° default, but this is printer- and
  material-specific. Probably needs to become a per-build parameter (CLI
  flag or assembly-level setting) once we hit a case where the default is
  clearly wrong.
- **Large-assembly scaling.** O(n²) interference check is fine up to ~20
  parts. Defer optimization until there's a real mechanism that needs it.
- **Pattern extraction.** At what point does a mechanism pattern (hinge,
  four-bar, cam, snap-fit) recur often enough to justify a helper? Track
  in `references/examples/` as we build them.

## Known bugs / gotchas

- **`a & b` returns `None` for empty intersections.** Build123d's `&`
  operator returns `None` (not an empty `Part`) when two solids do not
  overlap — including concave cases where parts nestle together without
  sharing volume, e.g. a tang in a clevis slot. The v0
  `NoInterference.evaluate` assumed the result is always a `Part` and
  crashed with `AttributeError: 'NoneType' object has no attribute
  'volume'`. Fixed in `assertions.py` by treating `None` as zero-volume
  (no overlap = assertion passes). Surfaced while modeling a
  yoke-and-tang pivot in the sorted-studs `ramp_mechanism`.

## Things considered and rejected

- **Semantic primitives (Shaft, Gear) as v0 API.** Deferred; may earn their
  place once patterns emerge.
- **`cq_gears` as a default dependency.** Considered alongside `bd_warehouse`,
  rejected for v0. It's CadQuery-based, so consuming it from Build123d
  involves shape conversion and mismatched location semantics — interop
  cost without a concrete need. `bd_warehouse.gear` already covers
  involute spur gears, which is enough until a real use case forces the
  question.
- **MCP server as primary surface.** Deferred; CLI is sufficient and simpler
  for current agent harnesses.
- **Rust or Go CLI for distribution.** `uv tool install` removes the
  motivating pain point.
- **TypeScript CLI to match agent-harness ecosystem.** Harness language
  doesn't propagate to subprocess tools; would just add an IPC boundary.
- **Web UI or chat interface.** Out of scope. Claude Code (or any agent
  harness) is the chat.
- **Slider-based parameter editing (CADAM style).** Agent edits code
  directly; no human-UI sliders needed. Parameters are just Python variables.
- **Rendering orthographic views on every build.** Diagnostics cover the
  common case cheaply; renders are a targeted tool for shape-level questions
  the agent (or human) raises explicitly. On-demand, not automatic.
- **Constraint solver with first-class relationships.** Too much machinery
  for v0. Assertions plus diagnostics cover the needs we can see.

## Naming

Project is named `cad-khana` — "house of CAD" in Hindi/Urdu/Persian. The
suffix `-khana` (خانه) appears in workshop-flavored compounds like
`karkhana` (workshop/factory) and `davakhana` (pharmacy), which fits the
intent: a place where CAD gets made. CLI command is `khana`. Package on
PyPI: `cad-khana`. Python import: `cad_khana`.
