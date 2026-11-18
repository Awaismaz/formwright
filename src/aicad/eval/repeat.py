"""EVAL-008 repeatability: the same prompt N times (default 5), and how much the resulting geometry varies.

Each run starts from an empty workspace and a fresh agent conversation, so runs are independent samples. Per run the
harness records the final build's gate verdict, every check's pass/fail, volume, bounding box (size and corners),
topology counts (faces/edges/solids), the feature count and the cylinder census, plus builds, tokens and time. The
report gives, per metric, mean / standard deviation / min / max / spread and the number of distinct values, the pass
rate of every check, and the share of runs whose geometry is identical to the most common result.

Modes (no model call unless ``--live`` is given explicitly):
  --fake             (default) synthetic replays of a reference solution: every run must come out identical.
                     Proves the harness; NOT a measurement of the agent.
  --replay PATH      recorded turns: a folder of cassettes (run i replays the i-th file, cycling) or one cassette
                     replayed for every run. Make them with --live --record DIR.
  --live             the real design agent. Spends tokens: prints an estimate and asks to confirm (or --yes).

    uv run aicad repeat --case P01                     # fake, 5 runs
    uv run aicad repeat --case B02 --live --runs 5 --record rep-cassettes --yes
    uv run aicad repeat --case B02 --replay rep-cassettes --out rep-out

Variance is judged on the deterministic build outputs only, never on the agent's own words.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

from aicad.eval.benchmark import (
    BENCH_SUFFIX,
    HIGH_TOKENS,
    TYPICAL_TOKENS,
    USD_PER_TOKEN,
    cylinder_census,
    score,
)
from aicad.eval.benchmark import synthetic_cassette as _bench_cassette
from aicad.eval.prompts import CASES

DEFAULT_RUNS = 5
GEOM_TOL = {"volume": 1e-6, "bbox": 1e-6}  # relative: "identical geometry" within kernel round-off
METRICS = ("volume", "bbox_x", "bbox_y", "bbox_z", "faces", "edges", "solids", "features", "builds", "duration_s",
           "tokens_platform")


# ------------------------------------------------------------------ one run
def run_metrics(status: dict[str, Any] | None, topo: dict[str, Any] | None) -> dict[str, Any]:
    """The geometry facts of one finished run (all None when nothing was built)."""
    st = status or {}
    fp = st.get("fingerprint") or {}
    bb = [float(x) for x in fp.get("bbox") or []]
    checks = {str(c.get("id")): bool(c.get("passed")) for c in st.get("checks") or [] if isinstance(c, dict)}
    built = bool(fp) and not st.get("error")
    return {"built": built, "gates_ok": bool(st.get("ok")) and built, "checks": checks,
            "volume": float(fp["volume"]) if built and "volume" in fp else None,
            "bbox_x": bb[0] if len(bb) == 3 else None, "bbox_y": bb[1] if len(bb) == 3 else None,
            "bbox_z": bb[2] if len(bb) == 3 else None, "bbox_minmax": st.get("bbox_minmax"),
            "faces": fp.get("faces"), "edges": fp.get("edges"), "solids": fp.get("solids"),
            "features": len(st.get("features") or []) if built else None,
            "census": {str(k): v for k, v in sorted(cylinder_census(topo or {}).items())} if built else {}}


def geometry_key(m: dict[str, Any]) -> str | None:
    """Rounded identity of a result: two runs with the same key built the same part (within round-off)."""
    if not m.get("built"):
        return None

    def r(v: Any, rel: float) -> Any:
        if v is None:
            return None
        if not v:
            return 0.0
        digits = max(0, int(-math.floor(math.log10(abs(v) * rel))))  # rel tolerance -> decimal places
        return round(float(v), digits)

    return json.dumps([r(m["volume"], GEOM_TOL["volume"]), *(r(m[k], GEOM_TOL["bbox"]) for k in
                       ("bbox_x", "bbox_y", "bbox_z")), m["faces"], m["edges"], m["solids"], m["census"]])


async def run_once(prompt: str, ws: Path, client_factory: Any, expect: dict[str, Any] | None = None,
                   model: str | None = None) -> dict[str, Any]:
    """One independent run in an empty workspace. ``client_factory(options)`` builds the agent client."""
    from aicad.agent.session import AgentSession

    ws.mkdir(parents=True, exist_ok=True)
    events: list[dict[str, Any]] = []
    s = AgentSession(ws, model=model, on_event=events.append, worker_key="repeat")
    s.client_factory = client_factory
    t0 = time.time()
    await s.send(prompt + BENCH_SUFFIX)
    if s.client is not None:
        try:
            await s.client.disconnect()
        except Exception as e:  # noqa: BLE001 - a dead agent process must not stop the series
            print(f"  (agent disconnect: {e})")

    def _read(name: str) -> dict[str, Any] | None:
        try:
            return json.loads((ws / "out" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    st, topo = _read("status.json"), _read("topo.json")
    m = run_metrics(st, topo)
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    cost = float(result.get("cost_est_usd") or 0.0)
    m.update(builds=sum(1 for e in events if e.get("type") == "tool_result" and e.get("build")),
             duration_s=round(time.time() - t0, 2), cost_usd=round(cost, 4),
             tokens_platform=round(cost / USD_PER_TOKEN) if cost else 0,
             errors=[e.get("text") for e in events if e.get("type") == "error"])
    m["key"] = geometry_key(m)
    if expect is not None:
        m["expect_passed"] = bool(score(expect, st, topo).get("passed"))
    return m


# ------------------------------------------------------------------ the series
def _stats(vals: list[float]) -> dict[str, Any]:
    if not vals:
        return {"n": 0}
    mean = statistics.fmean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return {"n": len(vals), "mean": round(mean, 6), "stdev": round(sd, 6), "min": min(vals), "max": max(vals),
            "spread": round(max(vals) - min(vals), 6), "cv": round(sd / abs(mean), 6) if mean else None,
            "distinct": len({round(v, 6) for v in vals})}


def summarise(runs: list[dict[str, Any]], *, mode: str, prompt: str, case: str | None) -> dict[str, Any]:
    n = len(runs) or 1
    built = [r for r in runs if r.get("built")]
    keys = Counter(r["key"] for r in built if r.get("key"))
    modal, modal_n = keys.most_common(1)[0] if keys else (None, 0)
    check_ids = sorted({c for r in runs for c in r.get("checks", {})})
    metrics = {k: _stats([float(r[k]) for r in runs if r.get(k) is not None]) for k in METRICS}
    varying = [k for k in ("volume", "bbox_x", "bbox_y", "bbox_z", "faces", "edges", "solids", "features")
               if metrics[k].get("distinct", 0) > 1]
    census_variants = len({json.dumps(r.get("census"), sort_keys=True) for r in built})
    if census_variants > 1:
        varying.append("census")
    if not built:
        verdict = "nothing built"
    elif len(built) == len(runs) and len(keys) == 1:
        verdict = "repeatable: every run built the same geometry"
    else:
        verdict = f"varies: {len(keys)} distinct results; differs in {', '.join(varying) or 'build success'}"
    out: dict[str, Any] = {
        "mode": mode, "case": case, "prompt": prompt, "runs": len(runs), "built_rate": round(len(built) / n, 3),
        "gates_pass_rate": round(sum(1 for r in runs if r.get("gates_ok")) / n, 3),
        "check_pass_rate": {c: round(sum(1 for r in runs if r.get("checks", {}).get(c)) / n, 3) for c in check_ids},
        "identical_to_modal": round(modal_n / n, 3), "distinct_geometries": len(keys), "modal_key": modal,
        "metrics": metrics, "varying": varying, "verdict": verdict,
        "note": ("fake mode: synthetic replays of the reference solution; validates the harness, not the agent"
                 if mode == "fake" else "")}
    if any("expect_passed" in r for r in runs):
        out["expect_pass_rate"] = round(sum(1 for r in runs if r.get("expect_passed")) / n, 3)
    return out


def markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [f"# Repeatability ({s['mode']}): {s['case'] or 'custom prompt'} x {s['runs']}", "",
             f"**{s['verdict']}**", "",
             f"Built {s['built_rate']:.0%} · gates passed {s['gates_pass_rate']:.0%} · identical to the most common "
             f"result {s['identical_to_modal']:.0%} · distinct geometries {s['distinct_geometries']}"
             + (f" · met the case expectation {s['expect_pass_rate']:.0%}" if "expect_pass_rate" in s else ""), ""]
    if s.get("note"):
        lines += [f"> {s['note']}", ""]
    lines += ["| Metric | n | mean | stdev | min | max | spread | CV | distinct |", "|---|---|---|---|---|---|---|---|---|"]
    for k, m in s["metrics"].items():
        if m.get("n"):
            lines.append(f"| {k} | {m['n']} | {m['mean']:g} | {m['stdev']:g} | {m['min']:g} | {m['max']:g} | "
                         f"{m['spread']:g} | {'' if m['cv'] is None else format(m['cv'], 'g')} | {m['distinct']} |")
    if s["check_pass_rate"]:
        lines += ["", "| Check | pass rate |", "|---|---|"]
        lines += [f"| {c} | {v:.0%} |" for c, v in s["check_pass_rate"].items()]
    lines += ["", "| Run | Built | Gates | Volume mm³ | Size mm | Faces | Features | Builds | Time s |",
              "|---|---|---|---|---|---|---|---|---|"]
    yn = {True: "yes", False: "no", None: "–"}
    for i, r in enumerate(report["runs"], 1):
        size = " × ".join(f"{r[k]:g}" for k in ("bbox_x", "bbox_y", "bbox_z")) if r.get("built") else "–"
        vol = f"{r['volume']:.3f}" if r.get("volume") is not None else "–"
        lines.append(f"| {i} | {yn[r.get('built')]} | {yn[r.get('gates_ok')]} | {vol} | {size} | "
                     f"{r.get('faces') if r.get('faces') is not None else '–'} | "
                     f"{r.get('features') if r.get('features') is not None else '–'} | {r.get('builds', 0)} | "
                     f"{r.get('duration_s', '–')} |")
    return "\n".join(lines) + "\n"


def fake_cassette(reference: str) -> dict[str, Any]:
    """A synthetic ideal turn that writes ``reference`` and builds it once (no model call)."""
    return _bench_cassette({"reference": reference})


def _replay_files(path: Path) -> list[Path]:
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not files:
        raise FileNotFoundError(f"no cassettes in {path}")
    return files


async def run_series(prompt: str, runs: int, mode: str, out: Path, *, reference: str | None = None,
                     replay: Path | None = None, record: Path | None = None, expect: dict[str, Any] | None = None,
                     case: str | None = None, model: str | None = None,
                     factory_for: Any = None) -> dict[str, Any]:
    """Run the series and write ``report.json`` + ``report.md`` to ``out``. ``factory_for(i)`` (tests) overrides the
    client factory of run i."""
    from aicad.agent import worker
    from aicad.agent.replay import RecordingClient, ReplayClient
    from aicad.agent.session import provider_client

    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    cassettes = _replay_files(replay) if mode == "replay" and replay is not None else []
    with tempfile.TemporaryDirectory(prefix="fw-repeat-") as tmp:
        try:
            for i in range(runs):
                if factory_for is not None:
                    factory = factory_for(i)
                elif mode == "fake":
                    if not reference:
                        raise ValueError("fake mode needs a reference solution (use --case)")
                    cas = fake_cassette(reference)
                    factory = lambda o, cas=cas: ReplayClient(o, cas, worker_key="repeat")
                elif mode == "replay":
                    f = cassettes[i % len(cassettes)]
                    factory = lambda o, f=f: ReplayClient(o, f, worker_key="repeat")
                elif record is not None:
                    rec = record / f"run-{i + 1:02d}.json"
                    factory = lambda o, rec=rec: RecordingClient(o, rec)
                else:
                    factory = provider_client
                r = await run_once(prompt, Path(tmp) / f"run-{i + 1:02d}", factory, expect, model)
                rows.append(r)
                print(f"  run {i + 1}/{runs}: {'built' if r['built'] else 'no build'}  "
                      f"gates {'PASS' if r['gates_ok'] else 'FAIL'}  volume {r.get('volume')}", flush=True)
        finally:
            await worker.shutdown_all()
    report = {"summary": summarise(rows, mode=mode, prompt=prompt, case=case), "runs": rows}
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (out / "report.md").write_text(markdown(report), encoding="utf-8")
    return report


def estimate(runs: int) -> str:
    return (f"{runs} live runs ~ {runs * TYPICAL_TOKENS:,} tokens typical (~ ${runs * TYPICAL_TOKENS * USD_PER_TOKEN:,.0f})"
            f", up to {runs * HIGH_TOKENS:,} tokens (~ ${runs * HIGH_TOKENS * USD_PER_TOKEN:,.0f})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aicad repeat", description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--case", help="a benchmark case id (prompt, expectation and reference), e.g. P01")
    src.add_argument("--prompt", help="free text prompt (needs --replay or --live; --reference FILE for --fake)")
    m = ap.add_mutually_exclusive_group()
    m.add_argument("--fake", action="store_true", help="(default) synthetic replays of the reference: no model calls")
    m.add_argument("--replay", type=Path, metavar="PATH", help="cassette folder (run i uses file i) or one cassette")
    m.add_argument("--live", action="store_true", help="run the real design agent (spends tokens)")
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS, help=f"number of runs (default {DEFAULT_RUNS})")
    ap.add_argument("--reference", type=Path, help="with --prompt --fake: the model script every run replays")
    ap.add_argument("--record", type=Path, metavar="DIR", help="with --live: save each run as DIR/run-NN.json")
    ap.add_argument("--yes", action="store_true", help="with --live: skip the cost confirmation")
    ap.add_argument("--model", help="with --live: agent model override")
    ap.add_argument("--api-key", action="store_true", help="with --live: bill ANTHROPIC_API_KEY instead of the login")
    ap.add_argument("--out", type=Path, default=Path("repeat-out"), help="report folder (report.json, report.md)")
    a = ap.parse_args(argv)
    if not 1 <= a.runs <= 50:
        print("--runs must be between 1 and 50")
        return 2
    mode = "live" if a.live else "replay" if a.replay else "fake"
    case = None
    if a.case:
        case = next((c for c in CASES if c["id"] == a.case.strip().upper()), None)
        if case is None:
            print(f"no benchmark case {a.case}")
            return 2
    prompt = case["prompt"] if case else a.prompt
    reference = case["reference"] if case else (a.reference.read_text(encoding="utf-8") if a.reference else None)
    if mode == "fake" and not reference:
        print("fake mode needs --case or --reference FILE")
        return 2
    if a.record and mode != "live":
        print("--record only applies to --live")
        return 2
    if mode == "live":
        print("Live repeatability: " + estimate(a.runs) + ".")
        if not a.yes:
            if not sys.stdin.isatty():
                print("Refusing to spend tokens without confirmation: pass --yes.")
                return 2
            try:
                if input("Proceed? [y/N] ").strip().lower() != "y":
                    return 1
            except EOFError:
                print("No confirmation received: nothing was run.")
                return 2
        if not a.api_key:
            from aicad.studio.app import use_subscription_auth

            use_subscription_auth()
    print(f"Repeatability ({mode}): {case['id'] if case else 'custom prompt'} x {a.runs}")
    report = asyncio.run(run_series(prompt, a.runs, mode, a.out, reference=reference, replay=a.replay,
                                    record=a.record, expect=case["expect"] if case else None,
                                    case=case["id"] if case else None, model=a.model))
    print(f"{report['summary']['verdict']}  -> {a.out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
