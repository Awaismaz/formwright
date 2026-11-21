"""Radial shaft seals (DIN 3760) on the fast path: the Toolbox seal, the layout's ``seal_seat`` in the open caps, the
cap's recess, Hex and Fitz (planetary benchmark A11, 2026-11-21: two seals the layout didn't place sent the program to
the master model). Every expected value is a hand calculation:

* DIN 3760 / ISO 6194-1 (the Toolbox table, verify): d 20 -> D 35, b 7; d 30 -> D 42, b 7.
* A11 (fixture ``golden/seals/planetary_with_seals.graph.json``): both shafts Ø20 where they leave the housing; the
  housing W = t_in + stack + t_out = 32 + 59 + 32 = 123 (t = 2 x 14 + 4 for two 6204 per end wall; stack = ring
  20 + 2 x 3, running gap 1, carrier 20, room 12), so the end walls' outer faces are at Y = ±61.5; the caps are
  round(max(8, 0.25 x 47)) = 12 thick (>= b + relief + 2 = 7 + 1 + 2 = 10), outer faces at ±73.5, so the seals
  span Y -73.5 .. -66.5 and 66.5 .. 73.5, coaxial with the shafts.
* Reducer (golden case c with a seal on each open cap): shafts leave by the +Y wall; input 6204 journal Ø20 ->
  20 x 35 x 7, output 6206 journal Ø30 -> 30 x 42 x 7; caps 12 and round(0.25 x 62) = 16 thick.
* The seal section (``toolbox.seal_profile``), h = (D - d) / 2: a nine-point polygon; its volume by Pappus,
  triangle by triangle (a fan from the first vertex, signed areas): V = 2 pi sum A_t (r1 + r2 + r3) / 3.
"""

from __future__ import annotations

import copy
import itertools
import json
import math
from pathlib import Path
from typing import Any

import pytest

from aicad import toolbox
from aicad.assembly import librarian
from aicad.graph import compile as gc
from aicad.graph import intent, model, validate
from aicad.graph import office as goffice
from aicad.office import direct, frames, generators, icd, platform_env

HERE = Path(__file__).resolve().parent
FIXTURE = json.loads((HERE / "golden" / "seals" / "planetary_with_seals.graph.json").read_text(encoding="utf-8"))
CASES = HERE.parent / "src" / "aicad" / "eval" / "golden_cases"


# ============================================================================ the Toolbox seal
def _fan_pappus(pts: list[tuple[float, float]]) -> float:
    a0 = pts[0]
    v = 0.0
    for p, q in itertools.pairwise(pts[1:]):
        area = ((p[0] - a0[0]) * (q[1] - a0[1]) - (q[0] - a0[0]) * (p[1] - a0[1])) / 2  # signed
        v += 2 * math.pi * area * (a0[0] + p[0] + q[0]) / 3
    return abs(v)


def test_seal_volume_by_hand() -> None:
    # d 20, D 35, b 7: h = 7.5; the section's points written out by hand from the fractions of h and b
    pts = [(12.25, 0.0), (17.5, 0.0), (17.5, 7.0), (16.375, 7.0), (16.375, 1.75), (13.75, 1.75), (11.5, 4.9),
           (10.0, 4.9), (10.0, 3.85)]
    assert [c for q in toolbox.seal_profile(20, 35, 7) for c in q] == pytest.approx([c for q in pts for c in q])
    want = _fan_pappus(pts)
    # the case alone is a tube Ø35 / Ø32.75 x 7: the seal is more than that and less than the full annulus
    assert math.pi / 4 * (35 ** 2 - 32.75 ** 2) * 7 < want < math.pi / 4 * (35 ** 2 - 20 ** 2) * 7
    shape, exp = toolbox.build("shaft_seal", D=20)
    assert exp == {"bbox": [35.0, 35.0, 7.0], "volume": pytest.approx(want, rel=1e-12), "solids": 1}
    assert shape.volume == pytest.approx(want, rel=1e-6) and shape.is_valid
    bb = shape.bounding_box()
    assert (bb.min.Z, bb.max.Z) == pytest.approx((0.0, 7.0)) and bb.max.X == pytest.approx(17.5)
    # the lip meets the shaft at d / 2 (a contact at nominal, no interference)
    from build123d import Cylinder

    assert (shape & Cylinder(10.0, 40)) is None or (shape & Cylinder(10.0, 40)).volume < 1e-9
    assert shape.distance_to(Cylinder(10.0, 40)) < 1e-9
    for d in (12, 30, 60):  # every size is the same simple polygon, scaled: valid, its Pappus volume
        D, b = toolbox.seal_row(d)
        s, e = toolbox.build("shaft_seal", D=d)
        assert s.is_valid and e["volume"] == pytest.approx(_fan_pappus(toolbox.seal_profile(d, D, b)), rel=1e-12)


