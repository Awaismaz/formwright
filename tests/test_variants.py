"""Design variants: named pinned revisions compared side by side; switching restores without AI."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_platform import _project_with_model, app_client, signup  # noqa: F401  (fixture re-export)

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"


def test_variants_lifecycle(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "variants@x.com")
    pid, _ws = _project_with_model(c, (DEMO / "mounting_plate.py").read_text(encoding="utf-8"))
    url = f"/api/projects/{pid}/variants"
    assert c.post(url, json={"name": "Nothing yet"}).status_code == 409  # no revision of the current design yet
    assert c.post(f"/api/projects/{pid}/params", json={"values": {"L": 130}}).status_code == 200
    short = c.post(url, json={"name": "Short plate", "note": "fits the 140 mm bay"})
    assert short.status_code == 200, short.text
    assert c.post(url, json={"name": "short PLATE"}).status_code == 409  # names are unique, case-insensitive
    assert c.post(url, json={"name": "Again"}).status_code == 409  # this revision is already a variant
    assert c.post(f"/api/projects/{pid}/params", json={"values": {"L": 160}}).status_code == 200
    assert c.post(url, json={"name": "Long plate"}).status_code == 200
    lst = c.get(url).json()
    by = {i["name"]: i for i in lst["items"]}
    assert by["Long plate"]["current"] and not by["Short plate"]["current"] and lst["current_is_variant"]
    assert by["Short plate"]["params"]["L"] == 130 and by["Long plate"]["params"]["L"] == 160
    dv = by["Long plate"]["volume"] - by["Short plate"]["volume"]
    assert dv == pytest.approx(30 * 80 * 10 - 30 * 1.0, rel=1e-6)  # +30 mm length, top chamfer ring +30·CH²
    assert by["Long plate"]["mass_g"] - by["Short plate"]["mass_g"] == pytest.approx(dv * 2.70 / 1000, rel=1e-6)
    # switching = restoring the variant's revision (no AI); it becomes current
    assert c.post(f"/api/projects/{pid}/revisions/{by['Short plate']['rev']}/restore").status_code == 200
    by = {i["name"]: i for i in c.get(url).json()["items"]}
    assert by["Short plate"]["current"] and not by["Long plate"]["current"]
    vid = by["Long plate"]["id"]
    assert c.patch(f"{url}/{vid}", json={"name": "Long plate (8 holes)"}).json()["name"] == "Long plate (8 holes)"
    assert c.delete(f"{url}/{vid}").status_code == 200
    assert [i["name"] for i in c.get(url).json()["items"]] == ["Short plate"]
