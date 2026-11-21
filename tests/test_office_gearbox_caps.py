"""Gearbox bearing caps on every seat, their cap screws and Hex's reading of standard parts (live "Gear Reducer"
program, 2026-11-19: only the input open cap was placed, its four M8 bolts clashed with it, and Hex read "Hex nut M8"
and "Washer M8" as hex bolts and "Oil plug M16" as a washer). Every expected value is a hand calculation:

* 6204: d 20, D 47, B 14; 6205: d 25, D 52, B 15 (ISO 15, the Toolbox table).
* M6 cap screws (the plan's), ISO 2306 tap drill 5.0, ISO 273 medium clearance 6.6, ISO 7089 washer OD 12.
* Ligament rule: wall between the seat and each tap drill >= max(3 mm, 0.5 d) = 3 for M6, so
  PCD = D + tap drill + 2 x 3, rounded up to 0.5 mm: 47 + 5 + 6 = 58 (input), 52 + 5 + 6 = 63 (output).
"""

from __future__ import annotations

import math
from typing import Any

import pytest
from test_office_orchestrator import office  # noqa: F401  (fixture)

from aicad.assembly import librarian
from aicad.office import icd, platform_env

# the live program's plan as Archie wrote it (with his Toolbox hints, some of them wrong)
REDUCER: dict[str, Any] = {"source": "archie", "summary": "Single stage 3:1 spur reducer", "assumptions": [
    "Shaft extensions come out on opposite sides; blind caps close the other bores."], "subassemblies": [
    {"name": "Housing", "description": "Split housing that carries both bearing pairs.", "parts": [
        # (the live plan said 95 high; the 124 mm gear needs 146, which the engineer accepted at the gate)
        {"name": "Housing base", "family": "machined", "complexity": 5, "qty": 1, "envelope": [210.0, 110.0, 146.0],
         "description": "Lower half of the split housing, cast-style aluminium, with mounting feet, a sump, two "
                        "half-bores of 47 mm and two of 52 mm at an 80 mm centre distance. Size assumed."},
        {"name": "Housing cover", "family": "machined", "complexity": 4, "qty": 1, "envelope": [210.0, 110.0, 80.0],
         "mounts_on": "Housing base", "description": "Upper half of the split housing with M8 flange bolt holes."},
        {"name": "Input open cap", "family": "turned", "complexity": 3, "qty": 1, "envelope": [72.0, 72.0, 18.0],
         "mounts_on": "Housing base",
         "description": "Flanged bearing cap for the 47 mm bore, with a 20x35x7 lip-seal recess and 4 x M6 holes."},
        {"name": "Input blind cap", "family": "turned", "complexity": 2, "qty": 1, "envelope": [72.0, 72.0, 14.0],
         "mounts_on": "Housing base",
         "description": "Closed flanged cap for the 47 mm bore, with a spigot that locates the bearing outer ring."},
        {"name": "Output open cap", "family": "turned", "complexity": 3, "qty": 1, "envelope": [78.0, 78.0, 18.0],
         "mounts_on": "Housing base",
         "description": "Flanged bearing cap for the 52 mm bore, with a 25x40x7 lip-seal recess and 4 x M6 holes."},
        {"name": "Output blind cap", "family": "turned", "complexity": 2, "qty": 1, "envelope": [78.0, 78.0, 14.0],
         "mounts_on": "Housing base",
         "description": "Closed flanged cap for the 52 mm bore, with a spigot that locates the bearing outer ring."},
        {"name": "Flange bolt M8x40", "family": "standard", "complexity": 1, "qty": 8, "toolbox": "hex_bolt",
         "description": "Hex bolt M8x40, class 8.8, joining the cover to the base."},
        {"name": "Hex nut M8", "family": "standard", "complexity": 1, "qty": 8, "toolbox": "hex_bolt",
         "description": "Hex nut M8 for the flange bolts."},
        {"name": "Washer M8", "family": "standard", "complexity": 1, "qty": 8, "toolbox": "hex_bolt",
         "description": "Plain washer M8 for the flange bolts."},
        {"name": "Dowel pin 6x20", "family": "standard", "complexity": 1, "qty": 2, "toolbox": "dowel",
         "description": "Dowel pin 6 mm x 20 that locates the cover to the base so the bores stay aligned."},
        {"name": "Cap screw M6x16", "family": "standard", "complexity": 1, "qty": 16, "toolbox": "bearing",
         "description": "Socket head cap screw M6x16 that fixes the four bearing caps."},
        {"name": "Oil plug M16", "family": "standard", "complexity": 1, "qty": 2, "toolbox": "washer",
         "description": "M16x1.5 plug with sealing washer, one for filling or breathing and one for draining."}]},
    {"name": "Input shaft group", "description": "High-speed pinion shaft.", "parts": [
        {"name": "Input shaft", "family": "turned", "complexity": 3, "qty": 1, "envelope": [25.0, 25.0, 170.0],
         "description": "Steel shaft (C45 or 42CrMo4) with 20 mm bearing seats and a 22 mm pinion seat. Length assumed."},
        {"name": "Pinion", "family": "gear", "complexity": 3, "qty": 1, "envelope": [44.0, 44.0, 22.0],
         "mounts_on": "Input shaft", "module": 2.0, "teeth": 20,
         "description": "Spur pinion, 20T, module 2, PCD 40, 22 mm face, keyed, case-hardened steel."},
        {"name": "Bearing 6204", "family": "standard", "complexity": 1, "qty": 2, "toolbox": "bearing",
         "description": "Deep-groove ball bearing 6204, 20x47x14, supporting the input shaft."}]},
    {"name": "Output shaft group", "description": "Low-speed gear shaft.", "parts": [
        {"name": "Output shaft", "family": "turned", "complexity": 3, "qty": 1, "envelope": [32.0, 32.0, 180.0],
         "description": "Steel shaft (42CrMo4) with 25 mm bearing seats and a 30 mm gear seat. Length assumed."},
        {"name": "Output gear", "family": "gear", "complexity": 3, "qty": 1, "envelope": [124.0, 124.0, 20.0],
         "mounts_on": "Output shaft", "module": 2.0, "teeth": 60,
         "description": "Spur gear, 60T, module 2, PCD 120, 20 mm face, keyed. Steel."},
        {"name": "Bearing 6205", "family": "standard", "complexity": 1, "qty": 2, "toolbox": "bearing",
         "description": "Deep-groove ball bearing 6205, 25x52x15, supporting the output shaft."}]}]}
