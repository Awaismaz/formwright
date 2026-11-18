"""AI Render Studio (BYO OpenAI key): key encryption at rest, validation, consent, the prompt refiner, the generation
job lifecycle and OpenAI error mapping. Every external call is mocked: no request reaches OpenAI or Claude."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from pathlib import Path
from typing import Any, ClassVar

import httpx2
import openai
import pytest
from build123d import Box, export_step
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from test_platform import admin, app_client, signup  # noqa: F401  (fixture re-export)

from aicad.airender import CAPTION, keystore, options, provider, refine, service
from aicad.platform import config

KEY = "sk-proj-TESTabcdefghijklmnopqrstuvwxyz0123456789AbCd"


def _png(w: int = 8, h: int = 6, colour: tuple[int, int, int] = (200, 40, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, "PNG")
    return buf.getvalue()


def _err(cls: str, status: int, body: dict[str, Any]) -> Exception:
    req = httpx2.Request("POST", "https://api.openai.com/v1/images/edits")
    return getattr(openai, cls)(body.get("message", "x"), response=httpx2.Response(status, request=req), body=body)


class _NS:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class MockOpenAI:
    """Records calls; `fail` raises on edit, `bad_key` raises on models.list."""

    calls: ClassVar[list[dict[str, Any]]] = []
    fail: Exception | None = None
    bad_key = False

    def __init__(self, key: str) -> None:
        self.key = key
        self.models = _NS(list=self._list)
        self.images = _NS(edit=self._edit)

    def _list(self) -> Any:
        if MockOpenAI.bad_key:
            raise _err("AuthenticationError", 401, {"message": "Incorrect API key provided: " + self.key,
                                                    "code": "invalid_api_key"})
        return _NS(data=[])

    def _edit(self, **kw: Any) -> Any:
        MockOpenAI.calls.append({**kw, "key": self.key})
        if MockOpenAI.fail is not None:
            raise MockOpenAI.fail
        n = kw.get("n", 1)
        data = [_NS(b64_json=base64.b64encode(_png(colour=(10 * i, 80, 160))).decode(), revised_prompt=None)
                for i in range(n)]
        usage = _NS(model_dump=lambda: {"input_tokens": 500, "output_tokens": 1000 * n, "total_tokens": 500 + 1000 * n})
        return _NS(data=data, size=kw.get("size"), quality=kw.get("quality"), usage=usage)


@pytest.fixture(autouse=True)
def _mock_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    MockOpenAI.calls, MockOpenAI.fail, MockOpenAI.bad_key = [], None, False
    monkeypatch.setattr(provider, "client_for", lambda key: MockOpenAI(key))
    monkeypatch.delenv("FW_AI_RENDER_FAKE", raising=False)

    async def no_claude(system: str, prompt: str) -> tuple[str, float | None]:
        raise AssertionError("tests must not call Claude")

    monkeypatch.setattr(refine, "run_refiner_agent", no_claude)


# ------------------------------------------------------------------ key storage
def test_key_encryption_round_trip_and_masking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FW_SECRET_KEY", raising=False)
    monkeypatch.setattr(config, "_settings", config.Settings(env="development", data_dir=tmp_path))  # restored after
    tok = keystore.encrypt(KEY)
    assert tok.startswith("v1:") and KEY not in tok and keystore.decrypt(tok) == KEY
    assert (tmp_path / "secret.key").is_file()  # a dev secret is generated once, inside data/
    assert keystore.encrypt(KEY) != tok  # random IV
    assert keystore.mask(KEY) == "sk-…AbCd" and "TEST" not in keystore.mask(KEY)
    assert keystore.scrub(f"bad key {KEY} here") == "bad key sk-… here"
    assert keystore.looks_like_key(KEY) and not keystore.looks_like_key("hello") and not keystore.looks_like_key("sk-a b")
    monkeypatch.setenv("FW_SECRET_KEY", "a-different-server-secret")
    with pytest.raises(keystore.KeyStoreError):
        keystore.decrypt(tok)  # a changed secret can't read old keys (clear message, no crash)
    assert keystore.decrypt(keystore.encrypt(KEY)) == KEY
    monkeypatch.delenv("FW_SECRET_KEY")
    monkeypatch.setattr(config, "_settings", config.Settings(env="production", data_dir=tmp_path,
                                                             stripe_secret_key="sk_test_x"))
    with pytest.raises(keystore.KeyStoreError):
        keystore.encrypt(KEY)  # production never falls back to a generated secret


# ------------------------------------------------------------------ prompt refiner
FACTS = {"name": "Pipe flange", "material": "Stainless steel 316", "size_mm": [150.0, 150.0, 18.0],
         "features": ["Bore Ø60.3", "6x Ø14 bolt holes"], "build_id": 1}


def test_template_refiner_is_deterministic_and_keeps_geometry() -> None:
    s = options.Settings(scene="workshop", finish="Brushed stainless", lighting="rim", camera="iso").validate()
    a = refine.compose(FACTS, s, "warm mood")
    assert a == refine.compose(FACTS, s, "warm mood") and a["engine"] == "template"
    p = a["prompt"]
    assert refine.GEOMETRY_CLAUSE in p and "Pipe flange" in p and "Brushed stainless" in p
    assert "150 × 150 × 18 mm" in p and "6x Ø14 bolt holes" in p and "warm mood" in p
    assert "workbench" in p and "rim" in p and "isometric" in p
    assert any(n.startswith("no text") for n in a["negative"]) and "no people or hands" in a["negative"]
    with_text = refine.compose(FACTS, s, "engrave the logo ACME on the face")
    assert not any(n.startswith("no text") for n in with_text["negative"])  # asked for text: allowed
    hand = refine.compose(FACTS, options.Settings(scene="in_hand").validate())
    assert "no people or hands" not in hand["negative"]
    # every scene/style/camera combination keeps the clause
    for sc in options.SCENES:
        for st in options.STYLES:
            assert refine.GEOMETRY_CLAUSE in refine.compose(FACTS, options.Settings(scene=sc, style=st).validate())["prompt"]
    with pytest.raises(ValueError):
        options.Settings(scene="moon").validate()
    with pytest.raises(ValueError):
        options.Settings(variants=9).validate()


def test_guarded_prompt_always_has_clause_and_negatives() -> None:
    sent = refine.guarded("A brass part on velvet, dramatic.", ["no dust"])
    assert refine.GEOMETRY_CLAUSE in sent and "Avoid:" in sent and "no dust" in sent
    assert refine.NEGATIVE_BASE[0] in sent  # the user deleted it: it comes back
    p = refine.compose(FACTS, options.Settings().validate())
    sent2 = refine.guarded(p["prompt"], p["negative"])
    assert sent2.count(refine.GEOMETRY_CLAUSE) == 1


def test_agent_refiner_parses_mocked_output(monkeypatch: pytest.MonkeyPatch) -> None:
    s = options.Settings().validate()
    seen: dict[str, str] = {}

    async def fake(system: str, prompt: str) -> tuple[str, float | None]:
        seen["prompt"] = prompt
        return (('Sure!\n```fw-prompt\n{"prompt": "A gleaming stainless flange on a seamless sweep, softbox light.", '
                '"negative": ["no rust"]}\n```'), 0.012)

    monkeypatch.setattr(refine, "run_refiner_agent", fake)
    out, usd = asyncio.run(refine.polish(FACTS, s, "gleaming"))
    assert out["engine"] == "ai" and usd == 0.012 and "gleaming" in seen["prompt"]
    assert out["prompt"].endswith(refine.GEOMETRY_CLAUSE)  # appended when the model dropped it
    assert "no rust" in out["negative"] and refine.NEGATIVE_BASE[0] in out["negative"]

    async def junk(system: str, prompt: str) -> tuple[str, float | None]:
        return "I can't do that.", 0.001

    monkeypatch.setattr(refine, "run_refiner_agent", junk)
    out, _ = asyncio.run(refine.polish(FACTS, s))
    assert out["engine"] == "template" and out["note"] and out["prompt"] == refine.compose(FACTS, s)["prompt"]

    async def down(system: str, prompt: str) -> tuple[str, float | None]:
        raise RuntimeError("agent unavailable")

    monkeypatch.setattr(refine, "run_refiner_agent", down)
    out, usd = asyncio.run(refine.polish(FACTS, s))
    assert out["engine"] == "template" and usd is None and refine.GEOMETRY_CLAUSE in out["prompt"]
    assert refine.parse_polish('{"prompt": "short"}') is None
    assert refine.parse_polish('x {"prompt": "a long enough prompt here please", "negative": "x"} y')["negative"] == []


# ------------------------------------------------------------------ provider
def test_error_mapping() -> None:
    m = provider.map_error
    assert m(_err("AuthenticationError", 401, {"message": f"Incorrect API key {KEY}"})).code == "bad_key"
    assert KEY not in m(_err("BadRequestError", 400, {"message": f"oops {KEY}"})).message
    assert m(_err("RateLimitError", 429, {"message": "You exceeded your current quota",
                                          "code": "insufficient_quota"})).code == "quota"
    assert m(_err("RateLimitError", 429, {"message": "Rate limit reached"})).code == "rate_limited"
    assert m(_err("BadRequestError", 400, {"message": "Your request was rejected by the safety system",
                                           "code": "moderation_blocked"})).code == "safety"
    assert m(_err("PermissionDeniedError", 403, {"message": "verify org"})).code == "forbidden"
    assert m(_err("NotFoundError", 404, {"message": "model"}), "gpt-image-2").code == "model"
    assert m(_err("InternalServerError", 500, {"message": "x"})).code == "upstream"
    assert m(openai.APITimeoutError(httpx2.Request("POST", "https://api.openai.com"))).code == "timeout"
    assert m(openai.APIConnectionError(request=httpx2.Request("POST", "https://api.openai.com"))).code == "network"
    assert m(ValueError("x")).code == "unknown"


def test_edit_call_parameters(tmp_path: Path) -> None:
    ref = tmp_path / "ref.png"
    ref.write_bytes(_png())
    datas, meta = provider.edit(KEY, [ref], "prompt", model="gpt-image-2", size="1536x1024", quality="low",
                                background="transparent", n=2, user_tag="u1")
    call = MockOpenAI.calls[-1]
    assert len(datas) == 2 and datas[0][:8] == b"\x89PNG\r\n\x1a\n"
    assert call["model"] == "gpt-image-2" and call["background"] == "transparent" and call["n"] == 2
    assert "input_fidelity" not in call and call["image"][0] == "ref.png"
    assert meta["usage"]["total_tokens"] == 2500
    provider.edit(KEY, [ref], "p", model="gpt-image-1.5", size="1024x1024", quality="high", background="white", n=1)
    assert MockOpenAI.calls[-1]["input_fidelity"] == "high" and MockOpenAI.calls[-1]["background"] == "auto"


# ------------------------------------------------------------------ API
def _built_project(c: TestClient, name: str = "Flange") -> tuple[str, Path]:
    from aicad.platform.db import session_factory
    from aicad.platform.models import Project
    from aicad.platform.routers.projects import workspace_for

    pid = c.post("/api/projects", json={"name": name}).json()["id"]
    db = session_factory()()
    ws = workspace_for(db.get(Project, pid))
    db.close()
    (ws / "out").mkdir(parents=True, exist_ok=True)
    export_step(Box(30, 20, 10), str(ws / "out" / "part.step"))
    (ws / "out" / "status.json").write_text(json.dumps({
        "ok": True, "build_id": 7, "material": "Brass C360", "part": "flange", "bbox_minmax": [0, 0, 0, 30, 20, 10],
        "features": [{"name": "Base block", "kind": "extrude"}]}))
    Image.new("RGB", (64, 48), (220, 220, 220)).save(ws / "out" / "thumb.png")
    return pid, ws


def test_api_key_consent_generate_and_errors(app_client: TestClient, caplog: pytest.LogCaptureFixture) -> None:  # noqa: F811
    caplog.set_level(logging.DEBUG)
    c = app_client
    assert c.get("/api/m/airender/integration").status_code == 401
    me = signup(c, "air@x.com")
    assert "airender" in me["org"]["modules"]
    pid, ws = _built_project(c)

    st = c.get("/api/m/airender/integration").json()
    assert st["has_key"] is False and st["consent"]["given"] is False and st["model"] == options.DEFAULT_MODEL
    info = c.get(f"/api/m/airender/projects/{pid}").json()
    assert info["facts"]["material"] == "Brass C360" and info["finish"].startswith("Brass")
    assert info["references"][0]["id"] == "thumb" and "path" not in info["references"][0]
    assert c.get(info["references"][0]["url"]).content[:4] == b"\x89PNG"
    assert c.get(f"/api/m/airender/projects/{pid}/references/..%2Fstatus").status_code == 404

    body = {"settings": {"scene": "studio"}, "prompt": "A brass block on white. " * 3, "negative": []}
    r = c.post(f"/api/m/airender/projects/{pid}/generate", json=body)
    assert r.status_code == 428 and r.json()["detail"]["code"] == "consent_required"
    assert c.post("/api/m/airender/integration/consent", json={"accept": True}).json()["consent"]["given"] is True
    r = c.post(f"/api/m/airender/projects/{pid}/generate", json=body)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_key"

    # key: format check, validation (mocked 401), then stored encrypted and only ever shown masked
    assert c.post("/api/m/airender/integration/key", json={"api_key": "not-a-key-at-all"}).status_code == 422
    MockOpenAI.bad_key = True
    r = c.post("/api/m/airender/integration/key", json={"api_key": KEY})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "bad_key" and KEY not in r.text
    MockOpenAI.bad_key = False
    r = c.post("/api/m/airender/integration/key", json={"api_key": KEY})
    assert r.status_code == 200 and r.json()["has_key"] and r.json()["key_hint"] == "sk-…AbCd"
    assert KEY not in r.text and KEY not in c.get("/api/m/airender/integration").text

    from aicad.platform.db import session_factory
    from aicad.platform.models import AuditLog, OrgPrefs

    db = session_factory()()
    stored = json.dumps(db.get(OrgPrefs, me["org"]["id"]).data)
    audits = json.dumps([a.meta for a in db.scalars(select(AuditLog))])
    db.close()
    assert KEY not in stored and "v1:" in stored and KEY not in audits

    # refine: template path is deterministic; the AI path is mocked
    rf = c.post(f"/api/m/airender/projects/{pid}/refine", json={"settings": {"finish": "Brass"}, "engine": "template"})
    assert rf.status_code == 200 and refine.GEOMETRY_CLAUSE in rf.json()["prompt"]
    assert c.post(f"/api/m/airender/projects/{pid}/refine", json={"settings": {"scene": "x"}}).status_code == 422

    # generate -> job -> gallery
    gen = {"settings": {"variants": 2, "quality": "low"}, "prompt": rf.json()["prompt"],
           "negative": rf.json()["negative"], "engine": "template"}
    v = c.post(f"/api/m/airender/projects/{pid}/generate", json=gen)
    assert v.status_code == 200, v.text
    service.wait_idle()
    done = c.get(f"/api/m/airender/projects/{pid}/jobs/{v.json()['id']}").json()
    assert done["state"] == "done", done
    assert len(done["images"]) == 2 and done["caption"] == CAPTION and done["usage"]["total_tokens"] == 2500
    call = MockOpenAI.calls[-1]
    assert call["key"] == KEY and refine.GEOMETRY_CLAUSE in call["prompt"] and "Avoid:" in call["prompt"]
    assert call["image"][0] == "ref.png"
    job_json = (ws / "airender" / done["id"] / "job.json").read_text(encoding="utf-8")
    assert KEY not in job_json
    png = c.get(done["images"][0]["url"])
    assert png.status_code == 200 and Image.open(io.BytesIO(png.content)).text.get("Description") == CAPTION
    assert "attachment" in c.get(done["images"][0]["url"] + "?dl=1").headers["content-disposition"]
    assert c.get(f"/api/m/airender/projects/{pid}/jobs/{done['id']}/files/job.json").status_code == 404

    # variation of the first image sends both images, the CAD reference first
    var = c.post(f"/api/m/airender/projects/{pid}/generate",
                 json={**gen, "settings": {"variants": 1}, "variation_of": {"job": done["id"], "index": 1}})
    service.wait_idle()
    assert [f[0] for f in MockOpenAI.calls[-1]["image"]] == ["ref.png", "var.png"]
    assert c.get(f"/api/m/airender/projects/{pid}/jobs/{var.json()['id']}").json()["state"] == "done"

    # OpenAI errors become plain messages on the job
    for exc, code in ((_err("RateLimitError", 429, {"message": "quota", "code": "insufficient_quota"}), "quota"),
                      (_err("AuthenticationError", 401, {"message": "bad " + KEY}), "bad_key"),
                      (_err("BadRequestError", 400, {"message": "safety system", "code": "moderation_blocked"}),
                       "safety")):
        MockOpenAI.fail = exc
        jid = c.post(f"/api/m/airender/projects/{pid}/generate", json=gen).json()["id"]
        service.wait_idle()
        j = c.get(f"/api/m/airender/projects/{pid}/jobs/{jid}").json()
        assert j["state"] == "failed" and j["error_code"] == code and KEY not in json.dumps(j)
    MockOpenAI.fail = None
    assert len(c.get(f"/api/m/airender/projects/{pid}/jobs").json()["jobs"]) == 5
    assert c.delete(f"/api/m/airender/projects/{pid}/jobs/{jid}").json()["ok"] is True

    # the key never reaches the logs
    assert KEY not in caplog.text

    # another workspace sees nothing; deleting the key disables generation
    c.post("/api/auth/logout")
    signup(c, "air2@x.com", workspace="Other Co")
    assert c.get(f"/api/m/airender/projects/{pid}").status_code == 404
    assert c.get("/api/m/airender/integration").json()["has_key"] is False
    c.post("/api/auth/logout")
    from test_platform import PW

    assert c.post("/api/auth/login", json={"email": "air@x.com", "password": PW}).status_code == 200
    assert c.delete("/api/m/airender/integration/key").json()["has_key"] is False
    r = c.post(f"/api/m/airender/projects/{pid}/generate", json=gen)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_key"


def test_ai_polish_via_api_is_metered(app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c = app_client
    me = signup(c, "polish@x.com")
    pid, _ = _built_project(c)

    async def fake(system: str, prompt: str) -> tuple[str, float | None]:
        return '```fw-prompt\n{"prompt": "A polished brass block on a white sweep, softbox.", "negative": []}\n```', 0.03

    monkeypatch.setattr(refine, "run_refiner_agent", fake)
    before = me["org"]["token_balance"]
    r = c.post(f"/api/m/airender/projects/{pid}/refine", json={"engine": "ai"}).json()
    assert r["engine"] == "ai" and r["tokens"] == 3 and refine.GEOMETRY_CLAUSE in r["prompt"]
    assert c.get("/api/auth/me").json()["org"]["token_balance"] == before - 3


def test_catalog_entry_is_honest() -> None:
    from aicad.platform.catalog import MODULES

    m = MODULES["airender"]
    assert m["status"] == "live" and m["beta"] and "Uses your OpenAI key" in m["tags"]
    assert "not dimensionally exact" in m["summary"] and "illustrative" in m["summary"]
    assert "not dimensionally exact" in CAPTION


def test_real_sdk_request_shape_through_a_mock_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The official SDK builds the multipart edit request (no network: httpx MockTransport answers)."""
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        if req.url.path.endswith("/models"):
            if req.headers.get("authorization") == "Bearer sk-bad-0000000000000000":
                return httpx2.Response(401, json={"error": {"message": "Incorrect API key", "code": "invalid_api_key"}})
            return httpx2.Response(200, json={"object": "list", "data": []})
        if b"moderation-test" in req.read():
            return httpx2.Response(400, json={"error": {"message": "Rejected by the safety system",
                                                        "code": "moderation_blocked"}})
        return httpx2.Response(200, json={"created": 1, "size": "1536x1024", "quality": "low",
                                          "data": [{"b64_json": base64.b64encode(_png()).decode()}],
                                          "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}})

    monkeypatch.setattr(provider, "client_for", lambda key: openai.OpenAI(
        api_key=key, max_retries=0, http_client=httpx2.Client(transport=httpx2.MockTransport(handler))))
    ref = tmp_path / "ref.png"
    ref.write_bytes(_png())
    datas, meta = provider.edit(KEY, [ref, ref], "a prompt", model="gpt-image-2", size="1536x1024", quality="low",
                                background="white", n=1, user_tag="u1")
    body = seen[-1].read()
    assert seen[-1].url.path == "/v1/images/edits" and seen[-1].headers["authorization"] == f"Bearer {KEY}"
    assert b'name="image[]"' in body and b'name="model"' in body and b"gpt-image-2" in body
    assert datas[0][:4] == b"\x89PNG" and meta["usage"]["total_tokens"] == 30
    provider.validate_key(KEY)
    with pytest.raises(provider.RenderError) as e:
        provider.validate_key("sk-bad-0000000000000000")
    assert e.value.code == "bad_key"
    with pytest.raises(provider.RenderError) as e:
        provider.edit(KEY, [ref], "moderation-test", model="gpt-image-2", size="1024x1024", quality="low",
                      background="white", n=1)
    assert e.value.code == "safety"


def test_client_is_the_official_sdk_unless_the_dev_fake_is_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.undo()  # drop the autouse mock of client_for
    monkeypatch.setattr(config, "_settings", config.Settings(env="development", data_dir=tmp_path))
    monkeypatch.delenv("FW_AI_RENDER_FAKE", raising=False)
    assert isinstance(provider.client_for(KEY), openai.OpenAI)
    monkeypatch.setenv("FW_AI_RENDER_FAKE", "1")
    assert isinstance(provider.client_for(KEY), provider.FakeOpenAI)
    monkeypatch.setattr(config, "_settings", config.Settings(env="production", data_dir=tmp_path,
                                                             stripe_secret_key="sk_test_x"))
    assert isinstance(provider.client_for(KEY), openai.OpenAI)  # never fake in production
