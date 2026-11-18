"""EVAL-008: same-prompt repeatability harness, driven by fakes and replays only (zero model calls).

Expected statistics are hand sums over the replayed scripts: a plate 80 x 50 x T has volume 4000*T mm^3."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest
from test_ai_quality import PLATE

from aicad.eval import repeat
from aicad.eval.benchmark import synthetic_cassette


def test_fake_series_of_five_is_repeatable(tmp_path: Path) -> None:
    out = tmp_path / "fake"
    assert repeat.main(["--case", "P01", "--out", str(out)]) == 0  # default: fake mode, 5 runs
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    s = rep["summary"]
    assert s["mode"] == "fake" and s["runs"] == 5 and len(rep["runs"]) == 5
    assert s["verdict"].startswith("repeatable") and s["identical_to_modal"] == 1.0 and s["distinct_geometries"] == 1
    assert s["gates_pass_rate"] == 1.0 and s["expect_pass_rate"] == 1.0
    assert s["metrics"]["volume"]["stdev"] == 0 and s["metrics"]["volume"]["distinct"] == 1
    assert all(v == 1.0 for v in s["check_pass_rate"].values()) and "CHK-08" in s["check_pass_rate"]
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "Repeatability (fake): P01 x 5" in md and "validates the harness, not the agent" in md


def test_replayed_series_reports_variance(tmp_path: Path) -> None:
    cas = tmp_path / "cassettes"
    cas.mkdir()
    thick = [6, 6, 8, 6, None]  # None: a run whose script fails to build
    for i, t in enumerate(thick, 1):
        script = PLATE.replace("THICK = 6", f"THICK = {t}") if t else PLATE.replace("result = Box", "result = Bx")
        (cas / f"run-{i:02d}.json").write_text(json.dumps(synthetic_cassette({"reference": script})))
    out = tmp_path / "rep"
    assert repeat.main(["--prompt", "plate 80 x 50", "--replay", str(cas), "--out", str(out)]) == 0
    s = json.loads((out / "report.json").read_text(encoding="utf-8"))["summary"]
    vols = [80 * 50 * t for t in thick if t]
    assert s["built_rate"] == 0.8 and s["gates_pass_rate"] == 0.8
    assert s["distinct_geometries"] == 2 and s["identical_to_modal"] == 0.6
    v = s["metrics"]["volume"]
    assert v["n"] == 4 and v["mean"] == pytest.approx(statistics.fmean(vols))
    assert v["stdev"] == pytest.approx(statistics.stdev(vols)) and v["stdev"] == pytest.approx(4000.0)
    assert v["spread"] == pytest.approx(8000.0) and v["distinct"] == 2
    assert s["metrics"]["bbox_x"]["distinct"] == 1 and s["metrics"]["bbox_z"]["distinct"] == 2
    assert s["verdict"].startswith("varies") and "volume" in s["varying"] and "bbox_x" not in s["varying"]
    assert s["check_pass_rate"]["CHK-05"] == 0.8


def test_metric_extraction_and_identity_key() -> None:
    st = {"ok": True, "fingerprint": {"volume": 24000.0000001, "bbox": [80, 50, 6], "faces": 6, "edges": 12,
                                       "solids": 1}, "checks": [{"id": "CHK-04", "passed": True}], "features": [{}]}
    m = repeat.run_metrics(st, {"faces": []})
    assert m["built"] and m["gates_ok"] and m["features"] == 1 and m["checks"] == {"CHK-04": True}
    st2 = json.loads(json.dumps(st))
    st2["fingerprint"]["volume"] = 24000.0
    assert repeat.geometry_key(m) == repeat.geometry_key(repeat.run_metrics(st2, {}))  # round-off only
    st2["fingerprint"]["volume"] = 24010.0
    assert repeat.geometry_key(m) != repeat.geometry_key(repeat.run_metrics(st2, {}))
    assert repeat.run_metrics({"error": "boom"}, None)["built"] is False
    assert repeat.geometry_key(repeat.run_metrics(None, None)) is None


def test_live_never_starts_unconfirmed_and_bad_args(tmp_path: Path) -> None:
    out = str(tmp_path / "x")
    assert repeat.main(["--case", "P01", "--live", "--out", out]) == 2  # stdin is not a TTY in tests: refused
    assert repeat.main(["--prompt", "a part", "--out", out]) == 2  # fake needs a reference
    assert repeat.main(["--case", "ZZZ", "--out", out]) == 2
    assert repeat.main(["--case", "P01", "--runs", "0", "--out", out]) == 2
    assert repeat.main(["--case", "P01", "--record", out, "--out", out]) == 2
    assert "5 live runs" in repeat.estimate(5)
    assert not (tmp_path / "x" / "report.json").exists()


def test_cli_entry_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    from aicad import cli

    seen: list[list[str]] = []
    monkeypatch.setattr(repeat, "main", lambda argv: seen.append(argv) or 0)
    assert cli.main(["repeat", "--case", "P01"]) == 0 and seen == [["--case", "P01"]]
