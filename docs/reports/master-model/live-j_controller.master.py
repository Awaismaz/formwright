from build123d import *
from aicad.master import kit as mk

def outline(z0, h, inset):
    zc = z0 + h/2
    s = mk.box(150-2*inset, 57-2*inset, h, (0, 19, zc))
    s = s + mk.box(110-2*inset, 40-2*inset, h, (0, -27.5, zc))
    for x in (-55, 55):
        s = s + mk.cyl(40-2*inset, h, (x, -27.5, zc), "z")
    return s

holes = [(-60, 35), (60, 35), (-55, -27.5), (55, -27.5)]

lower = outline(0, 18, 0) - outline(2, 16, 2)
for x, y in holes:
    lower = lower + mk.cyl(7, 17, (x, y, 9.5), "z")
for x, y in holes:
    lower = mk.drill(lower, (x, y, 0), 3.4, 18, "z", 1)
    lower = mk.drill(lower, (x, y, 0), 6, 9, "z", 1)

upper = outline(18, 14, 0) - outline(18, 12, 2)
for x, y in holes:
    upper = upper + mk.cyl(7, 13, (x, y, 24.5), "z")
for x, y in holes:
    upper = mk.drill(upper, (x, y, 18), 2.5, 7, "z", 1)

result = mk.master({"Lower shell": lower, "Upper shell": upper})
EXPECTED = {"solids": mk.count()}
