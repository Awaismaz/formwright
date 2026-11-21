"""Design Office board thumbnails: blueprint line art of a part snapshot, grouped by feature, drawn once per snapshot
in the drawing worker and cached next to it; the endpoint never waits (202) and is scoped by organisation."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from test_office_icd import BRACKET, PLAN, SPACER
from test_office_orchestrator import _program, office  # noqa: F401  (fixture)

from aicad.drawing import thumb
from aicad.office import program_assembly, thumbs


def _groups(svg: str) -> list[tuple[str, str]]:
    return re.findall(r'data-feature="(\w+)" data-g="\d+"(?: data-d="([\d.]+)")?', svg)


def _plate(tmp: Path) -> tuple[Path, dict[str, Any]]:
    """60 x 40 x 8 plate, two Ø6.6 holes, a Ø20 bore, the two -X vertical edges chamfered 2 mm."""
    from build123d import Axis, Box, Cylinder, Pos, chamfer, export_step

    from aicad.assembly import geometry

    s = Box(60, 40, 8) - Pos(-16.8, -6.8, 0) * Cylinder(3.3, 8) - Pos(16.8, 6.8, 0) * Cylinder(3.3, 8) - Cylinder(10, 8)
    s = chamfer(s.edges().filter_by(Axis.Z).group_by(Axis.X)[0], 2)
    tmp.mkdir(parents=True, exist_ok=True)
    export_step(s, str(tmp / "src.step"))
    return tmp, geometry.prepare(tmp, step=str(tmp / "src.step"))


def test_thumb_groups_real_edges_by_feature(tmp_path: Path) -> None:
    d, info = _plate(tmp_path / "plate")
    opts = {**thumbs.view_for([60, 40, 8]), "box": [-30, -20, -4, 30, 20, 4], "frame": None}
    res = thumb.write(str(d / "part.step"), info, opts, str(tmp_path / "a.svg"))
    svg = (tmp_path / "a.svg").read_text(encoding="utf-8")
    g = _groups(svg)
    # the three recognised bores (by diameter), the chamfer faces and the rest of the body; nothing unplaced
    assert sorted(x for x in g if x[0] == "bore") == [("bore", "20"), ("bore", "6.6"), ("bore", "6.6")]
    assert ("chamfer", "") in g and ("envelope", "") in g and res["unplaced"] == 0
    assert 'data-hidden="1"' in svg and 'stroke="currentColor"' in svg and svg.startswith("<svg")
    assert chr(0x2014) not in svg and chr(0x2013) not in svg  # no long dashes
    # deterministic: the same snapshot and view draw the same file
    thumb.write(str(d / "part.step"), info, opts, str(tmp_path / "b.svg"))
    assert (tmp_path / "b.svg").read_text(encoding="utf-8") == svg
    # a frame turns the part into the ICD part frame: a part modelled upside down draws like the upright one
    flip = {"R": [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]], "t": [0.0, 0.0, 0.0]}
    thumb.write(str(d / "part.step"), info, {**opts, "frame": flip}, str(tmp_path / "c.svg"))
    assert sorted(_groups((tmp_path / "c.svg").read_text(encoding="utf-8"))) == sorted(g)


def test_view_choice() -> None:
    assert thumbs.view_for([60, 40, 8])["name"] == "iso"            # a plate: iso
    assert thumbs.view_for([20, 20, 120])["name"] == "iso"          # a shaft: iso
    v = thumbs.view_for([80, 80, 20])                               # a gear blank: 35 degrees off its axis
    assert v["name"] == "axial" and abs(v["dir"][2] - 0.819152) < 1e-5
    v = thumbs.view_for([20, 80, 80])                               # the same disc along X
    assert v["name"] == "axial" and abs(v["dir"][0] - 0.819152) < 1e-5
    assert thumbs.view_for(None)["name"] == "iso"


def test_real_part_keeps_the_placeholder_it_replaced() -> None:
    assert program_assembly._ghost({"key": "h_p_i_1", "kind": "placeholder"}, "p_x_2") == {"ghost": "h_p_i_1"}
    assert program_assembly._ghost({"key": "p_x_2", "kind": "real", "ghost": "h_p_i_1"}, "p_x_3") == {"ghost": "h_p_i_1"}
    assert program_assembly._ghost({"key": "p_x_2", "kind": "real"}, "h_p_i_2") == {}  # a placeholder again
    assert program_assembly._ghost(None, "p_x_2") == {}


def _get(c: Any, url: str, timeout: float = 90) -> Any:
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = c.get(url)
        if r.status_code != 202:
            return r
        assert r.headers["retry-after"] == "1"
        time.sleep(0.2)
    raise AssertionError("thumbnail never drawn")


def test_thumb_endpoint_ghost_real_cache_and_scope(office: Any, tmp_path: Path) -> None:  # noqa: F811
    from test_platform import signup

    from aicad.assembly import store as astore
    from aicad.office import store
    from aicad.platform.config import get_settings

    c = office
    v = _program(c, "thumbs@x.com", PLAN)
    pid = v["id"]
    parts = v["assembly"]["parts"]
    ph = parts[BRACKET]["key"]
    base = f"/api/office/programs/{pid}/items/{BRACKET}/thumb"
    # nothing is drawn until a card asks; the first ask answers at once (202) and the drawing follows
    org = c.get("/api/auth/me").json()["org"]["id"]
    aroot = astore.org_root(get_settings().data_dir, org)
    assert not list((astore.part_dir(aroot, ph)).glob("thumb_v*.svg"))
    r = _get(c, f"{base}?state=ghost")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml"), r.text
    assert r.headers["cache-control"] == "private, no-cache"
    g = _groups(r.text)
    assert sorted(x for x in g if x[0] == "bore") == [("bore", "6.6")] * 4  # the bracket's four M6 clearance holes
    files = list(astore.part_dir(aroot, ph).glob(f"thumb_v{thumb.VERSION}_*.svg"))
    assert len(files) == 1 and files[0].read_text(encoding="utf-8") == r.text  # cached next to the snapshot
    r2 = c.get(f"{base}?state=ghost&k={ph}")
    assert r2.status_code == 200 and r2.text == r.text and "immutable" in r2.headers["cache-control"]
    assert c.get(f"{base}?state=ghost&k=h_other").status_code == 404      # the card's key is out of date
    assert c.get(f"{base}?state=real").status_code == 404                  # still a placeholder
    assert c.get(f"{base}?state=bogus").status_code == 422
    assert c.get(f"/api/office/programs/{pid}/items/i_nope/thumb?state=ghost").status_code == 404
    # the spacer (a ring) is drawn too; its own key
    assert _get(c, f"/api/office/programs/{pid}/items/{SPACER}/thumb?state=ghost").status_code == 200
    # the approved part: a real snapshot in the part cache replaces the placeholder (as Fitz's swap records it)
    key = "p_thumbtest_1"
    d, _info = _plate(astore.part_dir(aroot, key))
    astore.write_json(d / "meta.json", {"key": key, "kind": "project", "name": "Bracket"})
    root = store.org_root(get_settings().data_dir, org)
    with store.lock(pid):
        doc = store.load(root, pid)
        doc["assembly"]["parts"][BRACKET] = {"key": key, "kind": "real", "icd_version": 1,
                                             **program_assembly._ghost(doc["assembly"]["parts"][BRACKET], key)}
        store.save(root, doc)
    assert c.get(f"/api/office/programs/{pid}").json()["assembly"]["parts"][BRACKET]["ghost"] == ph
    real = _get(c, f"{base}?state=real&k={key}")
    assert real.status_code == 200 and real.text != r.text
    assert sorted(x for x in _groups(real.text) if x[0] == "bore") == [("bore", "20"), ("bore", "6.6"), ("bore", "6.6")]
    assert _get(c, f"{base}?state=ghost&k={ph}").text == r.text  # the ghost stays what it was
    # another organisation sees nothing
    c.post("/api/auth/logout")
    signup(c, "thumbs-intruder@x.com", workspace="Other Co")
    assert c.get(f"{base}?state=ghost").status_code == 404
    assert c.get(f"{base}?state=real&k={key}").status_code == 404
    assert json.dumps(c.get(f"{base}?state=ghost").json()).find("h_") < 0  # no key leaks in the error
