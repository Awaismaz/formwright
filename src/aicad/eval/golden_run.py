"""``aicad golden``: run the golden mechanism suite through the Design Office end to end (WORKLIST 46, EVAL-003).

Each case runs in its own throwaway platform (temporary data folder and database, the real FastAPI app in process):
a fresh workspace with a wallet, a program from the case's brief, the plan, the interfaces gate (the one-step light
path where the office offers it, else plan approval, "Fix with Archie" once when the interfaces have problems, ICD
approval) and Run, then the whole-program clash check. It measures completion, wall time per phase, tokens, clashes,
loose and binned parts, interface conformance, supervisor interventions and every expectation of the case, and
appends one record per case to the history (``golden.history_dir()``).

Modes
  --simulated   (default) simulated agents (``office.fake_agents``), Archie's plan replayed from the case (or the
                office's own planner), the supervisor and the visual checks in their simulated, rule-based mode.
                Deterministic and free: any live model call fails the case. One case at a time; the CAD workers are
                reaped after each case.
  --live        real agents through the office (the development Claude Code login, PD-09). Each case has a token
                cap (``[limits] tokens``, or ``--cap``): the program budget is set to it and the office is paused as
                soon as the wallet has spent it.

    uv run aicad golden                          # every case, simulated
    uv run aicad golden --case keyed-gear,b      # by id or letter
    uv run aicad golden --live --case a,b --cap 30
    uv run aicad golden --list

The founder's data is never touched: every run uses its own temporary folder (``--work``).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from aicad.eval import golden

EMAIL = "golden@formwright.test"
PASSWORD = "golden suite 46 ok"
WALLET = 100_000


def say(*a: Any) -> None:
    print(*a, flush=True)


class Stop(Exception):
    pass


# ----------------------------------------------------------------------------- the throwaway platform
@contextlib.contextmanager
def _env(values: dict[str, str | None]) -> Iterator[None]:
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def _patched(patches: list[tuple[Any, str, Any]]) -> Iterator[None]:
    saved = [(obj, name, getattr(obj, name)) for obj, name, _ in patches]
    try:
        for obj, name, val in patches:
            setattr(obj, name, val)
        yield
    finally:
        for obj, name, val in saved:
            setattr(obj, name, val)


def _no_live_ai(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError("golden suite, simulated: a live model call was attempted")


def _replay_planner(plan: dict[str, Any]) -> Any:
    async def run_agent(folder: Path, name: str, brief: str, notes: str = "", budget_usd: float | None = None
                        ) -> tuple[str, float | None]:
        text = ("Plan replayed from the golden case.\n\n```fw-plan\n" + json.dumps(plan, ensure_ascii=False)
                + "\n```")
        return text, None
    return run_agent


def _sim_llm(intent: dict[str, Any] | None) -> Any:
    """Simulated runs: the recorded intent reply for the design-graph planner (FW_DESIGN_GRAPH=1), else the
    tripwire. No other model call is answered."""
    async def complete(req: Any) -> Any:
        from aicad.llm.base import CallResult, Metering

        if intent is not None and getattr(req, "role", None) == "intent":
            return CallResult(text=json.dumps(intent), metering=Metering(provider="replay", role="intent", model=None),
                              data=intent)
        return _no_live_ai()
    return complete


def _replay_master(src: str | None) -> Any:
    """Simulated runs: the case's recorded master model (WORKLIST 50), else no master (the office falls back to the
    fast path and says so). Never a live turn."""
    async def agent_turn(folder: Path, name: str, brief: str, plan: dict[str, Any], budget_usd: float | None = None,
                         worker_key: str | None = None) -> Any:
        from aicad.master.run import Turn

        if src is None:
            return Turn(None, error="no master model is recorded for this golden case")
        return Turn(src, via="replay")
    return agent_turn


def graph_on(flags: dict[str, str] | None) -> bool:
    """The design-graph planner is the product default (PD-110); a run's flags, else the environment, can turn it off."""
    v = (flags or {}).get("FW_DESIGN_GRAPH", os.environ.get("FW_DESIGN_GRAPH", ""))
    return str(v).strip().lower() not in ("0", "false", "no", "off")


