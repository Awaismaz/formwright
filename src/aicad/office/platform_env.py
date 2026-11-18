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

from aicad.office import fake_agents, gage, orchestrator, roster, service, store

log = logging.getLogger("aicad.office.env")
RATE_LIMIT = re.compile(r"\b(rate[ -]?limit|usage limit|too many requests|overloaded|429)\b", re.IGNORECASE)


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
                        budget: int | None) -> dict[str, Any] | None:
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
                                 gage.review_prompt(t, state), None if self.god_tokens else cap * metering.USD_PER_TOKEN)
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

    # ------------------------------------------------------------------ Fitz
    async def integrate(self, root: Path, pid: str, tid: str) -> dict[str, Any]:
        from aicad.assembly import AssemblyInputError, fitz
        from aicad.assembly import service as aservice
        from aicad.assembly import store as astore
        from aicad.platform.models import Organization, Project
        from aicad.platform.routers.mod_assembly import _lock, _model_rev, _status
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
            async with _lock(adoc["id"]):
                adoc = astore.load(aroot, adoc["id"]) or adoc
                res = await fitz.execute(aroot, self.org_id, adoc, items, project_part)
                astore.save(aroot, adoc)
        except (AssemblyInputError, aservice.WorkerError) as e:
            return {"blocked": f"Fitz couldn't assemble this: {e}", "assembly_id": adoc["id"]}
        return {**res, "assembly_id": adoc["id"], "children": [k["id"] for k in kids]}


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
