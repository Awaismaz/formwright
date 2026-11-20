"""EVAL-003 design-agent benchmark: 20 original prompts judged by deterministic checks + analytic expectations.

Modes
  --dry              synthetic replays built from the reference solutions (no model calls). Proves the harness, the
                     expectations and the geometry pipeline agree. NOT a measurement of the agent.
  --replay DIR       replay recorded agent turns (DIR/<case id>.json, made with --live --record DIR). No model calls.
  --live             run the real design agent. Spends tokens: prints an estimate first and asks to confirm
                     (or pass --yes). Development auth uses this PC's Claude Code login (PD-09).

    uv run python -m aicad.eval.benchmark --dry --out bench-out
    uv run python -m aicad.eval.benchmark --live --record bench-cassettes --only P01,B02     # a few, live
    uv run python -m aicad.eval.benchmark --replay bench-cassettes                            # re-score offline

A case passes when the final build's gating checks pass AND bbox, volume and cylinder census match the case's
expectation. The agent's own words (summary, self-review) are never used to score.

Render similarity (EVAL-006, advisory, never gating): ``--save-renders DIR`` keeps each case's review sheet as
DIR/<case id>.png, ``--ref-renders DIR`` compares each new sheet with DIR/<case id>.png (``eval/render_similarity``)
and logs the score per case and the mean in the summary. It never changes a pass or fail.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from aicad.agent.blocks import gate_summary
from aicad.eval import render_similarity
from aicad.eval.prompts import CASES

BENCH_SUFFIX = ("\n\n[Benchmark run: nobody is available to answer questions. Make reasonable, clearly labelled "
                "assumptions and build the part.]")
TYPICAL_TOKENS, HIGH_TOKENS = 250, 400  # measured per new part (metering.DEFAULT_ESTIMATE["new"]); 1 token = $0.01
USD_PER_TOKEN = 0.01


# ------------------------------------------------------------------ scoring
def cylinder_census(topo: dict[str, Any]) -> dict[float, int]:
    """Distinct cylindrical surfaces by diameter, faces sharing an axis counted once."""
    seen: dict[float, set[tuple[float, ...]]] = {}
    for f in topo.get("faces", []):
        if f.get("type") != "cylinder" or not f.get("radius"):
            continue
        ax = f.get("axis") or [0, 0, 1]
        pt = f.get("axis_point") or [0, 0, 0]
        dot = sum(a * b for a, b in zip(ax, pt, strict=False))
        perp = tuple(round(p - dot * a, 2) + 0.0 for p, a in zip(pt, ax, strict=False))
        key = tuple(round(abs(a), 3) for a in ax) + perp
        seen.setdefault(round(2 * f["radius"], 2), set()).add(key)
    return {d: len(v) for d, v in seen.items()}


def score(expect: dict[str, Any], status: dict[str, Any] | None, topo: dict[str, Any] | None) -> dict[str, Any]:
    """Judge one build against a case's expectation."""
    gates = gate_summary(status)
    out: dict[str, Any] = {"gates_ok": gates["ok"], "failed_checks": gates["failed"], "bbox_ok": False,
                           "volume_ok": False, "census_ok": False, "solids_ok": False, "notes": []}
    if not status or status.get("error"):
        out["notes"].append("no successful build" if not status else "build error")
        out["passed"] = False
        return out
    fp = status.get("fingerprint") or {}
    got = sorted(float(x) for x in fp.get("bbox") or [0, 0, 0])
    want = sorted(float(x) for x in expect["bbox"])
    out["bbox_ok"] = all(abs(g - w) <= max(0.5, 0.005 * w) for g, w in zip(got, want, strict=False))
    if not out["bbox_ok"]:
        out["notes"].append(f"bbox {got} vs {want}")
    vol = float(fp.get("volume") or 0)
    out["volume_ok"] = abs(vol - expect["volume"]) <= expect.get("vol_tol", 0.01) * expect["volume"]
    if not out["volume_ok"]:
        out["notes"].append(f"volume {vol:.1f} vs {expect['volume']:.1f}")
    out["solids_ok"] = int(fp.get("solids") or 0) == expect.get("solids", 1)
    census = cylinder_census(topo or {})
    missing = {d: n for d, n in expect.get("cylinders", {}).items()
               if sum(c for dd, c in census.items() if abs(dd - d) <= 0.05) != n}
    out["census_ok"] = not missing
    if missing:
        out["notes"].append("cylinder census " + ", ".join(
            f"Ø{d}: {sum(c for dd, c in census.items() if abs(dd - d) <= 0.05)} vs {n}" for d, n in missing.items()))
    out["passed"] = bool(gates["ok"]) and all(out[k] for k in ("bbox_ok", "volume_ok", "census_ok", "solids_ok"))
    return out


