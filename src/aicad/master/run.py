"""The master step of the Design Office planning phase (WORKLIST 50).

``route(root, doc)`` runs after a plan is set: it records the deterministic decision (``decide``) on the plan and,
when the master path is needed, keeps the program in planning (stage "master") so the caller spawns ``task``.
``task`` runs the master turn (one design-agent turn on the Opus tier, dedicated instructions, the ``kit`` helpers),
measures the master in a separate process, writes the measured layout and its design graph onto the plan, meters the
turn like Archie's planning turn, and hands the plan to review. A turn or build that fails falls back to the fast
path, said in plain words on the plan (never silent).

Budget (measured in docs/reports/master-model.md): a master turn targets at most ``TARGET_TOKENS`` platform tokens and
``TARGET_S`` seconds; ``MAX_TOKENS`` is the hard cap per turn. ``FW_MASTER_REPLAY`` (development only) replays a
recorded master script instead of a model turn: a ``*.master.py`` file, or a folder of them whose sibling
``*.plan.json`` names the same designed parts as the plan.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aicad.master import decide as dec
from aicad.master import prompt as mprompt

log = logging.getLogger("aicad.master")

MAX_TOKENS = 120     # hard cap of one master turn (platform tokens)
TARGET_TOKENS = 60   # what a master turn should cost
TARGET_S = 120.0     # and how long it should take, measure included
MEASURE_TIMEOUT_S = 300.0
REPLAY_ENV = "FW_MASTER_REPLAY"


@dataclass
class Turn:
    source: str | None
    cost_usd: float | None = None
    seconds: float = 0.0
    error: str | None = None
    via: str = "agent"   # agent | replay
    meta: dict[str, Any] = field(default_factory=dict)


def _designed_names(plan: dict[str, Any]) -> set[str]:
    return {" ".join(str(p.get("name") or "").lower().split()) for s in plan.get("subassemblies") or []
            for p in s.get("parts") or [] if p.get("family") != "standard"}


def replay_source(plan: dict[str, Any]) -> str | None:
    """A recorded master script for this plan (``FW_MASTER_REPLAY``, development only), else None."""
    raw = os.environ.get(REPLAY_ENV, "").strip()
    if not raw or os.environ.get("FW_ENV", "").strip().lower() == "production":
        return None
    p = Path(raw)
    if p.is_file():
        return p.read_text(encoding="utf-8")
    if p.is_dir():
        want = _designed_names(plan)
        for f in sorted(p.glob("*.master.py")):
            pj = f.with_name(f.name.replace(".master.py", ".plan.json"))
            try:
                names = _designed_names(json.loads(pj.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
            if names and names == want:
                return f.read_text(encoding="utf-8")
    return None


async def agent_turn(folder: Path, name: str, brief: str, plan: dict[str, Any], budget_usd: float | None = None,
                     worker_key: str | None = None) -> Turn:
    """The master turn: the Studio agent machinery (session, CAD build tool, warm worker) with the master
    instructions, on the Opus orchestration tier. Tests and the golden suite's simulated mode replace this."""
    rp = replay_source(plan)
    if rp is not None:
        return Turn(rp, via="replay")
    from aicad.office import fake_agents

    if fake_agents.enabled():
        return Turn(None, error="simulated agents have no master model recorded for this plan")
    from aicad.agent.session import COMPACT_BASE, AgentSession
    from aicad.llm.routing import model_for

    class MasterSession(AgentSession):
        def options(self) -> Any:
            o = super().options()
            o.system_prompt = COMPACT_BASE + mprompt.MASTER_INSTRUCTIONS
            o.resume = None
            return o

    ws = folder / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    got: dict[str, Any] = {"cost": None, "subtype": None, "errors": []}

    def on_event(ev: dict[str, Any]) -> None:
        if ev.get("type") == "result":
            got["cost"], got["subtype"] = ev.get("cost_est_usd"), ev.get("subtype")
        elif ev.get("type") == "error":
            got["errors"].append(str(ev.get("text") or "")[:200])

    s = MasterSession(ws, model=model_for("design_agent", "complex"), on_event=on_event, worker_key=worker_key)
    s.run_budget_usd = budget_usd
    s.brief_approved = True
    t0 = time.perf_counter()
    try:
        await s.send(mprompt.prompt_for(name, brief, plan), shown="Master model", mode="build")
    finally:
        try:
            if s.client is not None:
                await s.client.disconnect()
        except Exception:
            log.debug("master session close failed", exc_info=True)
    rec = s.last_run_record or {}
    meta = {"model": (rec.get("turn") or {}).get("model"), "calls": len(rec.get("calls") or []),
            "subtype": got["subtype"]}
    src = (ws / "model.py").read_text(encoding="utf-8") if (ws / "model.py").exists() else None
    err = None if src else ("the master turn wrote no model" + (f" ({got['errors'][0]})" if got["errors"] else ""))
    return Turn(src, got["cost"], round(time.perf_counter() - t0, 2), err, "agent", meta)


