"""The orchestrator's platform side: the database, the Studio agent sessions, the Toolbox / company parts (Hex),
assemblies (Fitz) and Gage's review call. Everything is scoped to the program's organisation and runs as the user
who pressed Run (their token attribution and God-mode flags, stored on the program so a restart resumes as them).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from aicad.office import (
    conformance,
    deliverables,
    fake_agents,
    gage,
    interfaces,
    orchestrator,
    planner,
    program_assembly,
    roster,
    service,
    store,
)

log = logging.getLogger("aicad.office.env")
RATE_LIMIT = re.compile(r"\b(rate[ -]?limit|usage limit|too many requests|overloaded|429)\b", re.IGNORECASE)



def _icd_excerpt(doc: dict[str, Any], t: dict[str, Any]) -> str | None:
    """This part's approved interfaces, as the designer got them (Gage judges against what governs)."""
    from aicad.office import icd, interfaces

    if interfaces.has_icd(doc) and t["item_id"] in doc["skeleton"]["items"]:
        return icd.excerpt(doc["skeleton"], doc["icd"], t["item_id"])
    return None


_FITTED: dict[str, dict[str, dict[str, Any]]] = {}  # program -> ticket -> swap result from a batch (CD-032)

class PlatformEnv(orchestrator.Env):
    def __init__(self, root: Path, doc: dict[str, Any]) -> None:
        o = doc.get("orchestrator") or {}
        self.org_id: str = doc["org_id"]
        self.user_id: str = o.get("user_id") or doc.get("created_by")
        self.god_tokens = bool(o.get("god_tokens"))
        self.god_paywall = bool(o.get("god_paywall"))
        self.simulated = fake_agents.enabled()

    def _db(self) -> Any:
        from aicad.platform.db import session_factory

        return session_factory()()

    # ------------------------------------------------------------------ studio
    async def studio_info(self, doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return studio_info(self.org_id, {t["project_id"] for t in doc["tickets"] if t.get("project_id")})

    def _project(self, db: Any, project_id: str) -> Any:
        from aicad.platform.models import Project

        p = db.get(Project, project_id)
        if p is None or p.org_id != self.org_id:
            raise orchestrator.Stop("project not found")
        return p

    async def ensure_project(self, root: Path, pid: str, tid: str) -> str:
        from aicad.platform.models import Project
        from aicad.platform.routers.projects import workspace_for
        from aicad.platform.services import audit

        db = self._db()
        try:
            with store.lock(pid):
                doc = store.load(root, pid)
                if doc is None:
                    raise orchestrator.Stop("program deleted")
                t = service.ticket(doc, tid)
                p = db.get(Project, t["project_id"]) if t.get("project_id") else None
                if p is not None and p.org_id == self.org_id:
                    return str(p.id)
                p = Project(org_id=self.org_id, name=f"{doc['name']} · {t['title']}"[:120],
                            description=t["brief"][:2000], created_by=self.user_id)
                db.add(p)
                db.flush()
                workspace_for(p).mkdir(parents=True, exist_ok=True)
                audit(db, "project.created", None, self.org_id, target=p.id, name=p.name, office_program=pid)
                db.commit()
                t["project_id"] = p.id
                service.emit(root, doc, "ticket.started", f"{roster.agent(t['specialist'])['name']} opened "
                             f"{service._label(t)} as a Design Studio part.", service.agent_actor(t["specialist"]),
                             tid, project_id=p.id)
                store.save(root, doc)
                return str(p.id)
        finally:
            db.close()

    async def run_budget(self, doc: dict[str, Any], remaining: int | None) -> tuple[int | None, str | None]:
        from aicad.platform import metering
        from aicad.platform.models import Organization, User

        if self.god_tokens:
            return None, None
        db = self._db()
        try:
            org, user = db.get(Organization, self.org_id), db.get(User, self.user_id)
            if org is None or user is None:
                return None, "balance"
            want = metering.default_budget(db, org)
            # parallel agents share the balance: each run reserves at most its share, so three agents can start
            share = (org.token_balance - metering.reserved(self.org_id)) // max(1, int(doc.get("concurrency") or 1))
            want = min(want, max(metering.BUDGET_MIN, share))
            if remaining is not None:
                want = min(want, max(metering.BUDGET_MIN, remaining))
            budget, why = metering.run_budget(db, org, user, want)
            if budget is None:
                return None, "capacity" if why and "Another design run" in why else "balance"
            return budget, None
        finally:
            db.close()

    def _session(self, p: Any) -> Any:
        from aicad.platform.routers.projects import session_for

        return session_for(p, self.user_id, self.god_tokens,
                           fake_agents.FakeClient if self.simulated else None)

    async def design(self, project_id: str, prompt: str, shown: str, budget: int | None,
                     on_event: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        from aicad.platform import metering
        from aicad.platform.db import utcnow
        from aicad.platform.models import AgentRun, Organization
        from aicad.platform.routers.projects import latest_revision, workspace_for

        db = self._db()
        try:
            p = self._project(db, project_id)
            s = self._session(p)
            ws = workspace_for(p)
            waited = 0
            while s.busy and waited < 600:  # someone is using this part's Studio chat: wait for it
                await asyncio.sleep(1)
                waited += 1
            if s.busy:
                return {"rate_limited": False, "interrupted": True}
            org = db.get(Organization, self.org_id)
            kind = "change" if p.builds else "new"
            est = metering.estimate(db, org, kind, len(prompt))
            run = AgentRun(org_id=self.org_id, project_id=p.id, user_id=self.user_id, kind=kind,
                           template=p.template, brief_chars=len(prompt), budget_tokens=budget,
                           est_tokens=est["typical"], est_high=est["high"])
            db.add(run)
            p.updated_at = utcnow()
            db.commit()
            run_id = run.id
        finally:
            db.close()
        if budget is not None:
            metering.reserve(self.org_id, run_id, budget)
        s.run_id = run_id
        s.run_budget_usd = budget * metering.USD_PER_TOKEN if budget is not None else None
        s.turn_meta = {"rev_before": latest_revision(ws), "attachments": [], "run_id": run_id,
                       "budget_tokens": budget, "mode": "build"}
        s.brief_approved = True  # the ticket brief was approved at the program's brief gate (CAD-028 skip path)
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        s.subscribers.add(q)
        out: dict[str, Any] = {"rate_limited": False, "interrupted": False, "tokens": 0, "subtype": None}

        def handle(ev: dict[str, Any]) -> None:
            if ev.get("type") in ("text", "error") and RATE_LIMIT.search(str(ev.get("text") or "")):
                out["rate_limited"] = True
            if ev.get("type") == "result":
                out["subtype"] = ev.get("subtype")
                out["tokens"] = int(ev.get("tokens_charged") or 0)
            try:
                on_event(ev)
            except Exception:
                log.exception("progress update failed")

        task = asyncio.create_task(s.send(prompt, shown=shown, mode="build"))
        try:
            while not task.done() or not q.empty():
                try:
                    handle(await asyncio.wait_for(q.get(), 0.25))
                except TimeoutError:
                    pass
            await task
        except RuntimeError:  # the session became busy between the check and the send
            out["interrupted"] = True
        finally:
            s.subscribers.discard(q)
            if not task.done():  # the orchestrator was cancelled (shutdown): stop the turn too
                task.cancel()
        out["interrupted"] = out["interrupted"] or out["subtype"] == "stopped"
        return out

    async def design_direct(self, project_id: str, script: str, note: str) -> dict[str, Any]:
        """A model script written without AI (``office.direct``), built exactly as the design agent's build tool
        builds one (``tools.build_handler``: CHK-02..05, topology and the render now; exports, CHK-07 and CHK-08 on the
        same warm worker in the background), then awaited until every check has run. The build becomes the project's
        next revision; nothing is metered (no model call)."""
        import time

        from aicad.agent import tools
        from aicad.agent.deferred import read_status
        from aicad.agent.runner import is_verified
        from aicad.platform.db import utcnow
        from aicad.platform.models import User
        from aicad.platform.plain import build_error
        from aicad.platform.routers.projects import (
            _complete_revision,
            _snapshot,
            _status_summary,
            schedule_dims,
            wait_finalized,
            workspace_for,
        )
        from aicad.platform.services import notify_revision

        db = self._db()
        try:
            p = self._project(db, project_id)
            s = self._session(p)
            ws = workspace_for(p)
        finally:
            db.close()
        waited = 0
        while s.busy and waited < 600:  # someone is using this part's Studio chat: wait for it
            await asyncio.sleep(1)
            waited += 1
        if s.busy:
            return {"ok": False, "error": "the part's Studio chat is busy"}
        s.busy = True  # the Studio chat waits while the part is built (as for an agent turn)
        s.publish({"type": "busy", "value": True})
        vid = f"direct-{time.time_ns()}"
        t0 = time.perf_counter()
        ok = False
        try:
            await wait_finalized(project_id)
            ws.mkdir(parents=True, exist_ok=True)
            (ws / "model.py").write_text(script, encoding="utf-8")
            s.publish({"type": "text", "text": note})
            s.publish({"type": "tool", "id": vid, "name": "build", "brief": "Building from the interface spec"})
            out = await tools.build_handler(ws, ws / "out", s.worker_key, s.deferred)({"script": "model.py"})
            build_s = round(time.perf_counter() - t0, 2)
            st = read_status(ws / "out") or {}
            db = self._db()
            try:
                p = self._project(db, project_id)
                if st.get("build_id"):
                    p.last_status = _status_summary(st)
                    p.builds += 1
                    p.updated_at = utcnow()
                    who = db.get(User, self.user_id)
                    rev = _snapshot(p, ws, cause=note, kind="interface", by=who.name if who else None)
                    if rev:
                        notify_revision(db, p, rev, who, note)
                        if st.get("exports_pending"):
                            s.deferred.when_verified(st.get("build_id"), _complete_revision(ws, rev))
                db.commit()
            finally:
                db.close()
            if out.get("is_error") or st.get("error"):
                return {"ok": False, "error": build_error(st.get("error"), st.get("checks")), "build_s": build_s}
            final = await s.deferred.settle() or st  # CHK-07 round trip and CHK-08 repeatability
            checks_s = round(time.perf_counter() - t0 - build_s, 2)
            ok = is_verified(final)
            db = self._db()
            try:
                p = self._project(db, project_id)
                p.last_status = _status_summary(final)
                db.commit()
                schedule_dims(p, ws)  # the viewport dimensions of the editable parameters (no AI)
            finally:
                db.close()
            return {"ok": ok, "build_s": build_s, "checks_s": checks_s,
                    "error": None if ok else build_error(final.get("error"), final.get("checks"))}
        except Exception as e:  # a worker failure: the design agent takes the ticket as before
            log.exception("direct build failed")
            return {"ok": False, "error": str(e) or type(e).__name__}
        finally:
            s.busy = False
            s.publish({"type": "tool_result", "id": vid, "build": False, "is_error": not ok,
                       "brief": "Built and verified" if ok else "The build did not pass its checks"})
            s.publish({"type": "busy", "value": False})

    async def interrupt(self, project_id: str) -> None:
        from aicad.platform.routers.projects import _sessions

        s = _sessions.get(project_id)
        if s is not None and s.busy:
            await s.interrupt()

    async def part_state(self, project_id: str) -> dict[str, Any]:
        from aicad.platform.routers.projects import workspace_for

        db = self._db()
        try:
            p = self._project(db, project_id)
            ws = workspace_for(p)
            builds = p.builds
        finally:
            db.close()
        try:
            st = json.loads((ws / "out" / "status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        try:
            src = (ws / "model.py").read_text(encoding="utf-8")
        except OSError:
            src = ""
        return {"builds": builds, "ok": st.get("ok") if builds else None, "checks": st.get("checks") or [],
                "bbox": (st.get("fingerprint") or {}).get("bbox"), "params": st.get("params") or {},
                "source": src, "error": st.get("error")}

    # ------------------------------------------------------------------ Hex
    def _candidates(self, doc: dict[str, Any]) -> list[dict[str, Any]]:
        from aicad.platform.models import Project
        from aicad.platform.routers.projects import workspace_for

        own = {t.get("project_id") for t in doc["tickets"]}
        db = self._db()
        try:
            rows = db.scalars(select(Project).where(Project.org_id == self.org_id, Project.archived.is_(False))).all()
            out = []
            for p in rows:
                if p.id in own or not (p.last_status or {}).get("ok"):
                    continue
                if not (workspace_for(p) / "out" / "part.step").is_file():
                    continue
                out.append({"id": p.id, "name": p.name, "description": p.description or ""})
            return out
        finally:
            db.close()

    async def hex_lookup(self, doc: dict[str, Any], t: dict[str, Any]) -> dict[str, Any] | None:
        return hex_lookup(doc, t, self._candidates(doc))

    # ------------------------------------------------------------------ Gage's review note
    async def review_ai(self, doc: dict[str, Any], t: dict[str, Any], state: dict[str, Any],
                        budget: int | None, previous: list[str] | None = None) -> dict[str, Any] | None:
        from aicad.platform import metering
        from aicad.platform.models import Organization, User
        from aicad.platform.services import debit, track

        db = self._db()
        try:
            org = db.get(Organization, self.org_id)
            cap = gage.REVIEW_MAX_TOKENS if budget is None else min(gage.REVIEW_MAX_TOKENS, budget)
            if not self.god_tokens:
                cap = min(cap, max(0, (org.token_balance if org else 0) - metering.reserved(self.org_id)))
                if cap < 1:
                    return None
        finally:
            db.close()
        fn = fake_agents.fake_review if self.simulated else gage.run_review
        try:
            text, usd = await fn(store.program_dir(store.org_root(_data_dir(), self.org_id), doc["id"]) / "gage",
                                 gage.review_prompt(t, state, _icd_excerpt(doc, t), previous),
                                 None if self.god_tokens else cap * metering.USD_PER_TOKEN)
        except Exception:
            log.exception("Gage review note failed")
            return None
        r = gage.parse_review(text)
        tokens = min(cap, metering.tokens_for_usd(usd)) if usd else 0
        db = self._db()
        try:
            org, user = db.get(Organization, self.org_id), db.get(User, self.user_id)
            if usd and org is not None and not self.god_tokens:
                debit(db, org, tokens, "usage", f"Design Office · Gage review of {t['title']}", user, ref=doc["id"])
            track(db, "office_gage_review", user, self.org_id, tokens=tokens, verdict=(r or {}).get("verdict"))
            db.commit()
        finally:
            db.close()
        if r is None:
            return {"verdict": None, "findings": [], "note": None, "tokens": 0 if self.god_tokens else tokens}
        return {**r, "tokens": 0 if self.god_tokens else tokens}

    # ------------------------------------------------------------------ Phase 4: ICD, placeholders, swap-in
    async def real_part(self, project_id: str) -> str:
        """The project's verified build as a part snapshot (the same one Fitz assembles)."""
        from aicad.assembly import AssemblyInputError
        from aicad.assembly import service as aservice
        from aicad.platform.models import Project
        from aicad.platform.routers.mod_assembly import _model_rev, _status
        from aicad.platform.routers.projects import wait_finalized, workspace_for

        db = self._db()
        try:
            pr = db.get(Project, project_id)
            if pr is None or pr.org_id != self.org_id:
                raise AssemblyInputError("A part of this program is no longer in the workspace.")
            ws, pname = workspace_for(pr), pr.name
        finally:
            db.close()
        await wait_finalized(project_id)
        st = _status(ws)
        return await aservice.ensure_project_part(_aroot(self.org_id), self.org_id, project_id, pname, ws, st,
                                                  _model_rev(ws, st.get("build_id")))

    async def conformance(self, doc: dict[str, Any], t: dict[str, Any]) -> dict[str, Any] | None:
        from aicad.assembly import AssemblyInputError
        from aicad.assembly import store as astore
        from aicad.assembly.service import WorkerError

        if not t.get("project_id"):
            return None
        try:
            key = await self.real_part(t["project_id"])
        except (AssemblyInputError, WorkerError) as e:
            return {"version": doc["icd"]["version"], "ok": False, "interfaces": [],
                    "envelope": {"feature": "envelope", "spec": "a verified build", "measured": str(e), "ok": False}}
        aroot = _aroot(self.org_id)
        info = (astore.part(aroot, key) or {}).get("info") or {}
        return {**conformance.measure(doc["skeleton"], doc["icd"], t["item_id"], info, astore.refs(aroot, key)),
                "part_key": key}

    async def swap_in(self, root: Path, pid: str, tid: str) -> dict[str, Any]:
        doc = store.load(root, pid)
        if doc is None:
            raise orchestrator.Stop("program deleted")
        t = service.ticket(doc, tid)
        tb_gear = (t.get("reuse") or {}).get("source") == "toolbox" and (t.get("reuse") or {}).get("code") == "spur_gear" \
            and t["item_id"] in ((doc.get("skeleton") or {}).get("items") or {})
        if not t.get("project_id") and not tb_gear:
            return {"skipped": "Nothing to swap in: the part has no Design Studio build."}
        if tb_gear:  # a designed gear Hex took from the Toolbox (sized to the ICD): it goes in like a built part. The
            # Toolbox gear runs from Z 0 to its face width with a tooth on +X: its ICD frame is that, moved down B / 2
            from aicad.assembly import service as aservice
            from aicad.office import frames as rigid

            r = t["reuse"]
            key = await aservice.ensure_toolbox_part(_aroot(self.org_id), self.org_id, "spur_gear", r["params"])
            t["icd_check"] = {**(t.get("icd_check") or {}), "part_key": key,
                              "frame": rigid.frame(rigid.IDENT, [0.0, 0.0, -float(r["params"]["B"]) / 2])}
            with store.lock(pid):
                d = store.load(root, pid)
                if d is not None:
                    service.ticket(d, tid)["icd_check"] = t["icd_check"]
                    store.save(root, d)
        key = (t.get("icd_check") or {}).get("part_key") or await self.real_part(t["project_id"])
        if (doc.get("assembly") or {}).get("status") == "ready" and tid not in _FITTED.get(pid, {}):
            # the exact checks run here, outside the program lock, into the pair cache (ASM-023): the swap under the
            # lock finds them there, so swaps and integrations of other levels don't queue behind the geometry
            pre = {x["item_id"]: ((x.get("icd_check") or {}).get("part_key"), (x.get("icd_check") or {}).get("frame"))
                   for x in doc["tickets"] if x["item_id"] in doc["skeleton"]["items"] and (x["id"] == tid or (
                       orchestrator.run_of(x).get("next") == "fit" and x.get("project_id")))}
            pre[t["item_id"]] = (key, (t.get("icd_check") or {}).get("frame"))
            try:
                await program_assembly.prewarm_swap(
                    _aroot(self.org_id), self.org_id, doc, {i: k for i, (k, _) in pre.items() if k},
                    {i: fr for i, (_, fr) in pre.items() if fr and not fr.get("identity")})
            except Exception:
                log.warning("swap prewarm failed", exc_info=True)
        async with program_assembly.lock(pid):
            ready = _FITTED.setdefault(pid, {}).pop(tid, None)
            if ready is not None:  # swapped in with an earlier batch while this ticket waited (CD-032)
                return ready
            doc = store.load(root, pid)
            if doc is None:
                raise orchestrator.Stop("program deleted")
            if (doc.get("assembly") or {}).get("status") != "ready":
                return {"skipped": "Fitz will place this part when the program assembly is built."}
            # one assembly update for every approved part waiting to go in: one rebuild, one clash check
            batch = {t["item_id"]: (tid, key, (t.get("icd_check") or {}).get("frame"))}
            for x in doc["tickets"]:
                xk = (x.get("icd_check") or {}).get("part_key")
                if x["id"] != tid and orchestrator.run_of(x).get("next") == "fit" and xk and x.get("project_id") \
                        and x["item_id"] in doc["skeleton"]["items"] and x["item_id"] not in batch:
                    batch[x["item_id"]] = (x["id"], xk, (x.get("icd_check") or {}).get("frame"))
            frames = {i: fr for i, (_, _, fr) in batch.items() if fr and not fr.get("identity")}
            try:
                state = await program_assembly.swap(_aroot(self.org_id), self.org_id, doc,
                                                    {i: k for i, (_, k, _) in batch.items()}, frames=frames or None)
            except Exception as e:
                log.exception("swap-in failed")
                return {"error": f"Fitz couldn't swap the part in: {e}"}
            names = [service.ticket(doc, x)["title"] for x, _, _ in batch.values()]
            save_assembly(root, pid, state, f"Fitz swapped {', '.join(names)} into the program assembly.", event=False)
            last = state.get("last") or {}
            out: dict[str, dict[str, Any]] = {}
            for item, (xt, _, _) in batch.items():
                mine = (last.get("by_item") or {}).get(item, last.get("clashes") if len(batch) == 1 else [])
                out[xt] = {"last": {**last, "clashes": mine or []}, "problems": last.get("problems") or [],
                           "mates": state.get("mates"), "batch": len(batch)}
            own = out.pop(tid)
            _FITTED[pid].update(out)
        return own

    async def decide_cr(self, root: Path, pid: str, cid: str) -> dict[str, Any]:
        return await decide_cr(root, pid, cid, self)

    async def cr_review(self, doc: dict[str, Any], c: dict[str, Any], why: str) -> dict[str, Any] | None:
        """Archie's AI note on a change request (Archie-planned programs only). Metered like Gage's note."""
        from aicad.platform import metering
        from aicad.platform.models import Organization, User
        from aicad.platform.services import debit, track

        if doc.get("planner") != "archie":
            return None
        db = self._db()
        try:
            org = db.get(Organization, self.org_id)
            cap = planner.CR_MAX_TOKENS
            if not self.god_tokens:
                cap = min(cap, max(0, (org.token_balance if org else 0) - metering.reserved(self.org_id)))
                if cap < 1:
                    return None
        finally:
            db.close()
        fn = fake_agents.fake_cr_review if self.simulated else planner.run_cr_review
        try:
            text, usd = await fn(store.program_dir(store.org_root(_data_dir(), self.org_id), doc["id"]) / "archie",
                                 planner.cr_prompt(doc, c, why), None if self.god_tokens else cap * metering.USD_PER_TOKEN)
        except Exception:
            log.exception("Archie change-request review failed")
            return None
        r = planner.parse_cr_decision(text)
        tokens = min(cap, metering.tokens_for_usd(usd)) if usd else 0
        db = self._db()
        try:
            org, user = db.get(Organization, self.org_id), db.get(User, self.user_id)
            if usd and org is not None and not self.god_tokens:
                debit(db, org, tokens, "usage", f"Design Office · Archie on {c['id']}", user, ref=doc["id"])
            track(db, "office_cr_review", user, self.org_id, tokens=tokens, decision=(r or {}).get("decision"))
            db.commit()
        finally:
            db.close()
        return None if r is None else {**r, "tokens": 0 if self.god_tokens else tokens}

    # ------------------------------------------------------------------ Phase 5: Ortho and Smithy
    def _module(self, code: str) -> bool:
        from aicad.platform.models import Organization
        from aicad.platform.services import org_modules

        db = self._db()
        try:
            org = db.get(Organization, self.org_id)
            return org is not None and (code in org_modules(db, org) or self.god_paywall)
        finally:
            db.close()

    def _user_name(self) -> str:
        from aicad.platform.models import User

        db = self._db()
        try:
            u = db.get(User, self.user_id)
            return (u.name or u.email) if u else "Design Office"
        finally:
            db.close()

    async def drawing(self, doc: dict[str, Any], t: dict[str, Any], project_id: str) -> dict[str, Any]:
        from fastapi import HTTPException

        from aicad.platform.routers import mod_drawings as md
        from aicad.platform.routers.projects import workspace_for

        if not self._module("drawings"):
            return {"ok": False, "error": "Drawing Studio isn't included in your plan: unlock it to get drawings."}
        db = self._db()
        try:
            p = self._project(db, project_id)
            db.expunge(p)
        finally:
            db.close()
        ws = workspace_for(p)
        spec = {}
        if interfaces.has_icd(doc) and t["item_id"] in (doc.get("skeleton") or {}).get("items", {}):
            spec = deliverables.icd_spec(doc["skeleton"], doc["icd"], t["item_id"],
                                         (t.get("icd_check") or {}).get("frame"))
        d = ws / "drawings"
        d.mkdir(parents=True, exist_ok=True)
        (d / "spec.json").write_text(json.dumps(spec, indent=1, sort_keys=True), encoding="utf-8")
        meta = md._meta(p, ws, self._user_name(), md.local_date(None, None))
        old = md._record(ws) or {}
        base = old.get("options") or {}
        # CD-039: a sheet whose consistency check (CHK-12) fails is laid out again, simpler each time (no section
        # view, then three views, then two); the first layout that passes is kept
        tries = [base, {**base, "section": None}, {**base, "section": None, "views": ["front", "top", "right"]},
                 {**base, "section": None, "views": ["front", "top"]}]
        res = None
        for k, opts in enumerate(tries):
            try:
                res = await md._generate(p, ws, opts, meta, md._edits(ws), d)
            except HTTPException as e:
                if res is None:
                    return {"ok": False, "error": e.detail if isinstance(e.detail, str) else "The drawing failed."}
                break
            except Exception as e:
                log.exception("drawing failed")
                if res is None:
                    return {"ok": False, "error": f"The drawing failed: {e}"}
                break
            if res["result"]["check"]["passed"] or k == len(tries) - 1:
                break
        assert res is not None
        rec = res["result"]
        dims = rec.get("dimensions") or []
        return {"ok": True, "check_passed": bool(rec["check"]["passed"]), "problems": rec["check"].get("problems") or [],
                "scale": rec["sheet"]["scale"], "size": rec["sheet"]["size"], "model_rev": rec.get("model_rev"),
                "spec_dims": sum(1 for x in dims if x["tag"] == "spec"),
                "inferred_dims": sum(1 for x in dims if x["tag"] == "inferred"),
                "icd_dims": len((rec.get("icd") or {}).get("mapped") or []),
                "icd_offered": len((rec.get("icd") or {}).get("offered") or []),
                "callouts": len(rec.get("callouts") or [])}

    async def assembly_drawing(self, root: Path, pid: str, rev: str | None = None,
                               dest: Path | None = None) -> dict[str, Any]:
        return await assembly_drawing(root, pid, self.org_id, self._user_name(), rev, dest,
                                      self._module("drawings"))

    async def dfm(self, doc: dict[str, Any], t: dict[str, Any], project_id: str) -> dict[str, Any]:
        from aicad.manufacturing import shop as shop_mod
        from aicad.manufacturing.analyze import Inputs, analyse_workspace
        from aicad.platform.config import get_settings
        from aicad.platform.routers import mod_manufacturing as mm
        from aicad.platform.routers.projects import wait_finalized, workspace_for

        if not self._module("manufacturing"):
            return {"error": "The Manufacturing Advisor isn't included in your plan."}
        db = self._db()
        try:
            p = self._project(db, project_id)
            ws = workspace_for(p)
        finally:
            db.close()
        await wait_finalized(project_id)
        if not (ws / "out" / "part.step").is_file():
            return {"error": "No verified build to analyse."}
        org_dir = (get_settings().workspaces_dir.resolve() / self.org_id).resolve()
        prof, _ = shop_mod.load(org_dir)
        qty = max(10, int(t.get("qty") or 1))

        def run() -> dict[str, Any]:
            with mm._lock:
                return analyse_workspace(ws, prof, Inputs(quantity=qty), mm._project_material(ws))
        try:
            return {"analysis": await asyncio.to_thread(run)}
        except Exception as e:
            log.exception("DFM failed")
            return {"error": f"The analysis failed: {e}"}

    # ------------------------------------------------------------------ Fitz
    async def integrate(self, root: Path, pid: str, tid: str) -> dict[str, Any]:
        from aicad.assembly import AssemblyInputError, fitz, locks
        from aicad.assembly import service as aservice
        from aicad.assembly import store as astore
        from aicad.platform.models import Organization, Project
        from aicad.platform.routers.mod_assembly import _model_rev, _status
        from aicad.platform.routers.projects import wait_finalized, workspace_for
        from aicad.platform.services import org_modules

        doc = store.load(root, pid)
        if doc is None:
            raise orchestrator.Stop("program deleted")
        t = service.ticket(doc, tid)
        db = self._db()
        try:
            org = db.get(Organization, self.org_id)
            if org is None or ("assembly" not in org_modules(db, org) and not self.god_paywall):
                return {"blocked": "Assembly Studio isn't included in your plan, so Fitz can't assemble this. Unlock "
                                   "the add-on, then retry."}
        finally:
            db.close()
        if (doc.get("assembly") or {}).get("status") == "ready":
            return await self._integrate_program(root, pid, tid)
        kids = children(doc, t)
        aroot = astore.org_root(_data_dir(), self.org_id)
        item = next((i for i in doc["items"] if i["id"] == t["item_id"]), {"name": t["title"]})
        adoc = astore.load(aroot, t["assembly_id"]) if t.get("assembly_id") else None
        if adoc is None:
            adoc = astore.new_doc(f"{doc['name']} · {item['name']}"[:120], self.org_id, self.user_id, None)
            astore.save(aroot, adoc)
        present = {i["source"].get("project_id") for i in adoc["instances"] if i["source"].get("kind") == "project"}
        items: list[dict[str, Any]] = []
        for k in kids:
            r = k.get("reuse") or {}
            base = {"id": f"o{len(items) + 1}", "qty": int(k.get("qty") or 1), "qty_explicit": True, "enabled": True,
                    "target": None, "target_name": None, "mount": False, "alternatives": [], "text": k["title"]}
            if r.get("source") == "toolbox":
                items.append({**base, "source": "toolbox", "code": r["code"], "params": r.get("params"),
                              "kind": r.get("kind") or "part", "title": r.get("title") or k["title"],
                              **({"fasten": r["fasten"]} if r.get("fasten") else {})})
            else:
                proj = r.get("project_id") if r.get("source") == "project" else k.get("project_id")
                if not proj or proj in present:
                    continue
                items.append({**base, "source": "project", "project_id": proj, "kind": "part", "title": k["title"]})
        names = aservice.display_names(adoc)
        for it in items:
            fitz._intend(aroot, adoc, it, items, names)
        items = sorted(items, key=lambda x: fitz.ORDER[x["action"]])  # stable: plan order within an action
        for n, it in enumerate(items, start=1):
            it["order"] = n

        async def project_part(project_id: str) -> str:
            dbx = self._db()
            try:
                p = dbx.get(Project, project_id)
                if p is None or p.org_id != self.org_id:
                    raise AssemblyInputError("A part of this program is no longer in the workspace.")
                ws, pname = workspace_for(p), p.name
            finally:
                dbx.close()
            await wait_finalized(project_id)
            st = _status(ws)
            return await aservice.ensure_project_part(aroot, self.org_id, project_id, pname, ws, st,
                                                      _model_rev(ws, st.get("build_id")))

        try:
            async with locks.hold(adoc["id"], locks.OFFICE):
                adoc = astore.load(aroot, adoc["id"]) or adoc
                res = await fitz.execute(aroot, self.org_id, adoc, items, project_part)
                astore.save(aroot, adoc)
        except (AssemblyInputError, aservice.WorkerError) as e:
            return {"blocked": f"Fitz couldn't assemble this: {e}", "assembly_id": adoc["id"]}
        return {**res, "assembly_id": adoc["id"], "children": [k["id"] for k in kids]}

    async def look_level(self, root: Path, pid: str, tid: str, res: dict[str, Any]) -> dict[str, Any] | None:
        """PD-73: Fitz looks at the level he just integrated (quick placement checks + the visual check)."""
        from aicad.office import visual_office

        doc = store.load(root, pid)
        if doc is None:
            return None
        t = service.ticket(doc, tid)
        aid = res.get("assembly_id") or (((doc.get("assembly") or {}).get("final")) if t["item_id"] == "root"
                                         else t.get("assembly_id"))
        if not aid:
            return None
        return await visual_office.level_look(root, pid, tid, _aroot(self.org_id), aid, org_id=self.org_id,
                                              user_id=self.user_id, god=self.god_tokens,
                                              mode="simulated" if self.simulated else "ai")

    async def _integrate_program(self, root: Path, pid: str, tid: str) -> dict[str, Any]:
        """Integration with an ICD: the level's assembly already holds its parts (placeholders swapped for the real
        parts); Fitz fits the level's fasteners into its bolted joints and re-checks. Nested: the final assembly
        holds the sub-assemblies."""
        from aicad.assembly import AssemblyInputError
        from aicad.assembly.service import WorkerError

        async with program_assembly.lock(pid):
            doc = store.load(root, pid)
            if doc is None:
                raise orchestrator.Stop("program deleted")
            t = service.ticket(doc, tid)
            kids = children(doc, t) if t["item_id"] != "root" else [
                k for k in doc["tickets"] if k["id"] in (t.get("depends_on") or [])]
            ph = [k["title"] for k in kids if k["kind"] == "part" and
                  ((doc["assembly"].get("parts") or {}).get(k["item_id"]) or {}).get("kind") == "placeholder"]
            if ph and t["item_id"] != "root":
                waiting = [k["id"] for k in kids if k["kind"] == "part" and k["column"] in service.DONE_COLUMNS and
                           ((doc["assembly"].get("parts") or {}).get(k["item_id"]) or {}).get("kind") == "placeholder"]
                if waiting:  # approved but not fitted yet: fit them first, then assemble (CD-035)
                    return {"wait_fit": waiting, "why": f"Waiting for Fitz to swap the real {ph[0]}"
                            + (f" and {len(ph) - 1} more" if len(ph) > 1 else "") + " in for the placeholders"}
                return {"blocked": f"Fitz is still waiting for the real {ph[0]}: it has not been swapped in for its "
                                   "placeholder. Retry once it is approved."}
            std = [k for k in kids if k["kind"] == "standard"]
            # a sub-assembly of bought-out parts only (a fastener kit) has no layout of its own: its parts are fitted
            # where the joints are, as every other level is integrated (CD-034)
            designed = {s["id"] for s in program_assembly.subs_of(doc)}
            kit_subs = [i["id"] for i in doc["items"] if i["kind"] == "subassembly" and i["id"] not in designed]
            if t["item_id"] in kit_subs:
                n = len(std)
                return {"summary": f"{t['title'].removeprefix('Assemble ')} is a kit of {n} bought-out part"
                                   f"{'s' if n != 1 else ''}: Fitz fits them at the joints as each sub-assembly and the "
                                   "final assembly are integrated", "clashes": [], "log": [], "inserted": 0,
                        "children": [k["id"] for k in kids]}
            kit = [{**k, "_kit": True} for k in doc["tickets"] if k["kind"] == "standard" and k["item_id"] != t["item_id"]
                   and k["column"] in service.DONE_COLUMNS and any(
                       x["id"] == k["item_id"] and x.get("parent_id") in kit_subs for x in doc["items"])]
            std = std + kit
            try:
                res = await program_assembly.integrate(_aroot(self.org_id), self.org_id, doc, t["item_id"], std)
            except WorkerError as e:  # a timeout or a worker crash: try again (CD-036)
                return {"error": f"Fitz couldn't integrate this: {e}"}
            except AssemblyInputError as e:
                return {"blocked": f"Fitz couldn't integrate this: {e}"}
            if res.get("blocked"):
                return res
            state = {**doc["assembly"], "at": store.now(), "summary": res.get("program_summary")
                     or doc["assembly"].get("summary")}
            if t["item_id"] == "root":
                state["clashes"] = res["clashes"]
                state["check"] = {"status": "running", "at": store.now()}
            save_assembly(root, pid, state, None, event=False)
        if t["item_id"] == "root":  # PD-71: the whole-program clash check, advisory, after and outside the lock
            task = asyncio.get_running_loop().create_task(advisory_check(root, pid, tid, self.org_id))
            _ADVISORY.add(task)
            task.add_done_callback(_ADVISORY.discard)
        return {**res, "children": [k["id"] for k in kids]}


# ---------------------------------------------------------------------------- shared helpers
def _data_dir() -> Path:
    from aicad.platform.config import get_settings

    return get_settings().data_dir


def studio_info(org_id: str, ids: set[str]) -> dict[str, dict[str, Any]]:
    """Build state and tokens of the program's Studio projects (the board's checks badge and spend)."""
    from aicad.platform.db import session_factory
    from aicad.platform.models import AgentRun, Project

    ids = {i for i in ids if i}
    if not ids:
        return {}
    db = session_factory()()
    try:
        rows = db.scalars(select(Project).where(Project.id.in_(ids), Project.org_id == org_id)).all()
        spent = dict(db.execute(select(AgentRun.project_id, func.coalesce(func.sum(AgentRun.tokens), 0))
                                .where(AgentRun.project_id.in_(ids), AgentRun.org_id == org_id)
                                .group_by(AgentRun.project_id)).all())
        return {p.id: {"builds": p.builds, "ok": (p.last_status or {}).get("ok") if p.builds else None,
                       "tokens": int(spent.get(p.id) or 0)} for p in rows}
    finally:
        db.close()


def children(doc: dict[str, Any], t: dict[str, Any]) -> list[dict[str, Any]]:
    """The parts an integration ticket assembles: its sub-assembly's parts, or every part for the final assembly
    (sub-assemblies are flattened: an assembly can't hold another assembly yet)."""
    items = {i["id"]: i for i in doc["items"]}
    if t["item_id"] == "root":
        return [k for k in doc["tickets"] if k["kind"] != "integration"]
    return [k for k in doc["tickets"] if k["kind"] != "integration"
            and (items.get(k["item_id"]) or {}).get("parent_id") == t["item_id"]]


TOOLBOX_FOR_PARTS = {"fastener", "dowel", "gear"}


def hex_lookup(doc: dict[str, Any], t: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Reuse before design (zero tokens). Standard tickets: the Toolbox reading of the item, then your parts.
    Designed parts only reuse what is unambiguous: a fully specified Toolbox gear / fastener / dowel, or one of your
    verified parts with exactly this name."""
    from aicad import toolbox
    from aicad.assembly import librarian

    item = next((i for i in doc["items"] if i["id"] == t["item_id"]), {})
    text = f"{t['title']} {item.get('description') or ''}".strip()
    standard = t["kind"] == "standard"
    if standard and interfaces.has_icd(doc):  # a bearing / dowel the ICD sized and placed: take exactly that
        from aicad.office import icd

        seat = icd.seated(doc["icd"]["interfaces"], t["item_id"])
        if seat:
            return {"source": "toolbox", "code": seat["code"], "params": toolbox.normalize(seat["code"], seat["params"]),
                    "title": seat["title"], "standard": seat["standard"], "kind": seat["code"], "confidence": "high",
                    "read": True, "found": f"Hex found {seat['title']} in the Toolbox, sized by the ICD "
                                           f"({seat['interface']})"}
    tb = librarian.read_toolbox(text) or (librarian.read_toolbox(f"{t['title']} {item['toolbox']}")
                                          if standard and item.get("toolbox") else None)
    if tb is not None:
        ok = standard or (tb.get("kind") in TOOLBOX_FOR_PARTS and tb.get("confidence") == "high")
        if ok:
            params = tb.get("params")
            note = ""
            if params is None:
                params = toolbox.normalize(tb["code"], {})
                tb = {**tb, "title": toolbox.spec(tb["code"]).title(params)}
            it = ((doc.get("skeleton") or {}).get("items") or {}).get(t["item_id"]) or {}
            if not standard and tb["code"] == "spur_gear" and it.get("role") == "gear" and interfaces.has_icd(doc):
                from aicad.office import direct, icd

                if direct.enabled(doc) and direct.plan(doc, t)["path"] == "direct":
                    # the interfaces fix the gear: it is built from them (bore, hub keyway, the plan's material, true
                    # involute) in seconds, never swapped for a plain Toolbox gear that drops the keyway and material
                    return None
                if any(f["type"] not in ("hole", "gear", "face") for f in
                       icd.item_features(doc["skeleton"], doc["icd"]["interfaces"], t["item_id"])):
                    return None  # a keyed bore: the Toolbox gear has none, the designer builds it (direct, no AI)
                # a designed gear Hex takes from the Toolbox is made to its ICD: module, teeth, face width, bore
                params = toolbox.normalize("spur_gear", {**params, "M": it["module"], "Z": it["teeth"],
                                                         "B": it["face_width"], **({"BORE": it["bore"]} if it.get("bore") else {})})
                tb = {**tb, "title": toolbox.spec("spur_gear").title(params), "read": True}
            if not tb.get("read") and tb.get("kind") != "fastener":
                note = " (default size: the brief gives none, check it)"
            elif tb.get("kind") == "fastener" and not (tb.get("fasten") or {}).get("size"):
                note = " (size to suit the holes at assembly)"
            return {"source": "toolbox", "code": tb["code"], "params": params, "title": tb["title"],
                    "standard": tb.get("standard"), "kind": tb.get("kind"), "fasten": tb.get("fasten"),
                    "confidence": tb.get("confidence"), "found": f"Hex found {tb['title']} in the Toolbox{note}"}
    hits = librarian.find_parts(t["title"], candidates, limit=1)
    if hits and hits[0]["score"] >= (0.67 if standard else 0.99):
        h = hits[0]
        return {"source": "project", "project_id": h["id"], "title": h["name"], "confidence": "high",
                "found": f"Hex found {h['name']} in your parts"}
    return None


# ---------------------------------------------------------------------------- program assembly (shared helpers)
def _aroot(org_id: str) -> Path:
    from aicad.assembly import store as astore

    return astore.org_root(_data_dir(), org_id)


_ADVISORY: set[asyncio.Task[Any]] = set()


async def advisory_check(root: Path, pid: str, tid: str, org_id: str) -> dict[str, Any] | None:
    """Run the advisory whole-program clash check (PD-71) and record it: ``assembly.check`` (the Assembly tab) and a
    note on the final-assembly ticket. Never moves a ticket or blocks the program; a failure is a note too."""
    doc = store.load(root, pid)
    if doc is None:
        return None
    try:
        out = await program_assembly.advisory_check(_aroot(org_id), org_id, doc)
    except Exception as e:
        log.warning("advisory clash check failed", exc_info=True)
        out = {"status": "failed", "clashes": [], "at": store.now(),
               "text": f"Fitz's whole-program clash check didn't finish ({e}). It is advisory: nothing was held up. "
                       "Run Check in Assembly Studio on the final assembly to see clashes."}
    with store.lock(pid):
        d = store.load(root, pid)
        if d is None or not d.get("assembly"):
            return out
        d["assembly"]["check"] = {k: v for k, v in out.items() if k != "clashes"} | {"count": len(out["clashes"])}
        if out["status"] == "done":
            d["assembly"]["clashes"] = out["clashes"]
        t = next((x for x in d["tickets"] if x["id"] == tid), None)
        if t is not None:
            service.comment(root, d, tid, out["text"], service.agent_actor("fitz"))
            t["comments"][-1]["delivery"] = "stored"
        store.save(root, d)
    return out


def save_assembly(root: Path, pid: str, state: dict[str, Any], text: str | None, event: bool = True,
                  **data: Any) -> None:
    with store.lock(pid):
        doc = store.load(root, pid)
        if doc is None:
            return
        doc["assembly"] = state
        for t in doc["tickets"]:  # integration tickets open the level's document
            if t["kind"] == "integration":
                aid = state.get("final") if t["item_id"] == "root" else (state.get("subs") or {}).get(t["item_id"])
                if aid:
                    t["assembly_id"] = aid
        if event and text:
            service.emit(root, doc, "assembly.updated", text, service.agent_actor("fitz"), **data)
        store.save(root, doc)


def assembly_allowed(org_id: str, god_paywall: bool) -> bool:
    from aicad.platform.db import session_factory
    from aicad.platform.models import Organization
    from aicad.platform.services import org_modules

    db = session_factory()()
    try:
        org = db.get(Organization, org_id)
        return org is not None and ("assembly" in org_modules(db, org) or god_paywall)
    finally:
        db.close()


async def build_program_assembly(root: Path, pid: str, org_id: str, user_id: str, god_paywall: bool = False) -> None:
    """At ICD approval: Fitz assembles the program from placeholders (mates by interface name)."""
    if not assembly_allowed(org_id, god_paywall):
        save_assembly(root, pid, {"status": "unavailable", "summary": "Assembly Studio isn't included in your plan, "
                                  "so the live program assembly can't be built. Unlock the add-on, then rebuild it."},
                      "The live program assembly needs Assembly Studio (not in your plan).")
        return
    async with program_assembly.lock(pid):
        doc = store.load(root, pid)
        if doc is None or not interfaces.has_icd(doc):
            return
        keys = {}
        for t in doc["tickets"]:  # a rebuild keeps real parts already swapped in
            p = ((doc.get("assembly") or {}).get("parts") or {}).get(t["item_id"]) or {}
            if p.get("kind") == "real" and t["column"] in service.DONE_COLUMNS:
                keys[t["item_id"]] = p["key"]
        try:
            state = await program_assembly.build(_aroot(org_id), org_id, user_id, doc, keys)
        except Exception as e:
            log.exception("program assembly build failed")
            save_assembly(root, pid, {**(doc.get("assembly") or {}), "status": "failed",
                                      "summary": f"Fitz couldn't build the program assembly: {e}"},
                          "Fitz couldn't build the program assembly from placeholders.")
            return
        save_assembly(root, pid, state, state["summary"], clashes=len(state["clashes"]))


# ---------------------------------------------------------------------------- deliverables (CD-014)
def _clean(name: str, program: str) -> str:
    from aicad.assembly.service import clean_name

    return clean_name(name).removeprefix(f"{program} · ").strip()


def program_bom(doc: dict[str, Any]) -> dict[str, Any]:
    """The program BOM from its final assembly (what is really in the product) and its tickets (quantities, make /
    buy). Before the program assembly exists: from the tickets alone."""
    from aicad.assembly import service as aservice
    from aicad.assembly import store as astore
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    aroot = _aroot(doc["org_id"])
    state = doc.get("assembly") or {}
    final = astore.load(aroot, state["final"]) if state.get("final") and state.get("status") == "ready" else None
    names = {}
    pids = {t.get("project_id") or (t.get("reuse") or {}).get("project_id") for t in doc["tickets"]} - {None}
    info: dict[str, dict[str, Any]] = {}
    if pids:
        from aicad import materials

        db = session_factory()
        try:
            for p in db.scalars(select(Project).where(Project.id.in_(pids), Project.org_id == doc["org_id"])).all():
                names[p.id] = _clean(p.name, doc["name"])
                try:
                    st = json.loads((workspace_for(p) / "out" / "status.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    st = {}
                m = materials.get(materials.guess(st.get("material")))
                vol = (st.get("fingerprint") or {}).get("volume")
                info[p.id] = {"name": names[p.id], "material": st.get("material"),
                              "mass_g": round(float(vol) * float(m["density_g_cm3"]) / 1000.0, 2) if m and vol else None}
        finally:
            db.close()
    rows = None
    inst_items: dict[str, dict[str, Any]] = {}
    part_projects: dict[str, str] = {}
    if final is not None and final["instances"]:
        parts = aservice._parts(aroot, final)
        b = aservice.bom(aroot, final, names)
        rows = [{**r, "code": parts[r["part_key"]].get("code")} for r in b["rows"]]
        inst_items = {i["id"]: i["office"] for i in final["instances"] if i.get("office")}
        part_projects = {k: p["project_id"] for k, p in parts.items() if p.get("kind") == "project"}
    return deliverables.bom(doc["tickets"], rows, inst_items, part_projects, info)


def session_factory() -> Any:
    from aicad.platform.db import session_factory as sf

    return sf()()


async def assembly_drawing(root: Path, pid: str, org_id: str, user_name: str, rev: str | None = None,
                           dest: Path | None = None, allowed: bool = True) -> dict[str, Any]:
    """Ortho's assembly drawing (DRW-014): the final assembly in an isometric view, the program BOM as a table and
    a balloon per BOM line. Written to the program's ``deliverables/assembly`` folder (or ``dest`` for a release)."""
    from aicad.assembly import store as astore
    from aicad.drawing import worker as dworker
    from aicad.platform.routers.mod_drawings import local_date

    if not allowed:
        return {"ok": False, "error": "Drawing Studio isn't included in your plan: unlock it to get drawings."}
    doc = store.load(root, pid)
    if doc is None:
        return {"ok": False, "error": "Program not found"}
    state = doc.get("assembly") or {}
    aroot = _aroot(org_id)
    final = astore.load(aroot, state["final"]) if state.get("final") else None
    if final is None or not final["instances"]:
        return {"ok": False, "error": "There is no program assembly to draw."}
    b = program_bom(doc)
    nodes = [{"step": str(astore.part_dir(aroot, i["part"]) / "part.step"), "T": i["T"], "inst": i["id"]}
             for i in final["instances"]]
    out = dest or store.program_dir(root, pid) / "deliverables" / "assembly"
    meta = {"title": doc["name"], "drawing_no": f"FW-{doc['key']}-ASM", "drawn_by": user_name,
            "date": local_date(None, None), "rev": rev or "DRAFT",
            "source": f"ICD v{(doc.get('icd') or {}).get('version', '—')} · {len(final['instances'])} instances"}
    try:
        res = await dworker.assembly(org_id, nodes, b["rows"], out, meta)
    except Exception as e:
        log.exception("assembly drawing failed")
        return {"ok": False, "error": f"The assembly drawing failed: {e}"}
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error") or "The assembly drawing failed."}
    return {"ok": True, **res["result"], "bom_rows": len(b["rows"])}


async def decide_cr(root: Path, pid: str, cid: str, env: PlatformEnv | None) -> dict[str, Any]:
    """Archie decides a change request: the deterministic rule, then (Archie-planned programs) an AI note that may
    still reject. On accept the affected placeholders are regenerated in the program assembly."""
    doc = store.load(root, pid)
    if doc is None:
        return {}
    c = interfaces.cr(doc, cid)
    ev = interfaces.evaluate(doc, c)
    ai = None
    if ev["ok"] and env is not None:
        ai = await env.cr_review(doc, c, ev["reason"])
    with store.lock(pid):
        doc = store.load(root, pid)
        if doc is None:
            return {}
        out = interfaces.decide(root, doc, cid, service.agent_actor("archie"), ai)
        store.save(root, doc)
    orchestrator.poke(pid)
    if out["accepted"] and (doc.get("assembly") or {}).get("status") == "ready":
        async with program_assembly.lock(pid):
            doc = store.load(root, pid)
            if doc is not None:
                try:
                    state = await program_assembly.regenerate(_aroot(doc["org_id"]), doc["org_id"], doc, out["items"])
                    save_assembly(root, pid, state, f"Fitz regenerated {len(out['items'])} placeholder"
                                  f"{'s' if len(out['items']) != 1 else ''} for ICD v{doc['icd']['version']} "
                                  f"({cid}): mates re-attached by interface name, {len(state['clashes'])} clashes.")
                except Exception:
                    log.exception("placeholder regeneration failed")
    return {"id": cid, "status": out["cr"]["status"], "accepted": out["accepted"]}
