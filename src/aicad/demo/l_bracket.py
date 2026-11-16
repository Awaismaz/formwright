import math

from build123d import *

NAME = "L-bracket"
MATERIAL = "Aluminium 6061"
LEG_H, LEG_V, WIDTH, T, FILLET_IN = 60.0, 40.0, 50.0, 5.0, 3.0
HOLE_D, HOLE_EDGE = 5.5, 12.0
PARAMS = dict(LEG_H=LEG_H, LEG_V=LEG_V, WIDTH=WIDTH, T=T, FILLET_IN=FILLET_IN, HOLE_D=HOLE_D, HOLE_EDGE=HOLE_EDGE)

MIN3 = (Align.MIN, Align.MIN, Align.MIN)
body = Box(LEG_H, WIDTH, T, align=MIN3) + Box(T, WIDTH, LEG_V, align=MIN3)
inner = [e for e in body.edges().filter_by(Axis.Y) if abs(e.center().X - T) < 1e-6 and abs(e.center().Z - T) < 1e-6]
body = fillet(inner, FILLET_IN)
r = HOLE_D / 2
for y in (WIDTH / 4, 3 * WIDTH / 4):
    body -= Pos(LEG_H - HOLE_EDGE, y, -1) * Cylinder(r, T + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
    body -= Pos(-1, y, LEG_V - HOLE_EDGE) * Rot(0, 90, 0) * Cylinder(r, T + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))
result = body

_area = LEG_H * T + T * (LEG_V - T) + FILLET_IN**2 * (1 - math.pi / 4)
EXPECTED = {"bbox": [LEG_H, WIDTH, LEG_V], "volume": _area * WIDTH - 4 * math.pi * r**2 * T, "solids": 1}