BRIEF = "Build a Single stage 3:1 reducer with Spur Gears"


def _parts() -> tuple[list[dict[str, Any]], dict[str, str]]:
    parts = []
    for si, s in enumerate(REDUCER["subassemblies"], start=1):
        for p in s["parts"]:
            n = len(parts) + 1
            parts.append({"id": f"i_s{si}_p{n}", "name": p["name"], "family": p["family"], "qty": p["qty"],
                          "description": p["description"], "complexity": p["complexity"], "sub": f"i_s{si}",
                          **{k: p[k] for k in ("envelope", "mounts_on", "module", "teeth") if k in p}})
    return parts, {p["name"]: p["id"] for p in parts}


def test_every_seat_gets_its_cap_with_a_ligament_rule() -> None:
    parts, ids = _parts()
    sk, ifs = icd.build(parts, BRIEF)
    assert sk["layout"] == "gearbox"
    caps = [f for f in ifs if f["kind"] == "hole_pattern" and f["data"].get("cap")]
    S_IN, S_OUT = sk["items"][ids["Input shaft"]], sk["items"][ids["Output shaft"]]
    x_in, z = S_IN["copies"][0][0], S_IN["copies"][0][2]
    x_out = S_OUT["copies"][0][0]
    assert x_out - x_in == 80  # m (z1 + z2) / 2 = 2 (20 + 60) / 2
    seat = next(f for f in ifs if f["kind"] == "bearing_seat" and f["b"]["item"] == ids["Input shaft"])["data"]
    y0, y1 = seat["z"]
    # the shafts leave through the +Y wall: open caps there, blind caps over the -Y seats; by name
    got = [(f["b"]["name"], f["data"]["cap"], f["data"]["normal"][1], f["data"]["centre"], f["data"]["pcd"],
            f["data"]["plane_z"]) for f in caps]
    assert got == [("Input blind cap", "blind", -1, [x_in, z], 58, y0), ("Input open cap", "open", 1, [x_in, z], 58, y1),
                   ("Output blind cap", "blind", -1, [x_out, z], 63, y0),
                   ("Output open cap", "open", 1, [x_out, z], 63, y1)]
    for f in caps:
        d = f["data"]
        # the plan's cap screws (not the cover's flange bolts), M6 into tapped holes in the wall
        assert (d["fastener"], d["fastener_item"], d["count"], d["d"]) == ("M6", ids["Cap screw M6x16"], 4, 6.6)
        # max(2.5 x 6 + 3, 2 x 6 + 2 x 1.0 + 5) = max(18, 19): the screw length window spans one 5 mm step (PD-285)
        assert d["tapped"] == {"d": 5.0, "depth": 19.0, "thread": "M6"}
        lig = d["pcd"] / 2 - d["seat_D"] / 2 - d["tapped"]["d"] / 2
        assert lig == pytest.approx(3.0)  # (58 - 47) / 2 - 2.5 and (63 - 52) / 2 - 2.5
        r = d["pcd"] / 2 / math.sqrt(2)  # four holes at 45, 135, 225, 315 deg
        assert d["positions"][0] == [round(d["centre"][0] + r, 2), round(d["centre"][1] + r, 2)]
        # the relief over the turning inner ring: Ø (d + D) / 2, 1 mm deep
        assert d["relief"] == {"d": (20 + 47) / 2 if d["seat_D"] == 47 else (25 + 52) / 2, "depth": 1.0}
    # the cover keeps its M8 flange bolts
    lid = ifs[0]["data"]
    assert (lid["fastener"], lid["fastener_item"]) == ("M8", ids["Flange bolt M8x40"])
    it = sk["items"]
    # open caps pass the shaft (Ø + 2), blind caps are closed; OD = PCD + washer 12
    assert it[ids["Input open cap"]]["bore"] == S_IN["d"] + 2 and "bore" not in it[ids["Input blind cap"]]
    assert it[ids["Output open cap"]]["bore"] == S_OUT["d"] + 2 and "bore" not in it[ids["Output blind cap"]]
    assert it[ids["Input open cap"]]["size"][0] == 70 and it[ids["Output blind cap"]]["size"][0] == 75
    # caps sit on the wall faces, coaxial with their shafts
    assert it[ids["Input blind cap"]]["copies"] == [[x_in, y0 - 14 / 2, z]]
    assert it[ids["Output open cap"]]["copies"] == [[x_out, y1 + 18 / 2, z]]
    assert not any("has no interface" in n for n in sk["notes"])
    assert any(n.startswith("Bearing caps: Input blind cap (blind) over the -Y seat") for n in sk["notes"])
    assert not [x for x in icd.issues(sk, ifs) if x["code"] in ("no_interface", "ligament", "hole_overlap", "rim")]
    # the cap's features: four Ø6.6 holes through and the relief from its mounting face
    feats = icd.item_features(sk, ifs, ids["Input blind cap"])
    rel = [f for f in feats if f["type"] == "seat"]
    assert len([f for f in feats if f["type"] == "hole"]) == 4 and len(rel) == 1 and rel[0]["d"] == 33.5
    assert abs(rel[0]["z1"] - rel[0]["z0"]) == 1.0
    ex = icd.excerpt(sk, {"version": 1, "interfaces": ifs}, ids["Input blind cap"])
    assert "a blind cap: closed, no bore" in ex and "relief Ø33.5 × 1 deep" in ex


