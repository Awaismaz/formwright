"""Parts the assembly agent makes or sizes itself, with no AI geometry (WORKLIST 51).

Two jobs, both pure and deterministic:

1. **Make**: when every dimension of a new part is known (stated, or following from what it mates with), write the
   Design Studio model script directly: a readable script with editable ``PARAMS``, ``PARAM_META`` limits and
   ``EXPECTED`` values from hand formulas (``fw.stepped_shaft``, ``fw.shaft_keyway``, ``fw.spur_gear``). It then
   goes through the normal build and check gate (CHK-02..08) like any other script. Covered: a stepped shaft
   (journals, a hub seat against a collar shoulder, a DIN 6885 keyseat, a DIN 471 groove), a spur gear (module,
   teeth, face width, bore, hub keyway), a spacer (bore, outside Ø, length).
2. **Size from the context**: a Toolbox component brought in "for" a part takes the sizes that part fixes: a
   bearing gets the journal's bore, a gear the keyed seat's bore and keyway and a face width that covers the key, a
   key the keyseat's width and length, a retaining ring the groove's shaft size.

Every value says where it came from (``src``: stated / from the mating part / standard / assumed); assumed values are
shown to the engineer. Standards tables are the Toolbox's (``toolbox.KEY_ROWS``, ``toolbox.DIN471``,
``toolbox.BEARING``), marked "verify" there. Nothing here claims a part is fit for manufacture.
"""

from __future__ import annotations

import math
from typing import Any

from aicad import toolbox

VERSION = 1


class MakeError(ValueError):
    """The request can't be made as a direct part (a plain sentence for the engineer)."""


def _f(x: float) -> str:
    v = round(float(x), 4)
    return f"{v:.1f}" if v.is_integer() else repr(v)


def _g(x: float) -> str:
    return f"{round(float(x), 4):g}"


