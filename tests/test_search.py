"""Find similar parts / parts by size (deterministic shape signatures)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_platform import _project_with_model, app_client, signup  # noqa: F401  (fixture re-export)

from aicad import similarity

DEMO = Path(__file__).resolve().parents[1] / "src" / "aicad" / "demo"


def _sig(dims: list[float], fill: float = 0.9, cyl: dict[str, int] | None = None, mat: str = "Steel") -> dict:
    return {"dims": sorted(dims, reverse=True), "volume": dims[0] * dims[1] * dims[2] * fill, "fill": fill,
            "mix": {"plane": 0.8, "cylinder": 0.2, "cone": 0.0, "other": 0.0}, "cyl": cyl or {}, "material": mat,
            "features": ["Base plate"]}


def test_parse_size_queries() -> None:
    assert similarity.parse_size_query("120x80x10") == [120, 80, 10]
    assert similarity.parse_size_query("plate 120 × 80 mm") == [120, 80]
    assert similarity.parse_size_query("80*120") == [120, 80]
    assert similarity.parse_size_query("Ø50 x 200") == [200, 50, 50]
    assert similarity.parse_size_query("bracket") is None


def test_compare_scores_and_reasons() -> None:
    a = _sig([120, 80, 10], cyl={"6.60": 4})
    same = similarity.compare(a, _sig([10, 120, 80], cyl={"6.60": 4}))  # same part, other orientation
    assert same["score"] == pytest.approx(100, abs=0.01)
    assert same["reasons"][0].startswith("Same envelope 120 × 80 × 10") and "Same diameters: 4 × Ø6.6" in same["reasons"]
    scaled = similarity.compare(a, _sig([240, 160, 20], cyl={"6.60": 4}))
    assert "Same shape, scaled ×2.00" in scaled["reasons"][0] and scaled["shape"] == pytest.approx(1)
    assert scaled["score"] < same["score"]
    other = similarity.compare(a, _sig([30, 30, 200], fill=0.6))
    assert other["score"] < scaled["score"] < same["score"]
    m = similarity.size_match([120, 80], _sig([120, 80, 10]))
    assert m["score"] == pytest.approx(100) and "(exact)" in m["reasons"][0]


def test_similar_parts_api(app_client: TestClient) -> None:  # noqa: F811
    c = app_client
    signup(c, "similar@x.com")
    plate = (DEMO / "mounting_plate.py").read_text(encoding="utf-8")
    a, _ = _project_with_model(c, plate)
    b, _ = _project_with_model(c, plate)
    big, _ = _project_with_model(c, plate.replace("L = 120.0", "L = 180.0").replace("W = 80.0", "W = 120.0")
                                 .replace("T = 10.0", "T = 15.0"))
    bracket, _ = _project_with_model(c, (DEMO / "l_bracket.py").read_text(encoding="utf-8"))
    r = c.get(f"/api/search/similar/{a}")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    ids = [i["project"]["id"] for i in items]
    assert ids[0] == b and items[0]["score"] == pytest.approx(100, abs=0.01)
    assert items[0]["reasons"][0].startswith("Same envelope 120 × 80 × 10")
    assert big in ids and ids.index(big) > 0
    assert next(i for i in items if i["project"]["id"] == big)["reasons"][0].startswith("Same shape, scaled ×1.5")
    assert bracket not in ids[:2]
    r = c.get("/api/search/size", params={"q": "120x80x10"})
    found = [i["project"]["id"] for i in r.json()["items"]]
    assert set(found[:2]) == {a, b} and r.json()["dims"] == [120, 80, 10]
    assert c.get("/api/search/size", params={"q": "nothing here"}).json()["items"] == []
