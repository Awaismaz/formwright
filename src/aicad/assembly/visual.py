"""Visual assembly check (advisory): Claude looks at the 4-view picture of an assembly the way an engineer glances at
it before measuring anything, against the intended relations in plain words, and says whether it *looks* assembled.

Three layers, cheapest first:
  1. **Quick placement checks** (deterministic, milliseconds, no kernel): from each instance's placement and part
     box only. Parts that touch nothing (a row on the floor, a bearing floating off its shaft) and recognised gear
     pairs whose axes, centre distance or mid-planes don't agree with m (z1 + z2) / 2. These measure what a picture
     can't show reliably (a 5 mm offset) and catch what the exact interference check can't (parts lying apart don't
     interfere: the founder's "parts on the floor" passed it with 0 clashes).
  2. **The visual check** (one vision call, metered, small cap): ``looks_assembled`` / ``looks_wrong`` / ``unsure``, a
     status per relation and the visible problems. Advisory: it is labelled as a visual check and never accepts
     geometry on its own (CLAUDE.md: acceptance is deterministic checks).
  3. **The exact interference check** (B-rep booleans through the pair cache): what the policy below schedules.

Policy (``decide``, one setting ``FW_ASSEMBLY_VISUAL_CHECK``, default on, PD-73):
  * quick checks find a problem -> stop with that reason (measured, whatever the picture says);
  * the picture looks wrong -> run the exact check on the flagged parts first; stop when a measurement confirms it,
    otherwise report the concern as unconfirmed and carry on;
  * the picture looks assembled, every relation ok, quick checks clean -> the exact check is still run, but in the
    background (advisory) when it would take longer than looking did; when it is quick (cached pairs) it stays inline
    because measuring is then both faster and more reliable;
  * unsure, no AI, or the setting off -> the exact check runs inline as before.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np

ROLE = "assembly_check"
CHECK_MAX_TOKENS = 15     # platform tokens: hard cap for one visual check (1 token = 0.01 USD of compute)
TOUCH_MM = 0.5            # boxes this close count as touching
MESH_TOL_MM = 0.5         # centre distance / mid-plane tolerance of a gear pair (vision can't see this)
# Measured 2026-11-19 (docs/reports/assembly-fix/asm-visual.md), warm assembly worker, uncached pair cache:
#   interference 0.02 s per placeholder pair, 0.17 s per Toolbox gear/shaft/bearing pair;
#   exact clearance ~1.8 s per near pair of real gears (a gear pair's flanks dominate);
#   loading the part snapshots into a worker ~5 s, a cold worker ~4 s more; a cached pair ~0.
#   One visual check (render ~1.3 s + one vision call): 15-40 s, median ~20 s.
INT_PAIR_S = 0.2
CLR_PAIR_S = 1.8
LOAD_S = 5.0
VISION_S = 20.0
VISION_MODEL = "haiku"    # the harness alias; the default (larger) model cost ~30 platform tokens a look, this ~2
VISION_EFFORT = "low"
VISION_TIMEOUT_S = 120.0  # a look never holds a step longer than this (one live look ran 400 s under load)
OVERALL = ("looks_assembled", "looks_wrong", "unsure")
STATUS = ("ok", "wrong", "unsure")
PROBLEM_KINDS = ("floating", "row", "interpenetration", "orientation", "missing", "other")

INSTRUCTIONS = """You are an assembly checker in a mechanical design office. You look at one picture of an \
assembly, the way an engineer glances at it before measuring anything, and say whether it looks assembled as \
intended.

The picture has four views: ISO (top left), FRONT looking along +Y (top right), TOP looking down (bottom left), \
RIGHT looking along -X (bottom right). Z is up. A grid is drawn on the floor at the lowest point of the assembly. \
Every item has its own colour and a number tag; the key at the top left lists the numbers (copies of one item share \
its number and colour). A housing that holds other parts is drawn see-through.

Judge only what the picture shows. For every intended relation say "ok", "wrong" or "unsure", with one short reason. \
Then list the problems you can see: parts floating in the air or apart from everything, parts lying apart in a row \
on the floor instead of assembled, parts passing through each other, a part turned the wrong way, an expected part \
missing. Say "unsure" when the views can't show it (an offset of a few millimetres, tooth contact, a hidden part). \
Never claim the assembly is correct, fits or can be made: this is a visual check only. Never mention files, tools \
or how you work.

