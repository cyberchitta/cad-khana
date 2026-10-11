# cad-khana

An agent-first assembly and test layer for
[build123d](https://build123d.readthedocs.io/): a CLI tool and agent
skill for designing 3D-printable mechanisms.

An LLM agent writes parts in plain build123d. cad-khana composes them
into assemblies with joints and motion, holds claims about them (no
interference, a minimum distance, a printable wall), and produces what
the person on the other end needs: printable files, drawings and
renders. Nobody checks the agent's work before it believes it, so the
tool reports structured diagnostics the agent iterates on, and says
what it looked at as well as what it found.

*khana* (ख़ाना) is a Hindustani suffix meaning "house" or "workshop"
— as in *kar-khana* (factory) or *dawa-khana* (pharmacy). cad-khana
is a place for CAD.

**Status:** early. API may still churn.

## Read more

- [A LEGO Sorter Designed by Claude](https://sorted-studs.cyberchitta.cc/)
  — the machine cad-khana was built to design, every part drawn by an
  LLM. The article shows what the tool produces: interactive GLB
  models, engineering drawings and renders.
- [Tools for Vibe Cading](https://www.cyberchitta.cc/articles/cad-llm-tools.html)
  — a survey of open source tools that connect LLMs to CAD, split by
  who closes the feedback loop: the agent, on structured diagnostics,
  or a person, on renders.
- `skills/cad-khana/SKILL.md` — how the tool works. It is written for
  the agent and is the real documentation; it names the reference file
  to load for each task. `skills/cad-khana/references/examples/pin_hinge/`
  is a complete worked example.

## Install

### Claude Code skill (recommended for agent use)

Copy the skill into your project (loads only in this project's context):

```bash
git clone --depth=1 https://github.com/cyberchitta/cad-khana /tmp/cad-khana
cp -r /tmp/cad-khana/skills/cad-khana .claude/skills/
rm -rf /tmp/cad-khana
```

Or for all projects, copy it to `~/.claude/skills/` instead.

The first time you ask Claude for CAD work, the skill notices `khana`
isn't installed yet and follows `references/install.md` to run
`uv tool install` once.

### Manual install

```bash
uv tool install git+https://github.com/cyberchitta/cad-khana
```

Python 3.13 is required. From a local checkout, `uv sync`.

### Rendering (optional)

Photo-real rendering runs Blender as a Python module (`bpy`). The wheel
is about 700 MB, so it is an extra and nothing else needs it:

```bash
uv tool install "cad-khana[render] @ git+https://github.com/cyberchitta/cad-khana"
```

`bpy` is licensed GPL-3.0. cad-khana is Apache-2.0 and does not include
it; installing the extra fetches it from PyPI.

## License

Apache-2.0.
