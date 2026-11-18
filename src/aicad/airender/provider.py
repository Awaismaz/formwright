"""OpenAI Images API: key validation, image edit with reference images, and plain-language error mapping.

Uses the official `openai` SDK. The call is `images.edit(model, image=[reference, ...], prompt, size, quality,
background, n)`: GPT Image models treat the input images as references, so the part's geometry comes from the render
of the real model. `input_fidelity="high"` is sent only to models that accept it (gpt-image-1.5); gpt-image-2 and
later keep input detail on their own and reject or ignore the parameter.

`client_for(key)` is the single seam: tests monkeypatch it, and `FW_AI_RENDER_FAKE=1` (development only) swaps in
`FakeOpenAI`, which draws a stylised copy of the reference locally, so the app can be walked through without calling
OpenAI. The API key is passed in memory only; it is never logged or written to a job record.
"""

from __future__ import annotations

import base64
import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aicad.airender.keystore import scrub

TIMEOUT_S = 240.0
_FIDELITY_MODELS = ("gpt-image-1.5",)


@dataclass
class RenderError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def fake_mode() -> bool:
    from aicad.platform.config import get_settings

    return os.environ.get("FW_AI_RENDER_FAKE", "") == "1" and not get_settings().production


def client_for(key: str) -> Any:
    if fake_mode():
        return FakeOpenAI(key)
    import openai

    return openai.OpenAI(api_key=key, timeout=TIMEOUT_S, max_retries=1)


# ------------------------------------------------------------------ errors
def _code(e: Any) -> str:
    code = getattr(e, "code", None)
    body = getattr(e, "body", None)
    if not code and isinstance(body, dict):
        inner = body.get("error") if isinstance(body.get("error"), dict) else body
        code = inner.get("code") or inner.get("type")
    return str(code or "").lower()


def map_error(e: Exception, model: str | None = None) -> RenderError:
    """Any SDK exception -> RenderError(code, message for the user). Never includes the key."""
    import openai

    if isinstance(e, RenderError):
        return e
    code = _code(e)
    text = scrub(str(getattr(e, "message", "") or e))
    low = text.lower()
    if isinstance(e, openai.AuthenticationError):
        return RenderError("bad_key", "OpenAI rejected the API key. Check it, or paste a new key in AI Render "
                                      "settings.")
    if isinstance(e, openai.PermissionDeniedError):
        return RenderError("forbidden", "This OpenAI key isn't allowed to use the image model. OpenAI may require "
                                        "organisation verification for GPT Image models (platform.openai.com → "
                                        "Settings → Organization → General).")
    if isinstance(e, openai.RateLimitError):
        if "quota" in code or "quota" in low or "billing" in low:
            return RenderError("quota", "Your OpenAI account is out of credit or has reached its spending limit. "
                                        "Add credit at platform.openai.com → Billing, then try again.")
        return RenderError("rate_limited", "OpenAI is rate-limiting this key. Wait a minute and try again.")
    if isinstance(e, openai.NotFoundError):
        return RenderError("model", f"This OpenAI key can't access the image model {model or ''}".rstrip() + ".")
    if isinstance(e, openai.BadRequestError):
        if any(w in code for w in ("moderation", "content_policy", "safety")) or "safety" in low \
                or "moderation" in low:
            return RenderError("safety", "OpenAI's safety system declined this request. Rephrase the prompt "
                                         "(avoid people, brands or weapon-like wording) and try again.")
        return RenderError("bad_request", "OpenAI couldn't process this request: " + (text[:240] or "bad request"))
    if isinstance(e, openai.APITimeoutError):
        return RenderError("timeout", "OpenAI took too long to answer. Try again, or pick a lower quality or fewer "
                                      "variants.")
    if isinstance(e, openai.APIConnectionError):
        return RenderError("network", "Couldn't reach OpenAI. Check the server's internet connection and try again.")
    if isinstance(e, openai.APIStatusError):
        return RenderError("upstream", "OpenAI had a problem making the image. Try again shortly.")
    return RenderError("unknown", "The AI render failed unexpectedly. Try again.")


# ------------------------------------------------------------------ calls
def validate_key(key: str) -> None:
    """A free call (list models) that proves the key works. Raises RenderError."""
    try:
        client_for(key).models.list()
    except Exception as e:  # noqa: BLE001
        raise map_error(e) from None


def _usage(u: Any) -> dict[str, Any] | None:
    if u is None:
        return None
    d = u.model_dump() if hasattr(u, "model_dump") else dict(u) if isinstance(u, dict) else None
    if not isinstance(d, dict):
        return None
    keep = ("input_tokens", "output_tokens", "total_tokens", "input_tokens_details", "output_tokens_details")
    return {k: d[k] for k in keep if d.get(k) is not None}


