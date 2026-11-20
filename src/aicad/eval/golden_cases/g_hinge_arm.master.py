# Master model (recorded): hinged arm on a clevis base (FX-06 sizes). One coordinate system, Z up, the base plate on
# Z = 0. Hand values: plate 80 x 40 x 8; lugs 8 thick, 24 apart (Y ±12 .. ±20), up to Z 30 (envelope 80 x 40 x 30);
# pivot 24 above the underside at X -25; arm 100 x 22 x 12 centred on the pivot height (Z 18 .. 30), its pivot bore
# 11 from its -X end (X -36 .. 64), 1 mm clear of each lug; Ø8 bores through both lugs and the arm (the Ø8 x 40 pin
# is bought out: only its bores are modelled); two Ø6.6 fixing holes in the plate at X ±30.
from build123d import *

from aicad.master import kit as mk

PL, PW, PT = 80.0, 40.0, 8.0
LUG_T, GAP, H = 8.0, 24.0, 30.0
PIVOT_X, PIVOT_Z, PIN_D = -25.0, 24.0, 8.0
ARM_L, ARM_W, ARM_T = 100.0, 22.0, 12.0

ly = GAP / 2 + LUG_T / 2
clevis = mk.box(PL, PW, PT, (0, 0, PT / 2))
for sy in (-1, 1):
    clevis = clevis + mk.box(PL, LUG_T, H - PT, (0, sy * ly, PT + (H - PT) / 2))
clevis = clevis - mk.cyl(PIN_D, PW, (PIVOT_X, 0, PIVOT_Z), "y")
for x in (-30.0, 30.0):
    clevis = mk.drill(clevis, (x, 0, PT), 6.6, PT, "z", -1)
ax0 = PIVOT_X - ARM_W / 2
arm = mk.box(ARM_L, ARM_W, ARM_T, (ax0 + ARM_L / 2, 0, PIVOT_Z))
arm = arm - mk.cyl(PIN_D, ARM_W, (PIVOT_X, 0, PIVOT_Z), "y")

result = mk.master({"Clevis base": clevis, "Hinge arm": arm})
EXPECTED = {"solids": mk.count()}
