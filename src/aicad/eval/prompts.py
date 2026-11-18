"""EVAL-003 benchmark prompts: 20 original design requests with analytic expectations.

Each case: the prompt a user would type, the expectation the benchmark judges the result by (computed by hand from
the requirements, never measured from a model), and a reference solution used only by the dry run to prove the
harness and the expectations are self-consistent. The benchmark gates on the deterministic checks plus these
expectations, never on the agent's own claims.

Expectation fields:
  bbox    overall size in mm, compared orientation-free (sorted), tolerance max(0.5 mm, 0.5 %)
  volume  mm³, relative tolerance ``vol_tol`` (default 1 %)
  cylinders {diameter_mm: count}: distinct cylindrical surfaces (by axis) of that diameter, holes and outer
            diameters alike (feature census)
  solids  number of solids (default 1)
"""

from __future__ import annotations

from math import pi
from typing import Any

HDR = "from build123d import *\nfrom math import pi\nNAME = {name!r}\nMATERIAL = {mat!r}\n"
FLAT = "(Align.CENTER, Align.CENTER, Align.MIN)"


def _case(cid: str, family: str, prompt: str, bbox: list[float], volume: float, ref: str,
          cylinders: dict[float, int] | None = None, vol_tol: float = 0.01, name: str = "", mat: str = "") -> dict[str, Any]:
    return {"id": cid, "family": family, "prompt": prompt,
            "expect": {"bbox": bbox, "volume": volume, "vol_tol": vol_tol, "cylinders": cylinders or {}, "solids": 1},
            "reference": HDR.format(name=name or cid, mat=mat or "unspecified") + ref.strip() + "\n"}


def _r(d: float) -> float:
    return d / 2