def _num(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 0 else None


def din_key(d: float) -> dict[str, float]:
    """DIN 6885-1 (b, h, t1, t2) for a shaft or bore Ø d (the Toolbox table)."""
    b, h, t1, t2 = toolbox.key_row(d)
    return {"b": b, "h": h, "t1": t1, "t2": t2}


def key_length_for(space: float, b: float) -> float | None:
    """The longest DIN 6885 standard key length that fits ``space`` and exceeds the width."""
    return max((float(x) for x in toolbox.KEY_LENGTHS if b < x <= space + 1e-9), default=None)


def bearing_bore_width(d: float) -> tuple[int, float] | None:
    """(designation, width) of the 62xx (else 60xx) bearing with bore d."""
    for series in (62, 60):
        for k, (bd, _D, B) in sorted(toolbox.BEARING.items()):
            if k // 100 == series and abs(bd - d) < 1e-6:
                return k, float(B)
    return None


# ----------------------------------------------------------------------------- shafts
def design_shaft(spec: dict[str, Any]) -> dict[str, Any]:
    """A stepped shaft from a partial request: journals | hub seat | collar | journal, along +Z from Z = 0.

    ``spec``: journal_d (or d), seat_d, collar_d, journal_l, seat_l, collar_l, hub_width, keyseat (bool), groove
    (bool), chamfer, name, material. Returns the full layout with ``values`` {name: {value, src}}."""
    vals: dict[str, dict[str, Any]] = {}

    def put(name: str, value: float, src: str) -> float:
        vals[name] = {"value": round(float(value), 4), "src": src}
        return float(value)

    dj = _num(spec.get("journal_d")) or _num(spec.get("d"))
    if dj is None:
        raise MakeError("Say the shaft's journal diameter (for example Ø20), or what bearing it runs in.")
    put("journal_d", dj, "stated")
    brg = bearing_bore_width(dj)
    jl = _num(spec.get("journal_l"))
    if jl:
        put("journal_l", jl, "stated")
    elif brg:
        jl = put("journal_l", brg[1] + 2, f"bearing {brg[0]} width {brg[1]:g} + 2 mm")
    else:
        jl = put("journal_l", 16.0, "assumed")
    ds = _num(spec.get("seat_d"))
    ds = put("seat_d", ds, "stated") if ds else put("seat_d", dj + 5, "assumed: a 2.5 mm shoulder for the bearing")
    dc = _num(spec.get("collar_d"))
    dc = put("collar_d", dc, "stated") if dc else put("collar_d", ds + 5, "assumed: a 2.5 mm shoulder for the hub")
    if not dj < ds < dc:
        raise MakeError("The seat must be larger than the journals and the collar larger than the seat.")
    hw = _num(spec.get("hub_width"))
    hw = put("hub_width", hw, "stated") if hw else put("hub_width", 20.0, "assumed")
    sl = _num(spec.get("seat_l"))
    sl = put("seat_l", sl, "stated") if sl else put("seat_l", hw + 10, "hub width + 10 mm")
    if sl < hw:
        raise MakeError(f"The seat ({sl:g} mm) is shorter than the hub ({hw:g} mm).")
    cl = _num(spec.get("collar_l"))
    cl = put("collar_l", cl, "stated") if cl else put("collar_l", 8.0, "assumed")
    ch = _num(spec.get("chamfer"))
    ch = put("chamfer", ch, "stated") if ch is not None else put("chamfer", 1.0 if dj >= 15 else 0.5, "assumed")
    s0, s1 = jl, jl + sl          # the seat, the hub against the collar at s1
    out: dict[str, Any] = {"kind": "shaft", "name": str(spec.get("name") or "Stepped shaft")[:80],
                           "material": str(spec.get("material") or "Steel 1045 (medium carbon)")[:80],
                           "segments": [{"d": dj, "l": jl, "role": "journal"}, {"d": ds, "l": sl, "role": "seat"},
                                        {"d": dc, "l": cl, "role": "collar"}, {"d": dj, "l": jl, "role": "journal"}],
                           "length": 2 * jl + sl + cl, "hub": (s1 - hw, s1), "keyseat": None, "groove": None,
                           "values": vals, "bearing": brg[0] if brg else None}
    if spec.get("keyseat", True):
        try:
            k = din_key(ds)
        except toolbox.ToolboxError as e:
            raise MakeError(str(e)) from None
        L = _num(spec.get("key_length")) or key_length_for(hw - 4, k["b"])
        if L is None:
            raise MakeError(f"The hub ({hw:g} mm) is too narrow for a {k['b']:g} mm key.")
        put("key_length", L, "stated" if _num(spec.get("key_length")) else "DIN 6885 length, 4 mm shorter than the hub")
        out["keyseat"] = {"b": k["b"], "t1": k["t1"], "length": L, "center": s1 - hw / 2, "d": ds}
    if spec.get("groove"):
        if round(ds) != ds or round(ds) not in toolbox.DIN471:
            raise MakeError(f"No DIN 471 ring for a Ø{ds:g} seat: pick a seat Ø from the ring table.")
        s, _b, d2, m, _n = toolbox.DIN471[round(ds)]
        z1 = s1 - hw
        if z1 - m < s0 + 1:
            raise MakeError("The seat is too short for a circlip groove beside the hub.")
        out["groove"] = {"d1": ds, "d2": d2, "m": m, "s": s, "z0": z1 - m, "z1": z1}
        put("groove_d", d2, "DIN 471")
    if out["keyseat"] and out["groove"] and out["keyseat"]["center"] - out["keyseat"]["length"] / 2 < out["groove"]["z1"]:
        raise MakeError("The keyseat would run into the circlip groove: make the hub wider.")
    return out


def shaft_script(lay: dict[str, Any]) -> str:
    seg = lay["segments"]
    dj, ds, dc = seg[0]["d"], seg[1]["d"], seg[2]["d"]
    jl, sl, cl = seg[0]["l"], seg[1]["l"], seg[2]["l"]
    hw = lay["hub"][1] - lay["hub"][0]
    ks, gr = lay["keyseat"], lay["groove"]
    lines = [f"journals Ø{_g(dj)} × {_g(jl)} at both ends" + (f" (bearing {lay['bearing']})" if lay["bearing"] else ""),
             f"hub seat Ø{_g(ds)} × {_g(sl)}, the hub ({_g(hw)} wide) against the Ø{_g(dc)} collar"]
    if ks:
        lines.append(f"keyseat {_g(ks['b'])} × {_g(ks['t1'])} (DIN 6885), {_g(ks['length'])} long, centred in the hub")
    if gr:
        lines.append(f"circlip groove Ø{_g(gr['d2'])} × {_g(gr['m'])} (DIN 471 for Ø{_g(gr['d1'])}) at the hub's free face")
    doc = "\n".join(f"  {x}" for x in lines)
    out = [(f'"""{lay["name"]}: a stepped shaft made in Assembly Studio from the conversation (no AI geometry).\n\n'
           f"Along +Z from Z = 0. What it is made of:\n{doc}\n"
           "Sizes marked assumed in the conversation are a starting point: change them below. Fits are drawing "
           "callouts;\nthe model is at nominal size.\n\"\"\"\n")]
    if gr:
        out.append("import math\n")
    out += ["from build123d import *\n", "from aicad import fw\n", f'NAME = "{lay["name"]}"',
            f'MATERIAL = "{lay["material"]}"', "",
            f"D_JOURNAL = {_f(dj)}  # journal Ø, mm (bearing seats)", f"D_SEAT = {_f(ds)}  # hub seat Ø, mm",
            f"D_COLLAR = {_f(dc)}  # collar Ø, mm (the hub's shoulder)", f"L_JOURNAL = {_f(jl)}  # mm, each end",
            f"L_SEAT = {_f(sl)}  # mm", f"L_COLLAR = {_f(cl)}  # mm", f"HUB_WIDTH = {_f(hw)}  # the hub on the seat, mm",
            f"CHAMFER = {_f(lay['values']['chamfer']['value'])}  # 45° on both ends, mm"]
    names = ["D_JOURNAL", "D_SEAT", "D_COLLAR", "L_JOURNAL", "L_SEAT", "L_COLLAR", "HUB_WIDTH", "CHAMFER"]
    if ks:
        out.append(f"KEY_LENGTH = {_f(ks['length'])}  # keyseat length, mm (DIN 6885 {_g(ks['b'])} × {_g(ks['t1'])})")
        names.append("KEY_LENGTH")
    if gr:
        out.append(f"GROOVE_D = {_f(gr['d2'])}  # circlip groove Ø, mm (DIN 471)")
        out.append(f"GROOVE_WIDTH = {_f(gr['m'])}  # mm")
        names += ["GROOVE_D", "GROOVE_WIDTH"]
    out += ["", "PARAMS = dict(" + ", ".join(f"{n}={n}" for n in names) + ")", "PARAM_META = {",
            f'    "D_JOURNAL": {{"min": 3.0, "max": {_f(ds - 1)}, "step": 0.5, "unit": "mm", "group": "Shaft", "label": "Journal Ø"}},',
            f'    "D_SEAT": {{"min": {_f(dj + 1)}, "max": {_f(dc - 1)}, "step": 0.5, "unit": "mm", "group": "Shaft", "label": "Seat Ø"}},',
            f'    "D_COLLAR": {{"min": {_f(ds + 1)}, "max": {_f(2 * dc)}, "step": 0.5, "unit": "mm", "group": "Shaft", "label": "Collar Ø"}},',
            '    "L_JOURNAL": {"min": 2.0, "max": 500.0, "step": 0.5, "unit": "mm", "group": "Shaft", "label": "Journal length"},',
            f'    "L_SEAT": {{"min": {_f(hw)}, "max": 1000.0, "step": 0.5, "unit": "mm", "group": "Shaft", "label": "Seat length"}},',
            '    "L_COLLAR": {"min": 1.0, "max": 200.0, "step": 0.5, "unit": "mm", "group": "Shaft", "label": "Collar length"},',
            f'    "HUB_WIDTH": {{"min": {_f((ks or {}).get("length", 1) + 1)}, "max": {_f(sl)}, "step": 0.5, "unit": "mm", "group": "Hub", "label": "Hub width"}},',
            '    "CHAMFER": {"min": 0.0, "max": 3.0, "step": 0.1, "unit": "mm", "group": "Finish", "label": "End chamfer"},']
    if ks:
        out.append(f'    "KEY_LENGTH": {{"min": {_f(ks["b"] + 1)}, "max": {_f(hw)}, "step": 0.5, "unit": "mm", "group": "Keyseat", "label": "Keyseat length"}},')
    if gr:
        out.append(f'    "GROOVE_D": {{"min": {_f(round(0.8 * ds, 1))}, "max": {_f(ds - 0.1)}, "step": 0.1, "unit": "mm", "group": "Groove", "label": "Groove Ø"}},')
        out.append('    "GROOVE_WIDTH": {"min": 0.5, "max": 5.0, "step": 0.05, "unit": "mm", "group": "Groove", "label": "Groove width"},')
    out += ["}", "",
            "segments = [(D_JOURNAL, L_JOURNAL), (D_SEAT, L_SEAT), (D_COLLAR, L_COLLAR), (D_JOURNAL, L_JOURNAL)]",
            "part, shaft = fw.stepped_shaft(segments, chamfer=CHAMFER, name=NAME)",
            'volume = shaft["volume"]',
            "HUB_END = L_JOURNAL + L_SEAT  # the hub's face against the collar"]
    if ks:
        out += [("part, cut = fw.shaft_keyway(part, d=D_SEAT, z_center=HUB_END - HUB_WIDTH / 2, length=KEY_LENGTH)"
                "  # DIN 6885, centred in the hub"), "volume -= cut"]
    if gr:
        out += ["# circlip groove at the hub's free face: removed π/4 (D_SEAT² - GROOVE_D²) × width",
                "z_groove = HUB_END - HUB_WIDTH - GROOVE_WIDTH",
                "ring = Pos(0, 0, z_groove) * (Cylinder(D_SEAT / 2 + 1, GROOVE_WIDTH, align=(Align.CENTER, Align.CENTER, Align.MIN))",
                "                            - Cylinder(GROOVE_D / 2, GROOVE_WIDTH, align=(Align.CENTER, Align.CENTER, Align.MIN)))",
                'part = fw.feature("Circlip groove", part - ring, d=GROOVE_D, width=GROOVE_WIDTH)',
                "volume -= math.pi / 4 * (D_SEAT ** 2 - GROOVE_D ** 2) * GROOVE_WIDTH"]
    out += ["", "result = part", 'EXPECTED = {"bbox": shaft["bbox"], "volume": volume, "solids": 1}', ""]
    return "\n".join(out)


def shaft_volume(lay: dict[str, Any]) -> float:
    """Hand formula of the shaft's volume (the test oracle): cylinders, minus the two 45° end chamfers (Pappus),
    minus the keyseat (rounded slot: the floor chord integral) and the groove annulus."""
    from aicad import fw_std

    seg = lay["segments"]
    c = float(lay["values"]["chamfer"]["value"])
    v = sum(math.pi * (s["d"] / 2) ** 2 * s["l"] for s in seg)
    for s in (seg[0], seg[-1]):
        r = s["d"] / 2
        v -= c * c / 2 * 2 * math.pi * (r - c / 3)
    ks = lay["keyseat"]
    if ks:
        R, b, t1, L = ks["d"] / 2, ks["b"], ks["t1"], ks["length"]
        floor = R - t1

        def depth(x: float) -> float:
            return max(0.0, math.sqrt(max(R * R - x * x, 0.0)) - floor)

        hw = b / 2
        v -= (L - b) * fw_std._simpson(depth, -hw, hw)
        v -= fw_std._simpson(lambda t: 2 * hw * hw * math.cos(t) ** 2 * depth(hw * math.sin(t)), -math.pi / 2, math.pi / 2)
    gr = lay["groove"]
    if gr:
        v -= math.pi / 4 * (gr["d1"] ** 2 - gr["d2"] ** 2) * gr["m"]
    return v


# ----------------------------------------------------------------------------- gears and spacers
def design_gear(spec: dict[str, Any]) -> dict[str, Any]:
    """A spur gear: module and teeth required; face width, bore and keyway stated or from the shaft it goes on."""
    m, z = _num(spec.get("module")), _num(spec.get("teeth"))
    if m is None or z is None or round(z) != z:
        raise MakeError("Say the gear's module and number of teeth (for example m2, 40 teeth).")
    z = int(z)
    vals: dict[str, dict[str, Any]] = {"module": {"value": m, "src": "stated"}, "teeth": {"value": z, "src": "stated"}}
    bore = _num(spec.get("bore"))
    vals["bore"] = {"value": bore or round(m * z / 4), "src": spec.get("bore_src") or ("stated" if bore else "assumed")}
    bore = float(vals["bore"]["value"])
    B = _num(spec.get("face_width"))
    vals["face_width"] = {"value": B or 10 * m, "src": spec.get("face_width_src") or ("stated" if B else "10 × module")}
    rf = m * z / 2 - 1.25 * m
    if bore / 2 >= rf - 0.5 * m:
        raise MakeError(f"A Ø{bore:g} bore leaves no rim on an m{m:g} z{z} gear: keep it below Ø{2 * (rf - 0.5 * m):.1f}.")
    key = None
    if spec.get("keyway"):
        try:
            k = din_key(bore)
        except toolbox.ToolboxError as e:
            raise MakeError(str(e)) from None
        key = {"b": k["b"], "t2": k["t2"]}
    return {"kind": "gear", "name": str(spec.get("name") or f"Spur gear m{_g(m)} z{z}")[:80],
            "material": str(spec.get("material") or "Steel 1045 (medium carbon)")[:80], "module": m, "teeth": z,
            "face_width": float(vals["face_width"]["value"]), "bore": bore, "keyway": key, "values": vals}


def gear_script(lay: dict[str, Any]) -> str:
    k = lay["keyway"]
    out = [f'"""{lay["name"]}: a spur gear made in Assembly Studio from the conversation (no AI geometry).\n\n'
           f"  m{_g(lay['module'])} × {lay['teeth']} teeth, α 20°, face width {_g(lay['face_width'])}, bore "
           f"Ø{_g(lay['bore'])}" + (f", hub keyway {_g(k['b'])} × {_g(k['t2'])} (DIN 6885)" if k else "") + "\n"
           "  True involute teeth, a tooth centred on +X, the axis along Z from Z = 0; a working backlash of 0.04 m.\n"
           '"""\n', "from build123d import *\n", "from aicad import fw\n", f'NAME = "{lay["name"]}"',
           f'MATERIAL = "{lay["material"]}"', "", f"MODULE = {_f(lay['module'])}  # mm", f"TEETH = {lay['teeth']}",
           f"FACE_WIDTH = {_f(lay['face_width'])}  # mm", f"BORE = {_f(lay['bore'])}  # bore Ø, mm", "",
           "PARAMS = dict(MODULE=MODULE, TEETH=TEETH, FACE_WIDTH=FACE_WIDTH, BORE=BORE)", "PARAM_META = {",
           '    "MODULE": {"min": 0.5, "max": 10.0, "step": 0.25, "unit": "mm", "group": "Teeth", "label": "Module"},',
           '    "TEETH": {"min": 12, "max": 200, "step": 1, "unit": "", "group": "Teeth", "label": "Number of teeth"},',
           f'    "FACE_WIDTH": {{"min": 1.0, "max": {_f(math.ceil(4 * lay["face_width"]))}, "step": 0.5, "unit": "mm", "group": "Teeth", "label": "Face width"}},',
           '    "BORE": {"min": 3.0, "max": 400.0, "step": 0.5, "unit": "mm", "group": "Bore", "label": "Bore Ø"},',
           "}", "",
           "part, gear = fw.spur_gear(MODULE, TEETH, FACE_WIDTH, bore=BORE, backlash=0.04 * MODULE"
           + (", keyway=True" if k else "") + ', name="Involute teeth")',
           "", "result = part", 'EXPECTED = {"bbox": gear["bbox"], "volume": gear["volume"], "solids": 1}', ""]
    return "\n".join(out)


def design_spacer(spec: dict[str, Any]) -> dict[str, Any]:
    bore, length = _num(spec.get("bore")), _num(spec.get("length"))
    if bore is None or length is None:
        raise MakeError("A spacer needs its bore and length (or the two parts it sits between).")
    od = _num(spec.get("od"))
    vals = {"bore": {"value": bore, "src": spec.get("bore_src") or "stated"},
            "length": {"value": length, "src": spec.get("length_src") or "stated"},
            "od": {"value": od or bore + 8, "src": "stated" if od else "bore + 8 mm"}}
    od = float(vals["od"]["value"])
    if od <= bore:
        raise MakeError("The spacer's outside Ø must be larger than its bore.")
    return {"kind": "spacer", "name": str(spec.get("name") or f"Spacer Ø{_g(bore)}×{_g(length)}")[:80],
            "material": str(spec.get("material") or "Steel 1045 (medium carbon)")[:80], "bore": bore, "od": od,
            "length": length, "values": vals}


def spacer_script(lay: dict[str, Any]) -> str:
    return "\n".join([
        (f'"""{lay["name"]}: a spacer ring made in Assembly Studio from the conversation (no AI geometry).\n\n'
        f"  bore Ø{_g(lay['bore'])}, outside Ø{_g(lay['od'])}, {_g(lay['length'])} long, axis along Z from Z = 0.\n"
        '"""\n'), "import math\n", "from build123d import *\n", "from aicad import fw\n", f'NAME = "{lay["name"]}"',
        f'MATERIAL = "{lay["material"]}"', "", f"BORE = {_f(lay['bore'])}  # mm", f"OD = {_f(lay['od'])}  # mm",
        f"LENGTH = {_f(lay['length'])}  # mm", "", "PARAMS = dict(BORE=BORE, OD=OD, LENGTH=LENGTH)", "PARAM_META = {",
        '    "BORE": {"min": 1.0, "max": 500.0, "step": 0.5, "unit": "mm", "group": "Spacer", "label": "Bore Ø"},',
        '    "OD": {"min": 2.0, "max": 600.0, "step": 0.5, "unit": "mm", "group": "Spacer", "label": "Outside Ø"},',
        '    "LENGTH": {"min": 0.5, "max": 500.0, "step": 0.5, "unit": "mm", "group": "Spacer", "label": "Length"},', "}",
        "", "ring = Cylinder(OD / 2, LENGTH, align=(Align.CENTER, Align.CENTER, Align.MIN))",
        "ring -= Pos(0, 0, -1) * Cylinder(BORE / 2, LENGTH + 2, align=(Align.CENTER, Align.CENTER, Align.MIN))",
        'part = fw.feature("Spacer ring", ring, od=OD, bore=BORE, length=LENGTH)', "", "result = part",
        'EXPECTED = {"bbox": [OD, OD, LENGTH], "volume": math.pi / 4 * (OD ** 2 - BORE ** 2) * LENGTH, "solids": 1}', ""])


def make(kind: str, spec: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """(layout, model script) of a direct part; MakeError when it can't be made this way."""
    if kind == "shaft":
        lay = design_shaft(spec)
        return lay, shaft_script(lay)
    if kind == "gear":
        lay = design_gear(spec)
        return lay, gear_script(lay)
    if kind == "spacer":
        lay = design_spacer(spec)
        return lay, spacer_script(lay)
    raise MakeError("Only shafts, spur gears and spacers are made directly; other parts go to the design agent.")


def assumed(lay: dict[str, Any]) -> list[str]:
    """The values the engineer did not state, in plain words ("seat Ø25 (assumed: a 2.5 mm shoulder ...)")."""
    labels = {"journal_l": "journal length", "seat_d": "seat Ø", "collar_d": "collar Ø", "hub_width": "hub width",
              "seat_l": "seat length", "collar_l": "collar length", "chamfer": "end chamfer", "key_length": "keyseat length",
              "groove_d": "groove Ø", "bore": "bore", "face_width": "face width", "od": "outside Ø", "length": "length"}
    out = []
    for k, v in lay.get("values", {}).items():
        if v["src"] == "stated":
            continue
        lab = labels.get(k, k)
        num = f"{lab}{_g(v['value'])} mm" if lab.endswith("Ø") else f"{lab} {_g(v['value'])} mm"
        out.append(f"{num} ({v['src'].removesuffix(' (assumed)').removeprefix('assumed: ')})")
    return out


# ----------------------------------------------------------------------------- Toolbox sizes from the context
def size_for_host(code: str, params: dict[str, Any] | None, host: dict[str, Any] | None
                  ) -> tuple[dict[str, float], list[str]]:
    """Toolbox parameters for a component brought in for a shaft (``host`` = trains.shaft_geom of it, or None):
    what the request gave wins; the rest follows the shaft. Returns (params, notes in plain words)."""
    p = {k: v for k, v in (params or {}).items() if v is not None}
    notes: list[str] = []
    seats = (host or {}).get("seats") or []
    keyseats = (host or {}).get("keyseats") or []
    grooves = (host or {}).get("grooves") or []
    if host is not None:
        if code == "bearing" and "SERIES" not in p:
            for s in sorted(seats, key=lambda s: s["d"]):
                got = bearing_bore_width(s["d"])
                if got:
                    p["SERIES"] = got[0]
                    notes.append(f"bore Ø{_g(s['d'])} = the shaft's journal")
                    break
        elif code == "spur_gear":
            ks = max(keyseats, key=lambda k: k["length"], default=None)
            seat = next((s for s in seats if ks and abs(s["d"] - ks["d"]) < 1e-6), None) or \
                (max(seats, key=lambda s: s["length"]) if seats else None)
            if "BORE" not in p and seat is not None:
                p["BORE"] = seat["d"]
                notes.append(f"bore Ø{_g(seat['d'])} = the shaft's {'keyed ' if ks else ''}seat")
            if ks and "KEY_B" not in p and abs(float(p.get("BORE", 0)) - ks["d"]) < 1e-6:
                k = din_key(ks["d"])
                p["KEY_B"], p["KEY_T2"] = k["b"], k["t2"]
                notes.append(f"hub keyway {_g(k['b'])} × {_g(k['t2'])} (DIN 6885) for the keyseat")
            if "B" not in p:
                if ks:
                    p["B"] = math.ceil(ks["length"] + 4)
                    notes.append(f"face width {_g(p['B'])} covers the {_g(ks['length'])} mm key with 2 mm each side")
                elif seat is not None and "M" in p:
                    p["B"] = min(10 * float(p["M"]), math.floor(seat["length"]))
                    notes.append(f"face width {_g(p['B'])} (10 × module, at most the seat length)")
        elif code == "parallel_key":
            ks = max(keyseats, key=lambda k: k["length"], default=None)
            if ks is not None:
                p.setdefault("D", ks["d"])
                if "L" not in p:
                    L = key_length_for(ks["length"], ks["b"])
                    if L:
                        p["L"] = L
                notes.append(f"{_g(ks['b'])} mm wide for the shaft's keyseat, {_g(p.get('L', 0))} long")
        elif code == "retaining_ring" and "D" not in p and grooves:
            p["D"] = grooves[0]["d1"]
            notes.append(f"for the shaft's Ø{_g(grooves[0]['d2'])} groove (DIN 471 for Ø{_g(grooves[0]['d1'])})")
    return toolbox.normalize(code, p), notes
