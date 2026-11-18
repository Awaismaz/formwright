"""LEG-002: dependency licence audit + SBOM (scripts/sbom.py), offline. No new copyleft/AGPL dependency without an
allow-list entry; the committed SBOM matches the lockfiles."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def sbom() -> ModuleType:
    spec = importlib.util.spec_from_file_location("fw_sbom", ROOT / "scripts" / "sbom.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def data(sbom: ModuleType) -> dict[str, Any]:
    return sbom.collect()


def test_classification(sbom: ModuleType) -> None:
    c = sbom.classify
    assert c("MIT") == c("Apache-2.0 OR BSD-3-Clause") == c("BSD-3-Clause AND 0BSD AND MIT") == "permissive"
    assert c("AGPL-3.0-only") == c("SSPL-1.0") == "network-copyleft"
    assert c("GPL-3.0-or-later") == "strong-copyleft" and c("MIT OR GPL-3.0-only") == "permissive"  # choose MIT
    assert c("LGPL-2.1-only WITH OCCT-exception-1.0") == c("MPL-2.0") == c("MIT AND LGPL-2.1-only") == "weak-copyleft"
    assert c("FreeImage OR GPL-2.0-only OR GPL-3.0-only") == "weak-copyleft"
    assert c("LicenseRef-Anthropic-Commercial-Terms") == "proprietary"
    assert c("") == c("NOASSERTION") == "unknown"


def test_current_dependencies_pass_the_audit(sbom: ModuleType, data: dict[str, Any]) -> None:
    allow = sbom.load_allowlist()
    assert sbom.audit(data["python"] + data["web"], allow) == []
    assert sbom.main(["--check"]) == 0
    # the kernel is flagged through its bundled OCCT even though the wheel metadata says Apache-2.0
    ocp = next(x for x in data["python"] if x["name"] == "cadquery-ocp-novtk")
    assert ocp["class"] == "permissive" and ocp["effective_class"] == "weak-copyleft"
    assert any("OCCT" in b["name"] for b in ocp["bundled"])
    every = data["python"] + data["web"]
    assert not [x["name"] for x in every if x["effective_class"] in ("network-copyleft", "strong-copyleft")]
    assert not [x["name"] for x in every if x["effective_class"] == "unknown"]


def test_new_agpl_dependency_needs_an_allowlist_entry(sbom: ModuleType, data: dict[str, Any]) -> None:
    allow = sbom.load_allowlist()
    bad = {"ecosystem": "pypi", "name": "some-agpl-lib", "version": "1.0", "scope": "runtime",
           "license": "AGPL-3.0-or-later", "license_source": "test", "class": "network-copyleft", "bundled": []}
    problems = sbom.audit(data["python"] + [bad], allow)
    assert [p["name"] for p in problems] == ["some-agpl-lib"] and problems[0]["effective_class"] == "network-copyleft"
    ok = dict(allow, **{"pypi:some-agpl-lib": {"max_class": "network-copyleft"}})
    assert sbom.audit([bad], ok) == []
    # an allow-listed weak-copyleft package that turns AGPL in a later release is caught again
    worse = {**next(x for x in data["python"] if x["name"] == "certifi"), "license": "AGPL-3.0-only",
             "class": "network-copyleft"}
    assert sbom.audit([worse], allow)[0]["problem"].startswith("class network-copyleft exceeds")
    # an npm package with no licence at all is flagged as unknown
    unknown = {"ecosystem": "npm", "name": "mystery", "version": "0.1.0", "scope": "runtime", "license": "NOASSERTION",
               "license_source": "test", "class": "unknown", "bundled": []}
    assert sbom.audit([unknown], allow)[0]["problem"] == "not in the allow-list"


def test_committed_sbom_matches_lockfiles_and_is_cyclonedx(sbom: ModuleType, data: dict[str, Any]) -> None:
    for fname, comps in (("sbom-python.cdx.json", data["python"]), ("sbom-web.cdx.json", data["web"])):
        doc = json.loads((ROOT / "docs" / "legal" / fname).read_text(encoding="utf-8"))
        assert doc["bomFormat"] == "CycloneDX" and doc["specVersion"] == "1.5"
        assert doc["serialNumber"].startswith("urn:uuid:") and "timestamp" not in doc["metadata"]
        committed = sorted((c["name"], c["version"]) for c in doc["components"])
        assert committed == sorted((c["name"], c["version"]) for c in comps), \
            f"{fname} is stale: run `uv run python scripts/sbom.py`"
        assert all(c["purl"].startswith(("pkg:pypi/", "pkg:npm/")) for c in doc["components"])
        assert sbom.cyclonedx(comps, "x", "1") == sbom.cyclonedx(comps, "x", "1")  # reproducible bytes
    runtime = {c["name"] for c in data["python"] if c["scope"] == "runtime"}
    assert {"build123d", "fastapi", "claude-agent-sdk", "cadquery-ocp-novtk"} <= runtime
    assert {"pytest", "ruff"} <= {c["name"] for c in data["python"] if c["scope"] == "dev"}
    assert "httpx2-jsfetch" not in {c["name"] for c in data["python"]}  # emscripten-only: never installed
