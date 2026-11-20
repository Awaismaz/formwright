"""Direct design (no AI): build a Design Office part straight from its approved interfaces when they fix it.

A gear shaft in an approved program is fully defined by its ICD and skeleton: the envelope gives its length and Ø,
the bearing journals and gear seats give every step and its position, a keyed seat gives the DIN 6885 keyseat. Writing
that as a model script took a design agent one to two minutes of model output. ``plan`` decides per ticket whether the
part is that well defined and, if so, writes the Studio model script itself: a normal, readable script with editable
parameters, ``PARAM_META`` limits and EXPECTED values from hand formulas (``fw.stepped_shaft`` / ``fw.spur_gear``),
which then goes through exactly the same build and check gate (CHK-02..08) and the same ICD conformance review as an
agent's script. Nothing here calls a model or the CAD kernel; it is pure and tested by hand calculation.

Covered: shafts (journals, gear / hub seats, shoulders, keyseats, end chamfers, shoulder fillets), spacers and
sleeves (a bored ring), and spur gears (module, teeth, face width, bore, hub keyway). Everything else, and any part
whose brief asks for something the interfaces don't size (a thread, a groove, a hub on a gear, a size the ICD
doesn't explain), goes to the design agent as before; when only such extras are missing, the agent gets the direct
model as its starting point (``seed``).
"""

from __future__ import annotations

import hashlib
import itertools
import math
import os
import re
from typing import Any

from aicad.office import icd, interfaces

VERSION = 1
ENV = "FW_OFFICE_DIRECT"  # "0" turns the direct path off (measurements, or an operational kill switch)
LABEL = "Built from the interface spec (no AI)"

_SHAFTY = re.compile(r"\b(shaft|axle|spindle|arbor)s?\b", re.IGNORECASE)
_SPACERY = re.compile(r"\b(spacer|sleeve|distance (?:ring|piece|tube)|bush(?:ing)?|collar)s?\b", re.IGNORECASE)
_GEARY = re.compile(r"\b(gear|pinion|gearwheel)s?\b", re.IGNORECASE)
_SETSCREW = re.compile(r"set ?screws?|grub ?screws?", re.IGNORECASE)
_KEYWORD = re.compile(r"\bkey(?:ed|way|seat)?s?\b|feather key|parallel key", re.IGNORECASE)

# Features a brief may ask for that the interfaces don't size: (pattern, what it is, also looked for in the
# program brief's sentences about this kind of part)
_EXTRAS: list[tuple[re.Pattern[str], str, bool]] = [(re.compile(p, re.IGNORECASE), w, b) for p, w, b in (
    (r"\bthread(?:s|ed)?\b|\btapped\b", "a thread", True),
    (r"\bgrooves?\b|\bcirclips?\b|retaining ring|snap ring|\be-?clips?\b", "a groove or circlip", True),
    (r"\bundercuts?\b|\brelief\b", "an undercut", True),
    (r"\bd-?flats?\b|\bflats?\b|\bspanner\b|\bwrench\b", "a flat", True),
    (r"cross[- ]?holes?|cross[- ]?drill|radial holes?|\bholes?\b", "a hole", False),
    (r"\bsplines?d?\b|\bserrat", "a spline", True),
    (r"\bknurl", "knurling", True),
    (r"set ?screws?|grub ?screws?", "a set screw", True),
    (r"\bhex(?:agon(?:al)?)?\b|\bsquare (?:end|drive|section)\b", "a hex or square", True),
    (r"\btaper(?:ed)?\b|\bconical\b", "a taper", True),
    (r"\bslots?\b|\bslotted\b", "a slot", True),
    (r"cent(?:re|er)[- ](?:holes?|drill)", "centre holes", True),
    (r"\bhelical\b|\bhelix\b", "helical teeth", True),
    (r"\bweb\b|\bspokes?\b|lightening|\brecess(?:ed)?\b", "a web or recess", True),
    (r"\bcrowned?\b|profile shift|\bbevel\b|\bworm\b|\binternal gear|\brack\b|\bsprocket|\bpulley|\bcluster",
     "a special gear form", False),
    (r"\bseals?\b|o-?rings?|\boil(?:way)?\b|lubricat", "a seal or oil feature", True),
    (r"\bflange[sd]?\b", "a flange", True),
    (r"\bintegral\b|\bone piece\b|\bcut on the shaft\b", "an integral feature", True),
)]
# a metric thread size (capital M; "m2" is a module, and so is "M2" right before teeth / gear words)
_EXTRAS.insert(0, (re.compile(r"(?<![\w.])M\d{1,2}(?:\s*[x×]\s*\d+(?:\.\d+)?)?\b"
                              r"(?!\s*(?:gear|pinion|module|spur|,?\s*(?:x\s*)?\d+\s*(?:teeth|tooth|t\b|z\b)))"),
                   "a thread", True))
# the part's own size statement: "Ø20 x 100", "60 x 40 x 10 mm"
_ENVELOPE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mm\s*)?[x×]\s*(\d+(?:\.\d+)?)(?:\s*(?:mm\s*)?[x×]\s*(\d+(?:\.\d+)?))?")
# a hub or boss on a gear (a size the interfaces don't give); the "hub keyway" or "hub bore" is the gear's own bore
_HUB = re.compile(r"\b(?:hub|boss)\b(?!\s*(?:keyways?|key ?seats?|key|bores?|bored))", re.IGNORECASE)
_STEPPY = re.compile(r"\bshoulders?\b|\bsteps?\b|\bstepped\b|\bcollar\b", re.IGNORECASE)
_CHAMFER = re.compile(r"chamfer(?:ed|s)?\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*(?:mm)?", re.IGNORECASE)

# Materials named in a brief (word-bounded: "plate" must not read as PLA)
_MATERIALS: list[tuple[re.Pattern[str], str]] = [(re.compile(p, re.IGNORECASE), n) for p, n in (
    (r"\b(c45|1045|ck45|en8)\b", "Steel 1045 (medium carbon)"), (r"\b(42crmo4|4140)\b", "Steel 4140 (alloy)"),
    (r"\b(1018|s235|mild steel)\b", "Steel 1018 (low carbon)"), (r"\bstainless\b|\b(304|316)\b", "Stainless 304"),
    (r"\balumin(?:i)?um\b|\b6061\b", "Aluminium 6061-T6"), (r"\b7075\b", "Aluminium 7075-T6"),
    (r"\bbrass\b", "Brass C360"), (r"\bbronze\b", "Bearing bronze C932"),
    (r"\b(pom|acetal|delrin)\b", "Acetal POM (Delrin)"), (r"\bnylon\b|\bpa ?66\b", "Nylon PA66"),
    (r"\bsteel\b", "Steel 1045 (medium carbon)"))]
DEFAULT_MATERIAL = {"shaft": "Steel 1045 (medium carbon)", "gear": "Steel 1045 (medium carbon)",
                    "spacer": "Steel 1018 (low carbon)"}

