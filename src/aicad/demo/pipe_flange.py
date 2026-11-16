import math

from build123d import *

from aicad import fw

NAME = "Slip-on pipe flange"
MATERIAL = "Carbon steel"
OD = 150.0
T = 16.0
BORE = 60.3
RF_D = 100.0
RF_H = 2.0
N_BOLTS = 6
BOLT_D = 14.0
PCD = 120.0
PARAMS = dict(OD=OD, T=T, BORE=BORE, RF_D=RF_D, RF_H=RF_H, N_BOLTS=N_BOLTS, BOLT_D=BOLT_D, PCD=PCD)
PARAM_META = {
    "OD": {"min": 80, "max": 400, "step": 1, "unit": "mm", "group": "Flange", "label": "Outside Ø"},
    "T": {"min": 6, "max": 60, "step": 0.5, "unit": "mm", "group": "Flange", "label": "Thickness"},
    "RF_D": {"min": 40, "max": 380, "step": 1, "unit": "mm", "group": "Raised face", "label": "Raised face Ø"},
    "RF_H": {"min": 0.5, "max": 10, "step": 0.5, "unit": "mm", "group": "Raised face", "label": "Raised face height"},
    "BORE": {"min": 10, "max": 300, "step": 0.1, "unit": "mm", "group": "Bore", "label": "Bore Ø"},
    "N_BOLTS": {"min": 3, "max": 24, "step": 1, "group": "Bolt holes", "label": "Number of bolt holes"},
    "BOLT_D": {"min": 6, "max": 40, "step": 0.5, "unit": "mm", "group": "Bolt holes", "label": "Bolt hole Ø"},
    "PCD": {"min": 50, "max": 380, "step": 1, "unit": "mm", "group": "Bolt holes", "label": "Pitch circle Ø"},
}

f = fw.feature("Flange body", Cylinder(OD / 2, T, align=(Align.CENTER, Align.CENTER, Align.MIN)))
f = fw.feature("Raised face", f + Pos(0, 0, T) * Cylinder(RF_D / 2, RF_H, align=(Align.CENTER, Align.CENTER, Align.MIN)))
f = fw.feature("Bore", f - Pos(0, 0, -1) * Cylinder(BORE / 2, T + RF_H + 2, align=(Align.CENTER, Align.CENTER, Align.MIN)))
for i in range(N_BOLTS):
    a = 2 * math.pi * i / N_BOLTS
    f -= Pos(PCD / 2 * math.cos(a), PCD / 2 * math.sin(a), -1) * Cylinder(
        BOLT_D / 2, T + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
f = fw.feature("Bolt holes", f)
result = f

_v = math.pi * (OD / 2) ** 2 * T + math.pi * (RF_D / 2) ** 2 * RF_H - math.pi * (BORE / 2) ** 2 * (T + RF_H) \
    - N_BOLTS * math.pi * (BOLT_D / 2) ** 2 * T
EXPECTED = {"bbox": [OD, OD, T + RF_H], "volume": _v, "solids": 1}
