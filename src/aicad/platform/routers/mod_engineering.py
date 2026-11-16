"""Engineering Advisor API (`/api/m/engineering/...`): calculator catalogue and runs, the project link (model data
and pre-fill suggestions), load cases, calculation sets with engineer sign-off, tolerance stack-ups, and the
failure-mode checklist with stress-concentration hints.

Org-scoped through the project lookup; viewers are read-only; the module needs the `engineering` entitlement
(add-on, plan or God-mode unlock), otherwise 402.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from aicad import deliverables, materials
from aicad.engineering import REGISTRY, core, project, report, review, store, wording
from aicad.engineering import standards as std
from aicad.engineering import units as eunits
from aicad.engineering.calc_machine import stack
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.models import Project
from aicad.platform.routers.projects import _project, workspace_for
from aicad.platform.services import audit, org_modules

router = APIRouter(prefix="/api/m/engineering", tags=["engineering"])
CODE = "engineering"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(ws: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(str(ws), threading.Lock())


def eng_ctx(ctx: Ctx = Depends(verified_ctx)) -> Ctx:
    org = ctx.require_org()
    if CODE not in org_modules(ctx.db, org) and not ctx.god_on("bypass_paywall"):
        raise HTTPException(402, {"message": "Engineering Advisor is not part of your plan. Unlock the add-on to "
                                             "use it.", "cta": "/app/modules/engineering"})
    return ctx


def _writer(ctx: Ctx) -> None:
    if ctx.role == "viewer":
        raise HTTPException(403, "Viewers have read-only access to engineering records")


def _who(ctx: Ctx) -> dict[str, Any]:
    return {"id": ctx.user.id, "name": ctx.user.name}


def _ws(ctx: Ctx, pid: str) -> Path:
    return workspace_for(_project(ctx, pid))


def _run(calc_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
    try:
        return core.run(calc_id, inputs)
    except core.InputError as e:
        raise HTTPException(422, str(e)) from e


def _text(value: str | None, field: str, limit: int = 4000) -> str:
    s = (value or "").strip()[:limit]
    try:
        return wording.require_no_claim(s, field)
    except wording.ClaimError as e:
        raise HTTPException(422, str(e)) from e


# ----------------------------------------------------------------------------- catalogue
@router.get("/catalog")
def catalog(ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    mats = [m for m in (materials.mechanical(str(x["code"])) for x in materials.MATERIALS) if m]
    return {
        "calculators": [c.schema() for c in REGISTRY.values()],
        "units": eunits.kinds_for_ui(), "levels": core.LEVELS, "engine": core.ENGINE_VERSION,
        "library": {"standards_version": std.VERSION, "tables": std.provenance(),
                    "materials_version": materials.MECHANICAL_VERSION, "materials_note": materials.MECHANICAL_NOTE,
                    "materials": mats},
        "can_edit": ctx.role != "viewer",
    }


class RunIn(BaseModel):
    calc_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)


@router.post("/run")
def run_calc(body: RunIn, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    return _run(body.calc_id, body.inputs)


# ----------------------------------------------------------------------------- projects + model link
@router.get("/projects")
def projects(ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    org = ctx.require_org()
    out = []
    for p in ctx.db.scalars(select(Project).where(Project.org_id == org.id, Project.archived.is_(False))
                            .order_by(Project.updated_at.desc())):
        ws = workspace_for(p)
        sets = store.load(ws, "sets") if (ws / "engineering").is_dir() else []
        lcs = store.load(ws, "loadcases") if (ws / "engineering").is_dir() else []
        cur = deliverables.build_stamp(ws)
        states = [store.signoff_status(s, lcs, cur)["state"] for s in sets]  # type: ignore[arg-type]
        out.append({"id": p.id, "name": p.name, "built": (ws / "out" / "part.step").is_file(),
                    "part": (p.last_status or {}).get("part"), "material": (p.last_status or {}).get("material"),
                    "thumbnail": f"/api/projects/{p.id}/files/views.png" if (ws / "out" / "views.png").is_file()
                    else None, "sets": len(sets), "signed": states.count("signed"),
                    "model_changed": states.count("model_changed"), "load_cases": len(lcs)})
    return {"items": out}


@router.get("/projects/{pid}/model")
def model(pid: str, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    p = _project(ctx, pid)
    info = project.model_info(workspace_for(p))
    return {"project": {"id": p.id, "name": p.name}, **info}


# ----------------------------------------------------------------------------- load cases (ENG-001)
class LoadIn(BaseModel):
    name: str = Field("Load", max_length=80)
    type: str = Field("force", pattern="^(force|moment|pressure|acceleration|temperature|displacement)$")
    value: float
    unit: str = Field("N", max_length=20)
    direction: str = Field("", max_length=60)
    location: str = Field("", max_length=120)
    basis: str = Field("assumed", pattern="^(specified|measured|derived|assumed)$")
    source: str = Field("", max_length=200)


class SupportIn(BaseModel):
    type: str = Field("fixed", pattern="^(fixed|pinned|roller|bolted|bearing|contact|symmetry|other)$")
    location: str = Field("", max_length=120)
    note: str = Field("", max_length=200)


class LoadCaseIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    kind: str = Field("static", pattern="^(static|fatigue|impact|thermal|transport|other)$")
    description: str = Field("", max_length=2000)
    loads: list[LoadIn] = Field(default_factory=list, max_length=40)
    supports: list[SupportIn] = Field(default_factory=list, max_length=20)
    cycles: float | None = Field(None, ge=0)
    temperature_c: float | None = Field(None, ge=-273.15, le=3000)
    environment: str = Field("", max_length=200)
    source: str = Field("", max_length=300)


def _clean_lc(body: LoadCaseIn) -> dict[str, Any]:
    d = body.model_dump()
    d["description"] = _text(d["description"], "Description", 2000)
    _UNITS = {"force": "force", "moment": "moment", "pressure": "stress"}
    for ld in d["loads"]:
        kind = _UNITS.get(ld["type"])
        if kind:
            try:
                ld["value_canonical"] = eunits.to_canonical(kind, ld["value"], ld["unit"])
                ld["unit_canonical"] = eunits.KINDS[kind].label
            except eunits.UnitError as e:
                raise HTTPException(422, f"Load '{ld['name']}': {e}") from e
    return d


@router.get("/projects/{pid}/loadcases")
def list_lc(pid: str, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    return {"items": store.load(_ws(ctx, pid), "loadcases")}


def _touch_sets_for_lc(ws: Path, lc_id: str, before: list[dict[str, Any]], after: list[dict[str, Any]],
                       who: dict[str, Any], what: str) -> None:
    sets: list[dict[str, Any]] = store.load(ws, "sets")  # type: ignore[assignment]
    changed = False
    for cs in sets:
        if lc_id in (cs.get("load_case_ids") or []):
            h0 = store.set_hash(cs, before)
            if store.set_hash(cs, after) != h0:
                store.record_change(cs, h0, after, who, what)
                changed = True
    if changed:
        store.save(ws, "sets", sets)


@router.post("/projects/{pid}/loadcases")
def create_lc(pid: str, body: LoadCaseIn, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    ws = _ws(ctx, pid)
    with _lock(ws):
        items: list[dict[str, Any]] = store.load(ws, "loadcases")  # type: ignore[assignment]
        lc = {"id": store.new_id("lc"), **_clean_lc(body), "created_at": store.now(), "created_by": _who(ctx),
              "updated_at": store.now(), "updated_by": _who(ctx)}
        items.append(lc)
        store.save(ws, "loadcases", items)
    return lc


@router.patch("/projects/{pid}/loadcases/{lid}")
def update_lc(pid: str, lid: str, body: LoadCaseIn, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    ws = _ws(ctx, pid)
    with _lock(ws):
        items: list[dict[str, Any]] = store.load(ws, "loadcases")  # type: ignore[assignment]
        before = [dict(x) for x in items]
        lc = next((x for x in items if x["id"] == lid), None)
        if lc is None:
            raise HTTPException(404, "Load case not found")
        lc.update(_clean_lc(body), updated_at=store.now(), updated_by=_who(ctx))
        store.save(ws, "loadcases", items)
        _touch_sets_for_lc(ws, lid, before, items, _who(ctx), f"Load case '{lc['name']}' edited")
    return lc


@router.delete("/projects/{pid}/loadcases/{lid}")
def delete_lc(pid: str, lid: str, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    ws = _ws(ctx, pid)
    with _lock(ws):
        items: list[dict[str, Any]] = store.load(ws, "loadcases")  # type: ignore[assignment]
        sets: list[dict[str, Any]] = store.load(ws, "sets")  # type: ignore[assignment]
        if any(lid in (s.get("load_case_ids") or []) for s in sets):
            raise HTTPException(409, "This load case is linked to a calculation set; unlink it first")
        store.save(ws, "loadcases", [x for x in items if x["id"] != lid])
    return {"ok": True}


# ----------------------------------------------------------------------------- calculation sets + sign-off (ENG-008)
class SetIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    notes: str = Field("", max_length=4000)
    conclusion: str = Field("", max_length=2000)
    load_case_ids: list[str] = Field(default_factory=list, max_length=20)


class SetPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    notes: str | None = Field(None, max_length=4000)
    conclusion: str | None = Field(None, max_length=2000)
    load_case_ids: list[str] | None = Field(None, max_length=20)


class ItemIn(BaseModel):
    calc_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    title: str = Field("", max_length=120)
    source: dict[str, Any] | None = None   # project-link provenance of pre-filled inputs
    confirmed: list[str] = Field(default_factory=list, max_length=40)   # example values the user chose to keep


class SignIn(BaseModel):
    statement: str = Field(..., min_length=10, max_length=1000)
    confirm: bool = False
    loads_in_calcs: bool = False   # no load case linked: the signer confirms the loads are stated in each calculation


def _sets(ws: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return store.load(ws, "sets"), store.load(ws, "loadcases")  # type: ignore[return-value]


def _dec(ws: Path, cs: dict[str, Any], lcs: list[dict[str, Any]]) -> dict[str, Any]:
    cur = deliverables.build_stamp(ws)
    d = store.decorate(cs, lcs, cur)
    d["sign_statement"] = store.statement_facts(cs, lcs, cur)
    return d


def _find(sets: list[dict[str, Any]], sid: str) -> dict[str, Any]:
    cs = next((s for s in sets if s["id"] == sid), None)
    if cs is None:
        raise HTTPException(404, "Calculation set not found")
    return cs


@router.get("/projects/{pid}/sets")
def list_sets(pid: str, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    ws = _ws(ctx, pid)
    sets, lcs = _sets(ws)
    return {"items": [_dec(ws, s, lcs) for s in sets]}


@router.get("/projects/{pid}/sets/{sid}")
def get_set(pid: str, sid: str, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    ws = _ws(ctx, pid)
    sets, lcs = _sets(ws)
    return _dec(ws, _find(sets, sid), lcs)


def _check_lcs(ids: list[str], lcs: list[dict[str, Any]]) -> None:
    known = {c["id"] for c in lcs}
    if any(i not in known for i in ids):
        raise HTTPException(422, "Unknown load case")


@router.post("/projects/{pid}/sets")
def create_set(pid: str, body: SetIn, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    ws = _ws(ctx, pid)
    with _lock(ws):
        sets, lcs = _sets(ws)
        _check_lcs(body.load_case_ids, lcs)
        cs = {"id": store.new_id("cs"), "name": body.name.strip(), "notes": _text(body.notes, "Notes"),
              "conclusion": _text(body.conclusion, "Conclusion", 2000), "load_case_ids": body.load_case_ids,
              "items": [], "signoff": None, "created_at": store.now(), "created_by": _who(ctx),
              "updated_at": store.now(), "updated_by": _who(ctx),
              "history": [{"at": store.now(), "by": _who(ctx), "event": "created", "detail": "Set created"}]}
        sets.append(cs)
        store.save(ws, "sets", sets)
    return _dec(ws, cs, lcs)


@router.patch("/projects/{pid}/sets/{sid}")
def patch_set(pid: str, sid: str, body: SetPatch, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    ws = _ws(ctx, pid)
    with _lock(ws):
        sets, lcs = _sets(ws)
        cs = _find(sets, sid)
        h0 = store.set_hash(cs, lcs)
        what = []
        if body.name is not None:
            cs["name"] = body.name.strip()
            what.append("renamed")
        if body.notes is not None:
            cs["notes"] = _text(body.notes, "Notes")
            what.append("notes")
        if body.conclusion is not None:
            cs["conclusion"] = _text(body.conclusion, "Conclusion", 2000)
            what.append("conclusion")
        if body.load_case_ids is not None:
            _check_lcs(body.load_case_ids, lcs)
            cs["load_case_ids"] = body.load_case_ids
            what.append("linked load cases")
        store.record_change(cs, h0, lcs, _who(ctx), "Edited " + ", ".join(what or ["nothing"]))
        store.save(ws, "sets", sets)
    return _dec(ws, cs, lcs)


@router.delete("/projects/{pid}/sets/{sid}")
def delete_set(pid: str, sid: str, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    ws = _ws(ctx, pid)
    with _lock(ws):
        sets, _ = _sets(ws)
        cs = _find(sets, sid)
        if cs.get("signoff") and ctx.role not in ("owner", "admin"):
            raise HTTPException(403, "Only an admin can delete a set that has been signed")
        store.save(ws, "sets", [s for s in sets if s["id"] != sid])
    audit(ctx.db, "engineering.set_deleted", ctx.actor, ctx.require_org().id, project=pid, set=sid)
    ctx.db.commit()
    return {"ok": True}


def _item(body: ItemIn, ctx: Ctx, ws: Path) -> dict[str, Any]:
    result = _run(body.calc_id, body.inputs)
    calc = REGISTRY[body.calc_id]
    examples = {e["key"] for e in result.get("examples") or []}
    confirmed = sorted(k for k in set(body.confirmed) if k in examples)
    st = deliverables.read_status(ws)
    return {"id": store.new_id("it"), "calc_id": calc.id, "calc_version": calc.version, "engine": core.ENGINE_VERSION,
            "title": (body.title or calc.name).strip()[:120], "raw_inputs": body.inputs, "result": result,
            "source": body.source, "added_by": _who(ctx), "added_at": store.now(), "confirmed": confirmed,
            "build": deliverables.build_stamp(ws, st) if st.get("build_id") is not None else None}


@router.post("/projects/{pid}/sets/{sid}/items")
def add_item(pid: str, sid: str, body: ItemIn, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    ws = _ws(ctx, pid)
    with _lock(ws):
        sets, lcs = _sets(ws)
        cs = _find(sets, sid)
        if len(cs["items"]) >= 60:
            raise HTTPException(422, "A set holds at most 60 calculations")
        h0 = store.set_hash(cs, lcs)
        it = _item(body, ctx, ws)
        cs["items"].append(it)
        store.record_change(cs, h0, lcs, _who(ctx), f"Added '{it['title']}'")
        store.save(ws, "sets", sets)
    return _dec(ws, cs, lcs)


@router.patch("/projects/{pid}/sets/{sid}/items/{iid}")
def update_item(pid: str, sid: str, iid: str, body: ItemIn, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    ws = _ws(ctx, pid)
    with _lock(ws):
        sets, lcs = _sets(ws)
        cs = _find(sets, sid)
        idx = next((i for i, x in enumerate(cs["items"]) if x["id"] == iid), None)
        if idx is None:
            raise HTTPException(404, "Calculation not found")
        h0 = store.set_hash(cs, lcs)
        old = cs["items"][idx]
        it = _item(body, ctx, ws)
        it.update(id=old["id"], added_by=old.get("added_by"), added_at=old.get("added_at"),
                  edited_by=_who(ctx), edited_at=store.now())
        cs["items"][idx] = it
        store.record_change(cs, h0, lcs, _who(ctx), f"Edited inputs of '{it['title']}'")
        store.save(ws, "sets", sets)
    return _dec(ws, cs, lcs)


@router.delete("/projects/{pid}/sets/{sid}/items/{iid}")
def delete_item(pid: str, sid: str, iid: str, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    ws = _ws(ctx, pid)
    with _lock(ws):
        sets, lcs = _sets(ws)
        cs = _find(sets, sid)
        h0 = store.set_hash(cs, lcs)
        old = next((x for x in cs["items"] if x["id"] == iid), None)
        if old is None:
            raise HTTPException(404, "Calculation not found")
        cs["items"] = [x for x in cs["items"] if x["id"] != iid]
        store.record_change(cs, h0, lcs, _who(ctx), f"Removed '{old['title']}'")
        store.save(ws, "sets", sets)
    return _dec(ws, cs, lcs)


@router.post("/projects/{pid}/sets/{sid}/signoff")
def signoff(pid: str, sid: str, body: SignIn, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    if ctx.role not in ("owner", "admin", "engineer"):
        raise HTTPException(403, "Only engineers, admins and owners can sign calculation sets")
    if ctx.impersonating:
        raise HTTPException(403, "Sign-off is not possible while impersonating a user")
    if not body.confirm:
        raise HTTPException(422, "Confirm that you have reviewed the inputs, assumptions and results")
    statement = _text(body.statement, "Sign-off statement", 1000)
    ws = _ws(ctx, pid)
    with _lock(ws):
        sets, lcs = _sets(ws)
        cs = _find(sets, sid)
        if not cs["items"]:
            raise HTTPException(422, "Add at least one calculation before signing")
        missing = [it["title"] for it in cs["items"]
                   if it["result"].get("safety_factor") and not it["result"]["safety_factor"].get("source")]
        if missing:
            raise HTTPException(422, f"Safety factor source missing in: {', '.join(missing)}")
        if not cs.get("load_case_ids") and not body.loads_in_calcs:
            raise HTTPException(422, "Link the load cases these calculations use, or confirm that the loads are "
                                     "stated in each calculation")
        examples = [f"{it['title']} ({', '.join(e['label'] for e in store.unconfirmed(it))})"
                    for it in cs["items"] if store.unconfirmed(it)]
        if examples:
            raise HTTPException(422, "Replace or confirm the example load values first: " + "; ".join(examples))
        cur = deliverables.build_stamp(ws)
        old = [it["title"] for it in cs["items"] if it.get("source") and it.get("build")
               and not deliverables.same_build(it["build"], cur)]
        if old:
            raise HTTPException(422, "These calculations were pre-filled from an earlier model revision. Update "
                                     "their inputs from the current model and save them first: " + ", ".join(old))
        user = {"id": ctx.user.id, "name": ctx.user.name, "email": ctx.user.email, "role": ctx.role}
        so = store.sign(cs, lcs, user, statement, build=cur if cur.get("build_id") else None,
                        loads_in_calcs=body.loads_in_calcs and not cs.get("load_case_ids"))
        so["facts"] = store.statement_facts(cs, lcs, cur)
        store.save(ws, "sets", sets)
    audit(ctx.db, "engineering.signoff", ctx.actor, ctx.require_org().id, project=pid, set=sid, hash=so["hash"])
    ctx.db.commit()
    return _dec(ws, cs, lcs)


@router.get("/projects/{pid}/sets/{sid}/report.pdf")
def set_report(pid: str, sid: str, ctx: Ctx = Depends(eng_ctx)) -> Response:
    p = _project(ctx, pid)
    ws = workspace_for(p)
    sets, _ = _sets(ws)
    cs = _find(sets, sid)
    data = report.build_pdf(ws, sid, p.name)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in f"{p.name}_{cs['name']}")[:80] or "calculations"
    audit(ctx.db, "engineering.report", ctx.actor, ctx.require_org().id, project=pid, set=sid)
    ctx.db.commit()
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{safe}_calculations.pdf"',
                             "Cache-Control": "no-store"})


# ----------------------------------------------------------------------------- stack-ups (ENG-011)
class StackRow(BaseModel):
    name: str = Field("", max_length=80)
    dir: str = Field("+", pattern=r"^[+-]$")
    nominal: float
    plus: float = Field(..., ge=0)
    minus: float = Field(..., ge=0)
    sens: float = 1.0
    source: str = Field("", max_length=120)


class StackIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field("", max_length=1000)
    unit: str = Field("mm", pattern="^(mm|in)$")
    rows: list[StackRow] = Field(..., min_length=1, max_length=50)
    spec_min: float | None = None
    spec_max: float | None = None


def _stack_result(body: StackIn) -> dict[str, Any]:
    u = body.unit
    rows = [{"name": r.name, "dir": r.dir, "nominal": {"value": r.nominal, "unit": u},
             "plus": {"value": r.plus, "unit": u}, "minus": {"value": r.minus, "unit": u}, "sens": r.sens}
            for r in body.rows]
    inp: dict[str, Any] = {"rows": rows}
    if body.spec_min is not None:
        inp["spec_min"] = {"value": body.spec_min, "unit": u}
    if body.spec_max is not None:
        inp["spec_max"] = {"value": body.spec_max, "unit": u}
    res = _run("tolerance_stack", inp)
    k = 1.0 if u == "mm" else 25.4
    s = stack([{**r, "nominal": r["nominal"]["value"] * k, "plus": r["plus"]["value"] * k,
                "minus": r["minus"]["value"] * k} for r in rows])
    res["contributions"] = s["contrib"]
    return res


@router.get("/projects/{pid}/stackups")
def list_stacks(pid: str, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    return {"items": store.load(_ws(ctx, pid), "stackups")}


@router.post("/projects/{pid}/stackups")
def create_stack(pid: str, body: StackIn, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    ws = _ws(ctx, pid)
    with _lock(ws):
        items: list[dict[str, Any]] = store.load(ws, "stackups")  # type: ignore[assignment]
        st = {"id": store.new_id("st"), **body.model_dump(), "description": _text(body.description, "Description"),
              "result": _stack_result(body), "created_at": store.now(), "created_by": _who(ctx),
              "updated_at": store.now(), "updated_by": _who(ctx)}
        items.append(st)
        store.save(ws, "stackups", items)
    return st


@router.patch("/projects/{pid}/stackups/{tid}")
def update_stack(pid: str, tid: str, body: StackIn, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    ws = _ws(ctx, pid)
    with _lock(ws):
        items: list[dict[str, Any]] = store.load(ws, "stackups")  # type: ignore[assignment]
        st = next((x for x in items if x["id"] == tid), None)
        if st is None:
            raise HTTPException(404, "Stack-up not found")
        st.update(**body.model_dump(), description=_text(body.description, "Description"),
                  result=_stack_result(body), updated_at=store.now(), updated_by=_who(ctx))
        store.save(ws, "stackups", items)
    return st


@router.delete("/projects/{pid}/stackups/{tid}")
def delete_stack(pid: str, tid: str, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    ws = _ws(ctx, pid)
    with _lock(ws):
        items: list[dict[str, Any]] = store.load(ws, "stackups")  # type: ignore[assignment]
        store.save(ws, "stackups", [x for x in items if x["id"] != tid])
    return {"ok": True}


# ----------------------------------------------------------------------------- review: checklist + hints (ENG-002/006/010)
@router.get("/projects/{pid}/review")
def get_review(pid: str, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    ws = _ws(ctx, pid)
    info = project.model_info(ws)
    if not info.get("available"):
        return {"available": False, "reason": info.get("reason"), "items": [], "hints": [], "analyses": []}
    lcs: list[dict[str, Any]] = store.load(ws, "loadcases")  # type: ignore[assignment]
    items = review.checklist(info, info["hints"], lcs)
    state: dict[str, Any] = store.load(ws, "checklist")  # type: ignore[assignment]
    for it in items:
        it["state"] = state.get(it["id"], {"status": "open"})
    return {"available": True, "items": items, "hints": info["hints"], "analyses": review.recommended_analyses(items),
            "heuristic_note": review.HEURISTIC_NOTE, "level": "recommended_check"}


class ChecklistPatch(BaseModel):
    status: str = Field(..., pattern="^(open|in_progress|addressed|not_applicable)$")
    note: str = Field("", max_length=1000)


@router.patch("/projects/{pid}/review/items/{item_id}")
def patch_review(pid: str, item_id: str, body: ChecklistPatch, ctx: Ctx = Depends(eng_ctx)) -> dict[str, Any]:
    _writer(ctx)
    if not item_id.replace("_", "").isalnum() or len(item_id) > 40:
        raise HTTPException(422, "Bad item")
    ws = _ws(ctx, pid)
    with _lock(ws):
        state: dict[str, Any] = store.load(ws, "checklist")  # type: ignore[assignment]
        state[item_id] = {"status": body.status, "note": _text(body.note, "Note", 1000), "by": _who(ctx),
                          "at": store.now()}
        store.save(ws, "checklist", state)
    return state[item_id]
