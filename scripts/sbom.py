"""LEG-002: dependency licence audit + SBOM (CycloneDX 1.5 JSON), fully offline.

Inputs (nothing is downloaded):
  Python  ``uv.lock`` for the exact dependency set (runtime = closure of the ``aicad`` package's dependencies, dev =
          the ``dev`` group's closure minus runtime) and the *installed* package metadata (``importlib.metadata``:
          PEP 639 License-Expression, else the License field, else the trove classifiers) for licences.
  npm     ``web/package-lock.json`` (lockfile v2/v3 records each package's licence) and, when present,
          ``web/node_modules/<pkg>/package.json``.
Licences missing from metadata come from ``OVERRIDES`` below (each with its source). Native libraries bundled inside
wheels, which metadata does not describe, are listed in ``BUNDLED``.

Outputs (``--out``, default ``docs/legal``): ``sbom-python.cdx.json``, ``sbom-web.cdx.json``, ``licenses.json``
(the classified audit). ``docs/legal/LICENSES.md`` is written by hand from ``licenses.json`` and the allow-list.

Copyleft policy: every component whose licence is weak copyleft (LGPL, MPL, EPL, CDDL), strong copyleft (GPL) or
network copyleft (AGPL, SSPL), or whose licence is unknown, must have an entry in ``docs/legal/license-allowlist.json``
explaining how it is used. ``--check`` exits 1 when one does not (``tests/test_sbom.py`` runs it).

    uv run python scripts/sbom.py            # regenerate docs/legal/*
    uv run python scripts/sbom.py --check    # audit only, no files written
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "docs" / "legal" / "license-allowlist.json"
CLASSES = ("permissive", "weak-copyleft", "strong-copyleft", "network-copyleft", "proprietary", "unknown")
FLAGGED = {"weak-copyleft", "strong-copyleft", "network-copyleft", "proprietary", "unknown"}

# Licences that metadata lacks or states as prose. Each value: (SPDX expression, where it was confirmed).
OVERRIDES: dict[tuple[str, str], tuple[str, str]] = {
    ("pypi", "ocpsvg"): ("Apache-2.0", "upstream repository LICENSE (wheel metadata empty)"),
    ("pypi", "kiwisolver"): ("BSD-3-Clause", "license file in the wheel (metadata field holds the text)"),
    ("pypi", "matplotlib"): ("PSF-2.0", "matplotlib licence agreement (PSF-based) in the wheel"),
    ("pypi", "scipy"): ("BSD-3-Clause", "LICENSE.txt in the wheel (metadata field holds the text)"),
    ("pypi", "cycler"): ("BSD-3-Clause", "LICENSE in the wheel (metadata field holds a copyright line)"),
    ("pypi", "reportlab"): ("BSD-3-Clause", "LICENSE.txt in the wheel (metadata field holds prose)"),
    ("pypi", "pypdfium2"): ("Apache-2.0 OR BSD-3-Clause", "pypdfium2 REUSE metadata (PDFium is BSD-3-Clause)"),
    ("pypi", "pywin32"): ("PSF-2.0", "pywin32 licence (PSF), Windows only"),
    ("pypi", "asttokens"): ("Apache-2.0", "metadata 'Apache 2.0'"),
    ("pypi", "pexpect"): ("ISC", "upstream LICENSE (not installed on Windows)"),
    ("pypi", "ptyprocess"): ("ISC", "upstream LICENSE (not installed on Windows)"),
    ("pypi", "py-lib3mf"): ("BSD-2-Clause", "lib3mf LICENSE (Linux aarch64 wheel of lib3mf)"),
    # npm dev tooling whose lockfile entries lack a licence field (vitest 4 family); upstream package.json
    ("npm", "vitest"): ("MIT", "upstream package.json"),
    ("npm", "@vitest/expect"): ("MIT", "upstream package.json"),
    ("npm", "@vitest/mocker"): ("MIT", "upstream package.json"),
    ("npm", "@vitest/pretty-format"): ("MIT", "upstream package.json"),
    ("npm", "@vitest/runner"): ("MIT", "upstream package.json"),
    ("npm", "@vitest/snapshot"): ("MIT", "upstream package.json"),
    ("npm", "@vitest/spy"): ("MIT", "upstream package.json"),
    ("npm", "@vitest/utils"): ("MIT", "upstream package.json"),
    ("npm", "@standard-schema/spec"): ("MIT", "upstream package.json"),
    ("npm", "@types/chai"): ("MIT", "DefinitelyTyped (MIT)"),
    ("npm", "@types/deep-eql"): ("MIT", "DefinitelyTyped (MIT)"),
    ("npm", "assertion-error"): ("MIT", "upstream package.json"),
    ("npm", "chai"): ("MIT", "upstream package.json"),
    ("npm", "es-module-lexer"): ("MIT", "upstream package.json"),
    ("npm", "estree-walker"): ("MIT", "upstream package.json"),
    ("npm", "expect-type"): ("Apache-2.0", "upstream package.json"),
    ("npm", "magic-string"): ("MIT", "upstream package.json"),
    ("npm", "obug"): ("MIT", "upstream package.json"),
    ("npm", "pathe"): ("MIT", "upstream package.json"),
    ("npm", "picomatch"): ("MIT", "upstream package.json"),
    ("npm", "siginfo"): ("ISC", "upstream package.json"),
    ("npm", "stackback"): ("MIT", "upstream package.json"),
    ("npm", "std-env"): ("MIT", "upstream package.json"),
    ("npm", "tinybench"): ("MIT", "upstream package.json"),
    ("npm", "tinyexec"): ("MIT", "upstream package.json"),
    ("npm", "tinyrainbow"): ("MIT", "upstream package.json"),
    ("npm", "why-is-node-running"): ("MIT", "upstream package.json"),
}

# Native code shipped inside a wheel that the package's own licence does not cover (as found in the installed wheels).
BUNDLED: dict[str, list[dict[str, str]]] = {
    "cadquery-ocp-novtk": [
        {"name": "Open CASCADE Technology (OCCT) 8.0", "license": "LGPL-2.1-only WITH OCCT-exception-1.0",
         "linking": "shared libraries (TK*.dll / .so), loaded by the OCP bindings"},
        {"name": "FreeImage", "license": "FreeImage OR GPL-2.0-only OR GPL-3.0-only",
         "linking": "shared library; used under the FreeImage Public Licence (FIPL, MPL-1.1 based) option"},
        {"name": "LibRaw", "license": "LGPL-2.1-only OR CDDL-1.0", "linking": "shared library (raw.dll)"},
        {"name": "FreeType", "license": "FTL OR GPL-2.0-only", "linking": "shared library; used under the FTL option"},
    ],
    "claude-agent-sdk": [
        {"name": "Claude Code CLI (bundled executable)", "license": "LicenseRef-Anthropic-Commercial-Terms",
         "linking": "separate executable started as a subprocess"},
    ],
    "numpy": [{"name": "OpenBLAS (scipy-openblas)", "license": "BSD-3-Clause", "linking": "shared library"}],
    "scipy": [{"name": "OpenBLAS (scipy-openblas)", "license": "BSD-3-Clause", "linking": "shared library"}],
}

_CLASSIFIERS = {
    "MIT License": "MIT", "BSD License": "BSD-3-Clause", "Apache Software License": "Apache-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0", "Python Software Foundation License": "PSF-2.0",
    "ISC License (ISCL)": "ISC", "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.0-or-later",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only", "GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "GNU General Public License v2 (GPLv2)": "GPL-2.0-only", "GNU Affero General Public License v3": "AGPL-3.0-only",
    "The Unlicense (Unlicense)": "Unlicense", "Zope Public License": "ZPL-2.1",
}
_PROSE = {"mit": "MIT", "mit license": "MIT", "bsd": "BSD-3-Clause", "bsd license": "BSD-3-Clause",
          "bsd 3-clause license": "BSD-3-Clause", "bsd-3-clause": "BSD-3-Clause", "apache 2.0": "Apache-2.0",
          "apache-2.0": "Apache-2.0", "apache license 2.0": "Apache-2.0", "psf": "PSF-2.0", "mpl-2.0": "MPL-2.0",
          "mit or apache-2.0": "MIT OR Apache-2.0"}


# ------------------------------------------------------------------ classification
def classify_one(lic: str) -> str:
    u = lic.upper()
    if not u or u in ("NOASSERTION", "UNKNOWN"):
        return "unknown"
    if "LICENSEREF-ANTHROPIC" in u or "PROPRIETARY" in u or "COMMERCIAL" in u:
        return "proprietary"
    if "AGPL" in u or "SSPL" in u:
        return "network-copyleft"
    if "LGPL" in u or "MPL" in u or "EPL" in u or "CDDL" in u or u.startswith(("FREEIMAGE", "OFL")):
        return "weak-copyleft"
    if "GPL" in u or "EUPL" in u or "OSL-" in u:
        return "strong-copyleft"
    return "permissive"


def classify(expr: str) -> str:
    """SPDX-ish expression: OR = the most permissive option may be chosen, AND = all apply (worst wins)."""
    expr = (expr or "").strip().strip("()")
    if not expr:
        return "unknown"
    order = {c: i for i, c in enumerate(CLASSES)}
    options = [o.strip().strip("()") for o in re.split(r"\s+OR\s+", expr)]
    best = None
    for opt in options:
        parts = [p.strip().strip("()") for p in re.split(r"\s+AND\s+", opt)]
        worst = max((classify_one(p) for p in parts), key=lambda c: order[c])
        if best is None or order[worst] < order[best]:
            best = worst
    return best or "unknown"


# Platforms Formwright runs on: Linux servers (x86-64, arm64) and Windows workstations. Dependencies whose environment
# marker matches none of them (e.g. emscripten-only) are never installed and are left out of the SBOM.
TARGETS = [
    {"sys_platform": "linux", "platform_system": "Linux", "platform_machine": "x86_64", "os_name": "posix"},
    {"sys_platform": "linux", "platform_system": "Linux", "platform_machine": "aarch64", "os_name": "posix"},
    {"sys_platform": "win32", "platform_system": "Windows", "platform_machine": "AMD64", "os_name": "nt"},
]


def marker_applies(marker: str | None) -> bool:
    if not marker:
        return True
    from packaging.markers import Marker

    base = {"python_version": "3.12", "python_full_version": "3.12.0", "implementation_name": "cpython",
            "platform_python_implementation": "CPython", "extra": ""}
    m = Marker(marker)
    return any(m.evaluate({**base, **t}) for t in TARGETS)


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# ------------------------------------------------------------------ Python
def python_license(name: str) -> tuple[str, str]:
    """(SPDX expression, source) from the installed metadata."""
    from importlib.metadata import PackageNotFoundError, distribution

    ov = OVERRIDES.get(("pypi", norm(name)))
    try:
        md = distribution(name).metadata
    except PackageNotFoundError:
        return (ov[0], "override: " + ov[1]) if ov else ("NOASSERTION", "not installed on this machine")
    if ov:
        return ov[0], "override: " + ov[1]
    if md.get("License-Expression"):
        return md["License-Expression"].strip(), "metadata License-Expression"
    lic = (md.get("License") or "").strip()
    if lic and "\n" not in lic and len(lic) <= 60 and lic.lower() in _PROSE:
        return _PROSE[lic.lower()], "metadata License"
    cls = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    mapped = [_CLASSIFIERS[c] for c in cls if c in _CLASSIFIERS]
    if mapped:
        return " OR ".join(dict.fromkeys(mapped)), "metadata classifier"
    if lic and "\n" not in lic and len(lic) <= 60:
        return lic, "metadata License (prose)"
    return "NOASSERTION", "no licence in metadata"


def python_components(lock_path: Path) -> list[dict[str, Any]]:
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    pkgs = {norm(p["name"]): p for p in lock.get("package", [])}
    root = next(p for p in lock["package"] if (p.get("source") or {}).get("editable") == "." or p["name"] == "aicad")

    def closure(start: list[dict[str, Any]]) -> set[str]:
        seen: set[str] = set()
        todo = list(start)
        while todo:
            d = todo.pop()
            n = norm(d["name"])
            p = pkgs.get(n)
            if p is None:
                continue
            extras = d.get("extra") or []
            new = n not in seen
            seen.add(n)
            deps = list(p.get("dependencies", [])) if new else []
            for ex in extras:
                deps += (p.get("optional-dependencies") or {}).get(ex, [])
            todo += [x for x in deps if marker_applies(x.get("marker"))]
        return seen

    runtime = closure([d for d in root.get("dependencies", []) if marker_applies(d.get("marker"))])
    dev = closure([d for g in (root.get("dev-dependencies") or {}).values() for d in g
                   if marker_applies(d.get("marker"))]) - runtime
    out = []
    for n in sorted(runtime | dev):
        p = pkgs[n]
        lic, src = python_license(p["name"])
        out.append({"ecosystem": "pypi", "name": p["name"], "version": p.get("version", ""),
                    "scope": "runtime" if n in runtime else "dev", "license": lic, "license_source": src,
                    "class": classify(lic), "bundled": BUNDLED.get(n, [])})
    return out


# ------------------------------------------------------------------ npm
def npm_components(lock_path: Path) -> list[dict[str, Any]]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    nm = lock_path.parent / "node_modules"
    out = []
    for path, p in sorted((lock.get("packages") or {}).items()):
        if not path:
            continue
        name = p.get("name") or path.split("node_modules/")[-1]
        lic = p.get("license")
        src = "package-lock.json"
        ov = OVERRIDES.get(("npm", name))
        if not lic and ov:  # overrides first: the SBOM must not depend on whether node_modules is installed
            lic, src = ov[0], "override: " + ov[1]
        if not lic:
            pj = nm.parent / path / "package.json"
            try:
                lic = json.loads(pj.read_text(encoding="utf-8")).get("license")
                src = "node_modules package.json"
            except (OSError, ValueError):
                lic = None
        if isinstance(lic, dict):
            lic = lic.get("type")
        lic = str(lic or "NOASSERTION")
        out.append({"ecosystem": "npm", "name": name, "version": p.get("version", ""), "path": path,
                    "scope": "dev" if p.get("dev") else "runtime", "license": lic, "license_source": src,
                    "class": classify(lic), "bundled": []})
    _ = nm
    return out


# ------------------------------------------------------------------ outputs
def purl(c: dict[str, Any]) -> str:
    if c["ecosystem"] == "pypi":
        return f"pkg:pypi/{norm(c['name'])}@{c['version']}"
    name = c["name"].replace("@", "%40", 1) if c["name"].startswith("@") else c["name"]
    return f"pkg:npm/{name}@{c['version']}"


def cyclonedx(components: list[dict[str, Any]], app: str, version: str) -> dict[str, Any]:
    """CycloneDX 1.5 JSON. No timestamp, and a serial number derived from the content, so it regenerates
    byte-identically from the same lockfile."""
    comps = []
    for c in components:
        lic = c["license"]
        entry: dict[str, Any] = {"type": "library", "name": c["name"], "version": c["version"], "purl": purl(c),
                                 "scope": "required" if c["scope"] == "runtime" else "excluded",
                                 "bom-ref": purl(c) + (f"#{c['path']}" if c.get("path") else "")}
        if lic and lic != "NOASSERTION":
            entry["licenses"] = [{"expression": lic}] if (" " in lic or "LicenseRef" in lic) else \
                [{"license": {"id": lic}}]
        props = [{"name": "formwright:license-class", "value": c["class"]},
                 {"name": "formwright:license-source", "value": c["license_source"]}]
        entry["properties"] = props
        if c["bundled"]:
            entry["components"] = [{"type": "library", "name": b["name"], "licenses": [{"expression": b["license"]}],
                                    "properties": [{"name": "formwright:linking", "value": b["linking"]}]}
                                   for b in c["bundled"]]
        comps.append(entry)
    body = {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
            "metadata": {"component": {"type": "application", "name": app, "version": version},
                         "tools": {"components": [{"type": "application", "name": "formwright scripts/sbom.py"}]}},
            "components": comps}
    serial = uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(body, sort_keys=True))
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "serialNumber": f"urn:uuid:{serial}", **{
        k: v for k, v in body.items() if k not in ("bomFormat", "specVersion")}}


def effective_class(c: dict[str, Any]) -> str:
    """The component's own class, raised by any bundled native library (OR options already resolved)."""
    order = {k: i for i, k in enumerate(CLASSES)}
    return max([c["class"], *(classify(b["license"]) for b in c["bundled"])], key=lambda k: order[k])


