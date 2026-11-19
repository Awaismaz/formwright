"""Run the existing layout tests with the parity plugin, one or two files per pytest call (the machine's resource
rule), and print the parity table of docs/reports/connection-layout.md.

    unset VIRTUAL_ENV; uv run python docs/reports/connection-layout/parity.py [test files...]
"""

from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FILES = ["tests/test_office_icd.py", "tests/test_office_shaft_line.py", "tests/test_office_gearbox_caps.py",
         "tests/test_office_small.py", "tests/test_office_phase6_layout.py", "tests/test_design_graph.py"]


def main(files: list[str]) -> None:
    out = HERE / "parity.jsonl"
    out.unlink(missing_ok=True)
    env = dict(os.environ, FW_PARITY_OUT=str(out), PYTHONPATH=str(HERE) + os.pathsep + os.environ.get("PYTHONPATH", ""),
               FW_GRAPH_LAYOUT="0")  # the tests' own graph plans keep the template, so the plugin compares like for like
    for f in files:
        r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "parity_plugin", "-p", "no:cacheprovider", f],
                           cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        print(f, (r.stdout.strip().splitlines() or ["?"])[-1])
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines() if x.strip()]
    by = collections.defaultdict(collections.Counter)
    for r in rows:
        by[(Path(r["test"].split("::")[0]).name, r["layout"])][r["status"]] += 1
    print("\n| Test file | Template layout | Builds | Identical | Positions match | Differs | Template used | Errors |")
    print("|---|---|---:|---:|---:|---:|---:|---:|")
    for (f, lay), c in sorted(by.items()):
        print(f"| {f} | {lay} | {sum(c.values())} | {c['identical']} | {c['positions match']} | {c['differs']} | "
              f"{c['unsupported (template used)']} | {c['error']} |")
    tot = collections.Counter(r["status"] for r in rows)
    print(f"\nTotal {len(rows)} builds: " + ", ".join(f"{k} {v}" for k, v in tot.most_common()))
    for r in rows:
        if r["status"] in ("differs", "error", "positions match"):
            print("-", r["test"], r["layout"], r["status"], r.get("why") or r.get("diffs"))


if __name__ == "__main__":
    main(sys.argv[1:] or FILES)