def test_seal_table_is_shared_and_read_by_hex_and_the_studio() -> None:
    assert toolbox.seal_row(20) == (35.0, 7.0) and toolbox.seal_row(30) == (42.0, 7.0)
    assert generators.SEALS is toolbox.SEALS and generators.seal_for(25) == (40, 7)
    assert icd.SEALS[20.0] == (35.0, 7.0) and "verify" in toolbox.SEALS_SOURCE
    assert toolbox.VERSION >= 4
    with pytest.raises(toolbox.ToolboxError):
        toolbox.normalize("shaft_seal", {"D": 21})
    m = toolbox.match("Radial shaft seal 25x40x7")
    assert m[0]["code"] == "shaft_seal" and m[0]["params"] == {"D": 25}
    assert toolbox.match("oil seal for a 30 mm shaft")[0]["params"] == {"D": 30}
    assert all(x["code"] != "shaft_seal" for x in toolbox.match("stepped shaft Ø20 with a keyway"))
    assert all(x["code"] != "shaft" for x in toolbox.match("lip seal for the input shaft"))
    assert librarian.read_toolbox("Lip seal 20x35x7")["params"] == {"D": 20}  # type: ignore[index]
    assert librarian.read_toolbox("Input shaft seal")["code"] == "shaft_seal"  # type: ignore[index]
    for t in ("O-ring 20x2", "Cover gasket", "Oil seal carrier", "Oil plug M16, with sealing washer"):
        assert librarian.read_toolbox(t) is None, t


# ============================================================================ A11: the planetary set with its seals
def _finish(g: model.DesignGraph) -> goffice.OfficePlan:
    out = goffice.finish(goffice.OfficePlan(None), g, validate.issues(g))
    assert out.error is None, out.error
    return out


def _doc(out: goffice.OfficePlan, brief: str) -> dict[str, Any]:
    sk, ifs = gc.to_icd(out.graph, out.plan)
    parts = gc.plan_parts(out.plan)
    return {"id": "p", "name": "P", "skeleton": sk, "icd": {"version": 1, "status": "approved", "interfaces": ifs},
            "brief": brief, "plan": {**out.plan, "graph": {"data": out.graph.dump()}},
            "items": [{"id": p["id"], "name": p["name"], "description": p["description"]} for p in parts]}


def _id(doc: dict[str, Any], name: str) -> str:
    return next(i["id"] for i in doc["items"] if i["name"] == name)


def _a11() -> tuple[goffice.OfficePlan, dict[str, Any]]:
    out = _finish(model.DesignGraph.load(copy.deepcopy(FIXTURE["graph"])))
    return out, _doc(out, FIXTURE["brief"])