async def measure_file(script: Path, out: Path, timeout: float = MEASURE_TIMEOUT_S) -> dict[str, Any]:
    """Build and measure a master script in its own process (the tripwire applies, as for a Studio build)."""
    from aicad.agent.worker import child_env

    env = {**child_env(), "PYTHONIOENCODING": "utf-8"}
    proc = await asyncio.create_subprocess_exec(sys.executable, "-m", "aicad.master.measure", str(script), str(out),
                                                env=env, stdout=asyncio.subprocess.DEVNULL,
                                                stderr=asyncio.subprocess.PIPE)
    try:
        _o, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        return {"error": f"measuring the master model took longer than {timeout:.0f} s"}
    try:
        return json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"error": "the master model could not be measured" + (f": {err.decode(errors='replace')[-300:]}"
                                                                      if err else "")}


async def run(folder: Path, name: str, brief: str, plan: dict[str, Any], budget_usd: float | None = None,
              worker_key: str | None = None) -> dict[str, Any]:
    """Master turn + measurement. {"ok", "measure", "cost_usd", "seconds": {turn, measure, total}, "via", "error"}."""
    t0 = time.perf_counter()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        turn = await agent_turn(folder, name, brief, plan, budget_usd, worker_key)
    except Exception as e:
        log.exception("master turn failed")
        turn = Turn(None, error=f"the master turn failed ({type(e).__name__})")
    out: dict[str, Any] = {"ok": False, "cost_usd": turn.cost_usd, "via": turn.via, "meta": turn.meta,
                           "seconds": {"turn": turn.seconds}}
    if turn.source is None:
        out["error"] = turn.error or "no master model"
        out["seconds"]["total"] = round(time.perf_counter() - t0, 2)
        return out
    ws = folder / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    script = ws / "model.py"
    if not script.exists() or script.read_text(encoding="utf-8") != turn.source:
        script.write_text(turn.source, encoding="utf-8")
    t1 = time.perf_counter()
    m = await measure_file(script, folder / "measure.json")
    out["seconds"]["measure"] = round(time.perf_counter() - t1, 2)
    out["seconds"]["total"] = round(time.perf_counter() - t0, 2)
    out["script_sha"] = hashlib.sha256(turn.source.encode()).hexdigest()[:12]
    if "error" in m:
        out["error"] = "the master model did not build (" + str(m["error"])[:300] + ")"
        return out
    out.update(ok=True, measure=m)
    return out


# ----------------------------------------------------------------------------- the office hooks
def route(root: Path, doc: dict[str, Any]) -> bool:
    """Record the layout decision on the plan just set; True when the master turn must run now (the program stays in
    planning, stage "master", until ``task`` hands the plan to review). Questions on a design-graph plan come first:
    the decision is taken again once they are answered."""
    from aicad.office import service, store

    plan = doc.get("plan")
    if not plan:
        return False
    if ((plan.get("graph") or {}).get("questions")):
        plan["layout_path"] = {"path": "pending", "words": "The layout path is decided once the questions are answered",
                               "reasons": [], "mode": dec.mode()}
        return False
    d = dec.decide(plan, str(doc.get("brief") or ""), str(doc.get("name") or ""))
    d["at"] = store.now()
    plan["layout_path"] = d
    if d["path"] != "master":
        return False
    d["state"] = "modelling"
    doc["status"] = "planning"
    doc["planning"] = {"started_at": store.now(), "stage": "master", "notes": ""}
    service.emit(root, doc, "plan.master", f"Archie is modelling a master of {doc['name']} before the layout: "
                 + d["reasons"][0]["text"], service.agent_actor("archie"), reasons=[r["code"] for r in d["reasons"]])
    return True


