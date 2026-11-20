"""Instant, dimensioned 3D preview of a Design Office layout (WORKLIST 47).

Founder (2026-11-19): no AI image generation in planning. A generated picture has no dimensions and looks convincing
while being wrong; the engineer should approve the real layout. So at plan time the office solves the layout exactly
as plan approval will (the design graph and the connection solver, the master-model skeleton where that path is used,
else the role or standard layout; ``interfaces._graph_layout``), and this module turns the solved skeleton and its
interfaces into a compact scene the browser draws in a few milliseconds:

  bodies   one per item copy and per placed standard part: a primitive (box, cylinder, stepped shaft, gear blank at
           its tip circle and face width, bearing ring, key, retaining ring, screw as a simple cylinder) in its own
           frame, and a 12-number placement (``frames.to12``: rotation rows and translation, program frame, mm)
  path     how each part will be made: ``spec`` (built from the interface spec, no AI: ``direct.plan`` says so),
           ``toolbox`` (a standard part), ``ai`` (an AI designer models it; the reason is given)
  dims     the key numbers on the model (centre distances, overall envelope, shaft diameters at the seats, bolt
           circles, part sizes), each with where it came from: the brief, the engineer's answer, a standard, a design
           rule, an assumption, the layout, or the master model's measurement (the plan review's source tags)
  issues   layout conflicts, unplaced parts and per-copy ``no_interface`` problems with their text and the bodies
           they name, so they are drawn in red before anyone approves

No CAD kernel runs: everything is arithmetic on the layout (a reducer takes about 10 to 40 ms server side). The
preview is a picture of the layout for the engineer, never an acceptance check (CLAUDE.md: geometry acceptance is the
deterministic checks).
"""

from __future__ import annotations

import copy
import math
import re
import time
from typing import Any

from aicad.office import OfficeInputError

VERSION = 1
SOURCE_WORD = {"brief": "from the brief", "answer": "your answer", "standard": "standard", "rule": "design rule",
               "assumed": "assumed", "layout": "laid out", "plan": "from the plan",
               "measured": "measured from the master model"}
PATH_WORD = {"spec": "Built from the interface spec (no AI)", "toolbox": "Toolbox standard part",
             "template": "Workspace template (no AI)", "ai": "Modelled by an AI designer"}
MAX_SCREWS = 400      # screws drawn (a large program has hundreds; the rest are counted)
_FASTY = re.compile(r"screw|bolt|\bnut\b|washer|\bstud", re.IGNORECASE)


# ----------------------------------------------------------------------------- small vector helpers
def _r(x: float, n: int = 3) -> float:
    return round(float(x), n) + 0.0


def _v(p: Any) -> list[float]:
    return [_r(p[0]), _r(p[1]), _r(p[2])]


def _add(a: Any, b: Any, k: float = 1.0) -> list[float]:
    return [float(a[i]) + float(b[i]) * k for i in range(3)]


def _frame_z(n: list[float]) -> list[list[float]]:
    """A rotation (rows) whose third column is the unit vector ``n`` (a screw's axis), axis aligned when n is."""
    L = math.sqrt(sum(x * x for x in n)) or 1.0
    z = [x / L for x in n]
    ref = [0.0, 0.0, 1.0] if abs(z[2]) < 0.9 else [1.0, 0.0, 0.0]
    x = [ref[1] * z[2] - ref[2] * z[1], ref[2] * z[0] - ref[0] * z[2], ref[0] * z[1] - ref[1] * z[0]]
    xl = math.sqrt(sum(c * c for c in x)) or 1.0
    x = [c / xl for c in x]
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    return [[x[i], y[i], z[i]] for i in range(3)]


def _T(R: list[list[float]], t: Any) -> list[float]:
    from aicad.office import frames

    return [_r(v, 6) for v in frames.to12(R, [float(c) for c in t])]


def _half_world(R: list[list[float]], size: list[float]) -> list[float]:
    """Half extents along the program axes of a centred box of ``size`` turned by ``R``."""
    return [sum(abs(R[i][j]) * float(size[j]) / 2 for j in range(3)) for i in range(3)]


