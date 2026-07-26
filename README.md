# cad-khana

A CLI tool and agent skill for designing 3D-printable mechanisms in
[Build123d](https://build123d.readthedocs.io/), built for LLM-driven
iteration.

*khana* (ख़ाना) is a Hindustani suffix meaning "house" or "workshop"
— as in *kar-khana* (factory) or *dawa-khana* (pharmacy). cad-khana
is a place for CAD.

**Status:** early. API may still churn.

Used in practice to design the
[Sorted Studs LEGO scanner](https://sorted-studs.cyberchitta.cc/) —
every part drawn by an LLM via cad-khana.

## What it does

`cad-khana` wraps Build123d with a diagnostics-first workflow. You
(or an LLM agent) write Python modules that *declare* parts,
assemblies, and the claims they must satisfy; the `khana` CLI imports
a module and does one thing to it — check it, export STL/STEP, draw
it, or push it to a viewer. `khana check` writes a structured
`mechanism.json` reporting interferences, clearances, and every
assertion's result. A violated assertion fails the run, so geometric
constraints are enforced, not hoped for.

The tool is designed to close a specific gap: LLMs can reason about
CAD geometry from code but need explicit feedback on the things a
human would catch visually. Computed diagnostics cover the scalar
questions; `khana draw` produces engineering-drawing PNGs (HLR
line-art) a multimodal agent can read for shape-level questions that
numbers don't express well.

## Why it exists

Existing code-CAD tools (OpenSCAD, CadQuery, Build123d) assume a
human with a render window. For agent-driven design, a different
feedback loop works better:

1. Agent writes a Build123d module declaring parts, an assembly, and
   its assertions.
2. `khana check` imports it and writes diagnostics.
3. Agent reads diagnostics, edits the module, repeats.
4. When a shape-level question arises that diagnostics can't answer,
   the agent runs `khana draw` and reads the PNGs directly.
5. When the design is clean, a human reviews it in the OCP viewer, and
   `khana export` produces the printable geometry.

Humans stay in the loop for taste and physical-world validation;
correctness iteration happens in code.

## CLI

A **target** is `<module-path>[:<factory>]` — the module's `assembly`
member, or a named factory called with its defaults.

```
khana check  <target>       # diagnostics + assertions → mechanism.json
khana export <target>       # STL + STEP
khana view   <target>       # push to the OCP viewer
khana draw   <target>       # orthographic/iso engineering drawings (HLR line-art)
khana run    <script>       # execute an orchestration script (batches, sweeps)
khana diff   <old> <new>    # diff two diagnostics JSON files
```

Declaration modules call nothing effectful; every effect happens at
the CLI boundary, so the same file is safe under every verb.

## Install

### Claude Code skill (recommended for agent use)

Copy the skill into your project (loads only in this project's context):

```bash
git clone --depth=1 https://github.com/cyberchitta/cad-khana /tmp/cad-khana
cp -r /tmp/cad-khana/skills/cad-khana .claude/skills/
rm -rf /tmp/cad-khana
```

Or for all projects (loads everywhere):

```bash
git clone --depth=1 https://github.com/cyberchitta/cad-khana /tmp/cad-khana
cp -r /tmp/cad-khana/skills/cad-khana ~/.claude/skills/
rm -rf /tmp/cad-khana
```

The first time you ask Claude for CAD work, the skill notices `khana` isn't installed yet and follows `references/install.md` to run `uv tool install` once. After that, the skill loads automatically whenever you ask for CAD work.

### Manual install

From a local checkout (for development):

```bash
uv sync
uv run khana check assembly.py
```

As a global tool from GitHub:

```bash
uv tool install git+https://github.com/cyberchitta/cad-khana
```

### External tools

`export_glb` / `export_animated_glb` shell out to
[`gltf-transform`](https://gltf-transform.dev) for two post-processing
passes:

* `join` — merges primitives within each named node. OCP's
  `RWGltf_CafWriter` emits one primitive per face style (~30 per
  shape on real assemblies), which inflates the output glTF's JSON
  to multiples of the binary payload. Joining is mandatory and runs
  on every export.
* `draco` — re-encodes mesh attribute buffers with Draco
  compression. Optional (`draco=False` to skip).

Together they typically shrink a CAD glTF by ~10×. Install:

```bash
bun install -g @gltf-transform/cli   # or: npm install -g @gltf-transform/cli
```

Without the tool on `$PATH`, `export_glb` raises a `RuntimeError`
naming the install command. No Python equivalent exists for the
join pass — it's the reason we shell out.

## Viewer setup (for humans)

`khana view` pushes geometry to the OCP CAD Viewer, a standalone web
server. The easiest host is the
[VS Code extension](https://marketplace.visualstudio.com/items?itemName=bernhard-42.ocp-cad-viewer),
which embeds the viewer in an editor pane.

Any editor that can launch a task and open a browser tab also works:
run `python -m ocp_vscode` (from the cad-khana environment) to start
the viewer, then bind `khana view` to a task (e.g. a Zed
`tasks.json`).

The viewer is only needed for `khana view`; `khana check`, `khana
export`, and `khana draw` work without it.

## Example

A declaration module — parameters, pure part functions, and a factory
returning an `Assembly` with its claims. It calls nothing effectful:

```python
from build123d import Box, BuildPart, Location, Part

from cad_khana.mechanism.assembly import Assembly


def housing(width: float = 40, depth: float = 30, height: float = 20) -> Part:
    with BuildPart() as p:
        Box(width, depth, height)
    return p.part


def lever(length: float = 25) -> Part:
    with BuildPart() as p:
        Box(length, 5, 3)
    return p.part


def build_mechanism(lift_mm: float = 12.0) -> Assembly:
    return (
        Assembly()
        .with_part("housing", housing(), location=Location((0, 0, 0)))
        .with_part("lever",   lever(),   location=Location((0, 0, lift_mm)))
        .assert_no_interference("lever", "housing")
        .assert_clearance("lever", "housing", min_mm=0.2)
    )


assembly = build_mechanism()
```

```bash
khana check  assembly.py                  # → outputs/mechanism.json
khana check  assembly.py:build_mechanism  # the factory, called with defaults
khana export assembly.py                  # → outputs/assembly.{stl,step}
```

`skills/cad-khana/references/examples/pin_hinge/` is a complete worked
example. The conventions an agent needs — file kinds, claim taxonomy,
assertion reference, printability — are in
`skills/cad-khana/SKILL.md`; this README stays deliberately thin.

## Related work

The LLM-aided-CAD space is active. For a structured map see
[60 Alternatives to CAD Khana](https://www.cyberchitta.cc/articles/cad-llm-tools.html)
(May 2026), which splits the landscape by who closes the feedback loop:
agent-driven (the LLM iterates on structured diagnostics) vs.
human-directed (you inspect renders and steer).

cad-khana sits in the agent-driven half: structured JSON diagnostics let
an LLM iterate without human review.

## Project documents

- `CLAUDE.md` — operational instructions for agents working on this
  repo.
- `skills/cad-khana/SKILL.md` — agent-facing guide to using the tool.
- `skills/cad-khana/references/install.md` — one-shot install steps the skill follows on first use.

## License

Apache-2.0.
