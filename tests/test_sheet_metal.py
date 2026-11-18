"""Sheet metal (CAD-026): flat pattern lengths against hand formulas, folded geometry, DXF, Studio features, checks.

Every expected value is a hand formula over the inputs (BA = θ·(R + K·T), setbacks from the outer / inner virtual
sharp), never measured from the model.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_platform import _project_with_model, app_client, signup  # noqa: F401  (fixture re-export)

from aicad import sheetmetal as sm


def _ba(theta: float, r: float, k: float, t: float) -> float:
    return math.radians(theta) * (r + k * t)


def _plate(w: float, d: float, t: float, r: float, k: float, **kw: object) -> tuple[sm.Sheet, object]:
    from build123d import Location, Rectangle

    return sm.base(Rectangle(w, d).faces()[0], Location(), t, r, k, **kw)  # type: ignore[arg-type]


# ----------------------------------------------------------------------------- bend allowance and flat lengths
@pytest.mark.parametrize("k", [0.0, 0.33, 0.44, 0.5])
def test_flat_length_90_degree_material_inside(k: float) -> None:
    w, d, t, r, ln = 100.0, 60.0, 2.0, 2.0, 25.0
    s, part = _plate(w, d, t, r, k)
    s, part = sm.flange(s, part, (0, d / 2, t), ln, 90, position="inside")
    fl = sm.flatten(s, part)
    # outer dimensions d and ln, bend deduction BD = 2·(R+T)·tan45 − BA
    bd = 2 * (r + t) - _ba(90, r, k, t)
    assert fl["size"] == pytest.approx([w, d + ln - bd], abs=1e-6)
    assert fl["bends"][0]["ba"] == pytest.approx(math.pi / 2 * (r + k * t), abs=1e-6)
    # folded: outer face of the flange flush with the original edge, flange ln tall from the bottom face
    bb = part.bounding_box()  # type: ignore[attr-defined]
    assert [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z] == pytest.approx([-50, -30, 0, 50, 30, ln], abs=1e-6)
    s_ = r + t
    vol = t * (w * d - w * s_) + math.pi / 4 * ((r + t) ** 2 - r ** 2) * w + t * w * (ln - s_)
    assert part.volume == pytest.approx(vol, rel=1e-9)  # type: ignore[attr-defined]
    assert fl["area"] == pytest.approx(w * (d - s_) + w * _ba(90, r, k, t) + w * (ln - s_), rel=1e-9)


def test_flat_length_non_90_bends_and_positions() -> None:
    t, r, k = 1.5, 3.0, 0.33
    # 60° material outside: inner virtual sharp on the edge, straight part = L − (R+T)·tan30
    s, part = _plate(80, 40, t, r, k)
    s, part = sm.flange(s, part, (40, 0, t), 20, 60, position="outside")
    fl = sm.flatten(s, part)
    tan = math.tan(math.radians(30))
    assert fl["size"][0] == pytest.approx(80 - r * tan + _ba(60, r, k, t) + 20 - (r + t) * tan, abs=1e-6)
    assert fl["bends"][0]["straight"] == pytest.approx(20 - (r + t) * tan, abs=1e-6)
    # 120° bend outside, tangent length: nothing trimmed, flat = W + BA + L
    s, part = _plate(80, 40, t, r, k)
    s, part = sm.flange(s, part, (40, 0, 0), 15, 120, position="bend_outside", length_ref="tangent")
    fl = sm.flatten(s, part)
    assert fl["size"][0] == pytest.approx(80 + _ba(120, r, k, t) + 15, abs=1e-6)
    assert fl["bends"][0]["direction"] == "DOWN"  # picked on the bottom face's edge
    # 135° material inside: setback R+T (tangent convention above 90°)
    s, part = _plate(80, 40, t, r, k)
    s, part = sm.flange(s, part, (40, 0, t), 12, 135, position="inside", length_ref="tangent")
    assert sm.flatten(s, part)["size"][0] == pytest.approx(80 - (r + t) + _ba(135, r, k, t) + 12, abs=1e-6)
    assert part.is_valid  # type: ignore[attr-defined]


def test_multiple_flanges_u_channel_and_return_flange() -> None:
    t, r, k, w, d = 2.0, 2.0, 0.44, 120.0, 50.0
    s, part = _plate(w, d, t, r, k)
    s, part = sm.flange(s, part, (0, d / 2, t), 30, 90)
    s, part = sm.flange(s, part, (0, -d / 2, t), 30, 90)
    ba = _ba(90, r, k, t)
    fl = sm.flatten(s, part)
    assert fl["size"][1] == pytest.approx(d + 2 * 30 - 2 * (2 * (r + t) - ba), abs=1e-6)
    assert len(fl["bends"]) == 2 and all(b["direction"] == "UP" for b in fl["bends"])
    # a return flange on the first flange's free edge (outer face top edge): it folds outwards, 15 mm outer
    s, part = sm.flange(s, part, (0, d / 2, 30), 15, 90)
    fl = sm.flatten(s, part)
    assert fl["size"][1] == pytest.approx(d + 2 * 30 - 2 * (2 * (r + t) - ba) + 15 - (2 * (r + t) - ba), abs=1e-6)
    bb = part.bounding_box()  # type: ignore[attr-defined]
    assert bb.max.Y == pytest.approx(d / 2 - t + 15, abs=1e-6)  # outer face of the return = inside of the wall + 15
    assert part.is_valid and len(part.solids()) == 1  # type: ignore[attr-defined]
    assert part.volume == pytest.approx(sm.model_volume(s), rel=1e-9)  # type: ignore[attr-defined]
    # with K = 0.5 the neutral fibre is the mid-plane: flat volume equals the folded volume
    s5, p5 = _plate(w, d, t, r, 0.5)
    s5, p5 = sm.flange(s5, p5, (0, d / 2, t), 30, 90)
    assert sm.flatten(s5, p5)["local"].volume == pytest.approx(p5.volume, rel=1e-9)  # type: ignore[attr-defined]


def test_k_factor_shifts_flat_length_by_theta_dk_t() -> None:
    sizes = {}
    for k in (0.3, 0.45):
        s, part = _plate(60, 40, 3.0, 4.0, k)
        s, part = sm.flange(s, part, (30, 0, 3.0), 20, 75)
        sizes[k] = sm.flatten(s, part)["size"][0]
    assert sizes[0.45] - sizes[0.3] == pytest.approx(math.radians(75) * 0.15 * 3.0, abs=1e-6)


def test_hem_relief_and_cuts_carried_into_the_flat() -> None:
    from build123d import Cylinder

    t, r, k = 1.0, 1.0, 0.5
    # open hem, gap 1 → inside radius 0.5, material inside: flat = D − (R+T) + π·(R + K·T) + L
    s, part = _plate(50, 30, t, r, k)
    s, part = sm.flange(s, part, (0, 15, t), 8, 180, radius=0.5, kind="hem", position="inside")
    assert sm.flatten(s, part)["size"][1] == pytest.approx(30 - 1.5 + math.pi * (0.5 + 0.5) + 8, abs=1e-6)
    bb = part.bounding_box()  # type: ignore[attr-defined]
    assert bb.max.Z == pytest.approx(t + 2 * 0.5 + t, abs=1e-6) and bb.max.Y == pytest.approx(15, abs=1e-6)
    # end offsets with rectangular reliefs (width = ratio·T = 1, 1 mm past the bend start)
    s, part = _plate(50, 30, t, r, k, relief="rect", relief_ratio=1.0)
    s, part = sm.flange(s, part, (0, 15, t), 10, 90, inset=(5, 5))
    span, sb = 40.0, r + t
    base_area = 50 * 30 - sb * span - 2 * (1.0 + sb) * 1.0
    fl = sm.flatten(s, part)
    assert fl["area"] == pytest.approx(base_area + span * (_ba(90, r, k, t) + 10 - sb), rel=1e-9)
    # a hole drilled through the base after the flanges is in the flat (outline gets the circle)
    part = part - Cylinder(4, 50)  # type: ignore[operator]
    fl = sm.flatten(s, part)
    assert fl["area"] == pytest.approx(base_area - math.pi * 16 + span * (_ba(90, r, k, t) + 10 - sb), rel=1e-6)
    assert any(e["type"] == "circle" and e["r"] == pytest.approx(4) for e in fl["outline"])
    assert not fl["notes"]


def test_flange_errors_are_plain() -> None:
    s, part = _plate(40, 20, 2, 2, 0.44)
    with pytest.raises(ValueError, match="edge was not found"):
        sm.flange(s, part, (0, 0, 1), 10)  # the middle of the plate, no edge
    with pytest.raises(ValueError, match="too short"):
        sm.flange(s, part, (0, 10, 2), 3, 90)  # outer length below (R+T)·tan45
    s2, p2 = sm.flange(s, part, (0, 10, 2), 10, 90)
    with pytest.raises(ValueError, match="already has a bend"):
        sm.flange(s2, p2, (0, 10 - 4, 2), 10, 90)  # the bend start line of that flange
    with pytest.raises(ValueError, match="end offsets leave no flange"):
        sm.flange(s, part, (20, 0, 2), 10, inset=(10, 10.5))


def test_flat_pattern_dxf_layers_lines_and_notes(tmp_path: Path) -> None:
    import ezdxf

    s, part = _plate(100, 60, 2, 2, 0.44)
    s, part = sm.flange(s, part, (0, 30, 2), 25, 90)
    s, part = sm.flange(s, part, (50, 0, 0), 15, 45)
    fl = sm.flatten(s, part)
    summ = sm.summary(s, fl)
    sm.write_dxf(fl, summ, tmp_path / "flat.dxf", "Steel S235")
    doc = ezdxf.readfile(tmp_path / "flat.dxf")
    msp = doc.modelspace()
    assert doc.header["$INSUNITS"] == 4
    outline = [e for e in msp if e.dxf.layer == "OUTLINE"]
    length = sum(math.dist(tuple(e.dxf.start)[:2], tuple(e.dxf.end)[:2]) for e in outline if e.dxftype() == "LINE")
    assert length == pytest.approx(fl["perimeter"], abs=1e-5)
    assert len([e for e in msp if e.dxf.layer == "BEND_UP"]) == 1 and len([e for e in msp if e.dxf.layer == "BEND_DOWN"]) == 1
    notes = sorted(e.dxf.text for e in msp if e.dxf.layer == "BEND_NOTES")
    assert notes == ["DOWN 45%%d R2", "UP 90%%d R2"]
    assert doc.layers.get("BEND_UP").dxf.linetype == "DASHED"
    # the bend line sits mid-way along the bend strip: (base edge − setback) + BA/2
    up = next(e for e in msp if e.dxf.layer == "BEND_UP")
    assert up.dxf.start[1] == pytest.approx(30 - 4 + _ba(90, 2, 0.44, 2) / 2, abs=1e-6)
    assert summ["bend_count"] == 2 and summ["flat"]["size"] == fl["size"]


# ----------------------------------------------------------------------------- model scripts: helpers + checks
SCRIPT = '''"""Sheet-metal bracket: plate with a 90 degree flange and a hem (hand formulas in EXPECTED)."""
from aicad import fw

NAME = "Sheet bracket"
MATERIAL = "Steel S235"
W = 80.0
D = 50.0
T = 2.0
R = 2.0
L = 30.0
PARAMS = {"W": W, "D": D, "T": T, "R": R, "L": L}

part = fw.base_flange(width=W, height=D, thickness=T, radius=R, k=0.44)
part = fw.edge_flange(part, (0, D / 2, T), L, 90, name="Front flange")
part = fw.hem(part, (W / 2, 0, T), 6, gap=1.0, name="Side hem")
result = part
'''


def test_model_script_sheet_metal_passes_the_deterministic_checks(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "sheetchecks@x.com")
    w, d, t, r, ln, rh = 80.0, 50.0, 2.0, 2.0, 30.0, 0.5
    s_ = r + t
    hem_span = d - s_  # the side edge after the front flange trimmed the base
    vol = (t * (w * d - w * s_) + math.pi / 4 * ((r + t) ** 2 - r ** 2) * w + t * w * (ln - s_)
           - t * (rh + t) * hem_span + math.pi / 2 * ((rh + t) ** 2 - rh ** 2) * hem_span + t * 6 * hem_span)
    script = SCRIPT + f'EXPECTED = {{"bbox": [W, D, L], "volume": {vol!r}, "solids": 1}}\n'
    pid, ws = _project_with_model(c, script)
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["ok"], st.get("error") or st["checks"]
    by = {x["id"]: x for x in st["checks"]}
    for cid in ("CHK-02", "CHK-03", "CHK-04", "CHK-05", "CHK-07", "CHK-08"):
        assert by[cid]["passed"] and by[cid]["gating"], (cid, by[cid])
    smd = st["sheet_metal"]
    ba = _ba(90, r, 0.44, t)
    assert smd["bend_count"] == 2 and smd["thickness"] == t and smd["k_factor"] == 0.44
    hem_ba = _ba(180, rh, 0.44, t)
    assert smd["flat"]["size"] == pytest.approx([w - (rh + t) + hem_ba + 6, d - s_ + ba + ln - s_], abs=1e-6)
    assert [b["name"] for b in smd["bends"]] == ["Front flange", "Side hem"]
    assert [f["name"] for f in st["features"]] == ["Base-Flange", "Front flange", "Side hem"]
    for n in ("flat.dxf", "flat.topo.json", "flat.json"):
        assert (ws / "out" / n).is_file()
    r_ = c.get(f"/api/projects/{pid}/files/flat.dxf")
    assert r_.status_code == 200 and b"BEND_UP" in r_.content
    topo = c.get(f"/api/projects/{pid}/files/flat.topo.json").json()
    assert topo["bbox"][2] == pytest.approx(0) and topo["bbox"][5] == pytest.approx(t)  # lies on the base plane


# ----------------------------------------------------------------------------- Studio manual features
TOP = {"origin": [0, 0, 0], "normal": [0, 0, 1], "x_dir": [1, 0, 0]}


def _rect(x0: float, y0: float, x1: float, y1: float) -> dict:
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return {"kind": "loop", "segs": [{"type": "line", "a": list(pts[i]), "b": list(pts[(i + 1) % 4])} for i in range(4)]}


def test_studio_base_flange_edge_flange_lifecycle(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "sheetstudio@x.com")
    pid = c.post("/api/projects", json={"name": "Hand sheet"}).json()["id"]
    t, r, k = 2.0, 2.0, 0.44
    base = {"op": "sm_base", "name": "Base-Flange1", "plane": TOP, "profiles": [_rect(-50, -30, 50, 30)], "t": t, "r": r,
            "k": k, "relief": {"type": "rect", "ratio": 0.5}}
    rr = c.post(f"/api/projects/{pid}/manual", json={"feature": base})
    assert rr.status_code == 200, rr.text
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["ok"] and st["fingerprint"]["volume"] == pytest.approx(100 * 60 * t, rel=1e-9)
    assert st["sheet_metal"]["bend_count"] == 0 and st["sheet_metal"]["flat"]["size"] == pytest.approx([100, 60])
    v0 = st["fingerprint"]["volume"]
    # edge flange on the top edge at y = +30 (the edge's true middle and direction, as the viewer sends them)
    fl = {"op": "sm_flange", "name": "Edge-Flange1", "edge": [0, 30, t], "edge_ref": {"kind": "line", "dir": [1, 0, 0]},
          "length": 25, "angle": 90, "position": "inside", "length_ref": "outer"}
    rr = c.post(f"/api/projects/{pid}/manual", json={"feature": fl})
    assert rr.status_code == 200, rr.text
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    ba = _ba(90, r, k, t)
    assert st["ok"] and st["sheet_metal"]["flat"]["size"] == pytest.approx([100, 60 + 25 - (2 * (r + t) - ba)], abs=1e-6)
    assert st["fingerprint"]["bbox"] == pytest.approx([100, 60, 25], abs=1e-6)
    feats = c.get(f"/api/projects/{pid}/manual").json()["features"]
    fid = feats[-1]["id"]
    assert feats[-1]["ref_bbox"]  # picks follow the body (REF_OPS)
    # thicker sheet: the flange re-finds its edge and the flat follows the formula
    c.patch(f"/api/projects/{pid}/manual/{feats[0]['id']}", json={"feature": {**base, "t": 3.0}})
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert not st["manual_errors"], st["manual_errors"]
    assert st["sheet_metal"]["flat"]["size"][1] == pytest.approx(60 + 25 - (2 * (r + 3) - _ba(90, r, k, 3.0)), abs=1e-6)
    c.patch(f"/api/projects/{pid}/manual/{feats[0]['id']}", json={"feature": base})
    # suppress restores the plate, unsuppress brings it back
    assert c.patch(f"/api/projects/{pid}/manual/{fid}", json={"feature": {"suppressed": True}}).status_code == 200
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["fingerprint"]["volume"] == pytest.approx(v0, rel=1e-9) and st["sheet_metal"]["bend_count"] == 0
    assert c.patch(f"/api/projects/{pid}/manual/{fid}", json={"feature": {"suppressed": False}}).status_code == 200
    # bad input → 422 (plain words); an edge that isn't a sheet edge → 422 and nothing changes
    for bad in ({**fl, "angle": 0}, {**fl, "position": "sideways"}, {**fl, "length": -1}, {**fl, "inset": [1]},
                {**base, "k": 1.5}, {**base, "relief": {"type": "zigzag"}}):
        assert c.post(f"/api/projects/{pid}/manual", json={"feature": bad}).status_code == 422
    n = len(c.get(f"/api/projects/{pid}/manual").json()["features"])
    rr = c.post(f"/api/projects/{pid}/manual", json={"feature": {**fl, "edge": [0, 0, 1]}})
    assert rr.status_code == 422 and "edge was not found" in rr.json()["detail"]
    assert len(c.get(f"/api/projects/{pid}/manual").json()["features"]) == n
    # hem on the far edge, then the flat DXF is downloadable
    hem = {"op": "sm_hem", "name": "Hem1", "edge": [0, -30, t], "edge_ref": {"kind": "line", "dir": [1, 0, 0]},
           "length": 6, "gap": 1.0, "position": "inside"}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": hem}).status_code == 200
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["sheet_metal"]["bend_count"] == 2
    assert st["sheet_metal"]["bends"][1]["kind"] == "hem" and st["sheet_metal"]["bends"][1]["angle"] == 180
    assert c.get(f"/api/projects/{pid}/files/flat.dxf").status_code == 200
    # a base flange can only start a part
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": base}).status_code == 422


# ----------------------------------------------------------------------------- drawings, DFM, agent wording
def test_flat_pattern_sheet_on_drawings_and_dfm_from_the_model(app_client: TestClient) -> None:  # noqa: F811
    import ezdxf

    c = app_client
    signup(c, "sheetdrw@x.com")
    pid, ws = _project_with_model(c, SCRIPT + 'EXPECTED = {"bbox": [W, D, L], "solids": 1}\n')
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["ok"], st.get("error")
    r = c.post(f"/api/m/drawings/projects/{pid}/generate", json={"sheet": "A3"})
    assert r.status_code == 200, r.text
    rec = r.json()["drawing"]
    assert rec["check"]["passed"], rec["check"]  # the main sheet (views) of a bent part passes CHK-12 too
    fp = rec["flat_pattern"]
    assert fp["bends"] == 2 and fp["size"] == pytest.approx(st["sheet_metal"]["flat"]["size"], abs=1e-6)
    assert [b["direction"] for b in fp["table"]] == ["UP", "UP"] and fp["table"][1]["angle"] == 180
    svg = c.get(f"/api/m/drawings/projects/{pid}/files/flat.svg").text
    assert "B1 UP 90° R2" in svg and "BEND TABLE" in svg and "FLAT PATTERN" in svg and "K = 0.44" in svg
    pdf = c.get(f"/api/m/drawings/projects/{pid}/files/flat.pdf")
    assert pdf.content.startswith(b"%PDF-") and "_flat_pattern.pdf" in pdf.headers["content-disposition"]
    # DXF: the outline in model space at true size (same perimeter as the flat pattern)
    doc = ezdxf.readfile(ws / "drawings" / "flat_sheet.dxf")
    vis = [e for e in doc.modelspace() if e.dxf.layer == "VISIBLE" and e.dxftype() == "LINE"]
    per = sum(math.dist(tuple(e.dxf.start)[:2], tuple(e.dxf.end)[:2]) for e in vis)
    assert per == pytest.approx(st["sheet_metal"]["flat"]["perimeter_mm"], abs=1e-3)
    assert len([e for e in doc.modelspace() if e.dxf.layer == "CENTER"]) == 2  # one centre line per bend
    # Manufacturing Advisor: sheet metal from the model, flat size and bend count, advisory flags only
    a = c.post(f"/api/m/manufacturing/projects/{pid}/analyse", json={"quantity": 10, "material": "steel_1018"}).json()
    sig = a["signals"]["sheet"]
    assert sig["model"] and sig["bend_count"] == 2 and sig["flat_size"] == st["sheet_metal"]["flat"]["size"]
    flat3 = [f for f in a["findings"] if f["rule"] == "SHM-03"]
    assert len(flat3) == 1 and flat3[0]["severity"] == "info" and "2 bends" in flat3[0]["title"]
    assert not [f for f in a["findings"] if f["rule"] in ("SHM-04", "SHM-05")]  # 30 mm flange, R = T: no flags
    assert "sheet_metal" in {r_["process"] for r_ in a["process"]["ranking"]}


def json_dump(x: object) -> str:
    import json

    return json.dumps(x)


def test_dfm_flags_short_flange_and_tight_radius() -> None:
    from aicad.manufacturing.analyze import Inputs, analyse_shape
    from aicad.manufacturing.shop import ShopProfile

    t = 2.0
    s, part = _plate(80, 50, t, 1.0, 0.44)  # R1 < T2
    s, part = sm.flange(s, part, (0, 25, t), 6.0, 90)  # 6 mm outer < 4·T = 8 mm
    fl = sm.flatten(s, part)
    smd = sm.summary(s, fl)
    a = analyse_shape(part, ShopProfile(), Inputs(quantity=10, material="steel_1018"), sheet_model=smd)  # type: ignore[arg-type]
    by = {f["rule"]: f for f in a["findings"]}
    assert by["SHM-04"]["severity"] == "warning" and by["SHM-04"]["value"] == pytest.approx(6.0)
    assert "≥ 8 mm" in by["SHM-04"]["limit"]
    assert by["SHM-05"]["severity"] == "warning" and by["SHM-05"]["value"] == pytest.approx(1.0)
    assert a["cost"]  # the sheet line is costed from the flat blank
    line = a["process"]["ranking"]
    assert any(r["process"] == "sheet_metal" for r in line)
    # advisory only: nothing claims the part is fit to make
    text = json_dump(a["findings"]).lower()
    assert "approved for manufacture" not in text and "manufacturable" not in text


def test_agent_wording_hides_sheet_metal_helper_names() -> None:
    from aicad.agent import prompt
    from aicad.agent.session import scrub

    out = scrub("I used fw.base_flange, then `fw.edge_flange` twice and fw.hem on the back edge.")
    assert "fw." not in out and "base_flange" not in out and "edge_flange" not in out
    assert "fw.edge_flange" in prompt.CAD_AGENT_INSTRUCTIONS and "fw.base_flange" in prompt.CAD_AGENT_INSTRUCTIONS


# ----------------------------------------------------------------------------- follow-ups: corners, cuts through bends, jog
def _box_corner(corner: str, relief: str, gap: float = 0.2) -> tuple[sm.Sheet, object, dict]:
    s, part = _plate(100, 60, 2.0, 2.0, 0.44, relief=relief, relief_ratio=0.5, corner=corner, corner_gap=gap)
    s, part = sm.flange(s, part, (0, 30, 2.0), 25, 90)  # top edge, full length
    s, part = sm.flange(s, part, (50, 0, 2.0), 25, 90)  # right edge: meets the first flange at a corner
    return s, part, sm.flatten(s, part)


@pytest.mark.parametrize(("corner", "relief"), [("closed", "rect"), ("closed", "obround"), ("open", "rect"),
                                                 ("open", "none")])
def test_corner_relief_where_adjacent_flanges_meet(corner: str, relief: str) -> None:
    from build123d import Align, Box, Pos

    w, d, t, r, k, ln, g = 100.0, 60.0, 2.0, 2.0, 0.44, 25.0, 0.2
    s, part, fl = _box_corner(corner, relief, g)
    sb, ba, ls = r + t, _ba(90, r, k, t), ln - (r + t)
    cw = 0.5 * t  # relief width = ratio x T (relief "none": half the thickness so the bends part)
    relief_area = {"rect": cw * cw, "obround": math.pi * cw * cw / 4, "none": 0.0}[relief]
    base = w * d - sb * w - sb * (d - sb) - relief_area
    bend1 = (w - (sb + cw)) * ba  # first flange's bend cut back to the second bend start + relief
    bend2 = (d - sb) * ba
    if corner == "closed":  # first wall carried on to the gap from the second wall's inside face
        wall1, wall2 = ls * (w - t - g), ls * (d - sb + r + t)  # second wall reaches the first wall's outer face
    else:
        wall1, wall2 = ls * (w - (sb + cw)), ls * (d - sb)
    assert fl["area"] == pytest.approx(base + bend1 + bend2 + wall1 + wall2, rel=1e-9)
    assert fl["exact"] and not fl["notes"] and len(fl["local"].solids()) == 1  # type: ignore[attr-defined]
    assert part.is_valid and len(part.solids()) == 1  # type: ignore[attr-defined]
    assert part.volume == pytest.approx(sm.model_volume(s), rel=1e-9)  # type: ignore[attr-defined]
    # flat size is unchanged by the corner: W - s + BA + straight in each direction
    assert fl["size"] == pytest.approx([w - sb + ba + ls, d - sb + ba + ls], abs=1e-6)
    # the first bend's line in the flat stops at the relief
    line = fl["bends"][0]["line"]
    assert abs(line[0][0] - line[1][0]) == pytest.approx(w - (sb + cw), abs=1e-6)
    if corner == "closed":  # folded: the gap between the first wall's end and the second wall's inside face is g
        x_in = w / 2 - t
        probe = Pos(x_in - g + 1e-3, d / 2 - t + 1e-3, sb + 1) * Box(g - 2e-3, t - 2e-3, ln - sb - 2,
                                                                    align=(Align.MIN, Align.MIN, Align.MIN))
        assert (part & probe).volume == pytest.approx(0, abs=1e-9)  # type: ignore[operator]
        solid = Pos(x_in - g - 1e-3, d / 2 - t + 1e-3, sb + 1) * Box(1e-3, t - 2e-3, 1,
                                                                   align=(Align.MAX, Align.MIN, Align.MIN))
        assert (part & solid).volume == pytest.approx(solid.volume, rel=1e-6)  # type: ignore[operator]
        bb = part.bounding_box()  # type: ignore[attr-defined]
        assert [bb.max.X, bb.max.Y, bb.max.Z] == pytest.approx([w / 2, d / 2, ln], abs=1e-6)  # closed box corner


def test_three_sided_tray_corners_at_both_ends() -> None:
    w, d, t, r, k, ln, g = 120.0, 80.0, 1.5, 1.5, 0.4, 20.0, 0.2
    s, part = _plate(w, d, t, r, k)
    s, part = sm.flange(s, part, (0, d / 2, t), ln, 90)
    s, part = sm.flange(s, part, (0, -d / 2, t), ln, 90)
    s, part = sm.flange(s, part, (w / 2, 0, t), ln, 90)  # meets both: two corners
    fl = sm.flatten(s, part)
    sb, ba, ls, cw = r + t, _ba(90, r, k, t), ln - (r + t), 0.5 * t
    base = w * d - 2 * sb * w - sb * (d - 2 * sb) - 2 * cw * cw
    bends = 2 * (w - (sb + cw)) * ba + (d - 2 * sb) * ba
    walls = 2 * ls * (w - t - g) + ls * (d - 2 * sb + 2 * (r + t))
    assert fl["area"] == pytest.approx(base + bends + walls, rel=1e-9)
    assert part.is_valid and len(part.solids()) == 1 and len(fl["local"].solids()) == 1  # type: ignore[attr-defined]


def test_cuts_through_a_bend_are_unbent_into_the_flat() -> None:
    from build123d import Align, Box, Cylinder, Pos, Rot

    w, d, t, r, k, ln = 100.0, 60.0, 2.0, 2.0, 0.44, 25.0
    s, part = _plate(w, d, t, r, k)
    s, part = sm.flange(s, part, (0, d / 2, t), ln, 90)
    sb, ba = r + t, _ba(90, r, k, t)
    full = sm.flatten(s, part)["area"]
    # a window 10 wide from 3 mm before the bend, through the bend, 6 mm up the wall: flat hole 10 x (3 + BA + 6)
    a, b, wd = 3.0, 6.0, 10.0
    win = Pos(-wd / 2, d / 2 - sb - a, -1) * Box(wd, 20, sb + b + 1, align=(Align.MIN, Align.MIN, Align.MIN))
    fl = sm.flatten(s, part - win)  # type: ignore[operator]
    assert fl["area"] == pytest.approx(full - wd * (a + ba + b), rel=1e-9)
    assert not fl["notes"] and len(fl["local"].solids()) == 1
    xs = {round(e[p][0], 6) for e in fl["outline"] if e["type"] == "line" for p in ("a", "b")}
    assert -wd / 2 in xs and wd / 2 in xs  # the window's sides are in the outline
    # a radial hole (radius rho) drilled through the middle of the bend: its trace on the neutral surface
    # (radius rn = R + K T) is rho^2 >= rn^2 sin^2(s/rn) + y^2, area = integral of 2 sqrt(rho^2 - rn^2 sin^2(s/rn)) ds
    rho, rn = 1.2, r + k * t
    hole = Pos(0, d / 2 - sb, t + r) * Rot(45, 0, 0) * Cylinder(rho, 40, align=(Align.CENTER, Align.CENTER, Align.MAX))
    smax, n = rn * math.asin(rho / rn), 4000
    trace = sum(2 * math.sqrt(max(0.0, rho ** 2 - (rn * math.sin((-smax + (i + 0.5) * 2 * smax / n) / rn)) ** 2))
                for i in range(n)) * 2 * smax / n
    fl = sm.flatten(s, part - hole)  # type: ignore[operator]
    assert full - fl["area"] == pytest.approx(trace, rel=5e-3)  # sampled outline of the unbent hole
    assert not fl["notes"] and len(fl["local"].solids()) == 1


@pytest.mark.parametrize(("angle", "offset", "flip"), [(90.0, 12.0, False), (60.0, 8.0, False), (90.0, 10.0, True)])
def test_jog_flat_length_and_offset(angle: float, offset: float, flip: bool) -> None:
    from build123d import Cylinder, Pos

    w, d, t, r, k, dist = 100.0, 60.0, 2.0, 2.0, 0.44, 20.0
    s, part = _plate(w, d, t, r, k)
    part = part - Pos(40, 0, 0) * Cylinder(3, 10)  # a hole in the end that moves rides along
    s, part = sm.jog(s, part, (w / 2, 0, t), dist, offset, angle, flip=flip)
    th = math.radians(angle)
    m = (offset - (t + 2 * r) * (1 - math.cos(th))) / math.sin(th)  # offset = (T + 2R)(1 - cos a) + m sin a
    ba = _ba(angle, r, k, t)
    fl = sm.flatten(s, part)
    assert fl["size"] == pytest.approx([w + 2 * ba + m, d], abs=1e-6)
    assert fl["area"] == pytest.approx(w * d - math.pi * 9 + d * (2 * ba + m), rel=1e-9)
    assert any(e["type"] == "circle" and e["r"] == pytest.approx(3) for e in fl["outline"])
    bb = part.bounding_box()  # type: ignore[attr-defined]
    shift = (2 * r + t) * math.sin(th) + m * math.cos(th)  # the moved end starts this far past the jog line
    assert bb.max.X == pytest.approx(w / 2 + shift, abs=1e-6)
    assert [bb.min.Z, bb.max.Z] == pytest.approx([-offset, t] if flip else [0, offset + t], abs=1e-6)
    assert [b["kind"] for b in fl["bends"]] == ["jog", "jog"]
    assert fl["bends"][0]["direction"] != fl["bends"][1]["direction"]
    assert part.is_valid and len(part.solids()) == 1  # type: ignore[attr-defined]
    # flanges still go on the moved end's free edge after the jog
    s, part = sm.flange(s, part, (w / 2 + shift, 0, (-offset if flip else offset) + t), 10, 90)
    assert len(sm.flatten(s, part)["bends"]) == 3


def test_jog_errors_are_plain() -> None:
    s, part = _plate(100, 60, 2, 2, 0.44)
    with pytest.raises(ValueError, match="jog offset must be more than"):
        sm.jog(s, part, (50, 0, 2), 20, 5.0)  # 90 deg: needs more than T + 2R = 6
    s2, p2 = sm.flange(s, part, (0, 30, 2), 20, 90)
    with pytest.raises(ValueError, match="a bend is already on the side that moves"):
        sm.jog(s2, p2, (50, 0, 2), 20, 10)  # the moving end holds part of the flange's bend
    with pytest.raises(ValueError, match="cross the sheet once"):
        sm.jog(s, part, (50, 0, 2), 150, 10)  # the line misses the sheet


def test_studio_corner_and_jog_features(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "sheetjog@x.com")
    pid = c.post("/api/projects", json={"name": "Hand tray"}).json()["id"]
    t, r, k, g = 2.0, 2.0, 0.44, 0.5
    base = {"op": "sm_base", "name": "Base-Flange1", "plane": TOP, "profiles": [_rect(-50, -30, 50, 30)], "t": t,
            "r": r, "k": k, "relief": {"type": "rect", "ratio": 0.5}, "corner": {"type": "closed", "gap": g}}
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": {**base, "corner": {"type": "mitre"}}}).status_code == 422
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": base}).status_code == 200
    # a jog on the right end first: 20 mm in from the edge, raised 12 mm
    jog = {"op": "sm_jog", "name": "Jog1", "edge": [50, 0, t], "edge_ref": {"kind": "line", "dir": [0, 1, 0]},
           "distance": 20, "offset": 12, "angle": 90}
    for bad in ({**jog, "angle": 120}, {**jog, "distance": 0}, {**jog, "offset": -1}):
        assert c.post(f"/api/projects/{pid}/manual", json={"feature": bad}).status_code == 422
    rr = c.post(f"/api/projects/{pid}/manual", json={"feature": {**jog, "offset": 5}})
    assert rr.status_code == 422 and "jog offset must be more than" in rr.json()["detail"]
    assert c.post(f"/api/projects/{pid}/manual", json={"feature": jog}).status_code == 200
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    ba, m = _ba(90, r, k, t), 12 - (t + 2 * r)
    assert st["ok"] and st["sheet_metal"]["flat"]["size"] == pytest.approx([100 + 2 * ba + m, 60], abs=1e-6)
    assert st["fingerprint"]["bbox"] == pytest.approx([100 + 2 * r + t, 60, 12 + t], abs=1e-6)
    # flanges on the left and top edges of the staying piece: they meet at a closed corner (relief cut)
    for fe in ({"op": "sm_flange", "name": "Edge-Flange1", "edge": [-50, 0, t], "edge_ref": {"kind": "line", "dir": [0, 1, 0]},
                "length": 20, "angle": 90},
               {"op": "sm_flange", "name": "Edge-Flange2", "edge": [-10, 30, t], "edge_ref": {"kind": "line", "dir": [1, 0, 0]},
                "length": 20, "angle": 90, "inset": [5, 0]}):
        rr = c.post(f"/api/projects/{pid}/manual", json={"feature": fe})
        assert rr.status_code == 200, rr.text
    st = c.get(f"/api/projects/{pid}/files/status.json").json()
    assert st["ok"] and not st["manual_errors"] and st["sheet_metal"]["corner"] == {"type": "closed", "gap": g}
    assert st["sheet_metal"]["bend_count"] == 4 and not st["sheet_metal"]["notes"]
    # the top flange: the staying piece is 80 long, the left flange took sb, 5 mm offset at the jog end
    sb, cw = r + t, 0.5 * t
    top = next(b for b in st["sheet_metal"]["bends"] if b["name"] == "Edge-Flange2")
    assert top["span"] == pytest.approx(80 - sb - 5, abs=1e-6)
    # the left flange's bend was cut back for the relief: its bend line is (60 - sb) - (sb + cw) long
    left = next(b for b in st["sheet_metal"]["bends"] if b["name"] == "Edge-Flange1")
    (x0, y0), (x1, y1) = left["line"]
    assert math.dist((x0, y0), (x1, y1)) == pytest.approx(60 - (sb + cw), abs=1e-6)
