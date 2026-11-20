"""Find parts you already made: deterministic shape signatures and similarity across a workspace's projects.

A signature is computed once per verified build from `out/status.json` and `out/topo.json`, and cached in
`out/signature.json`. It is orientation-free (the bounding-box dimensions sorted), and records the volume, fill ratio,
surface mix (planar/cylindrical/conical/other area fractions) and a census of cylindrical faces by diameter.

Similarity blends three ideas engineers use when they say "we've made this before": the same envelope (size), the same
proportions and character (scale-free shape), and the same holes/bosses (cylinder census). Every match comes with
plain reasons.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

SIG_VERSION = 1
KINDS = ("plane", "cylinder", "cone", "other")


def signature(ws: Path) -> dict[str, Any] | None:
    """Shape signature of a project's latest verified build (cached per build), or None if there is none."""
    out = ws / "out"
    try:
        st = json.loads((out / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    fp = st.get("fingerprint") or {}
    if not st.get("ok") or not fp.get("bbox") or not fp.get("volume"):
        return None
    cache = out / "signature.json"
    try:
        sig = json.loads(cache.read_text(encoding="utf-8"))
        if sig.get("build_id") == st.get("build_id") and sig.get("v") == SIG_VERSION:
            return sig
    except (OSError, ValueError):
        pass
    dims = sorted((float(x) for x in fp["bbox"]), reverse=True)
    vol = float(fp["volume"])
    area = {k: 0.0 for k in KINDS}
    cyl: dict[str, int] = {}
    try:
        topo = json.loads((out / "topo.json").read_text(encoding="utf-8"))
        for f in topo.get("faces", []):
            t = f.get("type")
            k = t if t in ("plane", "cylinder", "cone") else "other"
            area[k] += float(f.get("area", 0))
            if t == "cylinder" and f.get("radius"):
                d = f"{2 * float(f['radius']):.2f}"
                cyl[d] = cyl.get(d, 0) + 1
    except (OSError, ValueError):
        pass
    total = sum(area.values()) or 1.0
    sig = {"v": SIG_VERSION, "build_id": st.get("build_id"), "dims": [round(d, 4) for d in dims], "volume": round(vol, 4),
           "fill": round(vol / max(dims[0] * dims[1] * dims[2], 1e-9), 5),
           "mix": {k: round(v / total, 4) for k, v in area.items()}, "cyl": dict(sorted(cyl.items())),
           "material": st.get("material"), "features": [f.get("name") for f in st.get("features") or []][:30]}
    try:
        cache.write_text(json.dumps(sig), encoding="utf-8")
    except OSError:
        pass
    return sig


def _size_sim(a: list[float], b: list[float]) -> float:
    """1.0 for the same envelope; about 0.74 when every dimension differs by 10 %."""
    return math.exp(-sum(abs(math.log(max(x, 1e-6) / max(y, 1e-6))) for x, y in zip(a, b, strict=True)))


def _shape_sim(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Scale-free: proportions, fill ratio and surface mix."""
    ra = [a["dims"][1] / a["dims"][0], a["dims"][2] / a["dims"][0]]
    rb = [b["dims"][1] / b["dims"][0], b["dims"][2] / b["dims"][0]]
    prop = sum(abs(math.log(max(x, 1e-6) / max(y, 1e-6))) for x, y in zip(ra, rb, strict=True))
    fill = abs(a["fill"] - b["fill"]) * 4
    mix = sum(abs(a["mix"].get(k, 0) - b["mix"].get(k, 0)) for k in KINDS) * 1.5
    return math.exp(-(prop + fill + mix))


def _cyl_sim(a: dict[str, int], b: dict[str, int]) -> tuple[float, list[str]]:
    """Weighted Jaccard of cylinder diameters (0.1 mm tolerance) and the shared ones, largest count first."""
    if not a and not b:
        return 1.0, []
    keys = sorted(set(a) | set(b), key=float)
    inter = union = 0
    shared = []
    used: set[str] = set()
    for k in keys:
        if k in used:
            continue
        near = [x for x in keys if abs(float(x) - float(k)) <= 0.1 and x not in used]
        used.update(near)
        ca = sum(a.get(x, 0) for x in near)
        cb = sum(b.get(x, 0) for x in near)
        inter += min(ca, cb)
        union += max(ca, cb)
        if min(ca, cb) > 0:
            shared.append((min(ca, cb), float(k)))
    shared.sort(reverse=True)
    return (inter / union if union else 1.0), [f"{n} × Ø{d:g}" if n > 1 else f"Ø{d:g}" for n, d in shared[:3]]


def _fmt_dims(d: list[float]) -> str:
    return " × ".join(f"{x:.4g}" for x in d)


def compare(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """Score 0 to 100 plus reasons, comparing signature `b` against the reference `a`."""
    size = _size_sim(a["dims"], b["dims"])
    shape = _shape_sim(a, b)
    holes, shared = _cyl_sim(a.get("cyl", {}), b.get("cyl", {}))
    score = 100 * (0.45 * size + 0.35 * shape + 0.20 * holes)
    reasons = []
    worst = max(abs(x / y - 1) for x, y in zip(a["dims"], b["dims"], strict=True))
    if worst <= 0.02:
        reasons.append(f"Same envelope {_fmt_dims(b['dims'])} mm" + (" (exact)" if worst < 0.0005 else f" (±{worst * 100:.1f} %)"))
    elif shape > 0.8:
        k = (b["dims"][0] * b["dims"][1] * b["dims"][2] / (a["dims"][0] * a["dims"][1] * a["dims"][2])) ** (1 / 3)
        reasons.append(f"Same shape, scaled ×{k:.2f} ({_fmt_dims(b['dims'])} mm)")
    else:
        reasons.append(f"Envelope {_fmt_dims(b['dims'])} mm")
    if shared:
        reasons.append("Same diameters: " + " · ".join(shared))
    if a.get("material") and a.get("material") == b.get("material"):
        reasons.append(f"Same material ({b['material']})")
    common = [f for f in b.get("features", []) if f and f in set(a.get("features", []))]
    if common:
        reasons.append("Shared features: " + ", ".join(common[:3]))
    return {"score": round(score, 1), "size": round(size, 3), "shape": round(shape, 3), "holes": round(holes, 3),
            "reasons": reasons}


_NUM = r"(\d+(?:\.\d+)?)"


def parse_size_query(q: str) -> list[float] | None:
    """'120x80x10', '120 × 80', 'Ø50 x 200', '120*80 mm' → dimensions (largest first); None if not a size query."""
    s = q.lower().replace("×", "x").replace("*", "x").replace(",", ".")
    m = re.search(rf"{_NUM}\s*(?:mm)?\s*x\s*{_NUM}(?:\s*(?:mm)?\s*x\s*{_NUM})?", s)
    if not m:
        return None
    vals = [float(v) for v in m.groups() if v is not None]
    if re.search(r"(ø|dia|diameter)\s*" + re.escape(m.group(1)), s) and len(vals) == 2:
        vals = [vals[0], vals[0], vals[1]]  # Ø50 x 200 → a 50 × 50 × 200 envelope
    return sorted(vals, reverse=True)


def size_match(dims: list[float], sig: dict[str, Any]) -> dict[str, Any]:
    """How well a part's envelope matches 2 or 3 requested dimensions (best pairing for 2)."""
    have = sig["dims"]
    if len(dims) == 3:
        s = _size_sim(dims, have)
        used = have
    else:
        pairs = [(have[i], have[j]) for i in range(3) for j in range(i + 1, 3)]
        s, used = max((_size_sim(dims, list(p)), list(p)) for p in pairs)
    worst = max(abs(x / y - 1) for x, y in zip(used, dims, strict=False))
    return {"score": round(100 * s, 1), "reasons": [f"Envelope {_fmt_dims(have)} mm"
                                                     + (" (exact)" if worst < 0.005 else f" (within {worst * 100:.0f} %)")]}
