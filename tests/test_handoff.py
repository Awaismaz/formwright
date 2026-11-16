"""Shop handoff pack: contents, manifest integrity, stale outputs left out."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from test_platform import _project_with_model, app_client, signup  # noqa: F401  (fixture re-export)

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"


def test_handoff_pack(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "handoff@x.com")
    pid, ws = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    assert c.post(f"/api/projects/{pid}/params", json={"values": {"L": 130}}).status_code == 200
    plan = c.get(f"/api/projects/{pid}/handoff").json()
    kinds = {i["kind"]: i for i in plan["items"]}
    assert plan["ready"] and kinds["drawing"].get("missing") and kinds["dfm"].get("missing") and kinds["notice"]["ok"]
    # a drawing from an older build is flagged and left out unless asked for
    (ws / "drawings").mkdir()
    (ws / "drawings" / "drawing.json").write_text(json.dumps({"build_id": "old", "model_rev": "1"}), encoding="utf-8")
    (ws / "drawings" / "sheet.pdf").write_bytes(b"%PDF-1.4 old drawing")
    plan = c.get(f"/api/projects/{pid}/handoff").json()
    assert next(i for i in plan["items"] if i["kind"] == "drawing")["stale"] is True
    r = c.get(f"/api/projects/{pid}/handoff.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    root = names[0].split("/")[0]
    assert root.endswith("_rev" + str(plan["revision"]))
    rel = sorted(n.split("/", 1)[1] for n in names)
    assert {"model/Plate.step", "model/Plate.stl", "model/Plate.3mf", "CHANGE_NOTICE.txt", "README.txt", "manifest.json"} <= set(rel)
    assert not any(n.startswith("drawing/") for n in rel)
    manifest = json.loads(z.read(f"{root}/manifest.json"))
    for name, meta in manifest["files"].items():  # every file matches its recorded hash
        data = z.read(f"{root}/{name}")
        assert hashlib.sha256(data).hexdigest() == meta["sha256"] and len(data) == meta["bytes"]
    assert manifest["checks_passed"] and manifest["stale_excluded"] == ["Drawing (model rev 1)"]
    readme = z.read(f"{root}/README.txt").decode()
    assert "Left out (older than this revision; regenerate first): Drawing (model rev 1)" in readme
    assert "Not produced yet: Manufacturability report" in readme and "not a manufacturing approval" in readme
    assert "Why: Parameters changed: L 120 → 130" in z.read(f"{root}/CHANGE_NOTICE.txt").decode()
    # explicitly including stale outputs
    z2 = zipfile.ZipFile(io.BytesIO(c.get(f"/api/projects/{pid}/handoff.zip", params={"include_stale": True}).content))
    assert any(n.endswith("drawing/Plate_drawing.pdf") for n in z2.namelist())
