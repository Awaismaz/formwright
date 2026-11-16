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
