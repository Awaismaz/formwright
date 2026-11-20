"""Assembly Studio: the assembly agent's conversation (WORKLIST 51). Same module and access as ``mod_assembly``.

  GET  /api/m/assembly/assemblies/{id}/chat          the conversation, what is running now, design jobs
  POST /api/m/assembly/assemblies/{id}/chat          the engineer says something: the agent's turn starts
  POST /api/m/assembly/assemblies/{id}/chat/reset    a new conversation (the old one is archived)

A turn runs in the background (``agent.run_turn``); the page polls GET while ``busy`` is set, which also carries the
step being worked on. ``wait`` makes the POST return after the turn (tests, scripts). Model calls go through the
provider layer as role ``assembly_agent`` (routing PD-82), capped per turn (``chat.TURN_MAX_TOKENS``) and within the
workspace's balance, metered and debited like every other AI step; a part the design agent makes is metered by the
Design Studio as usual. Without AI (no tokens, AI off, simulated agents) the offline reader answers the common
requests at no cost.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from aicad.assembly import agent, chat, store
from aicad.platform import metering
from aicad.platform.deps import Ctx
from aicad.platform.routers import mod_assembly as asm
from aicad.platform.services import debit, track

router = APIRouter(prefix="/api/m/assembly", tags=["assembly"])
log = logging.getLogger(__name__)
_running: dict[str, asyncio.Task[Any]] = {}
STALE_S = 900


class SayIn(BaseModel):
    text: str = Field(min_length=1, max_length=chat.MAX_TEXT)
    wait: bool = False
    job: str | None = None     # the answer is for this design job's question (relayed to the design agent)


# ----------------------------------------------------------------------------- the platform side of a turn
def _detail(e: HTTPException) -> str:
    d = e.detail
    return str(d.get("message") if isinstance(d, dict) else d)


class PlatformEnv(agent.Env):
    """Everything a turn needs, with its own database session per call (a turn outlives the request)."""

    def __init__(self, ctx: Ctx, root: Path, aid: str, ai_cap: int) -> None:
        org = ctx.require_org()
        self.org_id, self.user_id, self.user_name = org.id, ctx.user.id, ctx.user.name
        self.actor_id, self.session_id, self.role, self.god = ctx.actor.id, ctx.session.id, ctx.role, dict(ctx.god)
        self.root, self.aid, self.cap = root, aid, ai_cap

    @contextlib.contextmanager
    def ctx(self) -> Iterator[Ctx]:
        from aicad.platform.db import session_factory
        from aicad.platform.models import AuthSession, Organization, User

        db = session_factory()()
        try:
            user = db.get(User, self.user_id)
            c = Ctx(db=db, user=user, session=db.get(AuthSession, self.session_id), actor=db.get(User, self.actor_id),
                    org=db.get(Organization, self.org_id), role=self.role, god=self.god)
            yield c
        finally:
            db.close()

    async def project_part(self, project_id: str) -> str:
        with self.ctx() as c:
            try:
                return await asm._project_part(c, asm._project(c, project_id))
            except HTTPException as e:
                raise agent.ToolError(_detail(e)) from None

    def candidates(self) -> list[dict[str, Any]]:
        with self.ctx() as c:
            return asm._part_candidates(c)

    def project_params(self, project_id: str) -> dict[str, Any]:
        from aicad.platform.routers.projects import current_editable, workspace_for

        with self.ctx() as c:
            return current_editable(workspace_for(asm._project(c, project_id)))

    def _new_project(self, c: Ctx, name: str, description: str) -> Any:
        from aicad.platform.models import Project
        from aicad.platform.routers.projects import workspace_for
        from aicad.platform.services import audit

        p = Project(org_id=self.org_id, name=name[:120], description=description[:2000], created_by=self.user_id)
        c.db.add(p)
        c.db.flush()
        home = (store.load(self.root, self.aid) or {}).get("project_id")
        if home:   # DS-040: a part made for this assembly joins its home part's project
            from aicad.memory import context as mctx
            from aicad.memory import service as dps

            dp = mctx.design_project_of(c.db, home)
            if dp is not None:
                dps.link(c.db, p, dp, self.user_id)
        workspace_for(p).mkdir(parents=True, exist_ok=True)
        audit(c.db, "project.created", c.user, self.org_id, target=p.id, name=p.name)
        track(c.db, "project_created", c.user, self.org_id, template="assembly_agent")
        c.db.commit()
        return p

    async def make_part(self, name: str, source: str, note: str) -> str:
        from aicad.platform.routers.library import install_model

        with self.ctx() as c:
            if c.role == "viewer":
                raise agent.ToolError("Viewers can't make parts.")
            p = self._new_project(c, name, "Made in Assembly Studio")
            try:
                await install_model(p, c, source, strict=True, note=note)
            except HTTPException as e:
                raise agent.ToolError(_detail(e)) from None
            c.db.commit()
            return str(p.id)

    async def set_params(self, project_id: str, values: dict[str, float]) -> dict[str, Any]:
        from aicad.platform.routers.projects import ParamsIn, set_params

        with self.ctx() as c:
            try:
                return await set_params(project_id, ParamsIn(values=values), c)
            except HTTPException as e:
                raise agent.ToolError(_detail(e)) from None

    async def design_part(self, name: str, brief: str) -> str:
        from aicad.platform.routers.projects import ChatIn, agent_chat

        with self.ctx() as c:
            p = self._new_project(c, name, brief[:400])
            try:
                await agent_chat(p.id, ChatIn(prompt=brief, skip_brief=True), c)
            except HTTPException as e:
                raise agent.ToolError(_detail(e)) from None
            return str(p.id)

    async def watch_design(self, project_id: str, on_step: Callable[[str], None],
                           on_questions: Callable[[list[dict[str, Any]]], None] | None = None) -> bool:
        from aicad.agent.runner import is_verified
        from aicad.platform.routers import projects as prj

        s = prj._sessions.get(project_id)
        if s is not None:
            q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
            s.subscribers.add(q)
            try:
                loop = asyncio.get_running_loop()
                end = loop.time() + 20 * 60
                while loop.time() < end:
                    try:
                        ev = await asyncio.wait_for(q.get(), 2.0)
                    except TimeoutError:
                        if not s.busy:
                            break
                        continue
                    if ev.get("type") == "tool" and ev.get("brief"):
                        on_step(str(ev["brief"]))
                    if ev.get("type") == "questions" and on_questions is not None:
                        on_questions(list(ev.get("questions") or []))
                    if ev.get("type") == "result" or ev.get("type") == "busy" and ev.get("value") is False:
                        break
            finally:
                s.subscribers.discard(q)
        await prj.wait_finalized(project_id)
        with self.ctx() as c:
            p = asm._project(c, project_id)
            return bool(is_verified(asm._status(prj.workspace_for(p))))

    async def answer_design(self, project_id: str, text: str) -> None:
        from aicad.platform.routers.projects import ChatIn, agent_chat

        with self.ctx() as c:
            try:
                await agent_chat(project_id, ChatIn(prompt=text), c)
            except HTTPException as e:
                raise agent.ToolError(_detail(e)) from None

    def build_state(self, project_id: str) -> dict[str, Any]:
        from aicad.agent.runner import verification
        from aicad.platform.routers import projects as prj

        with self.ctx() as c:
            ws = prj.workspace_for(asm._project(c, project_id))
        st = asm._status(ws)
        vf = verification(st)
        geo = vf["state"] != "none" and (ws / "out" / "part.step").is_file()
        return {"geometry": geo, "verified": vf["state"] in ("verified", "pending"), "state": vf["state"],
                "accepted": vf["accepted"], "open": vf["open"]}

    async def look(self, root: Path, doc: dict[str, Any]) -> dict[str, Any] | None:
        with self.ctx() as c:
            acc = asm.visual_access(c)
        if acc is None:
            return None
        return await asm.look_at(root, doc, acc, what="Assembly Studio · assembly agent visual check")

    def context(self, doc: dict[str, Any]) -> str:
        from aicad.memory import context as mctx

        pid = doc.get("project_id") or next((i["source"].get("project_id") for i in doc["instances"]
                                             if i["source"].get("kind") == "project"), None)
        if not pid:
            return ""
        try:
            with self.ctx() as c:
                from aicad.platform.models import Project

                p = c.db.get(Project, pid)
                return mctx.turn_context(c.db, c.user, p, "").text if p is not None and p.org_id == self.org_id else ""
        except Exception:
            log.warning("assembly agent: no project context", exc_info=True)
            return ""

    async def model(self, system: str, prompt: str, job: str, schema: dict[str, Any]
                    ) -> tuple[Any, int, str | None]:
        from aicad import llm
        from aicad.llm import routing
        from aicad.llm.base import StructuredOutputError, parse_json_answer, schema_instruction

        god = bool(self.god.get("bypass_tokens"))
        budget = self.cap * metering.USD_PER_TOKEN   # the per-turn hard cap holds in God mode too
        try:
            res = await llm.complete(llm.CallRequest(
                role="assembly_agent", system=system + schema_instruction(schema), prompt=prompt,
                standalone_system=True, budget_usd=budget, model=routing.model_for("assembly_agent", job),
                max_tokens=4000))
        except Exception as e:
            log.warning("assembly agent model call failed", exc_info=True)
            return None, 0, type(e).__name__
        usd = res.metering.cost_usd
        tokens = min(self.cap, metering.tokens_for_usd(usd)) if usd else 0
        with self.ctx() as c:
            if tokens and not god:
                debit(c.db, c.require_org(), tokens, "usage", "Assembly Studio · assembly agent", c.user, ref=self.aid)
            track(c.db, "assembly_agent_turn", c.user, self.org_id, tokens=tokens if not god else 0, job=job)
            c.db.commit()
        try:
            return parse_json_answer(res.text, schema), tokens, None
        except StructuredOutputError as e:
            return None, tokens, str(e)


# ----------------------------------------------------------------------------- access and AI
def _ai(ctx: Ctx) -> tuple[bool, int]:
    """(an AI turn is available, its token cap)."""
    from aicad.office import fake_agents
    from aicad.platform.routers.projects import can_run_agent

    if fake_agents.enabled() or ctx.role == "viewer":
        return False, 0
    allowed, _, _ = can_run_agent(ctx)
    if not allowed:
        return False, 0
    if ctx.god_on("bypass_tokens"):
        return True, chat.TURN_MAX_TOKENS
    org = ctx.require_org()
    cap = min(chat.TURN_MAX_TOKENS, max(0, org.token_balance - metering.reserved(org.id)))
    return cap >= 3, cap


def _view(ctx: Ctx, aid: str) -> dict[str, Any]:
    root = asm._root(ctx)
    c = chat.load(root, aid)
    b = c.get("busy")
    if b and aid not in _running:   # a turn this server isn't running any more (a restart): say so
        def clear(cc: dict[str, Any]) -> None:
            if cc.get("busy"):
                cc["busy"] = None
                cc["messages"].append({"id": chat.next_id(cc), "role": "agent", "steps": [], "questions": [],
                                       "text": "My last turn was interrupted (the server restarted). Say it again "
                                               "and I'll pick it up.", "at": store.now(), "tokens": 0})
        c = chat.update(root, aid, clear)
    ai, _cap = _ai(ctx)
    return {**chat.public(c), "ai": ai, "can_edit": ctx.role != "viewer"}


@router.get("/assemblies/{aid}/chat")
def get_chat(aid: str, ctx: Ctx = Depends(asm.asm_ctx)) -> dict[str, Any]:
    asm._doc(ctx, aid)
    return _view(ctx, aid)


@router.post("/assemblies/{aid}/chat")
async def say(aid: str, body: SayIn, ctx: Ctx = Depends(asm.asm_ctx)) -> dict[str, Any]:
    asm._editor(ctx)
    asm._doc(ctx, aid)
    text = body.text.strip()
    if not text:
        raise HTTPException(409, "Write a message first.")
    root = asm._root(ctx)
    if aid in _running and not _running[aid].done():
        raise HTTPException(409, "I'm still working on your last message.")
    ai, cap = _ai(ctx)
    jid = body.job or _answers_job(chat.load(root, aid), text)
    if jid:   # the engineer answered a design agent's question here: it goes to that design, no turn of mine
        chat.update(root, aid, lambda c: chat.user_message(c, text, ctx.user.name))
        try:
            await agent.answer_job(root, aid, PlatformEnv(ctx, root, aid, cap), jid, text)
        except agent.ToolError as e:
            msg = str(e)
            chat.update(root, aid, lambda c: c["messages"].append(
                {"id": chat.next_id(c), "role": "agent", "text": msg, "steps": [], "questions": [], "at": store.now(),
                 "tokens": 0}))
        return _view(ctx, aid)

    def add(c: dict[str, Any]) -> None:
        chat.user_message(c, text, ctx.user.name)
        c["busy"] = {"since": store.now(), "step": "Reading your request"}

    chat.update(root, aid, add)
    env = PlatformEnv(ctx, root, aid, cap)
    track(ctx.db, "assembly_chat_message", ctx.user, ctx.require_org().id, chars=len(text), ai=ai)
    ctx.db.commit()

    async def turn() -> None:
        try:
            await agent.run_turn(root, aid, env, text, ai)
        finally:
            _running.pop(aid, None)

    task = asyncio.get_running_loop().create_task(turn())
    _running[aid] = task
    if body.wait:
        await task
    return _view(ctx, aid)


def _answers_job(c: dict[str, Any], text: str) -> str | None:
    """A message that answers a design job's question: a clicked chip ("<question> <answer>") or, when exactly one
    design is waiting and the last thing said was its question, whatever the engineer types next."""
    waiting = [j for j in c.get("jobs") or [] if j.get("status") == "question"]
    for j in waiting:
        if any(text.startswith(str(q.get("question") or "")) for q in j.get("questions") or []):
            return str(j["id"])
    last = c["messages"][-1] if c.get("messages") else None
    if len(waiting) == 1 and last and last.get("role") == "agent" and last.get("job") == waiting[0]["id"] \
            and last.get("questions"):
        return str(waiting[0]["id"])
    return None


@router.post("/assemblies/{aid}/chat/reset")
def reset(aid: str, ctx: Ctx = Depends(asm.asm_ctx)) -> dict[str, Any]:
    asm._editor(ctx)
    asm._doc(ctx, aid)
    if aid in _running and not _running[aid].done():
        raise HTTPException(409, "Wait for the current turn to finish.")
    chat.reset(asm._root(ctx), aid)
    return _view(ctx, aid)

