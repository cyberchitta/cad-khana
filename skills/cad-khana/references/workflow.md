# Workflow: design order, the iteration loop, when to stop

Load before starting a mechanism from a blank file, or when the same
failure has survived repeated fix attempts. This is process advice;
what a green check does not mean, and every warning kind, stay in
`SKILL.md`.

## Designing a new mechanism

When starting from a blank file, do these steps **in this order**.
Out-of-order work — most often, drawing before scalars are clean —
burns cycles on geometry that the diagnostics would have rejected for
free.

1. **Declare parts as pure functions.** One function per distinct
   printed body, taking parameters with defaults. No globals, no
   placement inside the function.
2. **Wire the assembly with explicit `Location`s, along its
   rigid-body boundaries.** Every relocatable unit with its own local
   frame, and every joint, is a `with_subassembly` node — declared
   from the start (a joint at angle 0 is fine), not bolted on later
   when animation needs it. A multi-part unit gets a
   `build_<name>() -> Assembly` builder in its own canonical frame;
   the parent places it via `location=`. A trivial mechanism with no
   such boundaries is a flat chain of
   `with_part(name, part(), location=…)` calls — the degenerate case,
   not the default shape. Names are stable IDs the assertions and
   diagnostics reference.
3. **Add `assert_no_interference` between *every* candidate-overlap
   pair immediately** — before any clearance work. The cost of
   asserting a pair that will never collide is one line; the cost of
   *not* asserting a pair that silently overlaps is a printed part
   you can't assemble. Default to over-asserting.
4. **Add `assert_distance(a, b, min_mm=…)` between every pair of
   parts that move relative to each other.** Pick a real number
   (≥ 0.2 mm for FDM at 0.4 mm nozzle) — not a placeholder you mean
   to revisit.
5. **Run `khana check` and iterate until all scalars are green.**
   Reading `mechanism.json` is the primary loop; do not draw yet.
6. **Then** `khana draw` for shape-level verification.
   `references/drawings.md` says which view answers which question.

The first pass at a new mechanism is the moment to be liberal with
assertions; pruning later (because one is provably redundant) is
cheap, but discovering a missing one downstream is expensive.

## Workflow

1. Write the declaration module. Use the canonical example
   (`references/examples/pin_hinge/`) as a template.
2. `khana check path/to/assembly.py` — and `khana run
   path/to/printability.py` once printed parts exist.
3. Read `outputs/mechanism.json` and each `outputs/<name>-printability.json`.
   - `status: "error"` → check `hint` first; if non-null it resolves the
     most common cases without reading the full traceback in `error`.
   - `status: "assertion_failed"` in mechanism → read `assertions` for
     failing entries. `interferences` often points directly at the
     root cause.
   - `status: "assertion_failed"` in a printability file → look at
     `min_wall_mm` and `overhang`; adjust the part's geometry or the
     `FDM` threshold.
   - All `status: "ok"` → design is clean. Consider whether you've
     asserted everything that matters (a silent passing check isn't
     proof; it's just no failures detected).
4. Edit parameters or geometry. Re-run. Repeat. After a change that
   moves a *global* dimension, draw one view before believing the
   green — a derived dimension nothing asserts moves with it.
5. When a question is shape-level rather than scalar ("is the tang
   pointing the right way", "did that cut land where I expected"), run
   `khana draw path/to/assembly.py` and read the views under
   `outputs/views/` — load `references/drawings.md` first.
6. When diagnostics are clean, ask the human to view it via
   `khana view path/to/assembly.py` (which pushes to the OCP VS Code
   viewer).

## When to stop iterating

Bounded loop: cap the repair cycle at **3–5 attempts** on the same
failure before stepping out. The cost of looping past that point is
context drift — earlier reasoning falls off, fixes start contradicting
each other, and the agent burns tokens re-deriving state it already
had.

Inside the loop, **feed the failure back into the next attempt**.
On a retry, the next prompt should carry forward the previous failing
script, the relevant `mechanism.json` (or `<name>-printability.json`)
slice, and the original task statement. Don't restart from scratch —
each iteration should be strictly more informed than the last.

When you hit the cap without convergence, **stop and escalate**: emit
a single line of the form

```
HUMAN_REVIEW: <one-sentence why> — last failure: <assertion or error>
```

and exit. Looping silently past 5 attempts wastes the human's
turnaround time and produces a worse handoff than a clean
"stuck-here-because-X" message. Common reasons to escalate:

- The same assertion fails after three substantive geometry edits
  (the constraint may be infeasible, or the spec needs to change).
- `status: "error"` repeats with the same `hint` after the suggested
  fix has been applied (the hint may be wrong for this case).
- Two assertions trade off against each other — fixing one breaks the
  other — and no clearance/wall budget exists that satisfies both.

Escalation is a feature, not a failure mode. A clean stop with
context beats a long thrash every time.
