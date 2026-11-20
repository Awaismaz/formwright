"""Drawing depth batch: cosmetic threads (CAD-027), detail views (DRW-011), GD&T only from input (DRW-013), ICD
datums / frames on Design Office part sheets (CD-021) and STEP-in drawings (DRW-016).

Every expected number is a hand value from the inputs (ISO 261 / ISO 724 tables, fixture sizes), never measured from
the built shape or the generated sheet.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

import pytest

from aicad import fw, threads
from aicad.drawing import DrawingInputError, detail, gdt
from aicad.drawing.generate import generate

L, W, T = 100.0, 60.0, 20.0
DRILL, DRILL_DEPTH, THREAD_DEPTH = 5.0, 15.0, 12.0  # M6 coarse: tap drill d - P = 5
META = {"title": "Tapped block", "drawing_no": "FW-T", "date": "2026-11-18"}


# ----------------------------------------------------------------------------- ISO 261 table and callout text
def test_thread_table_values_and_designations() -> None:
    assert threads.COARSE[6.0] == 1.0 and threads.COARSE[10.0] == 1.5 and threads.COARSE[24.0] == 3.0
    assert threads.pitches(10) == [1.5, 1.25, 1.0] and threads.pitches(6) == [1.0]
    b = threads.basic(6, 1.0)
    assert b["minor_int"] == pytest.approx(round(6 - 1.082532, 3)) and b["minor_ext"] == pytest.approx(round(6 - 1.226869, 3))
    assert b["tap_drill"] == 5.0
    assert threads.parse("M10x1.25-6H") == {"size": 10.0, "pitch": 1.25, "cls": "6H"}
    assert threads.parse("M8")["pitch"] == 1.25
    t = threads.resolve({"size": 6, "depth": THREAD_DEPTH}, internal=True, bore=DRILL, length=DRILL_DEPTH)
    assert t["designation"] == "M6×1-6H" and t["series"] == "coarse" and t["depth"] == THREAD_DEPTH
    assert threads.callout({**t, "thru": False}, 4) == "4X M6×1-6H ▽12"
    full = threads.resolve({"size": 6}, internal=True, bore=DRILL, length=None)
    assert threads.callout({**full, "thru": True}) == "M6×1-6H THRU"
    ext = threads.resolve({"designation": "M20x1.5"}, internal=False, bore=20.0)
    assert ext["designation"] == "M20×1.5-6g" and ext["series"] == "fine" and threads.callout(ext) == "M20×1.5-6g"
    # a depth equal to the hole is the full thread
    assert threads.resolve({"size": 6, "depth": 15}, internal=True, bore=5, length=15)["depth"] is None
    for bad, kw in (({"size": 7}, {}), ({"size": 6, "pitch": 1.25}, {}), ({"size": 6, "cls": "6g"}, {}),
                    ({"size": 6}, {"bore": 6.6}), ({"size": 6, "depth": 20}, {"bore": 5, "length": 15})):
        with pytest.raises(threads.ThreadError):
            threads.resolve(bad, internal=True, **kw)
    with pytest.raises(threads.ThreadError):
        threads.resolve({"size": 20}, internal=False, bore=19.0)


def test_hole_thread_validation_in_the_studio_api() -> None:
    from fastapi import HTTPException

    from aicad.platform.routers.studio import validate_feature

    base = {"op": "hole", "point": [0, 0, 20], "normal": [0, 0, 1], "d": 5, "depth": 15}
    out = validate_feature({**base, "thread": {"size": 6, "depth": 12}})
    assert out["thread"]["designation"] == "M6×1-6H" and out["thread"]["internal"] is True
    with pytest.raises(HTTPException) as e:
        validate_feature({**base, "d": 6.6, "thread": {"size": 6}})
    assert e.value.status_code == 422 and "tap drill" in e.value.detail
    th = validate_feature({"op": "thread", "face": {"point": [10, 0, 5]}, "thread": {"designation": "M20x1.5-6g"}})
    assert th["thread"] == {"size": 20.0, "pitch": 1.5, "depth": None, "cls": "6g"}
    with pytest.raises(HTTPException):
        validate_feature({"op": "thread", "face": {"point": [0, 0, 0]}, "thread": {"size": 7}})


# ----------------------------------------------------------------------------- fw: metadata, geometry unchanged
def _block() -> Any:
    from build123d import Align, Box

    return Box(L, W, T, align=(Align.CENTER, Align.CENTER, Align.MIN))


def _tapped_features() -> list[dict[str, Any]]:
    th = threads.resolve({"size": 6, "depth": THREAD_DEPTH}, internal=True, bore=DRILL, length=DRILL_DEPTH)
    f = {"id": "h1", "op": "hole", "name": "M6 Tapped Hole", "point": [-35.0, -20.0, T], "normal": [0, 0, 1],
         "d": DRILL, "depth": DRILL_DEPTH, "count": 2, "step": [70.0, 0, 0], "thread": th}
    return [f, {**f, "id": "h2", "point": [-35.0, 20.0, T]}]


def test_threaded_holes_record_metadata_and_keep_plain_geometry() -> None:
    fw.reset()
    part = fw.apply_manual(_block(), _tapped_features())
    assert fw.manual_errors() == []
    # geometry: four plain Ø5 x 15 drills, no helix
    assert part.volume == pytest.approx(L * W * T - 4 * math.pi * (DRILL / 2) ** 2 * DRILL_DEPTH, rel=1e-6)
    recs = fw.threads()
    pts = sorted(tuple(i["p"]) for r in recs for i in r["instances"])
    assert pts == [(-35.0, -20.0, T), (-35.0, 20.0, T), (35.0, -20.0, T), (35.0, 20.0, T)]
    assert all(i["dir"] == [0.0, 0.0, -1.0] for r in recs for i in r["instances"])
    assert {r["designation"] for r in recs} == {"M6×1-6H"} and all(r["depth"] == THREAD_DEPTH for r in recs)
    assert [e["params"].get("thread") for e in fw.log() if e["kind"] == "manual"] == ["M6×1-6H", "M6×1-6H"]


def test_cosmetic_thread_feature_internal_external_and_patterned() -> None:
    from build123d import Align, Cylinder, Pos

    fw.reset()
    part = _block() + Pos(0, 0, T) * Cylinder(10, 30, align=(Align.CENTER, Align.CENTER, Align.MIN))
    hole = {**_tapped_features()[0], "thread": None, "count": 1, "id": "h0"}
    feats = [hole,
             {"id": "t1", "op": "thread", "name": "Shaft thread", "face": {"point": [10.0, 0.0, 45.0]},
              "thread": {"size": 20, "pitch": 1.5, "depth": 25}},
             {"id": "t2", "op": "thread", "name": "Hole thread", "face": {"point": [-32.5, -20.0, 18.0]},
              "thread": {"size": 6}},
             {"id": "p1", "op": "pattern", "kind": "circular", "source": ["h3"], "count": 4,
              "axis": {"origin": [0, 0, 0], "dir": [0, 0, 1]}, "angle": 360}]
    th3 = threads.resolve({"size": 6}, internal=True, bore=DRILL, length=None)
    feats.insert(3, {"id": "h3", "op": "hole", "name": "M6", "point": [25.0, 0.0, T], "normal": [0, 0, 1], "d": DRILL,
                     "depth": None, "thread": th3})
    v0 = part.volume
    out = fw.apply_manual(part, feats)
    assert fw.manual_errors() == []
    recs = {r["feature"]: r for r in fw.threads()}
    shaft = recs["t1"]
    assert shaft["internal"] is False and shaft["designation"] == "M20×1.5-6g" and shaft["depth"] == 25
    assert shaft["instances"] == [{"p": [0.0, 0.0, T + 30], "dir": [0.0, 0.0, -1.0]}]  # starts at the end picked
    inner = recs["t2"]
    assert inner["internal"] is True and inner["designation"] == "M6×1-6H" and inner["depth"] is None
    assert inner["instances"][0]["p"] == [-35.0, -20.0, T]
    pat = sorted(tuple(round(c, 6) for c in i["p"]) for i in recs["p1"]["instances"])
    assert pat == sorted([(0.0, 25.0, T), (-25.0, 0.0, T), (0.0, -25.0, T)])
    # the thread features never change the solid: 1 blind + 4 through drills
    hand = math.pi * (DRILL / 2) ** 2 * (DRILL_DEPTH + 4 * T)
    assert out.volume == pytest.approx(v0 - hand, rel=1e-6)
    with pytest.raises(ValueError, match="external thread tolerance class|major diameter|cylindrical"):
        fw._cosmetic_thread(out, {"op": "thread", "face": {"point": [10.0, 0.0, 45.0]}, "thread": {"size": 24}})


def test_step_export_carries_threads_in_the_header_and_a_sidecar(tmp_path: Path) -> None:
    from build123d import import_step

    from aicad.agent.runner import _exports

    fw.reset()
    part = fw.apply_manual(_block(), _tapped_features())
    recs = fw.threads()
    _re, step = _exports(part, tmp_path, recs)
    head = step.read_bytes().split(b"ENDSEC;")[0].decode("ascii")
    assert "FW-THREAD 2X M6x1-6H INTERNAL DEPTH 12 DIR 0,0,-1 AT -35,-20,20;35,-20,20" in head
    assert import_step(str(step)).volume == pytest.approx(part.volume, rel=1e-6)
    side = json.loads((tmp_path / "part.threads.json").read_text(encoding="utf-8"))
    assert side["format"] == "formwright-cosmetic-threads/1" and len(side["threads"]) == 2
    first = step.read_bytes()
    _exports(part, tmp_path, recs)
    assert step.read_bytes() == first  # deterministic (CHK-08)
    _exports(part, tmp_path, [])
    assert b"FW-THREAD" not in step.read_bytes() and not (tmp_path / "part.threads.json").exists()


# ----------------------------------------------------------------------------- drawings: thread callouts
def _write(out: Path, shape: Any, extra: dict[str, Any] | None = None) -> None:
    from build123d import export_step

    out.mkdir(parents=True, exist_ok=True)
    export_step(shape, str(out / "part.step"))
    (out / "status.json").write_text(json.dumps({"ok": True, "part": "Part", "material": "Steel", "build_id": "b1",
                                                 "params": {"L": L, "W": W, "T": T}, **(extra or {})}), encoding="utf-8")


@pytest.fixture(scope="module")
def tapped(tmp_path_factory: pytest.TempPathFactory) -> Path:
    ws = tmp_path_factory.mktemp("tapped")
    fw.reset()
    part = fw.apply_manual(_block(), _tapped_features())
    _write(ws / "out", part, {"threads": fw.threads()})
    return ws


def _sheet(ws: Path, opts: dict[str, Any], meta: dict[str, Any], edits: dict[str, Any] | None
           ) -> tuple[dict[str, Any], dict[str, Any]]:
    """generate() plus the composed sheet (re-run the layout on the same inputs to read its primitives)."""
    import aicad.drawing.generate as g

    seen: dict[str, Any] = {}
    real = g.compose

    def spy(*a: Any, **k: Any) -> Any:
        seen["sheet"] = real(*a, **k)
        return seen["sheet"]

    g.compose = spy
    try:
        rec = generate(ws / "out", ws / "drawings", opts, meta, edits)
    finally:
        g.compose = real
    return rec, seen["sheet"]


def test_thread_callout_and_iso6410_marks(tapped: Path) -> None:
    rec, sheet = _sheet(tapped, {}, META, None)
    assert rec["check"]["passed"], rec["check"]["problems"]
    (c,) = [c for c in rec["callouts"] if c["type"] == "hole"]
    assert [ln["text"] for ln in c["lines"]] == ["4X M6×1-6H ▽12", "Ø5 ▽15"]
    assert c["lines"][0]["tag"] == "spec" and c["qty"] == 4 and c["dia"] == DRILL
    # ISO 6410-1: a thin 3/4 circle at the major Ø around each tapped hole in the top view
    s = sheet["scale"][0] / sheet["scale"][1]
    arcs = [p for p in sheet["prims"] if p["t"] == "arc" and p["l"] == "thread"]
    assert len(arcs) == 4 and all(p["p"][2] == pytest.approx(6.0 / 2 * s) and p["p"][4] - p["p"][3] == 270 for p in arcs)
    assert any("THREADS ARE COSMETIC" in n.get("txt", "") for n in sheet["prims"] if n["t"] == "text")
    assert rec["threads"][0]["designation"] == "M6×1-6H"
    svg = (tapped / "drawings" / "sheet.svg").read_text(encoding="utf-8")
    assert "4X M6×1-6H ▽12" in svg
    import ezdxf

    doc = ezdxf.readfile(str(tapped / "drawings" / "sheet.dxf"))
    psp = doc.layouts.get("Sheet")
    assert any(e.dxf.text == "4X M6×1-6H " for e in psp.query("TEXT")) and len(psp.query("LWPOLYLINE[layer=='TEXT']")) >= 2
    assert (tapped / "drawings" / "sheet.pdf").read_bytes().startswith(b"%PDF")


def test_external_thread_on_a_turned_diameter(tmp_path: Path) -> None:
    from build123d import Align, Cylinder, Pos

    D, LEN, TL = 20.0, 60.0, 25.0
    shaft = Cylinder(D / 2, LEN, align=(Align.CENTER, Align.CENTER, Align.MIN))
    shaft = shaft + Pos(0, 0, LEN) * Cylinder(6, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    fw.reset()
    fw.thread(shaft, (D / 2, 0, 5.0), "M20x1.5", depth=TL)
    _write(tmp_path / "out", shaft, {"threads": fw.threads(), "params": {"D": D}})
    rec, sheet = _sheet(tmp_path, {}, META, None)
    assert rec["check"]["passed"], rec["check"]["problems"]
    dia = [d for d in rec["dimensions"] if d["kind"] == "diameter" and d["value"] == D]
    assert [d["text"] for d in dia] == ["M20×1.5-6g"] and dia[0]["tag"] == "spec"
    root = (D - 1.226869 * 1.5) / 2  # ISO 724 d3
    s = sheet["scale"][0] / sheet["scale"][1]
    side = [p for p in sheet["prims"] if p["t"] == "line" and p["l"] == "thread"]
    assert len(side) >= 2
    gaps = sorted({round(abs(p["p"][1] - q["p"][1]), 4) for p in side for q in side if p is not q and p["view"] == q["view"]})
    assert pytest.approx(2 * root * s, abs=1e-3) in gaps
    lens = {round(math.hypot(p["p"][2] - p["p"][0], p["p"][3] - p["p"][1]), 4) for p in side}
    assert lens and all(x == pytest.approx(TL * s, abs=1e-3) for x in lens)
    assert any(n["txt"].startswith("THREAD M20×1.5-6g: 25 LONG") for n in sheet["prims"] if n["t"] == "text")


# ----------------------------------------------------------------------------- detail views
def test_detail_clipping_and_scale_rules() -> None:
    # a line at distance 3 from the centre of an r = 5 circle keeps the chord 2 sqrt(25 - 9) = 8
    (ln,) = detail.clip([["line", -20, 3, 20, 3]], 0, 0, 5)
    assert math.hypot(ln[3] - ln[1], ln[4] - ln[2]) == pytest.approx(8.0)
    assert detail.clip([["line", -20, 6, 20, 6]], 0, 0, 5) == []
    assert detail.clip([["circle", 1, 0, 2]], 0, 0, 5) == [["circle", 1, 0, 2]]
    # a circle of R 5 centred on the boundary of an r = 5 detail: the inside arc spans 2 acos(1/2) = 120°
    (arc,) = detail.clip([["circle", 5, 0, 5]], 0, 0, 5)
    assert arc[0] == "arc" and arc[5] - arc[4] == pytest.approx(120.0)
    assert detail.choose_scale(None, 1.0, 8) == (5, 1)  # largest ≥ 2x whose circle (16 x 5 = 80) fits 110 mm
    assert detail.choose_scale(None, 1.0, 30) == (2, 1)
    assert detail.choose_scale("10:1", 1.0, 8) == (10, 1)
    assert detail.choose_scale("1:1", 1.0, 8) == (5, 1)  # not an enlargement: the automatic one
    assert detail.letters(2, {"A"}) == ["B", "C"] and "I" not in detail.LETTERS
    with pytest.raises(DrawingInputError):
        detail.normalize([{"view": "top", "u": 0, "v": 0, "r": 5, "scale": "3:1"}])


def test_detail_view_on_the_sheet(tapped: Path) -> None:
    edits = {"details": [{"view": "top", "u": 35, "v": 20, "r": 8, "scale": None}]}
    rec, sheet = _sheet(tapped, {"section": "y"}, META, edits)
    assert rec["check"]["passed"], rec["check"]["problems"]
    (d,) = rec["details"]["drawn"]
    assert d["letter"] == "B" and d["scale"] == "5:1" and d["parent"] == "top"  # A is the section
    s = sheet["scale"][0] / sheet["scale"][1]
    v = sheet["views"]["detail-B"]
    assert v["rect"][2] - v["rect"][0] == pytest.approx(2 * 8 * 5) and v["scale"] == 5
    circles = [p for p in sheet["prims"] if p["t"] == "circle" and p["l"] == "detail"]
    assert sorted(round(p["p"][2], 6) for p in circles) == sorted([round(8 * s, 6), 40.0])
    texts = [p["txt"] for p in sheet["prims"] if p["t"] == "text"]
    assert "DETAIL B (5:1)" in texts and "B" in texts
    # inside the detail: the M6 drill circle at 5:1
    assert any(p["t"] == "circle" and p.get("view") == "detail-B" and p["p"][2] == pytest.approx(DRILL / 2 * 5)
               for p in sheet["prims"])


# ----------------------------------------------------------------------------- GD&T: only from input
def test_gdt_rules_and_nothing_invented(tapped: Path) -> None:
    rec, sheet = _sheet(tapped, {}, META, None)
    assert not [p for p in sheet["prims"] if p["l"] == "gdt" or p.get("kind") == "gdt"]
    assert rec["gdt"]["datums"] == [] and rec["gdt"]["frames"] == []
    with pytest.raises(DrawingInputError, match="form tolerance"):
        gdt.normalize({"frames": [{"char": "flatness", "tol": 0.1, "datums": ["A"], "target": {"kind": "dim", "id": "ext-x"}}]})
    with pytest.raises(DrawingInputError, match="needs at least one datum"):
        gdt.normalize({"frames": [{"char": "perpendicularity", "tol": 0.1, "target": {"kind": "dim", "id": "ext-x"}}]})
    with pytest.raises(DrawingInputError, match="twice"):
        gdt.normalize({"datums": [{"letter": "A", "target": {"kind": "dim", "id": "ext-x"}}] * 2})
    with pytest.raises(DrawingInputError, match="capital letter"):
        gdt.normalize({"datums": [{"letter": "I", "target": {"kind": "dim", "id": "ext-x"}}]})
    with pytest.raises(DrawingInputError, match="not on the drawing"):
        generate(tapped / "out", tapped / "d2", {}, META, {"gdt": {"frames": [
            {"char": "position", "tol": 0.2, "dia": True, "datums": ["B"], "target": {"kind": "callout", "id": "hole-0"}}]}})


def test_user_gdt_drawn_as_entered(tapped: Path) -> None:
    edits = {"gdt": {"datums": [{"letter": "A", "target": {"kind": "point", "view": "front", "u": -20, "v": 0}}],
                     "frames": [{"char": "flatness", "tol": 0.05, "target": {"kind": "point", "view": "front", "u": 10, "v": T}},
                                {"char": "position", "tol": 0.2, "dia": True, "mod": "M", "datums": ["A"],
                                 "target": {"kind": "callout", "id": "hole-0"}}]}}
    rec, sheet = _sheet(tapped, {}, META, edits)
    assert rec["check"]["passed"], rec["check"]["problems"]
    g = rec["check"]["detail"]["gdt"]
    assert g["frames"] == 2 and g["datums"] == ["A"] and g["dangling_datums"] == [] and g["untraced"] == []
    gt = sorted(p["txt"] for p in sheet["prims"] if p["t"] == "text" and p.get("kind") == "gdt")
    assert gt == sorted(["A", "A", "0.05", "Ø0.2", "M"])
    assert [f["text"] for f in rec["gdt"]["frames"]] == ["Flatness 0.05", "Position Ø0.2 (M) | A"]
    assert all(f["source"] == "user" for f in rec["gdt"]["frames"])
    # frames sit off the view geometry
    rect = sheet["views"]["front"]["rect"]
    boxes = [p["box"] for p in sheet["prims"] if p["t"] == "text" and p.get("kind") == "gdt" and p.get("view") == "front"]
    assert boxes and all(b[3] < rect[1] or b[1] > rect[3] or b[2] < rect[0] or b[0] > rect[2] for b in boxes)
    assert any("ENTERED BY THE USER" in p["txt"] for p in sheet["prims"] if p["t"] == "text")


# ----------------------------------------------------------------------------- ICD-derived GD&T (CD-021)
def test_icd_gdt_rules_on_a_bracket_drawing(tmp_path: Path) -> None:
    from test_office_phase5 import BRACKET, DOWELED, _parts

    from aicad.assembly import placeholder
    from aicad.office import deliverables, frames, icd

    sk, ifs = icd.build(_parts(DOWELED), "")
    doc = {"version": 3, "interfaces": ifs}
    g = deliverables.icd_gdt(sk, doc, BRACKET)
    H = sk["items"][BRACKET]["size"][2]
    (a,) = g["datums"]
    assert a["letter"] == "A" and a["target"] == {"kind": "plane", "point": [0.0, 0.0, -H / 2], "normal": [0.0, 0.0, -1.0]}
    flat = [f for f in g["frames"] if f["char"] == "flatness"]
    pos = [f for f in g["frames"] if f["char"] == "position"]
    assert [f["tol"] for f in flat] == [icd.FLATNESS]
    assert pos and all(f["tol"] == 2 * icd.POS_TOL and f["dia"] and f["datums"] == ["A"] for f in pos)
    # dowel holes: no relationship to a face in their interface, so no frame
    holes = [f for f in icd.item_features(sk, ifs, BRACKET) if f["type"] == "hole"]
    assert len(pos) == sum(1 for f in holes if any(icd.iface(doc, i)["kind"] == "hole_pattern"
                                                   for i in [f["if"], *f.get("also", [])]))
    # the part modelled turned a quarter about Z: targets come back in its own coordinates
    fr = frames.frame(frames.rot_z(90), [1.0, 2.0, 3.0])
    g2 = deliverables.icd_gdt(sk, doc, BRACKET, fr)
    p_icd = pos[0]["target"]["point"]
    back = frames.apply(frames.rot_z(90), g2["frames"][1]["target"]["point"])
    assert [round(x + t, 6) for x, t in zip(back, [1.0, 2.0, 3.0], strict=True)] == [round(x, 6) for x in p_icd]

    out = tmp_path / "out"
    _write(out, placeholder.shape(icd.placeholder_spec(sk, ifs, BRACKET)), {"params": {}})
    spec = deliverables.icd_spec(sk, doc, BRACKET)
    rec, sheet = _sheet(tmp_path, {}, {**META, "spec": spec}, None)
    assert rec["check"]["passed"], rec["check"]["problems"]
    gd = rec["gdt"]
    assert [(d["letter"], d["source"], d["view"]) for d in gd["datums"]] == [("A", "icd", "front")]
    assert sorted(f["text"] for f in gd["frames"]) == ["Flatness 0.05", "Position Ø0.2 | A"]
    assert gd["icd_version"] == 3 and gd["unresolved"] == []
    assert any(p["txt"].startswith("DATUMS AND GEOMETRIC TOLERANCES FROM THE INTERFACE SPEC (ICD v3")
               for p in sheet["prims"] if p["t"] == "text")


def test_icd_gdt_not_on_the_model_is_left_off(tmp_path: Path) -> None:
    from build123d import Align, Box

    spec = {"gdt": {"version": 1, "datums": [{"letter": "A", "ref": "IF-01", "label": "mounting face",
                                              "target": {"kind": "plane", "point": [0, 0, 7.5], "normal": [0, 0, 1]}}],
                    "frames": [{"char": "position", "tol": 0.2, "dia": True, "datums": ["A"], "ref": "IF-01",
                                "target": {"kind": "axis", "point": [0, 0, 0], "dir": [0, 0, 1], "d": 9.0}}]}}
    _write(tmp_path / "out", Box(40, 30, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)), {"params": {}})
    rec, sheet = _sheet(tmp_path, {}, {**META, "spec": spec}, None)
    assert rec["check"]["passed"]
    assert [u["type"] for u in rec["gdt"]["unresolved"]] == ["datum", "frame"]
    assert not [p for p in sheet["prims"] if p.get("kind") == "gdt"]


# ----------------------------------------------------------------------------- STEP in -> drawing (DRW-016)
def test_imported_step_drawing_is_all_inferred(tmp_path: Path) -> None:
    from build123d import Align, Box, Cylinder, Pos

    part = Box(80, 40, 10, align=(Align.CENTER, Align.CENTER, Align.MIN))
    for x in (-30, 30):
        part -= Pos(x, 0, -1) * Cylinder(3.3, 12, align=(Align.CENTER, Align.CENTER, Align.MIN))
    ws = tmp_path
    (ws / "imports").mkdir()
    (ws / "imports" / "p.features.json").write_text(json.dumps({"component": None, "unrecognised": {"bspline": 2}}),
                                                    encoding="utf-8")
    (ws / "model.py").write_text("RECOGNITION = 'imports/p.features.json'\n", encoding="utf-8")
    # recognised hole Ø as a "parameter": measured from the file, so it must not make the value spec
    _write(ws / "out", part, {"imported": True, "params": {"HP1_D": 6.6}})
    rec, sheet = _sheet(ws, {}, META, None)
    assert rec["check"]["passed"], rec["check"]["problems"]
    assert rec["dimensions"] and all(d["tag"] == "inferred" and d["param"] is None for d in rec["dimensions"])
    assert all(ln["tag"] == "inferred" for c in rec["callouts"] for ln in c["lines"])
    assert rec["mapping"]["mapped"] == {} and rec["imported"] == {"inferred_only": True, "component": None,
                                                                  "unrecognised_faces": 2}
    texts = [p["txt"] for p in sheet["prims"] if p["t"] == "text"]
    assert any("DIMENSIONS INFERRED FROM IMPORTED GEOMETRY: VERIFY" in t for t in texts)
    assert any("2 FACE(S) NOT RECOGNISED" in t for t in texts)


# ----------------------------------------------------------------------------- API
from test_drawings import app_client, write_model  # noqa: F401  (fixture)


def test_api_details_and_gdt_edits(app_client: Any) -> None:  # noqa: F811
    from test_platform import signup

    from aicad.platform.db import session_factory
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    c = app_client
    signup(c, "depth@x.com")
    c.post("/api/billing/payments/" + c.post("/api/billing/checkout", json={"product_code": "addon_drawings"})
           .json()["payment_id"] + "/simulate", json={"outcome": "success"})
    pid = c.post("/api/projects", json={"name": "Block"}).json()["id"]
    db = session_factory()()
    ws = workspace_for(db.get(Project, pid))
    db.close()
    write_model(ws / "out")
    assert c.post(f"/api/m/drawings/projects/{pid}/generate", json={}).status_code == 200
    bad = {"gdt": {"frames": [{"char": "position", "tol": 0.2, "datums": ["A"], "target": {"kind": "callout", "id": "hole-0"}}]}}
    r = c.post(f"/api/m/drawings/projects/{pid}/edits", json=bad)
    assert r.status_code == 422 and "datum A" in r.json()["detail"]
    assert not (ws / "drawings" / "edits.json").exists() or "gdt" not in json.loads((ws / "drawings" / "edits.json").read_text())
    ok = {"details": [{"view": "top", "u": 40, "v": 20, "r": 6}],
          "gdt": {"datums": [{"letter": "A", "target": {"kind": "point", "view": "front", "u": 0, "v": 0}}],
                  "frames": bad["gdt"]["frames"]}}
    r = c.post(f"/api/m/drawings/projects/{pid}/edits", json=ok)
    assert r.status_code == 200, r.text
    rec = r.json()["drawing"]
    assert rec["check"]["passed"] and rec["details"]["drawn"][0]["letter"] in ("A", "B")
    assert [f["text"] for f in rec["gdt"]["frames"]] == ["Position 0.2 | A"]
    assert set(rec["sheet"]["views"]) >= {"front", "top", "right"}
    assert r.json()["edits"]["details"][0]["r"] == 6


def test_studio_thread_features_flow_to_status_and_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A tapped Hole Wizard hole with a cosmetic thread, built through the Studio API: the build's status carries the
    thread, the plain drill is cut, the STEP header names it; a wrong thread on a shaft is refused."""
    from fastapi.testclient import TestClient
    from test_platform import _project_with_model, signup
    from test_studio import DEMO

    from aicad.platform import config
    from aicad.platform.app import create_app

    config.override_settings(config.Settings(
        env="development", data_dir=tmp_path / "data", database_url=f"sqlite:///{(tmp_path / 'db.sqlite').as_posix()}",
        app_url="http://testserver", superadmin_emails=(), stripe_secret_key="", trial_tokens=300))
    with TestClient(create_app()) as c:
        c.headers.update({"X-FW-CSRF": "1"})
        signup(c, "thread@x.com")
        pid, ws = _project_with_model(c, (DEMO / "l_bracket.py").read_text(encoding="utf-8"))
        v0 = c.get(f"/api/projects/{pid}/files/status.json").json()["fingerprint"]["volume"]
        hole = {"op": "hole", "name": "M6 Tapped Hole", "point": [30, 25, 5], "normal": [0, 0, 1], "d": 1,
                "spec": {"type": "tapped", "size": 6}, "thread": {"size": 6, "pitch": 1}}
        r = c.post(f"/api/projects/{pid}/manual", json={"feature": hole})
        assert r.status_code == 200, r.text
        st = c.get(f"/api/projects/{pid}/files/status.json").json()
        assert st["ok"] and st["fingerprint"]["volume"] == pytest.approx(v0 - math.pi * 2.5 ** 2 * 5, rel=1e-6)
        (t,) = st["threads"]
        assert t["designation"] == "M6×1-6H" and t["instances"] == [{"p": [30.0, 25.0, 5.0], "dir": [0.0, 0.0, -1.0]}]
        for _ in range(200):  # the STEP export of a fast build finishes in the background
            if b"FW-THREAD" in (ws / "out" / "part.step").read_bytes():
                break
            time.sleep(0.1)
        assert b"FW-THREAD 1X M6x1-6H INTERNAL DEPTH FULL" in (ws / "out" / "part.step").read_bytes()
        bad = {"op": "thread", "name": "Wrong", "face": {"point": [30, 25 + 2.5, 2.5]}, "thread": {"size": 24}}
        r = c.post(f"/api/projects/{pid}/manual", json={"feature": bad})
        assert r.status_code == 422, r.text
