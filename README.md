# cad-khana

A CLI tool and agent skill for designing 3D-printable mechanisms in
[Build123d](https://build123d.readthedocs.io/), built for LLM-driven
iteration.

*khana* (ख़ाना) is a Hindustani suffix meaning "house" or "workshop"
— as in *kar-khana* (factory) or *dawa-khana* (pharmacy). cad-khana
is a place for CAD.

**Status:** early. API may still churn.

## What it does

`cad-khana` wraps Build123d with a diagnostics-first workflow. You
(or an LLM agent) write Python scripts that declare parts and
assemblies; the `khana` CLI runs them, exports STL/STEP, and writes
a structured `diagnostics.json` reporting interferences, clearances,
wall thickness, and overhangs. Assertions in the script become build
failures when violated, so geometric constraints are enforced, not
hoped for.

The tool is designed to close a specific gap: LLMs can reason about
CAD geometry from code but need explicit feedback on the things a
human would catch visually. Computed diagnostics cover the scalar
questions; `khana render` produces PNGs a multimodal agent can read
for shape-level questions that numbers don't express well.

## Why it exists

Existing code-CAD tools (OpenSCAD, CadQuery, Build123d) assume a
human with a render window. For agent-driven design, a different
feedback loop works better:

1. Agent writes a Build123d script.
2. `khana build` runs it, exports geometry, writes diagnostics.
3. Agent reads diagnostics, edits the script, repeats.
4. When a shape-level question arises that diagnostics can't answer,
   the agent runs `khana render` and reads the PNGs directly.
5. When the design is clean, a human reviews it in the OCP viewer.

Humans stay in the loop for taste and physical-world validation;
correctness iteration happens in code.

## CLI

```
khana build <path>      # run script, export, write diagnostics.json
khana check <path>      # diagnostics only, no export
khana view <path>       # build + push to OCP viewer
khana render <path>     # orthographic/iso PNGs for the agent to read
khana diff <old> <new>  # diff two diagnostics.json files
```

## Install

### Claude Code skill (recommended for agent use)

Copy both skills into your project (loads only in this project's context):

```bash
git clone --depth=1 https://github.com/cyberchitta/cad-khana /tmp/cad-khana
cp -r /tmp/cad-khana/skills/cad-khana .claude/skills/
cp -r /tmp/cad-khana/skills/cad-khana-setup .claude/skills/
rm -rf /tmp/cad-khana
```

Or for all projects (loads everywhere):

```bash
git clone --depth=1 https://github.com/cyberchitta/cad-khana /tmp/cad-khana
cp -r /tmp/cad-khana/skills/cad-khana ~/.claude/skills/
cp -r /tmp/cad-khana/skills/cad-khana-setup ~/.claude/skills/
rm -rf /tmp/cad-khana
```

Then ask Claude to run `/cad-khana-setup` — it installs the `khana` CLI via `uv tool install` and removes itself. After that, the `cad-khana` skill is loaded automatically when you ask Claude for CAD work.

### Manual install

From a local checkout (for development):

```bash
uv sync
uv run khana build assembly.py
```

As a global tool from GitHub:

```bash
uv tool install git+https://github.com/cyberchitta/cad-khana
```

## Viewer setup (for humans)

Geometry previews render in VS Code via the
[OCP CAD Viewer](https://marketplace.visualstudio.com/items?itemName=bernhard-42.ocp-cad-viewer)
extension. Install it once, open the viewer pane, and `khana view`
will push assemblies to it.

The VS Code extension is not required for `khana build` or
`khana check`; only `khana view` needs it.

## Example

```python
from build123d import *

from cad_khana.core.assembly import Assembly
from cad_khana.core.build import build


def housing(width: float = 40, depth: float = 30, height: float = 20):
    with BuildPart() as p:
        Box(width, depth, height)
    return p.part


def lever(length: float = 25):
    with BuildPart() as p:
        Box(length, 5, 3)
    return p.part


assembly = (
    Assembly()
    .add("housing", housing(), location=Location((0, 0, 0)))
    .add("lever",   lever(),   location=Location((0, 0, 12)))
    .assert_no_interference("lever", "housing")
    .assert_clearance("lever", "housing", min_mm=0.2)
    .assert_min_wall("housing", min_mm=1.5)
)

build(assembly, out="outputs/")
```

## Project documents

- `CLAUDE.md` — operational instructions for agents working on this
  repo.
- `NOTES.md` — design rationale, key decisions, open questions.
- `skills/cad-khana/SKILL.md` — agent-facing guide to using the tool.
- `skills/cad-khana-setup/SKILL.md` — one-shot installer skill that self-deletes after running `uv tool install`.

## License

Apache-2.0.
