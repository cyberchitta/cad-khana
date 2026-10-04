# CLI: targets, output, imports, viewer, families, reading the JSON

Load before addressing a `:factory`, when an output file is not where
you expected, before a run whose outputs must stay apart (a before/after
baseline, parallel runs), when an import fails under `khana`, when
setting up the viewer, before writing a script that checks several
members of a family, before checking a subset of the claims or viewing
part of the tree, or before querying a diagnostics JSON too large to
read whole. The verb list and exit codes are in `SKILL.md` §CLI.

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

`khana run --out-root <dir>` (or `KHANA_OUT_ROOT=<dir>`) moves every
**relative** `out=` of the script's `check()` / `inspect()` calls under
`<dir>`, at the anchored directory's path relative to the cwd: run from
the repo root, `cad/m02/printability.py` with `out="outputs"` writes to
`<dir>/cad/m02/outputs/`. Different scripts under one root therefore
never collide, so two parallel runs of one unit each take their own
root, and a before/after baseline is two roots handed to `khana diff`.
An anchor outside the cwd (a scratch probe) mirrors its full absolute
path under the root. **An absolute `out=` is left alone** — it still
writes where it says. Without `--out`, the error diagnostics of a
failed script go under the root too; an explicit `--out` is not moved.
Exporters (`export_assembly`, GLB) do not read the root.

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

`khana run` also puts the **current directory** on `sys.path`, after
the script's own root, so a scratch probe outside the repo
(`khana run /tmp/probe.py` from the repo root) imports the repo's
packages without `PYTHONPATH=.`.

`khana run` passes the script no arguments: anything after the script's
path is parsed as an option of `run` itself, so it fails. Parametrize a
scratch script with environment variables instead
(`FACES=-Z khana run sweep.py`, read with `os.environ.get`).

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

## One run over a subset: `check --only`, `view --only` / `--hide`

```
khana check assembly.py --only 'clear_of:*'                 # hold only these claims
khana check assembly.py --only 'clear_of:*' --only 'gap_*'  # repeatable: any glob
khana view assembly.py --only s1                            # s1 and everything under it
khana view assembly.py --hide s1.arm --hide frame           # everything but these
```

**`check --only <glob>`** holds only the assertions whose name matches
(`fnmatch`, case-sensitive: `*`, `?`, `[...]` — a literal `[` in a name
is written `[[]`), over every declared motion as usual, and still
writes `mechanism.json`. It is a **partial run**, and the file says so
three ways: `selection` records the globs and `declared` / `evaluated`
counts, a `partial_run` warning is listed, and stderr says
`partial run: N of M assertions (only …); interferences not computed —
not a whole-model result`. The all-pairs interference pass — on a
large tree most of a check's time — is skipped, so `interferences` is
`null`, not `[]`. A glob that matches no assertion is a usage error
(exit 2) that writes nothing: a typo would otherwise evaluate zero
claims and exit 0. Each glob must match something, so one typo among
several is caught too. A contact claim's `during=` phase is still read
against every claim on its pair, selected or not.

Use it to watch a claim family go red and green while you edit; close
with a whole run before believing the model is clean. `khana diff`
refuses a partial file against a full one, or against another
selection — the claims one side left out would read as removed — and
compares two runs of the same `--only`.

**`view --only` / `--hide <path>`** filter what is pushed by dotted tree
path (`s1`, `s1.arm`, `frame`): a path names a part or a whole
sub-assembly (every part under it; `s1` never matches `s10`), both are
repeatable, and `--hide` applies after `--only`. An unknown path is a
usage error (exit 2) naming close matches. The push nests parts by
sub-assembly, so the viewer's tree has a row for `s1` to toggle. (`draw
--part` still takes one part name.)

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

## Reading the JSON: `khana show`

A top-level `mechanism.json` can hold tens of thousands of claims.
`khana show <file>` reads one `mechanism.json` or
`<name>-printability.json` and prints a summary — status, a
`partial run:` line when the file is one, the counts of
passed / failed / waived / skipped assertions (skips by class), warnings
by kind — then one line per assertion: state (`ok`, `FAIL`, `waived`,
`skip`), `value` (`-` when the claim records none), name, and `detail`
cut to one line.

```
khana show outputs/mechanism.json                       # summary + the first 50 claims
khana show outputs/mechanism.json --failed              # unwaived failures only
khana show outputs/mechanism.json --skipped             # skipped claims, each with why
khana show outputs/mechanism.json --grep clears --sort value --limit 5
khana show outputs/mechanism.json --group '^[^:]+'      # one line per claim family
khana show outputs/mechanism.json --failed --json | jq -r '.[].name'
```

- `--grep` is a regex searched in the name; `--failed` and `--skipped`
  select by state, and together select either. A waived failure is not
  `--failed` — it is listed with the rest, marked `waived`.
- `--sort value` is ascending, with valueless claims last. Ascending is
  the tight end for a distance or a clearance, and the loose end for an
  overlap volume — read which kind you sorted.
- Text output stops at 50 lines and says how many it left out;
  `--limit N` changes that, `--limit 0` prints all.
- `--group <regex>` prints one line per key instead: the regex's first
  capture group, or its whole match when it has none; names it misses
  share `(unmatched)`. Each line carries the count, how many failed,
  were waived or skipped, and the least `value` with the claim that has
  it. `--group '^[^:]+'` keys on the claim kind with its qualifier
  (`no_interference`, `m05.f1.tangent_contact`); a claim named without
  a kind prefix is its own group.
- `--json` prints the matching assertions (or groups) as a JSON list,
  unlimited unless `--limit` is given — for `jq`, not for reading.

It exits 0 whatever the file says — it is a reader, not a verdict — and
2 when the file is not a diagnostics file or an option is malformed.
Unlike `diff`, it reads a file at an older `schema_version`, as
written, and the summary's first line names both versions: it compares
nothing, so there is no second schema to coerce, but a field's meaning
is the current one only after a re-run. A summary field the older
schema lacks reads `absent`, never a zero — `interferences absent` is
a file that never had the field, not one that found none.