Answer with exactly one fenced block and nothing after it:
```json
{"overall": "looks_assembled" | "looks_wrong" | "unsure",
 "relations": [{"id": "R1", "status": "ok" | "wrong" | "unsure", "reason": "short"}],
 "problems": [{"kind": "floating" | "row" | "interpenetration" | "orientation" | "missing" | "other",
               "items": [item numbers], "text": "short"}],
 "summary": "one sentence"}
```"""

_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n?```", re.DOTALL)


# ----------------------------------------------------------------------------- settings
def enabled() -> bool:
    """FW_ASSEMBLY_VISUAL_CHECK: "on" (default) or "off". Server configuration, never shown to users."""
    from aicad.platform.config import get_settings

    return get_settings().assembly_visual_check


# ----------------------------------------------------------------------------- relations in plain words
def _gear_of(it: dict[str, Any]) -> tuple[float, int] | None:
    m, z = it.get("module"), it.get("teeth")
    return (float(m), int(z)) if m and z else None


def _side_name(skel: dict[str, Any], side: dict[str, Any]) -> str:
    """A side of an interface in plain words: its own name (copies numbered), the item's or the standard part's name,
    never an internal id."""
    if side.get("name"):
        return str(side["name"])
    it = (skel.get("items") or {}).get(side.get("item"))
    if it:
        return str(it["name"])
    st = next((x for x in skel.get("standard") or [] if x.get("item") == side.get("item")), None)
    if st:
        return f"{st['name']} #{int(side.get('copy') or 0) + 1}" if int(st.get("qty") or 1) > 1 else str(st["name"])
    return "a part"


def _num(v: Any) -> str:
    return f"{v:g}" if isinstance(v, int | float) else str(v)


def relations_from_skeleton(skel: dict[str, Any], ifaces: list[dict[str, Any]], brief: str = "") -> list[dict[str, Any]]:
    """What the layout intends, in plain words: the gear meshes first (the brief's point), then the ICD's interfaces
    (bearings on their journals or in their seats, gears on their shafts, bolted joints), or (no interfaces) the
    parts' roles: gears mesh in pairs on parallel shafts at m (z1 + z2) / 2, every gear sits on a shaft, shafts run in
    their bearings, parts mount on the block they hang from."""
    kept = set(skel.get("separate") or [])  # parts the engineer kept separate: nothing to relate them to
    items = {i: it for i, it in (skel.get("items") or {}).items() if i not in kept}
    mesh: list[str] = []
    out: list[str] = []
    for f in ifaces:
        a, b = _side_name(skel, f["a"]), _side_name(skel, f["b"])
        d = f.get("data") or {}
        k = f["kind"]
        if k == "gear_mesh":
            mesh.append(f"{a} meshes with {b}: axes parallel, {_num(d.get('centre_distance', '?'))} mm apart "
                        "(m (z1 + z2) / 2), the two gears in one plane")
        elif k == "shaft_bore":
            out.append(f"{a} sits on {b} (the shaft passes through its bore)")
        elif k == "bearing_journal":  # side a: the shaft, side b: the bearing
            out.append(f"{b} sits on its journal on {a}")
        elif k == "bearing_seat":
            out.append(f"{a} carries {b} in {len(d.get('seats') or [])} bearing seat(s)")
        elif k == "hole_pattern":
            out.append(f"{a} is bolted to {b}")
        elif k == "key":
            out.append(f"{a} is keyed to {b}")
        elif k == "dowel":
            out.append(f"{a} is located on {b} by dowel pins")
        else:
            out.append(f"{a} sits on {b}")
    gears = [(i, it) for i, it in items.items() if it.get("role") == "gear"]
    if not mesh:  # the brief's intent even when the ICD has no mesh: a wrong ICD must not set the bar (live run)
        for k, (_i, g1) in enumerate(gears):
            for _j, g2 in gears[k + 1:]:
                ga, gb = _gear_of(g1), _gear_of(g2)
                if ga and gb and abs(ga[0] - gb[0]) < 1e-6 and g1.get("sub") == g2.get("sub"):
                    c = ga[0] * (ga[1] + gb[1]) / 2
                    mesh.append(f"{g1['name']} meshes with {g2['name']}: axes parallel, {c:g} mm apart "
                                "(m (z1 + z2) / 2), the two gears in one plane, each on its own shaft")
    shafts = [it["name"] for it in items.values() if it.get("role") == "shaft"]
    if not ifaces:
        if gears and shafts:
            out.append("each gear sits on its own shaft (" + ", ".join(shafts) + ")")
        blocks = [it["name"] for it in items.values() if it.get("role") == "block"]
        if blocks:
            out.append(f"the other parts mount on {blocks[0]}")
    journals = [f for f in ifaces if f["kind"] in ("bearing_journal", "bearing_seat")]
    if skel.get("layout") == "shaft_line" and len(shafts) > 1:
        out.insert(0, "each shaft runs in two bearings, one either side of its gear; the shafts are parallel and "
                      "nothing holds them but their bearings (no housing)")
    elif skel.get("layout") == "shaft_line" and shafts:  # one shaft's sub-assembly: no "parallel pair" to look for
        out.insert(0, f"{shafts[0]} runs in two bearings, one either side of its gear; nothing holds it but its "
                      "bearings (no housing)")
    elif not journals:
        for st in skel.get("standard") or []:
            nm = str(st.get("name") or "")
            if re.search(r"\bbearing|\b6[02]0\d\b", nm, re.IGNORECASE):
                out.append(f"{st.get('qty', 1)} × {nm} carry the shafts (typically two per shaft, one either side of "
                           "its gear)")
    out = mesh + out
    if not out and brief and not (kept and not items):  # a kit of separate parts: nothing is meant to be assembled
        out.append("the parts are assembled as the brief describes")
    return [{"id": f"R{k + 1}", "text": t} for k, t in enumerate(out[:12])]


def relations_from_doc(root: Path, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """What an Assembly Studio document intends: its mates (pair by pair, in words) and its recognised gear pairs."""
    from aicad.assembly import service

    names = service.human_names(doc)  # people read these lines
    by_pair: dict[tuple[str, str], set[str]] = {}
    for m in doc.get("mates") or []:
        a, b = m["a"]["inst"], m["b"]["inst"]
        if a == b or m.get("suppressed"):
            continue
        ia, ib = service._inst(doc, a), service._inst(doc, b)
        if ia.get("group") and ib.get("group"):
            continue  # inside one fastener stack
        by_pair.setdefault(tuple(sorted((a, b))), set()).add(m["type"])
    out: list[str] = []
    for (a, b), types in list(by_pair.items())[:10]:
        how = " and ".join(sorted(types))
        out.append(f"{names[a]} is mated to {names[b]} ({how})")
    for g in gear_pairs(root, doc):
        out.append(f"{names[g['a']]} meshes with {names[g['b']]}: axes parallel, {g['a_mm']:g} mm apart "
                   "(m (z1 + z2) / 2), the two gears in one plane")
    if not out:
        out.append("every part is assembled to the others (none lies apart)")
    return [{"id": f"R{k + 1}", "text": t} for k, t in enumerate(out[:12])]


# ----------------------------------------------------------------------------- quick placement checks
def _world_boxes(root: Path, doc: dict[str, Any]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    from aicad.assembly import service, xform

    parts = service._parts(root, doc)
    out = {}
    for i in doc["instances"]:
        if not i.get("visible", True) or (i.get("office") or {}).get("bin"):
            continue
        T = xform.from12(i["T"])
        x0, y0, z0, x1, y1, z1 = parts[i["part"]]["info"]["bbox"]
        P = np.array([xform.pt(T, (x, y, z)) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
        out[i["id"]] = (P.min(axis=0), P.max(axis=0))
    return out


def _groups(boxes: dict[str, tuple[np.ndarray, np.ndarray]], link: dict[str, str] | None = None) -> list[list[str]]:
    """Connected groups of touching boxes (fastener stacks count as one body through ``link``)."""
    ids = list(boxes)
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for k, a in enumerate(ids):
        la, ha = boxes[a]
        for b in ids[k + 1:]:
            lb, hb = boxes[b]
            if np.all(la <= hb + TOUCH_MM) and np.all(lb <= ha + TOUCH_MM):
                parent[find(a)] = find(b)
    for a, b in (link or {}).items():
        if a in parent and b in parent:
            parent[find(a)] = find(b)
    g: dict[str, list[str]] = {}
    for i in ids:
        g.setdefault(find(i), []).append(i)
    return sorted(g.values(), key=len, reverse=True)


def apart_findings(names: dict[str, str], groups: list[list[str]], on_floor: dict[str, bool]) -> list[dict[str, Any]]:
    """Plain findings from the touch groups: nothing touches (a row), or some parts apart from the rest."""
    if len(groups) <= 1:
        return []
    n = sum(len(g) for g in groups)
    if len(groups[0]) == 1 or len(groups) >= max(3, n - 1):
        floor = sum(1 for g in groups for i in g if on_floor.get(i))
        return [{"code": "row", "severity": "block", "items": [i for g in groups for i in g],
                 "text": f"The parts are not assembled: {len(groups)} of {n} parts touch nothing"
                         + (f" ({floor} of them stand on the floor side by side, like a row)" if floor >= 2 else "")
                         + "."}]
    out = []
    for g in groups[1:6]:
        what = ", ".join(names.get(i, i) for i in g[:4]) + ("…" if len(g) > 4 else "")
        out.append({"code": "floating", "severity": "block", "items": g,
                    "text": f"{what} {'touches' if len(g) == 1 else 'touch'} nothing in the rest of the assembly "
                            "(apart, or floating)."})
    return out


def gear_pairs(root: Path, doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Recognised spur gears (``info.component``) of equal module whose axes are parallel and close enough to be
    meant to mesh (centre distance under 1.2 m (z1 + z2) / 2): their measured centre distance and mid-plane offset."""
    from aicad.assembly import service, xform

    parts = service._parts(root, doc)
    gears = []
    for i in doc["instances"]:
        c = (parts[i["part"]].get("info") or {}).get("component") or {}
        p = c.get("params") or {}
        if c.get("kind") != "spur_gear" or not p.get("module") or not p.get("teeth"):
            continue
        T = xform.from12(i["T"])
        ax = xform.vec(T, c.get("axis") or (0, 0, 1))
        ax = ax / max(float(np.linalg.norm(ax)), 1e-12)
        mid = xform.pt(T, np.asarray(c.get("origin") or (0, 0, 0), dtype=float)
                       + np.asarray(c.get("axis") or (0, 0, 1), dtype=float) * float(p.get("face_width") or 0) / 2)
        gears.append((i["id"], float(p["module"]), int(p["teeth"]), ax, mid, float(p.get("face_width") or 0)))
    out = []
    for k, (a, ma, za, axa, ca, ba) in enumerate(gears):
        for b, mb, zb, axb, cb, bb in gears[k + 1:]:
            if abs(ma - mb) > 1e-6 or np.linalg.norm(np.cross(axa, axb)) > 1e-3:
                continue
            want = ma * (za + zb) / 2
            d = cb - ca
            axial = float(np.dot(d, axa))
            radial = float(np.linalg.norm(d - axial * axa))
            if radial > 1.2 * want:
                continue
            out.append({"a": a, "b": b, "a_mm": round(want, 3), "centre_mm": round(radial, 3),
                        "offset_mm": round(abs(axial), 3), "engaged_mm": round(max(0.0, min(ba, bb) - abs(axial)), 3),
                        "face_mm": min(ba, bb)})
    return out


def quick_doc(root: Path, doc: dict[str, Any]) -> dict[str, Any]:
    """The deterministic quick checks of an assembly document. {findings, seconds, gear_pairs}."""
    import time

    from aicad.assembly import service

    t0 = time.perf_counter()
    names = service.human_names(doc)  # people read these lines
    boxes = _world_boxes(root, doc)
    link = {}
    first: dict[str, str] = {}
    for i in doc["instances"]:
        if i.get("group") and i["id"] in boxes:
            g = i["group"]
            if g in first:
                link[i["id"]] = first[g]
            else:
                first[g] = i["id"]
    findings: list[dict[str, Any]] = []
    if len(boxes) >= 2:
        zmin = min(float(b[0][2]) for b in boxes.values())
        on_floor = {i: abs(float(b[0][2]) - zmin) <= TOUCH_MM for i, b in boxes.items()}
        findings += apart_findings(names, _groups(boxes, link), on_floor)
    gp = gear_pairs(root, doc)
    for g in [] if any(f["code"] == "row" for f in findings) else gp:  # a row says it all
        a, b = names[g["a"]], names[g["b"]]
        if abs(g["centre_mm"] - g["a_mm"]) > MESH_TOL_MM:
            findings.append({"code": "gear_centre", "severity": "block", "items": [g["a"], g["b"]],
                             "text": f"{a} and {b} are {g['centre_mm']:g} mm apart; to mesh they must be "
                                     f"{g['a_mm']:g} mm (m (z1 + z2) / 2)."})
        if g["offset_mm"] > MESH_TOL_MM:
            findings.append({"code": "gear_plane", "severity": "block", "items": [g["a"], g["b"]],
                             "text": f"{a} and {b} are {g['offset_mm']:g} mm apart along their axes: only "
                                     f"{g['engaged_mm']:g} of {g['face_mm']:g} mm face width is in mesh."})
    return {"findings": findings, "seconds": round(time.perf_counter() - t0, 4), "gear_pairs": gp}


def quick_skeleton(skel: dict[str, Any], ifaces: list[dict[str, Any]]) -> dict[str, Any]:
    """The same placement checks on a layout (item envelopes at their positions), plus standard parts the layout
    gives no position (they would be left loose)."""
    from aicad.assembly import render

    sc = render.scene_from_skeleton(skel, "", ifaces)
    boxes: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    names: dict[str, str] = {}
    apart = {f"item:{i}" for i in skel.get("separate") or []}  # kept separate by the engineer at the ICD gate
    for b in sc["bodies"]:
        if b.get("group") in apart:
            continue
        bb = render.bounds({"bodies": [b]})
        if bb:
            boxes[b["id"]] = (np.array(bb[0]), np.array(bb[1]))
            names[b["id"]] = b["label"]
    findings: list[dict[str, Any]] = []
    if len(boxes) >= 2:
        zmin = min(float(b[0][2]) for b in boxes.values())
        on_floor = {i: abs(float(b[0][2]) - zmin) <= TOUCH_MM for i, b in boxes.items()}
        findings += apart_findings(names, _groups(boxes), on_floor)
    from aicad.office import icd

    for s in skel.get("standard") or []:
        nm = str(s.get("name") or "")
        if re.search(r"\bbearing|\b6[02]0\d\b", nm, re.IGNORECASE) and not icd.seated(ifaces, s["item"]):
            findings.append({"code": "unplaced_standard", "severity": "note", "items": [s["item"]],
                             "text": f"{s.get('qty', 1)} × {nm} have no seat in this layout: they would be left "
                                     "loose in the parts bin."})
    findings = merge_issues(findings, skel, ifaces)
    if not any(f["code"] == "row" for f in findings):
        findings += skeleton_gear_findings(skel, ifaces)
    return {"findings": findings, "bodies": len(sc["bodies"])}


# the office layout's own codes (``icd.issues``) where they say what the picture would: one finding each
ISSUE_MAP = {"row_layout": ("row", "block"), "no_interface": ("no_interface", "block"),
             "bearing_unplaced": ("unplaced_standard", "note"), "shaft_support": ("shaft_support", "block"),
             "line_clash": ("line_clash", "block"), "journal_off_shaft": ("journal_off_shaft", "block")}


def merge_issues(findings: list[dict[str, Any]], skel: dict[str, Any], ifaces: list[dict[str, Any]]
                 ) -> list[dict[str, Any]]:
    """Add the layout engine's issues (codes: row_layout, no_interface, bearing_unplaced, ...) and drop our own
    finding of the same kind, so the engineer reads one sentence per problem. Older layouts without ``issues``: as is."""
    from aicad.office import icd

    try:
        raw = icd.issues(skel, ifaces) if hasattr(icd, "issues") else []
    except Exception:  # noqa: BLE001 - a layout the issue reader doesn't know: our own checks stand
        raw = []
    mapped = []
    for x in raw:
        if x.get("acknowledged"):
            continue  # the engineer's recorded decision (a part kept separate): not a finding any more
        m = ISSUE_MAP.get(str(x.get("code")))
        if m:
            mapped.append({"code": m[0], "severity": m[1], "items": list(x.get("items") or []),
                           "text": str(x.get("text") or x.get("message") or "")})
    have = {f["code"] for f in mapped}
    return [f for f in findings if f["code"] not in have] + mapped


def skeleton_gear_findings(skel: dict[str, Any], ifaces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gear pairs that must mesh (the ICD's gear meshes, or the only two gears of one module in a sub-assembly):
    axes parallel, centre distance m (z1 + z2) / 2, mid-planes level. Layout positions are part centres."""
    from aicad.office import frames

    items = skel.get("items") or {}
    pairs = [(f["a"]["item"], f["b"]["item"]) for f in ifaces if f["kind"] == "gear_mesh"]
    if not pairs:
        by: dict[tuple[str, float], list[str]] = {}
        for i, it in items.items():
            g = _gear_of(it)
            if it.get("role") == "gear" and g:
                by.setdefault((str(it.get("sub")), g[0]), []).append(i)
        pairs = [(v[0], v[1]) for v in by.values() if len(v) == 2]
    out: list[dict[str, Any]] = []
    for a, b in pairs:
        ia, ib = items.get(a), items.get(b)
        ga, gb = (_gear_of(ia) if ia else None), (_gear_of(ib) if ib else None)
        if not (ia and ib and ga and gb and ia.get("copies") and ib.get("copies")):
            continue
        want = ga[0] * (ga[1] + gb[1]) / 2
        axa = np.array(frames.apply(frames.item_rotation(ia.get("ax") or "z", 0.0), [0, 0, 1]), dtype=float)
        axb = np.array(frames.apply(frames.item_rotation(ib.get("ax") or "z", 0.0), [0, 0, 1]), dtype=float)
        d = np.array(ib["copies"][0], dtype=float) - np.array(ia["copies"][0], dtype=float)
        axial = float(np.dot(d, axa))
        radial = float(np.linalg.norm(d - axial * axa))
        na, nb = ia["name"], ib["name"]
        if np.linalg.norm(np.cross(axa, axb)) > 1e-3:
            out.append({"code": "gear_axes", "severity": "block", "items": [a, b],
                        "text": f"{na} and {nb} must mesh, but their axes are not parallel in this layout."})
        elif abs(radial - want) > MESH_TOL_MM:
            out.append({"code": "gear_centre", "severity": "block", "items": [a, b],
                        "text": f"{na} and {nb} must mesh {want:g} mm apart (m (z1 + z2) / 2), but this layout puts "
                                f"their axes {radial:.4g} mm apart" + (" (on one axis, stacked)" if radial < 1 else "")
                                + "."})
        elif abs(axial) > MESH_TOL_MM:
            out.append({"code": "gear_plane", "severity": "block", "items": [a, b],
                        "text": f"{na} and {nb} sit {abs(axial):.4g} mm apart along their axes: not in one plane."})
    return out


# ----------------------------------------------------------------------------- exact-check estimate
def estimate_exact(root: Path, doc: dict[str, Any], clearance: bool = True) -> dict[str, Any]:
    """How long the exact check (``service.analyse``: interference, and clearance of near pairs) would take now:
    the pairs not yet in the pair cache times the measured means above, plus loading the parts. Cache reads only."""
    from aicad.assembly import pairs, service

    near = None
    if clearance:
        parts = service._parts(root, doc)
        near = min(service.NEAR_CAP_MM, max(2.0, 0.05 * service.length_scale(doc, parts) * 2))
    insts, want_int, want_clr, _w = service._candidates(root, doc, None, near, not clearance)
    lk = pairs._lookup(root, insts, want_int, want_clr, "1e-06", True)
    n_int = sum(1 for ops in lk["ops"].values() if "int" in ops)
    n_clr = sum(1 for ops in lk["ops"].values() if "clr" in ops)
    secs = n_int * INT_PAIR_S + n_clr * CLR_PAIR_S + (LOAD_S if lk["ops"] else 0.0)
    return {"pairs": len(want_int), "near": len(want_clr), "uncached": len(lk["ops"]), "seconds": round(secs, 1)}


# ----------------------------------------------------------------------------- the vision call
def prompt(scene: dict[str, Any], relations: list[dict[str, Any]], brief: str = "",
           notes: list[str] | None = None, image_name: str = "assembly.png") -> str:
    key = "; ".join(f"{k['n']} {k['label']}" + (f" (x{k['count']})" if k["count"] > 1 else "") for k in scene["key"])
    lines = [f"Picture: {image_name}", f"Items in the picture: {key}."]
    if brief:
        lines.append("What it should be: " + " ".join(brief.split())[:600])
    lines.append("Intended relations:\n" + "\n".join(f"{r['id']}: {r['text']}" for r in relations))
    if notes:
        lines.append("Also known (not drawn): " + "; ".join(notes[:6]))
    return "\n\n".join(lines)


async def ask(folder: Path, png: Path, text: str, budget_usd: float | None) -> tuple[str, float | None, dict[str, Any]]:
    """One vision call through the provider layer (``assembly_check`` role). Tests and simulated mode replace it."""
    from aicad import llm

    harness = llm.provider_name(ROLE) == "claude-sdk"
    res = await llm.complete(llm.CallRequest(role=ROLE, system=INSTRUCTIONS, prompt=text, images=(png,),
                                             cwd=folder, budget_usd=budget_usd, max_turns=3, max_tokens=1500,
                                             standalone_system=True, model=VISION_MODEL if harness else None,
                                             effort=VISION_EFFORT))
    return res.text, res.metering.cost_usd, {"usage": res.metering.usage.as_dict(), "model": res.metering.model,
                                              "latency_s": res.metering.latency_s}


def parse_verdict(text: str, relations: list[dict[str, Any]], key: list[dict[str, Any]] | None = None
                  ) -> dict[str, Any]:
    """The model's answer as a clean verdict. Anything unreadable is ``unsure`` (never a pass). Strings scrubbed."""
    from aicad.agent.session import scrub

    data: Any = None
    for raw in [*reversed(_FENCE.findall(text or "")), (text or "").strip()]:
        s, e = raw.find("{"), raw.rfind("}")
        if s < 0 or e <= s:
            continue
        try:
            data = json.loads(raw[s:e + 1])
            break
        except ValueError:
            continue
    ids = [r["id"] for r in relations]
    if not isinstance(data, dict):
        return {"overall": "unsure", "relations": [{"id": i, "status": "unsure", "reason": ""} for i in ids],
                "problems": [], "summary": "The visual check gave no readable answer.", "readable": False}

    nums = {k["n"]: k["label"] for k in key or []}

    def clean(s: Any, n: int = 240) -> str:
        return named(scrub(" ".join(str(s or "").split())), nums)[:n]

    got = {str(r.get("id")): r for r in data.get("relations") or [] if isinstance(r, dict)}
    rels = []
    for r in relations:
        g = got.get(r["id"]) or {}
        st = g.get("status") if g.get("status") in STATUS else "unsure"
        rels.append({"id": r["id"], "text": r["text"], "status": st, "reason": clean(g.get("reason"))})
    probs = []
    for p in (data.get("problems") or [])[:8]:
        if not isinstance(p, dict) or not str(p.get("text") or "").strip():
            continue
        its = [int(x) for x in p.get("items") or [] if isinstance(x, int | float) and not isinstance(x, bool)]
        probs.append({"kind": p.get("kind") if p.get("kind") in PROBLEM_KINDS else "other",
                      "items": [x for x in its if not nums or x in nums][:12],
                      "labels": [nums[x] for x in its if x in nums][:12], "text": clean(p.get("text"))})
    overall = data.get("overall") if data.get("overall") in OVERALL else "unsure"
    if overall == "looks_assembled" and (any(r["status"] == "wrong" for r in rels) or probs):
        overall = "looks_wrong" if any(r["status"] == "wrong" for r in rels) else "unsure"
    return {"overall": overall, "relations": rels, "problems": probs, "summary": clean(data.get("summary"), 300),
            "readable": True}


_ITEM_REF = re.compile(r"\b(?:item|part|body|no\.?|number)\s*#?\s*(\d+)\b", re.IGNORECASE)
_TAG_REF = re.compile(r"\s*[(\[]\s*#?(\d+)\s*[)\]]")
_INST = re.compile(r"<(\d+)>")


def named(text: str, nums: dict[int, str]) -> str:
    """The picture's number tags in a sentence become the parts' names (live run 2026-11-19: "Item 3" and
    "Key (3)" reached the chat), and SOLIDWORKS instance suffixes become plain words ("Gear shaft<1>" -> "Gear shaft",
    "Bearing<2>" -> "Bearing #2")."""
    if nums:
        text = _ITEM_REF.sub(lambda m: nums.get(int(m.group(1)), m.group(0)), text)
        text = _TAG_REF.sub(lambda m: "" if int(m.group(1)) in nums else m.group(0), text)
    return plain_instances(text)


def plain_instances(text: str) -> str:
    """``Name<1>`` -> ``Name``, ``Name<k>`` -> ``Name #k`` (k > 1): the instance number only where it tells two apart."""
    return _INST.sub(lambda m: "" if m.group(1) == "1" else f" #{m.group(1)}", text or "")


def fake_verdict(relations: list[dict[str, Any]], quick: dict[str, Any], key: list[dict[str, Any]]) -> dict[str, Any]:
    """Simulated mode (development, no tokens): a verdict that follows the quick checks, clearly marked."""
    block = [f for f in quick["findings"] if f["severity"] == "block"]
    rows = [f for f in block if f["code"] in ("row", "floating")]
    overall = "looks_wrong" if rows else "looks_assembled"
    return {"overall": overall,
            "relations": [{"id": r["id"], "text": r["text"], "status": "wrong" if rows else "ok",
                           "reason": "simulated"} for r in relations],
            "problems": [{"kind": f["code"], "items": [], "labels": [], "text": f["text"]} for f in rows],
            "summary": ("Simulated visual check: the parts look " + ("apart, not assembled." if rows else
                                                                    "assembled.")), "readable": True,
            "simulated": True}


# ----------------------------------------------------------------------------- policy
def decide(verdict: dict[str, Any] | None, quick: dict[str, Any], est: dict[str, Any] | None,
           vision_s: float | None = None) -> dict[str, Any]:
    """What the exact interference check does now and whether the step stops. Returns
    {exact: "inline" | "background" | "targeted", stop: bool, reason: str, targets: [inst ids], why: str}."""
    block = [f for f in quick.get("findings") or [] if f["severity"] == "block"]
    if block:
        return {"exact": "targeted", "stop": True, "reason": block[0]["text"],
                "targets": sorted({i for f in block for i in f["items"]}),
                "why": "A placement measurement found the problem; the picture doesn't decide it."}
    if verdict is None or not verdict.get("readable", True):
        return {"exact": "inline", "stop": False, "reason": "", "targets": [],
                "why": "No visual check: the exact check runs as usual."}
    ov = verdict["overall"]
    if ov == "looks_wrong":
        return {"exact": "targeted", "stop": False, "reason": verdict.get("summary") or "The picture looks wrong.",
                "targets": [], "confirm": True,
                "why": "The picture looks wrong: the flagged parts are measured first."}
    all_ok = verdict["relations"] and all(r["status"] == "ok" for r in verdict["relations"])
    if ov == "looks_assembled" and all_ok and not verdict.get("problems"):
        slow = est is not None and est.get("seconds", 0) > (vision_s or VISION_S)
        return {"exact": "background" if slow else "inline", "stop": False, "reason": "", "targets": [],
                "why": ("The picture looks assembled and every relation looks right: the exact check runs in the "
                        "background (advisory) because it would take longer than looking did."
                        if slow else "The picture looks assembled; the exact check is quick here, so it runs now.")}
    return {"exact": "inline", "stop": False, "reason": "", "targets": [],
            "why": "The visual check is unsure: the exact check runs as usual."}


def targets_from(verdict: dict[str, Any], doc: dict[str, Any], key: list[dict[str, Any]]) -> list[str]:
    """Instance ids of the items the picture flagged (by their key numbers, or by name in a wrong relation)."""
    flagged_n = {n for p in verdict.get("problems") or [] for n in p.get("items") or []}
    labels = {k["label"].lower() for k in key if k["n"] in flagged_n}
    for r in verdict.get("relations") or []:
        if r["status"] == "wrong":
            low = r["text"].lower()
            labels |= {k["label"].lower() for k in key if k["label"].lower() in low}
    return [i["id"] for i in doc["instances"] if i["name"].split("<")[0].strip().lower() in labels][:40]


def summary_line(verdict: dict[str, Any] | None) -> str:
    """One plain line for a log, a ticket comment or a chat message (labelled as a visual check)."""
    if verdict is None:
        return ""
    head = {"looks_assembled": "looks assembled", "looks_wrong": "looks wrong",
            "unsure": "can't tell from the picture"}[verdict["overall"]]
    bad = [r for r in verdict["relations"] if r["status"] == "wrong"]
    tail = verdict.get("summary") or ""
    if bad:
        tail = "; ".join(f"{r['text']}: {r['reason']}" if r["reason"] else r["text"] for r in bad[:3])
    elif verdict.get("problems"):
        tail = "; ".join(p["text"] for p in verdict["problems"][:3])
    return f"Visual check (advisory): it {head}" + (f". {tail}" if tail else ".")



# ----------------------------------------------------------------------------- one look, end to end
async def look(scene: dict[str, Any], relations: list[dict[str, Any]], folder: Path, *, brief: str = "",
               notes: list[str] | None = None, budget_usd: float | None = None, simulated: bool = False,
               quick: dict[str, Any] | None = None) -> dict[str, Any]:
    """Render ``scene`` into ``folder/assembly.png`` and get the verdict (simulated: from the quick checks, no
    tokens). Never raises: a failure is ``{"status": "failed", "error": plain text}``. Returns the record that is
    saved next to the picture (``visual.json``) and shown in the UI."""
    import time

    from aicad.assembly import render
    from aicad.platform import metering

    folder.mkdir(parents=True, exist_ok=True)
    png = folder / "assembly.png"
    rec: dict[str, Any] = {"status": "failed", "at": _now(), "relations_in": relations, "advisory": True}
    try:
        r = await render.render_async(scene, png)
    except render.RenderError as e:
        return {**rec, "error": str(e)}
    rec.update(render_s=r["seconds"], key=scene["key"], bodies=r["bodies"])
    t0 = time.perf_counter()
    if simulated:
        verdict = fake_verdict(relations, quick or {"findings": []}, scene["key"])
        usd: float | None = 0.0
        meta: dict[str, Any] = {}
    else:
        try:
            import asyncio

            text, usd, meta = await asyncio.wait_for(
                ask(folder, png, prompt(scene, relations, brief, notes, png.name), budget_usd), VISION_TIMEOUT_S)
        except TimeoutError:
            return {**rec, "status": "failed", "error": "The visual check took too long and was skipped; the measured "
                    "checks still apply.", "vision_s": round(time.perf_counter() - t0, 1)}
        except Exception as e:  # noqa: BLE001 - any provider failure: the visual check is simply missing
            from aicad.agent.session import scrub

            msg = scrub(str(e))[:200]
            if "budget" in msg.lower():
                msg = "the look needed more tokens than its cap"
            return {**rec, "status": "failed", "error": f"The visual check couldn't run ({msg}).",
                    "vision_s": round(time.perf_counter() - t0, 1)}
        verdict = parse_verdict(text, relations, scene["key"])
    tokens = 0 if not usd else min(CHECK_MAX_TOKENS, metering.tokens_for_usd(usd))
    rec.update(status="done", verdict=verdict, vision_s=round(time.perf_counter() - t0, 1), tokens=tokens,
               usd=round(usd or 0.0, 5), usage=meta.get("usage"), line=summary_line(verdict))
    store_record(folder, rec)
    return rec


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def store_record(folder: Path, rec: dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / "visual.json.tmp"
    tmp.write_text(json.dumps(rec, default=str), encoding="utf-8")
    tmp.replace(folder / "visual.json")


def load_record(folder: Path) -> dict[str, Any] | None:
    try:
        d = json.loads((folder / "visual.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def public(rec: dict[str, Any] | None) -> dict[str, Any] | None:
    """What the UI gets (no usage internals)."""
    if not rec:
        return None
    keep = ("status", "at", "verdict", "line", "tokens", "render_s", "vision_s", "error", "key", "quick", "policy",
            "exact", "advisory", "simulated", "level", "name")
    return {k: rec[k] for k in keep if k in rec}


# ----------------------------------------------------------------------------- the exact check, as the policy says
def clash_rows(an: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"a": c["a"], "b": c["b"], "a_name": c.get("a_name"), "b_name": c.get("b_name"),
             "volume_mm3": round(float(c["volume_mm3"]), 3)} for c in an["interference"]["pairs"]
            if c["kind"] == "interference"]


async def targeted(root: Path, org_id: str, doc: dict[str, Any], targets: list[str]) -> list[dict[str, Any]]:
    """Exact interference of the pairs that involve the flagged instances only (through the pair cache). With two
    or more flagged parts, only a clash *between* flagged parts confirms the picture: a flagged shaft touching an
    unflagged bearing (a 2.2 mm³ shoulder fillet, live run 2026-11-19) is not what the picture complained about, and
    clashes alone are advisory (PD-71)."""
    from aicad.assembly import service

    if not targets:
        return []
    res = await service.check_pairs(root, org_id, doc, only=targets)
    names = service.human_names(doc)  # people read these lines
    mine = set(targets)
    return [{"a": p["a"], "b": p["b"], "a_name": names.get(p["a"]), "b_name": names.get(p["b"]),
             "volume_mm3": round(float(p["volume_mm3"]), 3)} for p in res["interference"]["pairs"]
            if p["kind"] == "interference" and (len(mine) < 2 or (p["a"] in mine and p["b"] in mine))]


def confirm(decision: dict[str, Any], verdict: dict[str, Any] | None, clashes: list[dict[str, Any]]) -> dict[str, Any]:
    """After the targeted check of a "looks wrong": stop when a measurement confirms it, else carry on and say the
    concern was not confirmed (vision alone never stops a step: PD-73)."""
    if not decision.get("confirm"):
        return decision
    if clashes:
        c = clashes[0]
        return {**decision, "stop": True, "reason": f"{summary_line(verdict)} Measured: {c['a_name']} and "
                f"{c['b_name']} overlap by {c['volume_mm3']:.1f} mm³."}
    return {**decision, "stop": False, "unconfirmed": True,
            "reason": f"{summary_line(verdict)} The measurements found nothing to confirm it: carrying on."}