# ----------------------------------------------------------------------------- the layout the gate will see
def plan_layout(doc: dict[str, Any], plan: dict[str, Any] | None = None
                ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[str]]:
    """(program as approval would make it, skeleton, interfaces, notes) for the program's plan, or for an edited plan
    (``plan``: the plan review's unsaved edits, normalised exactly as approval normalises them). The same code as
    ``interfaces.create``: the master skeleton, the connection solver or the role layout, else the standard layout,
    then Archie's automatic adjustments when the first layout has problems. Nothing is saved."""
    from aicad.graph.compile import overrides_for
    from aicad.master import decide
    from aicad.office import icd, interfaces, planner

    base = doc.get("plan") or {}
    if not base.get("subassemblies"):
        raise OfficeInputError("There is no plan to preview yet.")
    if plan is not None:
        p2 = planner.normalise_plan(plan, base.get("source") or "standard")
        if p2 is None:
            raise OfficeInputError("The plan needs at least one sub-assembly with one part.")
        plan = {**base, **p2}
    else:
        plan = base
    pdoc = decide.pseudo_doc(copy.deepcopy(plan), str(doc.get("brief") or ""), str(doc.get("name") or "Program"))
    pdoc["direct_build"] = doc.get("direct_build", True)
    parts = icd.parts_from(pdoc)
    ov0 = overrides_for(pdoc["plan"], parts)
    built = interfaces._graph_layout(pdoc, ov0)
    skel, ic = icd.new_icd(parts, pdoc["brief"], "Archie", ov0, built=built)
    if skel.get("solver") == "roles":
        ic["overrides"] = {**(ic["overrides"] or {}), "layout": "roles"}
    pdoc["icd"], pdoc["skeleton"] = ic, skel
    notes: list[str] = []
    if ic["problems"] and skel.get("items"):
        ov, steps, probs = interfaces.autofix(pdoc, ic["overrides"])
        if steps:
            skel, ifs = interfaces._rebuild(pdoc, ov)
            ic.update(interfaces=ifs, overrides=ov, problems=probs)
            pdoc["skeleton"] = skel
            notes.append("Archie adjusted his layout so every part can be made: "
                         + "; ".join(interfaces._fmt_step(s) for s in steps[:6]))
    return pdoc, skel, ic["interfaces"], notes