def reap_workers() -> None:
    from aicad.agent import worker as bworker
    from aicad.assembly import worker as aworker
    from aicad.drawing import worker as dworker

    for mod in (bworker, aworker, dworker):
        with contextlib.suppress(Exception):
            mod.kill_all()


def _wallet(org_id: str, set_to: int | None = None) -> int:
    from aicad.platform.db import session_factory
    from aicad.platform.models import Organization

    db = session_factory()()
    try:
        org = db.get(Organization, org_id)
        if set_to is not None:
            org.token_balance = set_to
            db.commit()
        return int(org.token_balance)
    finally:
        db.close()


# ----------------------------------------------------------------------------- one case
def _ok(r: Any, what: str) -> dict[str, Any]:
    if r.status_code != 200:
        raise Stop(f"{what}: HTTP {r.status_code} {r.text[:300]}")
    return r.json()


def _poll(c: Any, pid: str, pred: Any, timeout: float, every: float = 0.25, on_tick: Any = None) -> dict[str, Any]:
    t0 = time.time()
    v: dict[str, Any] = {}
    while time.time() - t0 < timeout:
        v = _ok(c.get(f"/api/office/programs/{pid}"), "read the program")
        if on_tick is not None:
            on_tick(v)
        if pred(v):
            return v
        time.sleep(every)
    raise Stop(f"timed out after {timeout:.0f} s")


def _stalled(v: dict[str, Any]) -> bool:
    o = v.get("orchestrator") or {}
    return o.get("state") == "running" and int(o.get("blocked") or 0) > 0 and not int(o.get("working") or 0) \
        and not int(o.get("waiting") or 0) and not int(o.get("active") or 0)


