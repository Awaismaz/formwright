"""EVAL-006 advisory render similarity: hand-checkable synthetic images, then the benchmark / repeat / run-record
logging (zero model calls; the replays render with the same offscreen VTK review sheet a live build uses)."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from aicad.eval import render_similarity as rs

BG, FG = 240, 180  # grey levels: background and part
N = 256            # the working size, so no resampling happens and the IoUs below are exact


def square(x0: int, y0: int, s: int, n: int = N) -> np.ndarray:
    a = np.full((n, n), BG, dtype=np.uint8)
    a[y0:y0 + s, x0:x0 + s] = FG
    return a


def disc(cx: float, cy: float, r: float, n: int = N) -> np.ndarray:
    a = np.full((n, n), BG, dtype=np.uint8)
    yy, xx = np.mgrid[:n, :n]
    a[(xx + 0.5 - cx) ** 2 + (yy + 0.5 - cy) ** 2 <= r * r] = FG
    return a


def test_identical_images_score_one() -> None:
    ref = square(80, 80, 80)
    r = rs.compare(ref, ref.copy())
    assert r["score"] == 1.0 and r["silhouette_ssim"] == 1.0 and r["edge_iou"] == 1.0 and r["silhouette_iou"] == 1.0
    assert r["advisory"] is True and r["gating"] is False and r["size_px"] == [N, N]


def test_shift_scale_and_shape_score_lower_with_hand_ious() -> None:
    ref = square(80, 80, 80)
    s10 = rs.compare(ref, square(90, 80, 80))
    s40 = rs.compare(ref, square(120, 80, 80))
    big = rs.compare(ref, square(70, 70, 100))
    circ = rs.compare(ref, disc(120, 120, 40))
    # silhouette IoU by hand: shift 10 -> overlap 70x80 over union 2*6400-5600; shift 40 -> 40x80 / (12800-3200);
    # 100-square containing the 80-square -> 6400 / 10000; inscribed circle -> pi/4
    assert s10["silhouette_iou"] == pytest.approx(5600 / 7200, abs=1e-4)
    assert s40["silhouette_iou"] == pytest.approx(3200 / 9600, abs=1e-4)
    assert big["silhouette_iou"] == pytest.approx(0.64, abs=1e-4)
    assert circ["silhouette_iou"] == pytest.approx(math.pi / 4, abs=0.01)
    for r in (s10, s40, big, circ):
        assert r["score"] < 0.9 and r["edge_iou"] < 0.5
    assert s40["score"] < s10["score"] < 1.0
    assert s40["silhouette_ssim"] < s10["silhouette_ssim"] < 1.0


def test_one_pixel_shift_is_tolerated_and_empty_images() -> None:
    ref = square(80, 80, 80)
    r = rs.compare(ref, square(81, 80, 80))
    assert r["edge_iou"] > 0.6 and r["score"] > 0.8  # edges dilated by 1 px on both sides
    blank = np.full((N, N), BG, dtype=np.uint8)
    assert rs.compare(blank, blank)["score"] == 1.0
    e = rs.compare(ref, blank)
    assert e["silhouette_ssim"] == 0 and e["silhouette_iou"] == 0 and e["score"] <= 0.5


def test_alpha_silhouette_and_resampling() -> None:
    rgba = np.zeros((N, N, 4), dtype=np.uint8)
    rgba[80:160, 80:160] = [200, 200, 220, 255]  # opaque part on a transparent background
    a = Image.fromarray(rgba)
    assert rs.compare(a, a)["score"] == 1.0
    moved = np.roll(rgba, 10, axis=1)
    assert rs.compare(a, Image.fromarray(moved))["silhouette_iou"] == pytest.approx(5600 / 7200, abs=1e-4)
    # a 512 px copy of the same picture resamples to the same 256 px working image
    big = Image.fromarray(square(80, 80, 80)).resize((512, 512), Image.Resampling.NEAREST)
    assert rs.compare(square(80, 80, 80), big)["silhouette_iou"] == pytest.approx(1.0, abs=1e-3)


def _sheet(tiles: list[np.ndarray]) -> np.ndarray:
    return np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])


def test_review_sheet_compared_view_by_view_with_labels_masked() -> None:
    tiles = [square(80, 80, 80), disc(128, 128, 50), square(60, 100, 120), disc(100, 140, 30)]
    ref = _sheet(tiles)
    assert rs.compare_sheets(ref, ref.copy())["score"] == 1.0
    labelled = ref.copy()
    labelled[N - 12:N - 4, 8:60] = 20  # text in the bottom-left label strip of the ISO view
    assert rs.compare_sheets(ref, labelled)["score"] == 1.0
    other = _sheet([tiles[0], tiles[1], square(90, 100, 120), tiles[3]])  # TOP view changed
    r = rs.compare_sheets(ref, other)
    assert r["worst_view"] == 2 and r["views"][0]["score"] == 1.0 and r["views"][2]["score"] < 0.9
    assert r["score"] == pytest.approx(np.mean([v["score"] for v in r["views"]]), abs=1e-4)
    assert r["advisory"] is True and r["gating"] is False


def test_compare_files_never_raises(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    Image.fromarray(square(80, 80, 80)).save(a)
    assert rs.compare_files(a, tmp_path / "missing.png") is None
    (tmp_path / "bad.png").write_bytes(b"not a png")
    assert rs.compare_files(a, tmp_path / "bad.png") is None
    assert rs.compare_files(a, a)["score"] == 1.0
    assert rs.summary([]) == {"n": 0, "advisory": True}
    assert rs.summary([1.0, 0.5])["mean"] == 0.75


# ------------------------------------------------------------------ logging in the reports
def test_benchmark_logs_render_similarity_but_never_gates(tmp_path: Path) -> None:
    from aicad.eval import benchmark

    refs = tmp_path / "refs"
    out1 = tmp_path / "r1"
    assert benchmark.main(["--dry", "--only", "P02,B02", "--out", str(out1), "--save-renders", str(refs)]) == 0
    assert (refs / "P02.png").is_file() and (refs / "B02.png").is_file()
    shutil.copyfile(refs / "P02.png", refs / "B02.png")  # B02's reference now shows a different part
    out2 = tmp_path / "r2"
    assert benchmark.main(["--dry", "--only", "P02,B02", "--out", str(out2), "--ref-renders", str(refs)]) == 0
    rep = json.loads((out2 / "report.json").read_text(encoding="utf-8"))
    rows = {r["id"]: r for r in rep["rows"]}
    assert rows["P02"]["render_similarity"]["score"] == 1.0  # deterministic render of the same part
    assert rows["B02"]["render_similarity"]["score"] < 0.95
    assert rows["B02"]["passed"] and rep["summary"]["pass_rate"] == 1.0  # advisory: the verdict is unchanged
    s = rep["summary"]["render_similarity"]
    assert s["n"] == 2 and s["advisory"] is True and s["min"] == rows["B02"]["render_similarity"]["score"]
    md = (out2 / "report.md").read_text(encoding="utf-8")
    assert "Render similarity (advisory, never gating)" in md and "| P02 | plate | yes |" in md


def test_repeat_logs_render_similarity_to_first_run(tmp_path: Path) -> None:
    from aicad.eval import repeat

    out = tmp_path / "rep"
    assert repeat.main(["--case", "P01", "--runs", "2", "--render", "--out", str(out)]) == 0
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert [r["render"] for r in rep["runs"]] == ["run-01.png", "run-02.png"]
    assert all(r["render_similarity"]["score"] == 1.0 for r in rep["runs"])
    s = rep["summary"]
    assert s["render_similarity"]["mean"] == 1.0 and s["render_similarity"]["reference"] == "run-01.png"
    assert s["verdict"].startswith("repeatable")
    assert "(advisory, never gating)" in (out / "report.md").read_text(encoding="utf-8")


def test_run_record_logs_render_similarity_to_the_previous_render(tmp_path: Path) -> None:
    from aicad.agent.runrecord import RunRecorder

    out = tmp_path / "out"
    out.mkdir()
    sheet = _sheet([square(80, 80, 80)] * 4)
    Image.fromarray(sheet).save(out / "views.png")
    rec = RunRecorder(tmp_path, prompt="make it longer", mode="build", requested_model=None)
    Image.fromarray(_sheet([square(80, 80, 120)] + [square(80, 80, 80)] * 3)).save(out / "views.png")
    r = rec.finish()["render_similarity"]
    assert r["available"] and not r["unchanged"] and r["advisory"] is True and r["gating"] is False
    assert r["worst_view"] == 0 and r["score"] < 1.0
    assert rec.rec["outcome"]["status"] == "stopped"  # the render score never touches the outcome

    same = RunRecorder(tmp_path, prompt="no change", mode="build", requested_model=None)
    assert same.finish()["render_similarity"] == {"advisory": True, "gating": False,
                                                  "basis": "review render before this turn", "available": True,
                                                  "unchanged": True, "score": 1.0}
    (out / "views.png").unlink()
    first = RunRecorder(tmp_path, prompt="new part", mode="build", requested_model=None)
    Image.fromarray(sheet).save(out / "views.png")
    assert first.finish()["render_similarity"]["reason"] == "no earlier render to compare with"