def edit(key: str, images: list[Path], prompt: str, *, model: str, size: str, quality: str, background: str,
         n: int, user_tag: str | None = None) -> tuple[list[bytes], dict[str, Any]]:
    """Generate `n` images from the reference image(s). Returns (PNG bytes per image, metadata incl. usage)."""
    kw: dict[str, Any] = {"model": model, "prompt": prompt, "size": size, "quality": quality, "n": n,
                          "output_format": "png",
                          "background": "transparent" if background == "transparent" else "auto"}
    if model.startswith(_FIDELITY_MODELS):
        kw["input_fidelity"] = "high"
    if user_tag:
        kw["safety_identifier"] = user_tag[:64]
    files = [(p.name, p.read_bytes(), "image/png") for p in images]
    try:
        resp = client_for(key).images.edit(image=files if len(files) > 1 else files[0], **kw)
    except Exception as e:  # noqa: BLE001
        raise map_error(e, model) from None
    out: list[bytes] = []
    revised: list[str] = []
    for item in getattr(resp, "data", None) or []:
        b64 = getattr(item, "b64_json", None)
        if b64:
            out.append(base64.b64decode(b64))
        if getattr(item, "revised_prompt", None):
            revised.append(str(item.revised_prompt))
    if not out:
        raise RenderError("empty", "OpenAI returned no image. This usually means the request was filtered; try "
                                   "rephrasing the prompt.")
    meta = {"model": model, "size": getattr(resp, "size", None) or size,
            "quality": getattr(resp, "quality", None) or quality, "usage": _usage(getattr(resp, "usage", None)),
            "revised_prompts": revised[:4] or None}
    return out, meta


# ------------------------------------------------------------------ development fake (no network)
class _Obj:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)

    def model_dump(self) -> dict[str, Any]:
        return dict(self.__dict__)


class FakeOpenAI:
    """Stand-in client for walkthroughs (`FW_AI_RENDER_FAKE=1`). Keys containing "invalid" are rejected like a real
    401; "quota" behaves like an empty account. Images are a toned copy of the reference marked SIMULATED."""

    def __init__(self, key: str) -> None:
        self.key = key
        self.models = _Obj(list=self._list)
        self.images = _Obj(edit=self._edit)

    def _fail(self, status: int, cls: str, body: dict[str, Any]) -> None:
        import httpx2
        import openai

        req = httpx2.Request("POST", "https://api.openai.com/v1/images/edits")
        raise getattr(openai, cls)(body.get("message", "error"), response=httpx2.Response(status, request=req),
                                   body=body)

    def _list(self) -> Any:
        if "invalid" in self.key:
            self._fail(401, "AuthenticationError", {"message": "Incorrect API key provided", "code": "invalid_api_key"})
        return _Obj(data=[_Obj(id="gpt-image-2")])

    def _edit(self, *, image: Any, prompt: str, n: int = 1, size: str = "1024x1024", **kw: Any) -> Any:
        from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

        if "quota" in self.key:
            self._fail(429, "RateLimitError", {"message": "You exceeded your current quota", "code": "insufficient_quota"})
        first = image[0] if isinstance(image, list) else image
        src = Image.open(io.BytesIO(first[1])).convert("RGB")
        w, h = (int(v) for v in size.split("x"))
        tones = [((32, 36, 44), (226, 214, 196)), ((20, 30, 52), (205, 220, 240)), ((40, 30, 24), (240, 222, 190)),
                 ((24, 24, 24), (235, 235, 235))]
        data = []
        for i in range(max(1, n)):
            base = ImageOps.fit(src, (w, h), method=Image.Resampling.LANCZOS)
            g = ImageOps.colorize(ImageOps.grayscale(base), *tones[i % len(tones)])
            g = ImageEnhance.Contrast(g).enhance(1.25).filter(ImageFilter.SMOOTH)
            d = ImageDraw.Draw(g)
            d.rectangle([0, h - 34, w, h], fill=(0, 0, 0))
            d.text((12, h - 26), "SIMULATED AI RENDER (development fake, no OpenAI call)", fill=(255, 255, 255))
            buf = io.BytesIO()
            g.save(buf, "PNG")
            data.append(_Obj(b64_json=base64.b64encode(buf.getvalue()).decode(), revised_prompt=None))
        return _Obj(data=data, size=size, quality=kw.get("quality"),
                    usage=_Obj(input_tokens=1200, output_tokens=4160 * n, total_tokens=1200 + 4160 * n))
