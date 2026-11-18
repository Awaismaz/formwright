"""Rebuild the golden assembly fixtures and run their checks, or regenerate their definition files."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from aicad.fixtures import MODULES
from aicad.fixtures.harness import definition_json, run

SPECS = Path(__file__).resolve().parents[3] / "specs" / "fixtures"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m aicad.fixtures", description=__doc__)
    ap.add_argument("--write", action="store_true", help="write specs/fixtures/<fixture>/assembly.json")
    ap.add_argument("--only", help="comma-separated fixture ids, e.g. FX-04,FX-06")
    a = ap.parse_args(argv)
    want = {x.strip().upper() for x in a.only.split(",")} if a.only else set(MODULES)
    ok = True
    for fid, mod in MODULES.items():
        if fid not in want:
            continue
        fx = mod.fixture()
        if a.write:
            d = SPECS / mod.SLUG
            d.mkdir(parents=True, exist_ok=True)
            (d / "assembly.json").write_text(definition_json(fx), encoding="utf-8", newline="\n")
            print(f"{fid}: wrote {d / 'assembly.json'}")
            continue
        with tempfile.TemporaryDirectory(prefix="fw-fx-") as tmp:
            rep = run(fx, Path(tmp))
        bad = [c for c in rep["checks"] if not c["passed"]]
        ok &= not bad
        print(f"{fid} {fx.title}: {len(rep['checks']) - len(bad)}/{len(rep['checks'])} checks pass")
        for c in bad:
            print(f"  FAIL {c['id']}: {c['name']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
