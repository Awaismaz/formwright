# Master model (recorded): angle bracket bolted to a base plate (FX-04 sizes). One coordinate system, Z up, the plate
# on Z = 0. Hand values: plate 120 x 80 x 10; bracket foot 60 x 40 x 8 centred on the plate (Z 10 .. 18), upright 8
# thick at the foot's +Y edge (Y 12 .. 20), 50 high above the foot (Z 18 .. 68); two Ø6.6 holes 40 apart through the
# foot and the plate at X ±20, Y -4 (the middle of the free part of the foot); M6 through bolts with nuts; the plate's
# four Ø9 corner holes 10 from the edges.
from build123d import *

from aicad.master import kit as mk

PL, PW, PT = 120.0, 80.0, 10.0
FL, FW, FT = 60.0, 40.0, 8.0
UT, UH = 8.0, 50.0

plate = mk.box(PL, PW, PT, (0, 0, PT / 2))
bracket = mk.box(FL, FW, FT, (0, 0, PT + FT / 2)) + mk.box(FL, UT, UH, (0, FW / 2 - UT / 2, PT + FT + UH / 2))
bracket = bracket - mk.cyl(8.4, UT, (0, FW / 2 - UT / 2, PT + FT + 40.0), "y")
for x in (-20.0, 20.0):
    plate = mk.drill(plate, (x, -4.0, PT), 6.6, PT, "z", -1)
    bracket = mk.drill(bracket, (x, -4.0, PT + FT), 6.6, FT, "z", -1)
for x in (-50.0, 50.0):
    for y in (-30.0, 30.0):
        plate = mk.drill(plate, (x, y, PT), 9.0, PT, "z", -1)

result = mk.master({"Base plate": plate, "Angle bracket": bracket})
EXPECTED = {"solids": mk.count()}
