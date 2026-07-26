# pin_hinge

Canonical cad-khana example: a three-part pin hinge (clevis + tang + pin).

```
khana check  skills/cad-khana/references/examples/pin_hinge/assembly.py
khana run    skills/cad-khana/references/examples/pin_hinge/printability.py
khana export skills/cad-khana/references/examples/pin_hinge/assembly.py
khana view   skills/cad-khana/references/examples/pin_hinge/assembly.py
```

## Two files, because they are two kinds of thing

`assembly.py` is a **declaration module**. It holds parameters, pure part
functions, and `build_hinge()` — a factory returning an `Assembly` with
its claims attached. It calls nothing effectful. Each verb imports it and
does its own one thing, so the file is identical under `check`, `export`,
`draw`, and `view`.

`printability.py` is a **command script**. Per-part `inspect()` calls are
a batch, not a claim on the assembly, so they live behind `khana run`.
Its docstring opens with its own invocation line and says what `khana
check` on the sibling does *not* cover — without that sentence, "I ran
`khana check`, it was green" quietly means the printability checks never
ran.

The third kind — a **check module** (`check_*.py`, for claims about the
interaction of units, never imported by product code) — isn't needed
here: this mechanism is one unit. SKILL.md describes it.

## What it demonstrates

- **The factory contract.** `build_hinge(slot_clearance=…,
  pin_clearance=…)` is the module's public surface; its defaults are the
  master design. Overriding a clearance to ask "does it still pass at
  0.15?" is the same call a composing parent would make — not a special
  tool-facing entry point. The module-level `assembly = build_hinge()` is
  the tolerated *degenerate* form that lets `khana check <file>` resolve
  without a `:factory`.
- **Assertions as first-class claims.** `assert_no_interference` on all
  three pairs; `assert_clearance` for the tang's swing room and the pin's
  radial play.
- **A waiver with a reason.** Both printed parts trip `overhang_max` at
  90° — the crown of the horizontal pivot bore, which is real geometry.
  It is waived with a rationale that cites the bore span it depends on,
  rather than silenced by loosening `overhang_max_deg`. The threshold
  keeps catching real overhangs; the JSON keeps `passed: false` and
  records the reason under `warnings[].waived_failure`.

Edit any parameter (`PIN_D`, `CLEVIS_ARM_H`, `SLOT_CLEARANCE`) and re-run
to see the design update. Try `khana check
skills/cad-khana/references/examples/pin_hinge/assembly.py:build_hinge`
to address the factory directly — note it writes to
`outputs/assembly-build_hinge/`, since only the bare `assembly` stem
writes to plain `outputs/`.
