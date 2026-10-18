# CAD Khana

An agent-first assembly and test layer for
[build123d](https://build123d.readthedocs.io/): a CLI tool and agent
skill for designing 3D-printable mechanisms.

An LLM agent, using CAD Khana as a skill, writes parts in plain
build123d, composes them into assemblies with joints and motion, and
states claims about them: no interference, a minimum distance, a
printable wall. CAD Khana checks the claims on every run, reports
structured diagnostics the agent iterates on, and writes what the
person on the other end needs: printable files, drawings, renders,
and a viewer page to explore the assembly in.

No person looks at the model while the agent iterates. The diagnostics
are one way the agent knows whether a design is right, so CAD Khana
reports what was checked as well as what was found.

*khana* (ख़ाना) is a Hindustani suffix meaning "house" or "workshop"
— as in *kar-khana* (factory) or *dawa-khana* (pharmacy). CAD Khana
is a place for CAD.

**Status:** early. API may still churn.

## Read more

- [A LEGO Sorter Designed by Claude](https://sorted-studs.cyberchitta.cc/)
  — the machine CAD Khana was built to design, every part drawn by an
  LLM. The article shows what the tool produces: interactive GLB
  models, engineering drawings and renders.
- [Tools for Vibe Cading](https://www.cyberchitta.cc/articles/cad-llm-tools.html)
  — a survey of open source tools that connect LLMs to CAD, split by
  who closes the feedback loop: the agent, on structured diagnostics,
  or a person, on renders.
- [CAD Khana: The Assembly That Tests Itself](https://www.cyberchitta.cc/articles/cad-khana.html)
  — four defects in the sorter that its part files could not show,
  and how CAD Khana grew to check claims through a motion and against
  keep-outs.
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

`khana view` builds its viewer page with [bun](https://bun.sh), once
for each version of the page, so it needs `bun` on the PATH. No other
verb does.

### Rendering (optional)

Photo-real rendering runs Blender as a Python module (`bpy`). The wheel
is about 700 MB, so it is an extra and nothing else needs it:

```bash
uv tool install "cad-khana[render] @ git+https://github.com/cyberchitta/cad-khana"
```

`bpy` is licensed GPL-3.0. CAD Khana is Apache-2.0 and does not include
it; installing the extra fetches it from PyPI.

## License

Apache-2.0.