CASES: list[dict[str, Any]] = [
    # ------------------------------------------------------------------ plates
    _case("P01", "plate", "Aluminium 6061 mounting plate 120 × 80 × 8 mm with four Ø6.6 mm through holes for M6, each "
          "10 mm in from both adjacent edges.",
          [120, 80, 8], 120 * 80 * 8 - 4 * pi * 3.3**2 * 8, f"""
part = Box(120, 80, 8, align={FLAT})
for x in (-50, 50):
    for y in (-30, 30):
        part -= Pos(x, y, 4) * Cylinder(3.3, 8)
result = part
EXPECTED = {{"bbox": [120, 80, 8], "volume": 120*80*8 - 4*pi*3.3**2*8, "solids": 1}}
""", cylinders={6.6: 4}, name="Mounting plate", mat="6061-T6"),
    _case("P02", "plate", "Steel base plate 200 × 150 × 12 mm with a central Ø40 mm through bore and six Ø9 mm "
          "clearance holes on a 120 mm pitch circle.",
          [200, 150, 12], 200 * 150 * 12 - pi * 20**2 * 12 - 6 * pi * 4.5**2 * 12, f"""
part = Box(200, 150, 12, align={FLAT}) - Pos(0, 0, 6) * Cylinder(20, 12)
for loc in PolarLocations(60, 6):
    part -= Pos(0, 0, 6) * loc * Cylinder(4.5, 12)
result = part
EXPECTED = {{"bbox": [200, 150, 12], "volume": 200*150*12 - pi*20**2*12 - 6*pi*4.5**2*12, "solids": 1}}
""", cylinders={40: 1, 9: 6}),
    _case("P03", "plate", "Cover plate 100 × 100 × 5 mm with R10 corners (vertical edges) and four Ø5.5 mm holes on an "
          "80 × 80 mm square pattern.",
          [100, 100, 5], (100 * 100 - (4 - pi) * 10**2) * 5 - 4 * pi * 2.75**2 * 5, """
part = extrude(RectangleRounded(100, 100, 10), 5)
for x in (-40, 40):
    for y in (-40, 40):
        part -= Pos(x, y, 2.5) * Cylinder(2.75, 5)
result = part
EXPECTED = {"bbox": [100, 100, 5], "volume": (100*100 - (4 - pi)*10**2)*5 - 4*pi*2.75**2*5, "solids": 1}
""", cylinders={5.5: 4, 20: 4}),
    _case("P04", "plate", "Adapter plate 150 × 90 × 10 mm with a centred 60 × 30 mm rectangular through window and "
          "four Ø6.6 mm holes 12 mm in from both adjacent edges.",
          [150, 90, 10], 150 * 90 * 10 - 60 * 30 * 10 - 4 * pi * 3.3**2 * 10, f"""
part = Box(150, 90, 10, align={FLAT}) - Box(60, 30, 10, align={FLAT})
for x in (-63, 63):
    for y in (-33, 33):
        part -= Pos(x, y, 5) * Cylinder(3.3, 10)
result = part
EXPECTED = {{"bbox": [150, 90, 10], "volume": 150*90*10 - 60*30*10 - 4*pi*3.3**2*10, "solids": 1}}
""", cylinders={6.6: 4}),
    # ------------------------------------------------------------------ brackets
    _case("B01", "bracket", "L-bracket with a 60 mm base leg and a 40 mm tall upright leg (outside dimensions), 50 mm "
          "wide, 5 mm thick, sharp corners, no holes.",
          [60, 50, 40], (60 * 5 + 35 * 5) * 50, """
base = Box(60, 50, 5, align=(Align.MIN, Align.CENTER, Align.MIN))
up = Box(5, 50, 40, align=(Align.MIN, Align.CENTER, Align.MIN))
result = base + up
EXPECTED = {"bbox": [60, 50, 40], "volume": (60*5 + 35*5)*50, "solids": 1}
"""),
    _case("B02", "bracket", "Equal-leg L-bracket, legs 80 mm outside, 40 mm wide, 6 mm thick, two Ø9 mm holes in each "
          "leg on the width centreline at 25 mm and 60 mm from the outside corner.",
          [80, 40, 80], (80 * 6 + 74 * 6) * 40 - 4 * pi * 4.5**2 * 6, """
part = Box(80, 40, 6, align=(Align.MIN, Align.CENTER, Align.MIN)) + Box(6, 40, 80, align=(Align.MIN, Align.CENTER, Align.MIN))
for d in (25, 60):
    part -= Pos(d, 0, 3) * Cylinder(4.5, 6)
    part -= Pos(3, 0, d) * Rot(0, 90, 0) * Cylinder(4.5, 6)
result = part
EXPECTED = {"bbox": [80, 40, 80], "volume": (80*6 + 74*6)*40 - 4*pi*4.5**2*6, "solids": 1}
""", cylinders={9: 4}),
    _case("B03", "bracket", "U-channel bracket 100 mm long, 60 mm wide × 40 mm tall outside, 4 mm walls and base, open "
          "top.",
          [100, 60, 40], (60 * 40 - 52 * 36) * 100, f"""
result = Box(100, 60, 40, align={FLAT}) - Pos(0, 0, 4) * Box(100, 52, 36, align={FLAT})
EXPECTED = {{"bbox": [100, 60, 40], "volume": (60*40 - 52*36)*100, "solids": 1}}
"""),
    _case("B04", "bracket", "Gusseted angle bracket: legs 70 mm outside, 30 mm wide, 5 mm thick, with one 5 mm thick "
          "triangular gusset centred on the width, its two 40 mm legs measured from the inside corner.",
          [70, 30, 70], (70 * 5 + 65 * 5) * 30 + 0.5 * 40 * 40 * 5, """
part = Box(70, 30, 5, align=(Align.MIN, Align.CENTER, Align.MIN)) + Box(5, 30, 70, align=(Align.MIN, Align.CENTER, Align.MIN))
tri = Plane.XZ * Polygon((5, 5), (45, 5), (5, 45), align=None)
part += extrude(tri, 2.5, both=True)
result = part
EXPECTED = {"bbox": [70, 30, 70], "volume": (70*5 + 65*5)*30 + 0.5*40*40*5, "solids": 1}
"""),
    # ------------------------------------------------------------------ shafts
    _case("S01", "shaft", "Plain steel shaft Ø20 mm × 150 mm long.", [20, 20, 150], pi * 10**2 * 150, f"""
result = Cylinder(10, 150, align={FLAT})
EXPECTED = {{"bbox": [20, 20, 150], "volume": pi*10**2*150, "solids": 1}}
""", cylinders={20: 1}),
    _case("S02", "shaft", "Stepped shaft, coaxial: Ø30 × 40 mm, then Ø25 × 60 mm, then Ø20 × 50 mm.",
          [30, 30, 150], pi * (15**2 * 40 + 12.5**2 * 60 + 10**2 * 50), f"""
result = (Cylinder(15, 40, align={FLAT}) + Pos(0, 0, 40) * Cylinder(12.5, 60, align={FLAT})
          + Pos(0, 0, 100) * Cylinder(10, 50, align={FLAT}))
EXPECTED = {{"bbox": [30, 30, 150], "volume": pi*(15**2*40 + 12.5**2*60 + 10**2*50), "solids": 1}}
""", cylinders={30: 1, 25: 1, 20: 1}),
    _case("S03", "shaft", "Shaft Ø25 × 120 mm with a 2 mm × 45° chamfer on both end edges.",
          [25, 25, 120], pi * (12.5**2 * 120 - 2 * (12.5**2 * 2 - 2 / 3 * (10.5**2 + 10.5 * 12.5 + 12.5**2))), f"""
part = Cylinder(12.5, 120, align={FLAT})
result = chamfer(part.edges().filter_by(GeomType.CIRCLE), 2)
EXPECTED = {{"bbox": [25, 25, 120], "volume": pi*(12.5**2*120 - 2*(12.5**2*2 - 2/3*(10.5**2 + 10.5*12.5 + 12.5**2))),
            "solids": 1}}
""", cylinders={25: 1}),
    _case("S04", "shaft", "Hollow shaft (tube) OD 40 mm, ID 30 mm, 200 mm long.",
          [40, 40, 200], pi * (20**2 - 15**2) * 200, f"""
result = Cylinder(20, 200, align={FLAT}) - Cylinder(15, 200, align={FLAT})
EXPECTED = {{"bbox": [40, 40, 200], "volume": pi*(20**2 - 15**2)*200, "solids": 1}}
""", cylinders={40: 1, 30: 1}),
    # ------------------------------------------------------------------ flanges
    _case("F01", "flange", "Flat flange OD 150 mm, 15 mm thick, Ø60 mm bore, six Ø14 mm bolt holes on a 120 mm PCD.",
          [150, 150, 15], pi * (75**2 - 30**2) * 15 - 6 * pi * 7**2 * 15, f"""
part = Cylinder(75, 15, align={FLAT}) - Cylinder(30, 15, align={FLAT})
for loc in PolarLocations(60, 6):
    part -= loc * Cylinder(7, 15, align={FLAT})
result = part
EXPECTED = {{"bbox": [150, 150, 15], "volume": pi*(75**2 - 30**2)*15 - 6*pi*7**2*15, "solids": 1}}
""", cylinders={60: 1, 14: 6, 150: 1}),
    _case("F02", "flange", "Blind flange OD 120 mm × 12 mm thick, four Ø11 mm holes on a 95 mm PCD, no bore.",
          [120, 120, 12], pi * 60**2 * 12 - 4 * pi * 5.5**2 * 12, f"""
part = Cylinder(60, 12, align={FLAT})
for loc in PolarLocations(47.5, 4):
    part -= loc * Cylinder(5.5, 12, align={FLAT})
result = part
EXPECTED = {{"bbox": [120, 120, 12], "volume": pi*60**2*12 - 4*pi*5.5**2*12, "solids": 1}}
""", cylinders={11: 4}),
    _case("F03", "flange", "Hub flange: Ø100 × 10 mm disc with a Ø50 mm hub rising 30 mm from one face (40 mm overall), "
          "Ø25 mm through bore, four Ø9 mm holes on a 75 mm PCD in the disc.",
          [100, 100, 40], pi * 50**2 * 10 + pi * 25**2 * 30 - pi * 12.5**2 * 40 - 4 * pi * 4.5**2 * 10, f"""
part = Cylinder(50, 10, align={FLAT}) + Pos(0, 0, 10) * Cylinder(25, 30, align={FLAT})
part -= Cylinder(12.5, 40, align={FLAT})
for loc in PolarLocations(37.5, 4):
    part -= loc * Cylinder(4.5, 10, align={FLAT})
result = part
EXPECTED = {{"bbox": [100, 100, 40], "volume": pi*50**2*10 + pi*25**2*30 - pi*12.5**2*40 - 4*pi*4.5**2*10, "solids": 1}}
""", cylinders={25: 1, 9: 4}),
    _case("F04", "flange", "Square flange 100 × 100 × 12 mm with a Ø50 mm bore and four Ø11 mm holes on an 80 × 80 mm "
          "square.",
          [100, 100, 12], 100 * 100 * 12 - pi * 25**2 * 12 - 4 * pi * 5.5**2 * 12, f"""
part = Box(100, 100, 12, align={FLAT}) - Cylinder(25, 12, align={FLAT})
for x in (-40, 40):
    for y in (-40, 40):
        part -= Pos(x, y, 0) * Cylinder(5.5, 12, align={FLAT})
result = part
EXPECTED = {{"bbox": [100, 100, 12], "volume": 100*100*12 - pi*25**2*12 - 4*pi*5.5**2*12, "solids": 1}}
""", cylinders={50: 1, 11: 4}),
    # ------------------------------------------------------------------ enclosures
    _case("E01", "enclosure", "Open-top box 120 × 80 × 50 mm outside, 3 mm walls and a 3 mm floor, sharp edges.",
          [120, 80, 50], 120 * 80 * 50 - 114 * 74 * 47, f"""
result = Box(120, 80, 50, align={FLAT}) - Pos(0, 0, 3) * Box(114, 74, 47, align={FLAT})
EXPECTED = {{"bbox": [120, 80, 50], "volume": 120*80*50 - 114*74*47, "solids": 1}}
"""),
    _case("E02", "enclosure", "Closed hollow box 100 × 60 × 40 mm outside with a uniform 2.5 mm wall all round.",
          [100, 60, 40], 100 * 60 * 40 - 95 * 55 * 35, f"""
result = Box(100, 60, 40, align={FLAT}) - Pos(0, 0, 2.5) * Box(95, 55, 35, align={FLAT})
EXPECTED = {{"bbox": [100, 60, 40], "volume": 100*60*40 - 95*55*35, "solids": 1}}
"""),
    _case("E03", "enclosure", "Open-top tray 150 × 100 × 30 mm outside, 4 mm walls and floor, four Ø3.4 mm holes "
          "through the floor 10 mm in from both adjacent outside edges.",
          [150, 100, 30], 150 * 100 * 30 - 142 * 92 * 26 - 4 * pi * 1.7**2 * 4, f"""
part = Box(150, 100, 30, align={FLAT}) - Pos(0, 0, 4) * Box(142, 92, 26, align={FLAT})
for x in (-65, 65):
    for y in (-40, 40):
        part -= Pos(x, y, 0) * Cylinder(1.7, 4, align={FLAT})
result = part
EXPECTED = {{"bbox": [150, 100, 30], "volume": 150*100*30 - 142*92*26 - 4*pi*1.7**2*4, "solids": 1}}
""", cylinders={3.4: 4}),
    _case("E04", "enclosure", "Cylindrical cup: OD 60 mm, 70 mm tall, 3 mm wall, 5 mm floor, open top.",
          [60, 60, 70], pi * 30**2 * 70 - pi * 27**2 * 65, f"""
result = Cylinder(30, 70, align={FLAT}) - Pos(0, 0, 5) * Cylinder(27, 65, align={FLAT})
EXPECTED = {{"bbox": [60, 60, 70], "volume": pi*30**2*70 - pi*27**2*65, "solids": 1}}
""", cylinders={60: 1, 54: 1}),
]

assert len(CASES) == 20 and len({c["id"] for c in CASES}) == 20
