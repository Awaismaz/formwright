"""Pytest plugin: parity of the connection layout against the template layout (docs/reports/connection-layout.md).

Every ``icd.build`` an existing test makes still returns the template's layout (the tests run unchanged). Beside it,
the plugin reads the template's own parts, skeleton and interfaces back into a design graph (``adapt.from_parts``),
solves that graph with ``graph/layout.py`` and records whether the two layouts agree: the same items at the same
copies and sizes (0.01 mm), the same interfaces (kind, sides, copies) and the same interface numbers. One JSON line
per build in ``$FW_PARITY_OUT``. Run it through ``parity.py``.
"""

from __future__ import annotations

import json
import os
from typing import Any

from aicad.graph import adapt, layout
from aicad.office import icd

_orig = icd.build
_SKIP = {"name", "label", "edited", "phase_b", "shoulder_source", "bearing"}


def _num_eq(a: Any, b: Any) -> bool:
    if isinstance(a, int | float) and isinstance(b, int | float) and not isinstance(a, bool):
        return abs(float(a) - float(b)) <= 0.011
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_num_eq(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_num_eq(a[k], b[k]) for k in a)
    return a == b


def compare(t_sk: dict[str, Any], t_if: list[dict[str, Any]], s_sk: dict[str, Any], s_if: list[dict[str, Any]]
            ) -> dict[str, Any]:
    diffs: list[str] = []
    for i, a in t_sk["items"].items():
        b = s_sk["items"].get(i)
        if b is None:
            diffs.append(f"{a['name']}: not laid out")
            continue
        for k in ("copies", "size", "ax"):
            if not _num_eq(a.get(k), b.get(k)):
                diffs.append(f"{a['name']} {k}: {a.get(k)} vs {b.get(k)}")
    pos = not diffs

    def key(f: dict[str, Any]) -> tuple[Any, ...]:
        return (f["kind"], f["a"]["item"], f["a"]["copy"], f["b"]["item"], f["b"]["copy"])

    tk, sk = sorted(map(key, t_if)), sorted(map(key, s_if))
    ifs_same = tk == sk
    if not ifs_same:
        miss = [k for k in tk if k not in sk][:2]
        extra = [k for k in sk if k not in tk][:2]
        diffs.append(f"interfaces: template only {miss}, solver only {extra}")
    sd = {key(f): f["data"] for f in s_if}
    data_bad = 0
    for f in t_if:
        d2 = sd.get(key(f))
        if d2 is None:
            continue
        bad = [k for k in set(f["data"]) | set(d2) if k not in _SKIP and k != "journals"
               and not _num_eq(f["data"].get(k), d2.get(k))]
        if bad:
            data_bad += 1
            if data_bad <= 2:
                diffs.append(f"{f['kind']} {f['b']['name']}: {', '.join(sorted(bad))}")
    status = "identical" if pos and ifs_same and not data_bad else "positions match" if pos else "differs"
    return {"status": status, "diffs": diffs[:5], "items": len(t_sk["items"]), "interfaces": len(t_if),
            "problems_t": len(icd.problems(t_sk, t_if)), "problems_s": len(icd.problems(s_sk, s_if)),
            "conflicts": [c["text"] for c in s_sk.get("conflicts") or []][:2]}


def _wrapped(parts: list[dict[str, Any]], brief: str = "", overrides: dict[str, Any] | None = None
             ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    sk, ifs = _orig(parts, brief, overrides)
    rec: dict[str, Any] = {"test": os.environ.get("PYTEST_CURRENT_TEST", "").split(" ")[0],
                           "layout": sk.get("layout"), "names": sorted(it["name"] for it in sk["items"].values())[:6]}
    try:
        g = adapt.from_parts(parts, sk, ifs, brief)
        s2, i2 = layout.build(g, parts, brief, overrides, resolved=True)
        rec.update(compare(sk, ifs, s2, i2))
    except layout.Unsupported as e:
        rec.update(status="unsupported (template used)", why=str(e))
    except Exception as e:  # noqa: BLE001  (recorded: a solver crash is a parity failure, never hidden)
        rec.update(status="error", why=f"{type(e).__name__}: {e}")
    with open(os.environ["FW_PARITY_OUT"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
    return sk, ifs


def pytest_configure(config: Any) -> None:
    icd.build = _wrapped
