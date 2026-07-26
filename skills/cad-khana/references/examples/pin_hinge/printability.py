"""
Per-part printability for the pin hinge. A **command script**.

    khana run skills/cad-khana/references/examples/pin_hinge/printability.py

`khana check` on the sibling `assembly.py` covers the *mechanism* claims
— interference and clearance between the three parts. It does **not**
cover anything in this file. Printability is per-part and per-method, so
it is a batch of calls rather than a claim on the assembly, and a batch
is what `khana run` is for.

Writes `outputs/clevis-printability.json` and `outputs/tang-printability.json`.
The pin is stock hardware (a cylindrical rod) — bought, not printed, so
it gets no `inspect()`.
"""

from cad_khana.printability.inspect import inspect
from cad_khana.printability.methods import FDM

from assembly import PIN_HOLE_D, clevis, tang

# Both parts trip `overhang_max` at 90°: the crown of the horizontal
# pivot bore is a fully downward-facing face. That is real geometry, not
# a measurement artifact — which is why it is waived with a reason
# rather than silenced by loosening `overhang_max_deg`. A 4.6 mm bore
# self-bridges in PLA and the small crown sag lands inside the 0.3 mm
# pin clearance the assembly already asserts. Note the waiver cites the
# span it depends on: widen the bore and this rationale stops holding.
_BORE_CROWN = (
    f"crown of the horizontal {PIN_HOLE_D:.1f} mm pivot bore — a span that "
    "self-bridges in PLA, with the sag inside the asserted pin clearance"
)

inspect(
    clevis(), method=FDM(), out="outputs", name="clevis",
    waive={"overhang_max": _BORE_CROWN},
)
inspect(
    tang(), method=FDM(), out="outputs", name="tang",
    waive={"overhang_max": _BORE_CROWN},
)