# ------------------------------------------------------------------ synthetic (dry) replays
def synthetic_cassette(case: dict[str, Any]) -> dict[str, Any]:
    """A replay of an ideal agent turn: write the reference design, build once, summarise with a self-review."""
    review = {"observed": [{"text": "Overall size matches the requested envelope", "basis": "CHK-04"},
                           {"text": "Volume matches the hand calculation", "basis": "CHK-05"}],
              "uncertain": [{"text": "Synthetic replay: no visual inspection was made", "basis": "render"}]}
    return {"version": 1, "turns": [{"rebuild": True, "files": {"model.py": case["reference"]}, "messages": [
        {"type": "system", "subtype": "init", "data": {}},
        {"type": "assistant", "model": "replay", "content": [
            {"type": "text", "text": "Modelling the part from the stated dimensions."},
            {"type": "tool_use", "id": "w1", "name": "Write", "input": {"file_path": "model.py"}}]},
        {"type": "user", "content": [{"type": "tool_result", "tool_use_id": "w1", "content": "ok"}]},
        {"type": "assistant", "model": "replay", "content": [
            {"type": "tool_use", "id": "b1", "name": "mcp__cad__build_model", "input": {}}]},
        {"type": "user", "content": [{"type": "tool_result", "tool_use_id": "b1", "content": "(replayed)"}]},
        {"type": "assistant", "model": "replay", "content": [
            {"type": "text", "text": "Built.\n\n```fw-review\n" + json.dumps(review) + "\n```"}]},
        {"type": "result", "subtype": "success", "num_turns": 3, "duration_ms": 0, "session_id": "replay",
         "total_cost_usd": 0.0}]}]}


# ------------------------------------------------------------------ running
class _Tap:
    """Wraps an agent client to capture the result message's usage (input/output tokens)."""

    def __init__(self, inner: Any, sink: dict[str, Any]) -> None:
        self.inner, self.sink = inner, sink

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def receive_response(self) -> Any:
        async for m in self.inner.receive_response():
            if type(m).__name__ == "ResultMessage":
                self.sink["usage"] = getattr(m, "usage", None)
            yield m


def render_row(views: Path, case_id: str, ref_renders: Path | None, save_renders: Path | None) -> dict[str, Any] | None:
    """EVAL-006: keep the case's review sheet and/or compare it with the reference one (advisory, never gating)."""
    if ref_renders is None and save_renders is None:
        return None
    if not views.is_file():
        return {"available": False, "reason": "no render", "advisory": True}
    if save_renders is not None:
        import shutil

        save_renders.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(views, save_renders / f"{case_id}.png")
    if ref_renders is None:
        return None
    ref = ref_renders / f"{case_id}.png"
    sim = render_similarity.compare_files(ref, views) if ref.is_file() else None
    if sim is None:
        return {"available": False, "reason": "no reference render" if not ref.is_file() else "unreadable",
                "advisory": True}
    return {"available": True, **sim}


