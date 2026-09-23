# CLI: targets, output, imports, viewer, families

Load before addressing a `:factory`, when an output file is not where
you expected, when an import fails under `khana`, when setting up the
viewer, or before writing a script that checks several members of a
family. The verb list and exit codes are in `SKILL.md` §CLI.

## Targets: `<module-path>[:<factory>]`

```
khana check unit/assembly.py                 # the `assembly` member
khana check unit/assembly.py:build_rotor     # a named factory, called with defaults
```

Member resolution, in order:

1. `:factory` given → that name, which must be callable, called with
   **no arguments** — so a factory's defaults are the master design.
2. No `:factory` → the name `assembly`: a callable is called; a bare
   `Assembly` value is accepted as the **degenerate** form.
3. Neither → a usage error (exit 2) that **lists the module's public
   `-> Assembly` factories**. Read that message rather than grepping —
   it is the discovery mechanism, which is why the `-> Assembly` return
   annotation is load-bearing.

Binding arguments from the CLI is not supported: a factory is called
with its defaults or not at all. A family with several members (three
floor roles, twelve animation frames) is a command script today — see
**Parametrized families**.

## Where output lands

**The target owns its default out**, so co-located targets never
overwrite each other's `mechanism.json`:

| target | writes to |
|---|---|
| `unit/assembly.py` | `unit/outputs/` |
| `unit/check_cones.py` | `unit/outputs/check_cones/` |
| `unit/assembly.py:build_lid` | `unit/outputs/assembly-build_lid/` |

**`assembly` is a privileged *stem*, not "the unit's main file".** A
plain unit check whose file happens to be called `single_floor.py`
lands in `outputs/single_floor/`, not `outputs/`. If you are comparing
against a baseline by path, look in the subdirectory before reading a
missing file as a regression.

An explicit `--out <dir>` overrides and is taken **cwd-relative**
(you typed it). Inside a script under `khana run`, a relative `out=`
passed to `check()` / `inspect()` anchors to the *script's* directory,
so `out="outputs"` lands next to the script regardless of cwd.

## Imports resolve as if you had run the file directly

A **package member** (its directory and every ancestor up to the
package root carry an `__init__.py`) loads with `python -m` semantics:
the package root's parent goes on `sys.path` and relative imports
(`from .params import …`, `from ..shared import …`) resolve. A
**standalone** file gets its own directory on `sys.path`, so
`from assembly import clevis` finds the sibling. Both hold for import
verbs and for `khana run` alike, so a sub-assembly file can be both
imported by its composing parent and addressed standalone with no
`sys.path` bootstrapping of its own.

One caveat for standalone files: they are cached in `sys.modules`
under the **file stem**, so two different `assembly.py` files in one
process resolve to whichever loaded first. Inside a package tree this
cannot happen — another reason to use packages for anything with more
than one unit.

## Viewer: no editor required

`khana view` calls `ocp_vscode.show(...)`, which pushes geometry over
a local socket (default port 3939). The listener can be either the
**OCP CAD Viewer** VS Code extension *or* the **standalone viewer
server**, the separate `ocp-viewer` package:

```
uv run --with ocp-viewer python -m ocp_viewer   # listens on 3939; open http://localhost:3939/viewer
uv run khana view assembly.py                   # pushes geometry to whichever listener is up
```

(`ocp-vscode` 4.1 moved the standalone viewer out into `ocp-viewer`;
on 4.1+, `python -m ocp_vscode` only prints a "moved" notice. In an
environment locked to `ocp-vscode` < 4.1, `uv run python -m
ocp_vscode` is still the command.)

So you can drive the full `view` loop from any editor (or none at
all). For **Zed**, the pattern that matches the VS Code UX is a pair
of workspace tasks in `.zed/tasks.json` — one to start the viewer
server, one to push the current file to it:

```json
[
  {
    "label": "OCP viewer: start",
    "command": "uv",
    "args": ["run", "--with", "ocp-viewer", "python", "-m", "ocp_viewer"],
    "cwd": "$ZED_WORKTREE_ROOT",
    "allow_concurrent_runs": false
  },
  {
    "label": "khana view (current file)",
    "command": "cd \"$ZED_DIRNAME\" && uv run khana view \"$ZED_FILE\""
  }
]
```

## Parametrized families

The CLI addresses **one member per invocation**, and a factory is
called with its defaults. So a family — three floor roles, twelve
animation frames — is a command script:

```python
"""Check all three floor roles.

    khana run m05_diverter/ramp_mechanism/role_sweep.py

`khana check` on the sibling `assembly.py` covers the `middle` role
only (the factory default). `base` and `top` are checked here.
"""
from cad_khana.mechanism.check import check

from assembly import FLOOR_ROLES, make_assembly

for role in FLOOR_ROLES:
    check(make_assembly(role), out=f"outputs/{role}")
```

Two things make this safe rather than a workaround:

- **`khana run` defers failures.** Every iteration runs, every JSON on
  disk is current, and the run exits nonzero once at the end. Don't
  hand-roll failure accumulation or `raise SystemExit` — that
  duplicates the boundary and aborts the loop early.
- **Give each member its own `out=`.** A relative path anchors to the
  script's directory, and a per-member subdirectory is what keeps the
  twelfth frame from overwriting the first.

Name these `<family>_sweep.py`. The docstring's coverage sentence
matters most here: `khana check` on the sibling covers exactly one
member, and nothing signals that but the sentence.
