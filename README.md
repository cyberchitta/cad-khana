# cad-khana

An agent-first assembly and test layer for
[build123d](https://build123d.readthedocs.io/): a CLI tool and agent
skill for designing 3D-printable mechanisms.

*khana* (ख़ाना) is a Hindustani suffix meaning "house" or "workshop"
— as in *kar-khana* (factory) or *dawa-khana* (pharmacy). cad-khana
is a place for CAD.

**Status:** early. API may still churn.

Used in practice to design the
[Sorted Studs LEGO scanner](https://sorted-studs.cyberchitta.cc/) —
every part drawn by an LLM via cad-khana.

## What it does

The parts are plain build123d. cad-khana is the layer above them, and
it does three things with an assembly.

**It composes.** Named parts are placed into an `Assembly`; assemblies
nest as sub-assemblies with joints and anchors, and a joint's travel is
declared as a motion.

**It holds claims.** An assembly carries assertions about itself: no
interference, a minimum distance, a permitted or required contact, a
part kept out of a volume another part sweeps, one footprint within
another. A claim can be scoped to a named region of a part or to a
phase of a motion. `khana check` evaluates every claim at the as-built
pose and at each sampled pose of every declared motion, and writes a
structured `mechanism.json`. A violated claim fails the run, so a
geometric constraint is enforced, not hoped for. Per-part printability,
minimum wall thickness and overhangs for FDM, is checked by `inspect()`
calls in a script run with `khana run`. A reading that fails for a
reason you accept is waived with that reason and the bounds it holds
for, and stays a recorded failure.

**It produces the outputs.** STL and STEP for the printer, hidden-line
engineering drawings, a GLB for a web viewer, and photo-real renders
through Blender, all from the same declaration the claims were held on.

The tool reports what it looked at as well as what it found: a claim
that was skipped, a motion that moved nothing and a part made of
several solids are all named in the output, so a green run can be told
apart from a question that was never asked.

## Why it exists

Code-CAD tools (OpenSCAD, CadQuery, build123d) assume a person at a
viewport, checking each change by eye. An agent designing a mechanism
works differently: it writes the geometry, and nobody looks before it
decides the design is right. So the tool has to tell it.

1. The agent writes a build123d module declaring parts, an assembly,
   and its claims.
2. `khana check` imports it and writes diagnostics.
3. The agent reads them (`khana show` summarises and filters), edits
   the module, and repeats.
4. For a shape-level question the numbers answer poorly, the agent runs
   `khana draw` and reads the drawings.
5. When the design is clean, `khana export` writes the printable
   geometry, and a render shows it to whoever it is for.

People stay in the loop for taste and for the physical world: whether
the print works is not something a session can check.

## CLI

A **target** is `<module-path>[:<factory>]` — the module's `assembly`
member, or a named factory called with its defaults.

```
khana check  <target>       # hold every claim → mechanism.json
khana export <target>       # STL + STEP
khana view   <target>       # push to the OCP viewer
khana draw   <target>       # orthographic/iso engineering drawings (HLR line-art)
khana run    <script>       # execute a script: printability batches, sweeps, renders
khana show   <json>         # read one diagnostics file: summary, filters, groups
khana diff   <old> <new>    # diff two diagnostics files
khana status                # environment and viewer reachability
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

Python 3.13 is required.

### Rendering (optional)

Photo-real rendering runs Blender as a Python module (`bpy`). The wheel
is about 700 MB, so it is an extra and nothing else needs it:

```bash
uv tool install "cad-khana[render] @ git+https://github.com/cyberchitta/cad-khana"
```

`bpy` is licensed GPL-3.0. cad-khana is Apache-2.0 and does not include
it; installing the extra fetches it from PyPI.

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
run `uv run --with ocp-viewer python -m ocp_viewer` (from the
cad-khana environment) to start the standalone viewer, open
<http://localhost:3939/viewer>, then bind `khana view` to a task (e.g.
a Zed `tasks.json`). The standalone viewer is its own package since
`ocp-vscode` 4.1; on an environment locked to an older `ocp-vscode`,
`python -m ocp_vscode` starts it instead.

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
        .assert_distance("lever", "housing", min_mm=0.2)
    )


assembly = build_mechanism()
```

```bash
khana check  assembly.py                  # → outputs/mechanism.json
khana check  assembly.py:build_mechanism  # the factory, called with defaults
khana export assembly.py                  # → outputs/assembly.{stl,step}
```

A render script is a few lines more, run with `khana run`:

```python
from assembly import build_mechanism

from cad_khana.render.render import render
from cad_khana.render.scene import Scene

scene = Scene.from_assembly(build_mechanism()).with_materials({"lever": "steel"})
render(scene, out="renders", world_up=(0, 0, 1))  # → renders/render.png
```

`skills/cad-khana/references/examples/pin_hinge/` is a complete worked
example. The conventions an agent needs start at
`skills/cad-khana/SKILL.md`, which names the reference file to load
for each task (assertions, composition, motion, printability,
diagnostics, rendering); this README stays deliberately thin.

## Related work

The LLM-aided-CAD space is active. For a structured map see
[60 Alternatives to CAD Khana](https://www.cyberchitta.cc/articles/cad-llm-tools.html)
(May 2026), which splits the landscape by who closes the feedback loop:
agent-driven (the LLM iterates on structured diagnostics) vs.
human-directed (you inspect renders and steer).

cad-khana sits in the agent-driven half: structured diagnostics let an
LLM iterate to a clean design before a person looks at it.

## Project documents

- `CLAUDE.md` — operational instructions for agents working on this
  repo.
- `skills/cad-khana/SKILL.md` — agent-facing guide to using the tool:
  the file kinds, what a green check does not mean, and which reference
  to load when.
- `skills/cad-khana/references/` — the detail, loaded on demand.
- `skills/cad-khana/references/install.md` — one-shot install steps the skill follows on first use.

## License

Apache-2.0.