def test_the_old_ligament_is_flagged() -> None:
    """The live ICD: M8 on PCD 58 over the Ø47 seat leaves (58 - 47) / 2 - 6.8 / 2 = 2.1 mm (< max(3, 4) = 4)."""
    parts, ids = _parts()
    sk, ifs = icd.build(parts, BRIEF)
    f = next(f for f in ifs if f["b"]["item"] == ids["Input open cap"])
    f["data"].update(fastener="M8", fastener_size=8, d=9.0, tapped={"d": 6.8, "depth": 23.0, "thread": "M8"})
    w = [x for x in icd.issues(sk, ifs) if x["code"] == "ligament"]
    assert len(w) == 1 and w[0]["severity"] == "warning" and "leave 2.1 mm" in w[0]["text"]


@pytest.mark.parametrize(("text", "code", "title"), [
    ("Hex nut M8", "hex_nut", "Hex nut ISO 4032 M8"),
    ("Washer M8", "washer", "Washer ISO 7089 M8"),
    ("Oil plug M16", None, None),
    ("Cap screw M6x16", "shcs", "Socket head cap screw ISO 4762 M6×16"),
    ("Socket head cap screw M8x25", "shcs", "Socket head cap screw ISO 4762 M8×25"),
    ("Lock washer M8", None, None),  # a spring lock washer is not an ISO 7089 plain washer
    ("Drain plug M16x1.5", None, None),
    ("Breather M12", None, None),
    ("Flange bolt M8x40", "hex_bolt", "Hex bolt ISO 4017 M8×40"),
    ("Taper roller bearing 30205", None, None),
    ("Helical gear m2 30 teeth", None, None),
    ("Bearing 6204, held by a circlip", "bearing", "Ball bearing 6204"),
])
def test_hex_reads_the_head_noun(text: str, code: str | None, title: str | None) -> None:
    r = librarian.read_toolbox(text)
    assert (r and (r["code"], r["title"])) == ((code, title) if code else None)


