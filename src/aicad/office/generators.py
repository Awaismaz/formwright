"""Parametric generators for the Design Office's direct path (WORKLIST 45): the machined and turned parts of a
typical mechanism, built from the approved interfaces with no AI.

``direct.py`` builds shafts, spacers and spur gears. This module adds, per component kind:

* ``housing``  a gearbox base (a block with the ICD's gear cavity): bearing seats in the side walls at the centre
  distance, the cap screw holes on their PCD (the ligament rule of ``icd.py``), the split face with the cover's
  tapped holes and dowel holes, the sump floor, raised cap pads, mounting feet with tapped holes, the wall rule;
* ``cover``    the lid on a housing: through bolt holes and dowel holes, shelled from below over the cavity;
* ``cap``      open and blind bearing caps: flange with clearance holes on the cap PCD, the relief over the inner
  ring, a through bore and a lip-seal recess (DIN 3760 sizes) for open caps;
* ``plate``    base plates, mounting plates, side plates with bearing bores, end blocks, pillow-block style blocks:
  every ICD hole, bore and seat, corner holes the brief asks for at 1.5 d from the edges;
* ``bracket``  L brackets with gussets (foot, upright and gussets from ``fw.gusset``);
* ``pulley``   plain belt pulleys (rim, web, hub), timing pulleys simplified to their pitch Ø, sprockets simplified
  to their pitch Ø, with the ICD's bore and hub keyway;
* ``coupling`` rigid sleeve couplings and set-screw collars.

Each generator reads the part's interface features (``icd.item_features``) and, when the program has a design
graph, the component's parameters (style, sizes), and writes a normal Studio script: ``PARAMS`` with
``PARAM_META`` (so the viewport dimensions DS-038 map every parameter), EXPECTED from hand formulas
(``fw_std.machined_volume``: box or disc less pockets and axis-aligned cuts; Pappus for revolved profiles), and
the same build, check and conformance gate as every other part. Pure: no model call, no CAD kernel.

A part goes direct only when the interfaces fix every feature it carries and the brief asks for nothing these
generators don't make; otherwise ``direct.plan`` sends it to the design agent with the reasons, seeded with the
generator's model when the interfaces do fix it.
"""

from __future__ import annotations

import itertools
import math
import re
from typing import Any

from aicad import fw_std
from aicad.office import icd

VERSION = 1


class Undetermined(Exception):
    """The interfaces don't fix this part: the reason, in plain words (``direct`` re-raises it as its own)."""


# ============================================================================ expressions with their values
def _f(x: float) -> str:
    v = round(float(x), 4) + 0.0
    return f"{v:.1f}" if v.is_integer() else repr(v)


def _g(x: float) -> str:
    return f"{round(float(x), 4) + 0.0:g}"


class V:
    """A number and the script text that computes it from the parameters: ``V("WIDTH", 110) / 2 - DEPTH``."""

    __slots__ = ("prec", "src", "val")

    def __init__(self, src: str, val: float, prec: int = 9) -> None:
        self.src, self.val, self.prec = src, float(val), prec

    @staticmethod
    def of(x: Any) -> V:
        return x if isinstance(x, V) else V(_f(x), float(x))

    def _bin(self, o: Any, op: str, prec: int, fn: Any, swap: bool = False) -> V:
        if not isinstance(o, V) and float(o).is_integer():
            o = V(str(int(float(o))), float(o))  # an operand reads like hand-written code: WIDTH / 2
        a, b = (V.of(o), self) if swap else (self, V.of(o))
        if op in "+-" and a.prec == 9 and not _is_name(a.src) and a.val == 0:
            return b if op == "+" else -b
        if b.prec == 9 and a.prec == 9 and not _is_name(a.src) and not _is_name(b.src):
            v = fn(a.val, b.val)
            return V(_f(v), v)
        ls = a.src if a.prec >= prec else f"({a.src})"
        rs = b.src if (b.prec > prec or (b.prec == prec and op in "+*")) else f"({b.src})"
        return V(f"{ls} {op} {rs}", fn(a.val, b.val), prec)

    def __add__(self, o: Any) -> V:
        if not isinstance(o, V) and float(o) == 0:
            return self
        if not isinstance(o, V) and float(o) < 0:
            return self._bin(-float(o), "-", 1, lambda a, b: a - b)
        return self._bin(o, "+", 1, lambda a, b: a + b)

    def __radd__(self, o: Any) -> V:
        return self._bin(o, "+", 1, lambda a, b: a + b, swap=True)

    def __sub__(self, o: Any) -> V:
        if not isinstance(o, V) and float(o) == 0:
            return self
        if not isinstance(o, V) and float(o) < 0:
            return self._bin(-float(o), "+", 1, lambda a, b: a + b)
        return self._bin(o, "-", 1, lambda a, b: a - b)

    def __rsub__(self, o: Any) -> V:
        return self._bin(o, "-", 1, lambda a, b: a - b, swap=True)

    def __mul__(self, o: Any) -> V:
        return self._bin(o, "*", 2, lambda a, b: a * b)

    def __rmul__(self, o: Any) -> V:
        return self._bin(o, "*", 2, lambda a, b: a * b, swap=True)

    def __truediv__(self, o: Any) -> V:
        return self._bin(o, "/", 2, lambda a, b: a / b)

    def __neg__(self) -> V:
        if self.prec == 9:
            return V(f"-{self.src}" if _is_name(self.src) else _f(-self.val), -self.val, 3)
        return V(f"-({self.src})", -self.val, 3)


def _is_name(s: str) -> bool:
    return bool(re.fullmatch(r"[A-Z_][A-Z0-9_]*", s))


def _src(o: Any, indent: int = 0) -> str:
    if isinstance(o, V):
        return o.src
    if isinstance(o, bool) or o is None:
        return repr(o)
    if isinstance(o, int | float):
        return _f(o)
    if isinstance(o, str):
        return '"' + o.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(o, tuple):
        return "(" + ", ".join(_src(x) for x in o) + ("," if len(o) == 1 else "") + ")"
    if isinstance(o, list):
        return "[" + ", ".join(_src(x) for x in o) + "]"
    if isinstance(o, dict):
        return "{" + ", ".join(f'"{k}": {_src(v)}' for k, v in o.items()) + "}"
    raise TypeError(type(o))


def _num(o: Any) -> Any:
    if isinstance(o, V):
        return o.val
    if isinstance(o, tuple):
        return tuple(_num(x) for x in o)
    if isinstance(o, list):
        return [_num(x) for x in o]
    if isinstance(o, dict):
        return {k: _num(v) for k, v in o.items()}
    return o


class Script:
    """Parameters (with their PARAM_META rows) and the lines of a generated Studio script."""

    def __init__(self) -> None:
        self.params: list[tuple[str, float, str, tuple[float, float, float, str, str, str]]] = []
        self.names: set[str] = set()

    def p(self, name: str, value: float, comment: str, group: str, label: str, lo: float | None = None,
          hi: float | None = None, step: float = 0.5, unit: str = "mm") -> V:
        v = round(float(value), 4) + 0.0
        if name in self.names:
            return V(name, v)
        lo = round(min(v, lo if lo is not None else max(0.5, 0.5 * v) if v > 0 else 2 * v), 2)
        hi = round(max(v, hi if hi is not None else max(2 * v, v + 10) if v >= 0 else 0.5 * v), 2)
        self.params.append((name, v, comment, (lo, hi, step, unit, group, label)))
        self.names.add(name)
        return V(name, v)

    def block(self) -> list[str]:
        out = [f"{n} = {_f(v)}  # {c}" for n, v, c, _m in self.params]
        out += ["", _params([n for n, *_ in self.params]), _meta([(n, *m) for n, _v, _c, m in self.params])]
        return out


def _params(names: list[str]) -> str:
    lines, cur = [], "PARAMS = dict("
    for k, n in enumerate(names):
        bit = f"{n}={n}" + (", " if k < len(names) - 1 else ")")
        if len(cur) + len(bit) > 110:
            lines.append(cur.rstrip())
            cur = " " * 14
        cur += bit
    return "\n".join([*lines, cur])


def _meta(rows: list[tuple[str, float, float, float, str, str, str]]) -> str:
    lines = ["PARAM_META = {"]
    for name, lo, hi, step, unit, group, label in rows:
        u = f', "unit": "{unit}"' if unit else ""
        lines.append(f'    "{name}": {{"min": {_f(lo)}, "max": {_f(hi)}, "step": {_g(step)}{u}, "group": "{group}", '
                     f'"label": "{label}"}},')
    lines.append("}")
    return "\n".join(lines)


def _rows(name: str, rows: list[tuple[Any, str]]) -> list[str]:
    """``name = [`` one row per line with its comment ``]``."""
    if not rows:
        return [f"{name} = []"]
    out = [f"{name} = ["]
    for r, why in rows:
        out.append(f"    {_src(r)}," + (f"  # {why}" if why else ""))
    out.append("]")
    return out


def header(name: str, what: str, icd_version: int, lines: list[str], notes: list[str]) -> str:
    body = "\n".join(f"  {x}" for x in lines)
    extra = ("\nDesign choices (not in the interfaces; edit freely):\n" + "\n".join(f"  {x}" for x in notes)) if notes \
        else ""
    return (f'"""{name}: {what}, built from the approved interface spec (ICD v{icd_version}).\n\n'
            "Modelled in the ICD part frame (origin at the centre of its envelope); the program assembly places it\n"
            f"from there. What the interfaces fix:\n{body}{extra}\nFits are drawing callouts: the model is at nominal "
            "size. The parameters below can be edited freely;\nkeep the interface sizes unless the ICD changes.\n"
            '"""\n')


# ============================================================================ standards used here (verify, PD-13)
# DIN 3760 / ISO 6194-1 rotary shaft lip seals, one common size per shaft Ø: d -> (D outside Ø, b width), mm.
SEALS: dict[float, tuple[float, float]] = {
    10: (22, 7), 12: (22, 7), 15: (26, 7), 17: (30, 7), 20: (35, 7), 22: (35, 7), 25: (40, 7), 28: (42, 7),
    30: (42, 7), 32: (47, 7), 35: (50, 7), 40: (55, 8), 45: (62, 8), 50: (68, 8), 55: (72, 8), 60: (80, 8)}
SEALS_SOURCE = "DIN 3760 / ISO 6194-1 lip seal sizes (verify against the seal maker's catalogue)"
# timing belts: pitch (mm) and the pitch line differential u (PD - OD = 2u), verify against the belt maker
BELTS: dict[str, tuple[float, float]] = {"GT2": (2.0, 0.254), "GT3": (3.0, 0.381), "HTD 3M": (3.0, 0.381),
                                         "HTD 5M": (5.0, 0.5715), "HTD 8M": (8.0, 0.686), "T2.5": (2.5, 0.3),
                                         "T5": (5.0, 0.5), "T10": (10.0, 1.0), "XL": (5.08, 0.254),
                                         "L": (9.525, 0.381)}
# ISO 606 / ANSI roller chains: pitch p, inner width b1 (mm); tooth width 0.93 b1 (verify)
CHAINS: dict[str, tuple[float, float]] = {"04B": (6.0, 2.8), "05B": (8.0, 3.0), "06B": (9.525, 5.72),
                                          "08B": (12.7, 7.75), "10B": (15.875, 9.65), "12B": (19.05, 11.68),
                                          "25": (6.35, 3.18), "35": (9.525, 4.77), "40": (12.7, 7.85),
                                          "50": (15.875, 9.4), "60": (19.05, 12.57)}
FOOT_EDGE = 1.5   # x d: hole centre to the nearest edge (founder's rule for plates and feet)
PAD_MARGIN = 2.0  # mm a cap pad stands beyond the cap's OD
PAD_RELIEF = 2.0  # mm the outer wall face is relieved around the cap pads
FOOT_RELIEF = 2.0  # mm the underside is relieved between the feet
RIM = 10.0        # mm band round the edge of a relieved face


def seal_for(d: float) -> tuple[float, float] | None:
    k = round(float(d), 3)
    return SEALS.get(k) if k in SEALS else None


def tap_drill(m: int) -> float:
    return float(icd.TAP_DRILL[m])


def mount_size(L: float) -> int:
    """Foundation bolts for a housing of footprint length L (a rule of thumb, stated in the script)."""
    return 6 if L < 120 else 8 if L < 250 else 10 if L < 400 else 12


# ============================================================================ features in part coordinates
def part_c(x: dict[str, Any]) -> tuple[str, tuple[float, float]]:
    """(axis, position across it in part axes) of a cylindrical ICD feature. ICD features along X / Y are written
    in their canonical frame (``frames.CANON``): along Y, canonical (cx, cy) is part (X, -Z); along X, part (Y, -Z)
    with canonical X = -Z... see ``fw_std._ACROSS`` for the order of the two coordinates."""
    ax = x.get("ax") or "z"
    cx, cy = float(x["c"][0]), float(x["c"][1])
    if ax == "z":
        return "z", (cx, cy)
    if ax == "y":
        return "y", (cx, -cy + 0.0)
    return "x", (cy, -cx + 0.0)


def _r(x: float) -> float:
    return round(float(x), 4) + 0.0


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _ext_name(ax: str) -> str:
    return {"x": "LENGTH", "y": "WIDTH", "z": "HEIGHT"}[ax]


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", " ", s).strip()


def _pattern(pts: list[tuple[float, float]]) -> tuple[str, Any]:
    """The shape of a set of hole centres: ("grid", (cx, cy, px, py)) for a symmetric 2 x 2 grid, ("pair", (cx, cy,
    p, axis)) for two holes, ("circle", (cx, cy, pcd, [angles])) for three or more on a circle, else ("list", pts)."""
    n = len(pts)
    cx, cy = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    cx, cy = _r(cx), _r(cy)
    if n == 4:
        dx = sorted({_r(abs(p[0] - cx)) for p in pts})
        dy = sorted({_r(abs(p[1] - cy)) for p in pts})
        quads = {(p[0] > cx, p[1] > cy) for p in pts}
        if len(dx) == 1 and len(dy) == 1 and len(quads) == 4 and dx[0] > 0 and dy[0] > 0:
            return "grid", (cx, cy, 2 * dx[0], 2 * dy[0])
    if n == 2:
        a, b = pts
        if abs(a[1] - b[1]) < 1e-6:
            return "pair", (cx, cy, _r(abs(a[0] - b[0])), "x")
        if abs(a[0] - b[0]) < 1e-6:
            return "pair", (cx, cy, _r(abs(a[1] - b[1])), "y")
    if n >= 3:
        rs = [math.hypot(p[0] - cx, p[1] - cy) for p in pts]
        if max(rs) - min(rs) < 1e-3 and rs[0] > 0:
            ang = [_r(math.degrees(math.atan2(p[1] - cy, p[0] - cx)) % 360) for p in pts]
            return "circle", (cx, cy, _r(2 * rs[0]), ang)
    return "list", pts


