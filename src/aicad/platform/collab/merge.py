"""Three-way merge of a part (pure, deterministic, no build).

A part's model script has three kinds of content, merged three different ways:

- **parameters**: top-level numeric assignments (``T = 10.0``): merged per name (one side changed = take it; both
  changed to different values = conflict);
- **manual features**: the app-managed feature list (JSON-like dicts with ids): merged per feature id (added,
  deleted, edited on one side = take it; edited on both, or edited on one and deleted on the other = conflict);
- **design source** (what the design agent wrote): a line-based 3-way text merge (the classic merge3 algorithm over
  ``difflib`` matching blocks) with parameter values and the manual-feature block masked out first, so a parameter
  edit never collides with a neighbouring line.

`merge_model` returns the merged script, or the list of conflicts. A conflict is resolved by id with ``"ours"``
(main), ``"theirs"`` (the branch) or ``{"text": ...}`` / ``{"value": ...}`` (a reconciled value, e.g. proposed by the
design agent and accepted by the user).
"""

from __future__ import annotations

import ast
import pprint
import re
from difflib import SequenceMatcher
from typing import Any

BLOCK_START = "# --- Formwright manual features (managed by the app; edit them in the feature tree) ---"
BLOCK_END = "# --- end manual features ---"
PARAM_RE = re.compile(r"^(?P<name>[A-Z][A-Z0-9_]*)(?P<sp>\s*=\s*)(?P<val>-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)(?P<rest>\s*(?:#.*)?)$")
MASK = "⁣FWPARAM⁣"

Number = float | int


# ----------------------------------------------------------------------------- the three parts of a script
def read_manual(src: str) -> list[dict[str, Any]]:
    if BLOCK_START not in src:
        return []
    block = src[src.index(BLOCK_START):src.index(BLOCK_END)] if BLOCK_END in src else src[src.index(BLOCK_START):]
    for node in ast.parse(block).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "MANUAL_FEATURES":
            return list(ast.literal_eval(node.value))
    return []


def strip_manual(src: str) -> str:
    if BLOCK_START not in src:
        return src
    end = src.index(BLOCK_END) + len(BLOCK_END) if BLOCK_END in src else len(src)
    return src[:src.index(BLOCK_START)].rstrip("\n") + "\n" + src[end:].lstrip("\n")


def write_manual(src: str, feats: list[dict[str, Any]]) -> str:
    src = strip_manual(src)
    if not feats:
        return src.rstrip("\n") + "\n"
    block = (f"\n\n{BLOCK_START}\nfrom aicad import fw as _fw\n\n"
             f"MANUAL_FEATURES = {pprint.pformat(feats, width=100, sort_dicts=False)}\n"
             f"result = _fw.apply_manual(result, MANUAL_FEATURES)\n{BLOCK_END}\n")
    return src.rstrip("\n") + block


def _num(s: str) -> Number:
    return int(s) if re.fullmatch(r"-?\d+", s) else float(s)


def read_params(src: str) -> dict[str, Number]:
    """Top-level numeric assignments of the design source (first assignment of each name wins)."""
    out: dict[str, Number] = {}
    for line in strip_manual(src).splitlines():
        m = PARAM_RE.match(line)
        if m and m["name"] not in out:
            out[m["name"]] = _num(m["val"])
    return out


def mask_params(src: str) -> list[str]:
    """Source lines with parameter values masked (so value edits are merged per parameter, not as text)."""
    seen: set[str] = set()
    lines = []
    for line in strip_manual(src).splitlines():
        m = PARAM_RE.match(line)
        if m and m["name"] not in seen:
            seen.add(m["name"])
            line = f"{m['name']}{m['sp']}{MASK}{m['rest']}"
        lines.append(line)
    return lines


def unmask(lines: list[str], values: dict[str, Number]) -> str:
    out = []
    for line in lines:
        if MASK in line:
            name = line.split("=", 1)[0].strip()
            v = values.get(name)
            if v is None:
                continue  # the parameter was removed on the side we took
            lit = str(v) if isinstance(v, int) else repr(float(v))
            line = line.replace(MASK, lit)
        out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