def test_a11_takes_the_fast_path_and_the_icd_seats_both_seals() -> None:
    from aicad.master import decide

    out, doc = _a11()
    d = decide.decide(out.plan, FIXTURE["brief"], "Planetary")
    assert d["path"] == "fast", d["reasons"]  # A11: "Input shaft seal: no interface in this layout places it"
    sk, ifs = doc["skeleton"], doc["icd"]["interfaces"]
    assert icd.problems(sk, ifs) == [] and not [x for x in icd.issues(sk, ifs) if x["code"] == "part_unplaced"]
    seals = {f["b"]["name"]: f for f in ifs if f["kind"] == "seal_seat"}
    assert sorted(seals) == ["Input shaft seal", "Output shaft seal"]
    fi, fo = seals["Input shaft seal"], seals["Output shaft seal"]
    assert (fi["a"]["name"], fo["a"]["name"]) == ("Input open cap", "Output open cap")
    for f in (fi, fo):
        x = f["data"]
        assert (x["d"], x["D"], x["b"], x["fit"], x["shaft_d"]) == (20, 35, 7, "H8", 20)
        assert x["axis"] == sk["items"][x["shaft_item"]]["copies"][0][::2]  # coaxial with its shaft
        assert sk["items"][f["a"]["item"]]["size"][2] == 12  # the cap: round(0.25 x 47)
    assert (fi["data"]["z"], fi["data"]["face_z"], fi["data"]["side"]) == ([-73.5, -66.5], -73.5, -1)
    assert (fo["data"]["z"], fo["data"]["face_z"], fo["data"]["side"]) == ([66.5, 73.5], 73.5, 1)
    assert sk["items"][_id(doc, "Input shaft")]["copies"][0][1] - sk["items"][_id(doc, "Input shaft")]["size"][2] / 2 \
        < -73.5  # the shaft runs on through the seal
    # the cap's recess in its part frame: from the outer face (the -Y cap's outer face is its -Z face), 7 deep, H8
    for cap, span in (("Input open cap", (-6.0, 1.0)), ("Output open cap", (-1.0, 6.0))):
        rec = [x for x in icd.item_features(sk, ifs, _id(doc, cap)) if x.get("seal")]
        assert len(rec) == 1 and (rec[0]["d"], rec[0]["fit"], rec[0]["z0"], rec[0]["z1"]) == (35, "H8", *span)
    # where Fitz puts the Toolbox seal: its air face on the outer face, its +Z into the housing
    si = icd.seated(ifs, _id(doc, "Input shaft seal"))
    so = icd.seated(ifs, _id(doc, "Output shaft seal"))
    assert si is not None and so is not None and si["code"] == so["code"] == "shaft_seal"
    assert si["at"] == [[0.0, -73.5, fi["data"]["axis"][1]]] and so["at"] == [[0.0, 73.5, fo["data"]["axis"][1]]]
    assert frames.apply(si["Rs"][0], [0, 0, 1]) == [0, 1, 0] and frames.apply(so["Rs"][0], [0, 0, 1]) == [0, -1, 0]
    assert all(frames.det(R) == 1 for R in (si["Rs"][0], so["Rs"][0]))
    # Hex takes the seal the ICD sized from the Toolbox
    hit = platform_env.hex_lookup(doc, {"title": "Input shaft seal", "kind": "standard",
                                        "item_id": _id(doc, "Input shaft seal")}, [])
    assert hit is not None and hit["code"] == "shaft_seal" and hit["params"] == {"D": 20}
    assert hit["title"] == "Radial shaft seal DIN 3760 A 20×35×7"


def test_a11_caps_are_built_from_the_interfaces_with_the_icd_recess() -> None:
    _out, doc = _a11()
    for cap in ("Input open cap", "Output open cap"):
        p = direct.plan(doc, {"kind": "part", "item_id": _id(doc, cap), "title": cap, "qty": 1, "id": "t"})
        assert p["path"] == "direct", p.get("reasons")
        src = p["script"]
        assert "SEAL_D = 35.0" in src and "SEAL_WIDTH = 7.0" in src and "the ICD's H8" in src
        assert "lip seal recess" in p["summary"]


