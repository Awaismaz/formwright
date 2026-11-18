"""AI Render Studio: marketing visuals of a verified part made with OpenAI image generation, using the
workspace's OWN OpenAI API key (bring-your-own-key).

A render of the real geometry (a Mesh Studio Cycles render, else the build's thumbnail) is always sent as the
reference image, and the prompt carries a geometry-preservation clause, but the output is an AI image: illustrative,
never dimensionally exact. Every image is captioned with `CAPTION`.

- `keystore`  encrypts the key at rest (Fernet; server secret from FW_SECRET_KEY or a generated dev secret)
- `options`   the scene / finish / lighting / camera / background / style catalogue that feeds the prompt
- `refine`    the prompt refinement layer: deterministic template composer + an optional one-shot Claude polish
- `provider`  the OpenAI Images API call (edit with reference images), key validation and error mapping
- `service`   reference-image selection and the background generation jobs, stored under `<workspace>/airender/`
"""

from __future__ import annotations

CAPTION = ("AI-generated visual — not dimensionally exact; use Mesh Studio renders or drawings for exact "
           "geometry")

CONSENT_TEXT = ("To make AI renders, Formwright sends the reference image of your part and the image prompt to "
                "OpenAI (a third party) using your workspace's OpenAI API key. OpenAI processes them under your "
                "own OpenAI account terms. Nothing else from your project (CAD files, drawings, parameters) is sent.")
CONSENT_VERSION = 1
