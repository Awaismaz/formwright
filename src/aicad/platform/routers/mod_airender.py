"""AI Render Studio API (`/api/m/airender`): AI marketing visuals of a verified part via OpenAI image generation,
paid by the workspace's own OpenAI key (BYO key, Beta).

Integration (key + consent) is per workspace. Admins and owners add, replace or delete the key; it is validated with
a free OpenAI call, stored encrypted and only ever returned as a masked hint. Generating needs the key AND the
one-time consent that the reference image and the prompt go to OpenAI. Engineers generate; viewers browse.

Flow: Refine (template, or a short Claude polish) -> Review (the user edits the prompt) -> Generate (background job,
OpenAI images.edit with the reference render) -> Gallery (download, regenerate, variation).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from aicad.airender import CAPTION, integration, keystore, options, provider, refine, service
from aicad.platform.deps import Ctx, verified_ctx
from aicad.platform.routers.billing import tokens_for_cost
from aicad.platform.routers.projects import _project, _thumb, workspace_for
from aicad.platform.services import audit, debit, org_modules, track

router = APIRouter(prefix="/api/m/airender", tags=["airender"])
POLISH_MIN_TOKENS = 2


def air_ctx(ctx: Ctx = Depends(verified_ctx)) -> Ctx:
    org = ctx.require_org()
    if "airender" not in org_modules(ctx.db, org) and not ctx.god_on("bypass_paywall"):
        raise HTTPException(402, {"message": "AI Render Studio isn't included in your plan.",
                                  "cta": "/app/billing"})
    return ctx


def _base(pid: str) -> str:
    return f"/api/m/airender/projects/{pid}/jobs"


class SettingsIn(BaseModel):
    scene: str = Field(default="studio", max_length=20)
    finish: str = Field(default="", max_length=options.MAX_FINISH)
    lighting: str = Field(default="softbox", max_length=20)
    camera: str = Field(default="match", max_length=20)
    background: str = Field(default="white", max_length=20)
    style: str = Field(default="photoreal", max_length=20)
    size: str = Field(default="1536x1024", max_length=12)
    quality: str = Field(default="medium", max_length=10)
    variants: int = Field(default=1, ge=1, le=options.MAX_VARIANTS)

    def settings(self) -> options.Settings:
        try:
            return options.Settings(**self.model_dump()).validate()
        except ValueError as e:
            raise HTTPException(422, str(e)) from e


class RefineIn(BaseModel):
    settings: SettingsIn = SettingsIn()
    user_prompt: str = Field(default="", max_length=options.MAX_USER_PROMPT)
    engine: str = Field(default="ai", pattern="^(ai|template)$")


class VariationIn(BaseModel):
    job: str = Field(max_length=16)
    index: int = Field(ge=1, le=options.MAX_VARIANTS)


class GenerateIn(BaseModel):
    settings: SettingsIn = SettingsIn()
    prompt: str = Field(min_length=10, max_length=refine.MAX_PROMPT)
    negative: list[str] = Field(default_factory=list, max_length=12)
    engine: str = Field(default="template", max_length=10)
    reference: str | None = Field(default=None, max_length=40)
    variation_of: VariationIn | None = None


class KeyIn(BaseModel):
    api_key: str = Field(min_length=10, max_length=400)


class ConsentIn(BaseModel):
    accept: bool


# ------------------------------------------------------------------ integration (key + consent)
@router.get("/integration")
def get_integration(ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    return {**integration.public_state(ctx.db, ctx.require_org()), "can_manage": ctx.role in ("owner", "admin"),
            "fake": provider.fake_mode()}


@router.post("/integration/key")
def put_key(body: KeyIn, ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    ctx.require_role("admin")
    org = ctx.require_org()
    key = body.api_key.strip()
    if not keystore.looks_like_key(key):
        raise HTTPException(422, "That doesn't look like an OpenAI API key (they start with sk-).")
    try:
        provider.validate_key(key)
    except provider.RenderError as e:
        raise HTTPException(400, {"message": e.message, "code": e.code}) from None
    integration.set_key(ctx.db, org, key, ctx.user.id, ctx.user.name)
    audit(ctx.db, "airender.key_set", ctx.user, org.id, hint=keystore.mask(key))
    ctx.db.commit()
    return get_integration(ctx)


@router.delete("/integration/key")
def delete_key(ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    ctx.require_role("admin")
    org = ctx.require_org()
    if integration.clear_key(ctx.db, org):
        audit(ctx.db, "airender.key_deleted", ctx.user, org.id)
    ctx.db.commit()
    return get_integration(ctx)


@router.post("/integration/consent")
def consent(body: ConsentIn, ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    ctx.require_role("engineer")
    org = ctx.require_org()
    integration.set_consent(ctx.db, org, body.accept, ctx.user.id, ctx.user.name)
    audit(ctx.db, "airender.consent_" + ("given" if body.accept else "withdrawn"), ctx.user, org.id)
    ctx.db.commit()
    return get_integration(ctx)


# ------------------------------------------------------------------ options and projects
@router.get("/options")
def get_options(ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    return {**options.catalog(), "caption": CAPTION, "model": options.model()}


def _mesh_available() -> bool:
    try:
        from aicad.meshstudio import runner

        return bool(runner.detect().get("available"))
    except Exception:  # noqa: BLE001
        return False


@router.get("/projects/{pid}")
def project(pid: str, ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    p = _project(ctx, pid)
    ws = workspace_for(p)
    if not (ws / "out" / "part.step").is_file():
        raise HTTPException(409, "This project has no verified model yet. Build it in the Design Studio first.")
    facts = refine.part_facts(ws, p.name)
    refs = [service.public_ref(r) | {"url": f"/api/m/airender/projects/{pid}/references/{r['id']}"}
            for r in service.references(ws)]
    return {"project": {"id": p.id, "name": p.name, "thumbnail": _thumb(p)}, "facts": facts,
            "finish": options.finish_from_material(facts.get("material")), "references": refs,
            "can_make_reference": _mesh_available(), "jobs": service.list_jobs(ws, _base(pid)), "caption": CAPTION}


@router.get("/projects/{pid}/references/{rid}")
def reference_image(pid: str, rid: str, ctx: Ctx = Depends(air_ctx)) -> FileResponse:
    ref = service.reference(workspace_for(_project(ctx, pid)), rid)
    if ref is None:
        raise HTTPException(404, "Reference not found")
    return FileResponse(ref["path"], media_type="image/png", headers={"Cache-Control": "private, max-age=600"})


@router.post("/projects/{pid}/references/studio")
def make_reference(pid: str, ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    """No studio render yet: queue a quick Mesh Studio preview of the exact model to use as the reference."""
    ctx.require_role("engineer")
    p = _project(ctx, pid)
    ws = workspace_for(p)
    from aicad.meshstudio import jobs, presets, runner, scene
    from aicad.meshstudio import service as mesh

    facts = refine.part_facts(ws, p.name)
    sug = presets.map_material(facts.get("material"))
    try:
        opts = scene.Options(finish=sug["finish"], colour=sug.get("colour"), quality="preview", camera="hero")
        v = mesh.request_render(ws, p.name, opts, ctx.require_org().id, ctx.user.id, "")
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(409, str(e)) from e
    except runner.BlenderError as e:
        raise HTTPException(503, str(e)) from e
    except jobs.QueueFull as e:
        raise HTTPException(429, str(e)) from e
    return {"state": v.get("state"), "id": v.get("id")}


@router.get("/projects/{pid}/references/studio/{jid}")
def reference_job(pid: str, jid: str, ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    from aicad.meshstudio import service as mesh

    v = mesh.job_view(workspace_for(_project(ctx, pid)), jid, "")
    if v is None:
        raise HTTPException(404, "Render not found")
    return {"state": v.get("state"), "progress": v.get("progress"), "error": v.get("error")}


# ------------------------------------------------------------------ refine -> generate
@router.post("/projects/{pid}/refine")
async def refine_prompt(pid: str, body: RefineIn, ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    p = _project(ctx, pid)
    org = ctx.require_org()
    s = body.settings.settings()
    facts = refine.part_facts(workspace_for(p), p.name)
    unlimited = ctx.god_on("bypass_tokens") or provider.fake_mode()  # the development fake costs nothing
    if body.engine == "template":
        return refine.compose(facts, s, body.user_prompt)
    if not unlimited and org.token_balance < POLISH_MIN_TOKENS:
        return {**refine.compose(facts, s, body.user_prompt),
                "note": "Not enough tokens for the AI polish, so this is the standard template."}
    out, usd = await refine.polish(facts, s, body.user_prompt)
    if out["engine"] == "ai":
        tokens = max(1, tokens_for_cost(usd)) if usd else 1
        out["tokens"] = 0 if unlimited else tokens
        if not unlimited:
            debit(ctx.db, org, tokens, "usage", f"AI Render Studio · prompt polish for {p.name}", ctx.user, ref=pid)
        track(ctx.db, "airender_refine", ctx.user, org.id, tokens=out["tokens"])
        ctx.db.commit()
    return out


@router.post("/projects/{pid}/generate")
def generate(pid: str, body: GenerateIn, ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    ctx.require_role("engineer")
    p = _project(ctx, pid)
    org = ctx.require_org()
    s = body.settings.settings()
    if not integration.has_consent(ctx.db, org):
        raise HTTPException(428, {"message": "Confirm that the reference image and prompt may be sent to OpenAI "
                                             "first.", "code": "consent_required"})
    try:
        key = integration.get_key(ctx.db, org)
    except keystore.KeyStoreError as e:
        raise HTTPException(409, {"message": str(e), "code": "key_unreadable"}) from None
    if not key:
        raise HTTPException(409, {"message": "Add your OpenAI key to enable AI renders.", "code": "no_key"})
    ws = workspace_for(p)
    ref = service.reference(ws, body.reference)
    if ref is None:
        raise HTTPException(409, "There is no reference image of this part yet. Make a studio reference first.")
    facts = refine.part_facts(ws, p.name)
    try:
        v = service.submit(ws, key=key, settings=s, prompt=body.prompt, negative=body.negative,
                           engine=body.engine if body.engine in ("ai", "template", "edited") else "edited",
                           ref=ref, org_id=org.id, user_id=ctx.user.id, build_id=facts.get("build_id"),
                           variation_of=body.variation_of.model_dump() if body.variation_of else None,
                           base_url=_base(pid))
    except service.Busy as e:
        raise HTTPException(429, str(e)) from None
    audit(ctx.db, "airender.generate", ctx.user, org.id, target=pid, job=v["id"], n=s.variants,
          quality=s.quality, model=v.get("model"))
    track(ctx.db, "airender_generate", ctx.user, org.id, n=s.variants, quality=s.quality, scene=s.scene)
    ctx.db.commit()
    return v


@router.get("/projects/{pid}/jobs")
def jobs(pid: str, ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    return {"jobs": service.list_jobs(workspace_for(_project(ctx, pid)), _base(pid))}


@router.get("/projects/{pid}/jobs/{jid}")
def job(pid: str, jid: str, ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    v = service.job_view(workspace_for(_project(ctx, pid)), jid, _base(pid))
    if v is None:
        raise HTTPException(404, "Render not found")
    return v


@router.delete("/projects/{pid}/jobs/{jid}")
def delete(pid: str, jid: str, ctx: Ctx = Depends(air_ctx)) -> dict[str, Any]:
    ctx.require_role("engineer")
    p = _project(ctx, pid)
    try:
        ok = service.delete_job(workspace_for(p), jid)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    if not ok:
        raise HTTPException(404, "Render not found")
    return {"ok": True}


@router.get("/projects/{pid}/jobs/{jid}/files/{name}")
def download(pid: str, jid: str, name: str, dl: int = 0, ctx: Ctx = Depends(air_ctx)) -> FileResponse:
    p = _project(ctx, pid)
    path = service.file_path(workspace_for(p), jid, name)
    if path is None:
        raise HTTPException(404, "File not found")
    media = "image/jpeg" if name.endswith(".jpg") else "image/png"
    headers = {"Cache-Control": "private, max-age=3600"}
    if dl:
        stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in p.name)[:60] or "part"
        return FileResponse(path, media_type=media, filename=f"{stem}_ai_{jid[:6]}_{name}", headers=headers)
    return FileResponse(path, media_type=media, headers=headers)