def test_the_seal_seats_without_interference(tmp_path: Path) -> None:
    """Kernel check: the generator-built caps and shafts, the Toolbox seals and bearings, placed where Fitz puts them,
    overlap nowhere (< 1e-6 mm³); each seal touches its cap (the recess) and its shaft (the lip, at nominal); Gage
    finds the recess on the cap."""
    import numpy as np
    from build123d import Location
    from test_office_icd import _prepare

    from aicad.assembly.geometry import _trsf
    from aicad.office import conformance, program_assembly

    _out, doc = _a11()
    sk, ifs = doc["skeleton"], doc["icd"]["interfaces"]

    def at(shape: Any, T12: list[float]) -> Any:
        T = np.array(list(T12) + [0, 0, 0, 1], dtype=float).reshape(4, 4)
        return shape.moved(Location(_trsf(T)))

    placed: dict[str, Any] = {}
    for name in ("Input open cap", "Output open cap", "Input shaft", "Output shaft"):
        p = direct.plan(doc, {"kind": "part", "item_id": _id(doc, name), "title": name, "qty": 1, "id": "t"})
        ns: dict[str, Any] = {}
        exec(compile(p["script"], name, "exec"), ns)  # noqa: S102 - our own generator's script
        shape = ns["result"]
        if "cap" in name:
            res = conformance.measure(sk, doc["icd"], _id(doc, name), *_prepare(tmp_path, shape, name.replace(" ", "_")))
            assert res["ok"], [r for x in res["interfaces"] for r in x["rows"] if not r["ok"]]
            assert any("lip seal recess" in r["feature"] and r["ok"] for x in res["interfaces"] for r in x["rows"])
        placed[name] = at(shape, program_assembly.place(sk, _id(doc, name), 0))
    for name in ("Input shaft seal", "Output shaft seal", "Input shaft bearing", "Output shaft bearing"):
        seat = icd.seated(ifs, _id(doc, name))
        assert seat is not None
        shape, _e = toolbox.build(seat["code"], **seat["params"])
        for n, p in enumerate(seat["at"]):
            R = seat["Rs"][n] if seat.get("Rs") else seat.get("R") or frames.IDENT
            placed[f"{name} {n}"] = at(shape, frames.to12(R, p))
    names = sorted(placed)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            v = sum((x & y).volume if (x & y) is not None else 0.0
                    for x in placed[a].solids() for y in placed[b].solids())
            assert v < 1e-6, (a, b, v)
    for side in ("Input", "Output"):
        seal = placed[f"{side} shaft seal 0"]
        assert seal.distance_to(placed[f"{side} open cap"]) < 1e-6 and seal.distance_to(placed[f"{side} shaft"]) < 1e-6
        bb = seal.bounding_box()
        assert (bb.max.Y - bb.min.Y) == pytest.approx(7.0) and (bb.max.X - bb.min.X) == pytest.approx(35.0)


# ============================================================================ the parallel gearbox
def _reducer(extra: list[dict[str, Any]], conns: list[dict[str, Any]]) -> tuple[goffice.OfficePlan, dict[str, Any]]:
    d = json.loads((CASES / "c_reducer.intent.json").read_text(encoding="utf-8"))
    r = d["reply"]
    r["components"] += extra
    r["connections"] += conns
    g, iss, _qs = intent.compile_reply(r, d["name"], d["brief"])
    assert not [i for i in iss if i["severity"] == "error"], iss
    out = _finish(g)
    return out, _doc(out, d["brief"])


