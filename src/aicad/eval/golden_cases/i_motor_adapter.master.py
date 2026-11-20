# Master model (recorded): NEMA 17 stepper on a custom adapter plate on an L bracket. One coordinate system: Z up,
# the bracket foot on Z = 0, the upright at the back (+Y), the motor in front of the plate (-Y).
# Hand values: foot 80 x 60 x 6; upright 80 x 14 x 70 at Y 16..30 (Z 6..76); plate 80 x 5 x 60 standing on the foot
# against the upright: Y 11..16, Z 6..66; four M4 (Ø3.3 tap drill, 12 deep: 2 d of thread) in the upright at X ±30,
# Z 36 ± 20, the plate's Ø4.5 holes over them; NEMA 17: 42.3 square x 48 long, its face on the plate at Y = 11,
# axis at X 0, Z 36, four M3 (Ø2.5, 8 deep) on the 31 mm square, the plate's Ø3.4 holes over them, Ø23 pilot bore at the axis;
# a Ø52 window in the upright on the motor axis gives the M3 screw heads (inserted from the plate's back) room.
from build123d import *

from aicad.master import kit as mk

FOOT_L, FOOT_W, FOOT_T = 80.0, 60.0, 6.0
UP_T, UP_H = 14.0, 70.0
PLATE_T, PLATE_H = 5.0, 60.0
MOTOR, MOTOR_L = 42.3, 48.0
M4_TAP, M4_CLR, M4_DEPTH = 3.3, 4.5, 12.0
M3_TAP, M3_CLR, M3_DEPTH = 2.5, 3.4, 8.0
SQ = 31.0
PILOT = 23.0
WINDOW = 52.0

y_up0 = FOOT_W / 2 - UP_T                 # 20: the upright's front face
y_pl0 = y_up0 - PLATE_T                   # 14: the plate's front face (the motor face)
zc = FOOT_T + PLATE_H / 2                 # 36: the plate centre and the motor axis
bracket = mk.box(FOOT_L, FOOT_W, FOOT_T, (0, 0, FOOT_T / 2)) + \
    mk.box(FOOT_L, UP_T, UP_H, (0, y_up0 + UP_T / 2, FOOT_T + UP_H / 2))
plate = mk.box(FOOT_L, PLATE_T, PLATE_H, (0, y_pl0 + PLATE_T / 2, zc))
motor = mk.box(MOTOR, MOTOR_L, MOTOR, (0, y_pl0 - MOTOR_L / 2, zc))
for x, z in [(sx * 30.0, zc + sz * 20.0) for sx in (-1, 1) for sz in (-1, 1)]:
    bracket = mk.drill(bracket, (x, y_up0, z), M4_TAP, M4_DEPTH, "y", 1)
    plate = mk.drill(plate, (x, y_pl0, z), M4_CLR, PLATE_T, "y", 1)
for x, z in [(sx * SQ / 2, zc + sz * SQ / 2) for sx in (-1, 1) for sz in (-1, 1)]:
    plate = mk.drill(plate, (x, y_pl0, z), M3_CLR, PLATE_T, "y", 1)
    motor = mk.drill(motor, (x, y_pl0, z), M3_TAP, M3_DEPTH, "y", -1)
plate = mk.drill(plate, (0, y_pl0, zc), PILOT, PLATE_T, "y", 1)
bracket = mk.drill(bracket, (0, y_up0, zc), WINDOW, UP_T, "y", 1)

result = mk.master({"Mounting bracket": bracket, "Motor adapter plate": plate, "Stepper motor NEMA 17": motor})
EXPECTED = {"solids": mk.count()}
