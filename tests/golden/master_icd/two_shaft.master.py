# Recorded master (benchmark attempt A3, planner fallback): a two-shaft spur gear reducer. Split housing on the shaft
# axes (Z 110, axes along Y): Ø52 (6205) and Ø72 (6207) bearing bores through both side walls, half in the base and
# half in the cover; pinion Ø60 and gear Ø150 as pitch circles, 105 apart.
from build123d import *

from aicad.master import kit as mk

ZA = 110.0                 # shaft axis height = split line
XI, XO = -52.5, 52.5       # input / output axes (centre distance 105, m3 z20/z50)
X0, X1 = -109.0, 154.0     # housing outer x
YW = 72.0                  # outer face of side walls (bearing faces)
BI, BO = 52.0, 72.0        # bearing bores 6205 / 6207

# ---------------- Housing base ----------------
base = mk.box(X1 - X0, 2 * YW, ZA, (( X0 + X1) / 2, 0, ZA / 2))
base -= mk.box(239, 80, ZA - 25 + 1, ((-97 + 142) / 2, 0, 25 + (ZA - 25 + 1) / 2))
feet = mk.box(X1 - X0 + 40, 184, 15, ((X0 + X1) / 2, 0, 7.5))
base = base + feet
for fx in (X0 - 10, X1 + 10):
    for fy in (-82, 82):
        base = mk.drill(base, (fx, fy, 15), 14, 15, "z", -1)
base = mk.drill(base, (X1, 0, 31), 10, 12, "x", -1)          # oil drain

# ---------------- Housing cover ----------------
cover = mk.box(X1 - X0, 2 * YW, 40, ((X0 + X1) / 2, 0, ZA + 20))
cover += mk.box(X1 - X0, 100, 57, ((X0 + X1) / 2, 0, 150 + 28.5))
cover -= mk.box(239, 80, 85, ((-97 + 142) / 2, 0, ZA + 42.5))
cover += mk.cyl(24, 15, (100, 0, 214.5), "z")                # breather boss
cover = mk.drill(cover, (100, 0, 222), 10, 27, "z", -1)

# bearing bores in both halves
for x, d in ((XI, BI), (XO, BO)):
    bore = mk.cyl(d, 2 * YW + 2, (x, 0, ZA), "y")
    base -= bore
    cover -= bore

# cover bolts M10: clearance in cover flange, tap in base
for bx in (-100, 0, 110, 145):
    for by in (-62, 62):
        cover = mk.drill(cover, (bx, by, 150), 11, 40, "z", -1)
        base = mk.drill(base, (bx, by, ZA), 8.5, 15, "z", -1)

# ---------------- Bearing caps (4 identical) ----------------
caps = []
r = 42 * 0.7071
for x in (XI, XO):
    for s in (-1, 1):
        cap = mk.cyl(100, 10, (x, s * (YW + 5), ZA), "y")
        cap -= mk.cyl(32, 12, (x, s * (YW + 5), ZA), "y")
        for dx in (-r, r):
            for dz in (-r, r):
                cap -= mk.cyl(6.6, 12, (x + dx, s * (YW + 5), ZA + dz), "y")
                if dz < 0:
                    base = mk.drill(base, (x + dx, s * YW, ZA + dz), 5.0, 9, "y", -s)
                else:
                    cover = mk.drill(cover, (x + dx, s * YW, ZA + dz), 5.0, 9, "y", -s)
        caps.append(cap)

# ---------------- Input shaft + pinion ----------------
ish = mk.cyl(20, 48, (XI, -106, ZA), "y")          # coupling end y -130..-82
ish += mk.cyl(25, 62, (XI, -51, ZA), "y")          # y -82..-20
ish += mk.cyl(30, 40, (XI, 0, ZA), "y")            # pinion seat
ish += mk.cyl(25, 50, (XI, 45, ZA), "y")           # y 20..70
pinion = mk.cyl(60, 40, (XI, 0, ZA), "y") - mk.cyl(30, 42, (XI, 0, ZA), "y")

# ---------------- Output shaft + gear ----------------
osh = mk.cyl(35, 50, (XO, -45, ZA), "y")           # y -70..-20
osh += mk.cyl(45, 40, (XO, 0, ZA), "y")            # gear seat
osh += mk.cyl(35, 52, (XO, 46, ZA), "y")           # y 20..72
osh += mk.cyl(30, 68, (XO, 106, ZA), "y")          # output end y 72..140
gear = mk.cyl(150, 40, (XO, 0, ZA), "y") - mk.cyl(45, 42, (XO, 0, ZA), "y")

result = mk.master({
    "Housing base": base,
    "Housing cover": cover,
    "Bearing cap": caps,
    "Input shaft": ish,
    "Pinion": pinion,
    "Output shaft": osh,
    "Output gear": gear,
})
EXPECTED = {"solids": mk.count()}