def _on_pcd(c: V, pcd: V, fn: str, a: float, v: float) -> V:
    lead = "" if c.prec == 9 and not _is_name(c.src) and c.val == 0 else f"{c.src} + "
    return V(f"{lead}{pcd.src} / 2 * math.{fn}(math.radians({_g(a)}))", c.val + pcd.val / 2 * v, 1)


def _pos_exprs(S: Script, pts: list[tuple[float, float]], pre: str, group: str, what: str, ax: str,
               centre: tuple[V, V] | None = None, pcd: float | None = None) -> list[tuple[V, V]]:
    """Hole centres as expressions of a few parameters (pattern centre and pitches, or a PCD)."""
    u_n, v_n = {"z": ("X", "Y"), "y": ("X", "Z"), "x": ("Y", "Z")}[ax]
    kind, d = _pattern(pts)
    if centre is not None and kind in ("grid", "pair", "list") and len(pts) >= 3:
        kind, d = "circle", None
    if kind == "circle" or centre is not None and len(pts) >= 3:
        cx, cy = (centre[0].val, centre[1].val) if centre else (d[0], d[1])
        rs = [math.hypot(p[0] - cx, p[1] - cy) for p in pts]
        if max(rs) - min(rs) > 1e-3:
            return [(V.of(p[0]), V.of(p[1])) for p in pts]
        ang = [_r(math.degrees(math.atan2(p[1] - cy, p[0] - cx)) % 360) for p in pts]
        if centre is None:
            centre = (S.p(f"{pre}_{u_n}", cx, f"{what}: pattern centre {u_n}, mm", group, f"{_cap(_slug(what))} centre {u_n}",
                          lo=cx - 50, hi=cx + 50),
                      S.p(f"{pre}_{v_n}", cy, f"{what}: pattern centre {v_n}, mm", group, f"{_cap(_slug(what))} centre {v_n}",
                          lo=cy - 50, hi=cy + 50))
        pv = pcd if pcd is not None and abs(pcd - 2 * rs[0]) < 0.05 else _r(2 * rs[0])
        pcd = S.p(f"{pre}_PCD", pv, f"{what}: pitch circle Ø, mm", group, f"{_cap(what)} PCD")
        out = []
        ang = [float(round(a)) if abs(a - round(a)) < 0.05 else a for a in ang]
        for a in ang:
            ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
            out.append((_on_pcd(centre[0], pcd, "cos", a, ca), _on_pcd(centre[1], pcd, "sin", a, sa)))
        return out
    if kind == "grid":
        cx, cy, px, py = d
        X = S.p(f"{pre}_{u_n}", cx, f"{what}: pattern centre {u_n}, mm", group, f"{_cap(_slug(what))} centre {u_n}",
                lo=cx - 50, hi=cx + 50) if cx else V.of(0.0)
        Y = S.p(f"{pre}_{v_n}", cy, f"{what}: pattern centre {v_n}, mm", group, f"{_cap(_slug(what))} centre {v_n}",
                lo=cy - 50, hi=cy + 50) if cy else V.of(0.0)
        PX = S.p(f"{pre}_PITCH_{u_n}", px, f"{what}: hole spacing along {u_n}, mm", group,
                 f"{_cap(_slug(what))} spacing {u_n}")
        PY = S.p(f"{pre}_PITCH_{v_n}", py, f"{what}: hole spacing along {v_n}, mm", group,
                 f"{_cap(_slug(what))} spacing {v_n}")
        return [(X + PX / 2 if p[0] > cx else X - PX / 2, Y + PY / 2 if p[1] > cy else Y - PY / 2) for p in pts]
    if kind == "pair":
        cx, cy, pp, along = d
        X = S.p(f"{pre}_{u_n}", cx, f"{what}: pattern centre {u_n}, mm", group, f"{_cap(_slug(what))} centre {u_n}",
                lo=cx - 50, hi=cx + 50) if cx else V.of(0.0)
        Y = S.p(f"{pre}_{v_n}", cy, f"{what}: pattern centre {v_n}, mm", group, f"{_cap(_slug(what))} centre {v_n}",
                lo=cy - 50, hi=cy + 50) if cy else V.of(0.0)
        nm = u_n if along == "x" else v_n
        P = S.p(f"{pre}_PITCH", pp, f"{what}: hole spacing along {nm}, mm", group, f"{_cap(_slug(what))} spacing")
        if along == "x":
            return [(X + P / 2 if p[0] > cx else X - P / 2, Y) for p in pts]
        return [(X, Y + P / 2 if p[1] > cy else Y - P / 2) for p in pts]
    return [(V.of(p[0]), V.of(p[1])) for p in pts]


# ============================================================================ the part's context
class Ctx:
    """What a generator reads: the skeleton, the interfaces, the item and the plan's words about it."""

    def __init__(self, doc: dict[str, Any], item: str, name: str, desc: str) -> None:
        self.doc, self.item, self.name, self.desc = doc, item, name, desc
        self.sk = doc["skeleton"]
        self.ifs = doc["icd"]["interfaces"]
        self.it = self.sk["items"][item]
        self.byif = {f["id"]: f for f in self.ifs}
        self.feats = icd.item_features(self.sk, self.ifs, item)
        self.icd_version = doc["icd"]["version"]
        self.graph = graph_component(doc, name)

    def other(self, f: dict[str, Any]) -> str:
        return f["b"]["name"] if f["a"]["item"] == self.item else f["a"]["name"]

    def side(self, f: dict[str, Any]) -> str:
        return "a" if f["a"]["item"] == self.item else "b"

    def m_sizes(self) -> set[int]:
        out = set()
        for f in self.ifs:
            if self.item in (f["a"]["item"], f["b"]["item"]) and f["kind"] == "hole_pattern"                     and f["data"].get("fastener_size"):
                out.add(int(f["data"]["fastener_size"]))
        return out


def graph_component(doc: dict[str, Any], name: str) -> dict[str, Any] | None:
    """The design graph's component for this part (kind and parameter values), when the program has a graph."""
    g = (doc.get("plan") or {}).get("graph") or {}
    data = g.get("data") or {}
    for c in data.get("components") or []:
        if str(c.get("name")) == name:
            params = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in (c.get("params") or {}).items()}
            return {"kind": c.get("kind"), "params": params, "id": c.get("id")}
    return None


def graph_kinds(doc: dict[str, Any]) -> list[dict[str, Any]]:
    g = (doc.get("plan") or {}).get("graph") or {}
    out = []
    for c in (g.get("data") or {}).get("components") or []:
        params = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in (c.get("params") or {}).items()}
        out.append({"kind": c.get("kind"), "name": c.get("name"), "params": params})
    return out


_CAPPY = re.compile(r"\bcaps?\b|end cover|bearing cover", re.IGNORECASE)
_LIDDY = re.compile(r"\bcover\b|\blid\b", re.IGNORECASE)
_BRACKETY = re.compile(r"\bbrackets?\b|\bangle\b|\bl[- ]?brackets?\b", re.IGNORECASE)
_PULLEYY = re.compile(r"\bpulleys?\b|\bsheaves?\b|\bsprockets?\b", re.IGNORECASE)
_COUPLY = re.compile(r"\bcouplings?\b", re.IGNORECASE)


def kind_of(doc: dict[str, Any], item: str, name: str, desc: str) -> str | None:
    """Which generator builds this part, or None (the design agent)."""
    sk = doc["skeleton"]
    it = sk["items"][item]
    g = graph_component(doc, name) or {}
    gk = g.get("kind")
    role = it.get("role")
    if role == "block" and it.get("shape") == "box":
        cav = it.get("cavity") or {}
        if cav and cav.get("wall") is not None and any(
                f["kind"] == "bearing_seat" and f["a"]["item"] == item for f in doc["icd"]["interfaces"]):
            return "housing"
        if gk == "cover" or (_LIDDY.search(name) and _host_cavity(doc, item) is not None):
            return "cover"
        if _BRACKETY.search(name) and gk not in ("plate", "housing"):
            return "bracket"
        if gk == "bracket" and not cav and _foot_only(doc, item):
            return "bracket"
        return "plate"
    if role == "hub" and it.get("shape") == "cylinder":
        caps = [f for f in doc["icd"]["interfaces"] if f["kind"] == "hole_pattern" and f["b"]["item"] == item
                and (f["data"] or {}).get("cap")]
        if caps and (gk == "bearing_cap" or _CAPPY.search(name) or gk is None):
            return "cap"
        if gk == "pulley" or _PULLEYY.search(name):
            return "pulley"
        if _COUPLY.search(name):
            return "coupling"
        if gk in ("hub", "spacer") or _HUBBY.search(name):
            return "hub"
        return None
    return None


_HUBBY = re.compile(r"\b(hub|tube|drum|roller|wheel|disc|disk|flange|bush(?:ing)?|sleeve|boss|ring)s?\b", re.IGNORECASE)


def _foot_only(doc: dict[str, Any], item: str) -> bool:
    """Every interface feature of a block is on its bottom face (an L bracket can carry them on its foot)."""
    sk = doc["skeleton"]
    H = float(sk["items"][item]["size"][2])
    for x in icd.item_features(sk, doc["icd"]["interfaces"], item):
        if x.get("ax"):
            return False
        if x["type"] == "face" and not (abs(float(x["z"]) + H / 2) < 0.01 and int(x["n"]) < 0):
            return False
        if x["type"] == "hole" and x.get("z0") is not None:
            return False
        if x["type"] not in ("face", "hole"):
            return False
    return True


