import math

from build123d import *

from aicad import fw

NAME = "L-bracket"
MATERIAL = "Aluminium 6061"
LEG_H = 60.0
LEG_V = 40.0
WIDTH = 50.0
T = 5.0
FILLET_IN = 3.0
HOLE_D = 5.5
HOLE_EDGE = 12.0
PARAMS = dict(LEG_H=LEG_H, LEG_V=LEG_V, WIDTH=WIDTH, T=T, FILLET_IN=FILLET_IN, HOLE_D=HOLE_D, HOLE_EDGE=HOLE_EDGE)
PARAM_META = {
    "LEG_H": {"min": 20, "max": 300, "step": 1, "unit": "mm", "group": "Legs", "label": "Base leg length"},
    "LEG_V": {"min": 20, "max": 300, "step": 1, "unit": "mm", "group": "Legs", "label": "Upright leg height"},
    "WIDTH": {"min": 10, "max": 300, "step": 1, "unit": "mm", "group": "Legs", "label": "Width"},
    "T": {"min": 2, "max": 30, "step": 0.5, "unit": "mm", "group": "Legs", "label": "Thickness"},
    "FILLET_IN": {"min": 0.5, "max": 20, "step": 0.5, "unit": "mm", "group": "Inside fillet", "label": "Inside radius"},
    "HOLE_D": {"min": 2, "max": 30, "step": 0.1, "unit": "mm", "group": "Mounting holes", "label": "Hole Ø"},
    "HOLE_EDGE": {"min": 4, "max": 100, "step": 0.5, "unit": "mm", "group": "Mounting holes", "label": "Hole distance from the leg end"},
}

MIN3 = (Align.MIN, Align.MIN, Align.MIN)
body = fw.feature("Bracket body", Box(LEG_H, WIDTH, T, align=MIN3) + Box(T, WIDTH, LEG_V, align=MIN3))
inner = [e for e in body.edges().filter_by(Axis.Y) if abs(e.center().X - T) < 1e-6 and abs(e.center().Z - T) < 1e-6]
body = fw.feature("Inside fillet", fillet(inner, FILLET_IN))
r = HOLE_D / 2
for y in (WIDTH / 4, 3 * WIDTH / 4):
    body -= Pos(LEG_H - HOLE_EDGE, y, -1) * Cylinder(r, T + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body -= Pos(-1, y, LEG_V - HOLE_EDGE) * Rot(0, 90, 0) * Cylinder(r, T + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
body = fw.feature("Mounting holes", body)
result = body

_area = LEG_H * T + T * (LEG_V - T) + FILLET_IN**2 * (1 - math.pi / 4)
EXPECTED = {"bbox": [LEG_H, WIDTH, LEG_V], "volume": _area * WIDTH - 4 * math.pi * r**2 * T, "solids": 1}
