# Master model (recorded): electronics enclosure, base + lid + 4 corner screw bosses. Coarse multibody skeleton,
# one coordinate system: Z up, the base standing on Z = 0. Hand values: bosses Ø8 touching both walls in the inside
# corners -> centres at X = ±(60 - 2.5 - 4) = ±53.5, Y = ±(40 - 2.5 - 4) = ±33.5; M3 tapped Ø2.5 x 8 from the rim;
# lid clearance holes Ø3.4 (ISO 273 medium) over them.
from build123d import *

from aicad.master import kit as mk

L = 120.0  # enclosure length (X)
W = 80.0   # enclosure width (Y)
H = 40.0   # base height (Z)
T = 2.5    # wall and floor
LID_T = 3.0
BOSS_D = 8.0
TAP_D = 2.5
TAP_DEPTH = 8.0
CLEAR_D = 3.4

bx, by = L / 2 - T - BOSS_D / 2, W / 2 - T - BOSS_D / 2
corners = [(sx * bx, sy * by) for sx in (-1, 1) for sy in (-1, 1)]

base = mk.box(L, W, H, (0, 0, H / 2)) - mk.box(L - 2 * T, W - 2 * T, H - T, (0, 0, T + (H - T) / 2 + 0.001))
for x, y in corners:
    base = base + mk.cyl(BOSS_D, H - T, (x, y, T + (H - T) / 2))
    base = mk.drill(base, (x, y, H), TAP_D, TAP_DEPTH, "z", -1)

lid = mk.box(L, W, LID_T, (0, 0, H + LID_T / 2))
for x, y in corners:
    lid = mk.drill(lid, (x, y, H + LID_T), CLEAR_D, LID_T, "z", -1)

result = mk.master({"Enclosure base": base, "Enclosure lid": lid})
EXPECTED = {"solids": mk.count()}