def drive(c: Any, case: dict[str, Any], mode: str, cap: int | None, log: Any, out: dict[str, Any]) -> None:
    """Plan, gate, run and check one program through the API. Fills ``out`` as it goes (timings, the program id,
    tokens, the stop reason), so a case that stops early still reports what it measured; raises ``Stop``."""
    from aicad.office import program_assembly

    sim = case.get("sim") or {}
    # Archie plans live, or replays the case's plan, or (design-graph path) replays the recorded intent reply
    archie = mode == "live" or "plan_data" in sim or (
        graph_on({"FW_DESIGN_GRAPH": os.environ.get("FW_DESIGN_GRAPH", "")}) and "intent_data" in sim)
    lim = case.get("limits") or {}
    wall = float(lim.get(f"wall_{mode}_s") or 600)
    phases: dict[str, float] = out.setdefault("phases", {})
    out.update(stopped=None, pid=None, fix=None, icd_problems_first=None, tokens=0)
    org = c.get("/api/auth/me").json()["org"]["id"]
    start_wallet = _wallet(org)
    out["spent"] = lambda: start_wallet - _wallet(org)
    paused = {"done": False}

    def watch(v: dict[str, Any]) -> None:  # the live token cap: pause the office once the wallet has spent it
        if mode != "live" or cap is None or paused["done"]:
            return
        if start_wallet - _wallet(org) >= cap and (v.get("orchestrator") or {}).get("state") == "running":
            c.post(f"/api/office/programs/{v['id']}/pause")
            paused["done"] = True
            out["stopped"] = f"token cap {cap} reached"

    t = time.time()
    body: dict[str, Any] = {"name": case["title"][:60], "brief": case["brief"],
                            "planner": "archie" if archie else "standard", "deliverables": False}
    if mode == "live" and cap is not None:
        body["budget_tokens"] = cap
    v = _ok(c.post("/api/office/programs", json=body), "create the program")
    pid = out["pid"] = v["id"]
    v = _poll(c, pid, lambda v: v["status"] != "planning", 900 if mode == "live" else 300)
    phases["plan"] = round(time.time() - t, 2)
    if v["status"] != "plan_review":
        raise Stop(f"planning ended in '{v['status']}'")
    qs = (((v.get("plan") or {}).get("graph") or {}).get("questions")) or []
    out["questions"] = len(qs)
    if qs:  # design-graph plans (PD-110) ask before approval: the runner takes Archie's defaults, as a user may
        ans = {q["id"]: q["default"] for q in qs if q.get("default")}
        v = _ok(c.post(f"/api/office/programs/{pid}/plan/answers", json={"answers": ans}), "take Archie's defaults")
        v = _poll(c, pid, lambda v: v["status"] != "planning", 900 if mode == "live" else 300)
        if (((v.get("plan") or {}).get("graph") or {}).get("questions")):
            raise Stop("Archie still has questions after his defaults were taken")
    lp = (v.get("plan") or {}).get("layout_path") or {}
    mm = (v.get("plan") or {}).get("master") or {}
    out["path"] = {"path": lp.get("path"), "words": lp.get("words"),
                   "reasons": [r.get("code") for r in lp.get("reasons") or []], "forced": lp.get("mode") == "force",
                   "master_s": (mm.get("seconds") or {}).get("total"), "master_tokens": mm.get("tokens"),
                   "master_ok": mm.get("ok"), "master_errors": len(mm.get("errors") or []),
                   "trial_s": (lp.get("trial") or {}).get("seconds")}
    log(f"  plan: {sum(len(s['parts']) for s in v['plan']['subassemblies'])} part lines "
        f"({phases['plan']:.1f} s){', small program' if v.get('light') else ''}; {lp.get('words') or 'no layout path'}")

    t = time.time()
    ran = False
    if v.get("light"):
        v = _ok(c.post(f"/api/office/programs/{pid}/gates/express", json={}), "approve in one step")
        ex = v.get("express") or {}
        out["icd_problems_first"] = int(ex.get("problems") or 0)
        ran = bool(ex.get("run"))
        if ex.get("run_blocked"):
            raise Stop(f"Run refused: {ex['run_blocked']}")
    else:
        v = _ok(c.post(f"/api/office/programs/{pid}/gates/brief/approve", json={}), "approve the plan")
    if not ran:
        if not v.get("icd"):
            raise Stop("no interfaces were drafted")
        probs = len(v["icd"].get("problems") or [])
        if out["icd_problems_first"] is None:
            out["icd_problems_first"] = probs
        if probs:  # the engineer's in-product way out: Fix with Archie, once
            r = c.post(f"/api/office/programs/{pid}/icd/fix")
            out["fix"] = (r.json().get("fix") if r.status_code == 200 else {"error": r.text[:200]})
            v = _ok(c.get(f"/api/office/programs/{pid}"), "read the program")
            left = [p.get("text") if isinstance(p, dict) else str(p) for p in v["icd"].get("problems") or []]
            if left:
                phases["gate"] = round(time.time() - t, 2)
                raise Stop(f"interfaces gate: {len(left)} problem(s) left after Fix with Archie: {left[0][:200]}")
        _ok(c.post(f"/api/office/programs/{pid}/gates/icd/approve"), "approve the interfaces")
        _ok(c.post(f"/api/office/programs/{pid}/run"), "press Run")
    phases["gate"] = round(time.time() - t, 2)
    log(f"  gates: {'one step' if v.get('light') else 'plan + interfaces'}, "
        f"{out['icd_problems_first']} interface problem(s) ({phases['gate']:.1f} s)")

    t = time.time()
    since: dict[str, float] = {}

    def done(v: dict[str, Any]) -> bool:
        st = (v.get("orchestrator") or {}).get("state")
        if v["status"] == "complete" or st in ("complete", "stopped") or (st == "paused" and paused["done"]):
            return True
        if _stalled(v):  # every open ticket waits for the engineer; Archie (supervisor) gets a grace period
            since.setdefault("s", time.time())
            return time.time() - since["s"] > (90 if mode == "live" else 20)
        since.pop("s", None)
        return False

    try:
        v = _poll(c, pid, done, max(300.0, 2 * wall), every=0.5, on_tick=watch)
    except Stop as e:
        raise Stop(f"run {e}") from e
    phases["run"] = round(time.time() - t, 2)
    st = (v.get("orchestrator") or {}).get("state")
    if v["status"] != "complete" and not out["stopped"]:
        blocked = [(x["title"], (x.get("run") or {}).get("reason") or (x.get("run") or {}).get("line"))
                   for x in v["tickets"] if (x.get("run") or {}).get("status") == "blocked"]
        out["stopped"] = (f"office {st}" + (f" ({(v['orchestrator'] or {}).get('reason')})"
                                             if (v.get("orchestrator") or {}).get("reason") else "")
                          + (f"; blocked: {blocked[0][0]}: {str(blocked[0][1])[:240]}" if blocked else ""))
    log(f"  run: {v['status']} ({phases['run']:.1f} s)")

    t = time.time()
    if v["status"] == "complete":
        with contextlib.suppress(Stop):
            v = _poll(c, pid, lambda v: program_assembly.clash_status(v.get("assembly") or {})["status"]
                      in ("done", "failed"), 600, every=0.5)
    phases["check"] = round(time.time() - t, 2)