def load_allowlist(path: Path = ALLOWLIST) -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {f"{e['ecosystem']}:{norm(e['name']) if e['ecosystem'] == 'pypi' else e['name']}": e
            for e in data.get("entries", [])}


def audit(components: list[dict[str, Any]], allow: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Flagged components without an allow-list entry (or whose class got worse than the entry allows)."""
    order = {k: i for i, k in enumerate(CLASSES)}
    problems = []
    for c in components:
        cls = effective_class(c)
        if cls not in FLAGGED:
            continue
        key = f"{c['ecosystem']}:{norm(c['name']) if c['ecosystem'] == 'pypi' else c['name']}"
        e = allow.get(key)
        if e is None:
            problems.append({**c, "effective_class": cls, "problem": "not in the allow-list"})
        elif order[cls] > order.get(e.get("max_class", "unknown"), 0):
            problems.append({**c, "effective_class": cls,
                             "problem": f"class {cls} exceeds the allow-listed {e.get('max_class')}"})
    return problems


def collect(root: Path = ROOT) -> dict[str, Any]:
    py = python_components(root / "uv.lock")
    web = npm_components(root / "web" / "package-lock.json")
    for c in py + web:
        c["effective_class"] = effective_class(c)
    return {"python": py, "web": web}


def summary(comps: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for c in comps:
        s = out.setdefault(c["scope"], {})
        s[c["effective_class"]] = s.get(c["effective_class"], 0) + 1
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "legal")
    ap.add_argument("--check", action="store_true", help="audit only: exit 1 on an unlisted copyleft/unknown licence")
    ap.add_argument("--allowlist", type=Path, default=ALLOWLIST)
    a = ap.parse_args(argv)
    data = collect()
    allow = load_allowlist(a.allowlist)
    problems = audit(data["python"] + data["web"], allow)
    for p in problems:
        print(f"LICENCE: {p['ecosystem']} {p['name']} {p['version']} ({p['scope']}): {p['license']} "
              f"[{p['effective_class']}] - {p['problem']}")
    if not a.check:
        a.out.mkdir(parents=True, exist_ok=True)
        from importlib.metadata import version

        try:
            app_v = version("aicad")
        except Exception:  # noqa: BLE001
            app_v = "0"
        web_v = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8")).get("version", "0")
        for name, comps, app, v in (("sbom-python.cdx.json", data["python"], "formwright-server", app_v),
                                    ("sbom-web.cdx.json", data["web"], "formwright-web", web_v)):
            (a.out / name).write_text(json.dumps(cyclonedx(comps, app, v), indent=1) + "\n", encoding="utf-8")
        flagged = [c for c in data["python"] + data["web"] if c["effective_class"] in FLAGGED]
        report = {"python": summary(data["python"]), "web": summary(data["web"]),
                  "flagged": [{k: c[k] for k in ("ecosystem", "name", "version", "scope", "license",
                                                  "effective_class", "bundled")} for c in flagged],
                  "components": {"python": len(data["python"]), "web": len(data["web"])}}
        (a.out / "licenses.json").write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {a.out}/sbom-python.cdx.json ({len(data['python'])}), sbom-web.cdx.json ({len(data['web'])}), "
              f"licenses.json ({len(flagged)} flagged)")
    print(f"{len(problems)} licence problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