async def run_case(case: dict[str, Any], mode: str, root: Path, replay_dir: Path | None = None,
                   record_dir: Path | None = None, model: str | None = None, ref_renders: Path | None = None,
                   save_renders: Path | None = None) -> dict[str, Any]:
    from aicad.agent.replay import RecordingClient, ReplayClient
    from aicad.agent.session import AgentSession

    ws = root / case["id"]
    ws.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {"id": case["id"], "family": case["family"], "mode": mode, "builds": 0,
                           "first_pass": None, "pass_within_3": False}
    per_build: list[bool] = []
    events: list[dict[str, Any]] = []
    sink: dict[str, Any] = {}

    def _read(name: str) -> dict[str, Any] | None:
        try:
            return json.loads((ws / "out" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def on_event(ev: dict[str, Any]) -> None:
        events.append(ev)
        if ev.get("type") == "tool_result" and ev.get("build"):
            per_build.append(bool(score(case["expect"], _read("status.json"), _read("topo.json"))["passed"]))

    s = AgentSession(ws, model=model, on_event=on_event, worker_key="bench")
    if mode == "dry":
        cassette = synthetic_cassette(case)
        if ref_renders is not None or save_renders is not None:
            cassette["render"] = True  # the replay renders the review sheet like a live build does
        s.client_factory = lambda o: _Tap(ReplayClient(o, cassette, worker_key="bench"), sink)
    elif mode == "replay":
        f = (replay_dir or Path(".")) / f"{case['id']}.json"
        if not f.is_file():
            return {**row, "passed": False, "notes": [f"no recording at {f.name}"], "skipped": True}
        s.client_factory = lambda o: _Tap(ReplayClient(o, f, worker_key="bench"), sink)
    elif record_dir is not None:
        rec = record_dir / f"{case['id']}.json"
        s.client_factory = lambda o: _Tap(RecordingClient(o, rec), sink)
    else:
        from aicad.agent.session import provider_client
        s.client_factory = lambda o: _Tap(provider_client(o), sink)
    t0 = time.time()
    await s.send(case["prompt"] + BENCH_SUFFIX)
    if s.client is not None:
        try:
            await s.client.disconnect()
        except Exception as e:  # noqa: BLE001 - a dead agent process must not stop the benchmark
            print(f"  (agent disconnect: {e})")
    final = score(case["expect"], _read("status.json"), _read("topo.json"))
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    usage = sink.get("usage") or {}
    cost = result.get("cost_est_usd") or 0.0
    rsim = render_row(ws / "out" / "views.png", case["id"], ref_renders, save_renders)
    if rsim is not None:
        row["render_similarity"] = rsim
    return {**row, **final, "builds": len(per_build), "first_pass": per_build[0] if per_build else False,
            "pass_within_3": any(per_build[:3]), "turns": result.get("turns"),
            "duration_s": round(time.time() - t0, 1), "cost_usd": round(cost, 4),
            "tokens_platform": round(cost / USD_PER_TOKEN) if cost else 0,
            "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
            "self_review": any(e.get("type") == "review" for e in events),
            "errors": [e.get("text") for e in events if e.get("type") == "error"]}


def summarise(rows: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    ran = [r for r in rows if not r.get("skipped")]
    n = len(ran) or 1

    def rate(k: str) -> float:
        return round(sum(1 for r in ran if r.get(k)) / n, 3)

    sims = [float(r["render_similarity"]["score"]) for r in ran
            if (r.get("render_similarity") or {}).get("available")]
    extra = {"render_similarity": render_similarity.summary(sims)} if any("render_similarity" in r for r in ran) else {}
    return {**extra, "mode": mode, "cases": len(rows), "ran": len(ran), "pass_rate": rate("passed"),
            "first_pass_rate": rate("first_pass"), "within_3_rate": rate("pass_within_3"),
            "gates_ok_rate": rate("gates_ok"), "cost_usd": round(sum(r.get("cost_usd") or 0 for r in ran), 3),
            "tokens_platform": sum(r.get("tokens_platform") or 0 for r in ran),
            "time_s": round(sum(r.get("duration_s") or 0 for r in ran), 1),
            "by_family": {f: round(sum(1 for r in ran if r["family"] == f and r.get("passed"))
                                   / max(1, sum(1 for r in ran if r["family"] == f)), 3)
                          for f in sorted({r["family"] for r in ran})},
            "note": ("synthetic replays of the reference solutions: validates the harness and expectations, "
                     "not the agent") if mode == "dry" else ""}


def markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [f"# Design-agent benchmark ({s['mode']})", "",
             (f"Cases {s['ran']}/{s['cases']} · pass {s['pass_rate']:.0%} · first-pass {s['first_pass_rate']:.0%} · "
             f"≤3 builds {s['within_3_rate']:.0%} · gates {s['gates_ok_rate']:.0%} · "
             f"{s['tokens_platform']} tokens (${s['cost_usd']}) · {s['time_s']} s"), ""]
    if s.get("note"):
        lines += [f"> {s['note']}", ""]
    rs = s.get("render_similarity")
    if rs:
        lines += [("Render similarity (advisory, never gating): " + (f"mean {rs['mean']:.3f}, min {rs['min']:.3f} "
                                                                       f"over {rs['n']} case(s)" if rs.get("n")
                                                                       else "no reference renders compared")), ""]
    lines += ["| Case | Family | Pass | Builds | First pass | Gates | Bbox | Volume | Census | Tokens | Time s | Notes |"
              + (" Render sim (advisory) |" if rs else ""),
              "|---|---|---|---|---|---|---|---|---|---|---|---|" + ("---|" if rs else "")]
    yn = {True: "yes", False: "no", None: "-"}
    for r in report["rows"]:
        lines.append(f"| {r['id']} | {r['family']} | {yn[r.get('passed')]} | {r.get('builds', 0)} | "
                     f"{yn[r.get('first_pass')]} | {yn[r.get('gates_ok')]} | {yn[r.get('bbox_ok')]} | "
                     f"{yn[r.get('volume_ok')]} | {yn[r.get('census_ok')]} | {r.get('tokens_platform', 0)} | "
                     f"{r.get('duration_s', '-')} | {'; '.join(r.get('notes') or [])} |"
                     + (f" {_sim_cell(r.get('render_similarity'))} |" if rs else ""))
    return "\n".join(lines) + "\n"


def _sim_cell(r: dict[str, Any] | None) -> str:
    if not r:
        return "-"
    return f"{r['score']:.3f}" if r.get("available") else str(r.get("reason") or "-")


async def run(cases: list[dict[str, Any]], mode: str, out: Path, replay_dir: Path | None = None,
              record_dir: Path | None = None, model: str | None = None, ref_renders: Path | None = None,
              save_renders: Path | None = None) -> dict[str, Any]:
    from aicad.agent import worker

    out.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="fw-bench-") as tmp:
        try:
            for c in cases:
                r = await run_case(c, mode, Path(tmp), replay_dir, record_dir, model, ref_renders, save_renders)
                rows.append(r)
                print(f"  {c['id']:<4} {'PASS' if r.get('passed') else 'FAIL'}  builds {r.get('builds', 0)}  "
                      f"{'; '.join(r.get('notes') or [])}", flush=True)
        finally:
            await worker.shutdown_all()
    report = {"summary": summarise(rows, mode), "rows": rows}
    (out / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (out / "report.md").write_text(markdown(report), encoding="utf-8")
    return report


def estimate(n: int) -> str:
    return (f"{n} live runs ~ {n * TYPICAL_TOKENS:,} tokens typical (~ ${n * TYPICAL_TOKENS * USD_PER_TOKEN:,.0f}), "
            f"up to {n * HIGH_TOKENS:,} tokens (~ ${n * HIGH_TOKENS * USD_PER_TOKEN:,.0f})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aicad bench", description=__doc__.split("\n\n")[0])
    m = ap.add_mutually_exclusive_group(required=True)
    m.add_argument("--dry", action="store_true", help="synthetic replays of the reference solutions (no model calls)")
    m.add_argument("--replay", type=Path, metavar="DIR", help="replay recorded turns DIR/<id>.json (no model calls)")
    m.add_argument("--live", action="store_true", help="run the real design agent (spends tokens)")
    ap.add_argument("--record", type=Path, metavar="DIR", help="with --live: save each turn as DIR/<id>.json")
    ap.add_argument("--only", help="comma-separated case ids, e.g. P01,B02")
    ap.add_argument("--yes", action="store_true", help="with --live: skip the cost confirmation")
    ap.add_argument("--model", help="with --live: agent model override")
    ap.add_argument("--api-key", action="store_true", help="with --live: bill ANTHROPIC_API_KEY instead of the login")
    ap.add_argument("--out", type=Path, default=Path("bench-out"), help="report folder (report.json, report.md)")
    ap.add_argument("--ref-renders", type=Path, metavar="DIR",
                    help="compare each review sheet with DIR/<case id>.png (advisory render similarity)")
    ap.add_argument("--save-renders", type=Path, metavar="DIR", help="keep each review sheet as DIR/<case id>.png")
    a = ap.parse_args(argv)
    cases = CASES
    if a.only:
        want = {x.strip().upper() for x in a.only.split(",")}
        cases = [c for c in CASES if c["id"] in want]
        if not cases:
            print(f"no cases match {a.only}")
            return 2
    mode = "dry" if a.dry else "replay" if a.replay else "live"
    if mode == "live":
        print("Live benchmark: " + estimate(len(cases)) + ".")
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
    print(f"Benchmark ({mode}): {len(cases)} case(s)")
    report = asyncio.run(run(cases, mode, a.out, a.replay, a.record, a.model, a.ref_renders, a.save_renders))
    s = report["summary"]
    print(f"pass {s['pass_rate']:.0%} | first-pass {s['first_pass_rate']:.0%} | <=3 builds {s['within_3_rate']:.0%} | "
          f"{s['tokens_platform']} tokens | {s['time_s']} s  -> {a.out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