def snapshot(c: Any, pid: str, drove: dict[str, Any]) -> dict[str, Any]:
    """Everything the expectations read, from the API (and the program's assembly documents)."""
    from aicad.assembly import store as astore
    from aicad.office import program_assembly, scope
    from aicad.office import store as ostore
    from aicad.platform.config import get_settings

    v = _ok(c.get(f"/api/office/programs/{pid}"), "read the program")
    org = v["org_id"]
    plan = v.get("plan") or {"subassemblies": []}
    lines = [p for s in plan["subassemblies"] for p in s["parts"]]
    kinds: dict[str, int] = {}  # pieces of each kind (the brief fixes pieces; a planner may split part lines)
    for p in lines:
        k = scope.kind_of(p["name"]) or "none"
        kinds[k] = kinds.get(k, 0) + int(p.get("qty") or 1)
    tickets = []
    conf_ok = conf_total = direct = no_ai = 0
    for t in v.get("tickets") or []:
        reuse = t.get("reuse") or {}
        chk = t.get("icd_check") or {}
        rows = [row for x in chk.get("interfaces") or [] for row in x.get("rows") or []]
        conf_ok += sum(1 for row in rows if row.get("ok"))
        conf_total += len(rows)
        is_direct = (t.get("direct") or {}).get("path") == "direct"
        direct += int(is_direct)
        # a designed part without a design turn: built from the interfaces, or made from the Toolbox to the ICD
        no_ai += int(t.get("kind") == "part" and (is_direct or reuse.get("source") == "toolbox")
                     and not int(t.get("tokens") or 0))
        tickets.append({"title": t["title"], "kind": t.get("kind"), "column": t["column"],
                        "status": (t.get("run") or {}).get("status"),
                        "reuse_code": reuse.get("code") if reuse.get("source") == "toolbox" else "",
                        "direct": is_direct, "tokens": int(t.get("tokens") or 0) + int(t.get("review_tokens") or 0)})
    insts: list[dict[str, Any]] = []
    stacks: list[dict[str, Any]] = []
    r = c.get(f"/api/office/programs/{pid}/assembly")
    aview = r.json() if r.status_code == 200 else {}
    av = aview.get("view")
    looks = [{"name": x.get("name"), "status": x.get("status"),
              "verdict": (x.get("verdict") or {}).get("overall") if isinstance(x.get("verdict"), dict)
              else x.get("verdict")} for x in aview.get("looks") or []]
    if av:
        parts = av.get("parts") or {}
        for i in av.get("instances") or []:
            bb = (parts.get(i["part"]) or {}).get("bbox") or [0, 0, 0, 0, 0, 0]
            insts.append({"name": i["name"], "T": i["T"], "kind": i.get("kind"), "bin": bool(i.get("bin")),
                          "fastener": bool(i.get("fastener")), "item": i.get("item"),
                          "box": golden.world_box(i["T"], bb)})
    st = v.get("assembly") or {}
    if st.get("final"):
        adoc = astore.load(astore.org_root(get_settings().data_dir, org), st["final"])
        for g in (adoc or {}).get("groups") or []:
            if g.get("kind") == "fastener":
                sp = g.get("spec") or {}
                stacks.append({"style": sp.get("style"), "size": sp.get("size"), "length": sp.get("length")})
    events = ostore.events(ostore.org_root(get_settings().data_dir, org), pid, 100_000)
    blocked = sum(1 for e in events if e.get("type") == "ticket.blocked")
    sup = (v.get("supervisor") or {}).get("log") or []
    cs = program_assembly.clash_status(st)
    placed = [i for i in insts if not i["bin"]]
    metrics = {
        "wall_s": round(sum(drove["phases"].values()), 2), "phases": drove["phases"],
        "tokens": int(drove.get("tokens") or 0), "light": bool((v.get("express") or {}).get("approved")),
        "parts": len(lines), "pieces": sum(int(p.get("qty") or 1) for p in lines),
        "subs": len(plan["subassemblies"]), "tickets": len(v.get("tickets") or []),
        "instances": len(insts), "clashes": cs["count"], "clash_check": cs["status"],
        "binned": sum(1 for i in insts if i["bin"]), "loose": len(golden.loose_names(placed)),
        "loose_names": golden.loose_names(placed)[:12],
        "placeholders": sum(1 for i in insts if i["kind"] == "placeholder"),
        "blocked": blocked, "icd_problems": drove.get("icd_problems_first"),
        "interfaces": len((v.get("icd") or {}).get("interfaces") or []), "questions": drove.get("questions") or 0,
        "conformance": {"ok": conf_ok, "total": conf_total}, "direct": direct, "no_ai": no_ai,
        "supervisor": sum(1 for e in sup if e.get("status") in ("applied", "asking", "done", "undone")),
        "supervisor_asking": sum(1 for e in sup if e.get("status") == "asking"),
        "ai_parts": sum(1 for t in tickets if t["kind"] == "part" and t["tokens"] > 0),
        "looks_wrong": sum(1 for x in looks if "wrong" in str(x["verdict"] or "")),
        "path": (drove.get("path") or {}).get("path"), "path_words": (drove.get("path") or {}).get("words"),
        "path_forced": bool((drove.get("path") or {}).get("forced")),
        "path_reasons": (drove.get("path") or {}).get("reasons"),
        "master_s": (drove.get("path") or {}).get("master_s"),
        "master_tokens": (drove.get("path") or {}).get("master_tokens"),
        "master_ok": (drove.get("path") or {}).get("master_ok"),
    }
    return {"status": v["status"], "stopped": drove.get("stopped"), "metrics": metrics, "kinds": kinds,
            "tickets": tickets, "instances": insts, "stacks": stacks,
            "warnings": (v.get("icd") or {}).get("warnings") or [], "fix": drove.get("fix"), "looks": looks,
            "supervisor": [{k: e.get(k) for k in ("status", "tool", "class", "title", "diagnosis", "outcome")}
                           for e in sup][:12]}


