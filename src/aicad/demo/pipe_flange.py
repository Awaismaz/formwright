import math

from build123d import *

NAME = "Slip-on pipe flange"
MATERIAL = "Carbon steel"
OD, T, BORE = 150.0, 16.0, 60.3
RF_D, RF_H = 100.0, 2.0
N_BOLTS, BOLT_D, PCD = 6, 14.0, 120.0
PARAMS = dict(OD=OD, T=T, BORE=BORE, RF_D=RF_D, RF_H=RF_H, N_BOLTS=N_BOLTS, BOLT_D=BOLT_D, PCD=PCD)

f = Cylinder(OD / 2, T, align=(Align.CENTER, Align.CENTER, Align.MIN))
f += Pos(0, 0, T) * Cylinder(RF_D / 2, RF_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
f -= Pos(0, 0, -1) * Cylinder(BORE / 2, T + RF_H + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
for i in range(N_BOLTS):
    a = 2 * math.pi * i / N_BOLTS
    f -= Pos(PCD / 2 * math.cos(a), PCD / 2 * math.sin(a), -1) * Cylinder(
        BOLT_D / 2, T + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
result = f

_v = math.pi * (OD / 2) ** 2 * T + math.pi * (RF_D / 2) ** 2 * RF_H - math.pi * (BORE / 2) ** 2 * (T + RF_H) \
    - N_BOLTS * math.pi * (BOLT_D / 2) ** 2 * T
EXPECTED = {"bbox": [OD, OD, T + RF_H], "volume": _v, "solids": 1}
