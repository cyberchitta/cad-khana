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

**User-script style is recommended, not enforced.** The library accepts any
Build123d `Part`. `SKILL.md` recommends functional patterns (pure part
functions, declarative assemblies, derived dimensions) because the agent
will be the primary author and functional scripts are more re-editable. But
a stateful or imported part should still work without friction.

## Open questions

- **Min wall thickness accuracy.** Ray-cast point-sampling is the v0
  approximation. When does it fail badly enough to need a real medial-axis
  implementation? Record failure cases here as they come up.
- **Overhang threshold.** 45° default, but this is printer- and
  material-specific. Probably needs to become a per-build parameter (CLI
  flag or assembly-level setting) once we hit a case where the default is
  clearly wrong.
- **Large-assembly scaling.** O(n²) interference check is fine up to ~20
  parts. Defer optimization until there's a real mechanism that needs it.
- **Pattern extraction.** At what point does a mechanism pattern (hinge,
  four-bar, cam, snap-fit) recur often enough to justify a helper? Track
  in `references/examples/` as we build them.

## Things considered and rejected

- **Semantic primitives (Shaft, Gear) as v0 API.** Deferred; may earn their
  place once patterns emerge.
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