def run_case(case: dict[str, Any], mode: str = "simulated", *, work: Path | None = None, cap: int | None = None,
             keep: bool = False, log: Any = say, routing: dict[str, str] | None = None,
             flags: dict[str, str] | None = None) -> dict[str, Any]:
    """Run one case in its own throwaway platform; returns the history record (not yet appended). ``flags``: extra
    server environment for the run (a product switch under comparison, e.g. ``FW_DESIGN_GRAPH=1``), recorded."""
    from fastapi.testclient import TestClient

    from aicad import llm
    from aicad.office import fake_agents, gage, planner
    from aicad.platform import config
    from aicad.platform.routers import auth as auth_router

    tmp = Path(tempfile.mkdtemp(prefix=f"golden-{case['id']}-", dir=str(work) if work else None))
    cap = cap if cap is not None else (case.get("limits") or {}).get("tokens")
    sim = mode == "simulated"
    env = {"FW_ADMIN_PASSWORD": PASSWORD, fake_agents.ENV: "1" if sim else "0", "FW_OFFICE_FAKE_DELAY": None,
           "FW_OFFICE_FAKE_DEFECTS": None, "FW_OFFICE_FAKE_SCRIPT": None, "FW_OFFICE_SUPERVISOR": None,
           "FW_OFFICE_SUPERVISOR_LIVE": None, "FW_ASSEMBLY_VISUAL_CHECK": None, **(flags or {})}
    patches: list[tuple[Any, str, Any]] = []
    if sim:
        plan = (case.get("sim") or {}).get("plan_data")
        from aicad.master import run as master_run

        patches += [(planner, "run_agent", _replay_planner(plan) if plan else _no_live_ai),
                    (master_run, "agent_turn", _replay_master((case.get("sim") or {}).get("master_src"))),
                    (gage, "run_review", _no_live_ai),
                    (llm, "complete", _sim_llm((case.get("sim") or {}).get("intent_data") if graph_on(flags) else None))]
    rec: dict[str, Any] = {"schema": golden.SCHEMA, "run_id": uuid.uuid4().hex[:12], "at": _now(), "mode": mode,
                           "case": case["id"], "title": case["title"], "letter": case.get("letter"),
                           "cap": cap if mode == "live" else None, "flags": dict(flags or {})}
    t0 = time.time()
    log(f"[{case['id']}] {case['title']} ({mode})")
    try:
        with _env(env), _patched(patches):
            auth_router._attempts.clear()
            config.override_settings(config.Settings(
                env="development", data_dir=tmp / "data", database_url=f"sqlite:///{(tmp / 'db.sqlite').as_posix()}",
                app_url="http://golden.test", superadmin_emails=(EMAIL,), stripe_secret_key="", trial_tokens=1000))
            fake_agents.reset()
            from aicad.platform.app import create_app

            with TestClient(create_app()) as c:
                c.headers.update({"X-FW-CSRF": "1"})
                _ok(c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}), "sign in")
                c.post("/api/onboarding", json={"role": "Design engineer", "workspace_name": "Golden suite"})
                _wallet(c.get("/api/auth/me").json()["org"]["id"], WALLET)
                drove: dict[str, Any] = {"phases": {}}
                try:
                    drive(c, case, mode, cap, log, drove)
                except Stop as e:
                    rec["stopped"] = str(e)
                    log(f"  stopped: {e}")
                finally:
                    if callable(drove.get("spent")):
                        drove["tokens"] = drove.pop("spent")()
                pid = drove.get("pid") or _last_pid(c)
                snap = snapshot(c, pid, {**drove, "phases": drove.get("phases") or {}}) if pid else \
                    {"status": "not created", "metrics": {}, "instances": []}
                if rec.get("stopped"):
                    snap["stopped"] = rec["stopped"]
            fake_agents.reset()
        plan_fixed = sim and not graph_on(flags)  # the case's own plan was replayed
        rows = golden.evaluate(case, snap, mode, plan_fixed)
        rec.update(status=snap["status"], stopped=snap.get("stopped"), metrics=snap["metrics"], plan_fixed=plan_fixed,
                   expectations=rows, passed=golden.passed(rows),
                   detail={"kinds": snap.get("kinds"), "tickets": snap.get("tickets"), "stacks": snap.get("stacks"),
                           "warnings": snap.get("warnings"), "fix": snap.get("fix"), "looks": snap.get("looks"),
                           "supervisor": snap.get("supervisor"),
                           "instances": [{"name": i["name"], "box": i["box"], "bin": i["bin"]}
                                         for i in snap.get("instances") or []][:80]})
    except Exception as e:  # noqa: BLE001 - a crash is a failed case with its reason, never a dead suite
        import traceback

        rec.update(status="error", passed=False, error=f"{type(e).__name__}: {e}", metrics={}, expectations=[],
                   trace=traceback.format_exc()[-2000:])
        log(f"  error: {e}")
    finally:
        reap_workers()
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)
    rec["elapsed_s"] = round(time.time() - t0, 1)
    sha, dirty = golden.git_stamp()
    routes = routing if routing is not None else golden.gather_routing()
    rec.update(sha=sha, dirty=dirty, routing=routes, routing_id=golden.routing_id(routes))
    return rec