TOL = 1e-6


class Undetermined(Exception):
    """The interfaces don't fix this part: the reason, in plain words."""


def enabled(doc: dict[str, Any]) -> bool:
    if os.environ.get(ENV, "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    return doc.get("direct_build", True) is not False


def sha(script: str) -> str:
    return hashlib.sha256(script.replace("\r\n", "\n").encode("utf-8")).hexdigest()[:16]


# ============================================================================ the decision
def plan(doc: dict[str, Any], t: dict[str, Any]) -> dict[str, Any]:
    """Decide how this ticket's part is designed.

    ``{"path": "direct", "kind", "script", "sha", "summary", "material", "icd_version", ...}`` when the approved ICD and
    skeleton fix every dimension; else ``{"path": "agent", "reasons": [...]}`` with what is not fixed, plus ``seed``
    (the direct script) when the interfaces do fix the part and only extras the brief asks for are missing."""
    if t.get("kind") != "part":
        return _agent(["it is not a designed part"])
    if not interfaces.has_icd(doc) or (doc.get("icd") or {}).get("status") != "approved":
        return _agent(["the program has no approved interfaces"])
    sk = doc["skeleton"]
    it = (sk.get("items") or {}).get(t["item_id"])
    if not it:
        return _agent(["the part is not in the layout"])
    item = next((i for i in doc.get("items") or [] if i["id"] == t["item_id"]), {})
    name = str(item.get("name") or t["title"])
    desc = str(item.get("description") or "")
    kind = _kind(it, f"{name} {desc}")
    if kind == "spacer" and _SETSCREW.search(f"{name} {desc}"):
        kind = "collar"  # a set-screw collar: the generators' turned ring with a radial tapped hole
    if kind is None or kind == "collar":
        return _generated(doc, t, it, name, desc, kind)
    ifs = doc["icd"]["interfaces"]
    try:
        spec = {"shaft": _shaft_spec, "gear": _gear_spec, "spacer": _spacer_spec}[kind](sk, ifs, t["item_id"], it)
        extras = _extras(kind, spec, name, desc, _program_sentences(str(doc.get("brief") or ""), kind))
        spec.update(name=name, item=t["item_id"], icd_version=doc["icd"]["version"],
                    material=_material(desc) or DEFAULT_MATERIAL[kind], qty=int(t.get("qty") or 1))
        ch = _CHAMFER.search(desc)
        if ch and kind != "gear":
            spec["chamfer_text"] = float(ch.group(1))
        script = {"shaft": shaft_script, "gear": gear_script, "spacer": spacer_script}[kind](spec)
    except Undetermined as e:
        return _agent([str(e)])
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError):  # an incomplete or malformed ICD entry
        return _agent(["the interfaces of this part are incomplete"])
    out = {"kind": kind, "script": script, "sha": sha(script), "summary": spec["summary"],
           "material": spec["material"], "icd_version": doc["icd"]["version"], "version": VERSION,
           "features": spec["n_features"]}
    if extras:
        return {**_agent(extras), "seed": out}
    return {"path": "direct", **out}


def _generated(doc: dict[str, Any], t: dict[str, Any], it: dict[str, Any], name: str, desc: str,
               kind: str | None) -> dict[str, Any]:
    """Housings, covers, caps, plates, brackets, pulleys, couplings and collars (``generators``, WORKLIST 45)."""
    from aicad.office import generators

    kind = kind or generators.kind_of(doc, t["item_id"], name, desc)
    if kind is None:
        what = {"block": "a block or plate", "hub": "a hub of this kind"}.get(str(it.get("role")), "this kind of part")
        return _agent([f"{what} needs the designer (no generator for it)"])
    try:
        g = generators.plan_part(kind, doc, t["item_id"], name, desc)
    except (Undetermined, generators.Undetermined) as e:
        return _agent([str(e)])
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError, StopIteration):
        return _agent(["the interfaces of this part are incomplete"])
    out = {"kind": kind, "script": g["script"], "sha": sha(g["script"]), "summary": g["summary"],
           "material": g["material"], "icd_version": doc["icd"]["version"], "version": VERSION,
           "features": g["n_features"], "generator": g["generator"], "notes": g["notes"]}
    if g["extras"]:
        return {**_agent(g["extras"]), "seed": out}
    return {"path": "direct", **out}


def _agent(reasons: list[str]) -> dict[str, Any]:
    return {"path": "agent", "reasons": reasons}


def _kind(it: dict[str, Any], text: str) -> str | None:
    role = it.get("role")
    if role == "shaft" and it.get("shape") == "cylinder":
        return "shaft"
    if role == "gear" and it.get("module") and it.get("teeth") and not it.get("internal"):
        return "gear"  # (an internal ring gear has no generator here: the design agent makes it)
    if role == "hub" and it.get("shape") == "cylinder" and _SPACERY.search(text) and not _GEARY.search(text):
        return "spacer"
    return None


def _program_sentences(brief: str, kind: str) -> str:
    rx = {"shaft": _SHAFTY, "gear": _GEARY, "spacer": _SPACERY}[kind]
    return " ".join(s for s in re.split(r"(?<=[.;!?])\s+|\n+", brief) if rx.search(s))


def _extras(kind: str, spec: dict[str, Any], name: str, desc: str, program: str) -> list[str]:
    """What the brief asks for beyond the interfaces (each makes the part need the design agent)."""
    from aicad.office import gage

    text = f"{name}. {desc}"
    out: list[str] = []
    for rx, what, in_program in _EXTRAS:
        if rx.search(text) or (in_program and program and rx.search(program)):
            if what == "a hole" and kind == "gear" and not re.search(r"cross|radial|holes\b", text, re.IGNORECASE):
                continue  # "bore hole" on a gear is its bore
            if what == "a groove or circlip" and spec.get("grooves"):
                continue  # the interfaces place the circlip groove
            out.append(f"the brief asks for {what}")
    if kind == "gear" and _HUB.search(text):
        out.append("the brief asks for a hub the interfaces don't size")
    if _KEYWORD.search(text) and not spec["keyways"]:
        out.append("the brief asks for a key the interfaces don't size")
    if kind == "shaft" and _STEPPY.search(text) and len(spec["segments"]) < 2:
        out.append("the brief asks for a shoulder the interfaces don't place")
    known = set(spec["known"]) | _envelope_numbers(desc)
    for label, v in gage.brief_dimensions(desc):
        ch = _CHAMFER.search(desc)
        if ch and abs(float(ch.group(1)) - v) < TOL:
            continue
        if not any(abs(v - k) < 1e-6 for k in known):
            out.append(f"the brief gives a size the interfaces don't explain ({label})")
    seen: set[str] = set()
    return [x for x in out if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]


