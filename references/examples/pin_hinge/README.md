# pin_hinge

Canonical cad-khana example: a three-part pin hinge (clevis + tang + pin).

```
khana build references/examples/pin_hinge/assembly.py
khana view  references/examples/pin_hinge/assembly.py
```

`assembly.py` demonstrates the full recommended pattern — parameters
and derived dimensions at the top, pure part functions in the middle,
and a declarative `Assembly` with assertions at the bottom. Edit any
parameter (e.g., `PIN_D`, `CLEVIS_ARM_H`) and re-run to see the design
update.

The example exercises every v0 assertion type:

- `assert_no_interference` — all three parts are disjoint.
- `assert_clearance` — the tang has room to swing in the slot; the pin
  has radial play in its bore.
- `assert_min_wall` — the clevis's thinnest feature stays above the
  printability floor.