def test_gearbox_seals_on_both_open_caps() -> None:
    from aicad.master import decide

    out, doc = _reducer([{"id": f"{s}_seal", "kind": "seal", "name": f"{s.capitalize()} shaft seal"}
                         for s in ("input", "output")],
                        [{"kind": "mounted_on", "host": f"{s}_open_cap", "guest": f"{s}_seal"}
                         for s in ("input", "output")])
    assert decide.decide(out.plan, doc["brief"], "Reducer")["path"] == "fast"
    sk, ifs = doc["skeleton"], doc["icd"]["interfaces"]
    assert icd.problems(sk, ifs) == []
    seals = {f["b"]["name"]: f for f in ifs if f["kind"] == "seal_seat"}
    assert sorted(seals) == ["Input shaft seal", "Output shaft seal"]
    y1 = sk["items"][_id(doc, "Housing base")]["size"][1] / 2  # the +Y wall's outer face: the shafts leave there
    for name, cap, d, D, H in (("Input shaft seal", "Input open cap", 20, 35, 12),
                               ("Output shaft seal", "Output open cap", 30, 42, 16)):
        x = seals[name]["data"]
        assert seals[name]["a"]["name"] == cap and (x["d"], x["D"], x["b"], x["side"]) == (d, D, 7, 1)
        assert sk["items"][_id(doc, cap)]["size"][2] == H
        assert (x["face_z"], x["z"]) == (y1 + H, [y1 + H - 7, y1 + H])
        sh = sk["items"][x["shaft_item"]]
        assert x["axis"] == sh["copies"][0][::2] and sh["copies"][0][1] + sh["size"][2] / 2 > y1 + H
        p = direct.plan(doc, {"kind": "part", "item_id": _id(doc, cap), "title": cap, "qty": 1, "id": "t"})
        assert p["path"] == "direct" and f"SEAL_D = {D:.1f}" in p["script"], p.get("reasons")
    assert not any(f["a"]["name"].endswith("blind cap") for f in seals.values())


def test_gearbox_seals_on_the_housing_go_to_the_open_caps_by_name() -> None:
    """Two seals of one line, on the housing (no cap named): one in each open cap, where a shaft leaves; a seal
    named after the output shaft takes the output cap first."""
    _out, doc = _reducer([{"id": "seals", "kind": "seal", "name": "Shaft seals", "qty": 2},
                         {"id": "out_seal", "kind": "seal", "name": "Output seal", "qty": 1}],
                        [{"kind": "mounted_on", "host": "housing_base", "guest": "seals"},
                         {"kind": "mounted_on", "host": "output_shaft", "guest": "out_seal"}])
    sk, ifs = doc["skeleton"], doc["icd"]["interfaces"]
    got = sorted((f["b"]["name"], f["a"]["name"]) for f in ifs if f["kind"] == "seal_seat")
    assert got == [("Output seal", "Output open cap"), ("Shaft seals #1", "Input open cap")]
    # the second "Shaft seals" piece has no open cap left: said, and it stays in the parts bin (a warning, not a gate)
    assert any("Shaft seals: 1 of 2 have no open cap" in n for n in sk["notes"])
    assert icd.problems(sk, ifs) == []


# ============================================================================ the program, end to end (simulated)
def test_a11_program_runs_with_seals_seated_and_no_clash(tmp_path: Path) -> None:
    """Golden case (l), A11's intent reply replayed through the Design Office with simulated agents: the fast path,
    both seals fitted by Fitz in their caps (Toolbox, 0 tokens), 0 clashes, nothing in the parts bin, no placeholder
    left, every expectation of the case holds (each seal inside its cap along Y, touching its shaft)."""
    from aicad.eval import golden, golden_run

    cases = golden.load_cases(["l"])
    assert [c["id"] for c in cases] == ["planetary-seals"]
    # the design-graph path (the default for everyone, PD-110) and the master-model rule on (tests pin both off)
    rec = golden_run.run_suite(cases, "simulated", work=tmp_path, history=tmp_path / "hist", log=lambda *a: None,
                               flags={"FW_DESIGN_GRAPH": "1", "FW_MASTER_MODEL": "auto"})[0]
    bad = [e for e in rec.get("expectations") or [] if e["ok"] is False]
    assert rec["passed"], (rec.get("error"), rec.get("stopped"), bad)
    m = rec["metrics"]
    assert (m["tokens"], m["clashes"], m["binned"], m["placeholders"]) == (0, 0, 0, 0), m
    ids = {e["id"] for e in rec["expectations"] if e["ok"] is True}
    assert {"path", "count.1", "reuse.1", "reuse.2", "within.1", "within.2", "touch.1", "touch.2"} <= ids, sorted(ids)