def attach(doc: dict[str, Any], res: dict[str, Any], tokens: int = 0) -> None:
    """Put the master turn's result on the plan: the measurement, the measured design graph, the parts' measured
    envelopes; or the fast-path fallback with the reason."""
    from aicad.graph import office as gview
    from aicad.master import skeleton
    from aicad.office import icd

    plan = doc["plan"]
    lp = plan.setdefault("layout_path", {"path": "master", "reasons": []})
    if not res.get("ok"):
        lp.update(path="fast", state="fallback", fallback=res.get("error"),
                  words="Laid out on the fast path (the master model could not be made: "
                        + str(res.get("error") or "unknown") + ")")
        plan["master"] = {"ok": False, "error": res.get("error"), "seconds": res.get("seconds"), "tokens": tokens,
                          "via": res.get("via")}
        return
    pdoc = dec.pseudo_doc(plan, str(doc.get("brief") or ""), str(doc.get("name") or ""))
    parts = icd.parts_from(pdoc)
    skel, ifs = skeleton.build(res["measure"], parts, str(doc.get("brief") or ""))
    g = skeleton.graph(skel, ifs, parts, str(doc.get("name") or ""), str(doc.get("brief") or ""))
    size_of = {it["name"]: it["size"] for it in skel["items"].values()}
    for s in plan.get("subassemblies") or []:
        for p in s.get("parts") or []:
            if p.get("name") in size_of:
                p["envelope"] = [float(x) for x in size_of[p["name"]]]
    errs = [c["text"] for c in skel.get("conflicts") or []]
    warns = [w["text"] for w in skel.get("findings") or []]
    plan["master"] = {
        "ok": True, "measure": res["measure"], "via": res.get("via"), "seconds": res.get("seconds"), "tokens": tokens,
        "script_sha": res.get("script_sha"),
        "graph": {"data": g.dump(), "view": gview.view(g)},
        "summary": {"bodies": len(res["measure"].get("bodies") or []), "interfaces": len(ifs),
                    "bolted": sum(1 for f in ifs if f["kind"] == "hole_pattern"),
                    "faces": sum(1 for f in ifs if f["kind"] == "face"),
                    "fits": sum(1 for f in ifs if f["kind"] in ("shaft_bore", "dowel"))},
        "errors": errs, "warnings": warns, "notes": list(skel.get("notes") or [])}
    lp["state"] = "done"


async def task(root: Path, pid: str, org_id: str, user_id: str, god_tokens: bool) -> None:
    """The master step in the background (spawned by the office router after ``route`` returned True)."""
    from aicad.office import service, store
    from aicad.platform import metering
    from aicad.platform.db import session_factory
    from aicad.platform.models import Organization, User
    from aicad.platform.services import debit, track

    doc = store.load(root, pid)
    if doc is None or (doc.get("planning") or {}).get("stage") != "master":
        return
    db = session_factory()()
    try:
        org = db.get(Organization, org_id)
        balance = org.token_balance if org else 0
    finally:
        db.close()
    budget = None if god_tokens else max(0, min(balance, MAX_TOKENS)) * metering.USD_PER_TOKEN
    res = await run(store.program_dir(root, pid) / "master", doc["name"], doc["brief"], doc["plan"], budget, org_id)
    usd = res.get("cost_usd")
    tokens = metering.tokens_for_usd(usd) if usd else 0
    if usd:
        db = session_factory()()
        try:
            org, user = db.get(Organization, org_id), db.get(User, user_id)
            if org is not None and not god_tokens:
                debit(db, org, tokens, "usage", f"Design Office · Archie master model for {doc['name']}", user, ref=pid)
            track(db, "office_master_model", user, org_id, tokens=tokens, ok=bool(res.get("ok")))
            db.commit()
        finally:
            db.close()
    with store.lock(pid):
        doc = store.load(root, pid)
        if doc is None or (doc.get("planning") or {}).get("stage") != "master" or not doc.get("plan"):
            return
        attach(doc, res, tokens)
        doc["budget"]["planning_tokens"] = int(doc["budget"].get("planning_tokens", 0)) + (0 if god_tokens else tokens)
        doc["status"], doc["planning"] = "plan_review", None
        m = doc["plan"].get("master") or {}
        if m.get("ok"):
            s = m["summary"]
            text = (f"Archie modelled a master of {doc['name']}: {s['bodies']} bodies in one coordinate system, "
                    f"{s['interfaces']} interfaces measured from it ({s['bolted']} bolted, {s['faces']} seating faces"
                    + (f", {s['fits']} bore fits" if s["fits"] else "") + ")."
                    + (f" {len(m['errors'])} problem(s) found by the measurement: {m['errors'][0]}" if m["errors"] else "")
                    + (f" {len(m['warnings'])} warning(s)." if m["warnings"] else ""))
        else:
            text = f"Archie could not model a master of {doc['name']} ({m.get('error')}): the fast path lays it out."
        service.emit(root, doc, "plan.master_done", text, service.agent_actor("archie"), ok=bool(m.get("ok")))
        store.save(root, doc)
