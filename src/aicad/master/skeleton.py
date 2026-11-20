"""A measured master model as the Design Office's skeleton and ICD (WORKLIST 50).

``build(measured, parts, brief, overrides)`` returns ``(skeleton, interfaces)`` in exactly the format
``office.icd.build`` and ``graph.layout.build`` produce, so the ICD gate, the direct builder, Gage, Fitz, revision and
the supervisor read it unchanged. Positions are not solved here: they are where the master bodies sat. Rules:

* **Frame.** The base body (a name that reads as a base, frame, lower shell or housing; else the body lowest on Z,
  then the largest) has datum A on the top of its envelope, its centre on X and Y at the origin; +Z up.
* **Items.** One item per designed part, one copy per body ("Leg #2"); the envelope is the body's box, the copy's
  position its centre (a part is modelled centred in its own frame, as everywhere in the office). An open pocket (an L
  bracket's inside corner) becomes the item's ``cavity`` with ``open_through`` (holes may open into it).
* **Interfaces.** A planar contact with holes across it is a ``hole_pattern``: the side with tap-drill holes is side a
  (tapped, blind, its measured depth), the clearance side b; both clearance is a through bolt (side a the one nearer
  the base); the fastener size from the tap drill (ISO 2306) or the clearance (ISO 273), the planned screw line of
  that size as the fastener item. A planar contact with no holes is a ``face`` (seating face). A bore on a pin of a
  turned part is a ``shaft_bore`` (H7/h6 when the master shows no gap, H7/g6 otherwise). Locating spigots between two
  blocks are kept in the notes, not as interfaces (a block carries no boss feature).
* **Honesty.** Every measurement finding is on the skeleton: overlaps, bodies that touch nothing or are not connected
  to the base, bodies that match no planned part, planned parts with no body, copies that differ, all errors at the
  gate (``conflicts``); edge or point touches, faces off the axes and lone fastener holes are warnings (``findings``).
* **Design graph.** ``graph(...)`` writes what was measured back as a design graph (components with their measured
  envelopes, bolted joints with their screws, seats, fits), source "layout" with the note "measured from the master
  model", for the plan review and the record.
"""

from __future__ import annotations

import math
import re
from collections import deque
from typing import Any

from aicad.office import icd

PLANE = icd.PLANE
AXI = icd.AXIS_INDEX
SIZE_TOL = 0.05
_BASE = re.compile(r"\bbase\b|\bframe\b|chassis|\blower\b|\bbottom\b|housing|\bbody\b|\bmain\b", re.IGNORECASE)
_SCREWY = re.compile(r"screw|bolt|cap screw|shcs|\bM\d", re.IGNORECASE)


def _r2(x: float) -> float:
    return icd._r2(float(x))


def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().split())


def _m_of(text: str) -> int | None:
    m = re.search(r"\bM(\d{1,2})(?=\b|\s*[x×X]\s*\d)", text or "")  # "M3", "M3x12", "M3 x 12"
    return int(m.group(1)) if m else None


def _tap_m(d: float) -> int | None:
    best = min(icd.TAP_DRILL.items(), key=lambda kv: abs(kv[1] - d))
    return best[0] if abs(best[1] - d) <= 0.15 else None


def _clear_m(d: float) -> int | None:
    best = min(icd.CLEARANCE.items(), key=lambda kv: abs(kv[1] - d))
    return best[0] if abs(best[1] - d) <= 0.15 else None


