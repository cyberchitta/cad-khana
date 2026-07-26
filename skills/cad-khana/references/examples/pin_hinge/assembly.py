"""
Pin hinge — canonical cad-khana example. A **declaration module**.

A three-part mechanism: a U-shaped clevis, a flat tang that swings in its
slot, and a pin passing through both. The design shows the workflow
``cad-khana`` is built for:

* parameters and derived dimensions at the top, so one constant change
  propagates through the whole assembly;
* pure part functions that return Build123d ``Part`` values;
* declarative assembly composition via method chaining;
* mechanism assertions (no interference, clearance) declared on the
  assembly, so a verb evaluates them.

This file **calls nothing effectful** — no ``check()``, no ``inspect()``,
no export. Its public surface is the factory ``build_hinge()``; the verbs
import it and each does its own one thing::

    khana check  .../pin_hinge/assembly.py       # outputs/mechanism.json
    khana export .../pin_hinge/assembly.py       # outputs/assembly.{stl,step}
    khana draw   .../pin_hinge/assembly.py       # outputs/views/*.png
    khana view   .../pin_hinge/assembly.py       # push to the OCP viewer

Per-part printability lives in the sibling command script:
``khana run .../pin_hinge/printability.py``.
"""

from build123d import Box, Cylinder, Location, Part, Pos, Rot

from cad_khana.mechanism.assembly import Assembly


# --- Parameters ---------------------------------------------------------

PIN_D = 4.0             # hinge pin diameter
PIN_CLEARANCE = 0.3     # radial clearance between pin and pivot holes
SLOT_CLEARANCE = 0.5    # gap between each tang face and the facing arm

TANG_L = 40.0           # tang length along its own +X
TANG_T = 4.0            # tang thickness (aligned with pin axis)
TANG_W = 12.0           # tang height perpendicular to length and thickness
TANG_PIVOT_OFFSET = 6.0 # distance from the tang's near end to its pivot hole

CLEVIS_L = 20.0         # clevis length along the pin axis
CLEVIS_BASE_T = 5.0     # thickness of the clevis base plate
CLEVIS_ARM_T = 3.0      # thickness of each arm
CLEVIS_ARM_H = 14.0     # arm height above the base plate


# --- Derived ------------------------------------------------------------

PIN_HOLE_D = PIN_D + 2 * PIN_CLEARANCE
SLOT_GAP = TANG_T + 2 * SLOT_CLEARANCE
CLEVIS_W = SLOT_GAP + 2 * CLEVIS_ARM_T
PIN_L = CLEVIS_W + 4.0
PIVOT_Z = CLEVIS_BASE_T + CLEVIS_ARM_H / 2


# --- Parts --------------------------------------------------------------

def pin(length: float = PIN_L, diameter: float = PIN_D) -> Part:
    """Cylindrical hinge pin; cylinder axis along +Z in its local frame."""
    return Cylinder(diameter / 2, length)


def tang(
    length: float = TANG_L,
    thickness: float = TANG_T,
    width: float = TANG_W,
    hole_d: float = PIN_HOLE_D,
    pivot_offset: float = TANG_PIVOT_OFFSET,
) -> Part:
    """Flat plate with a pivot hole near one end.

    Plate extends along +X from the origin. The pivot hole axis runs
    along Y so the thin dimension of the plate lines up with the hinge.
    """
    plate = Pos(length / 2, 0, 0) * Box(length, thickness, width)
    hole = (
        Pos(pivot_offset, 0, 0)
        * Rot(90, 0, 0)
        * Cylinder(hole_d / 2, thickness * 2)
    )
    return plate - hole


def clevis(
    length: float = CLEVIS_L,
    base_t: float = CLEVIS_BASE_T,
    arm_t: float = CLEVIS_ARM_T,
    arm_h: float = CLEVIS_ARM_H,
    slot_gap: float = SLOT_GAP,
    hole_d: float = PIN_HOLE_D,
    pivot_z: float = PIVOT_Z,
) -> Part:
    """U-bracket with a base plate and two arms; pivot hole axis along Y."""
    width = slot_gap + 2 * arm_t
    base = Pos(0, 0, base_t / 2) * Box(length, width, base_t)
    arm_offset_y = slot_gap / 2 + arm_t / 2
    arm_z = base_t + arm_h / 2
    arm_plus = Pos(0, arm_offset_y, arm_z) * Box(length, arm_t, arm_h)
    arm_minus = Pos(0, -arm_offset_y, arm_z) * Box(length, arm_t, arm_h)
    body = base + arm_plus + arm_minus
    pivot_hole = (
        Pos(0, 0, pivot_z)
        * Rot(90, 0, 0)
        * Cylinder(hole_d / 2, width + 2)
    )
    return body - pivot_hole


# --- Assembly -----------------------------------------------------------


def build_hinge(
    slot_clearance: float = SLOT_CLEARANCE,
    pin_clearance: float = PIN_CLEARANCE,
) -> Assembly:
    """The hinge, with its claims. Defaults are the master design.

    This is the module's public surface. A *member* is this factory plus
    an argument binding; calling it with defaults is what the CLI does,
    and what a composing parent would do to place the master. Overriding
    a clearance is how you ask "does it still pass at 0.15?" — the same
    call a parent makes, not a special tool-facing entry point.
    """
    slot_gap = TANG_T + 2 * slot_clearance
    hole_d = PIN_D + 2 * pin_clearance
    return (
        Assembly()
        .with_part("clevis", clevis(slot_gap=slot_gap, hole_d=hole_d))
        .with_part(
            "tang",
            tang(hole_d=hole_d),
            location=Location((-TANG_PIVOT_OFFSET, 0, PIVOT_Z)),
        )
        .with_part(
            "pin",
            pin(),
            location=Location((0, 0, PIVOT_Z)) * Rot(90, 0, 0),
        )
        .assert_no_interference("tang", "clevis")
        .assert_no_interference("pin", "clevis")
        .assert_no_interference("pin", "tang")
        .assert_clearance("tang", "clevis", min_mm=0.3)
        .assert_clearance("pin", "clevis", min_mm=0.2)
    )


# The degenerate form: a memoized master, so `khana check <file>` with no
# `:factory` resolves. Tolerated and documented, not the contract — the
# factory above is. Parents call `build_hinge()`, never this.
assembly = build_hinge()