# ----------------------------------------------------------------------------- merge3 over lines
def _intersect(ra: tuple[int, int], rb: tuple[int, int]) -> tuple[int, int] | None:
    lo, hi = max(ra[0], rb[0]), min(ra[1], rb[1])
    return (lo, hi) if lo < hi else None


def _sync_regions(base: list[str], a: list[str], b: list[str]) -> list[tuple[int, int, int, int, int, int]]:
    am = SequenceMatcher(None, base, a, autojunk=False).get_matching_blocks()
    bm = SequenceMatcher(None, base, b, autojunk=False).get_matching_blocks()
    ia = ib = 0
    out = []
    while ia < len(am) and ib < len(bm):
        abase, amatch, alen = am[ia]
        bbase, bmatch, blen = bm[ib]
        i = _intersect((abase, abase + alen), (bbase, bbase + blen))
        if i:
            lo, hi = i
            asub, bsub = amatch + (lo - abase), bmatch + (lo - bbase)
            out.append((lo, hi, asub, asub + hi - lo, bsub, bsub + hi - lo))
        if abase + alen < bbase + blen:
            ia += 1
        else:
            ib += 1
    out.append((len(base), len(base), len(a), len(a), len(b), len(b)))
    return out


def merge3(base: list[str], ours: list[str], theirs: list[str]) -> list[dict[str, Any]]:
    """Chunks of a 3-way line merge: {"kind": "same"|"ours"|"theirs"|"both"|"conflict", "base", "ours", "theirs"}."""
    chunks: list[dict[str, Any]] = []
    iz = ia = ib = 0
    for zmatch, zend, amatch, aend, bmatch, bend in _sync_regions(base, ours, theirs):
        if iz < zmatch or ia < amatch or ib < bmatch:
            bz, ba, bb = base[iz:zmatch], ours[ia:amatch], theirs[ib:bmatch]
            if ba == bb:
                kind = "both" if ba != bz else "same"
            elif ba == bz:
                kind = "theirs"
            elif bb == bz:
                kind = "ours"
            else:
                kind = "conflict"
            chunks.append({"kind": kind, "base": bz, "ours": ba, "theirs": bb})
        if zmatch < zend:
            chunks.append({"kind": "same", "base": base[zmatch:zend], "ours": base[zmatch:zend],
                           "theirs": base[zmatch:zend]})
        iz, ia, ib = zend, aend, bend
    return chunks


# ----------------------------------------------------------------------------- structured merges
def merge_params(base: dict[str, Number], ours: dict[str, Number], theirs: dict[str, Number]
                 ) -> tuple[dict[str, Number], list[dict[str, Any]]]:
    merged: dict[str, Number] = {}
    conflicts = []
    for k in sorted(set(base) | set(ours) | set(theirs)):
        b, o, t = base.get(k), ours.get(k), theirs.get(k)
        if o == t:
            v = o
        elif o == b:
            v = t
        elif t == b:
            v = o
        else:
            conflicts.append({"id": f"param:{k}", "kind": "param", "key": k, "base": b, "ours": o, "theirs": t})
            v = o
        if v is not None:
            merged[k] = v
    return merged, conflicts


