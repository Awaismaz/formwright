import math

from build123d import *

NAME = "Stepped shaft"
MATERIAL = "Steel 1045"
D1 = 20.0
L1 = 40.0
D2 = 25.0
L2 = 70.0
KW = 6.0  # keyway width, depth (from Ø25 surface), length
KD = 3.5
KL = 30.0
PARAMS = dict(D1=D1, L1=L1, D2=D2, L2=L2, KW=KW, KD=KD, KL=KL)

shaft = Cylinder(D1 / 2, L1, align=(Align.CENTER, Align.CENTER, Align.MIN))
shaft += Pos(0, 0, L1) * Cylinder(D2 / 2, L2, align=(Align.CENTER, Align.CENTER, Align.MIN))
shaft += Pos(0, 0, L1 + L2) * Cylinder(D1 / 2, L1, align=(Align.CENTER, Align.CENTER, Align.MIN))
key = Pos(D2 / 2 - KD, 0, L1 + L2 / 2 - KL / 2) * Box(KD + 1, KW, KL, align=(Align.MIN, Align.CENTER, Align.MIN))
shaft -= key
result = shaft


# Keyway removes the part of the Ø25 cylinder with x > R-KD and |y| < KW/2 over length KL.
_R = D2 / 2
_x0 = _R - KD
_yc = KW / 2
# Area of { x > x0, |y| < yc, x^2 + y^2 < R^2 }: integrate over y.
_n = 4000
_area = sum((math.sqrt(_R**2 - (-_yc + (i + 0.5) * 2 * _yc / _n) ** 2) - _x0) * (2 * _yc / _n) for i in range(_n))
_vol = 2 * math.pi * (D1 / 2) ** 2 * L1 + math.pi * _R**2 * L2 - _area * KL
EXPECTED = {"bbox": [D2, D2, 2 * L1 + L2], "volume": _vol, "solids": 1, "volume_tol": 1e-4}
