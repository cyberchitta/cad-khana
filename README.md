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

`khana view` pushes geometry to the OCP CAD Viewer, a standalone web
server. The easiest host is the
[VS Code extension](https://marketplace.visualstudio.com/items?itemName=bernhard-42.ocp-cad-viewer),
which embeds the viewer in an editor pane.

Any editor that can launch a task and open a browser tab also works:
run `python -m ocp_vscode` (from the cad-khana environment) to start
the viewer, then bind `khana view` to a task (e.g. a Zed
`tasks.json`).

The viewer is only needed for `khana view`; `khana build`, `khana
check`, and `khana render` work without it.

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

## Related work

The LLM-aided-CAD space is active. Where cad-khana sits:

**Direct peer.** [`llmcad`](https://pypi.org/project/llmcad/) is the closest
in shape: a minimal Python CAD library designed for LLMs to drive. It wraps
OCP (the OCCT Python bindings) directly rather than going through Build123d,
and its LLM-ergonomic bet is named faces/edges, face-local coordinates, and
multi-view PNG snapshots — no structured diagnostics or assertions.
cad-khana's bet is a different one — diagnostics JSON plus assertions on top
of an existing Build123d API, with renders as a complementary channel — so
the two are worth reading side by side.

**End-user CAD apps with chat UIs** — different category, not alternatives.
[FreeCAD AI](https://github.com/ghbalf/freecad-ai),
[TalkCAD](https://github.com/outerreaches/talkcad),
[CQAsk](https://github.com/OpenOrion/CQAsk), and
[CADialogue](https://github.com/Hiram31/CADialogue) are products a human opens
and chats with. cad-khana is a library an agent harness drives from a script;
there's no GUI and no chat surface.

**Substrate, not alternatives.**
[Build123d](https://build123d.readthedocs.io/) is what cad-khana wraps;
[CadQuery](https://cadquery.readthedocs.io/) and
[OpenSCAD](https://openscad.org/) are the obvious other code-CAD substrates a
similar tool could be built on.

**Different problem — text/image to CAD model weights.**
[CAD-Coder](https://github.com/AndresGuzman-Arenas/CAD-Coder),
[CADmium](https://github.com/CADmium-Co/CADmium), and
[BlenderLLM](https://github.com/FreedomIntelligence/BlenderLLM) train or
fine-tune models that emit CAD. cad-khana is tooling for the inference loop,
not a model — orthogonal work.

**Survey.**
[LLMs-CAD-Survey-Taxonomy](https://github.com/lichengzhanguom/LLMs-CAD-Survey-Taxonomy)
([arXiv:2505.08137](https://arxiv.org/abs/2505.08137)) is a reasonable map of
the broader landscape.

## Project documents

- `CLAUDE.md` — operational instructions for agents working on this
  repo.
- `NOTES.md` — design rationale, key decisions, open questions.
- `skills/cad-khana/SKILL.md` — agent-facing guide to using the tool.
- `skills/cad-khana-setup/SKILL.md` — one-shot installer skill that self-deletes after running `uv tool install`.

## License

Apache-2.0.