def _last_pid(c: Any) -> str | None:
    r = c.get("/api/office/programs")
    items = r.json().get("items") if r.status_code == 200 else None
    return items[0]["id"] if items else None


def _now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------- the suite
def table(recs: list[dict[str, Any]]) -> str:
    head = ("| Case | Result | Path | Wall s (plan/gate/run/check) | Tokens | Clashes | Binned | Loose | Blocked | "
            "Failed expectations |")
    out = [head, "|" + "---|" * 10]
    for r in recs:
        m = r.get("metrics") or {}
        ph = m.get("phases") or {}
        bad = [f"{x['label']}: got {x['got']}, want {x['want']}" for x in r.get("expectations") or []
               if x["ok"] is False]
        if r.get("error"):
            bad = [r["error"]]
        ms = f" ({m['master_s']} s)" if m.get("master_s") else ""
        out.append(f"| {r.get('letter') or ''} {r['case']} | {'PASS' if r.get('passed') else 'FAIL'} | "
                   f"{m.get('path') or ''}{ms} | {m.get('wall_s', '')} ({'/'.join(str(ph.get(k, '-')) for k in ('plan', 'gate', 'run', 'check'))}) | "
                   f"{m.get('tokens', '')} | {m.get('clashes', '')} | {m.get('binned', '')} | {m.get('loose', '')} | "
                   f"{m.get('blocked', '')} | {'; '.join(bad)[:400]} |")
    return "\n".join(out)


