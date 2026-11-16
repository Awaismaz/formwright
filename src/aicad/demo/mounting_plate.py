import math

from build123d import *

NAME = "Mounting plate"
MATERIAL = "Aluminium 6061-T6"
L = 120.0
W = 80.0
T = 10.0
HOLE_D = 6.6  # M6 clearance (ISO 273 medium)
EDGE = 10.0
PL = 40.0
PW = 30.0
PD = 4.0
PR = 3.0
CH = 1.0
PARAMS = dict(L=L, W=W, T=T, HOLE_D=HOLE_D, EDGE=EDGE, PL=PL, PW=PW, PD=PD, PR=PR, CH=CH)

part = Box(L, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN))
part = chamfer(part.edges().group_by(Axis.Z)[-1], CH)
for sx in (-1, 1):
    for sy in (-1, 1):
        part -= Pos(sx * (L / 2 - EDGE), sy * (W / 2 - EDGE), T / 2) * Cylinder(HOLE_D / 2, T + 2)
part -= Pos(0, 0, T - PD) * extrude(RectangleRounded(PL, PW, PR), amount=PD)
result = part

_v = L * W * T - ((L + W) * CH**2 - 4 * CH**3 / 3) - 4 * math.pi * (HOLE_D / 2) ** 2 * T \
    - (PL * PW - (4 - math.pi) * PR**2) * PD
EXPECTED = {"bbox": [L, W, T], "volume": _v, "solids": 1}