def _host_cavity(doc: dict[str, Any], item: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """(host item, its cavity) when this part is bolted onto a housing with a gear cavity (the lid)."""
    sk = doc["skeleton"]
    for f in doc["icd"]["interfaces"]:
        if f["kind"] == "hole_pattern" and f["b"]["item"] == item:
            host = sk["items"].get(f["a"]["item"]) or {}
            if host.get("cavity"):
                return host, host["cavity"]
    return None


# ============================================================================ machined blocks (housing, cover, plate)
_SHAPE_WORDS = re.compile(r"\b(lugs?|clevis|ribs?|bosses|boss|pockets?|slots?|slotted|counter ?bored?|counter ?sunk|"
                          r"countersinks?|steps?|stepped|grooves?|tabs?|ears?|forks?|yoke|windows?|cut-?outs?|notch(?:es)?|"
                          r"t-?slots?|dovetails?|spigots?|fins?|webs?|chamfer(?:ed|s)?|fillet(?:ed|s)?|radius(?:ed)?|"
                          r"rounded|knurl\w*|engrav\w*|logo|knuckles?)\b", re.IGNORECASE)
_CORNER = re.compile(r"\b(two|four|2|4)\s+[ØⲐ⌀]\s*(\d+(?:\.\d+)?)\s*(?:mm\s*)?(?:corner|mounting|fixing)\s+holes?\b",
                     re.IGNORECASE)


def _ends(S: Script, ax: str, s0: float, s1: float, ext: V, depth: V | None) -> tuple[V, V]:
    """A span along an axis as expressions: the faces (±ext / 2) and a depth from them, else literals."""
    def one(z: float) -> V:
        cands = [ext / 2, -(ext / 2)]
        if depth is not None:
            cands += [ext / 2 - depth, -(ext / 2) + depth]
        for c in cands:
            if abs(c.val - z) < 1e-6:
                return c
        return V.of(z)
    return one(s0), one(s1)


def _face_ok(x: dict[str, Any], ext: dict[str, float], cuts_num: list[dict[str, Any]],
             pockets_num: list[dict[str, Any]]) -> bool:
    ax = x.get("ax") or "z"
    z, n = float(x["z"]), int(x["n"])
    half = ext[ax] / 2
    if abs(abs(z) - half) < 0.01 and z * n > 0:
        return True
    for c in cuts_num:
        if c["ax"] != ax or c.get("span") is None:
            continue
        if any(abs(float(e) - z) < 0.01 for e in c["span"]):
            return True
    a = fw_std._AX[ax]
    for p in pockets_num:  # a pocket's floor (a shoulder face inside a relieved face)
        if abs(float(p["min"][a]) - z) < 0.01 or abs(float(p["max"][a]) - z) < 0.01:
            return True
    return False


def block_spec(kind: str, cx: Ctx) -> dict[str, Any]:
    it = cx.it
    L, W, H = (float(v) for v in it["size"])
    S = Script()
    ext_num = {"x": L, "y": W, "z": H}
    word = {"housing": "Housing", "cover": "Cover", "plate": "Block"}[kind]
    LENGTH = S.p("LENGTH", L, "mm along X (ICD envelope)", word, "Length", lo=10)
    WIDTH = S.p("WIDTH", W, "mm along Y (ICD envelope)", word, "Width", lo=10)
    HEIGHT = S.p("HEIGHT", H, "mm along Z (ICD envelope)" + (" (thickness)" if H < 0.4 * min(L, W) else ""), word,
                 "Height" if H >= 0.4 * min(L, W) else "Thickness", lo=2)
    EXT = {"x": LENGTH, "y": WIDTH, "z": HEIGHT}
    lines: list[str] = []
    notes: list[str] = []
    cuts: list[tuple[dict[str, Any], str]] = []
    pockets: list[tuple[dict[str, Any], str]] = []
    optional: list[str] = []  # design additions that may be dropped (rows carry "_opt": the name)
    faces: list[dict[str, Any]] = []
    known: set[float] = {L, W, H}
    m_sizes = cx.m_sizes()
    n_feat = 0
    groups: dict[str, list[dict[str, Any]]] = {}
    for x in cx.feats:
        t = x["type"]
        if t == "face":
            faces.append(x)
            continue
        if t not in ("hole", "seat"):
            raise Undetermined(f"{x['label']} is not a feature of a machined block this can build")
        groups.setdefault(x["if"], []).append(x)
    # ---- bearing seats first (the cap holes and pads refer to their axes)
    seat_axes: list[dict[str, Any]] = []
    axis_z: V | None = None
    n_seat = 0
    for iid, xs in groups.items():
        f = cx.byif[iid]
        if f["kind"] != "bearing_seat":
            continue
        n_seat += 1
        d = f["data"]
        seats = [x for x in xs if x.get("fit")]
        clear = [x for x in xs if not x.get("fit")]
        ax, c = part_c(seats[0] if seats else xs[0])
        if any(part_c(x) != (ax, c) for x in xs):
            raise Undetermined(f"the bearing seats of {cx.other(f)} are not on one axis")
        k = n_seat
        grp = f"Seat {k}"
        other = cx.other(f)
        D = S.p(f"SEAT_{k}_D", float(d["D"]), f"bearing seat Ø, mm ({d['designation']} outer ring, H7) for the {other}",
                grp, f"Seat {k} Ø")
        B = S.p(f"SEAT_{k}_DEPTH", float(d["B"]), f"seat depth, mm (the {d['designation']}'s width B)", grp,
                f"Seat {k} depth")
        known |= {float(d["D"]), float(d["B"]), float(d["d"])}
        u_n, v_n = {"z": ("X", "Y"), "y": ("X", "Z"), "x": ("Y", "Z")}[ax]
        U = S.p(f"SEAT_{k}_{u_n}", c[0], f"{other} axis {u_n}, mm", grp, f"Seat {k} {u_n}", lo=c[0] - 100,
                hi=c[0] + 100) if abs(c[0]) > 1e-9 else V.of(0.0)
        if ax == "y" and axis_z is not None and abs(axis_z.val - c[1]) < 1e-6:
            Vv = axis_z
        elif ax == "y":
            Vv = S.p("AXIS_Z" if axis_z is None else f"SEAT_{k}_Z", c[1], "shaft axes height from the envelope "
                     "centre, mm" if axis_z is None else f"{other} axis Z, mm", "Seats", "Shaft axes Z",
                     lo=c[1] - 50, hi=c[1] + 50) if abs(c[1]) > 1e-9 else V.of(0.0)
            if axis_z is None:
                axis_z = Vv
        else:
            Vv = S.p(f"SEAT_{k}_{v_n}", c[1], f"{other} axis {v_n}, mm", grp, f"Seat {k} {v_n}", lo=c[1] - 100,
                     hi=c[1] + 100) if abs(c[1]) > 1e-9 else V.of(0.0)
        seat_axes.append({"k": k, "ax": ax, "c": c, "U": U, "V": Vv, "D": D, "if": iid, "other": other})
        for x in seats:
            s0, s1 = _ends(S, ax, float(x["z0"]), float(x["z1"]), EXT[ax], B)
            cuts.append(({"name": f"Bearing seats ({other}, {d['designation']})", "ax": ax, "c": (U, Vv), "d": D,
                          "span": (s0, s1)}, f"{iid} {x['label']}"))
            n_feat += 1
        for x in clear:
            CL = S.p(f"CLEAR_{k}_D", float(x["d"]), f"shaft clearance Ø behind the seats, mm ({other})", grp,
                     f"Seat {k} clearance Ø")
            known.add(float(x["d"]))
            s0, s1 = _ends(S, ax, float(x["z0"]), float(x["z1"]), EXT[ax], B)
            cuts.append(({"name": f"Shaft clearance ({other})", "ax": ax, "c": (U, Vv), "d": CL, "span": (s0, s1)},
                         f"{iid} {x['label']}"))
            n_feat += 1
        lines.append(f"{iid}  bearing seat{'s' if len(seats) != 1 else ''} Ø{_g(d['D'])} H7 × {_g(d['B'])} deep for the "
                     f"{other} ({d['designation']}), axis along {ax.upper()} at {u_n} {_g(c[0])}, {v_n} {_g(c[1])}")
    for a, b in itertools.pairwise(seat_axes):
        if a["ax"] == b["ax"]:
            known.add(_r(math.hypot(a["c"][0] - b["c"][0], a["c"][1] - b["c"][1])))
    # ---- hole patterns, dowels, bores
    n_h = 0
    cap_od: dict[int, float] = {}
    for iid, xs in groups.items():
        f = cx.byif[iid]
        if f["kind"] == "bearing_seat":
            continue
        d = f["data"]
        ax, _c0 = part_c(xs[0])
        if any(part_c(x)[0] != ax for x in xs):
            raise Undetermined(f"the holes of {iid} are not parallel")
        other = cx.other(f)
        pts = [part_c(x)[1] for x in xs]
        dd = {float(x["d"]) for x in xs}
        if len(dd) != 1:
            raise Undetermined(f"the holes of {iid} differ in size")
        dia = dd.pop()
        known.add(dia)
        blind = [x for x in xs if x.get("z0") is not None]
        if f["kind"] == "dowel":
            grp, pre, what = "Dowels", "DOWEL", f"dowel holes ({other})"
            DIA = S.p("DOWEL_D", dia, f"dowel hole Ø, mm (H7 for {d.get('standard') or 'ISO 8734'} pins)", grp,
                      "Dowel hole Ø")
            thread = None
            kind_txt = f"{len(xs)} dowel holes Ø{_g(dia)} H7 (with the {other})"
        elif f["kind"] == "hole_pattern" and d.get("cap") and cx.side(f) == "a":
            seat = next((s for s in seat_axes if s["ax"] == ax and math.hypot(
                s["c"][0] - _cap_centre(f, cx)[0], s["c"][1] - _cap_centre(f, cx)[1]) < 1e-6), None)
            if seat is None:
                raise Undetermined(f"the cap screws of the {other} are not round a bearing seat")
            k = seat["k"]
            grp, pre = f"Seat {k}", f"CAP_{k}"
            what = f"cap screws round seat {k}"
            DIA = S.p("CAP_TAP_D", dia, f"cap screw tap drill Ø, mm (M{d['fastener_size']}, ISO 2306)", "Cap screws",
                      "Cap screw tap drill")
            thread = f"M{d['fastener_size']}x{_pitch(int(d['fastener_size'])):g}"
            kind_txt = (f"{len(xs)} tapped holes M{d['fastener_size']} × {_g(d['tapped']['depth'])} deep on PCD "
                        f"{_g(d['pcd'])} for the {other} ({d['cap']} cap)")
            known |= {float(d["pcd"]), float(d["tapped"]["depth"]), float(d.get("seat_D") or 0)}
            cap_od[k] = max(cap_od.get(k, 0.0), float(cx.sk["items"][f["b"]["item"]]["size"][0]))
        elif f["kind"] == "hole_pattern":
            n_h += 1
            grp, pre, what = f"Holes {n_h}", f"HOLES_{n_h}", f"holes for the {other}"
            tp = d.get("tapped") if cx.side(f) == "a" else None
            if tp:
                DIA = S.p(f"HOLES_{n_h}_D", dia, f"tap drill Ø, mm ({tp['thread']}, ISO 2306) for the {other}", grp,
                          f"Holes {n_h} tap drill")
                thread = f"{tp['thread']}x{_pitch(int(d['fastener_size'])):g}"
                kind_txt = f"{len(xs)} tapped holes {tp['thread']} × {_g(tp['depth'])} deep for the {other}"
                known.add(float(tp["depth"]))
            else:
                DIA = S.p(f"HOLES_{n_h}_D", dia, f"clearance hole Ø, mm (M{d.get('fastener_size')}, ISO 273) for the "
                          f"{other}", grp, f"Holes {n_h} Ø")
                thread = None
                kind_txt = f"{len(xs)} holes Ø{_g(dia)} for the {other}'s {d.get('fastener') or ''} fasteners".replace(
                    "  ", " ")
            for k in ("inset", "pcd"):
                if d.get(k):
                    known.add(float(d[k]))
        elif f["kind"] == "shaft_bore":
            n_h += 1
            grp, pre, what = f"Bore {n_h}", f"BORE_{n_h}", f"bore for the {other}"
            DIA = S.p(f"BORE_{n_h}_D", dia, f"bore Ø, mm ({x_fit(xs[0])} for the {other})", grp, f"Bore {n_h} Ø")
            thread = None
            kind_txt = f"bore Ø{_g(dia)} {x_fit(xs[0])} for the {other}"
        else:
            raise Undetermined(f"{xs[0]['label']} ({f['kind']}) is not a block feature this can build")
        depth = None
        if blind:
            ds = {_r(float(x["z1"]) - float(x["z0"])) for x in blind}
            if len(ds) == 1 and pre.startswith("CAP_"):
                depth = S.p("CAP_TAP_DEPTH", ds.pop(), "cap screw hole depth, mm (2.5 d + 3)", "Cap screws",
                            "Cap screw hole depth")
            elif len(ds) == 1:
                depth = S.p(f"{pre}_DEPTH", ds.pop(), f"hole depth, mm ({what})", grp, f"{_cap(_slug(what))} depth")
        centre = None
        if pre.startswith("CAP_"):
            s = next(s for s in seat_axes if s["k"] == int(pre.split("_")[1]))
            centre = (s["U"], s["V"])
        if len(pts) == 1 and not centre:
            u_n, v_n = {"z": ("X", "Y"), "y": ("X", "Z"), "x": ("Y", "Z")}[ax]
            P = [(S.p(f"{pre}_{u_n}", pts[0][0], f"{what}: {u_n}, mm", grp, f"{_cap(_slug(what))} {u_n}", lo=pts[0][0] - 50,
                      hi=pts[0][0] + 50) if abs(pts[0][0]) > 1e-9 else V.of(0.0),
                  S.p(f"{pre}_{v_n}", pts[0][1], f"{what}: {v_n}, mm", grp, f"{_cap(_slug(what))} {v_n}", lo=pts[0][1] - 50,
                      hi=pts[0][1] + 50) if abs(pts[0][1]) > 1e-9 else V.of(0.0))]
        else:
            P = _pos_exprs(S, pts, pre, grp, what, ax, centre, float(d["pcd"]) if d.get("pcd") else None)
        nm = {"DOWEL": "Dowel holes"}.get(pre, None) or (f"Cap screw holes ({other})" if pre.startswith("CAP_")
                                                          else f"{what[0].upper()}{what[1:]}")
        for x, p in zip(xs, P, strict=True):
            span = None
            if x.get("z0") is not None:
                span = _ends(S, ax, float(x["z0"]), float(x["z1"]), EXT[ax], depth)
            row: dict[str, Any] = {"name": nm, "ax": ax, "c": p, "d": DIA, "span": span}
            if thread and span is not None:
                row["thread"] = thread
            cuts.append((row, f"{iid} {x['label']}"))
            n_feat += 1
        lines.append(f"{iid}  {kind_txt}")
    ctx = {"S": S, "EXT": EXT, "L": L, "W": W, "H": H, "notes": notes, "lines": lines, "cuts": cuts,
           "pockets": pockets, "optional": optional, "known": known, "m_sizes": m_sizes, "seat_axes": seat_axes,
           "cap_od": cap_od, "axis_z": axis_z}
    if kind == "housing":
        _housing_extras(cx, ctx)
    elif kind == "cover":
        _cover_extras(cx, ctx)
    else:
        _plate_extras(cx, ctx)
    body = ("box", LENGTH, WIDTH, HEIGHT)
    # validate with the hand formula; drop optional design additions that don't fit, last added first
    while True:
        info = fw_std.machined_volume(_num(body), [_num(_clean(p)) for p, _w in pockets],
                                      [_num(_clean(c)) for c, _w in cuts])
        if not info["problems"]:
            break
        drop = optional.pop() if optional else None
        if drop is None:
            raise Undetermined("the interface features overlap: " + info["problems"][0])
        cuts[:] = [c for c in cuts if c[0].get("_opt") != drop]
        pockets[:] = [p for p in pockets if p[0].get("_opt") != drop]
        notes[:] = [n for n in notes if not n.startswith(drop)]
        notes.append(f"{drop}: left out (it would cross an interface feature: {info['problems'][0]}).")
    cuts_num = [_num(_clean(c)) for c, _w in cuts]
    pk_num = [_num(_clean(p)) for p, _w in pockets]
    for x in faces:
        if not _face_ok(x, ext_num, cuts_num, pk_num):
            raise Undetermined(f"{x['label']} at {(x.get('ax') or 'z').upper()} {_g(x['z'])} is not a face of the block")
        lines.append(f"{x['if']}  {x['label']} at {(x.get('ax') or 'z').upper()} {_g(x['z'])}")
        n_feat += 1
    for c in cuts_num:
        known.add(_r(c["d"]))
        if c.get("span") is not None:
            known.add(_r(abs(c["span"][1] - c["span"][0])))
    return {"kind": kind, "S": S, "body": body, "cuts": cuts, "pockets": pockets, "lines": lines, "notes": notes,
            "known": known, "m_sizes": m_sizes | ctx.get("m_extra", set()), "n_features": n_feat,
            "volume": info["volume"], "summary": ctx.get("summary") or _block_summary(kind, cx, ctx),
            "allowed": ctx.get("allowed", set()), "word": word}


def x_fit(x: dict[str, Any]) -> str:
    return str(x.get("fit") or "")


def _pitch(m: int) -> float:
    from aicad import holes

    return float(holes.PITCH[m])


def _cap_centre(f: dict[str, Any], cx: Ctx) -> tuple[float, float]:
    """The cap's centre (the seat axis) in the host's part coordinates across the cap axis."""
    side = f["a"]
    d = f["data"]
    ax = icd.ax_of(d)
    p = icd._part_pt(cx.sk, side, icd.point3(ax, d["centre"], d["plane_z"]))
    if ax == "y":
        return _r(p[0]), _r(p[2])
    if ax == "x":
        return _r(p[1]), _r(p[2])
    return _r(p[0]), _r(p[1])


def _block_summary(kind: str, cx: Ctx, ctx: dict[str, Any]) -> str:
    L, W, H = ctx["L"], ctx["W"], ctx["H"]
    n_holes = sum(1 for c, _w in ctx["cuts"] if not c["name"].startswith(("Bearing", "Shaft clearance")))
    n_seats = sum(1 for c, _w in ctx["cuts"] if c["name"].startswith("Bearing"))
    bits = [f"{'block' if H >= 0.4 * min(L, W) else 'plate'} {_g(L)} × {_g(W)} × {_g(H)}"]
    if n_seats:
        bits.append(f"{n_seats} bearing seat{'s' if n_seats != 1 else ''}")
    if n_holes:
        bits.append(f"{n_holes} hole{'s' if n_holes != 1 else ''}")
    return ", ".join(bits)


def _housing_extras(cx: Ctx, ctx: dict[str, Any]) -> None:
    """The gear cavity, the wall rule, cap pads and mounting feet."""
    S, EXT, notes = ctx["S"], ctx["EXT"], ctx["notes"]
    LENGTH, WIDTH, HEIGHT = EXT["x"], EXT["y"], EXT["z"]
    cav = cx.it["cavity"]
    L, W, H = ctx["L"], ctx["W"], ctx["H"]
    seat_axes = ctx["seat_axes"]
    rule_B = max([float(cx.byif[s["if"]]["data"]["B"]) for s in seat_axes] or [0.0]) + icd.SHOULDER
    cap_depth = next((c["span"][1].val - c["span"][0].val for c, _w in ctx["cuts"] if c.get("thread")
                      and c["name"].startswith("Cap screw")), 0.0)
    rule = max(rule_B, cap_depth + 3.0 if cap_depth else 0.0, 12.0)
    WALL = S.p("WALL", float(cav["wall"]), f"side wall thickness, mm (rule: >= max(B + {icd.SHOULDER:g} shoulder, cap "
               f"screw depth + 3, 12) = {_g(rule)}; the ICD's)", "Housing", "Side wall", lo=min(rule, float(cav["wall"])))
    END = S.p("END_WALL", float(cav["end_wall"]), "end wall thickness, mm (the ICD's)", "Housing", "End wall", lo=4)
    FLOOR = S.p("FLOOR", float(cav["floor"]), "floor thickness under the sump, mm (the ICD's)", "Housing", "Floor",
                lo=4)
    mn = (-(LENGTH / 2) + END, -(WIDTH / 2) + WALL, -(HEIGHT / 2) + FLOOR)
    mx = (LENGTH / 2 - END, WIDTH / 2 - WALL, HEIGHT / 2)
    if any(abs(a.val - float(b)) > 1e-6 for a, b in zip((*mn, *mx), (*cav["min"], *cav["max"]), strict=True)):
        mn = tuple(V.of(float(v)) for v in cav["min"])  # type: ignore[assignment]
        mx = tuple(V.of(float(v)) for v in cav["max"])  # type: ignore[assignment]
    ctx["pockets"].append(({"name": "Gear cavity and sump", "min": mn, "max": mx},
                           "the gears run here; the floor below is the sump; open at the top under the cover"))
    ctx["lines"].insert(0, f"gear cavity X {_g(cav['min'][0])} to {_g(cav['max'][0])}, Y {_g(cav['min'][1])} to "
                           f"{_g(cav['max'][1])}, Z {_g(cav['min'][2])} to the top (open under the cover); side walls "
                           f"{_g(cav['wall'])}, end walls {_g(cav['end_wall'])}, floor {_g(cav['floor'])}")
    ctx["known"] |= {float(cav["wall"]), float(cav["end_wall"]), float(cav["floor"])}
    ctx["allowed"] = {"a flange", "a hole", "a thread"}
    # cap pads: the outer wall faces are relieved round raised pads under the caps (flat, square to the bores)
    with_caps = [s for s in seat_axes if s["ax"] == "y" and s["k"] in ctx["cap_od"]]
    if with_caps:
        DEP = S.p("PAD_RELIEF", PAD_RELIEF, "outer wall faces relieved round the cap pads, mm", "Cap pads",
                  "Pad relief depth", lo=0.5, hi=5)
        RIMP = S.p("PAD_RIM", RIM, "band left at full face round the relieved area, mm", "Cap pads", "Pad rim",
                   lo=2, hi=40)
        keeps = []
        for s in with_caps:
            pd = S.p(f"PAD_{s['k']}_D", ctx["cap_od"][s["k"]] + 2 * PAD_MARGIN,
                     f"cap pad Ø round seat {s['k']}, mm (cap OD + 2 × {PAD_MARGIN:g})", "Cap pads", f"Pad {s['k']} Ø")
            keeps.append({"ax": "y", "c": (s["U"], s["V"]), "d": pd})
        for sgn in (1, -1):
            y0, y1 = (WIDTH / 2 - DEP, WIDTH / 2) if sgn > 0 else (-(WIDTH / 2), -(WIDTH / 2) + DEP)
            ctx["pockets"].append(({"_opt": "Cap pads", "name": f"Cap pads ({'+' if sgn > 0 else '-'}Y wall)",
                                    "min": (-(LENGTH / 2) + RIMP, y0, -(HEIGHT / 2) + RIMP),
                                    "max": (LENGTH / 2 - RIMP, y1, HEIGHT / 2 - RIMP), "keep": keeps},
                                   "the face round the pads is relieved; each cap seats on its pad"))
        ctx["optional"].append("Cap pads")
        notes.append(f"Cap pads: the outer wall faces are relieved {_g(PAD_RELIEF)} mm round raised pads "
                     f"{_g(PAD_MARGIN)} mm larger than each cap, so the caps seat on machined pads.")
    # mounting feet: the underside relieved between two feet, four tapped holes 1.5 d from the edges
    m = mount_size(L)
    e = FOOT_EDGE * m
    FL = S.p("FOOT_LENGTH", max(3.0 * m, 20.0), f"each mounting foot along X, mm (>= 2 × 1.5 d for M{m})", "Feet",
             "Foot length", lo=2 * e)
    FR = S.p("FOOT_RELIEF", FOOT_RELIEF, "underside relieved between the feet, mm", "Feet", "Foot relief", lo=0.5,
             hi=5)
    FD = S.p("FOOT_TAP_D", tap_drill(m), f"foot hole tap drill Ø, mm (M{m}, ISO 2306)", "Feet", "Foot tap drill")
    FH = S.p("FOOT_TAP_DEPTH", 2.0 * m, f"foot hole depth, mm (2 d for M{m} in a casting)", "Feet", "Foot hole depth")
    FE = S.p("FOOT_EDGE", e, f"foot hole centre to the edges, mm (1.5 d for M{m})", "Feet", "Foot hole edge distance")
    ctx["pockets"].append(({"_opt": "Mounting feet", "name": "Mounting feet", "min": (-(LENGTH / 2) + FL, -(WIDTH / 2), -(HEIGHT / 2)),
                            "max": (LENGTH / 2 - FL, WIDTH / 2, -(HEIGHT / 2) + FR)},
                           "the underside between the two feet is relieved, so the housing stands on its feet"))
    for sx in (1, -1):
        for sy in (1, -1):
            ctx["cuts"].append(({"_opt": "Mounting feet", "name": f"Foot holes M{m}", "ax": "z",
                                 "c": (LENGTH / 2 - FE if sx > 0 else -(LENGTH / 2) + FE,
                                       WIDTH / 2 - FE if sy > 0 else -(WIDTH / 2) + FE),
                                 "d": FD, "span": (-(HEIGHT / 2), -(HEIGHT / 2) + FH),
                                 "thread": f"M{m}x{_pitch(m):g}"}, "tapped from below, for the foundation bolts"))
    ctx["optional"].append("Mounting feet")
    ctx["m_extra"] = {m}
    notes.append(f"Mounting feet: two feet {_g(FL.val)} mm long at the ends (the underside between them relieved "
                 f"{_g(FOOT_RELIEF)} mm), four M{m} tapped holes {_g(2 * m)} deep, {_g(e)} mm (1.5 d) from the edges.")
    n_seats = len(seat_axes)
    D_txt = " / ".join(sorted({cx.byif[s["if"]]["data"]["designation"] for s in seat_axes}))
    cd = ""
    ys = [s for s in seat_axes if s["ax"] == "y"]
    if len(ys) >= 2:
        cd = f" at {_g(abs(ys[1]['c'][0] - ys[0]['c'][0]))} centre distance"
    n_cap = sum(1 for c, _w in ctx["cuts"] if c["name"].startswith("Cap screw"))
    ctx["summary"] = (f"gearbox housing {_g(L)} × {_g(W)} × {_g(H)}: {n_seats} bearing bores ({D_txt}){cd}, walls "
                      f"{_g(cav['wall'])}, {n_cap} cap screw holes, cover joint and dowels, cap pads, feet with 4 × M{m}")


def _cover_extras(cx: Ctx, ctx: dict[str, Any]) -> None:
    """Shelled from below over the housing's cavity, leaving the roof and the walls the bolts pass through."""
    S, EXT, notes = ctx["S"], ctx["EXT"], ctx["notes"]
    HEIGHT = EXT["z"]
    ctx["allowed"] = {"a flange", "a hole", "a thread"}
    hc = _host_cavity(cx.doc, cx.item)
    if hc is None:
        return
    host, cav = hc
    me = cx.it
    if me.get("rot") or host.get("rot") or len(me.get("copies") or []) != 1:
        return
    off = [float(host["copies"][0][k]) - float(me["copies"][0][k]) for k in range(3)]
    lo_x, hi_x = float(cav["min"][0]) + off[0], float(cav["max"][0]) + off[0]
    lo_y, hi_y = float(cav["min"][1]) + off[1], float(cav["max"][1]) + off[1]
    roof = float(max(8.0, round(0.15 * ctx["H"])))
    if roof >= ctx["H"] - 2:
        return
    ROOF = S.p("ROOF", roof, "top thickness over the hollow, mm (a design choice: max(8, 0.15 H))", "Cover", "Roof",
               lo=3)
    if abs(lo_x + hi_x) < 1e-6 and abs(lo_y + hi_y) < 1e-6:
        PL = S.p("HOLLOW_LENGTH", hi_x - lo_x, "hollow under the cover along X, mm (the housing's cavity)", "Cover",
                 "Hollow length")
        PW = S.p("HOLLOW_WIDTH", hi_y - lo_y, "hollow under the cover along Y, mm (the housing's cavity)", "Cover",
                 "Hollow width")
        mn: tuple[Any, ...] = (-(PL / 2), -(PW / 2), -(HEIGHT / 2))
        mx: tuple[Any, ...] = (PL / 2, PW / 2, HEIGHT / 2 - ROOF)
    else:
        mn = (V.of(lo_x), V.of(lo_y), -(HEIGHT / 2))
        mx = (V.of(hi_x), V.of(hi_y), HEIGHT / 2 - ROOF)
    ctx["pockets"].append(({"_opt": "Hollow", "name": "Hollow over the gear cavity", "min": mn, "max": mx},
                           "the cover is shelled from below over the housing's cavity"))
    ctx["optional"].append("Hollow")
    notes.append(f"Hollow: shelled from below over the housing's cavity ({_g(hi_x - lo_x)} × {_g(hi_y - lo_y)}), "
                 f"roof {_g(roof)} mm; the bolt holes stay in the walls.")
    n_dowel = sum(1 for c, _w in ctx["cuts"] if c["name"].startswith("Dowel"))
    ctx["summary"] = (f"housing cover {_g(ctx['L'])} × {_g(ctx['W'])} × {_g(ctx['H'])}: "
                      f"{sum(1 for c, _w in ctx['cuts'] if not c['name'].startswith('Dowel'))} bolt holes, "
                      + (f"{n_dowel} dowel holes, " if n_dowel else "") + "shelled over the cavity")


def _plate_extras(cx: Ctx, ctx: dict[str, Any]) -> None:
    """Corner holes the brief asks for (1.5 d from the edges) and the edge-distance rule on every hole."""
    S, EXT, notes = ctx["S"], ctx["EXT"], ctx["notes"]
    LENGTH, WIDTH = EXT["x"], EXT["y"]
    L, W = ctx["L"], ctx["W"]
    ctx["allowed"] = {"a hole"} | ({"a thread"} if any(c.get("thread") for c, _w in ctx["cuts"]) else set())
    cav = cx.it.get("cavity")
    if cav:
        mn = tuple(V.of(float(v)) for v in cav["min"])
        mx = tuple(V.of(float(v)) for v in cav["max"])
        ctx["pockets"].append(({"name": "Slot", "min": mn, "max": mx}, str(cav.get("note") or "the ICD's opening")))
        ctx["lines"].insert(0, f"opening X {_g(cav['min'][0])} to {_g(cav['max'][0])}, Y {_g(cav['min'][1])} to "
                               f"{_g(cav['max'][1])}, Z {_g(cav['min'][2])} to {_g(cav['max'][2])} (the ICD's)")
        ctx["known"] |= {_r(float(cav["max"][k]) - float(cav["min"][k])) for k in range(3)}
    m = _CORNER.search(cx.desc or "")
    if m:
        n = 4 if m.group(1).lower() in ("four", "4") else 2
        d = float(m.group(2))
        e = FOOT_EDGE * d
        CD = S.p("CORNER_HOLE_D", d, "corner hole Ø, mm (the brief's)", "Corner holes", "Corner hole Ø")
        CE = S.p("CORNER_EDGE", e, "corner hole centre to the edges, mm (1.5 d)", "Corner holes", "Corner edge distance")
        corners = [(1, 1), (-1, -1)] if n == 2 else [(1, 1), (-1, 1), (-1, -1), (1, -1)]
        for sx, sy in corners:
            ctx["cuts"].append(({"_opt": "Corner holes", "name": "Corner holes", "ax": "z",
                                 "c": (LENGTH / 2 - CE if sx > 0 else -(LENGTH / 2) + CE,
                                       WIDTH / 2 - CE if sy > 0 else -(WIDTH / 2) + CE), "d": CD, "span": None},
                                f"the brief's corner hole, 1.5 d = {_g(e)} from both edges"))
        ctx["optional"].append("Corner holes")
        ctx["known"] |= {d}
        ctx["corner"] = m.group(0)
        notes.append(f"Corner holes: {n} × Ø{_g(d)} through, {_g(e)} mm (1.5 d) from both edges (the brief's).")
    short = []
    for c, _w in ctx["cuts"]:
        if c["ax"] != "z" or c["name"] == "Corner holes":
            continue
        x, y = c["c"][0].val if isinstance(c["c"][0], V) else c["c"][0], c["c"][1].val if isinstance(c["c"][1], V) \
            else c["c"][1]
        d = c["d"].val if isinstance(c["d"], V) else float(c["d"])
        edge = min(L / 2 - abs(x), W / 2 - abs(y))
        if edge < FOOT_EDGE * d - 1e-6:
            short.append(f"Ø{_g(d)} at ({_g(x)}, {_g(y)}) is {_g(edge)} from the edge ({_g(edge / d)} d)")
    if short:
        notes.append("Edge distance below 1.5 d (the ICD places these holes): " + "; ".join(sorted(set(short))) + ".")
        ctx["edge_short"] = short


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def _imports(uses_math: bool) -> list[str]:
    return [*(["import math\n"] if uses_math else []), "from build123d import *\n", "from aicad import fw, fw_std\n"]


def block_script(spec: dict[str, Any], name: str, material: str, icd_version: int) -> str:
    what = {"housing": "gearbox housing (base)", "cover": "housing cover", "plate": "machined block"}[spec["kind"]]
    S: Script = spec["S"]
    pockets = [(_clean(p), w) for p, w in spec["pockets"]]
    cuts = [(_clean(c), w) for c, w in spec["cuts"]]
    body = "\n".join([*_rows("pockets", pockets), *_rows("cuts", cuts)])
    out = [header(name, what, icd_version, spec["lines"], spec["notes"]), *_imports("math." in body),
           f'NAME = "{name}"', f'MATERIAL = "{material}"', "", *S.block(), ""]
    if pockets:
        out += ["# pockets: (min corner, max corner) in the part frame; pads in a pocket stay at full height",
                *_rows("pockets", pockets), ""]
    else:
        out += ["pockets = []", ""]
    out += ["# cuts: axis, position across it (X, Y for Z; X, Z for Y; Y, Z for X), Ø, span along it (None: through)",
            *_rows("cuts", cuts), "",
            'part, info = fw_std.machined(("box", LENGTH, WIDTH, HEIGHT), pockets=pockets, cuts=cuts, name=NAME)',
            "",
            "result = part",
            "# hand volume: the box less each pocket and each cut over the material it passes (fw_std.machined_volume)",
            'EXPECTED = {"bbox": info["bbox"], "volume": info["volume"], "solids": 1}', ""]
    return "\n".join(out)


# ============================================================================ what the brief asks beyond the generator
_KIND_RX = {"housing": re.compile(r"housing|casing|\bcase\b|gear ?box|\bbase\b", re.IGNORECASE),
            "cover": re.compile(r"\bcover|\blid\b", re.IGNORECASE),
            "cap": re.compile(r"\bcaps?\b", re.IGNORECASE),
            "plate": re.compile(r"\bplates?\b|\bblocks?\b|\bbase\b|\bcarriage|\bmount", re.IGNORECASE),
            "bracket": re.compile(r"\bbrackets?\b", re.IGNORECASE),
            "pulley": re.compile(r"\bpulleys?\b|\bsprockets?\b|\bsheaves?\b", re.IGNORECASE),
            "coupling": re.compile(r"\bcouplings?\b", re.IGNORECASE),
            "collar": re.compile(r"\bcollars?\b", re.IGNORECASE),
            "hub": re.compile(r"\bhubs?\b|\btubes?\b|\bdrums?\b|\bwheels?\b|\bflanges?\b", re.IGNORECASE)}
_HOLE_CLAUSE = re.compile(r"\bholes?\b|\bbores?\b", re.IGNORECASE)
_THREAD_M = re.compile(r"(?<![\w.])M(\d{1,2})(?:\s*[x×]\s*\d+(?:\.\d+)?)?\b")


def program_sentences(brief: str, kind: str) -> str:
    rx = _KIND_RX.get(kind)
    if rx is None:
        return ""
    return " ".join(s for s in re.split(r"(?<=[.;!?])\s+|\n+", brief) if rx.search(s))


def _clauses(text: str) -> list[str]:
    return [c for c in re.split(r"[,;:.]\s+|\s+and\s+|\s+with\s+|\(|\)", text or "") if c.strip()]


def interface_numbers(desc: str, hole_ds: set[float], m_sizes: set[int]) -> set[float]:
    """The plan's own statements of an interface the approved ICD now fixes ("two Ø6.6 holes 40 mm apart for the
    bracket bolts", "4 x M6 holes"): a clause about holes that names one of the ICD's hole Ø or fastener sizes. The
    ICD supersedes it (as it supersedes the planned envelope), so its numbers are not extra requirements."""
    from aicad.office import gage

    out: set[float] = set()
    for cl in _clauses(desc):
        if not _HOLE_CLAUSE.search(cl):
            continue
        ds = {v for lab, v in gage.brief_dimensions(cl) if lab.startswith("Ø")}
        ms = {int(m) for m in _THREAD_M.findall(cl)}
        if (ds & {round(d, 4) for d in hole_ds}) or (ms & m_sizes):
            out |= {v for _lab, v in gage.brief_dimensions(cl)}
            out |= {float(x) for x in re.findall(r"(?<![\w.Ø])(\d+(?:\.\d+)?)\s*(?:mm\s*)?apart", cl)}
    return out


_FASTENER_AFTER = re.compile(r"\s*(?:head\s*|socket\s*|flange\s*)?(?:bolts?|nuts?|screws?|keys?|heads?|sockets?|"
                             r"washers?|cap screws?)\b", re.IGNORECASE)


def _exempt(what: str, m: re.Match[str], src: str, allowed: set[str], m_ok: set[int], threaded: bool) -> bool:
    """A match of an extras pattern that is not an extra: an M size of the ICD's own fasteners, a thread word on a
    part whose ICD holes are tapped, "hex" naming a bolt or nut, or a feature this generator makes."""
    word = m.group(0)
    if what == "a thread":
        mm = re.fullmatch(r"M(\d{1,2})(?:\s*[x×]\s*\d+(?:\.\d+)?)?", word.strip())
        if mm:
            return int(mm.group(1)) in m_ok or bool(_FASTENER_AFTER.match(src[m.end():]))
        return threaded
    if what == "a hex or square":
        return bool(_FASTENER_AFTER.match(src[m.end():]))
    return what in allowed


def extras(kind: str, spec: dict[str, Any], name: str, desc: str, program: str,
           allow_words: tuple[str, ...] = ()) -> list[str]:
    """What the brief asks for beyond what this generator builds (each sends the part to the design agent)."""
    from aicad.office import direct, gage

    text = f"{name}. {desc}"
    allowed = set(spec.get("allowed") or ())
    out: list[str] = []
    m_ok = set(spec.get("m_sizes") or ())
    threaded = any(c.get("thread") for c, _w in spec.get("cuts") or [])
    for rx, what, in_program in direct._EXTRAS:
        srcs = [text] + ([program] if in_program and program else [])
        for src in srcs:
            if any(not _exempt(what, m, src, allowed, m_ok, threaded) for m in rx.finditer(src)):
                out.append(f"the brief asks for {what}")
                break
    for m in _SHAPE_WORDS.finditer(desc or ""):
        w = m.group(1).lower()
        if any(w.startswith(a) for a in allow_words):
            continue
        out.append(f"the brief asks for a shape the interfaces don't give ({w})")
        break
    if direct._KEYWORD.search(text) and not spec.get("keyways"):
        out.append("the brief asks for a key the interfaces don't size")
    hole_ds = {float(c["d"].val if isinstance(c["d"], V) else c["d"]) for c, _w in spec.get("cuts") or []}
    known = set(spec["known"]) | direct._envelope_numbers(desc) | interface_numbers(desc, hole_ds, m_ok)
    known |= set(spec.get("known_extra") or ())
    for label, v in gage.brief_dimensions(desc):
        if not any(abs(v - k) < 1e-6 for k in known):
            out.append(f"the brief gives a size the interfaces don't explain ({label})")
    seen: set[str] = set()
    return [x for x in out if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]


DEFAULT_MATERIAL = {"housing": "Aluminium 6061-T6", "cover": "Aluminium 6061-T6", "cap": "Steel 1018 (low carbon)",
                    "plate": "Steel 1018 (low carbon)", "bracket": "Steel 1018 (low carbon)",
                    "pulley": "Aluminium 6061-T6", "coupling": "Steel 1045 (medium carbon)",
                    "collar": "Steel 1045 (medium carbon)", "hub": "Steel 1045 (medium carbon)"}
ALLOW_WORDS = {"housing": ("chamfer",), "cover": (), "plate": (), "bracket": ("fillet", "radius", "rounded"),
               "cap": ("spigot", "chamfer", "recess"), "pulley": ("groove", "web", "chamfer", "step"),
               "coupling": ("chamfer", "step"), "collar": ("chamfer",), "hub": ("chamfer",)}


def plan_part(kind: str, doc: dict[str, Any], item: str, name: str, desc: str) -> dict[str, Any]:
    """The generator's spec and script for one part: ``{"script", "summary", "n_features", "extras", ...}``.
    Raises ``Undetermined`` when the interfaces don't fix it."""
    from aicad.office import direct

    cx = Ctx(doc, item, name, desc)
    builder = {"housing": block_spec, "cover": block_spec, "plate": block_spec}.get(kind)
    other = {"cap": cap_spec, "bracket": bracket_spec, "pulley": pulley_spec, "coupling": coupling_spec, "hub": hub_spec,
             "collar": collar_spec}.get(kind)
    if builder is not None:
        spec = builder(kind, cx)
    elif other is not None:
        spec = other(cx)
    else:
        raise Undetermined("this kind of part needs the designer")
    material = direct._material(desc) or _graph_material(cx) or DEFAULT_MATERIAL[kind]
    writer = {"housing": block_script, "cover": block_script, "plate": block_script, "cap": cap_script,
              "bracket": bracket_script, "pulley": pulley_script, "coupling": coupling_script, "hub": coupling_script,
              "collar": collar_script}[kind]
    script = writer(spec, name, material, cx.icd_version)
    ex = extras(kind, spec, name, desc, program_sentences(str(doc.get("brief") or ""), kind), ALLOW_WORDS.get(kind, ()))
    return {"kind": kind, "script": script, "summary": spec["summary"], "material": material,
            "n_features": spec["n_features"], "extras": ex, "notes": spec["notes"], "generator": VERSION}


def _graph_material(cx: Ctx) -> str | None:
    from aicad.office import direct

    g = cx.graph or {}
    for c in (cx.doc.get("plan") or {}).get("graph", {}).get("data", {}).get("components", []) or []:
        if c.get("id") == g.get("id") and c.get("material"):
            return direct._material(str(c["material"]))
    return None


# ============================================================================ bearing caps (open and blind)
_SEAL_TXT = re.compile(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(?:mm\s*)?(?:\w+[\s-]+){0,2}"
                       r"seal", re.IGNORECASE)
_SEALY = re.compile(r"\bseal(?:ed|s|ing)?\b|\blip\b", re.IGNORECASE)
_SPIGOT = re.compile(r"\bspigot\b", re.IGNORECASE)


def _shaft_through(cx: Ctx, f: dict[str, Any]) -> float | None:
    """The shaft Ø passing through an open cap: the bearing seat on the same host and axis gives it."""
    d = f["data"]
    for g in cx.ifs:
        if g["kind"] != "bearing_seat" or g["a"]["item"] != f["a"]["item"]:
            continue
        gd = g["data"]
        if icd.ax_of(gd) == icd.ax_of(d) and all(abs(float(a) - float(b)) < 1e-6
                                                for a, b in zip(gd["axis"], d["centre"], strict=True)):
            return float(gd.get("shaft_d") or gd["d"])
    return None


def cap_spec(cx: Ctx) -> dict[str, Any]:
    it = cx.it
    OD, H = float(it["size"][0]), float(it["size"][2])
    f = next(g for g in cx.ifs if g["kind"] == "hole_pattern" and g["b"]["item"] == cx.item and g["data"].get("cap"))
    d = f["data"]
    style = str(d["cap"])
    gstyle = ((cx.graph or {}).get("params") or {}).get("style")
    S = Script()
    lines: list[str] = []
    notes: list[str] = []
    known: set[float] = {OD, H, float(d["pcd"]), float(d["d"]), float(d["seat_D"])}
    face = next((x for x in cx.feats if x["type"] == "face"), None)
    holes = [x for x in cx.feats if x["type"] == "hole"]
    relief = [x for x in cx.feats if x["type"] == "seat"]
    other = [x for x in cx.feats if x["type"] not in ("face", "hole", "seat")]
    if other:
        raise Undetermined(f"{other[0]['label']} is not a feature of a bearing cap this can build")
    if face is None or abs(abs(float(face["z"])) - H / 2) > 0.01:
        raise Undetermined("the cap's mounting face is not one of its faces")
    if any(x.get("z0") is not None or x.get("ax") for x in holes):
        raise Undetermined("the cap's screw holes don't run through it")
    mz = 1 if float(face["n"]) > 0 else -1  # the mounting face (towards the housing) is at mz × H / 2
    S.p("OD", OD, "flange outside Ø, mm (PCD + the washer OD, the ICD's)", "Cap", "Flange Ø")
    T = S.p("THICKNESS", H, "flange thickness, mm (ICD envelope)", "Cap", "Thickness", lo=4)
    HD = S.p("HOLE_D", float(d["d"]), f"clearance hole Ø, mm (M{d['fastener_size']}, ISO 273)", "Holes", "Hole Ø")
    pts = [(float(x["c"][0]), float(x["c"][1])) for x in holes]
    P = _pos_exprs(S, pts, "HOLE", "Holes", "cap screw holes", "z", (V.of(0.0), V.of(0.0)), float(d["pcd"]))
    cuts: list[tuple[dict[str, Any], str]] = []
    for x, p in zip(holes, P, strict=True):
        cuts.append(({"name": f"Cap screw holes M{d['fastener_size']}", "ax": "z", "c": p, "d": HD, "span": None},
                     f"{x['if']} {x['label']}"))
    lines.append(f"{f['id']}  {len(holes)} holes Ø{_g(d['d'])} on PCD {_g(d['pcd'])} for the M{d['fastener_size']} cap "
                 f"screws into the {f['a']['name']}; mounting face at Z {_g(face['z'])}")
    for x in relief:
        RD = S.p("RELIEF_D", float(x["d"]), "relief Ø over the turning inner ring, mm ((d + D) / 2, the ICD's)",
                 "Relief", "Relief Ø")
        RH = S.p("RELIEF_DEPTH", abs(float(x["z1"]) - float(x["z0"])), "relief depth, mm (the ICD's)", "Relief",
                 "Relief depth", lo=0.2, hi=5)
        span = (T / 2 - RH, T / 2) if mz > 0 else (-(T / 2), -(T / 2) + RH)
        cuts.append(({"name": "Relief over the inner ring", "ax": "z", "c": (0.0, 0.0), "d": RD, "span": span},
                     f"{x['if']} the cap bears on the outer ring only"))
        known |= {float(x["d"]), abs(float(x["z1"]) - float(x["z0"]))}
        lines.append(f"{x['if']}  {x['label']}")
    text = f"{cx.name}. {cx.desc}"
    seal_txt: tuple[float, float, float] | None = None
    m = _SEAL_TXT.search(cx.desc or "")
    if m:
        seal_txt = (float(m.group(1)), float(m.group(2)), float(m.group(3)))
    if style == "open":
        bore = float(it.get("bore") or 0)
        if bore <= 0:
            raise Undetermined("the open cap has no bore in the interfaces")
        shaft = _shaft_through(cx, f) or bore - 2.0
        BO = S.p("BORE", bore, f"shaft passage Ø, mm (the Ø{_g(shaft)} shaft + 2, the ICD's)", "Bore", "Bore Ø")
        cuts.append(({"name": "Shaft passage", "ax": "z", "c": (0.0, 0.0), "d": BO, "span": None},
                     f"the Ø{_g(shaft)} shaft leaves the housing through it"))
        known |= {bore, shaft}
        lines.append(f"open cap: the Ø{_g(shaft)} shaft passes through a Ø{_g(bore)} bore")
        seal = None
        src = ""
        if seal_txt and abs(seal_txt[0] - shaft) < 1e-6:
            seal, src = (seal_txt[1], seal_txt[2]), "the plan's"
        else:
            gs = next((c for c in graph_kinds(cx.doc) if c["kind"] == "seal"
                       and abs(float(c["params"].get("d") or 0) - shaft) < 1e-6), None)
            if gs and gs["params"].get("D") and gs["params"].get("B"):
                seal, src = (float(gs["params"]["D"]), float(gs["params"]["B"])), "the design's"
            elif seal_for(shaft):
                seal, src = seal_for(shaft), "DIN 3760"
        if seal_txt and seal and abs(seal_txt[0] - shaft) > 1e-6:
            notes.append(f"Seal: the plan names a {_g(seal_txt[0])} × {_g(seal_txt[1])} × {_g(seal_txt[2])} seal (for a "
                         f"Ø{_g(seal_txt[0])} shaft); the approved ICD passes Ø{_g(shaft)} here, so the recess is for "
                         f"{_g(shaft)} × {_g(seal[0])} × {_g(seal[1])} ({src}).")
        if seal_txt:
            known |= set(seal_txt)
        rd = max((float(x["d"]) for x in relief), default=0.0)
        rh = max((abs(float(x["z1"]) - float(x["z0"])) for x in relief), default=0.0)
        if seal and seal[0] > bore and seal[1] + rh <= H - 2.0:
            SD = S.p("SEAL_D", seal[0], f"lip seal recess Ø, mm ({_g(shaft)} × {_g(seal[0])} × {_g(seal[1])}, {src})",
                     "Seal", "Seal recess Ø")
            SW = S.p("SEAL_WIDTH", seal[1], "lip seal recess depth, mm (the seal's width)", "Seal", "Seal recess depth",
                     lo=2, hi=20)
            span = (-(T / 2), -(T / 2) + SW) if mz > 0 else (T / 2 - SW, T / 2)
            cuts.append(({"name": "Lip seal recess", "ax": "z", "c": (0.0, 0.0), "d": SD, "span": span},
                         "from the outer face; the seal runs on the shaft"))
            known |= {seal[0], seal[1]}
            if not any(n.startswith("Seal:") for n in notes):
                notes.append(f"Seal: a {_g(shaft)} × {_g(seal[0])} × {_g(seal[1])} lip seal recess from the outer face "
                             f"({SEALS_SOURCE if src == 'DIN 3760' else src + ' size for the shaft that passes'}).")
            _ = rd
        else:
            notes.append("Seal: no recess (no standard seal for this shaft Ø fits the cap); add one if the brief needs "
                         "it.")
            if _SEALY.search(text):
                raise Undetermined(f"no lip seal for a Ø{_g(shaft)} shaft fits this cap")
    else:
        lines.append("blind cap: closed (no bore)")
        if _SEALY.search(cx.desc or ""):
            raise Undetermined("the brief asks for a seal on a blind cap")
    if gstyle and gstyle != style:
        notes.append(f"Style: the design names an {gstyle} cap; the approved interfaces make it {style} (they decide).")
    if _SPIGOT.search(text):
        notes.append("Spigot: the ICD has the cap bear flat on the bearing's outer ring (with the relief over the inner "
                     "ring), so there is no spigot; a spigot would sit in the bore where the bearing is.")
    ch = 1.0 if OD >= 40 else 0.5
    CH = S.p("CHAMFER", ch, "45° chamfer on the outer face's rim, mm", "Finish", "Rim chamfer", lo=0.0, hi=3)
    chamfers = [({"z": -(T / 2) if mz > 0 else T / 2, "c": CH}, "the outer face's rim")]
    info = fw_std.machined_volume(("disc", OD, H), [], [_num(c) for c, _w in cuts], [_num(c) for c, _w in chamfers])
    if info["problems"]:
        raise Undetermined("the cap's features overlap: " + info["problems"][0])
    lines.append(f"{face['if']}  {face['label']} at Z {_g(face['z'])}")
    summary = (f"{style} bearing cap Ø{_g(OD)} × {_g(H)}: {len(holes)} × Ø{_g(d['d'])} on PCD {_g(d['pcd'])}"
               + (", relief" if relief else "") + (", shaft bore and lip seal recess" if style == "open" and any(
                   c["name"] == "Lip seal recess" for c, _w in cuts) else ", shaft bore" if style == "open" else ""))
    return {"kind": "cap", "S": S, "cuts": cuts, "chamfers": chamfers, "lines": lines, "notes": notes, "known": known,
            "m_sizes": {int(d["fastener_size"])}, "n_features": len(holes) + len(relief) + 1, "summary": summary,
            "allowed": {"a hole", "a thread", "a flange", "a web or recess", "an undercut"}
            | ({"a seal or oil feature"} if style == "open" else set()), "style": style}


def cap_script(spec: dict[str, Any], name: str, material: str, icd_version: int) -> str:
    S: Script = spec["S"]
    cuts = [(_clean(c), w) for c, w in spec["cuts"]]
    rows = "\n".join(_rows("cuts", cuts))
    out = [header(name, f"{spec['style']} bearing cap", icd_version, spec["lines"], spec["notes"]),
           *_imports("math." in rows), f'NAME = "{name}"', f'MATERIAL = "{material}"', "", *S.block(), "",
           "# coaxial and axial cuts (Z is the cap's axis; the mounting face is the one the ICD names)",
           *_rows("cuts", cuts), "", *_rows("chamfers", spec["chamfers"]), "",
           'part, info = fw_std.machined(("disc", OD, THICKNESS), cuts=cuts, chamfers=chamfers, name=NAME)', "",
           "result = part",
           "# hand volume: the disc less each cut over its length and the rim chamfer (Pappus)",
           'EXPECTED = {"bbox": info["bbox"], "volume": info["volume"], "solids": 1}', ""]
    return "\n".join(out)


# ============================================================================ brackets (L with gussets)
_FOOT_T = re.compile(r"\bfoot\b[^.;]*?\d+(?:\.\d+)?\s*[x×]\s*\d+(?:\.\d+)?\s*[x×]\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_UP_T = re.compile(r"\b(?:upright|web|leg)\b[^.;]*?(\d+(?:\.\d+)?)\s*(?:mm\s*)?thick", re.IGNORECASE)
_UP_H = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mm\s*)?(?:high|tall)\b", re.IGNORECASE)
_UP_HOLE = re.compile(r"[ØⲐ⌀]\s*(\d+(?:\.\d+)?)\s*(?:mm\s*)?hole\s+(\d+(?:\.\d+)?)\s*(?:mm\s*)?up\b", re.IGNORECASE)


def bracket_spec(cx: Ctx) -> dict[str, Any]:
    it = cx.it
    L, W, H = (float(v) for v in it["size"])
    desc = cx.desc or ""
    holes = [x for x in cx.feats if x["type"] == "hole"]
    faces = [x for x in cx.feats if x["type"] == "face"]
    if any(x["type"] not in ("hole", "face") for x in cx.feats):
        bad = next(x for x in cx.feats if x["type"] not in ("hole", "face"))
        raise Undetermined(f"{bad['label']} is not a feature of a bracket this can build")
    if any(x.get("ax") or x.get("z0") is not None for x in holes):
        raise Undetermined("a bracket is built here with its foot holes only (the ICD puts holes elsewhere)")
    if any(x.get("ax") or not (abs(float(x["z"]) + H / 2) < 0.01 and int(x["n"]) < 0) for x in faces):
        raise Undetermined("a bracket is built here when it mounts by its foot (the ICD names another face)")
    prog = program_sentences(str(cx.doc.get("brief") or ""), "bracket")
    m = _FOOT_T.search(desc) or _FOOT_T.search(prog)
    tf = float(m.group(1)) if m else None
    m = _UP_T.search(desc) or _UP_T.search(prog)
    tu = float(m.group(1)) if m else None
    rule = float(max(5, round(0.12 * min(L, W))))
    notes: list[str] = []
    if tf is None or tu is None:
        notes.append(f"Thickness: {'foot' if tf is None else 'upright'}{' and upright' if tf is None and tu is None else ''}"
                     f" {_g(rule)} mm (a design choice: 0.12 × the smaller side, at least 5).")
    tf, tu = tf or rule, tu or rule
    m = _UP_H.search(desc) or _UP_H.search(prog)
    known: set[float] = {L, W, H, tf, tu}
    if m:
        h = float(m.group(1))
        known.add(h)
        if abs(h + tf - H) > 0.01 and abs(h - H) > 0.01:
            notes.append(f"Height: the brief's {_g(h)} mm upright doesn't match the {_g(H)} envelope; the envelope "
                         "(ICD) decides.")
    if tf >= H - 2 or tu >= min(L, W) / 2:
        raise Undetermined("the foot or upright is too thick for the bracket's envelope")
    fsize = next((int(f["data"]["fastener_size"]) for f in cx.ifs if f["kind"] == "hole_pattern"
                  and cx.item in (f["a"]["item"], f["b"]["item"]) and f["data"].get("fastener_size")), None)
    washer = float(icd.WASHER_OD.get(fsize, 0) if fsize else 0) or max((float(x["d"]) * 2 for x in holes), default=0)
    pts = [(float(x["c"][0]), float(x["c"][1])) for x in holes]
    # the upright on an edge that leaves the foot holes room for their washers (the longer edges first)
    edges = ["+Y", "-Y", "+X", "-X"] if L >= W else ["+X", "-X", "+Y", "-Y"]
    side = None
    need = washer / 2 + 0.5
    for e in edges:
        ax = 1 if e[1] == "Y" else 0
        sgn = 1 if e[0] == "+" else -1
        inner = sgn * ((W if ax else L) / 2 - tu)
        if all(sgn * (inner - p[ax]) >= need - 1e-9 for p in pts):
            side = e
            break
    if side is None:
        gap = min(((W if a else L) / 2 - tu - max(abs(p[a]) for p in pts)) for a in (0, 1)) if pts else 0.0
        raise Undetermined(f"the {_g(tu)} mm upright leaves no room for the M{fsize or '?'} washers of the ICD's hole "
                           f"pattern on any edge ({_g(gap)} mm from the holes to the upright, {_g(need)} needed)")
    S = Script()
    LENGTH = S.p("LENGTH", L, "mm along X (ICD envelope)", "Bracket", "Length", lo=10)
    WIDTH = S.p("WIDTH", W, "mm along Y (ICD envelope)", "Bracket", "Width", lo=10)
    HEIGHT = S.p("HEIGHT", H, "mm along Z (ICD envelope)", "Bracket", "Height", lo=10)
    FT = S.p("FOOT_T", tf, "foot thickness, mm" + (" (the brief's)" if _FOOT_T.search(desc + prog) else ""), "Bracket",
             "Foot thickness", lo=2)
    UT = S.p("UPRIGHT_T", tu, "upright thickness, mm" + (" (the brief's)" if _UP_T.search(desc + prog) else ""), "Bracket",
             "Upright thickness", lo=2)
    ax = 1 if side[1] == "Y" else 0
    sgn = 1 if side[0] == "+" else -1
    if ax == 1:
        mn: tuple[Any, ...] = (-(LENGTH / 2), -(WIDTH / 2) if sgn > 0 else -(WIDTH / 2) + UT, -(HEIGHT / 2) + FT)
        mx: tuple[Any, ...] = (LENGTH / 2, WIDTH / 2 - UT if sgn > 0 else WIDTH / 2, HEIGHT / 2)
    else:
        mn = (-(LENGTH / 2) if sgn > 0 else -(LENGTH / 2) + UT, -(WIDTH / 2), -(HEIGHT / 2) + FT)
        mx = (LENGTH / 2 - UT if sgn > 0 else LENGTH / 2, WIDTH / 2, HEIGHT / 2)
    pockets = [({"name": "L section", "min": mn, "max": mx}, f"leaves the foot and the upright on the {side} edge")]
    lines = [(f"foot {_g(L)} × {_g(W)} × {_g(tf)} on the bottom face (its mounting face), upright {_g(tu)} thick on the "
             f"{side} edge, {_g(H - tf)} above the foot")]
    cuts: list[tuple[dict[str, Any], str]] = []
    if holes:
        f = cx.byif[holes[0]["if"]]
        dia = float(holes[0]["d"])
        HD = S.p("HOLES_1_D", dia, f"foot hole Ø, mm (M{fsize}, ISO 273) for the {cx.other(f)}", "Holes", "Foot hole Ø")
        P = _pos_exprs(S, pts, "HOLES_1", "Holes", "foot holes", "z")
        for x, p in zip(holes, P, strict=True):
            cuts.append(({"name": "Foot holes", "ax": "z", "c": p, "d": HD, "span": None}, f"{x['if']} {x['label']}"))
        known.add(dia)
        lines.append(f"{f['id']}  {len(holes)} holes Ø{_g(dia)} through the foot for the {cx.other(f)}; the upright "
                     f"clears their washers (Ø{_g(washer)})")
    m = _UP_HOLE.search(desc) or _UP_HOLE.search(prog)
    if m:
        hd, hz = float(m.group(1)), float(m.group(2))
        UD = S.p("UPRIGHT_HOLE_D", hd, "hole through the upright, Ø mm (the brief's)", "Upright hole", "Upright hole Ø")
        UZ = S.p("UPRIGHT_HOLE_H", hz, "its centre above the underside, mm (the brief's)", "Upright hole",
                 "Upright hole height")
        cut_ax = "y" if ax == 1 else "x"
        cuts.append(({"name": "Upright hole", "ax": cut_ax, "c": (0.0, -(HEIGHT / 2) + UZ), "d": UD, "span": None},
                     "the brief's hole through the upright, centred along it"))
        known |= {hd, hz}
        notes.append(f"Upright hole: Ø{_g(hd)} through the upright, {_g(hz)} mm above the underside (the brief's), "
                     "centred along it.")
    run = (W if ax == 1 else L) - tu  # foot depth in front of the upright
    up = H - tf
    leg = float(round(min(0.6 * run, 0.6 * up), 1))
    span_len = L if ax == 1 else W
    gussets: list[dict[str, Any]] = []
    if leg >= 5:
        GL = S.p("GUSSET_LEG", leg, "gusset legs along the foot and up the upright, mm (0.6 × the shorter)", "Gussets",
                 "Gusset leg", lo=2)
        GT = S.p("GUSSET_T", tu, "gusset thickness, mm (the upright's)", "Gussets", "Gusset thickness", lo=2)
        ok = True
        inner = sgn * ((W if ax == 1 else L) / 2 - tu)
        for e in (1, -1):  # gussets at both ends of the upright, inside the corner; clear of every washer
            a0, a1 = sorted((e * (span_len / 2 - tu), e * span_len / 2))
            b0, b1 = sorted((inner, inner - sgn * leg))
            for p in pts:
                along, across = (p[0], p[1]) if ax == 1 else (p[1], p[0])
                if fw_std._disk_in_rect(along, across, washer / 2 + 0.5, (a0, a1, b0, b1)) != "out":
                    ok = False
            gussets.append({"end": e})
        if ok:
            notes.append(f"Gussets: two, {_g(leg)} mm legs, {_g(tu)} thick, at the ends of the upright.")
        else:
            gussets = []
            notes.append("Gussets: left out (they would cover the foot holes).")
    else:
        GL = GT = None
    info = fw_std.machined_volume(("box", L, W, H), [_num(p) for p, _w in pockets], [_num(c) for c, _w in cuts])
    if info["problems"]:
        raise Undetermined("the bracket's features overlap: " + info["problems"][0])
    for x in faces:
        lines.append(f"{x['if']}  {x['label']} at Z {_g(x['z'])}")
    gtxt = []
    for g in gussets:
        e = g["end"]
        if ax == 1:  # upright along X at a Y edge: gussets at the X ends, in the YZ plane
            corner = (LENGTH / 2 - GT / 2 if e > 0 else -(LENGTH / 2) + GT / 2,
                      WIDTH / 2 - UT if sgn > 0 else -(WIDTH / 2) + UT, -(HEIGHT / 2) + FT)
            la = (0.0, -GL if sgn > 0 else GL, 0.0)
        else:
            corner = (LENGTH / 2 - UT if sgn > 0 else -(LENGTH / 2) + UT,
                      WIDTH / 2 - GT / 2 if e > 0 else -(WIDTH / 2) + GT / 2, -(HEIGHT / 2) + FT)
            la = (-GL if sgn > 0 else GL, 0.0, 0.0)
        lb = (0.0, 0.0, GL)
        gtxt.append(f"part, v = fw.gusset(part, {_src(corner)}, {_src(la)}, {_src(lb)}, GUSSET_T, "
                    f'name="Gusset {"+" if e > 0 else "-"}{"X" if ax == 1 else "Y"}")')
        gtxt.append("volume += v")
    summary = (f"L bracket {_g(L)} × {_g(W)} × {_g(H)}: foot {_g(tf)}, upright {_g(tu)} on the {side} edge, "
               f"{len(holes)} foot holes" + (", upright hole" if m else "") + (f", {len(gussets)} gussets" if gussets
                                                                                else ""))
    vol = info["volume"] + len(gussets) * 0.5 * leg * leg * tu
    return {"kind": "bracket", "S": S, "pockets": pockets, "cuts": cuts, "gussets": gtxt, "lines": lines,
            "notes": notes, "known": known, "m_sizes": {fsize} if fsize else set(),
            "n_features": len(holes) + len(faces), "summary": summary, "allowed": {"a hole"}, "volume": vol}


def bracket_script(spec: dict[str, Any], name: str, material: str, icd_version: int) -> str:
    S: Script = spec["S"]
    cuts = [(_clean(c), w) for c, w in spec["cuts"]]
    rows = "\n".join(_rows("cuts", cuts))
    out = [header(name, "L bracket", icd_version, spec["lines"], spec["notes"]), *_imports("math." in rows),
           f'NAME = "{name}"', f'MATERIAL = "{material}"', "", *S.block(), "",
           "# the L section: the envelope box less the space in front of the upright, above the foot",
           *_rows("pockets", spec["pockets"]), "", *_rows("cuts", cuts), "",
           'part, info = fw_std.machined(("box", LENGTH, WIDTH, HEIGHT), pockets=pockets, cuts=cuts, name=NAME)',
           'volume = info["volume"]']
    if spec["gussets"]:
        out += ["# gussets in the inside corner (each adds legs² / 2 × thickness)", *spec["gussets"]]
    out += ["", "result = part", 'EXPECTED = {"bbox": info["bbox"], "volume": volume, "solids": 1}', ""]
    return "\n".join(out)


# ============================================================================ turned hubs: pulleys, sprockets, couplings
_TIMING = re.compile(r"\btiming\b|\btoothed\b|\bsynchronous\b|\bGT[23]\b|\bHTD\b|\b[358]M\b|\bT(?:2\.5|5|10)\b|\bXL\b",
                     re.IGNORECASE)
_VBELT = re.compile(r"\bv-?belts?\b|\bv-?grooves?\b|\bSP[ZABC]\b|\b[ABC]-section\b|\bpoly-?v\b", re.IGNORECASE)
_TEETH = re.compile(r"(\d+)\s*(?:teeth|tooth|t)\b", re.IGNORECASE)
_CHAIN = re.compile(r"\b(0[4-9]B|1[0-2]B)\b|\b(?:ANSI|#)\s*(25|35|40|50|60)\b", re.IGNORECASE)
_FLEX = re.compile(r"\b(jaw|spider|flexible|elastomer\w*|oldham|bellows|disc|grid|beam|helical|universal|"
                   r"cardan)\b", re.IGNORECASE)


def _hub_features(cx: Ctx, what: str) -> dict[str, Any]:
    """Bore(s), hub keyways and end faces of a turned hub (all along its axis)."""
    from aicad.office import direct

    H = float(cx.it["size"][2])
    bores, keys, faces = [], [], []
    for x in cx.feats:
        if x.get("ax"):
            raise Undetermined(f"{x['label']} is off the {what}'s axis")
        if x["type"] == "hole" and abs(float(x["c"][0])) < 1e-6 and abs(float(x["c"][1])) < 1e-6:
            bores.append(x)
        elif x["type"] == "keyway" and x.get("on") == "hub":
            f = cx.byif[x["if"]]
            keys.append({**x, "angle": direct._key_angle(cx.sk, f, cx.side(f)), "data": f["data"]})
        elif x["type"] == "face" and abs(abs(float(x["z"])) - H / 2) < 0.01 and int(x["n"]) * float(x["z"]) > 0:
            faces.append(x)
        else:
            raise Undetermined(f"{x['label']} is not a feature of a {what} this can build")
    return {"bores": bores, "keys": keys, "faces": faces}


def _keyway_rows(S: Script, keys: list[dict[str, Any]], bore_of: Any, H: float) -> tuple[list[str], set[float]]:
    out: list[str] = []
    known: set[float] = set()
    for n, k in enumerate(keys, start=1):
        sfx = "" if len(keys) == 1 else f"_{n}"
        b, t2 = float(k["b"]), float(k["depth"])
        z0, z1 = float(k["z0"]), float(k["z1"])
        KB = S.p(f"KEY{sfx}_B", b, f"hub keyway width, mm ({k['data'].get('standard') or 'DIN 6885'})", "Keyway",
                 "Keyway width", lo=1)
        KT = S.p(f"KEY{sfx}_T2", t2, "hub keyway depth above the bore, mm (t2)", "Keyway", "Keyway depth", lo=0.5)
        span = ("-WIDTH / 2", "WIDTH / 2") if abs(z0 + H / 2) < 0.01 and abs(z1 - H / 2) < 0.01 else (_f(z0), _f(z1))
        ang = "" if abs(k["angle"] - 90) < 1e-9 else f", angle={_g(k['angle'])}"
        out += [f"part, v = fw_std.hub_keyway(part, {bore_of(k).src}, {KB.src}, {KT.src}, {span[0]}, {span[1]}{ang})",
                "volume -= v"]
        known |= {b, t2, *(float(k["data"][x]) for x in ("h", "t1", "length") if k["data"].get(x) is not None)}
    return out, known


def pulley_spec(cx: Ctx) -> dict[str, Any]:
    it = cx.it
    OD, H = float(it["size"][0]), float(it["size"][2])
    text = f"{cx.name}. {cx.desc}"
    hf = _hub_features(cx, "pulley")
    if len(hf["bores"]) != 1 or hf["bores"][0].get("z0") is not None:
        raise Undetermined("the pulley has no single through bore in its interfaces")
    if _VBELT.search(text):
        raise Undetermined("a V-belt pulley needs its groove section (not built from the interface spec yet)")
    bore = float(hf["bores"][0]["d"])
    S = Script()
    notes: list[str] = []
    lines = [f"{hf['bores'][0]['if']}  bore Ø{_g(bore)} H7 through, on the shaft"]
    known: set[float] = {OD, H, bore}
    R = S.p("OD", OD, "outside Ø, mm (ICD envelope)", "Pulley", "Outside Ø")
    WID = S.p("WIDTH", H, "width along the axis, mm (ICD envelope)", "Pulley", "Width", lo=2)
    BO = S.p("BORE", bore, "bore Ø, mm (H7 on the shaft)", "Pulley", "Bore Ø", lo=1)
    t2 = max((float(k["depth"]) for k in hf["keys"]), default=0.0)
    hub = max(1.8 * bore, bore + 2 * (t2 + 4))
    sprocket = bool(re.search(r"\bsprockets?\b", text, re.IGNORECASE))
    timing = not sprocket and bool(_TIMING.search(text))
    tm = _TEETH.search(text)
    prof: list[tuple[V, V]]
    if sprocket or timing:
        if not tm:
            raise Undetermined(f"a {'sprocket' if sprocket else 'timing pulley'} needs its number of teeth")
        z = int(tm.group(1))
        known.add(float(z))
        if sprocket:
            cm = _CHAIN.search(text)
            if not cm:
                raise Undetermined("a sprocket needs its chain (ISO 606 08B, ANSI 40, ...)")
            code = (cm.group(1) or cm.group(2)).upper()
            p, b1 = CHAINS[code]
            pd = p / math.sin(math.pi / z)
            tw = round(0.93 * b1, 2)
            what = f"sprocket for {code} chain ({_g(p)} pitch), {z} teeth"
            notes.append(f"Teeth: not modelled; the sprocket is its pitch disc Ø{_g(round(pd, 3))} = p / sin(180° / z), "
                         f"{_g(tw)} wide (0.93 × the chain's inner width {_g(b1)}, ISO 606, verify).")
        else:
            belt = next((k for k in sorted(BELTS, key=len, reverse=True)
                         if re.search(r"(?<![\w.])" + r"\s*".join(map(re.escape, k.split())) + r"(?![\w.])", text,
                                   re.IGNORECASE)),
                        None)
            if belt is None:
                raise Undetermined("a timing pulley needs its belt profile (GT2, HTD 5M, T5, XL, ...)")
            p, _u = BELTS[belt]
            pd = z * p / math.pi
            tw = 0.0
            what = f"timing pulley {belt}, {z} teeth"
            notes.append(f"Teeth: not modelled; the pulley is simplified to its pitch cylinder Ø{_g(round(pd, 3))} = "
                         f"z × p / π ({belt}, pitch {_g(p)}), with flanges to the envelope Ø.")
        known |= {round(pd, 3), p}
        if pd > OD + 1e-6:
            raise Undetermined(f"the pitch Ø{_g(round(pd, 2))} is larger than the envelope Ø{_g(OD)}")
        PD = S.p("PITCH_D", round(pd, 4), f"pitch Ø, mm ({'p / sin(180° / z)' if sprocket else 'z p / π'})", "Teeth",
                 "Pitch Ø", lo=bore + 4)
        HUB = S.p("HUB_D", min(hub, round(pd - 4, 1)), "hub Ø, mm (a design choice: 1.8 × bore, or bore + 2 (t2 + 4))",
                  "Hub", "Hub Ø", lo=bore + 1)
        if HUB.val <= bore + 2 * t2 + 1:
            raise Undetermined("the pitch Ø leaves no hub round the keyway")
        if sprocket:
            TW = S.p("TOOTH_WIDTH", tw, "tooth width, mm (0.93 × the chain's inner width)", "Teeth", "Tooth width",
                     lo=1)
            if tw >= H:
                prof = [(BO / 2, -(WID / 2)), (PD / 2, -(WID / 2)), (PD / 2, WID / 2), (BO / 2, WID / 2)]
            else:
                prof = [(BO / 2, -(WID / 2)), (HUB / 2, -(WID / 2)), (HUB / 2, -(TW / 2)), (PD / 2, -(TW / 2)),
                        (PD / 2, TW / 2), (HUB / 2, TW / 2), (HUB / 2, WID / 2), (BO / 2, WID / 2)]
            R_used = PD
        else:
            FT = S.p("FLANGE_T", 1.5 if H >= 10 else 1.0, "flange thickness, mm (a design choice)", "Flanges",
                     "Flange thickness", lo=0.5)
            if OD - pd < 2.0:
                notes.append("Flanges: none (the envelope Ø leaves no room beyond the pitch Ø).")
                prof = [(BO / 2, -(WID / 2)), (PD / 2, -(WID / 2)), (PD / 2, WID / 2), (BO / 2, WID / 2)]
                R_used = PD
            else:
                prof = [(BO / 2, -(WID / 2)), (R / 2, -(WID / 2)), (R / 2, -(WID / 2) + FT), (PD / 2, -(WID / 2) + FT),
                        (PD / 2, WID / 2 - FT), (R / 2, WID / 2 - FT), (R / 2, WID / 2), (BO / 2, WID / 2)]
                R_used = R
    else:
        what = "plain belt pulley"
        rim = max(3.0, round(0.08 * OD, 1))
        web = max(4.0, round(0.3 * H, 1))
        notes.append(f"Form: a flat-faced belt pulley, rim {_g(rim)} thick, web {_g(web)} thick, hub Ø{_g(round(hub, 1))} "
                     "(design choices); crown the face if the belt needs it.")
        if hub + 2 * rim + 4 >= OD or web >= H - 2:
            prof = [(BO / 2, -(WID / 2)), (R / 2, -(WID / 2)), (R / 2, WID / 2), (BO / 2, WID / 2)]
            notes[-1] = "Form: a solid flat-faced pulley (no room for a web)."
        else:
            HUB = S.p("HUB_D", round(hub, 1), "hub Ø, mm (1.8 × bore, or bore + 2 (t2 + 4))", "Hub", "Hub Ø", lo=bore + 1)
            RIMT = S.p("RIM_T", rim, "rim thickness, mm (0.08 × OD, at least 3)", "Rim", "Rim thickness", lo=1)
            WEB = S.p("WEB_T", web, "web thickness, mm (0.3 × width, at least 4)", "Web", "Web thickness", lo=1)
            ri = R / 2 - RIMT
            prof = [(BO / 2, -(WID / 2)), (HUB / 2, -(WID / 2)), (HUB / 2, -(WEB / 2)), (ri, -(WEB / 2)),
                    (ri, -(WID / 2)), (R / 2, -(WID / 2)), (R / 2, WID / 2), (ri, WID / 2), (ri, WEB / 2),
                    (HUB / 2, WEB / 2), (HUB / 2, WID / 2), (BO / 2, WID / 2)]
        R_used = R
    key_rows, kk = _keyway_rows(S, hf["keys"], lambda k: BO, H)
    known |= kk
    for k in hf["keys"]:
        lines.append(f"{k['if']}  {k['label']}")
    for x in hf["faces"]:
        lines.append(f"{x['if']}  {x['label']} at Z {_g(x['z'])}")
    vol = fw_std.revolved_volume([(_num(a), _num(b)) for a, b in prof])
    for k in hf["keys"]:
        b, t2k = float(k["b"]), float(k["depth"])
        vol -= (b * (bore / 2 + t2k) - fw_std._keyway_segment(bore / 2, b)) * (float(k["z1"]) - float(k["z0"]))
    summary = f"{what} Ø{_g(OD)} × {_g(H)}, bore Ø{_g(bore)}" + (" with a keyway" if hf["keys"] else "")
    return {"kind": "pulley", "S": S, "profile": prof, "key_rows": key_rows, "lines": lines, "notes": notes,
            "known": known, "m_sizes": set(), "n_features": 1 + len(hf["keys"]) + len(hf["faces"]),
            "summary": summary, "allowed": {"a hole", "a special gear form", "a flange", "a web or recess"},
            "keyways": hf["keys"], "what": what, "volume": vol, "R": _num(R_used)}


def _profile_src(prof: list[tuple[V, V]]) -> list[str]:
    out = ["profile = [  # (r, z): the section revolved about Z"]
    for a, b in prof:
        out.append(f"    ({_src(a)}, {_src(b)}),")
    out.append("]")
    return out


def pulley_script(spec: dict[str, Any], name: str, material: str, icd_version: int) -> str:
    S: Script = spec["S"]
    out = [header(name, spec["what"], icd_version, spec["lines"], spec["notes"]), *_imports(False),
           f'NAME = "{name}"', f'MATERIAL = "{material}"', "", *S.block(), "", *_profile_src(spec["profile"]),
           "part, info = fw_std.revolved(profile, name=NAME)",
           'volume = info["volume"]  # Pappus: 2π × the first moment of the section about the axis',
           *spec["key_rows"], "", "result = part", 'EXPECTED = {"bbox": info["bbox"], "volume": volume, "solids": 1}',
           ""]
    return "\n".join(out)


def hub_spec(cx: Ctx) -> dict[str, Any]:
    """A plain turned hub, tube, drum or flange: the envelope cylinder with the ICD's bores and hub keyways."""
    spec = coupling_spec(cx, what="hub")
    OD, H = float(cx.it["size"][0]), float(cx.it["size"][2])
    spec["notes"] = [("Form: a plain turned part to the envelope (bored and keyed as the ICD says); turn it down or "
                     "hollow it in the Studio if it should be lighter.")]
    spec["summary"] = spec["summary"].replace("rigid sleeve coupling", "turned hub")
    spec["kind"] = "hub"
    spec["allowed"] = {"a hole", "a flange"}
    spec["what"] = "turned hub"
    _ = (OD, H)
    return spec


def coupling_spec(cx: Ctx, what: str = "coupling") -> dict[str, Any]:
    it = cx.it
    OD, H = float(it["size"][0]), float(it["size"][2])
    text = f"{cx.name}. {cx.desc}"
    fm = _FLEX.search(text) if what == "coupling" else None
    if fm:
        raise Undetermined(f"a {fm.group(1).lower()} coupling needs the designer (rigid sleeves are built from the "
                           "interfaces)")
    hf = _hub_features(cx, what)
    if not hf["bores"]:
        raise Undetermined(f"the {what} has no bore in its interfaces")
    S = Script()
    lines: list[str] = []
    notes = ["Form: a rigid sleeve coupling (one piece), bored for each shaft."]
    known: set[float] = {OD, H}
    S.p("OD", OD, "outside Ø, mm (ICD envelope)", "Coupling", "Outside Ø")
    WID = S.p("WIDTH", H, "length along the axis, mm (ICD envelope)", "Coupling", "Length", lo=2)
    cuts: list[tuple[dict[str, Any], str]] = []
    bore_names: dict[float, V] = {}
    if len({float(b["d"]) for b in hf["bores"]}) > 1 and all(b.get("z0") is None for b in hf["bores"]):
        # the ICD states each bore through the whole hub: a stepped bore can't be (each step ends at the other), so
        # the conformance review would refuse any model; said instead of built (finding for the layout)
        raise Undetermined("the interfaces give bores of two sizes, each through the whole coupling (a stepped bore "
                           "needs each bore's depth)")
    for n, x in enumerate(sorted(hf["bores"], key=lambda b: float(b.get("z0") or -1e9)), start=1):
        d = float(x["d"])
        if d not in bore_names:
            bore_names[d] = S.p(f"BORE_{len(bore_names) + 1}" if len(hf["bores"]) > 1 else "BORE", d,
                                f"bore Ø, mm ({x_fit(x) or 'H7'} on the shaft)", "Bores", f"Bore {n} Ø", lo=1)
        span = None if x.get("z0") is None else _ends(S, "z", float(x["z0"]), float(x["z1"]), WID, None)
        cuts.append(({"name": f"Bore Ø{_g(d)}", "ax": "z", "c": (0.0, 0.0), "d": bore_names[d], "span": span},
                     f"{x['if']} {x['label']}"))
        known.add(d)
        lines.append(f"{x['if']}  {x['label']}" + ("" if x.get("z0") is None else f", Z {_g(x['z0'])} to {_g(x['z1'])}"))
    if any(float(k["d"]) not in bore_names for k in hf["keys"]):
        raise Undetermined("a hub keyway is not on one of the coupling's bores")
    key_rows, kk = _keyway_rows(S, hf["keys"], lambda k: bore_names[float(k["d"])], H)
    known |= kk
    for k in hf["keys"]:
        lines.append(f"{k['if']}  {k['label']}")
    for x in hf["faces"]:
        lines.append(f"{x['if']}  {x['label']} at Z {_g(x['z'])}")
    info = fw_std.machined_volume(("disc", OD, H), [], [_num(c) for c, _w in cuts])
    if info["problems"]:
        raise Undetermined("the coupling's bores overlap: " + info["problems"][0])
    summary = (f"rigid sleeve coupling Ø{_g(OD)} × {_g(H)}, bore{'s' if len(bore_names) > 1 else ''} "
               + " / ".join(f"Ø{_g(d)}" for d in bore_names) + (f", {len(hf['keys'])} keyway"
                                                                + ("s" if len(hf["keys"]) != 1 else "") if hf["keys"]
                                                                else ""))
    return {"kind": "coupling", "S": S, "cuts": cuts, "key_rows": key_rows, "lines": lines, "notes": notes,
            "known": known, "m_sizes": set(), "n_features": len(hf["bores"]) + len(hf["keys"]) + len(hf["faces"]),
            "summary": summary, "allowed": {"a hole"}, "keyways": hf["keys"], "what": "rigid sleeve coupling"}


def coupling_script(spec: dict[str, Any], name: str, material: str, icd_version: int) -> str:
    S: Script = spec["S"]
    cuts = [(_clean(c), w) for c, w in spec["cuts"]]
    out = [header(name, spec.get("what") or "rigid sleeve coupling", icd_version, spec["lines"], spec["notes"]),
           *_imports(False),
           f'NAME = "{name}"', f'MATERIAL = "{material}"', "", *S.block(), "", *_rows("cuts", cuts), "",
           'part, info = fw_std.machined(("disc", OD, WIDTH), cuts=cuts, name=NAME)', 'volume = info["volume"]',
           *spec["key_rows"], "", "result = part", 'EXPECTED = {"bbox": info["bbox"], "volume": volume, "solids": 1}',
           ""]
    return "\n".join(out)


_SETSCREW_M = re.compile(r"(?<![\w.])M(\d{1,2})\b[^.;,]*?(?:set|grub)\s*screw|(?:set|grub)\s*screws?\s*M(\d{1,2})\b",
                         re.IGNORECASE)


def collar_spec(cx: Ctx) -> dict[str, Any]:
    """A shaft collar: the bored ring the spacer path builds, plus a radial tapped hole for a set screw."""
    from aicad.office import direct

    sp = direct._spacer_spec(cx.sk, cx.ifs, cx.item, cx.it)
    OD, H, bore = sp["OD"], sp["H"], sp["bore"]
    m = _SETSCREW_M.search(f"{cx.name}. {cx.desc}")
    size = int(m.group(1) or m.group(2)) if m else (4 if bore <= 10 else 5 if bore <= 20 else 6 if bore <= 30 else 8)
    if size not in icd.TAP_DRILL:
        raise Undetermined(f"no tap drill for an M{size} set screw")
    td = tap_drill(size)
    if td >= bore or (OD - bore) / 2 < 1.0 * size:
        raise Undetermined(f"an M{size} set screw doesn't fit a Ø{_g(OD)} / Ø{_g(bore)} collar")
    S = Script()
    ODp = S.p("OD", OD, "outside Ø, mm", "Collar", "Outside Ø")
    WID = S.p("WIDTH", H, "width along the shaft, mm", "Collar", "Width", lo=2)
    BO = S.p("BORE", bore, "bore Ø, mm (on the shaft)", "Collar", "Bore Ø", lo=1)
    TD = S.p("SET_SCREW_D", td, f"set screw tap drill Ø, mm (M{size}, ISO 2306)", "Set screw", "Tap drill Ø", lo=1)
    lines = [f"{sp['bore_if'] or 'bore'}  bore Ø{_g(bore)} on the {sp.get('host') or 'shaft'}",
             f"envelope Ø{_g(OD)} × {_g(H)}"]
    for f in sp["faces"]:
        lines.append(f"{f['if']}  {f['label']} at Z {_g(f['z'])}")
    notes = [f"Set screw: one M{size} radial tapped hole at mid-width on +X ("
             + ("the brief's size" if m else "a design choice by the bore") + ")."]
    cuts = [({"name": "Bore", "ax": "z", "c": (0.0, 0.0), "d": BO, "span": None}, "on the shaft")]
    vol = math.pi / 4 * (OD ** 2 - bore ** 2) * H - (fw_std.cross_hole_volume(OD, td)
                                                      - fw_std.cross_hole_volume(bore, td)) / 2
    _ = (ODp, WID)
    return {"kind": "collar", "S": S, "cuts": cuts, "lines": lines, "notes": notes,
            "known": set(sp["known"]) | {td, float(size)}, "m_sizes": {size}, "n_features": 1 + len(sp["faces"]),
            "summary": f"shaft collar Ø{_g(OD)} / Ø{_g(bore)} × {_g(H)} with an M{size} set screw",
            "allowed": {"a hole", "a thread", "a set screw"}, "size": size, "volume": vol, "TD": TD}


def collar_script(spec: dict[str, Any], name: str, material: str, icd_version: int) -> str:
    S: Script = spec["S"]
    size = spec["size"]
    out = [header(name, "shaft collar", icd_version, spec["lines"], spec["notes"]), *_imports(False),
           f'NAME = "{name}"', f'MATERIAL = "{material}"', "", *S.block(), "", *_rows("cuts", spec["cuts"]), "",
           'part, info = fw_std.machined(("disc", OD, WIDTH), cuts=cuts, name=NAME)',
           "# the set screw hole, radial on +X at mid-width, from the bore out through the wall",
           "tool = Pos((OD / 2 + 1) / 2, 0, 0) * Rot(0, 90, 0) * Cylinder(SET_SCREW_D / 2, OD / 2 + 1)",
           f'part = fw.feature("Set screw hole M{size}", part - tool, d=SET_SCREW_D)',
           (f'part = fw.thread(part, ((OD + BORE) / 4, 0, SET_SCREW_D / 2), "M{size}x{_pitch(size):g}", '
           "depth=(OD - BORE) / 2)"),
           "# removed: half the cross hole through the full ring less the half through the bore (by symmetry)",
           'volume = info["volume"] - (fw.cross_hole_volume(OD, SET_SCREW_D) - fw.cross_hole_volume(BORE, SET_SCREW_D)) / 2',
           "", "result = part", 'EXPECTED = {"bbox": info["bbox"], "volume": volume, "solids": 1}', ""]
    return "\n".join(out)
