"""Change notices: what changed between revisions and why (deterministic)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_platform import _project_with_model, app_client, signup  # noqa: F401  (fixture re-export)

from aicad import change_notice

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"


def test_diff_lines_are_readable() -> None:
    base = {"status": {"params": {"L": 120, "N": 4}, "features": [{"name": "Base", "kind": "feature"}, {"name": "Holes", "kind": "feature"}],
                       "fingerprint": {"volume": 1000.0, "bbox": [10, 10, 10]}, "material": "Steel 1045", "ok": True},
            "manual": []}
    cur = {"status": {"params": {"L": 130, "N": 4}, "features": [{"name": "Base", "kind": "feature"}, {"name": "Holes", "kind": "feature", "suppressed": True},
                                                                  {"name": "Slot", "kind": "manual"}],
                      "fingerprint": {"volume": 1100.0, "bbox": [10, 10, 11]}, "material": "Steel 1045", "ok": True},
           "manual": [{"id": "a", "op": "sketch", "name": "Slot"}]}
    d = change_notice.diff(base, cur)
    assert d["lines"][0] == "L: 120 → 130"
    assert "Added: Slot" in d["lines"] and "Suppressed: Holes" in d["lines"]
    assert "Volume +100.0 mm³ (+10.00 %)" in d["lines"]
    assert "Mass +0.8 g (now 8.6 g)" in d["lines"]  # 100 mm³ × 7.85 g/cm³
    assert "Envelope 10 × 10 × 10 → 10 × 10 × 11 mm" in d["lines"]
    assert change_notice.diff(base, base)["lines"] == ["No change to parameters, features or geometry (rebuild only)"]


def test_change_notice_api_records_what_and_why(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "notice@x.com")
    pid, _ws = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    for length in (150, 160):
        assert c.post(f"/api/projects/{pid}/params", json={"values": {"L": length}}).status_code == 200
    revs = c.get(f"/api/projects/{pid}/revisions").json()["items"]
    n = revs[0]["n"]
    assert revs[0]["why"] == "Parameters changed: L 150 → 160" and revs[0]["kind"] == "params" and revs[0]["by"]
    r = c.get(f"/api/projects/{pid}/revisions/{n}/notice")
    assert r.status_code == 200, r.text
    nt = r.json()
    assert nt["base"] == n - 1 and nt["latest"] and nt["superseded_by"] is None
    assert nt["why"] == "Parameters changed: L 150 → 160"
    ch = nt["changes"]
    assert ch["params"] == [{"name": "L", "from": 150, "to": 160}]
    dv = 10 * 80 * 10 - 10 * 1.0 ** 2  # length +10 mm; the top chamfer ring grows by 10 mm × CH²
    assert ch["geometry"]["volume"]["delta"] == pytest.approx(dv, rel=1e-6)
    assert ch["geometry"]["mass_g"]["delta"] == pytest.approx(dv * 2.70 / 1000, rel=1e-6)
    assert "Envelope 150 × 80 × 10 → 160 × 80 × 10 mm" in ch["lines"]
    # the earlier revision is superseded
    old = c.get(f"/api/projects/{pid}/revisions/{n - 1}/notice").json()
    assert old["superseded_by"] == n and not old["latest"]
    # a no-AI suppress records its own cause
    assert c.post(f"/api/projects/{pid}/design-features/suppress", json={"name": "Mounting holes (4x)", "suppressed": True}).status_code == 200
    top = c.get(f"/api/projects/{pid}/revisions").json()["items"][0]
    nt = c.get(f"/api/projects/{pid}/revisions/{top['n']}/notice").json()
    assert nt["why"] == "Suppressed “Mounting holes (4x)” (no AI)"
    assert "Suppressed: Mounting holes (4x)" in nt["changes"]["lines"]
    assert nt["changes"]["geometry"]["volume"]["delta"] == pytest.approx(4 * math.pi * 3.3 ** 2 * 10, rel=1e-6)
    assert c.get(f"/api/projects/{pid}/revisions/999/notice").status_code == 404