class _Build:
    def __init__(self, m: dict[str, Any], parts: list[dict[str, Any]], brief: str, ov: dict[str, Any] | None):
        self.m, self.parts, self.brief = m, parts, brief
        self.ov = ov or {}
        self.iov: dict[str, dict[str, Any]] = self.ov.get("items") or {}
        self.fov: dict[str, dict[str, Any]] = self.ov.get("interfaces") or {}
        self.conflicts: list[dict[str, Any]] = []
        self.findings: list[dict[str, Any]] = []
        self.notes: list[str] = []
        self.ifs: list[dict[str, Any]] = []
        self.by_pid = {p["id"]: p for p in parts}

    # ------------------------------------------------------------------ findings
    def err(self, text: str, items: list[str] | None = None, bodies: list[str] | None = None) -> None:
        self.conflicts.append({"text": "Master model: " + text, "parts": list(bodies or []), "connections": [],
                               "items": list(items or [])})

    def warn(self, code: str, text: str, items: list[str] | None = None) -> None:
        self.findings.append({"code": code, "severity": "warning", "text": "Master model: " + text,
                              "items": list(items or []), "interfaces": []})

    # ------------------------------------------------------------------ 1. bodies to plan parts
    def match(self) -> None:
        designed = {_norm(p["name"]): p for p in self.parts if p["family"] != "standard"}
        standard = {_norm(p["name"]): p for p in self.parts if p["family"] == "standard"}
        self.bodies = self.m["bodies"]
        self.item_of: dict[int, tuple[str, int]] = {}   # body index -> (item id, copy)
        self.copies: dict[str, list[int]] = {}           # item id -> body indexes by copy
        self.ignored: list[str] = []
        for k, b in enumerate(self.bodies):
            key = _norm(b["name"])
            p = designed.get(key)
            if p is None:
                p = next((q for n, q in designed.items() if n and (n in key or key in n)), None)
            if p is None:
                if key in standard or any(n and (n in key or key in n) for n in standard):
                    self.ignored.append(b["label"])
                    continue
                self.err(f"the body {b['label']} matches no part of the plan. Name each body after its planned part "
                         "(copies \"Name #2\").", bodies=[b["label"]])
                continue
            lst = self.copies.setdefault(p["id"], [])
            lst.append(k)
        for pid, ks in self.copies.items():
            ks.sort(key=lambda k: self.bodies[k]["copy"])
            want = icd.ncopies_quiet(self.by_pid[pid])
            if len(ks) != want:
                self.err(f"{self.by_pid[pid]['name']} is planned {want} time(s) but the master has {len(ks)} "
                         "bodies for it.", [pid], [self.bodies[k]["label"] for k in ks])
            s0 = self.bodies[ks[0]]["size"]
            for k in ks[1:]:
                if any(abs(a - b) > SIZE_TOL for a, b in zip(self.bodies[k]["size"], s0, strict=True)):
                    self.err(f"the copies of {self.by_pid[pid]['name']} differ in size ({s0} and "
                             f"{self.bodies[k]['size']}): copies are one part design.", [pid],
                             [self.bodies[k]["label"]])
            for c, k in enumerate(ks):
                self.item_of[k] = (pid, c)
        for p in self.parts:
            if p["family"] != "standard" and p["id"] not in self.copies:
                self.err(f"{p['name']} is planned but has no body in the master model.", [p["id"]])
        if self.ignored:
            self.notes.append("Bought-out parts modelled in the master (" + ", ".join(self.ignored[:4])
                              + ") are not measured as parts: the joints place them.")

    # ------------------------------------------------------------------ 2. base and frame
    def frame(self) -> None:
        cands = sorted(self.copies, key=lambda pid: (
            0 if _BASE.search(self.by_pid[pid]["name"]) and not re.search(r"\b(?:upper|top)\b", self.by_pid[pid]["name"],
                                                                          re.IGNORECASE) else 1,
            round(self.bodies[self.copies[pid][0]]["min"][2], 3), -self.bodies[self.copies[pid][0]]["volume"]))
        self.base = cands[0] if cands else None
        if self.base is None:
            self.o = [0.0, 0.0, 0.0]
            return
        b = self.bodies[self.copies[self.base][0]]
        self.o = [b["centre"][0], b["centre"][1], b["max"][2]]

    def P(self, p: list[float]) -> list[float]:
        return [_r2(p[k] - self.o[k]) for k in range(3)]

    def P2(self, ax: str, a2: list[float]) -> list[float]:
        i, j = PLANE[ax]
        return [_r2(a2[0] - self.o[i]), _r2(a2[1] - self.o[j])]

    def T(self, ax: str, t: float) -> float:
        return _r2(t - self.o[AXI[ax]])

    # ------------------------------------------------------------------ 3. the joint tree (from the base)
    def tree(self) -> None:
        adj: dict[int, set[int]] = {}
        pairs = [(c["a"], c["b"]) for c in self.m["contacts"]]
        pairs += [(x, y) for pn in self.m.get("pins") or [] for x in pn["bodies"] for y in pn["bodies"] if x < y]
        for a, b in pairs:
            if a in self.item_of and b in self.item_of:
                adj.setdefault(a, set()).add(b)
                adj.setdefault(b, set()).add(a)
        self.depth: dict[int, int] = {}
        self.parent: dict[int, int | None] = {}
        if self.base is None:
            return
        root = self.copies[self.base][0]
        q = deque([root])
        self.depth[root], self.parent[root] = 0, None
        while q:
            k = q.popleft()
            for n in sorted(adj.get(k, ())):
                if n not in self.depth:
                    self.depth[n], self.parent[n] = self.depth[k] + 1, k
                    q.append(n)
        touched = {k for c in self.m["contacts"] for k in (c["a"], c["b"])} | \
            {k for pn in self.m.get("pins") or [] for k in pn["bodies"]}
        for k, (pid, _c) in self.item_of.items():
            if k in self.depth or k not in touched:
                continue  # (touching nothing is the measurement's own finding)
            self.err(f"{self.bodies[k]['label']} is not connected to the {self.by_pid[self.base]['name']} through any "
                     "joint: it would not be assembled with the rest.", [pid], [self.bodies[k]["label"]])

    # ------------------------------------------------------------------ 4. items
    def items(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for p in self.parts:
            pid = p["id"]
            if pid not in self.copies:
                continue
            ks = self.copies[pid]
            b0 = self.bodies[ks[0]]
            size = [float(x) for x in b0["size"]]
            o = self.iov.get(pid) or {}
            resized = False
            for n, key in enumerate(("L", "W", "H")):  # an envelope resized at the gate (grown around its centre)
                if o.get(key):
                    resized = resized or abs(float(o[key]) - size[n]) > SIZE_TOL
                    size[n] = float(o[key])
            par = self.parent.get(ks[0])
            it: dict[str, Any] = {"name": p["name"], "role": "block", "shape": "box", "size": [_r2(x) for x in size],
                                  "sub": p["sub"], "parent": self.item_of[par][0] if par is not None else None,
                                  "copies": [self.P(self.bodies[k]["centre"]) for k in ks], "qty": p["qty"],
                                  "source": "master"}
            pk = b0.get("pocket")
            if pk and not resized:
                c = b0["centre"]
                it["cavity"] = {"kind": "pocket", "min": [_r2(pk["min"][k] - c[k]) for k in range(3)],
                                "max": [_r2(pk["max"][k] - c[k]) for k in range(3)],
                                "open_through": bool(pk.get("open")), "open": list(pk.get("open") or []),
                                "note": "Open pocket of the master body (keep it clear: the mating part sits there)."}
            out[pid] = it
        return out

    # ------------------------------------------------------------------ 5. interfaces
    def add(self, kind: str, a: tuple[int, int], b: tuple[int, int], data: dict[str, Any], datums: list[str],
            label: str) -> None:
        iid = f"IF-{len(self.ifs) + 1:02d}"
        o = self.fov.get(iid) or {}

        def side(k: int) -> dict[str, Any]:
            pid, c = self.item_of[k]
            n = len(self.copies[pid])
            return {"item": pid, "copy": c, "name": self.by_pid[pid]["name"] + (f" #{c + 1}" if n > 1 else "")}

        sa, sb = side(a[0]), side(b[0])
        f = {"id": iid, "kind": kind, "name": f"{sb['name']} ↔ {sa['name']}: {label}", "a": sa, "b": sb,
             "datums": datums, "data": data, "edited": sorted(o)}
        self.ifs.append(f)

    def nxt(self) -> dict[str, Any]:
        return self.fov.get(f"IF-{len(self.ifs) + 1:02d}") or {}

    def _fastener_item(self, m: int, count: int) -> str | None:
        std = [p for p in self.parts if p["family"] == "standard" and _SCREWY.search(p["name"] + " " + p["description"])]
        sized = [p for p in std if _m_of(p["name"]) == m or (_m_of(p["name"]) is None and _m_of(p["description"]) == m)]
        pick = next((p for p in sized if int(p["qty"]) % max(1, count) == 0), None) or (sized[0] if sized else None)
        return pick["id"] if pick else None

    def _closer(self, i: int, j: int) -> bool:
        """True when body i is nearer the base than body j (side a of a through-bolted or seated joint)."""
        return (self.depth.get(i, 99), i) <= (self.depth.get(j, 99), j)

    def interfaces(self) -> None:
        for c in self.m["contacts"]:
            i, j = c["a"], c["b"]
            if i not in self.item_of or j not in self.item_of:
                continue
            if c["kind"] == "planar" and c.get("bolts"):
                self._bolted(c, i, j)
            elif c["kind"] == "planar":
                a, b = (i, j) if self._closer(i, j) else (j, i)
                sign = c["sign_a"] if a == i else -c["sign_a"]
                o = self.nxt()
                data = {"plane_z": self.T(c["axis"], c["t"]), "normal": [float(sign) * x for x in icd.unit(c["axis"])],
                        "flatness": float(o.get("flatness") or icd.FLATNESS),
                        "position_tol": float(o.get("position_tol") or icd.POS_TOL)}
                if c["axis"] != "z":
                    data["ax"] = c["axis"]
                pas = self._passages(c, a == i)
                if pas:
                    data["passages"] = pas
                self.add("face", (a, 0), (b, 0), data, ["A"], "seating face (measured)")
            elif c["kind"] == "coaxial":
                self._fit(c, i, j)
        for pn in self.m.get("pins") or []:
            self._pin(pn)

    def _pin(self, pn: dict[str, Any]) -> None:
        """A pivot axis through two or more bodies: the planned pin (ISO 8734 dowel) through all of them, or a pivot
        bolt; the body nearest the base carries it (side a)."""
        ks = sorted((k for k in pn["bodies"] if k in self.item_of), key=lambda k: (self.depth.get(k, 99), k))
        if len(ks) < 2:
            return
        ax = pn["axis"]
        std = [p for p in self.parts if p["family"] == "standard"]
        pin = next((p for p in std if re.search(r"\bpin\b|dowel|pivot|hinge", p["name"], re.IGNORECASE)
                    and not _SCREWY.search(p["name"])), None)
        lo, hi = self.T(ax, pn["span"][0]), self.T(ax, pn["span"][1])
        for k in ks[1:]:
            o = self.nxt()
            if pin is not None:
                data = {"d": _r2(pn["d"]), "fit": str(o.get("fit") or "H7/h6"), "count": 1,
                        "positions": [self.P2(ax, pn["at"])], "plane_z": _r2((lo + hi) / 2), "ax": ax,
                        "length": _r2(hi - lo), "pin_item": pin["id"], "joint": None, "standard": "ISO 8734",
                        "position_tol": icd.POS_TOL, "measured": True}
                self.add("dowel", (ks[0], 0), (k, 0), data, ["A", "B", "C"],
                         f"pin Ø{pn['d']:g} x {hi - lo:g} (measured pivot axis)")
            else:
                self.warn("pivot_unplanned", f"a Ø{pn['d']:g} hole line runs through "
                          + ", ".join(self.bodies[x]["label"] for x in ks)
                          + " (a pivot axis) but the plan has no pin for it.", [self.item_of[x][0] for x in ks])
                return

    def _passages(self, c: dict[str, Any], a_is_i: bool) -> list[dict[str, Any]]:
        """Openings across a joint (a pilot bore in a window, a shaft passage): both holes are ICD features, so the
        detailed parts (and the placeholders) keep them open."""
        out = []
        for w in c.get("ways") or []:
            da, db = (w["d_a"], w["d_b"]) if a_is_i else (w["d_b"], w["d_a"])
            out.append({"at": self.P2(c["axis"], w["at"]), "d_a": _r2(da), "d_b": _r2(db)})
        return out

    def _bolted(self, c: dict[str, Any], i: int, j: int) -> None:
        bolts = c["bolts"]
        da = [x["a"]["d"] for x in bolts]
        db = [x["b"]["d"] for x in bolts]
        blind_a = all(not x["a"]["through"] for x in bolts)
        blind_b = all(not x["b"]["through"] for x in bolts)
        tap_a = all(_tap_m(d) for d in da) and blind_a
        tap_b = all(_tap_m(d) for d in db) and blind_b
        if tap_a and not tap_b:
            a, b, ta, cl = i, j, "a", "b"
        elif tap_b and not tap_a:
            a, b, ta, cl = j, i, "b", "a"
        else:
            a, b = (i, j) if self._closer(i, j) else (j, i)
            ta, cl = None, ("b" if b == j else "a")
        sign = c["sign_a"] if a == i else -c["sign_a"]
        d_clear = max(x[cl]["d"] for x in bolts)
        m = _clear_m(d_clear) or icd.bolt_for_hole(d_clear)
        if ta is not None:
            mt = _tap_m(bolts[0][ta]["d"])
            if mt and mt != m:
                self.warn("thread_mismatch", f"the tapped holes (M{mt}) and the clearance holes (Ø{d_clear:g}, M{m}) "
                          f"of the joint at {c['axis'].upper()} = {c['t']:g} disagree; M{mt} is used.",
                          [self.item_of[a][0], self.item_of[b][0]])
                m = mt
        o = self.nxt()
        m = int(o.get("fastener") or m)
        m = m if m in icd.CLEARANCE else icd.bolt_for_hole(d_clear)
        d = float(o.get("d") or d_clear)
        pts = [self.P2(c["axis"], x["at"]) for x in bolts]
        tapped = None
        if ta is not None:
            depth = min(x[ta]["depth"] for x in bolts)
            tapped = {"d": icd.TAP_DRILL[m], "depth": _r2(depth), "thread": f"M{m}"}
        count = len(pts)
        data: dict[str, Any] = {
            "fastener": f"M{m}", "fastener_size": m, "fastener_item": self._fastener_item(m, count), "count": count,
            "d": _r2(d), "pattern": "grid" if count >= 4 else "linear", "inset": None,
            "plane_z": self.T(c["axis"], c["t"]), "normal": [float(sign) * x for x in icd.unit(c["axis"])],
            "positions": pts, "through": tapped is None, **({"tapped": tapped} if tapped else {}),
            "flatness": float(o.get("flatness") or icd.FLATNESS), "position_tol": float(o.get("position_tol") or icd.POS_TOL),
            "measured": True}
        if c["axis"] != "z":
            data["ax"] = c["axis"]
        pas = self._passages(c, a == i)
        if pas:
            data["passages"] = pas
        cb = self._counterbore(c, bolts, cl, b)
        if cb:
            data["counterbore"] = cb
        self._screw_fits(c, bolts, m, ta, cl, a, b, cb)
        if data["fastener_item"] is None:
            self.warn("no_fastener", f"no planned screw or bolt is M{m}: the {count} hole(s) of this joint have no "
                      "fastener line in the plan.", [self.item_of[a][0], self.item_of[b][0]])
        self.add("hole_pattern", (a, 0), (b, 0), data, ["A", "B", "C"],
                 f"{count} x M{m} {'into tapped holes' if tapped else 'through bolts'} (measured)")

    def _counterbore(self, c: dict[str, Any], bolts: list[dict[str, Any]], cl: str, b: int) -> dict[str, Any] | None:
        """The counterbore over the clearance holes of the head side (the same at every hole), measured: a larger
        coaxial blind hole that continues the clearance hole away from the joint face. {"d", "depth", "length"}
        (length: the head side's whole thickness at the hole), else None."""
        found = []
        t = float(c["t"])
        for x in bolts:
            h = x[cl]
            far = h["hi"] if abs(h["lo"] - t) <= 0.05 else h["lo"]
            cb = next((g for g in self.bodies[b]["holes"] if g["axis"] == h["axis"] and g["d"] > h["d"] + 0.2
                       and math.dist(g["at"], h["at"]) <= 0.05 and min(abs(g["lo"] - far), abs(g["hi"] - far)) <= 0.05),
                      None)
            if cb is None:
                return None
            found.append((cb["d"], cb["depth"], h["depth"] + cb["depth"]))
        if not found or len(set(found)) != 1:
            return None
        d, depth, length = found[0]
        return {"d": _r2(d), "depth": _r2(depth), "length": _r2(length)}

    def _screw_fits(self, c: dict[str, Any], bolts: list[dict[str, Any]], m: int, ta: str | None, cl: str, a: int,
                    b: int, cb: dict[str, Any] | None = None) -> None:
        """Does a standard screw fit the joint as modelled (Fitz's rule: ISO lengths, 2 x d engagement in an unknown
        material)? The clamp is the clearance hole's own length (a counterbore shortens it). Said at the gate."""
        from aicad.assembly import fasteners

        grip = min(float(x[cl]["depth"]) for x in bolts)
        try:
            if ta is not None:
                depth = min(float(x[ta]["depth"]) for x in bolts)
                r = fasteners.tapped_length(m, grip, True, depth, True, None)
                why = f"a {grip:g} mm clamp into {depth:g} mm of tapped thread"
            else:
                grip += min(float(x["a" if cl == "b" else "b"]["depth"]) for x in bolts)
                r = fasteners.through_length(m, grip, True, True)
                why = f"a {grip:g} mm clamp with washers and a nut"
        except (KeyError, ValueError):
            return
        if r.get("L") is None:
            self.warn("screw_length", f"no standard M{m} length fits {why} at {c['axis'].upper()} = {c['t']:g} "
                      f"(needs {r.get('L_min')} mm" + (f", at most {r['L_max']} mm" if r.get("L_max") else "")
                      + "): deepen the tapped holes or shorten the clamp, else the screws can't be fitted.",
                      [self.item_of[a][0], self.item_of[b][0]])

    def _fit(self, c: dict[str, Any], i: int, j: int) -> None:
        bore, pin = (i, j) if c["bore"] == "a" else (j, i)
        pin_part = self.by_pid[self.item_of[pin][0]]
        if pin_part["family"] != "turned":
            self.notes.append(f"{self.bodies[pin]['label']} locates in a Ø{c['d_bore']:g} bore of "
                              f"{self.bodies[bore]['label']} (a spigot between two blocks: kept as a note; the joint "
                              "is carried by the faces and bolts).")
            return
        o = self.nxt()
        fit = str(o.get("fit") or ("H7/h6" if c["gap"] <= icd.POS_TOL else "H7/g6"))
        ax = c["axis"]
        lo, hi = self.T(ax, c["span"][0]), self.T(ax, c["span"][1])
        data = {"d": _r2(c["d_pin"]), "fit": fit if fit in icd.FITS else "H7/h6", "length": _r2(hi - lo),
                "axis": self.P2(ax, c["line"]), "z": [lo, hi], "flush_z": None, "position_tol": icd.POS_TOL,
                "measured": True}
        if ax != "z":
            data["ax"] = ax
        self.add("shaft_bore", (bore, 0), (pin, 0), data, ["A", "B", "C"], "bore on pin (measured)")

    # ------------------------------------------------------------------ 6. measurement findings
    def measured_findings(self) -> None:
        lab = {b["label"]: k for k, b in enumerate(self.bodies)}
        for f in self.m.get("findings") or []:
            items = sorted({self.item_of[lab[n]][0] for n in f.get("bodies") or [] if lab.get(n) in self.item_of})
            if f.get("severity") == "error":
                self.err(f["text"], items, list(f.get("bodies") or []))
            else:
                self.warn(f.get("code") or "master", f["text"], items)

    # ------------------------------------------------------------------ the run
    def run(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        self.match()
        self.frame()
        self.tree()
        items = self.items()
        self.interfaces()
        self.measured_findings()
        lo, hi = [math.inf] * 3, [-math.inf] * 3
        for it in items.values():
            for c in it["copies"]:
                for k in range(3):
                    lo[k] = min(lo[k], c[k] - it["size"][k] / 2)
                    hi[k] = max(hi[k], c[k] + it["size"][k] / 2)
        if not items:
            lo = hi = [0.0, 0.0, 0.0]
        base_name = self.by_pid[self.base]["name"] if self.base else "base"
        csys = (f"Origin at the centre of the top of the {base_name} envelope (datums A, B, C); +Z up; X and Y as in "
                "the master model, which every part was measured from.")
        datums = [{"id": "A", "kind": "plane", "name": f"{base_name} top (envelope)", "origin": [0, 0, 0],
                   "normal": [0, 0, 1]},
                  {"id": "B", "kind": "plane", "name": "Mid-plane XZ", "origin": [0, 0, 0], "normal": [0, 1, 0]},
                  {"id": "C", "kind": "plane", "name": "Mid-plane YZ", "origin": [0, 0, 0], "normal": [1, 0, 0]}]
        n_b = sum(1 for f in self.ifs if f["kind"] == "hole_pattern")
        n_f = sum(1 for f in self.ifs if f["kind"] == "face")
        n_s = sum(1 for f in self.ifs if f["kind"] in ("shaft_bore", "dowel"))
        head = (f"Laid out from a master model: {len(self.item_of)} bodies in one coordinate system, each part placed "
                f"where its body sat; the interfaces are measured from it ({n_b} bolted joint{'s' if n_b != 1 else ''}, "
                f"{n_f} seating face{'s' if n_f != 1 else ''}"
                + (f", {n_s} bore or pin fit{'s' if n_s != 1 else ''}" if n_s else "") + ").")
        self.notes.insert(0, head)
        parts_std = [{"item": p["id"], "name": p["name"], "qty": p["qty"], "sub": p["sub"]}
                     for p in self.parts if p["family"] == "standard"]
        skel: dict[str, Any] = {
            "units": "mm", "base": self.base, "layout": "block", "csys": csys, "datums": datums, "axes": [],
            "envelope": {"min": [_r2(x) for x in lo], "max": [_r2(x) for x in hi],
                         "size": [_r2(hi[k] - lo[k]) for k in range(3)]},
            "items": items, "notes": self.notes, "standard": parts_std, "solver": "master"}
        if self.conflicts:
            skel["conflicts"] = self.conflicts
        if self.findings:
            skel["findings"] = self.findings
        sep = sorted(i for i in (self.ov.get("separate") or {}) if i in items)
        if sep:
            skel["separate"] = sep
        return skel, self.ifs


def build(measured: dict[str, Any], parts: list[dict[str, Any]], brief: str = "",
          overrides: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    return _Build(measured, parts, brief, overrides).run()


def build_for_doc(doc: dict[str, Any], overrides: dict[str, Any] | None
                  ) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """The program's layout from its master model, or None (no master, or the plan doesn't take the master path)."""
    mm = ((doc.get("plan") or {}).get("master") or {})
    lp = (doc.get("plan") or {}).get("layout_path") or {}
    if lp.get("path") != "master" or not mm.get("measure"):
        return None
    return build(mm["measure"], icd.parts_from(doc), str(doc.get("brief") or ""), overrides)


# ----------------------------------------------------------------------------- what was measured, as a design graph
def graph(skel: dict[str, Any], ifs: list[dict[str, Any]], parts: list[dict[str, Any]], name: str, brief: str
          ) -> Any:
    """The measured layout written back as a design graph (plan review, record): components with their measured
    envelopes, bolted joints with their screws, seating faces, bore fits."""
    from aicad.graph import registry
    from aicad.graph.model import Component, Connection, DesignGraph, Param, slug

    note = "measured from the master model"
    g = DesignGraph(name=name, brief=brief, summary="Measured from the master model.", source="master")
    cid: dict[str, str] = {}
    for p in parts:
        k = registry.kind_from_name(p["name"])
        if p["family"] == "standard" and registry.COMPONENTS.get(k) and registry.COMPONENTS[k].family != "standard":
            k = "fastener" if _SCREWY.search(p["name"]) else "other"
        if p["family"] != "standard" and registry.COMPONENTS.get(k) and registry.COMPONENTS[k].family == "standard":
            k = "other"
        c = Component(id=g.new_id(slug(p["name"]) or "part"), kind=k if k in registry.COMPONENTS else "other",
                      name=p["name"], qty=max(1, min(500, int(p["qty"]))), group=str(p.get("sub") or ""))
        it = skel["items"].get(p["id"])
        if it:
            for key, v in zip(("L", "W", "H"), it["size"], strict=True):
                c.params[key] = Param(value=float(v), source="layout", note=note)
        m = _m_of(p["name"])
        if p["family"] == "standard" and m:
            c.params["size"] = Param(value=m, source="plan", note="from the plan")
        g.components.append(c)
        cid[p["id"]] = c.id
    kinds = {"hole_pattern": "bolted_joint", "face": "mounted_on", "shaft_bore": "hub_fit", "dowel": "pin_joint"}
    for f in ifs:
        k = kinds.get(f["kind"])
        if k is None or f["a"]["item"] not in cid or f["b"]["item"] not in cid:
            continue
        d = f["data"]
        via = [cid[d[k]] for k in ("fastener_item", "pin_item") if d.get(k) in cid]
        x = Connection(id=g.next_connection_id(), kind=k, host=cid[f["a"]["item"]], guest=cid[f["b"]["item"]], via=via)
        if f["kind"] == "hole_pattern":
            x.params["count"] = Param(value=int(d["count"]), source="layout", note=note)
            x.params["fastener"] = Param(value=str(d["fastener"]), source="layout", note=note)
        if f["kind"] == "shaft_bore":
            x.params["fit"] = Param(value=str(d["fit"]), source="layout", note=note)
        if not any(y.kind == x.kind and y.host == x.host and y.guest == x.guest for y in g.connections):
            g.connections.append(x)
    g.notes.append("Measured from the master model: positions and joints come from one coordinate system.")
    return g
