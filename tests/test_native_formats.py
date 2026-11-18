"""Native formats (IO-020..IO-024): .fwpart / .fwasm / .fwdrw / .fwprog round trips between workspaces, tamper
detection, malicious archives, the script gate, cross-workspace trust, assembly dedup and the version migration hook."""

from __future__ import annotations

import io
import json
import stat
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_platform import _project_with_model, app_client, signup  # noqa: F401  (fixture re-export)

from aicad.native import NativeFormatError, gate
from aicad.native import container as c

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"


# ------------------------------------------------------------------------------------------------ helpers
def _zip(entries: list[tuple[str, bytes]], symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries:
            zi = zipfile.ZipInfo(name, c.ZIP_EPOCH)
            zi.compress_type = zipfile.ZIP_DEFLATED
            if name == symlink:
                zi.create_system = 3
                zi.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(zi, data)
    return buf.getvalue()


def _manifest(files: dict[str, bytes], **kw: Any) -> bytes:
    m = {"format": "formwright.part", "format_version": 1,
         "entries": {n: {"sha256": c.sha256(d), "size": len(d)} for n, d in files.items()}, **kw}
    return json.dumps(m).encode()


def _repack(data: bytes, change: dict[str, bytes | None], tmp: Path, org: str = "someone-else",
            manifest_patch: dict[str, Any] | None = None) -> bytes:
    """An attacker's re-pack: changed entries with a *consistent* manifest, signed by another workspace."""
    pkg = c.read_package(data)
    files = dict(pkg.files)
    for k, v in change.items():
        if v is None:
            files.pop(k, None)
        else:
            files[k] = v
    body = {k: v for k, v in pkg.manifest.items() if k not in ("entries", "signature", "format", "format_version")}
    body.update(manifest_patch or {})
    return c.write_package(pkg.ext, files, body, tmp, org)


def _ws(pid: str) -> Path:
    from aicad.platform.db import session_factory
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    db = session_factory()()
    try:
        return workspace_for(db.get(Project, pid))
    finally:
        db.close()


def _status(c_: TestClient, pid: str) -> dict[str, Any]:
    return c_.get(f"/api/projects/{pid}/files/status.json").json()


def _bracket(cl: TestClient) -> str:
    """The demo L bracket plus a manual hole (managed block) and a parameter edit (two revisions)."""
    pid, _ = _project_with_model(cl, (DEMO / "l_bracket.py").read_text(encoding="utf-8"))
    hole = {"op": "hole", "name": "Extra hole", "point": [30, 25, 5], "normal": [0, 0, 1], "d": 6}
    assert cl.post(f"/api/projects/{pid}/manual", json={"feature": hole}).status_code == 200
    return pid


def _post_file(cl: TestClient, path: str, data: bytes, filename: str, **params: Any) -> Any:
    q = "&".join([f"filename={filename}"] + [f"{k}={v}" for k, v in params.items()])
    return cl.post(f"/api/native/{path}?{q}", content=data, headers={"Content-Type": "application/octet-stream"})


def _switch(cl: TestClient, email: str, workspace: str) -> None:
    cl.post("/api/auth/logout")
    signup(cl, email, workspace=workspace)


# ------------------------------------------------------------------------------------------------ container
def test_malicious_archives_are_rejected() -> None:
    model = b"from build123d import *\nresult = Box(1, 1, 1)\n"
    ok_files = {"model.py": model}
    cases = {
        "zip slip": [("manifest.json", _manifest({"../evil.py": model})), ("../evil.py", model)],
        "absolute": [("manifest.json", _manifest({"/etc/evil.py": model})), ("/etc/evil.py", model)],
        "drive": [("manifest.json", _manifest({"C:/evil.py": model})), ("C:/evil.py", model)],
        "backslash": [("manifest.json", _manifest({"a\\..\\evil.py": model})), ("a\\..\\evil.py", model)],
        "hidden": [("manifest.json", _manifest({".fw/x.py": model})), (".fw/x.py", model)],
        "reserved": [("manifest.json", _manifest({"imports/CON.step": model})), ("imports/CON.step", model)],
        "no manifest": [("model.py", model)],
        "extra entry": [("manifest.json", _manifest(ok_files)), ("model.py", model), ("other.py", model)],
        "bad checksum": [("manifest.json", _manifest(ok_files)), ("model.py", model + b"#")],
        "newer version": [("manifest.json", json.dumps({"format": "formwright.part", "format_version": 99,
                                                        "entries": {}}).encode())],
        "unknown format": [("manifest.json", json.dumps({"format": "x", "format_version": 1, "entries": {}}).encode())],
    }
    for label, entries in cases.items():
        with pytest.raises(NativeFormatError):
            c.read_package(_zip(entries))
        assert label
    with pytest.raises(NativeFormatError, match="link"):
        c.read_package(_zip([("manifest.json", _manifest({"model.py": model})), ("model.py", model)], symlink="model.py"))
    bomb = b"\0" * (40 * 1024 * 1024)  # 40 MB of zeros compresses ~1000:1
    with pytest.raises(NativeFormatError, match="zip bomb"):
        c.read_package(_zip([("manifest.json", _manifest({"imports/a.step": bomb})), ("imports/a.step", bomb)]))
    with pytest.raises(NativeFormatError, match="not a valid package"):
        c.read_package(b"hello")


def test_deterministic_write_and_signature(tmp_path: Path) -> None:
    files = {"model.py": b"result = 1\n", "imports/a.json": b"{}"}
    a = c.write_package("fwpart", files, {"title": "x"}, tmp_path, "org1")
    b = c.write_package("fwpart", dict(reversed(list(files.items()))), {"title": "x"}, tmp_path, "org1")
    assert a == b                                   # byte-identical: ordering and timestamps are fixed
    with zipfile.ZipFile(io.BytesIO(a)) as z:
        assert z.namelist()[:2] == ["mimetype", "manifest.json"]
        assert all(i.date_time == c.ZIP_EPOCH for i in z.infolist())
    assert c.sniff_ext(a) == "fwpart"
    pkg = c.read_package(a)
    assert c.trust_for(pkg.manifest, tmp_path, "org1") == ("workspace", None)
    assert c.trust_for(pkg.manifest, tmp_path, "org2")[0] == "foreign"
    pkg.manifest["title"] = "changed"               # same org, but the signed manifest was edited
    trust, note = c.trust_for(pkg.manifest, tmp_path, "org1")
    assert trust == "foreign" and "changed after export" in note
    assert pkg.manifest["signature"]["org"] != "org1"  # never the raw workspace id


def test_version_migration_hook(tmp_path: Path) -> None:
    files = {"model.py": b"result = 1\n"}
    raw = _zip([("manifest.json", json.dumps({
        "format": "formwright.part", "format_version": 0, "fingerprint": {"volume": 1.0}, "step_sha256": "ab",
        "entries": {"model.py": {"sha256": c.sha256(files["model.py"]), "size": len(files["model.py"])}}}).encode()),
        ("model.py", files["model.py"])])
    pkg = c.read_package(raw)
    assert pkg.migrated_from == 0 and pkg.manifest["format_version"] == c.FORMAT_VERSION
    assert pkg.manifest["geometry"] == {"fingerprint": {"volume": 1.0}, "step_sha256": "ab"}
    assert "fingerprint" not in pkg.manifest and pkg.warnings
    saved = c.MIGRATIONS.pop(("formwright.part", 0))
    try:
        with pytest.raises(NativeFormatError, match="old format version"):
            c.read_package(raw)
    finally:
        c.MIGRATIONS[("formwright.part", 0)] = saved


def test_script_gate() -> None:
    real = [(DEMO / n).read_text(encoding="utf-8") for n in ("l_bracket.py", "mounting_plate.py")]
    from aicad import toolbox

    real.append(toolbox.model_source("flange", {}))
    real.append("from build123d import *\nresult = Box(1, 1, 1)\n"
                "# --- Formwright manual features\nfrom aicad import fw as _fw\n\nMANUAL_FEATURES = []\n"
                "result = _fw.apply_manual(result, MANUAL_FEATURES)\n")
    for src in real:
        gate.check_script(src, "m", strict=True, helpers=set())
    with pytest.raises(NativeFormatError, match="os"):
        gate.check_script("import os\nresult = 1\n", "m", strict=False, helpers=set())
    gate.check_script("from OCP.BRepTools import BRepTools\nresult = 1\n", "m", strict=False, helpers=set())
    bad = ["from OCP.BRepTools import BRepTools", "from build123d import export_step",
           "from build123d import *\nexport_stl(Box(1,1,1), 'C:/x.stl')", "x = (1).__class__",
           "getattr(1, 'real')", "from aicad import fw\nfw._refplane", "from aicad import fw\nfw.itertools",
           "from build123d import *\nBox(1,1,1).export_brep('x')", "import numpy", "from . import x",
           "'{0.__class__}'.format(1)", "from build123d import *\nimport_step('x.step')", "global x",
           "import helper_x"]
    for src in bad:
        with pytest.raises(NativeFormatError):
            gate.check_script(src + "\nresult = 1\n", "m", strict=True, helpers=set())
    gate.check_script("import helper_x\nresult = helper_x.make()\n", "m", strict=True, helpers={"helper_x"})
    with pytest.raises(NativeFormatError):
        gate.helper_names(["math.py"])


# ------------------------------------------------------------------------------------------------ API round trips
def test_part_round_trip_trust_tamper_and_malicious(app_client: TestClient, tmp_path: Path) -> None:  # noqa: F811
    cl = app_client
    signup(cl, "alice@x.com", workspace="Alice Works")
    pid = _bracket(cl)
    r = cl.get(f"/api/native/projects/{pid}/export")
    assert r.status_code == 200, r.text
    src = _status(cl, pid)  # after the export: it waits for the background exports of the last edit
    assert r.headers["content-type"] == "application/vnd.formwright.part+zip"
    assert 'filename="Plate.fwpart"' in r.headers["content-disposition"]
    data = r.content
    assert cl.get(f"/api/native/projects/{pid}/export").content == data      # deterministic
    pkg = c.read_package(data)
    assert {"model.py", "out/part.step", "out/status.json", "design/brief.json"} <= set(pkg.files)
    assert any(n.startswith("revisions/") for n in pkg.files) and "chat/chat.jsonl" not in pkg.files
    assert b"# --- Formwright manual features" in pkg.files["model.py"]
    m = pkg.manifest
    assert m["format"] == "formwright.part" and m["part"]["units"] == "mm" and m["geometry"]["fingerprint"] == src["fingerprint"]
    assert m["geometry"]["step_sha256"] == src["step_sha256"] and "build123d" in m["kernel"]
    assert pid not in json.dumps(m)                                         # opaque ids only
    assert len(cl.get(f"/api/native/projects/{pid}/export?history=0").content) < len(data)
    # same workspace: trusted
    v = _post_file(cl, "inspect", data, "Plate.fwpart").json()
    assert v["trust"] == "workspace" and not v["needs_confirm"] and v["summary"]["parameters"] > 0
    # another workspace: notice + confirmation before the first rebuild
    _switch(cl, "bob@x.com", "Bob Builds")
    v = _post_file(cl, "inspect", data, "Plate.fwpart").json()
    assert v["trust"] == "foreign" and v["needs_confirm"] and v["kind"] == "part"
    r = _post_file(cl, "import", data, "Plate.fwpart")
    assert r.status_code == 409 and r.json()["detail"]["needs_confirm"]
    assert cl.get("/api/projects").json()["items"] == []
    r = _post_file(cl, "import", data, "Plate.fwpart", confirm=1)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["verification"]["state"] == "identical", res
    assert res["verification"]["step_identical"]
    new = res["project"]["id"]
    st = _status(cl, new)
    assert st["ok"] and st["fingerprint"] == src["fingerprint"]
    assert st["editable_params"] == src["editable_params"] and st["manual_features"] == 1
    assert [f["name"] for f in st["features"]] == [f["name"] for f in src["features"]]
    assert cl.get(f"/api/projects/{new}/manual").json()["features"][0]["name"] == "Extra hole"
    revs = cl.get(f"/api/projects/{new}/revisions").json()["items"]
    assert len(revs) == 2 and revs[0]["kind"] == "import" and revs[1]["why"].startswith("Manual feature")
    prov = cl.get(f"/api/native/projects/{new}/provenance").json()["import"]
    assert prov["verification"]["state"] == "identical" and prov["trust"] == "foreign"
    # parameters are immediately editable (no AI)
    name = next(iter(st["editable_params"]))
    val = st["editable_params"][name]
    r = cl.post(f"/api/projects/{new}/params", json={"values": {name: val + 1}})
    assert r.status_code == 200, r.text
    # tampering: one byte of the model changed -> checksum mismatch, nothing created
    n_before = len(cl.get("/api/projects").json()["items"])
    bad = _zip([(n, (pkg.files.get(n, b"") + b"#") if n == "model.py" else
                 json.dumps(m).encode() if n == "manifest.json" else pkg.files[n])
                for n in ["manifest.json", *pkg.files]])
    r = _post_file(cl, "import", bad, "Plate.fwpart", confirm=1)
    assert r.status_code == 422 and "changed after export" in r.json()["detail"]
    # a consistent re-pack whose model imports os: the gate stops it before anything runs
    evil = _repack(data, {"model.py": b"import os\nos.system('echo pwned')\n" + pkg.files["model.py"]}, tmp_path)
    r = _post_file(cl, "import", evil, "Plate.fwpart", confirm=1)
    assert r.status_code == 422 and "'os' is not allowed" in r.json()["detail"]
    # strict gate for foreign files: file access through the CAD library is refused
    evil = _repack(data, {"model.py": pkg.files["model.py"] + b"\nexport_stl(result, 'C:/temp/x.stl')\n"}, tmp_path)
    r = _post_file(cl, "import", evil, "Plate.fwpart", confirm=1)
    assert r.status_code == 422 and "export_stl" in r.json()["detail"]
    zslip = _zip([("manifest.json", _manifest({"../../x.py": b"x"})), ("../../x.py", b"x")])
    assert _post_file(cl, "import", zslip, "x.fwpart", confirm=1).status_code == 422
    assert len(cl.get("/api/projects").json()["items"]) == n_before
    # the script can't rebuild here: exact geometry kept from the embedded STEP (read-only fallback)
    broken = _repack(data, {"model.py": b"from build123d import *\nresult = Box(1, 1, 1) + missing_name\n"}, tmp_path)
    res = _post_file(cl, "import", broken, "Plate.fwpart", confirm=1).json()
    assert res["verification"]["state"] == "fallback" and not res["verification"]["diffs"]
    assert _status(cl, res["project"]["id"])["fingerprint"] == src["fingerprint"]


def test_assembly_round_trip_with_dedup(app_client: TestClient) -> None:  # noqa: F811
    cl = app_client
    signup(cl, "asm1@x.com", workspace="Asm One")
    plate, _ = _project_with_model(cl, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    bracket, _ = _project_with_model(cl, (DEMO / "l_bracket.py").read_text(encoding="utf-8"))
    v = cl.post("/api/m/assembly/assemblies", json={"project_id": plate}).json()
    aid = v["assembly"]["id"]
    v = cl.post(f"/api/m/assembly/assemblies/{aid}/instances", json={"project_id": bracket}).json()
    v = cl.post(f"/api/m/assembly/assemblies/{aid}/instances", json={"project_id": bracket}).json()  # 2nd instance
    v = cl.post(f"/api/m/assembly/assemblies/{aid}/instances", json={"toolbox": {"code": "hex_bolt", "params": {"D": 6, "L": 25}}}).json()
    assert len(v["instances"]) == 4, v
    plate_i, br_i = v["instances"][0]["id"], v["instances"][1]["id"]
    from aicad.platform.config import get_settings

    refs = {}
    for iid in (plate_i, br_i):
        inst = next(i for i in v["instances"] if i["id"] == iid)
        org = next(iter((get_settings().data_dir / "assemblies").iterdir())).name
        refs[iid] = json.loads((get_settings().data_dir / "assemblies" / org / "_parts" / inst["part"] / "refs.json")
                               .read_text(encoding="utf-8"))
    fa = next(int(k) for k, f in refs[plate_i]["faces"].items() if f["kind"] == "plane" and f["v"][2] > 0.99)
    fb = next(int(k) for k, f in refs[br_i]["faces"].items() if f["kind"] == "plane" and f["v"][2] < -0.99)
    v = cl.post(f"/api/m/assembly/assemblies/{aid}/mates", json={
        "type": "coincident", "a": {"inst": plate_i, "kind": "face", "id": fa}, "b": {"inst": br_i, "kind": "face", "id": fb}}).json()
    assert v["mates"][0]["status"] == "ok", v["mates"]
    pstat = _status(cl, plate)
    r = cl.get(f"/api/native/assemblies/{aid}/export")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/vnd.formwright.assembly+zip"
    data = r.content
    pkg = c.read_package(data)
    assert sum(1 for n in pkg.files if n.endswith(".fwpart")) == 2           # bracket embedded once
    plate_bytes = cl.get(f"/api/native/projects/{plate}/export").content
    # other workspace already has the plate (imported earlier): the assembly links to it instead of duplicating
    _switch(cl, "asm2@x.com", "Asm Two")
    res = _post_file(cl, "import", plate_bytes, "plate.fwpart", confirm=1).json()
    assert res["verification"]["state"] == "identical"
    res = _post_file(cl, "import", data, "asm.fwasm", confirm=1)
    assert res.status_code == 200, res.text
    res = res.json()
    actions = sorted(p["action"] for p in res["parts"])
    assert actions == ["imported", "linked"], res["parts"]
    assert res["verification"]["state"] == "identical" and res["mates"] == 1 and res["mates_dropped"] == 0
    names = [p["name"] for p in cl.get("/api/projects").json()["items"]]
    assert len(names) == 2                                                  # plate once, bracket once
    va = cl.get(f"/api/m/assembly/assemblies/{res['assembly']['id']}").json()
    assert len(va["instances"]) == 4 and va["mates"][0]["status"] == "ok"
    assert any(i["source"]["kind"] == "toolbox" for i in va["instances"])
    linked = next(p for p in res["parts"] if p["action"] == "linked")
    assert _status(cl, linked["project"]["id"])["fingerprint"] == pstat["fingerprint"]
    # importing the same assembly again links every part (no new projects)
    res2 = _post_file(cl, "import", data, "asm.fwasm", confirm=1).json()
    assert all(p["action"] == "linked" for p in res2["parts"])
    assert len(cl.get("/api/projects").json()["items"]) == 2


def test_drawing_and_program_round_trip(app_client: TestClient) -> None:  # noqa: F811
    cl = app_client
    signup(cl, "drw1@x.com", workspace="Draw One")
    pid, _ = _project_with_model(cl, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    assert cl.post(f"/api/m/drawings/projects/{pid}/generate", json={"sheet": "A3"}).status_code == 200
    assert cl.put(f"/api/m/drawings/projects/{pid}/edits", json={"notes": ["Deburr all edges"], "regenerate": False}).status_code == 200
    r = cl.get(f"/api/native/drawings/{pid}/export")
    assert r.status_code == 200, r.text
    drw = r.content
    assert "part.fwpart" in c.read_package(drw).files
    prog = cl.post("/api/office/programs", json={"name": "Bracket kit", "brief": "A small wall bracket kit with a plate.",
                                                 "planner": "standard"}).json()
    r = cl.get(f"/api/native/programs/{prog['id']}/export")
    assert r.status_code == 200, r.text
    prg = r.content
    _switch(cl, "drw2@x.com", "Draw Two")
    res = _post_file(cl, "import", drw, "plate.fwdrw", confirm=1)
    assert res.status_code == 200, res.text
    res = res.json()
    assert res["verification"]["state"] == "identical" and res["drawing_note"] is None
    d = cl.get(f"/api/m/drawings/projects/{res['project']['id']}").json()
    assert d["drawing"] and not d["stale"] and d["edits"]["notes"] == ["Deburr all edges"]
    assert d["drawing"]["sheet"]["size"] == "A3"
    res = _post_file(cl, "import", prg, "kit.fwprog", confirm=1)
    assert res.status_code == 200, res.text
    new = res.json()["program"]["id"]
    got = cl.get(f"/api/office/programs/{new}").json()
    assert got["name"] == "Bracket kit" and got["brief"].startswith("A small wall bracket")
    assert len(got["tickets"]) == len(prog["tickets"])


def test_export_all_and_import_archive(app_client: TestClient) -> None:  # noqa: F811
    cl = app_client
    signup(cl, "all@x.com", workspace="All Parts")
    _project_with_model(cl, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    cl.post("/api/projects", json={"name": "Empty"})                         # nothing built: skipped
    r = cl.get("/api/native/projects/export-all")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    pkg = c.read_package(r.content)
    assert pkg.ext == "zip" and len(pkg.files) == 1 and pkg.manifest["skipped"] == ["Empty"]
    _switch(cl, "all2@x.com", "All Two")
    res = _post_file(cl, "import", r.content, "all.zip", confirm=1).json()
    assert [p["verification"]["state"] for p in res["parts"]] == ["identical"]
    v = _post_file(cl, "inspect", b"PK\x03\x04garbage", "x.fwpart")
    assert v.status_code == 415
    assert _post_file(cl, "inspect", b"hello", "notes.txt").status_code == 415


# ------------------------------------------------------------------------------------------------ every module (IO-025)
def _png() -> bytes:
    import struct
    import zlib

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0" + b"\xff" * 6 + b"\0" + b"\xff" * 6)) + chunk(b"IEND", b""))


def test_every_module_saves_and_opens(app_client: TestClient, tmp_path: Path) -> None:  # noqa: F811
    from aicad.platform.config import get_settings

    cl = app_client
    me = signup(cl, "mods1@x.com", workspace="Mods One")
    org = me["org"]["id"]
    data_dir = get_settings().data_dir
    pid, ws = _project_with_model(cl, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    # Manufacturing Advisor: a real analysis
    assert cl.post(f"/api/m/manufacturing/projects/{pid}/analyse", json={"quantity": 50}).status_code == 200
    # Engineering, print, Mesh Studio and AI Render folders (module outputs written as the modules store them)
    (ws / "engineering").mkdir(exist_ok=True)
    (ws / "engineering" / "calc_sets.json").write_text(json.dumps([{"id": "cs_1", "name": "Bolts", "items": [],
        "signoff": {"by": "Ada", "user_id": me["user"]["id"]}, "project_id": pid}]), encoding="utf-8")
    (ws / "engineering" / "geometry.json").write_text("{}", encoding="utf-8")       # a cache: never exported
    (ws / "print").mkdir(exist_ok=True)
    (ws / "print" / "setup.json").write_text(json.dumps({"preset": "fdm", "path": "C:/Users/ada/x.3mf"}), encoding="utf-8")
    jid = "0123456789abcdef"
    (ws / "mesh" / "renders" / jid).mkdir(parents=True)
    (ws / "mesh" / "look.json").write_text(json.dumps({"preset": "studio"}), encoding="utf-8")
    (ws / "mesh" / "renders" / jid / "job.json").write_text(json.dumps({"id": jid, "state": "done", "outputs": ["render.png"]}), encoding="utf-8")
    (ws / "mesh" / "renders" / jid / "render.png").write_bytes(_png())
    (ws / "mesh" / "renders" / jid / "scene.blend").write_bytes(b"BLENDER-v300")    # never exported (can hold scripts)
    (ws / "airender" / jid).mkdir(parents=True)
    (ws / "airender" / jid / "job.json").write_text(json.dumps({"id": jid, "state": "done", "outputs": ["out_1.png"],
                                                                "prompt": "studio shot"}), encoding="utf-8")
    (ws / "airender" / jid / "out_1.png").write_bytes(_png())
    # 2D draft, Image-to-CAD read, 3D Print Prep mesh upload
    did = cl.post("/api/m/drawings/drafts", json={"name": "Gasket G1", "sheet": {"size": "A4"}, "template": "gasket",
                                                  "params": {"od": 150, "id": 60, "holes": 6, "hole_d": 14, "pcd": 120}}).json()["id"]
    from aicad.image2cad import store as istore

    d, meta = istore.create(data_dir, org, "u", "bracket.png", _png())
    istore.write_json(d, "read.json", {"values": [{"label": "Width", "value": 40}]})
    istore.update_meta(d, status="read")
    from aicad.printprep import service as psvc

    stl = b"solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 10 0 0\nvertex 0 10 0\nendloop\nendfacet\nendsolid t\n"
    up = psvc.create_upload(data_dir, org, "u", "tri.stl", stl, "mm")
    files: dict[str, tuple[bytes, str]] = {}
    for kind, ident, ext in (("mfg", pid, "fwmfg"), ("calc", pid, "fwcalc"), ("print", pid, "fwprint"),
                             ("mesh", pid, "fwrender"), ("ai", pid, "fwrender"), ("draft", did, "fwdrw"),
                             ("read", meta["id"], "fwread"), ("upload", up["id"], "fwprint")):
        r = cl.get(f"/api/native/modules/{kind}/{ident}/export")
        assert r.status_code == 200, (kind, r.text)
        assert r.headers["content-type"] == f"application/vnd.formwright.{c.FORMATS[ext][0].split('.')[1]}+zip"
        pkg = c.read_package(r.content)
        assert pkg.ext == ext and pkg.manifest["kind"] == kind
        assert org not in r.content.decode("latin-1") and me["user"]["id"] not in json.dumps(pkg.manifest)
        files[kind] = (r.content, ext)
    mesh = c.read_package(files["mesh"][0])
    assert f"doc/renders/{jid}/render.png" in mesh.files and not any(n.endswith(".blend") for n in mesh.files)
    calc = c.read_package(files["calc"][0])
    assert "doc/geometry.json" not in calc.files and me["user"]["id"].encode() not in calc.files["doc/calc_sets.json"]
    assert b"C:/Users" not in c.read_package(files["print"][0]).files["doc/setup.json"]
    assert cl.get(f"/api/native/modules/mfg/{cl.post('/api/projects', json={'name': 'E'}).json()['id']}/export").status_code == 409
    # a blend file smuggled into a render package is refused
    evil = _repack(files["mesh"][0], {f"doc/renders/{jid}/scene.blend": b"BLENDER"}, tmp_path)
    _switch(cl, "mods2@x.com", "Mods Two")
    r = _post_file(cl, "import", evil, "x.fwrender", confirm=1)
    assert r.status_code == 422 and "does not accept" in r.json()["detail"]
    results = {}
    for kind, (data, ext) in files.items():
        v = _post_file(cl, "inspect", data, f"x.{ext}").json()
        assert v["kind"] == kind and v["needs_confirm"], v
        r = _post_file(cl, "import", data, f"x.{ext}", confirm=1)
        assert r.status_code == 200, (kind, r.text)
        results[kind] = r.json()
    for kind in ("mfg", "calc", "print", "mesh", "ai"):
        assert results[kind]["verification"]["state"] == "identical", kind
    org2 = cl.get("/api/auth/me").json()["org"]["id"]
    ws2 = _ws(results["calc"]["project"]["id"])
    sets = json.loads((ws2 / "engineering" / "calc_sets.json").read_text(encoding="utf-8"))
    assert sets[0]["signoff"] is None and sets[0]["project_id"] == results["calc"]["project"]["id"]
    assert results["calc"]["notes"]
    mfg = cl.get(f"/api/m/manufacturing/projects/{results['mfg']['project']['id']}/analysis")
    assert mfg.status_code == 200 and mfg.json()["freshness"]["state"] == "current"   # identical STEP: still current
    assert (_ws(results["mesh"]["project"]["id"]) / "mesh" / "renders" / jid / "render.png").is_file()
    assert (_ws(results["ai"]["project"]["id"]) / "airender" / jid / "out_1.png").is_file()
    dr = cl.get(f"/api/m/drawings/drafts/{results['draft']['draft']['id']}").json()
    assert dr["name"] == "Gasket G1" and sorted(x["text"] for x in dr["dimensions"]) == sorted(["Ø150", "Ø60", "Ø120", "6X Ø14"])
    rd = cl.get(f"/api/m/image2cad/uploads/{results['read']['upload']['id']}")
    assert rd.status_code == 200, rd.text
    assert (data_dir / "image2cad" / org2 / results["read"]["upload"]["id"] / "read.json").is_file()
    assert any(u["id"] == results["upload"]["upload"]["id"] for u in cl.get("/api/m/print/uploads").json()["items"])
