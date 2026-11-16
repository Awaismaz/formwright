"""Agent plumbing tests. No model calls: CI must never consume subscription or API usage."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aicad.agent.runner import ScriptRejected, tripwire
from aicad.agent.session import AgentSession, make_guard
from aicad.studio.app import create_app

GOOD = """
from build123d import *
NAME = "t"
result = Box(20, 10, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))
result -= Pos(0, 0, 2.5) * Cylinder(2, 7)
EXPECTED = {"bbox": [20, 10, 5], "volume": 20*10*5 - 3.141592653589793*4*5, "solids": 1}
"""


def _run_runner(tmp_path: Path, src: str) -> dict[str, Any]:
    script = tmp_path / "model.py"
    script.write_text(src)
    out = tmp_path / "out"
    subprocess.run([sys.executable, "-I", "-m", "aicad.agent.runner", str(script), str(out)],
                   cwd=tmp_path, timeout=180, check=False)
    return json.loads((out / "status.json").read_text())


def test_runner_builds_and_checks(tmp_path: Path) -> None:
    s = _run_runner(tmp_path, GOOD)
    assert s["ok"], s
    assert {c["id"] for c in s["checks"]} >= {"CHK-02", "CHK-03", "CHK-04", "CHK-05", "CHK-07", "CHK-08"}
    for f in ("part.step", "part.stl", "model.glb"):
        assert (tmp_path / "out" / f).stat().st_size > 0


def test_runner_catches_wrong_expectation(tmp_path: Path) -> None:
    s = _run_runner(tmp_path, GOOD.replace('"bbox": [20, 10, 5]', '"bbox": [20, 10, 6]'))
    assert not s["ok"]
    assert next(c for c in s["checks"] if c["id"] == "CHK-04")["passed"] is False


def test_runner_reports_script_errors(tmp_path: Path) -> None:
    s = _run_runner(tmp_path, "from build123d import *\nresult = Box(1, 1)\n")
    assert not s["ok"] and "TypeError" in s["error"]


def test_runner_requires_result(tmp_path: Path) -> None:
    s = _run_runner(tmp_path, "from build123d import *\nx = Box(1, 1, 1)\n")
    assert "result" in s["error"]


@pytest.mark.parametrize("src", [
    "import os\n", "import subprocess as sp\n", "from shutil import rmtree\n",
    "open('x')\n", "__import__('os')\n", "eval('1')\n", "from urllib.request import urlopen\n",
])
def test_tripwire_rejects(src: str) -> None:
    with pytest.raises(ScriptRejected):
        tripwire(src)


def test_tripwire_allows_geometry() -> None:
    tripwire(GOOD + "import math\nfrom build123d import Box\n")


def _guard(root: Path, tool: str, ti: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(make_guard(root)({"tool_name": tool, "tool_input": ti}, None, None))


@pytest.mark.parametrize("tool,ti,denied", [
    ("Read", {"file_path": "model.py"}, False),
    ("Write", {"file_path": "sub/part.py"}, False),
    ("Read", {"file_path": "../secret.txt"}, True),
    ("Read", {"file_path": "C:/Windows/win.ini"}, True),
    ("Edit", {"file_path": "../../x.py"}, True),
    ("Glob", {"pattern": "**/*.py"}, False),
    ("Glob", {"pattern": "../**/*"}, True),
    ("Grep", {"pattern": "x", "path": ".."}, True),
    ("WebFetch", {"url": "https://build123d.readthedocs.io/en/latest/"}, False),
    ("WebFetch", {"url": "https://example.com/"}, True),
])
def test_path_and_web_guard(tmp_path: Path, tool: str, ti: dict[str, Any], denied: bool) -> None:
    r = _guard(tmp_path, tool, ti)
    assert bool(r) is denied, r


class FakeSession(AgentSession):
    async def send(self, prompt: str) -> None:  # no model call
        self.publish({"type": "user", "text": prompt})
        self.publish({"type": "text", "text": "ok"})


def test_app_endpoints(tmp_path: Path) -> None:
    s = FakeSession(tmp_path / "ws")
    s.out_dir.mkdir(parents=True)
    (s.out_dir / "status.json").write_text('{"ok": true}')
    (s.workspace / "model.py").write_text("secret")
    c = TestClient(create_app(s))
    assert c.get("/api/state").json()["agent"] is True
    assert c.get("/files/status.json").json() == {"ok": True}
    for bad in ("/files/model.py", "/files/..%2Fmodel.py", "/files/secret"):
        assert c.get(bad).status_code == 404
    assert c.post("/api/chat", json={"prompt": "  "}).status_code == 400
    s.busy = True
    assert c.post("/api/chat", json={"prompt": "hi"}).status_code == 409
    s.busy = False
    assert c.post("/api/chat", json={"prompt": "hi"}).status_code == 200
    assert "Design agent" in c.get("/").text


def test_editable_params_only_declared_plain_literals() -> None:
    from aicad.agent.runner import editable_params

    src = (
        "MODULE = 3\nTEETH = 40\nFLANK_PTS = 16\nN = 4000\ntooth_int = 0.0\n"
        "OFFSET = -2.5\nDERIVED = MODULE * TEETH\nLOOPED = 1\nLOOPED += 1\n"
        "for i in range(3):\n    tooth_int += i\n"
    )
    declared = {"MODULE": 3, "TEETH": 40, "DERIVED": 120, "LOOPED": 2, "OFFSET": -2.5, "MISSING": 1}
    ed = editable_params(src, declared)
    assert ed == {"MODULE": 3, "TEETH": 40, "OFFSET": -2.5}  # N, FLANK_PTS, tooth_int not declared
    assert isinstance(ed["TEETH"], int)


def test_runner_reports_editable_params_and_skips_determinism(tmp_path: Path) -> None:
    src = GOOD.replace('NAME = "t"', 'NAME = "t"\nL = 20.0\nPARAMS = dict(L=L)\nn_samples = 50')
    s = _run_runner(tmp_path, src)
    assert s["editable_params"] == {"L": 20.0}
    script = tmp_path / "model.py"
    subprocess.run([sys.executable, "-I", "-m", "aicad.agent.runner", str(script), str(tmp_path / "out2"),
                    "--no-determinism"], cwd=tmp_path, timeout=180, check=False)
    s2 = json.loads((tmp_path / "out2" / "status.json").read_text())
    chk8 = next(c for c in s2["checks"] if c["id"] == "CHK-08")
    assert s2["ok"] and chk8["gating"] is False and "skipped" in chk8["name"]


def test_warm_worker_builds_renders_and_recovers(tmp_path: Path) -> None:
    from aicad.agent import worker

    script = tmp_path / "model.py"
    script.write_text(GOOD)

    async def go() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        try:
            r1 = await worker.build("t", script, tmp_path / "o1")
            r2 = await worker.build("t", script, tmp_path / "o2", determinism=False)
            rr = await worker.render("t", tmp_path / "o2" / "part.stl", tmp_path / "v.png", "t")
            script.write_text("from build123d import *\nprint('noise to stdout')\nresult = Box(1, 2, 3)\n")
            r3 = await worker.build("t", script, tmp_path / "o3")
            return r1, r2, rr, r3
        finally:
            await worker.shutdown_all()

    r1, r2, rr, r3 = asyncio.run(go())
    assert r1["rc"] == 0 and r2["rc"] == 0 and rr["ok"] and (tmp_path / "v.png").stat().st_size > 1000
    assert r2["elapsed_s"] < r1["elapsed_s"]  # warm + no determinism rebuild
    assert r3["ok"] and json.loads((tmp_path / "o3" / "status.json").read_text())["fingerprint"]["volume"] == 6.0


def test_stl_export_deviation_is_absolute(tmp_path: Path) -> None:
    """part.stl must stay within 0.01 mm of the exact surface on large parts too (build123d's tolerance is relative)."""
    import struct

    from build123d import Cylinder

    from aicad.agent.runner import export_stl_abs

    r = 100.0
    p = tmp_path / "c.stl"
    assert export_stl_abs(Cylinder(r, 20), p)
    data = p.read_bytes()
    n = struct.unpack("<I", data[80:84])[0]
    worst = 0.0
    for i in range(n):
        if abs(struct.unpack("<3f", data[84 + 50 * i:84 + 50 * i + 12])[2]) > 0.1:
            continue  # end caps: their chords cross the disc; only the side wall approximates the cylinder
        v = struct.unpack("<9f", data[84 + 50 * i + 12:84 + 50 * i + 48])
        pts = [v[0:3], v[3:6], v[6:9]]
        for a, b in ((0, 1), (1, 2), (2, 0)):  # edge midpoints on the side wall sag inward by the chordal deviation
            mx, my = (pts[a][0] + pts[b][0]) / 2, (pts[a][1] + pts[b][1]) / 2
            rho = (mx * mx + my * my) ** 0.5
            if rho > r * 0.5:
                worst = max(worst, r - rho)
    assert 0 < worst <= 0.0101, worst  # float32 STL coordinates