def test_hex_never_substitutes_another_kind_of_part() -> None:
    """The live plan's items with Archie's wrong Toolbox hints: the head noun wins, the hint is used only for the same
    family; a plug has no Toolbox family, so it is designed as a bought-out part."""
    plan_items = {p["name"]: p for s in REDUCER["subassemblies"] for p in s["parts"]}
    doc = {"items": [{"id": n, "description": p["description"], "toolbox": p.get("toolbox")}
                     for n, p in plan_items.items()]}
    want = {"Hex nut M8": ("hex_nut", "Hex nut ISO 4032 M8"), "Washer M8": ("washer", "Washer ISO 7089 M8"),
            "Cap screw M6x16": ("shcs", "Socket head cap screw ISO 4762 M6×16"),
            "Flange bolt M8x40": ("hex_bolt", "Hex bolt ISO 4017 M8×40"), "Oil plug M16": None}
    for name, w in want.items():
        hit = platform_env.hex_lookup(doc, {"title": name, "kind": "standard", "item_id": name}, [])
        assert (hit and (hit["code"], hit["title"])) == w, (name, hit)


def test_reducer_assembles_with_every_cap_screwed_down(office: Any) -> None:  # noqa: F811
    """The live plan end to end with simulated agents: four caps on four seats, 16 ISO 4762 M6 stacks through the
    caps into the walls, the cover's four M8 stacks, nothing in the parts bin, no clash anywhere, and every planned
    fastener either in a stack or reported."""
    from test_office_icd import _asm
    from test_office_orchestrator import _program, _wait

    from aicad.assembly import store as astore
    from aicad.office import program_assembly

    c = office
    v = _program(c, "reducer@x.com", REDUCER, brief=BRIEF)
    pid = v["id"]
    assert v["assembly"]["status"] == "ready" and v["assembly"]["clashes"] == [], v["assembly"].get("summary")
    c.post(f"/api/office/programs/{pid}/run")
    v = _wait(c, pid, lambda v: v["orchestrator"]["state"] in ("complete", "blocked", "stopped"), timeout=2400)
    assert v["status"] == "complete", [(t["title"], t["column"], (t.get("run") or {}).get("status")) for t in v["tickets"]]
    by = {t["title"]: t for t in v["tickets"]}
    assert [by[n]["reuse"]["code"] for n in ("Hex nut M8", "Washer M8", "Cap screw M6x16")] == ["hex_nut", "washer", "shcs"]
    assert (by["Oil plug M16"].get("reuse") or {}).get("source") != "toolbox"
    aroot = _asm(c)[0]
    st = v["assembly"]
    final = astore.load(aroot, st["final"])
    assert not [i["name"] for i in final["instances"] if (i.get("office") or {}).get("bin")]
    caps = {i["name"]: i for i in final["instances"] if (i.get("office") or {}).get("item") and "cap" in i["name"]}
    assert sorted(caps) == ["Input blind cap", "Input open cap", "Output blind cap", "Output open cap"]
    stacks = [g for g in final["groups"] if g.get("kind") == "fastener"]
    specs = sorted((g["spec"]["style"], g["spec"]["size"]) for g in stacks)
    assert specs == [("hex_bolt", 8)] * 4 + [("shcs", 6)] * 16, specs
    # every cap stack sits on a cap: its hole is a hole of one of the four caps
    cap_ids = {i["id"] for i in caps.values()}
    assert sum(1 for g in stacks if g["hole"]["inst"] in cap_ids) == 16
    v = _wait(c, pid, lambda v: program_assembly.clash_status(v["assembly"])["status"] in ("done", "failed"),
              timeout=900)
    cs = program_assembly.clash_status(v["assembly"])
    assert (cs["status"], cs["count"]) == ("done", 0), (cs, v["assembly"].get("clashes"))
    # every planned fastener is in a stack or reported: the nuts (the joints are tapped), the washers beyond the
    # cover stacks' four, the bolts beyond the cover's four holes, and the plugs (no interface)
    said = " | ".join(cm["text"] for t in v["tickets"] for cm in t.get("comments") or [])
    for bit in ("Hex nut M8: no bolt stack", "Washer M8: 4 of 8 are in the bolt stacks",
                "4 more than the ICD's joints take", "Oil plug M16 has no interface"):
        assert bit in said, (bit, said[-3000:])