def merge_features(base: list[dict[str, Any]], ours: list[dict[str, Any]], theirs: list[dict[str, Any]]
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Merge feature lists by id. Order: main's order, with features new on the branch inserted after the feature
    that precedes them on the branch."""
    B = {f["id"]: f for f in base}
    O = {f["id"]: f for f in ours}
    T = {f["id"]: f for f in theirs}
    conflicts = []
    chosen: dict[str, dict[str, Any] | None] = {}
    for fid in list(dict.fromkeys([*O, *T, *B])):
        b, o, t = B.get(fid), O.get(fid), T.get(fid)
        if o == t:
            v = o
        elif o == b:
            v = t
        elif t == b:
            v = o
        else:
            name = (o or t or b or {}).get("name") or fid
            conflicts.append({"id": f"feature:{fid}", "kind": "feature", "key": fid, "name": name,
                              "base": b, "ours": o, "theirs": t})
            v = o
        chosen[fid] = v
    order = [f["id"] for f in ours if chosen.get(f["id"]) is not None]
    for i, f in enumerate(theirs):
        fid = f["id"]
        if fid in order or chosen.get(fid) is None:
            continue
        prev = next((theirs[j]["id"] for j in range(i - 1, -1, -1) if theirs[j]["id"] in order), None)
        order.insert(order.index(prev) + 1 if prev else 0, fid)
    return [chosen[i] for i in order if chosen[i] is not None], conflicts  # type: ignore[misc]


# ----------------------------------------------------------------------------- whole script
def same_model(a: str, b: str) -> bool:
    norm = lambda s: "\n".join(x.rstrip() for x in s.strip().splitlines())
    return norm(a) == norm(b)


def merge_model(base: str, ours: str, theirs: str, resolutions: dict[str, Any] | None = None) -> dict[str, Any]:
    """3-way merge of a model script. Returns {"source": merged or None, "conflicts": [unresolved...],
    "all_conflicts": [...], "summary": {...}}. `ours` = main (target), `theirs` = the branch."""
    res = resolutions or {}
    # parameters
    params, pconf = merge_params(read_params(base), read_params(ours), read_params(theirs))
    # manual features
    feats, fconf = merge_features(read_manual(base), read_manual(ours), read_manual(theirs))
    # design source
    chunks = merge3(mask_params(base), mask_params(ours), mask_params(theirs))
    sconf = []
    lines: list[str] = []
    n = 0
    for ch in chunks:
        if ch["kind"] == "conflict":
            n += 1
            cid = f"source:{n}"
            sconf.append({"id": cid, "kind": "source", "key": str(n),
                          "base": unmask(ch["base"], read_params(base)), "ours": unmask(ch["ours"], read_params(ours)),
                          "theirs": unmask(ch["theirs"], read_params(theirs)), "_chunk": ch})
            r = res.get(cid)
            if r == "theirs":
                lines += ch["theirs"]
            elif isinstance(r, dict) and isinstance(r.get("text"), str):
                lines += r["text"].rstrip("\n").splitlines()
            else:
                lines += ch["ours"]
        else:
            lines += ch["theirs"] if ch["kind"] == "theirs" else ch["ours"]
    # apply parameter / feature resolutions
    for c in pconf:
        r = res.get(c["id"])
        v = c["theirs"] if r == "theirs" else (r.get("value") if isinstance(r, dict) else c["ours"])
        if v is None:
            params.pop(c["key"], None)
        else:
            params[c["key"]] = v
    for c in fconf:
        r = res.get(c["id"])
        pick = c["theirs"] if r == "theirs" else c["ours"]
        idx = next((i for i, f in enumerate(feats) if f["id"] == c["key"]), None)
        if pick is None and idx is not None:
            feats.pop(idx)
        elif pick is not None and idx is not None:
            feats[idx] = pick
        elif pick is not None:
            feats.append(pick)
    all_conf = [*pconf, *fconf, *sconf]
    unresolved = [c for c in all_conf if c["id"] not in res]
    for c in sconf:
        c.pop("_chunk", None)
    src = write_manual(unmask(lines, params), feats)
    return {"source": None if unresolved else src, "conflicts": unresolved, "all_conflicts": all_conf,
            "summary": {"params": len(params), "features": len(feats),
                        "conflicts": {"param": len(pconf), "feature": len(fconf), "source": len(sconf)}}}


def diff_params(a: dict[str, Number], b: dict[str, Number]) -> dict[str, dict[str, Any]]:
    return {k: {"from": a.get(k), "to": b.get(k)} for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}


def diff_features(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    A = {f["id"]: f for f in a}
    B = {f["id"]: f for f in b}
    out = []
    for fid in dict.fromkeys([*A, *B]):
        x, y = A.get(fid), B.get(fid)
        if x == y:
            continue
        ref = y or x or {}
        out.append({"id": fid, "name": ref.get("name") or ref.get("op") or fid, "op": ref.get("op"),
                    "change": "added" if x is None else "removed" if y is None else "edited",
                    "fields": sorted(k for k in set(x or {}) | set(y or {}) if (x or {}).get(k) != (y or {}).get(k))
                    if x and y else []})
    return out