def _envelope_numbers(desc: str) -> set[float]:
    """The part's own size statement ("Ø20 x 100", "20 mm diameter, 120 long"): the layout read it as the planned
    envelope and the approved ICD supersedes it, so it is never an extra requirement. Other sizes are."""
    out: set[float] = set()
    m = _ENVELOPE.search(desc or "")
    if m:
        out |= {float(g) for g in m.groups() if g}
    dia = re.search(r"[ØⲐ⌀]\s*(\d+(?:\.\d+)?)", desc or "")
    if dia:
        out.add(float(dia.group(1)))
    out |= {float(v) for v in icd._worded(desc or "") if v}
    return out


def _material(text: str) -> str | None:
    for rx, mat in _MATERIALS:
        if rx.search(text):
            return mat
    return None


# ============================================================================ part specs (from the ICD)
def _r(x: float) -> float:
    return round(float(x), 4)


def _n(k: int, word: str) -> str:
    return f"{k} {word}{'s' if k != 1 else ''}"


def _by_id(ifs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {f["id"]: f for f in ifs}


def _other(f: dict[str, Any], item: str) -> str:
    return f["b"]["name"] if f["a"]["item"] == item else f["a"]["name"]


def _key_angle(sk: dict[str, Any], f: dict[str, Any], side: str) -> float:
    """The keyway's side about the part axis, degrees from +X (unrounded: a gear's tooth phase turns it)."""
    d = f["data"]
    lax = icd._lax(icd._part_vec(sk, f[side], icd.unit(icd.ax_of(d))))
    q = icd.to_canon(lax, icd._part_vec(sk, f[side], icd.point3(icd.ax_of(d), d["dir"], 0.0)))
    a = math.degrees(math.atan2(q[1], q[0]))
    return round(a, 3) + 0.0


def _centred(x: dict[str, Any]) -> bool:
    return abs(float(x["c"][0])) < 1e-6 and abs(float(x["c"][1])) < 1e-6


def _shaft_spec(sk: dict[str, Any], ifs: list[dict[str, Any]], item: str, it: dict[str, Any]) -> dict[str, Any]:
    """The shaft profile from its interfaces: diameter zones (journals, seats), checked faces, keyseats."""
    from aicad import fw_std

    L = float(it["size"][2])
    D = float(it.get("d") or it["size"][0])
    zl, zh = -L / 2, L / 2
    byid = _by_id(ifs)
    zones: list[dict[str, Any]] = []
    faces: list[dict[str, Any]] = []
    keys: list[dict[str, Any]] = []
    grooves: list[dict[str, Any]] = []
    for x in icd.item_features(sk, ifs, item):
        if x.get("ax"):
            raise Undetermined(f"{x['label']} is off the shaft axis")
        if x["type"] == "boss":
            if not _centred(x):
                raise Undetermined(f"{x['label']} is off the shaft axis")
            spans: list[tuple[float, float, str]] = []
            if x.get("z0") is not None:
                spans.append((float(x["z0"]), float(x["z1"]), x["if"]))
            else:  # a seat: where the gear / hub sits on the shaft
                for iid in [x["if"], *(x.get("also") or [])]:
                    f = byid[iid]
                    d = f["data"]
                    if f["kind"] != "shaft_bore" or not d.get("z") or f["b"]["item"] != item:
                        raise Undetermined(f"{x['label']} has no position along the shaft")
                    g = icd._axial(sk, f["b"], d, d["axis"], d["z"][0], d["z"][1])
                    spans.append((float(g["z0"]), float(g["z1"]), iid))
            for z0, z1, iid in spans:
                f = byid[iid]
                if z0 < zl - 0.01 or z1 > zh + 0.01:
                    raise Undetermined(f"{x['label']} runs past the shaft end")
                role = "journal" if f["kind"] in ("bearing_journal", "bearing_seat") else "seat"
                what = (f"bearing journal for the {f['data'].get('designation')}" if role == "journal"
                        else f"seat for the {_other(f, item)}")
                zones.append({"z0": max(z0, zl), "z1": min(z1, zh), "d": float(x["d"]), "role": role,
                              "fit": x.get("fit"), "if": iid, "what": what})
        elif x["type"] == "face":
            faces.append(x)
        elif x["type"] == "keyway" and x.get("on") == "shaft":
            keys.append(x)
        elif x["type"] == "groove" and x.get("on", "shaft") == "shaft":
            grooves.append(_groove(x, byid.get(x["if"])))
        else:
            raise Undetermined(f"{x['label']} is not a shaft feature this can build")
    # the diameter profile from -Z to +Z: the envelope Ø, turned down where a journal or seat says
    cuts = sorted({_r(zl), _r(zh), *(_r(z["z0"]) for z in zones), *(_r(z["z1"]) for z in zones)})
    segs: list[dict[str, Any]] = []
    for a, b in itertools.pairwise(cuts):
        if b - a < 1e-6:
            continue
        mid = (a + b) / 2
        here = [z for z in zones if z["z0"] - TOL <= mid <= z["z1"] + TOL]
        ds = {_r(z["d"]) for z in here}
        if len(ds) > 1:
            raise Undetermined(f"two diameters are asked for between Z {a:g} and {b:g}")
        d = ds.pop() if ds else D
        if d > D + TOL:
            raise Undetermined(f"Ø{d:g} is larger than the shaft envelope Ø{D:g}")
        roles = [z["role"] for z in here]
        if segs and abs(segs[-1]["d"] - d) < TOL:
            segs[-1]["z1"] = b
            segs[-1]["roles"] += roles
        else:
            segs.append({"d": d, "z0": a, "z1": b, "roles": roles})
    if len(segs) > 12:
        raise Undetermined("the shaft has more steps than a simple turned shaft")
    for f in faces:  # every face the ICD states must be an end face or a shoulder of this profile
        z, n = float(f["z"]), int(f["n"])
        if (abs(z - zl) < 0.01 and n < 0) or (abs(z - zh) < 0.01 and n > 0):
            continue
        k = next((i for i in range(len(segs) - 1) if abs(segs[i]["z1"] - z) < 0.01), None)
        if k is None or not ((n < 0 and segs[k + 1]["d"] > segs[k]["d"]) or (n > 0 and segs[k]["d"] > segs[k + 1]["d"])):
            raise Undetermined(f"{f['label']} at Z {z:g} is not a shoulder of the shaft")
    keyways = []
    for k in keys:
        z0, z1, d = float(k["z0"]), float(k["z1"]), float(k["d"])
        seg = next((s for s in segs if s["z0"] - TOL <= z0 and z1 <= s["z1"] + TOL), None)
        if seg is None or abs(seg["d"] - d) > TOL or z1 - z0 <= float(k["b"]):
            raise Undetermined(f"{k['label']} does not sit on one diameter of the shaft")
        f = byid[k["if"]]
        try:
            din = fw_std.din6885(d)
        except ValueError as e:
            raise Undetermined(str(e)) from None
        keyways.append({"z0": z0, "z1": z1, "d": d, "b": float(k["b"]), "t1": float(k["depth"]),
                        "din": abs(din["b"] - float(k["b"])) < TOL and abs(din["t1"] - float(k["depth"])) < TOL,
                        "angle": _key_angle(sk, f, "b" if f["b"]["item"] == item else "a"), "if": k["if"],
                        "what": f"keyseat for the {_other(f, item)}'s key ({f['data'].get('standard') or 'DIN 6885'})",
                        "key": f"{f['data']['b']:g} × {f['data']['h']:g} × {f['data']['length']:g}"})
    for g in grooves:  # a circlip groove sits inside one diameter, clear of its shoulders
        seg = next((s for s in segs if s["z0"] - TOL <= g["z0"] and g["z1"] <= s["z1"] + TOL), None)
        if seg is None or (g["d_shaft"] is not None and abs(seg["d"] - g["d_shaft"]) > TOL) or g["d"] >= seg["d"]:
            raise Undetermined(f"{g['label']} does not sit on one diameter of the shaft")
        g["d_shaft"] = seg["d"]
    diam = sorted({s["d"] for s in segs})
    known = {L, D, *diam, *(z["d"] for z in zones), *(k["b"] for k in keyways), *(k["z1"] - k["z0"] for k in keyways),
             *(k["t1"] for k in keyways), *(_r(s["z1"] - s["z0"]) for s in segs),
             *(g["d"] for g in grooves), *(g["z1"] - g["z0"] for g in grooves)}
    for k in keyways:  # the key the keyseat takes (b × h × length, and the hub's t2) is sized by the same interface
        kd = byid[k["if"]]["data"]
        known |= {float(kd[x]) for x in ("h", "t2", "length") if kd.get(x) is not None}
    r_s = None  # the bearings' corner chamfer (ISO 582 r_s min) when the interface gives it: shoulder fillets stay under
    for f in ifs:
        if item in (f["a"]["item"], f["b"]["item"]) and f["kind"] in ("bearing_journal", "bearing_seat"):
            fd = f["data"]
            known |= {float(fd["D"]), float(fd["B"]), float(fd["d"])}
            rs = next((fd[k] for k in ("r_s_min", "r_s", "rs_min", "corner_chamfer") if fd.get(k)), None)
            if rs:
                r_s = min(float(rs), r_s if r_s is not None else float(rs))
    steps = "Ø" + " / Ø".join(f"{s['d']:g}" for s in segs) if len(segs) > 1 else f"Ø{D:g}"
    n_j = sum(1 for z in zones if z["role"] == "journal")
    summary = (f"shaft {steps} × {L:g}, " + (f"{_n(n_j, 'bearing journal')}, " if n_j else "")
               + f"{_n(sum(1 for z in zones if z['role'] == 'seat'), 'seat')}"
               + (f", {len(keyways)} keyseat{'s' if len(keyways) != 1 else ''}" if keyways else ""))
    if grooves:
        summary += f", {_n(len(grooves), 'circlip groove')}"
    hub_shoulder = any(f["kind"] == "shaft_bore" and f["b"]["item"] == item and f["data"].get("shoulder_z") is not None
                       for f in ifs)
    return {"L": L, "D": D, "segments": segs, "zones": zones, "faces": faces, "keyways": keyways, "grooves": grooves,
            "r_s": r_s, "known": known, "summary": summary, "hub_shoulder": hub_shoulder,
            "n_features": len(zones) + len(faces) + len(keyways) + len(grooves)}


def _groove(x: dict[str, Any], f: dict[str, Any] | None) -> dict[str, Any]:
    """A circlip groove (DIN 471) from whatever fields its feature or interface gives: the span (z0..z1, or z with a
    width), the groove Ø (d2 / groove_d, or the shaft Ø less twice the depth)."""
    src = {**((f or {}).get("data") or {}), **x}
    width = next((float(src[k]) for k in ("width", "w", "m") if src.get(k)), None)
    if src.get("z0") is not None and src.get("z1") is not None:
        z0, z1 = float(src["z0"]), float(src["z1"])
    elif src.get("z") is not None and width:
        z0, z1 = float(src["z"]) - width / 2, float(src["z"]) + width / 2
    else:
        raise Undetermined(f"{x.get('label') or 'a groove'} has no position along the shaft")
    d_shaft = next((float(src[k]) for k in ("d1", "shaft_d", "d") if src.get(k)), None)
    dg = next((float(src[k]) for k in ("d2", "groove_d", "d_groove") if src.get(k)), None)
    if dg is None:
        depth = next((float(src[k]) for k in ("depth", "t", "t1") if src.get(k)), None)
        if depth is None or d_shaft is None:
            raise Undetermined(f"{x.get('label') or 'a groove'} has no groove diameter")
        dg = d_shaft - 2 * depth
    if z1 - z0 <= 0 or dg <= 0:
        raise Undetermined(f"{x.get('label') or 'a groove'} has no size")
    return {"z0": z0, "z1": z1, "d": dg, "d_shaft": d_shaft if dg != d_shaft else None, "if": x.get("if"),
            "label": x.get("label") or f"circlip groove Ø{dg:g}", "standard": src.get("standard") or "DIN 471"}


def _gear_spec(sk: dict[str, Any], ifs: list[dict[str, Any]], item: str, it: dict[str, Any]) -> dict[str, Any]:
    m, z, B = float(it["module"]), int(it["teeth"]), float(it["face_width"])
    H = float(it["size"][2])
    if abs(H - B) > TOL:
        raise Undetermined(f"the gear envelope is {H:g} long but the face width is {B:g} (a hub the ICD doesn't size)")
    if float(it["size"][0]) + 0.01 < m * (z + 2):
        raise Undetermined("the envelope is smaller than the tip circle")
    byid = _by_id(ifs)
    bore = None
    bore_if = None
    keyway = None
    alpha = icd.PRESSURE_ANGLE
    mesh = []
    faces = []
    for x in icd.item_features(sk, ifs, item):
        if x.get("ax"):
            raise Undetermined(f"{x['label']} is off the gear axis")
        if x["type"] == "hole" and _centred(x) and x.get("z0") is None and bore is None:
            bore, bore_if = float(x["d"]), x["if"]
        elif x["type"] == "gear":
            if abs(float(x["module"]) - m) > TOL or int(x["teeth"]) != z:
                raise Undetermined(f"the mesh asks for {x['label']}, the layout for m{m:g} × {z}")
            for iid in [x["if"], *(x.get("also") or [])]:
                f = byid[iid]
                alpha = float(f["data"].get("pressure_angle") or alpha)
                mesh.append({"if": iid, "mate": _other(f, item), "a": float(f["data"]["centre_distance"])})
        elif x["type"] == "keyway" and x.get("on") == "hub" and keyway is None:
            if abs(float(x["z0"]) + B / 2) > 0.01 or abs(float(x["z1"]) - B / 2) > 0.01:
                raise Undetermined(f"{x['label']} doesn't run through the gear")
            f = byid[x["if"]]
            keyway = {"b": float(x["b"]), "t2": float(x["depth"]), "d": float(x["d"]), "if": x["if"],
                      "angle": _key_angle(sk, f, "a" if f["a"]["item"] == item else "b"),
                      "standard": f["data"].get("standard") or "DIN 6885"}
        elif x["type"] == "face" and abs(abs(float(x["z"])) - B / 2) < 0.01 and int(x["n"]) * float(x["z"]) > 0:
            faces.append(x)
        else:
            raise Undetermined(f"{x['label']} is not a gear feature this can build")
    if bore is None:
        raise Undetermined("the gear has no bore in its interfaces")
    rf = m * z / 2 - 1.25 * m
    if bore / 2 >= rf - 0.5 * m:
        raise Undetermined(f"the Ø{bore:g} bore leaves no rim under the teeth")
    if keyway is not None:
        from aicad import fw_std

        if abs(keyway["d"] - bore) > TOL:
            raise Undetermined("the hub keyway is not on the bore")
        try:
            din = fw_std.din6885(bore)
        except ValueError as e:
            raise Undetermined(str(e)) from None
        keyway["din"] = abs(din["b"] - keyway["b"]) < TOL and abs(din["t2"] - keyway["t2"]) < TOL
    known = {m, float(z), B, bore, m * z, m * (z + 2), m * z - 2.5 * m, *(x["a"] for x in mesh), float(it["size"][0])}
    if keyway:  # the keyway and the key it takes (b × h × length, the shaft's t1): sized by the key interface
        known |= {keyway["b"], keyway["t2"]}
        kd = byid[keyway["if"]]["data"]
        known |= {float(kd[x]) for x in ("h", "t1", "length") if kd.get(x) is not None}
    summary = f"spur gear m{m:g} × {z} teeth, face {B:g}, bore Ø{bore:g}" + (" with a keyway" if keyway else "")
    return {"m": m, "z": z, "B": B, "bore": bore, "bore_if": bore_if, "alpha": alpha, "keyway": keyway,
            "keyways": [keyway] if keyway else [], "mesh": mesh, "faces": faces, "known": known, "summary": summary,
            "n_features": 2 + len(faces) + (1 if keyway else 0)}


def _spacer_spec(sk: dict[str, Any], ifs: list[dict[str, Any]], item: str, it: dict[str, Any]) -> dict[str, Any]:
    OD, H = float(it["size"][0]), float(it["size"][2])
    bore, bore_if = None, None
    faces = []
    for x in icd.item_features(sk, ifs, item):
        if x.get("ax"):
            raise Undetermined(f"{x['label']} is off the part axis")
        if x["type"] == "hole" and _centred(x) and x.get("z0") is None and bore is None:
            bore, bore_if = float(x["d"]), x["if"]
        elif x["type"] == "face" and abs(abs(float(x["z"])) - H / 2) < 0.01 and int(x["n"]) * float(x["z"]) > 0:
            faces.append(x)
        else:
            raise Undetermined(f"{x['label']} is not a spacer feature this can build")
    if bore is None:
        bore = float(it.get("bore") or 0) or None
    if bore is None:
        raise Undetermined("the spacer has no bore in its interfaces")
    if OD - bore < 2.0:
        raise Undetermined(f"a Ø{bore:g} bore leaves less than 1 mm of wall in Ø{OD:g}")
    host = next((f["b"]["name"] for f in ifs if f["id"] == bore_if), None) if bore_if else None
    summary = f"spacer Ø{OD:g} / Ø{bore:g} × {H:g}"
    return {"OD": OD, "H": H, "bore": bore, "bore_if": bore_if, "host": host, "faces": faces, "keyways": [],
            "od_given": it.get("source") != "assumed",
            "known": {OD, H, bore}, "summary": summary, "n_features": 1 + len(faces)}


# ============================================================================ scripts
def _f(x: float) -> str:
    """A float literal that reads like a hand-written one (20.0, 3.5, 0.25)."""
    v = round(float(x), 4)
    return f"{v:.1f}" if v.is_integer() else repr(v)


def _g(x: float) -> str:
    return f"{round(float(x), 4):g}"


def _meta(rows: list[tuple[str, float, float, float, str, str, str]]) -> str:
    lines = ["PARAM_META = {"]
    for name, lo, hi, step, unit, group, label in rows:
        u = f', "unit": "{unit}"' if unit else ""
        def num(v: float) -> str:  # whole-number parameters (teeth) keep whole-number limits
            return str(v) if isinstance(v, int) else _f(v)

        st = str(step) if isinstance(step, int) else _g(step)
        lines.append(f'    "{name}": {{"min": {num(lo)}, "max": {num(hi)}, "step": {st}{u}, "group": "{group}", '
                     f'"label": "{label}"}},')
    lines.append("}")
    return "\n".join(lines)


def _params(names: list[str]) -> str:
    """PARAMS = dict(...), wrapped like hand-written code."""
    lines, cur = [], "PARAMS = dict("
    for k, n in enumerate(names):
        bit = f"{n}={n}" + (", " if k < len(names) - 1 else ")")
        if len(cur) + len(bit) > 110:
            lines.append(cur.rstrip())
            cur = " " * 14
        cur += bit
    return "\n".join([*lines, cur])


def _header(spec: dict[str, Any], what: str, lines: list[str]) -> str:
    body = "\n".join(f"  {x}" for x in lines)
    return (f'"""{spec["name"]}: {what}, built from the approved interface spec (ICD v{spec["icd_version"]}).\n\n'
            "Modelled along Z with the origin at the centre of its envelope (the ICD part frame); the program\n"
            "assembly places it from there. What the interfaces fix:\n"
            f"{body}\nFits are drawing callouts: the model is at nominal size. The parameters below can be edited "
            "freely;\nkeep the interface sizes unless the ICD changes.\n"
            '"""\n')


def _names(segs: list[dict[str, Any]], D: float) -> tuple[dict[float, str], list[str | None]]:
    """Parameter names: one per distinct diameter (D for the envelope Ø), one per segment length except the body
    (the longest segment at D, derived from LENGTH)."""
    dn: dict[float, str] = {D: "D"}
    used = {"D"}
    for s in segs:
        if s["d"] in dn:
            continue
        base = "D_JOURNAL" if "journal" in s["roles"] else "D_SEAT" if "seat" in s["roles"] else "D_STEP"
        nm = base
        n = 2
        while nm in used:
            nm, n = f"{base}_{n}", n + 1
        dn[s["d"]] = nm
        used.add(nm)
    body = max((i for i, s in enumerate(segs) if abs(s["d"] - D) < TOL),
               key=lambda i: (segs[i]["z1"] - segs[i]["z0"], -i), default=None)
    if body is None:  # no segment at the envelope Ø: the longest one is derived
        body = max(range(len(segs)), key=lambda i: (segs[i]["z1"] - segs[i]["z0"], -i))
    roles = ["JOURNAL" if "journal" in s["roles"] else "SEAT" if "seat" in s["roles"] else "STEP" for s in segs]
    count: dict[str, int] = {}
    total = {r: sum(1 for i, x in enumerate(roles) if x == r and i != body) for r in set(roles)}
    ln: list[str | None] = []
    for i, r in enumerate(roles):
        if i == body:
            ln.append(None)
            continue
        count[r] = count.get(r, 0) + 1
        ln.append(f"L_{r}" if total[r] == 1 else f"L_{r}_{count[r]}")
    return dn, ln


def shaft_script(spec: dict[str, Any]) -> str:
    segs, D, L = spec["segments"], spec["D"], spec["L"]
    dn, ln = _names(segs, D)
    ends = (segs[0]["d"], segs[-1]["d"])
    chamfer = spec.get("chamfer_text") or (1.0 if min(ends) >= 15 else 0.5)
    chamfer = min(chamfer, 0.25 * min(ends), 0.5 * min(segs[0]["z1"] - segs[0]["z0"], segs[-1]["z1"] - segs[-1]["z0"]))
    steps = [abs(a["d"] - b["d"]) / 2 for a, b in itertools.pairwise(segs)]
    fillet = 0.5 if steps and min(steps) > 0.75 else 0.0
    if fillet and spec.get("r_s"):  # never more than the bearing's corner chamfer, or the ring can't seat
        fillet = min(fillet, round(0.8 * float(spec["r_s"]), 2))
    if spec.get("hub_shoulder"):  # a gear / hub face bears on a shoulder: its bore edge is sharp (no chamfer in the
        fillet = 0.0              # ICD), so a fillet in the corner would hold the hub off its seat (3 mm³ of overlap)
    grooves = spec.get("grooves") or []
    lines = []
    for z in sorted(spec["zones"], key=lambda z: z["z0"]):
        lines.append(f"{z['if']}  {z['what']}: Ø{_g(z['d'])} {z['fit'] or ''}".rstrip()
                     + f", Z {_g(z['z0'])} to {_g(z['z1'])}")
    for f in spec["faces"]:
        lines.append(f"{f['if']}  {f['label']} at Z {_g(f['z'])}")
    for k in spec["keyways"]:
        lines.append(f"{k['if']}  {k['what']} ({k['key']}): {_g(k['b'])} wide, {_g(k['t1'])} deep, "
                     f"Z {_g(k['z0'])} to {_g(k['z1'])}")
    for g in grooves:
        lines.append(f"{g['if']}  {g['label']} ({g['standard']}): Ø{_g(g['d'])}, {_g(g['z1'] - g['z0'])} wide, "
                     f"Z {_g(g['z0'])} to {_g(g['z1'])}")
    out = [_header(spec, "turned shaft", lines), *(["import math\n"] if grooves else []), "from build123d import *\n",
           "from aicad import fw\n",
           f'NAME = "{spec["name"]}"', f'MATERIAL = "{spec["material"]}"', ""]
    p: list[str] = []
    out.append(f"LENGTH = {_f(L)}  # overall length, mm (ICD envelope)")
    p.append("LENGTH")
    for d, nm in sorted(dn.items(), key=lambda kv: -kv[0]):
        if not any(abs(s["d"] - d) < TOL for s in segs):
            continue
        roles = [z for z in spec["zones"] if abs(z["d"] - d) < TOL]
        why = ", ".join(sorted({z["what"] for z in roles}))
        out.append(f"{nm} = {_f(d)}  # {'shaft' if nm == 'D' else nm.split('_')[1].lower()} Ø, mm"
                   + (f" ({why})" if why else ""))
        p.append(nm)
    for i, s in enumerate(segs):
        if ln[i]:
            out.append(f"{ln[i]} = {_f(s['z1'] - s['z0'])}  # mm, Ø{_g(s['d'])} from Z {_g(s['z0'])} to {_g(s['z1'])}")
            p.append(ln[i])  # type: ignore[arg-type]
    for n, k in enumerate(spec["keyways"], start=1):
        sfx = "" if len(spec["keyways"]) == 1 else f"_{n}"
        out.append(f"KEY{sfx}_LENGTH = {_f(k['z1'] - k['z0'])}  # keyseat length, mm ({k['key']} key)")
        out.append(f"KEY{sfx}_START = {_f(k['z0'] + L / 2)}  # keyseat start, mm from the -Z end")
        p += [f"KEY{sfx}_LENGTH", f"KEY{sfx}_START"]
    for n, g in enumerate(grooves, start=1):
        sfx = "" if len(grooves) == 1 else f"_{n}"
        out.append(f"GROOVE{sfx}_D = {_f(g['d'])}  # circlip groove Ø, mm ({g['standard']})")
        out.append(f"GROOVE{sfx}_WIDTH = {_f(g['z1'] - g['z0'])}  # mm")
        out.append(f"GROOVE{sfx}_START = {_f(g['z0'] + L / 2)}  # groove start, mm from the -Z end")
        p += [f"GROOVE{sfx}_D", f"GROOVE{sfx}_WIDTH", f"GROOVE{sfx}_START"]
    out.append(f"CHAMFER = {_f(chamfer)}  # 45° chamfer on both ends, mm")
    p.append("CHAMFER")
    if fillet:
        out.append(f"FILLET = {_f(fillet)}  # shoulder fillet radius, mm (keep it under the bearing's corner chamfer)")
        p.append("FILLET")
    out += ["", _params(p)]
    fixed = sum(s["z1"] - s["z0"] for i, s in enumerate(segs) if ln[i])
    smaller = [d for d in dn if d < D - TOL]
    rows = [("LENGTH", float(math.ceil(max(fixed + 1, 2 * chamfer + 2))),
             float(max(math.ceil(2 * L), math.ceil(fixed + 10))), 1.0, "mm", "Shaft", "Overall length")]
    for d, nm in sorted(dn.items(), key=lambda kv: -kv[0]):
        if nm not in p:
            continue
        lo = (max(smaller) + 2 * fillet + 1) if nm == "D" and smaller else 3.0
        hi = (D - 2 * fillet - 1) if nm != "D" else 2 * D
        rows.append((nm, round(min(lo, d), 1), round(max(hi, d), 1), 0.5, "mm", "Shaft",
                     "Shaft Ø" if nm == "D" else nm.split("_", 1)[1].replace("_", " ").capitalize() + " Ø"))
    for i, s in enumerate(segs):
        if ln[i]:
            n = ln[i]
            rows.append((n, 1.0, float(math.ceil(L)), 0.5, "mm", "Shaft",  # type: ignore[arg-type]
                         n[2:].replace("_", " ").capitalize() + " length"))  # type: ignore[index]
    for n, k in enumerate(spec["keyways"], start=1):
        sfx = "" if len(spec["keyways"]) == 1 else f"_{n}"
        rows.append((f"KEY{sfx}_LENGTH", float(math.floor(k["b"] + 1)), float(math.ceil(L)), 0.5, "mm", "Keyseat",
                     "Keyseat length"))
        rows.append((f"KEY{sfx}_START", 0.0, float(math.ceil(L)), 0.5, "mm", "Keyseat", "Keyseat start from the -Z end"))
    for n, g in enumerate(grooves, start=1):
        sfx = "" if len(grooves) == 1 else f"_{n}"
        rows += [(f"GROOVE{sfx}_D", round(0.5 * g["d_shaft"], 1), round(g["d_shaft"] - 0.1, 1), 0.1, "mm", "Groove",
                  "Groove Ø"),
                 (f"GROOVE{sfx}_WIDTH", 0.1, 10.0, 0.05, "mm", "Groove", "Groove width"),
                 (f"GROOVE{sfx}_START", 0.0, float(math.ceil(L)), 0.5, "mm", "Groove", "Groove start from the -Z end")]
    rows.append(("CHAMFER", 0.0, round(max(chamfer, 0.25 * min(ends)), 1), 0.1, "mm", "Finish", "End chamfer"))
    if fillet:
        rows.append(("FILLET", 0.0, round(max(fillet, min(1.0, min(steps) - 0.1)), 1), 0.1, "mm", "Finish",
                     "Shoulder fillet"))
    out += [_meta(rows), ""]
    # the segments, -Z end first; the body length follows from LENGTH
    body = ln.index(None)
    rest = " - ".join(x for x in ln if x)
    if rest:
        out.append(f"body = LENGTH - {rest}  # the Ø{_g(segs[body]['d'])} body takes up the rest of the length")
    out.append("segments = [  # (Ø, length) from the -Z end")
    for i, s in enumerate(segs):
        what = sorted({z["what"] for z in spec["zones"] if s["z0"] - TOL <= (z["z0"] + z["z1"]) / 2 <= s["z1"] + TOL})
        out.append(f"    ({dn[s['d']]}, {ln[i] or ('body' if rest else 'LENGTH')}),  # "
                   + ("; ".join(what) if what else "plain"))
    out.append("]")
    out.append(f"part, shaft = fw.stepped_shaft(segments, chamfer=CHAMFER{', fillet=FILLET' if fillet else ''}, "
               f"z0=-LENGTH / 2, name=NAME)")
    out.append("volume = shaft[\"volume\"]")
    for n, k in enumerate(spec["keyways"], start=1):
        sfx = "" if len(spec["keyways"]) == 1 else f"_{n}"
        din = fw_din(k["d"])
        size = "" if k["din"] else f", b={_f(k['b'])}, t1={_f(k['t1'])}"
        note = f"DIN 6885 for Ø{_g(k['d'])}: b {_g(din['b'])}, t1 {_g(din['t1'])}" if k["din"] else "sizes from the ICD"
        side = "" if abs(k["angle"] - 90) < 1e-9 else f", angle={_g(k['angle'])}"
        out.append(f"part, cut = fw.shaft_keyway(part, d={dn[k['d']]}, z_center=-LENGTH / 2 + KEY{sfx}_START + "
                   f"KEY{sfx}_LENGTH / 2, length=KEY{sfx}_LENGTH{size}{side})  # {note}")
        out.append("volume -= cut")
    for n, g in enumerate(grooves, start=1):
        sfx = "" if len(grooves) == 1 else f"_{n}"
        ds = dn[g["d_shaft"]]
        out += [(f"# circlip groove {n}: the Ø{_g(g['d_shaft'])} turned down to GROOVE{sfx}_D over GROOVE{sfx}_WIDTH "
                 "(removed: π/4 (Ø² - groove Ø²) × width)"),
                f"ring = Pos(0, 0, -LENGTH / 2 + GROOVE{sfx}_START) * (",
                f"    Cylinder({ds} / 2 + 1, GROOVE{sfx}_WIDTH, align=(Align.CENTER, Align.CENTER, Align.MIN))",
                f"    - Cylinder(GROOVE{sfx}_D / 2, GROOVE{sfx}_WIDTH, align=(Align.CENTER, Align.CENTER, Align.MIN)))",
                f'part = fw.feature("Circlip groove {n}", part - ring, d=GROOVE{sfx}_D, width=GROOVE{sfx}_WIDTH)',
                f"volume -= math.pi / 4 * ({ds} ** 2 - GROOVE{sfx}_D ** 2) * GROOVE{sfx}_WIDTH"]
    out += ["", "result = part", 'EXPECTED = {"bbox": shaft["bbox"], "volume": volume, "solids": 1}', ""]
    return "\n".join(out)


def fw_din(d: float) -> dict[str, float]:
    from aicad import fw_std

    return fw_std.din6885(d)


def gear_script(spec: dict[str, Any]) -> str:
    k = spec["keyway"]
    lines = [f"{spec['bore_if']}  bore Ø{_g(spec['bore'])} H7 through, on the shaft"]
    for x in spec["mesh"]:
        lines.append(f"{x['if']}  mesh with the {x['mate']}: m{_g(spec['m'])} × {spec['z']} teeth, "
                     f"α {_g(spec['alpha'])}°, centre distance {_g(x['a'])}; a tooth centred on +X")
    if k:
        lines.append(f"{k['if']}  hub keyway {_g(k['b'])} × {_g(k['t2'])} ({k['standard']}) through the bore")
    for f in spec["faces"]:
        lines.append(f"{f['if']}  {f['label']} at Z {_g(f['z'])}")
    out = [_header(spec, "spur gear", lines), "from build123d import *\n", "from aicad import fw\n",
           f'NAME = "{spec["name"]}"', f'MATERIAL = "{spec["material"]}"', "",
           f"MODULE = {_f(spec['m'])}  # mm (the mesh)", f"TEETH = {spec['z']}  # number of teeth",
           f"FACE_WIDTH = {_f(spec['B'])}  # mm", f"PRESSURE_ANGLE = {_f(spec['alpha'])}  # degrees",
           f"BORE = {_f(spec['bore'])}  # bore Ø, mm (H7 on the shaft)", "",
           _params(["MODULE", "TEETH", "FACE_WIDTH", "PRESSURE_ANGLE", "BORE"])]
    rim = spec["m"] * spec["z"] - 2.5 * spec["m"] - spec["m"]
    out.append(_meta([("MODULE", 0.5, 10.0, 0.25, "mm", "Teeth", "Module"),
                      ("TEETH", 8, 400, 1, "", "Teeth", "Number of teeth"),
                      ("FACE_WIDTH", 1.0, float(math.ceil(4 * spec["B"])), 0.5, "mm", "Teeth", "Face width"),
                      ("PRESSURE_ANGLE", 14.5, 25.0, 0.5, "°", "Teeth", "Pressure angle"),
                      ("BORE", 3.0, round(max(spec["bore"], rim - 0.5), 1), 0.5, "mm", "Bore", "Bore Ø")]))
    out.append("")
    kw = ""
    if k:
        kw = ", keyway=True" if k["din"] else f", keyway=({_f(k['b'])}, {_f(k['t2'])})"
        if abs(k["angle"] - 90) > 1e-9:
            kw += f", keyway_angle={_g(k['angle'])}"
    out.append("# true involute teeth, a tooth centred on +X; Z from -FACE_WIDTH / 2 to +FACE_WIDTH / 2")
    out.append(f"part, gear = fw.spur_gear(MODULE, TEETH, FACE_WIDTH, pressure_angle=PRESSURE_ANGLE, bore=BORE{kw},\n"
               "                          z0=-FACE_WIDTH / 2)" + (
                   f"  # keyway: DIN 6885 for Ø{_g(spec['bore'])}" if k and k["din"] else ""))
    out += ["", "result = part", 'EXPECTED = {"bbox": gear["bbox"], "volume": gear["volume"], "solids": 1}',
            '# tip Ø = MODULE × (TEETH + 2), pitch Ø = MODULE × TEETH (gear["gear"] has them)', ""]
    return "\n".join(out)


def spacer_script(spec: dict[str, Any]) -> str:
    OD, H, bore = spec["OD"], spec["H"], spec["bore"]
    chamfer = spec.get("chamfer_text") or (0.5 if (OD - bore) / 2 >= 2 else 0.2)
    chamfer = min(chamfer, (OD - bore) / 4, H / 4)
    host = f" on the {spec['host']}" if spec.get("host") else ""
    lines = [f"{spec['bore_if'] or 'bore'}  bore Ø{_g(bore)} H7{host}",
             f"envelope Ø{_g(OD)} × {_g(H)}" + ("" if spec["od_given"] else " (the outside Ø is the layout's envelope: "
                                                                        "check it against what the spacer bears on)")]
    for f in spec["faces"]:
        lines.append(f"{f['if']}  {f['label']} at Z {_g(f['z'])}")
    out = [_header(spec, "spacer", lines), "import math\n", "from build123d import *\n", "from aicad import fw\n",
           f'NAME = "{spec["name"]}"', f'MATERIAL = "{spec["material"]}"', "",
           f"OD = {_f(OD)}  # outside Ø, mm", f"LENGTH = {_f(H)}  # mm, along the shaft",
           f"BORE = {_f(bore)}  # bore Ø, mm (H7 on the shaft)",
           f"CHAMFER = {_f(chamfer)}  # 45° break on the outer edges, mm", "",
           "PARAMS = dict(OD=OD, LENGTH=LENGTH, BORE=BORE, CHAMFER=CHAMFER)",
           _meta([("OD", round(bore + 2, 1), round(max(2 * OD, OD + 10), 1), 0.5, "mm", "Spacer", "Outside Ø"),
                  ("LENGTH", 1.0, float(math.ceil(max(4 * H, H + 20))), 0.5, "mm", "Spacer", "Length"),
                  ("BORE", 1.0, round(OD - 2, 1), 0.5, "mm", "Spacer", "Bore Ø"),
                  ("CHAMFER", 0.0, round(max(chamfer, min((OD - bore) / 4, H / 4)), 1), 0.1, "mm", "Finish",
                   "Edge chamfer")]), "",
           "ring = Cylinder(OD / 2, LENGTH) - Cylinder(BORE / 2, LENGTH + 2)  # centred on the origin",
           'part = fw.feature("Spacer ring", ring, od=OD, bore=BORE, length=LENGTH)',
           "if CHAMFER > 0:",
           "    edges = fw.edges_near(part, [(OD / 2, 0, LENGTH / 2), (OD / 2, 0, -LENGTH / 2)])",
           '    part = fw.feature("Edge chamfers", chamfer(edges, CHAMFER), length=CHAMFER)',
           "",
           "# ring volume minus the two 45° chamfers (Pappus: triangle CHAMFER² / 2 at radius OD / 2 - CHAMFER / 3)",
           "volume = math.pi / 4 * (OD ** 2 - BORE ** 2) * LENGTH - 2 * CHAMFER ** 2 / 2 * 2 * math.pi * (OD / 2 - CHAMFER / 3)",
           "result = part", 'EXPECTED = {"bbox": [OD, OD, LENGTH], "volume": volume, "solids": 1}', ""]
    return "\n".join(out)


# ============================================================================ ticket wording
def note(p: dict[str, Any], seed: bool = False) -> str:
    """What the Studio chat says about a direct build (plain words; also the revision's cause)."""
    if p.get("template"):
        t = p["template"]
        src = f"{t['source'].get('title') or t['name']}" + (f" in {t['source']['program_name']}"
                                                            if t["source"].get("program_name") else "")
        if seed:
            return (f"Design Office: a starting model from the workspace template {t['name']} (from {src}; no AI), "
                    f"its parameters mapped to ICD v{p['icd_version']} where they match. The designer fits the rest.")
        return (f"Design Office: built from the workspace template {t['name']} (from {src}; no AI), every mapped "
                f"size from ICD v{p['icd_version']}. Every parameter can be edited here without AI.")
    if seed:
        return (f"Design Office: a starting model from the interface spec (no AI): {p['summary']}, every size from "
                f"ICD v{p['icd_version']}. The designer adds what the brief asks for beyond the interfaces.")
    return (f"Design Office: built from the interface spec (no AI): {p['summary']}, {p['material']}, every size from ICD "
            f"v{p['icd_version']}. Every parameter can be edited here without AI.")


def seed_prompt(reasons: list[str]) -> str:
    """Told to the design agent when it starts from the direct model (only extras are missing)."""
    if any(r.startswith("starting from the workspace template") for r in reasons):
        return ("A starting model is already built from a workspace template of the same kind of part (an earlier "
                "verified design), its parameters set from this ICD where they match. Read the current model first, "
                "keep its structure and PARAMS, make every interface feature match this part's ICD excerpt, rebuild, "
                "and finish with your self-review.")
    want = "; ".join(r.removeprefix("the brief asks for ").removeprefix("the brief gives ") for r in reasons)
    return ("A starting model is already built and verified from the ICD: every interface feature at its stated "
            "place, the driving dimensions in PARAMS. Read the current model first and keep its interface features "
            f"and parameters. Add only what the brief asks for beyond the interfaces ({want}), rebuild, and finish "
            "with your self-review.")


def is_direct(t: dict[str, Any], state: dict[str, Any]) -> bool:
    """The ticket's latest build is the model this path wrote, unchanged (nobody edited it since)."""
    d = t.get("direct") or {}
    return d.get("path") == "direct" and not d.get("superseded") and bool(state.get("source"))         and sha(str(state.get("source"))) == d.get("sha")