def run_suite(cases: list[dict[str, Any]], mode: str = "simulated", *, work: Path | None = None,
              cap: int | None = None, keep: bool = False, history: Path | None = None, record: bool = True,
              log: Any = say, flags: dict[str, str] | None = None) -> list[dict[str, Any]]:
    suite_id = uuid.uuid4().hex[:8]
    routes = golden.gather_routing()
    recs = []
    for case in cases:
        if mode == "simulated" and graph_on(flags) and not (case.get("sim") or {}).get("intent_data"):
            log(f"[{case['id']}] skipped: no recorded intent reply to replay on the design-graph path")
            continue
        rec = run_case(case, mode, work=work, cap=cap, keep=keep, log=log, routing=routes, flags=flags)
        rec["suite_id"] = suite_id
        if record:
            golden.append(rec, history)
        recs.append(rec)
        log(f"  {'PASS' if rec.get('passed') else 'FAIL'} in {rec['elapsed_s']} s")
    return recs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aicad golden", description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--simulated", action="store_true", help="simulated agents, deterministic, 0 tokens (default)")
    g.add_argument("--live", action="store_true", help="real agents through the office (spends tokens)")
    ap.add_argument("--case", default="", help="comma-separated case ids or letters (default: all)")
    ap.add_argument("--fast", action="store_true", help="only the cases marked fast")
    ap.add_argument("--cap", type=int, default=None, help="live: token cap per case (default: the case's limit)")
    ap.add_argument("--work", default=None, help="folder for the throwaway platforms (default: system temp)")
    ap.add_argument("--history", default=None, help="history folder (default: FW_GOLDEN_DIR or eval/golden/history)")
    ap.add_argument("--keep", action="store_true", help="keep each case's throwaway platform")
    ap.add_argument("--no-record", action="store_true", help="don't append to the history")
    ap.add_argument("--json", default=None, help="also write the records of this run to a JSON file")
    ap.add_argument("--env", action="append", default=[], metavar="NAME=VALUE",
                    help="a server switch for these runs (repeatable; recorded with each run), e.g. FW_DESIGN_GRAPH=1")
    ap.add_argument("--list", action="store_true", help="list the cases and exit")
    a = ap.parse_args(argv)
    with contextlib.suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    # reaped CAD workers leave asyncio pipe transports whose finalisers complain at exit: noise, not a result
    sys.unraisablehook = lambda u: None if isinstance(u.exc_value, (ValueError, ResourceWarning)) \
        else sys.__unraisablehook__(u)
    try:
        cases = golden.load_cases([x for x in a.case.split(",") if x.strip()] or None)
    except golden.CaseError as e:
        print(f"error: {e}")
        return 2
    if a.fast:
        cases = [c for c in cases if c.get("fast")]
    if a.list:
        for c in cases:
            print(f"{c.get('letter', ''):>3} {c['id']:<14} {c['title']}  (tokens <= {c['limits'].get('tokens')})")
        return 0
    flags: dict[str, str] = {}
    for kv in a.env:
        k, sep, v = kv.partition("=")
        if not sep or not k.strip().startswith("FW_"):
            print(f"error: --env takes FW_NAME=VALUE, not {kv!r}")
            return 2
        flags[k.strip()] = v
    mode = "live" if a.live else "simulated"
    if mode == "live":
        caps = [a.cap if a.cap is not None else c["limits"].get("tokens") for c in cases]
        print(f"LIVE: {len(cases)} case(s), token caps {caps} (at most {sum(int(x or 0) for x in caps)} tokens).")
    work = Path(a.work) if a.work else None
    if work:
        work.mkdir(parents=True, exist_ok=True)
    recs = run_suite(cases, mode, work=work, cap=a.cap, keep=a.keep, log=say,
                     history=Path(a.history) if a.history else None, record=not a.no_record, flags=flags)
    print()
    print(table(recs))
    n = sum(1 for r in recs if r.get("passed"))
    print(f"\n{n} of {len(recs)} cases pass ({mode}).")
    if a.json:
        Path(a.json).write_text(json.dumps(recs, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return 0 if n == len(recs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