# ----------------------------------------------------------------------------- how each part will be made
def build_paths(doc: dict[str, Any], skel: dict[str, Any], ifs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{item id: {"path": "spec" | "ai", "why": plain words}} for every designed item, from the direct builder's own
    decision on this layout as if it were approved (``direct.plan``: pure, no kernel, no model)."""
    from aicad.office import direct

    d2 = {**doc, "skeleton": skel, "icd": {**(doc.get("icd") or {}), "status": "approved", "interfaces": ifs,
                                           "version": int((doc.get("icd") or {}).get("version") or 1)}}
    on = direct.enabled(d2)
    out: dict[str, dict[str, Any]] = {}
    by_item = {t["item_id"]: t for t in doc.get("tickets") or [] if t.get("kind") == "part"}
    for iid in skel.get("items") or {}:
        t = by_item.get(iid)
        if t is None or not on:
            out[iid] = {"path": "ai", "why": "the direct path is switched off" if not on else ""}
            continue
        try:
            dp = direct.plan(d2, t)
        except Exception as e:  # noqa: BLE001 - a builder that can't read this layout: the designer models it
            dp = {"path": "agent", "reasons": [f"the interfaces can't be read yet ({type(e).__name__})"]}
        if dp.get("path") == "direct":
            out[iid] = {"path": "spec", "why": str(dp.get("summary") or "")}
        else:
            out[iid] = {"path": "ai", "why": "; ".join(str(x) for x in (dp.get("reasons") or [])[:2])}
        # the ticket's own build path (its estimate's, PD-190) wins: the board, the estimates and the preview agree
        est = {"direct": "spec", "template": "template", "agent": "ai"}.get(str(t.get("estimate_path") or ""))
        if est and est != out[iid]["path"]:
            out[iid] = {"path": est, "why": out[iid]["why"] if est == "ai" else ""}
    return out


# ----------------------------------------------------------------------------- where each number came from
class _Sources:
    """Source tags of the plan's numbers: the design graph's parameters (by part name), else the plan or the layout."""

    def __init__(self, plan: dict[str, Any] | None, master: bool):
        self.master = master
        g = ((plan or {}).get("graph") or {}).get("data") or {}
        self.comps = {str(c.get("name")): c for c in g.get("components") or []}
        self.conns = list(g.get("connections") or [])
        self.ids = {str(c.get("id")): str(c.get("name")) for c in g.get("components") or []}
        self.graph = bool(g)

    def param(self, name: str, keys: tuple[str, ...], what: str, value: Any, default: str = "layout",
              note: str = "") -> dict[str, Any]:
        if self.master:
            return {"what": what, "value": value, "source": "measured", "word": SOURCE_WORD["measured"],
                    "note": note or "measured from the master model's body"}
        c = self.comps.get(name) or self.comps.get(re.sub(r"\s*#\d+$", "", name))
        for k in keys:
            p = ((c or {}).get("params") or {}).get(k)
            if isinstance(p, dict) and p.get("value") is not None:
                src = str(p.get("source") or "assumed")
                return {"what": what, "value": value, "source": src, "word": SOURCE_WORD.get(src, src),
                        "note": str(p.get("note") or note)}
        src = "plan" if (not self.graph and default == "layout" and c is None and keys) else default
        return {"what": what, "value": value, "source": src, "word": SOURCE_WORD.get(src, src), "note": note}

    def conn(self, kind: str, a: str, b: str, key: str, what: str, value: Any, default: str, note: str
             ) -> dict[str, Any]:
        if self.master:
            return {"what": what, "value": value, "source": "measured", "word": SOURCE_WORD["measured"], "note": note}
        for x in self.conns:
            if x.get("kind") != kind:
                continue
            ends = {self.ids.get(str(x.get("host"))), self.ids.get(str(x.get("guest")))}
            if not ({a, b} <= ends or not (a and b)):
                continue
            p = (x.get("params") or {}).get(key)
            if isinstance(p, dict) and p.get("value") is not None:
                src = str(p.get("source") or "rule")
                return {"what": what, "value": value, "source": src, "word": SOURCE_WORD.get(src, src),
                        "note": note or str(p.get("note") or "")}   # the formula with this program's numbers
        return {"what": what, "value": value, "source": default, "word": SOURCE_WORD.get(default, default),
                "note": note}


def _fmt(x: float) -> str:
    return f"{round(float(x), 2):g}"


# ----------------------------------------------------------------------------- the scene
def scene(skel: dict[str, Any], ifs: list[dict[str, Any]], *, plan: dict[str, Any] | None = None,
          paths: dict[str, dict[str, Any]] | None = None, notes: list[str] | None = None) -> dict[str, Any]:
    """The preview scene of a skeleton and its interfaces (pure; see the module doc for the format)."""
    from aicad.office import direct, frames, icd

    t0 = time.perf_counter()
    items: dict[str, dict[str, Any]] = skel.get("items") or {}
    master = skel.get("solver") == "master" or str(skel.get("layout") or "") == "master"
    src = _Sources(plan, master)
    paths = paths or {}
    bodies: list[dict[str, Any]] = []
    dims: list[dict[str, Any]] = []
    rows: dict[str, dict[str, Any]] = {}

    def body(iid: str, copy_: int, name: str, kind: str, g: dict[str, Any], T: list[float], path: str,
             extra: dict[str, Any] | None = None) -> dict[str, Any]:
        b = {"id": f"{iid}#{copy_}", "item": iid, "copy": copy_, "name": name, "kind": kind, "g": g, "T": T,
             "path": path, **(extra or {})}
        bodies.append(b)
        return b

    # designed items: one body per copy, at the layout position (parts are modelled centred)
    for iid, it in items.items():
        size = [float(v) for v in it.get("size") or [10, 10, 10]]
        nm = str(it.get("name") or iid)
        pth = paths.get(iid) or {"path": "ai", "why": ""}
        rows[iid] = {"name": nm, "path": pth["path"], "why": pth.get("why") or "", "qty": len(it.get("copies") or []),
                     "standard": False}
        role = it.get("role")
        if it.get("shape") == "box":
            kind, g = "box", {"s": size}
            if it.get("cavity"):
                g["open"] = True
        elif role == "gear" and it.get("internal") and it.get("module") and it.get("teeth"):
            # an internal ring gear: drawn as its rim, open to the tooth tips m (z - 2)
            kind, g = "cyl", {"d": size[0], "L": size[2], "bore": _r(float(it["module"]) * (int(it["teeth"]) - 2))}
        elif role == "gear" and it.get("module") and it.get("teeth"):
            m, z = float(it["module"]), int(it["teeth"])
            kind, g = "gear", {"tip": _r(m * (z + 2)), "pitch": _r(m * z), "width": size[2], "m": m, "z": z,
                               "bore": float(it.get("bore") or 0)}
        elif role == "shaft":
            kind, g = "shaft", {"segs": [[-size[2] / 2, size[2] / 2, size[0]]]}
            try:
                spec = direct._shaft_spec(skel, ifs, iid, it)
                g["segs"] = [[_r(s["z0"]), _r(s["z1"]), _r(s["d"])] for s in spec["segments"]]
            except Exception:  # noqa: BLE001, S110 - a profile the builder can't read: the envelope cylinder
                pass
        else:
            kind, g = "cyl", {"d": size[0], "L": size[2]}
            if it.get("bore"):
                g["bore"] = float(it["bore"])
        R = frames.item_rotation(it.get("ax") or "z", float(it.get("rot") or 0) + float(it.get("phase") or 0))
        for c, at in enumerate(it.get("copies") or []):
            body(iid, c, nm if len(it.get("copies") or []) < 2 else f"{nm} #{c + 1}", kind, g, _T(R, at), pth["path"])
        # its size, with where the numbers came from (shown on hover and with "all dimensions")
        if not it.get("copies"):
            continue
        at0 = it["copies"][0]
        if kind == "gear":
            text = f"m{_fmt(g['m'])} × {g['z']}, Ø{_fmt(g['tip'])} × {_fmt(g['width'])}"
            srcs = [src.param(nm, ("module",), "Module", g["m"], "rule"), src.param(nm, ("teeth",), "Teeth", g["z"],
                                                                                    "rule"),
                    src.param(nm, ("face_width",), "Face width", g["width"], "rule", "10 × module unless stated"),
                    {"what": "Tip circle", "value": g["tip"], "source": "standard", "word": SOURCE_WORD["standard"],
                     "note": f"m (z + 2) = {_fmt(g['m'])} × {g['z'] + 2}"}]
        elif kind == "shaft":
            ds = sorted({s[2] for s in g["segs"]})
            text = "Ø" + " / Ø".join(_fmt(d) for d in ds) + f" × {_fmt(size[2])}"
            srcs = [src.param(nm, ("length",), "Length", size[2], "layout", "the bearings, hubs and shaft ends it carries"),
                    src.param(nm, ("d",), "Seat Ø", ds[0], "layout")]
        elif kind == "box":
            text = " × ".join(_fmt(x) for x in size)
            srcs = [src.param(nm, ("L",), "Length", size[0], "layout"), src.param(nm, ("W",), "Width", size[1], "layout"),
                    src.param(nm, ("H", "T"), "Height", size[2], "layout")]
        else:
            text = f"Ø{_fmt(size[0])} × {_fmt(size[2])}"
            srcs = [src.param(nm, ("od", "d"), "Diameter", size[0], "layout"),
                    src.param(nm, ("width", "length"), "Length", size[2], "layout")]
        dims.append({"id": f"size:{iid}", "kind": "label", "at": _v(at0), "text": text, "label": f"{nm} size",
                     "items": [iid], "prio": 2, "sources": srcs})

    # standard parts the interfaces seat: bearings, keys, rings, pins (where Fitz will put them)
    std_names: dict[str, str] = {}
    unplaced: list[str] = []
    for st in skel.get("standard") or []:
        sid, nm = st["item"], str(st.get("name") or st["item"])
        std_names[sid] = nm
        rows[sid] = {"name": nm, "path": "toolbox", "why": "", "qty": int(st.get("qty") or 1), "standard": True}
        seat = icd.seated(ifs, sid)
        if not seat:
            continue
        R = seat.get("R") or frames.IDENT
        code = seat["code"]
        if code == "bearing":
            from aicad.toolbox import BEARING

            d, D, B = BEARING[int(seat["params"]["SERIES"])]
            kind, g, half = "bearing", {"d": float(d), "D": float(D), "B": float(B)}, float(B) / 2
        elif code == "parallel_key":
            from aicad.toolbox import key_row

            kb, kh, _t1, _t2 = key_row(float(seat["params"]["D"]))
            kind, g, half = "key", {"s": [float(seat["params"]["L"]), kb, kh]}, kh / 2
        elif code == "retaining_ring":
            from aicad.toolbox import ring_row

            s_, b_, d2, _m, _n = ring_row(float(seat["params"]["D"]))
            kind, g, half = "ring", {"d": float(d2), "D": float(d2 + 2 * b_), "s": float(s_)}, float(s_) / 2
        else:
            kind, g = "cyl", {"d": float(seat["params"]["D"]), "L": float(seat["params"]["L"])}
            half = float(seat["params"]["L"]) / 2
        for c, at in enumerate(seat["at"]):
            mid = [float(at[k]) + R[k][2] * half for k in range(3)]
            body(sid, c, nm, kind, g, _T(R, mid), "toolbox", {"standard": True})
        rows[sid]["placed"] = len(seat["at"])

    # screws of the bolted joints, as simple cylinders through the joint (lengths are chosen at assembly)
    n_screws = 0
    for f in ifs:
        d = f.get("data") or {}
        if f.get("kind") != "hole_pattern" or not d.get("positions"):
            continue
        m = float(d.get("fastener_size") or icd.bolt_for_hole(float(d.get("d") or 6.6)))
        fid = str(d.get("fastener_item") or f"fasteners:{f['id']}")
        if fid not in rows:
            rows[fid] = {"name": str(d.get("fastener") or "Screw"), "path": "toolbox", "why": "", "qty": 0,
                         "standard": True}
        rows[fid]["placed"] = int(rows[fid].get("placed") or 0) + len(d["positions"])
        ax = icd.ax_of(d)
        n = [float(x) for x in (d.get("normal") or icd.unit(ax))]
        ta = _depth(items, f["a"], n, float(d["plane_z"]), -1)
        tb = _depth(items, f["b"], n, float(d["plane_z"]), +1)
        if d.get("through") or d.get("pivot"):
            lo, hi = -ta, tb   # through both parts; head on side a
            head_at = -1
        else:
            eng = min(float((d.get("tapped") or {}).get("depth") or 1.5 * m), ta or 1.5 * m)
            lo, hi = -eng, min(tb, 3 * m) if tb > 0 else 2 * m
            head_at = +1
        L = max(hi - lo, m)
        sname = std_names.get(fid, "")
        hex_ = re.search(r"hex|\bbolt", sname, re.IGNORECASE) and not re.search(r"socket|cap screw|shcs", sname,
                                                                               re.IGNORECASE)
        hd, hk = (1.6 * m, 0.7 * m) if hex_ else (1.5 * m, m)   # ISO 4017 / ISO 4762 proportions
        g = {"d": m, "L": _r(L), "head_d": _r(hd), "head_h": _r(hk)}
        dirv = n if head_at > 0 else [-x for x in n]
        R = _frame_z(dirv)
        for k, p2 in enumerate(d["positions"]):
            if n_screws >= MAX_SCREWS:
                break
            base = icd.point3(ax, p2, float(d["plane_z"]))
            tip = _add(base, n, lo if head_at > 0 else hi)   # the shank's far end; the head at the other end
            c = sum(1 for b in bodies if b["item"] == fid)
            body(fid, c, sname or rows[fid]["name"], "screw", g, _T(R, tip), "toolbox",
                 {"standard": True, "joint": f["id"]})
            n_screws += 1
        # the bolt circle, or the pattern's count and size
        if d.get("pcd") and d.get("centre") is not None:
            c3 = icd.point3(ax, d["centre"], float(d["plane_z"]))
            key = f"pcd:{_r(d['pcd'])}:{ax}:{_r(d['centre'][0])}:{_r(d['centre'][1])}"
            if not any(x["id"] == key for x in dims):  # one per bolt circle and axis line (both caps of a seat)
                dims.append({"id": key, "kind": "diameter", "c": _v(c3), "axis": _v(icd.unit(ax)),
                             "r": _r(float(d["pcd"]) / 2), "value": float(d["pcd"]),
                             "text": f"{len(d['positions'])}× {d.get('fastener') or ''} PCD {_fmt(d['pcd'])}".replace("  ", " "),
                             "label": f"Bolt circle, {f['a']['name']} / {f['b']['name']}",
                             "items": [f["a"]["item"], f["b"]["item"]], "prio": 1,
                             "sources": [{"what": "Bolt circle Ø", "value": float(d["pcd"]), "source": "rule",
                                          "word": SOURCE_WORD["rule"] if not master else SOURCE_WORD["measured"],
                                          "note": "the seat Ø plus room for the screw heads and the wall (layout rule)"},
                                         {"what": "Screws", "value": d.get("fastener"),
                                          "source": "measured" if master else "rule",
                                          "word": SOURCE_WORD["measured" if master else "rule"],
                                          "note": "screw size for the joint (layout rule, ISO 273 clearance holes)"}]})
        else:
            p0 = icd.point3(ax, d["positions"][0], float(d["plane_z"]))
            nh = len(d["positions"])
            how = ("a pivot bolt through both parts" if d.get("pivot") else
                   f"{nh} hole{'s' if nh != 1 else ''} Ø{_fmt(d.get('d') or 0)} (ISO 273 clearance)"
                   + (f", {d['pattern']} pattern {_fmt(d['inset'])} from the edge" if d.get("inset") else ""))
            dims.append({"id": f"holes:{f['id']}", "kind": "label", "at": _v(p0),
                         "text": f"{nh}× {d.get('fastener') or 'M?'}",
                         "label": f"Bolted joint {f['a']['name']} / {f['b']['name']}",
                         "items": [f["a"]["item"], f["b"]["item"]], "prio": 2,
                         "sources": [{"what": "Screws", "value": d.get("fastener"),
                                      "source": "measured" if master else "rule",
                                      "word": SOURCE_WORD["measured" if master else "rule"], "note": how}]})

    # centre distances (gear meshes, belts)
    for f in ifs:
        d = f.get("data") or {}
        if f.get("kind") not in ("gear_mesh", "belt_drive") or d.get("axis_a") is None or d.get("axis_b") is None:
            continue
        ax = icd.ax_of(d)
        pa = icd.point3(ax, d["axis_a"], float(d.get("plane_a") or 0))
        pb = icd.point3(ax, d["axis_b"], float(d.get("plane_a") or 0))
        a = float(d.get("centre_distance") or math.dist(pa, pb))
        note = (f"a = m (z_ring - z_planet) / 2 = {_fmt(d.get('module') or 0)} × ({d.get('teeth_b')} - "
                f"{d.get('teeth_a')}) / 2" if d.get("internal") else
                f"a = m (z1 + z2) / 2 = {_fmt(d.get('module') or 0)} × ({d.get('teeth_a')} + {d.get('teeth_b')}) / 2"
                if f["kind"] == "gear_mesh" else "C = D1 + D2 unless stated (layout rule)")
        dims.append({"id": f"cd:{f['id']}", "kind": "linear", "a": _v(pa), "b": _v(pb), "value": _r(a),
                     "text": _fmt(a), "label": f"Centre distance {f['a']['name']} / {f['b']['name']}",
                     "items": [f["a"]["item"], f["b"]["item"]], "prio": 1,
                     "sources": [src.conn(f["kind"], f["a"]["name"], f["b"]["name"], "centre_distance",
                                          "Centre distance", _r(a), "standard" if f["kind"] == "gear_mesh" else "rule",
                                          note)]})

    # shaft diameters at the seats (one per shaft and diameter)
    seen: set[tuple[str, float]] = set()
    for f in ifs:
        d = f.get("data") or {}
        k = f.get("kind")
        if k not in ("shaft_bore", "bearing_journal", "bearing_seat") or d.get("axis") is None:
            continue
        ax = icd.ax_of(d)
        if k == "bearing_seat":
            shaft, dia = f["b"], float(d.get("d") or d.get("shaft_d") or 0)
            spans = [s["z"] for s in d.get("seats") or []] or [d.get("z") or [0, 0]]
        else:
            shaft = f["b"] if k == "shaft_bore" else f["a"]
            dia = float(d.get("d") or 0)
            spans = [d.get("seat_z") or d.get("z") or [0, 0]]
        if not dia or (shaft["item"], dia) in seen or shaft["item"] not in items:
            continue
        seen.add((shaft["item"], dia))
        z0, z1 = float(spans[0][0]), float(spans[0][1])
        c3 = icd.point3(ax, d["axis"], (z0 + z1) / 2)
        if k == "shaft_bore":
            hub = f["a"]["name"]
            s1 = src.param(shaft["name"], ("d",), f"Seat Ø for the {hub}", dia, "layout")
            fit = d.get("fit")
            label = f"{shaft['name']}: seat for the {hub}"
        else:
            s1 = {"what": "Journal Ø", "value": dia, "source": "standard", "word": SOURCE_WORD["standard"],
                  "note": f"the bore of the {d.get('designation') or ''} bearing (ISO 15)".replace("  ", " ")}
            if master:
                s1 = {**s1, "source": "measured", "word": SOURCE_WORD["measured"]}
            fit = d.get("shaft_fit")
            label = f"{shaft['name']}: bearing journal"
        dims.append({"id": f"dia:{shaft['item']}:{_r(dia)}", "kind": "diameter", "c": _v(c3), "axis": _v(icd.unit(ax)),
                     "r": _r(dia / 2), "value": dia, "text": f"Ø{_fmt(dia)}" + (f" {fit.split('/')[-1]}" if fit else ""),
                     "label": label, "items": [shaft["item"], f["a"]["item"] if k != "bearing_journal" else shaft["item"]],
                     "prio": 1, "sources": [s1] + ([{"what": "Fit", "value": fit, "source": "rule",
                                                    "word": SOURCE_WORD["rule"], "note": "ISO 286 (verify)"}] if fit else [])})

    # the overall envelope of what is drawn
    lo, hi = _bounds(bodies)
    if lo is not None and hi is not None:
        for i, axn in enumerate("XYZ"):
            span = hi[i] - lo[i]
            if span < 0.5:
                continue
            b = list(lo)
            b[i] = hi[i]
            dims.append({"id": f"env:{axn}", "kind": "linear", "a": _v(lo), "b": _v(b), "value": _r(span),
                         "text": _fmt(span), "label": f"Overall {('length', 'width', 'height')[i]} ({axn})", "items": [],
                         "prio": 1, "envelope": True,
                         "sources": [{"what": f"Overall {axn}", "value": _r(span), "source": "layout",
                                      "word": SOURCE_WORD["measured" if master else "layout"],
                                      "note": "the extent of every part as placed (screws drawn at their joint)"}]})

    # problems, on the bodies they name
    from aicad.office import icd as icd_

    issues: list[dict[str, Any]] = []
    for x in icd_.issues(skel, ifs):
        sev = str(x.get("severity") or "error")
        its = [str(i) for i in x.get("items") or []]
        if x.get("code") == "no_interface" and x.get("copy") is not None:
            ids = [f"{its[0]}#{int(x['copy'])}"] if its else []
        else:
            ids = [b["id"] for b in bodies if b["item"] in its]
        issues.append({"code": x.get("code"), "severity": sev, "text": str(x.get("text") or ""), "items": its,
                       "bodies": ids, "acknowledged": bool(x.get("acknowledged"))})
    for iss in issues:
        if iss["acknowledged"]:
            continue
        for b in bodies:
            if b["id"] in iss["bodies"] and iss["severity"] == "error":
                b["flag"] = "error"
    for si, s in enumerate((plan or {}).get("subassemblies") or []):  # each row's place in the plan (the review
        for pi, p in enumerate(s.get("parts") or []):                    # matches its own edited rows by it)
            r = rows.get(f"i_{s.get('id')}_{p.get('id')}")
            if r is not None:
                r["at"] = [si, pi]
    for sid, r in rows.items():
        if r.get("standard") and sid in std_names and not r.get("placed") and not _FASTY.search(r["name"]):
            unplaced.append(sid)
    out = {
        "version": VERSION, "units": "mm",
        "solver": skel.get("solver") or skel.get("layout"), "layout": skel.get("layout"), "master": master,
        "bodies": bodies, "dims": dims, "issues": issues, "rows": rows, "unplaced": unplaced,
        "envelope": {"min": _v(lo), "max": _v(hi)} if lo is not None and hi is not None else None,
        "notes": list(notes or []) + [str(n) for n in (skel.get("notes") or [])[:4]],
        "counts": {"bodies": len(bodies), "screws": n_screws, "dims": len(dims),
                   "errors": sum(1 for x in issues if x["severity"] == "error" and not x["acknowledged"]),
                   "warnings": sum(1 for x in issues if x["severity"] != "error" or x["acknowledged"])},
        "paths": {k: sum(1 for r in rows.values() if r["path"] == k) for k in ("spec", "toolbox", "template", "ai")},
        "ms": {"scene": _r((time.perf_counter() - t0) * 1000, 1)},
    }
    return out


def _depth(items: dict[str, Any], side: dict[str, Any], n: list[float], plane: float, sgn: int) -> float:
    """How far one side's part reaches from the joint plane along ``sgn`` x the joint normal (0 when unknown)."""
    from aicad.office import frames

    it = items.get(side.get("item"))
    if not it:
        return 0.0
    cps = it.get("copies") or []
    c = int(side.get("copy") or 0)
    if c >= len(cps):
        return 0.0
    R = frames.item_rotation(it.get("ax") or "z", float(it.get("rot") or 0))
    half = _half_world(R, [float(v) for v in it.get("size") or [0, 0, 0]])
    k = max(range(3), key=lambda i: abs(n[i]))
    s = 1.0 if n[k] >= 0 else -1.0
    far = float(cps[c][k]) + sgn * s * half[k]
    return max(0.0, (far - plane) * sgn * s)


def _bounds(bodies: list[dict[str, Any]]) -> tuple[list[float] | None, list[float] | None]:
    """World box of the bodies from their primitives: boxes by their corners, round bodies exactly (a disc of radius
    r about a unit axis a reaches r sqrt(1 - a_i^2) along program axis i)."""
    if not bodies:
        return None, None
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for b in bodies:
        g, k, T = b["g"], b["kind"], b["T"]
        if k in ("box", "key"):
            e = [float(x) / 2 for x in g["s"]]
            for x in (-e[0], e[0]):
                for y in (-e[1], e[1]):
                    for z in (-e[2], e[2]):
                        for i in range(3):
                            w = T[4 * i] * x + T[4 * i + 1] * y + T[4 * i + 2] * z + T[4 * i + 3]
                            lo[i], hi[i] = min(lo[i], w), max(hi[i], w)
            continue
        if k == "shaft":
            segs = [(float(s[0]), float(s[1]), float(s[2]) / 2) for s in g.get("segs") or []]
        elif k == "screw":
            segs = [(0.0, float(g["L"]), float(g["d"]) / 2),
                    (float(g["L"]), float(g["L"]) + float(g["head_h"]), float(g["head_d"]) / 2)]
        else:
            r = float({"gear": g.get("tip"), "bearing": g.get("D"), "ring": g.get("D")}.get(k) or g.get("d") or 0) / 2
            hl = float(g.get("width") or g.get("B") or g.get("s") or g.get("L") or 0) / 2
            segs = [(-hl, hl, r)]
        a = [T[2], T[6], T[10]]
        for z0, z1, r in segs:
            for i in range(3):
                rad = r * math.sqrt(max(0.0, 1 - a[i] * a[i]))
                for z in (z0, z1):
                    c = T[4 * i + 2] * z + T[4 * i + 3]
                    lo[i], hi[i] = min(lo[i], c - rad), max(hi[i], c + rad)
    return [_r(x) for x in lo], [_r(x) for x in hi]


# ----------------------------------------------------------------------------- what the API serves
def for_program(doc: dict[str, Any], plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """The preview for a program as it stands: its approved (or draft) interfaces once they exist, else its plan (or
    the plan review's unsaved edits in ``plan``) laid out exactly as approval will lay it out."""
    t0 = time.perf_counter()
    has_icd = bool(doc.get("icd")) and bool(doc.get("skeleton"))
    if has_icd and plan is None:
        skel, ifs, d2, notes, state = doc["skeleton"], doc["icd"]["interfaces"], doc, [], "icd"
        t1 = time.perf_counter()
    else:
        d2, skel, ifs, notes = plan_layout(doc, plan)
        state = "edited" if plan is not None else "plan"
        t1 = time.perf_counter()
    paths = build_paths(d2, skel, ifs)
    t2 = time.perf_counter()
    out = scene(skel, ifs, plan=d2.get("plan"), paths=paths, notes=notes)
    out["state"] = state
    out["icd_version"] = (doc.get("icd") or {}).get("version") if state == "icd" else None
    out["icd_status"] = (doc.get("icd") or {}).get("status") if state == "icd" else None
    out["ms"].update(layout=_r((t1 - t0) * 1000, 1), paths=_r((t2 - t1) * 1000, 1),
                     total=_r((time.perf_counter() - t0) * 1000, 1))
    return out


def compare(doc: dict[str, Any], key: str) -> dict[str, Any]:
    """Before / after of a program revision: an applied revision (``R-…`` id: its snapshot, then the next revision's
    snapshot or the program now) or one Archie proposes (a supervisor log entry waiting for an answer: the candidate,
    computed and not applied)."""
    from aicad.office import revision

    revs = list(doc.get("revisions") or [])
    e = next((x for x in (doc.get("supervisor") or {}).get("log") or [] if x.get("id") == key), None)
    if e is not None and (e.get("undo") or {}).get("kind") == "revision":  # Archie's applied revision: its record
        key = str(e["undo"].get("id") or key)
    k = next((i for i, r in enumerate(revs) if r.get("id") == key), None)
    if k is not None:
        rev = revs[k]
        if rev.get("status") != "applied":
            raise OfficeInputError("This revision was undone: there is no after state to show.")
        snap = rev.get("snapshot") or {}
        if not snap.get("skeleton") or not (snap.get("icd") or {}).get("interfaces"):
            raise OfficeInputError("This revision has no layout to compare.")
        nxt = next((r for r in revs[k + 1:] if r.get("status") == "applied" and r.get("snapshot")), None)
        after_doc = nxt["snapshot"] if nxt else doc
        before = _scene_of(snap)
        after = _scene_of(after_doc)
        title = f"{rev['id']}: ICD v{rev.get('icd_from')} to v{rev.get('icd_to')}"
    else:
        act = (e or {}).get("action") or {}
        if not e or act.get("tool") != "revise_program" or e.get("status") != "asking":
            raise OfficeInputError("No revision with that id.")
        cand = revision.candidate(doc, act.get("changes") or act.get("ops") or [])
        before = _scene_of(doc)
        d2 = {**doc, "plan": cand["plan"], "items": cand["items"], "skeleton": cand["skeleton"],
              "icd": {**(doc.get("icd") or {}), "interfaces": cand["interfaces"]}}
        after = _scene_of(d2)
        title = str(e.get("title") or "Proposed revision")
    return {"title": title, "before": before, "after": after}


def _scene_of(d: dict[str, Any]) -> dict[str, Any]:
    skel, ifs = d["skeleton"], (d.get("icd") or {}).get("interfaces") or []
    full = {**d, "tickets": d.get("tickets") or []}
    out = scene(skel, ifs, plan=d.get("plan"), paths=build_paths(full, skel, ifs))
    out["state"] = "icd"
    out["icd_version"] = (d.get("icd") or {}).get("version")
    return out
