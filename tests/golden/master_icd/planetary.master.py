# Recorded master (benchmark attempt A4): a single stage planetary gearbox. Split housing on the shaft axis (Z 135,
# axes along X): Ø47 bearing bores (6204) at both ends and a Ø210 cavity for the ring gear, half in the base and half
# in the cover; sun, planets and ring as pitch circles (m2: Ø60, Ø60, Ø180); planets Ø42 bore (6004) on Ø20 pins in
# the carrier.
import math

from build123d import *

from aicad.master import kit as mk

HC = 135.0  # shaft axis height (axis along X)

# ---------- housing (full, then split at axis plane) ----------
X0, X1 = -38.0, 90.0
L = X1 - X0
XC = (X0 + X1) / 2
body = mk.box(L, 240, 240, (XC, 0, HC))
body = body + mk.box(L, 300, 30, (XC, 0, HC))              # split flanges
body = body + mk.box(L, 320, 15, (XC, 0, 7.5))             # feet plate
body = body + mk.box(L, 240, 120, (XC, 0, 15 + 60))         # fill to feet
body = body - mk.cyl(210, 72, (26, 0, HC), "x")             # cavity x -10..62
body = body - mk.cyl(47, 30, (-24, 0, HC), "x")             # input bearing bore
body = body - mk.cyl(47, 30, (76, 0, HC), "x")              # output bearing bore

base = body & mk.box(L, 400, HC, (XC, 0, HC / 2))
cover = body & mk.box(L, 400, 150, (XC, 0, HC + 75))

# cover bolts M8, through both flanges (bolt and nut)
for x in (-25.0, 10.0, 45.0, 77.0):
    for y in (-137.5, 137.5):
        cover = mk.drill(cover, (x, y, HC + 15), 9, 15, "z", -1)
        base = mk.drill(base, (x, y, HC), 9, 15, "z", -1)
# foot mounting holes
for x in (-20.0, 72.0):
    for y in (-145.0, 145.0):
        base = mk.drill(base, (x, y, 15), 13, 15, "z", -1)

# ---------- bearing caps ----------
cap_pts = [(s1 * 24.75, s2 * 24.75) for s1 in (-1, 1) for s2 in (-1, 1)]
in_cap = mk.cyl(90, 8, (-42, 0, HC), "x") - mk.cyl(25, 8, (-42, 0, HC), "x")
out_cap = mk.cyl(90, 8, (94, 0, HC), "x") - mk.cyl(25, 8, (94, 0, HC), "x")
for (y, dz) in cap_pts:
    z = HC + dz
    in_cap = mk.drill(in_cap, (-46, y, z), 6.6, 8, "x", 1)
    out_cap = mk.drill(out_cap, (98, y, z), 6.6, 8, "x", -1)
    if dz < 0:
        base = mk.drill(base, (X0, y, z), 5.0, 9, "x", 1)
        base = mk.drill(base, (X1, y, z), 5.0, 9, "x", -1)
    else:
        cover = mk.drill(cover, (X0, y, z), 5.0, 9, "x", 1)
        cover = mk.drill(cover, (X1, y, z), 5.0, 9, "x", -1)

# ---------- gears (pitch circles), plane x 0..20 ----------
ring = mk.cyl(210, 20, (10, 0, HC), "x") - mk.cyl(180, 20, (10, 0, HC), "x")
sun = mk.cyl(60, 20, (10, 0, HC), "x") - mk.cyl(20, 20, (10, 0, HC), "x")
in_shaft = mk.cyl(20, 87, (20 - 43.5, 0, HC), "x")          # x -67..20

planets, pins = [], []
carrier = mk.cyl(160, 20, (31, 0, HC), "x") + mk.cyl(40, 20, (51, 0, HC), "x")
carrier = carrier - mk.cyl(20, 40, (41, 0, HC), "x")
for k in range(3):
    a = math.radians(90 + 120 * k)
    y, z = round(60 * math.cos(a), 6), round(HC + 60 * math.sin(a), 6)
    planets.append(mk.cyl(60, 20, (10, y, z), "x") - mk.cyl(42, 20, (10, y, z), "x"))
    pins.append(mk.cyl(20, 46, (18, y, z), "x"))              # x -5..41
    carrier = carrier - mk.cyl(20, 20, (31, y, z), "x")

out_shaft = mk.cyl(20, 84, (21 + 42, 0, HC), "x")           # x 21..105

result = mk.master({
    "Housing base": base,
    "Housing cover": cover,
    "Input open cap": in_cap,
    "Output open cap": out_cap,
    "Ring gear": ring,
    "Sun gear": sun,
    "Input shaft": in_shaft,
    "Planet gear": planets,
    "Planet pin": pins,
    "Planet carrier": carrier,
    "Output shaft": out_shaft,
})
EXPECTED = {"solids": mk.count()}
