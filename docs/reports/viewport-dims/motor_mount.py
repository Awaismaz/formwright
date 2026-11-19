import math

from build123d import *

from aicad import fw

NAME = "Motor mount bracket"
MATERIAL = "Aluminium 6082-T6"
BASE_L = 140.0  # base length
BASE_W = 70.0  # base depth
BASE_T = 8.0  # base thickness
WALL_H = 60.0  # wall height above the base
WALL_T = 8.0  # wall thickness
MOTOR_BORE = 22.0  # motor pilot bore
BOLT_N = 4  # motor bolts
BOLT_PCD = 44.0  # motor bolt circle
BOLT_D = 3.4  # M3 clearance
SLOT_L = 30.0  # mounting slot length
SLOT_W = 6.6  # mounting slot width (M6)
FILLET_R = 5.0  # inside fillet base/wall
PARAMS = dict(BASE_L=BASE_L, BASE_W=BASE_W, BASE_T=BASE_T, WALL_H=WALL_H, WALL_T=WALL_T, MOTOR_BORE=MOTOR_BORE,
              BOLT_N=BOLT_N, BOLT_PCD=BOLT_PCD, BOLT_D=BOLT_D, SLOT_L=SLOT_L, SLOT_W=SLOT_W, FILLET_R=FILLET_R)
PARAM_META = {
    "BASE_L": {"min": 90, "max": 300, "unit": "mm", "group": "Base", "label": "Base length"},
    "BASE_W": {"min": 50, "max": 200, "unit": "mm", "group": "Base", "label": "Base depth"},
    "BASE_T": {"min": 4, "max": 20, "unit": "mm", "group": "Base", "label": "Base thickness"},
    "WALL_H": {"min": 40, "max": 150, "unit": "mm", "group": "Wall", "label": "Wall height"},
    "WALL_T": {"min": 4, "max": 20, "unit": "mm", "group": "Wall", "label": "Wall thickness"},
    "MOTOR_BORE": {"min": 10, "max": 40, "unit": "mm", "group": "Motor", "label": "Pilot bore Ø"},
    "BOLT_N": {"min": 3, "max": 8, "step": 1, "group": "Motor", "label": "Motor bolts"},
    "BOLT_PCD": {"min": 30, "max": 60, "unit": "mm", "group": "Motor", "label": "Bolt circle Ø"},
    "BOLT_D": {"min": 2.4, "max": 6.6, "unit": "mm", "group": "Motor", "label": "Bolt hole Ø"},
    "SLOT_L": {"min": 10, "max": 50, "unit": "mm", "group": "Base", "label": "Slot length"},
    "SLOT_W": {"min": 4.5, "max": 11, "unit": "mm", "group": "Base", "label": "Slot width"},
    "FILLET_R": {"min": 1, "max": 10, "unit": "mm", "group": "Wall", "label": "Inside fillet"},
}

y_wall = -BASE_W / 2 + WALL_T / 2
part = Box(BASE_L, BASE_W, BASE_T, align=(Align.CENTER, Align.CENTER, Align.MIN))
part += Pos(0, y_wall, BASE_T) * Box(BASE_L, WALL_T, WALL_H, align=(Align.CENTER, Align.CENTER, Align.MIN))
inner = [e for e in part.edges().filter_by(Axis.X)
         if abs(e.center().Z - BASE_T) < 1e-6 and abs(e.center().Y - (-BASE_W / 2 + WALL_T)) < 1e-6]
part = fw.feature("Base and wall", fillet(inner, FILLET_R))

cz = BASE_T + WALL_H / 2
cut = Pos(0, y_wall, cz) * Rot(90, 0, 0) * Cylinder(MOTOR_BORE / 2, WALL_T + 2)
for i in range(BOLT_N):
    a = 2 * math.pi * i / BOLT_N + math.pi / 4
    cut += Pos(BOLT_PCD / 2 * math.cos(a), y_wall, cz + BOLT_PCD / 2 * math.sin(a)) * Rot(90, 0, 0) * Cylinder(
        BOLT_D / 2, WALL_T + 2)
part = fw.feature("Motor bore and bolt circle", part - cut)

for sx in (-1, 1):
    slot = Pos(sx * (BASE_L / 2 - 25), 12, -1) * extrude(Rot(0, 0, 90) * SlotOverall(SLOT_L, SLOT_W), amount=BASE_T + 2)
    part -= slot
part = fw.feature("Mounting slots", part)
result = part

EXPECTED = {"bbox": [BASE_L, BASE_W, BASE_T + WALL_H], "solids": 1}
