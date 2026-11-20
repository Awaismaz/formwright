# Master model (recorded): an original handheld-controller-style split housing (no product copied): a lower and an
# upper shell meeting on a flat split line at Z = 18, joined by four M3 screws from below. Coarse skeleton: each shell
# is a hollow slab with a grip lobe at each end (a cylinder across the end), 2 mm walls, open at the split face.
# Hand values: body 110 x 95 between the lobe centres, lobes Ø40 at X = ±55 (overall 150 x 95);
# screws at X ±40, Y ±30: lower shell Ø11 bosses, Ø3.4 through with Ø8 x 9 counterbores from below (room for the ISO 7089 washer,
# 9 mm clamped), upper
# shell Ø7 bosses tapped Ø2.5 x 8 from the split face: M3 x 16 (Fitz: 9 + 0.5 washer + 6 .. 9 + 0.5 + 7).
from build123d import *

from aicad.master import kit as mk

BODY_L, W = 110.0, 95.0
LOBE_D = 40.0
LOWER_H, UPPER_H = 18.0, 14.0
T = 2.0
BOSS_D, TAP_D, TAP_DEPTH = 7.0, 2.5, 8.0
CLR_D, CB_D, CB_DEPTH = 3.4, 8.0, 9.0
LOWER_BOSS_D = 11.0
SX, SY = 40.0, 30.0


def slab(z0: float, h: float, open_top: bool) -> object:
    outer = mk.box(BODY_L, W, h, (0, 0, z0 + h / 2))
    for sx in (-1, 1):
        outer = outer + mk.cyl(LOBE_D, W, (sx * BODY_L / 2, 0, z0 + h / 2), "y").intersect(
            mk.box(LOBE_D, W, h, (sx * BODY_L / 2, 0, z0 + h / 2)))
    zc = z0 + T + (h - T) / 2 + 0.001 if open_top else z0 + (h - T) / 2 - 0.001
    inner = mk.box(BODY_L - 2 * T, W - 2 * T, h - T, (0, 0, zc))
    return outer - inner


screws = [(sx * SX, sy * SY) for sx in (-1, 1) for sy in (-1, 1)]
lower = slab(0.0, LOWER_H, True)
upper = slab(LOWER_H, UPPER_H, False)
for x, y in screws:
    lower = lower + mk.cyl(LOWER_BOSS_D, LOWER_H, (x, y, LOWER_H / 2))
    lower = mk.drill(lower, (x, y, 0.0), CLR_D, LOWER_H, "z", 1)
    lower = mk.drill(lower, (x, y, 0.0), CB_D, CB_DEPTH, "z", 1)
    upper = upper + mk.cyl(BOSS_D, UPPER_H - T, (x, y, LOWER_H + (UPPER_H - T) / 2))
    upper = mk.drill(upper, (x, y, LOWER_H), TAP_D, TAP_DEPTH, "z", 1)

result = mk.master({"Lower shell": lower, "Upper shell": upper})
EXPECTED = {"solids": mk.count()}
