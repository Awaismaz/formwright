import math

from build123d import *

from aicad import fw

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
PARAM_META = {
    "L": {"min": 60, "max": 400, "step": 1, "unit": "mm", "group": "Plate", "label": "Length"},
    "W": {"min": 40, "max": 300, "step": 1, "unit": "mm", "group": "Plate", "label": "Width"},
    "T": {"min": 6, "max": 40, "step": 0.5, "unit": "mm", "group": "Plate", "label": "Thickness"},
    "CH": {"min": 0, "max": 3, "step": 0.1, "unit": "mm", "group": "Plate", "label": "Top chamfer"},
    "HOLE_D": {"min": 3.4, "max": 13.5, "step": 0.1, "unit": "mm", "group": "Holes", "label": "Clearance Ø"},
    "EDGE": {"min": 6, "max": 30, "step": 0.5, "unit": "mm", "group": "Holes", "label": "Edge distance"},
    "PL": {"min": 10, "max": 200, "step": 1, "unit": "mm", "group": "Pocket", "label": "Pocket length"},
    "PW": {"min": 10, "max": 150, "step": 1, "unit": "mm", "group": "Pocket", "label": "Pocket width"},
    "PD": {"min": 0.5, "max": 20, "step": 0.5, "unit": "mm", "group": "Pocket", "label": "Pocket depth"},
    "PR": {"min": 0.5, "max": 20, "step": 0.5, "unit": "mm", "group": "Pocket", "label": "Corner radius"},
}

part = fw.feature("Base plate", Box(L, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN)))
part = fw.feature("Top chamfer", chamfer(part.edges().group_by(Axis.Z)[-1], CH))
for sx in (-1, 1):
    for sy in (-1, 1):
        part -= Pos(sx * (L / 2 - EDGE), sy * (W / 2 - EDGE), T / 2) * Cylinder(HOLE_D / 2, T + 2)
part = fw.feature("Mounting holes (4x)", part)
part -= Pos(0, 0, T - PD) * extrude(RectangleRounded(PL, PW, PR), amount=PD)
part = fw.feature("Centre pocket", part)
result = part

_v = L * W * T - ((L + W) * CH**2 - 4 * CH**3 / 3) - 4 * math.pi * (HOLE_D / 2) ** 2 * T \
    - (PL * PW - (4 - math.pi) * PR**2) * PD
EXPECTED = {"bbox": [L, W, T], "volume": _v, "solids": 1}
