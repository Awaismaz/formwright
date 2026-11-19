"""Agent latency benchmark (agent-latency report): five representative design turns, timed from the run record.

Where EVAL-003 (``aicad bench``) asks "does the agent build the right part?", this asks "how long does a turn take,
and what does it cost, without making the part worse?". Each case is a prompt a user (or the Design Office) sends,
an analytic expectation (judged exactly like the benchmark: gating checks + bbox + volume + cylinder census, never
the agent's words) and, for an edit, the design the edit starts from. Per turn the report takes from the AGT-009 run
record: wall time (send to settled verdict), time to the first response, model calls, output tokens, cost, builds,
tools used, and whether the result passed.

Cases (fixed, so before/after compare like with like):
  OFF  Design Office ticket: the founder's pinion shaft (ICD-driven turned part), verbatim office prompt
  BRK  gusseted L-bracket, fully dimensioned
  MMP  NEMA 23 motor mount plate (pilot bore, M5 pattern, M6 counterbored corners, R5 corners)
  EDT  an edit of an existing base plate: the six holes become M8 counterbored holes
  THR  turned pivot pin with a cosmetic M16x1.5 thread and a cross hole

Modes (no model call unless ``--live`` is given explicitly):
  --dry     synthetic replays of each case's reference solution: proves expectations and harness agree (free)
  --live    the real design agent; prints an estimate and asks to confirm (or --yes). Spends tokens.

    uv run aicad latency --dry
    uv run aicad latency --live --yes --only BRK,EDT --label before --out lat-before
    uv run aicad latency --live --yes --model claude-sonnet-5-5 --only EDT --label sonnet
    uv run aicad latency --compare lat-before lat-after          # the before/after table (markdown)

The session is pre-connected and the build worker warmed before the clock starts, as the Studio does when a project
opens (PS-04) and the Office does at ICD approval, so the numbers are a turn's own latency.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from aicad.eval.benchmark import BENCH_SUFFIX, USD_PER_TOKEN, score, synthetic_cassette

HDR = "from build123d import *\nfrom math import pi, sqrt\nfrom aicad import fw\n"
FLAT = "(Align.CENTER, Align.CENTER, Align.MIN)"


def _simpson(f: Any, a: float, b: float, n: int = 2000) -> float:
    h = (b - a) / n
    return (f(a) + f(b) + sum((4 if i % 2 else 2) * f(a + i * h) for i in range(1, n))) * h / 3


def cross_hole_volume(R: float, a: float) -> float:
    """Material a Ã˜2a through hole removes from a Ã˜2R rod, axes perpendicular and intersecting (hand integral: the
    hole's cross-section disc yÂ² + zÂ² <= aÂ² times the rod's chord 2 sqrt(RÂ² - yÂ²))."""
    return _simpson(lambda y: 2 * math.sqrt(max(a * a - y * y, 0)) * 2 * math.sqrt(R * R - y * y), -a, a)


def _chamfer45(r: float, c: float) -> float:
    """A 45Â° chamfer c on a circular edge of radius r (Pappus: triangle cÂ²/2 at radius r - c/3)."""
    return c * c / 2 * 2 * math.pi * (r - c / 3)


def _cbore(d: float, depth: float, D: float, h: float) -> float:
    return math.pi / 4 * d * d * depth + math.pi / 4 * (D * D - d * d) * h


# ------------------------------------------------------------------ the cases
OFFICE_SHAFT = (Path(__file__).with_name("latency_office_shaft.txt"))

EDIT_SEED = HDR + '''NAME = "Base plate"
MATERIAL = "Steel S355"
LENGTH = 200  # mm, along X
WIDTH = 150  # mm, along Y
THICK = 12  # mm
BORE_D = 40  # centre bore
PCD = 120  # bolt circle
N_HOLES = 6
HOLE_D = 6.6  # M6 clearance (ISO 273 medium)
PARAMS = dict(LENGTH=LENGTH, WIDTH=WIDTH, THICK=THICK, BORE_D=BORE_D, PCD=PCD, N_HOLES=N_HOLES, HOLE_D=HOLE_D)

part = fw.feature("Base plate", Box(LENGTH, WIDTH, THICK, align=(Align.CENTER, Align.CENTER, Align.MIN)))
part = fw.feature("Centre bore", part - Pos(0, 0, THICK / 2) * Cylinder(BORE_D / 2, THICK + 2))
for loc in PolarLocations(PCD / 2, N_HOLES):
    part = part - Pos(0, 0, THICK / 2) * loc * Cylinder(HOLE_D / 2, THICK + 2)
part = fw.feature("Bolt holes", part)
result = part
EXPECTED = {"bbox": [LENGTH, WIDTH, THICK], "solids": 1,
            "volume": LENGTH * WIDTH * THICK - pi * BORE_D ** 2 / 4 * THICK - N_HOLES * pi * HOLE_D ** 2 / 4 * THICK}
'''

_off_vol = math.pi / 4 * (20 ** 2 * 100 + 26 ** 2 * 30)  # journals 2 x 50 + seat 30 (ICD), before keyways and finish
_brk_vol = 80 * 60 * 8 + 80 * 8 * 62 + 2 * 0.5 * 40 * 40 * 8 - 4 * math.pi * 4.5 ** 2 * 8
_mmp_vol = ((90 * 90 - (4 - math.pi) * 5 ** 2) * 10 - math.pi / 4 * 38.1 ** 2 * 10 - 4 * math.pi / 4 * 5.5 ** 2 * 10
            - 4 * _cbore(6.6, 10, 11, 6.5))
_edt_vol = 200 * 150 * 12 - math.pi * 20 ** 2 * 12 - 6 * _cbore(9, 12, 15, 9)
_thr_vol = (math.pi * 15 ** 2 * 12 + math.pi * 8 ** 2 * 50 - _chamfer45(15, 1) - _chamfer45(8, 1)
            - cross_hole_volume(8, 3))

CASES: list[dict[str, Any]] = [
    {"id": "OFF", "kind": "office ticket", "simple": True, "prompt_file": OFFICE_SHAFT.name,
     # the agent chooses the finish (chamfers, fillets, a circlip groove, the stub keyway): 4 % on the ICD volume
     "expect": {"bbox": [26, 26, 130], "volume": _off_vol, "vol_tol": 0.04, "cylinders": {20: 1, 26: 1}, "solids": 1},
     "reference": HDR + '''NAME = "Pinion shaft"
MATERIAL = "Steel 1045 (C45)"
D_JOURNAL = 20
D_SEAT = 26
L_JOURNAL = 50
L_SEAT = 30
PARAMS = dict(D_JOURNAL=D_JOURNAL, D_SEAT=D_SEAT, L_JOURNAL=L_JOURNAL, L_SEAT=L_SEAT)
part, s = fw.stepped_shaft([(D_JOURNAL, L_JOURNAL), (D_SEAT, L_SEAT), (D_JOURNAL, L_JOURNAL)], chamfer=1,
                           z0=-(L_JOURNAL + L_SEAT / 2))
part, kv = fw.shaft_keyway(part, D_SEAT, 0, 18, b=8, t1=4, angle=0)
result = part
EXPECTED = {"bbox": s["bbox"], "volume": s["volume"] - kv, "solids": 1}
'''},
    {"id": "BRK", "kind": "bracket", "simple": True,
     "prompt": ("Gusseted L-bracket in 6061-T6, 8 mm plate throughout, 80 mm wide along X. The base leg is 60 mm deep "
                "along Y and lies on Z = 0; the upright leg stands at the back edge, 70 mm tall overall. Two triangular "
                "gussets, 8 mm thick, flush with the two side faces, with 40 mm legs along the base and up the upright "
                "measured from the inside corner. Two Ã˜9 mm through holes in the base at X = Â±25, 20 mm from the front "
                "edge; two Ã˜9 mm through holes in the upright at X = Â±20, 50 mm above the underside. Sharp edges, no "
                "fillets."),
     "expect": {"bbox": [80, 60, 70], "volume": _brk_vol, "vol_tol": 0.01, "cylinders": {9: 4}, "solids": 1},
     "reference": HDR + '''NAME = "Gusseted L-bracket"
MATERIAL = "Aluminium 6061-T6"
part = Box(80, 60, 8, align=(Align.CENTER, Align.MIN, Align.MIN))
part += Pos(0, 52, 0) * Box(80, 8, 70, align=(Align.CENTER, Align.MIN, Align.MIN))
tri = Plane.YZ * Polygon((52, 8), (12, 8), (52, 48), align=None)
for x in (-40, 32):
    part += Pos(x, 0, 0) * extrude(tri, 8, dir=(1, 0, 0))
for x in (-25, 25):
    part -= Pos(x, 20, 4) * Cylinder(4.5, 10)
for x in (-20, 20):
    part -= Pos(x, 56, 50) * Rot(90, 0, 0) * Cylinder(4.5, 10)
result = part
EXPECTED = {"bbox": [80, 60, 70], "volume": 80*60*8 + 80*8*62 + 2*0.5*40*40*8 - 4*pi*4.5**2*8, "solids": 1}
'''},
    {"id": "MMP", "kind": "plate", "simple": True,
     "prompt": ("NEMA 23 motor mount plate in 6061-T6: 90 Ã— 90 Ã— 10 mm with R5 vertical corner radii; a Ã˜38.1 mm "
                "pilot bore through the centre; four Ã˜5.5 mm through holes for the M5 motor screws on a 47.14 mm "
                "square pattern centred on the bore; four M6 counterbored mounting holes 10 mm in from both adjacent "
                "edges (Ã˜6.6 through, counterbore Ã˜11 Ã— 6.5 mm deep from the top face)."),
     "expect": {"bbox": [90, 90, 10], "volume": _mmp_vol, "vol_tol": 0.01, "cylinders": {38.1: 1, 5.5: 4, 6.6: 4,
                                                                                         11: 4}, "solids": 1},
     "reference": HDR + f'''NAME = "NEMA 23 motor plate"
MATERIAL = "Aluminium 6061-T6"
part = extrude(RectangleRounded(90, 90, 5), 10)
part -= Pos(0, 0, 5) * Cylinder(38.1 / 2, 12)
for x in (-23.57, 23.57):
    for y in (-23.57, 23.57):
        part -= Pos(x, y, 5) * Cylinder(2.75, 12)
for x in (-35, 35):
    for y in (-35, 35):
        part -= Pos(x, y, 5) * Cylinder(3.3, 12)
        part -= Pos(x, y, 10 - 6.5) * Cylinder(5.5, 6.5, align={FLAT})
result = part
EXPECTED = {{"bbox": [90, 90, 10], "volume": {_mmp_vol!r}, "solids": 1}}
'''},
    {"id": "EDT", "kind": "edit", "simple": True, "seed": EDIT_SEED,
     "prompt": ("Change the six bolt holes to M8 counterbored holes for socket head cap screws: Ã˜9 through with a "
                "Ã˜15 Ã— 9 mm deep counterbore from the top face. Keep everything else."),
     "expect": {"bbox": [200, 150, 12], "volume": _edt_vol, "vol_tol": 0.01, "cylinders": {40: 1, 9: 6, 15: 6},
                "solids": 1},
     "reference": EDIT_SEED.replace("HOLE_D = 6.6  # M6 clearance (ISO 273 medium)", "HOLE_D = 9  # M8 clearance\n"
                                    "CB_D = 15\nCB_DEPTH = 9")
                           .replace("    part = part - Pos(0, 0, THICK / 2) * loc * Cylinder(HOLE_D / 2, THICK + 2)",
                                    "    part = part - Pos(0, 0, THICK / 2) * loc * Cylinder(HOLE_D / 2, THICK + 2)\n"
                                    "    part = part - Pos(0, 0, THICK - CB_DEPTH / 2) * loc * Cylinder(CB_D / 2, CB_DEPTH)")
                           .replace("- N_HOLES * pi * HOLE_D ** 2 / 4 * THICK}",
                                    "- N_HOLES * (pi * HOLE_D ** 2 / 4 * THICK + pi * (CB_D ** 2 - HOLE_D ** 2) / 4 "
                                    "* CB_DEPTH)}")},
    {"id": "THR", "kind": "turned + thread", "simple": True,
     "prompt": ("Threaded pivot pin in 303 stainless steel, axis Z: a Ã˜30 Ã— 12 mm head from Z = 0, then a Ã˜16 mm shank "
                "50 mm long. The last 25 mm of the shank carries an M16Ã—1.5 external thread (cosmetic). A Ã˜6 mm cross "
                "hole goes through the shank along X, 10 mm above the head's top face. 1 mm Ã— 45Â° chamfers on both end "
                "edges (the head's bottom edge and the shank tip)."),
     "expect": {"bbox": [30, 30, 62], "volume": _thr_vol, "vol_tol": 0.01, "cylinders": {30: 1, 16: 1, 6: 1},
                "solids": 1},
     "reference": HDR + f'''NAME = "Pivot pin"
MATERIAL = "Stainless 303"
part, s = fw.stepped_shaft([(30, 12), (16, 50)], chamfer=1)
part -= Pos(0, 0, 22) * Rot(0, 90, 0) * Cylinder(3, 20)
part = fw.thread(part, (8, 0, 61), "M16x1.5", depth=25)
result = part
EXPECTED = {{"bbox": [30, 30, 62], "volume": {_thr_vol!r}, "solids": 1}}
'''},
]
assert len({c["id"] for c in CASES}) == len(CASES)


def prompt_of(case: dict[str, Any]) -> str:
    if case.get("prompt_file"):
        return Path(__file__).with_name(case["prompt_file"]).read_text(encoding="utf-8").strip()
    return case["prompt"] + BENCH_SUFFIX


# ------------------------------------------------------------------ one turn
def metrics_from_record(rec: dict[str, Any] | None) -> dict[str, Any]:
    """The latency facts of one turn from its AGT-009 run record."""
    rec = rec or {}
    t = rec.get("timings_s") or {}
    cb = rec.get("cost_breakdown") or {}
    calls = rec.get("calls") or []
    return {"record_total_s": t.get("total"), "first_response_s": t.get("first_response"),
            "connect_s": t.get("connect"), "build_s": t.get("builds"), "model_api_s": t.get("model_api"),
            "model_calls": cb.get("model_calls"), "output_tokens": cb.get("output_tokens"),
            "context_max": cb.get("context_tokens_max"), "cost_usd": (rec.get("cost_usd") or {}).get("run")
            if (rec.get("cost_usd") or {}).get("run") is not None else cb.get("cost_usd"),
            "tools": (rec.get("tools") or {}).get("by_name"), "models": (rec.get("model") or {}).get("used"),
            "effort": (rec.get("turn") or {}).get("effort"), "turn": rec.get("turn"),
            "calls": [{k: c.get(k) for k in ("n", "start_s", "duration_s", "output_tokens", "tools")} for c in calls],
            "outcome": (rec.get("outcome") or {}).get("status")}


async def run_case(case: dict[str, Any], mode: str, root: Path, model: str | None = None,
                   record_dir: Path | None = None) -> dict[str, Any]:
    from aicad.agent import worker
    from aicad.agent.replay import RecordingClient, ReplayClient
    from aicad.agent.runner import is_verified
    from aicad.agent.session import AgentSession, provider_client

    ws = root / case["id"]
    (ws / "out").mkdir(parents=True, exist_ok=True)
    key = "latency"
    await worker.warm(key)
    if case.get("seed"):  # an edit starts from a built, verified design
        (ws / "model.py").write_text(case["seed"], encoding="utf-8")
        await worker.build(key, ws / "model.py", ws / "out", determinism=True)
    events: list[dict[str, Any]] = []
    s = AgentSession(ws, model=model, on_event=events.append, worker_key=key)
    if mode == "dry":
        cas = synthetic_cassette(case)
        s.client_factory = lambda o: ReplayClient(o, cas, worker_key=key)
    elif record_dir is not None:
        rec = record_dir / f"{case['id']}.json"
        s.client_factory = lambda o: RecordingClient(o, rec)
    else:
        s.client_factory = provider_client
    prompt = prompt_of(case)
    await s.preconnect()  # the Studio pre-connects when a project opens (PS-04); not part of the turn
    t0 = time.perf_counter()
    await s.send(prompt)
    wall = time.perf_counter() - t0
    if s.client is not None:
        try:
            await s.client.disconnect()
        except Exception as e:  # noqa: BLE001 - a dead agent process must not stop the benchmark
            print(f"  (agent disconnect: {e})")

    def _read(name: str) -> dict[str, Any] | None:
        try:
            return json.loads((ws / "out" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    st = _read("status.json")
    sc = score(case["expect"], st, _read("topo.json"))
    m = metrics_from_record(s.last_run_record)
    texts = [e.get("text", "") for e in events if e.get("type") == "text"]
    script = (ws / "model.py").read_text(encoding="utf-8") if (ws / "model.py").is_file() else ""
    passed = bool(sc.get("passed")) and is_verified(st or {})
    cost = m.get("cost_usd") or 0.0
    return {"id": case["id"], "kind": case["kind"], "mode": mode, "wall_s": round(wall, 1), **m,
            "tokens_platform": round(cost / USD_PER_TOKEN, 1) if cost else 0, "passed": passed,
            "verified": is_verified(st or {}), "score": sc,
            "builds": sum(1 for e in events if e.get("type") == "tool_result" and e.get("build")),
            "reply_chars": sum(len(t) for t in texts), "script_lines": len(script.splitlines()),
            "faces": ((st or {}).get("fingerprint") or {}).get("faces"),
            "volume": ((st or {}).get("fingerprint") or {}).get("volume"),
            "edit_block": any(e.get("type") == "edit" for e in events),
            "errors": [e.get("text") for e in events if e.get("type") == "error"]}


# ------------------------------------------------------------------ report
COLS = ("wall_s", "first_response_s", "model_calls", "output_tokens", "cost_usd", "builds", "passed")


def markdown(rows: list[dict[str, Any]], label: str) -> str:
    lines = [f"# Agent latency ({label})", "",
             "| Case | Wall s | First response s | Calls | Output tok | Cost $ | Builds | Pass | Tools | Notes |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['id']} | {r.get('wall_s')} | {r.get('first_response_s')} | {r.get('model_calls')} | "
                     f"{r.get('output_tokens')} | {r.get('cost_usd')} | {r.get('builds')} | "
                     f"{'yes' if r.get('passed') else 'no'} | {json.dumps(r.get('tools'))} | "
                     f"{'; '.join((r.get('score') or {}).get('notes') or [])} |")
    tot = {k: round(sum(float(r.get(k) or 0) for r in rows), 3) for k in ("wall_s", "output_tokens", "cost_usd")}
    lines += ["", (f"Total: wall {tot['wall_s']} s, output {tot['output_tokens']:.0f} tokens, ${tot['cost_usd']}, "
                   f"pass {sum(1 for r in rows if r.get('passed'))}/{len(rows)}")]
    return "\n".join(lines) + "\n"


def compare(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> str:
    """Before/after per case (markdown)."""
    a = {r["id"]: r for r in after}
    lines = ["| Case | Wall s (before â†’ after) | First response s | Output tokens | Cost $ | Pass |",
             "|---|---|---|---|---|---|"]
    for b in before:
        x = a.get(b["id"])
        if x is None:
            continue

        def cell(k: str, nd: int = 1, b: dict[str, Any] = b, x: dict[str, Any] = x) -> str:
            vb, va = b.get(k), x.get(k)
            if vb is None or va is None:
                return f"{vb} â†’ {va}"
            return f"{round(float(vb), nd):g} â†’ {round(float(va), nd):g}"

        lines.append(f"| {b['id']} | {cell('wall_s')} | {cell('first_response_s')} | {cell('output_tokens', 0)} | "
                     f"{cell('cost_usd', 3)} | {'yes' if b.get('passed') else 'no'} â†’ "
                     f"{'yes' if x.get('passed') else 'no'} |")
    return "\n".join(lines) + "\n"


async def run(cases: list[dict[str, Any]], mode: str, out: Path, label: str, model: str | None = None,
              record_dir: Path | None = None) -> list[dict[str, Any]]:
    from aicad.agent import worker

    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="fw-latency-") as tmp:
        try:
            for c in cases:
                r = await run_case(c, mode, Path(tmp), model, record_dir)
                rows.append(r)
                print(f"  {c['id']:<4} {'PASS' if r['passed'] else 'FAIL'}  wall {r['wall_s']} s  first "
                      f"{r.get('first_response_s')} s  out {r.get('output_tokens')} tok  ${r.get('cost_usd')}  "
                      f"calls {r.get('model_calls')}  {'; '.join(r['score'].get('notes') or [])}", flush=True)
                (out / "rows.json").write_text(json.dumps({"label": label, "model": model, "rows": rows}, indent=1,
                                                          default=str), encoding="utf-8")
        finally:
            await worker.shutdown_all()
    (out / "report.md").write_text(markdown(rows, label), encoding="utf-8")
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aicad latency", description=__doc__.split("\n\n")[0])
    m = ap.add_mutually_exclusive_group(required=True)
    m.add_argument("--dry", action="store_true", help="synthetic replays of the reference solutions (no model calls)")
    m.add_argument("--live", action="store_true", help="run the real design agent (spends tokens)")
    m.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"), help="before/after table")
    ap.add_argument("--only", help="comma-separated case ids, e.g. BRK,EDT")
    ap.add_argument("--yes", action="store_true", help="with --live: skip the cost confirmation")
    ap.add_argument("--model", help="with --live: agent model override")
    ap.add_argument("--label", default="run", help="a name for this run (report heading)")
    ap.add_argument("--record", type=Path, metavar="DIR", help="with --live: save each turn as DIR/<id>.json")
    ap.add_argument("--out", type=Path, default=Path("latency-out"))
    a = ap.parse_args(argv)
    if a.compare:
        rows = [json.loads((p / "rows.json").read_text(encoding="utf-8"))["rows"] for p in a.compare]
        print(compare(rows[0], rows[1]))
        return 0
    cases = CASES
    if a.only:
        want = {x.strip().upper() for x in a.only.split(",")}
        cases = [c for c in CASES if c["id"] in want]
        if not cases:
            print(f"no cases match {a.only}")
            return 2
    mode = "dry" if a.dry else "live"
    if mode == "live":
        print(f"Live latency benchmark: {len(cases)} turn(s), about 10-25 tokens each.")
        if not a.yes:
            print("Refusing to spend tokens without confirmation: pass --yes.")
            return 2
        from aicad.studio.app import use_subscription_auth

        use_subscription_auth()
    print(f"Latency ({mode}, {a.label}): {len(cases)} case(s)")
    rows = asyncio.run(run(cases, mode, a.out, a.label, a.model, a.record))
    print(markdown(rows, a.label))
    return 0 if mode == "live" or all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
