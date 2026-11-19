"""The deterministic sizing pass: fill what the brief leaves open from the connections and the standards.

``resolve(graph)`` returns a new graph where every value the downstream compilers need is present and says where it
came from. Order matters and is fixed:

1. implied parts: a keyed hub gets its key, a ring-retained part its retaining ring (unless the brief excludes keys
   or rings: then a keyed hub becomes a plain fit, said in the notes);
2. bearings with a written designation fix their journals; shafts get their seat Ø (written, from a hub's written
   bore, from a bearing, from the input shaft and the ratio for an output shaft, else Ø20 assumed);
3. a shaft with a shoulder stop is stepped; its larger step is ``icd.shoulder_for`` unless written;
4. gears: teeth from the mesh ratio when missing (z1 = 20, z2 = round(i z1)), module 2 assumed, face width 10 m,
   bore = the seat Ø of the shaft they sit on;
5. keys from DIN 6885-1 for the seat Ø, length from the hub width; bearings from ISO 15 for the journal; rings
   from DIN 471; the mesh's centre distance a = m (z1 + z2) / 2 and ratio z2 / z1.
"""

from __future__ import annotations

import re
from typing import Any

from aicad.graph import registry, standards
from aicad.graph.model import Component, Connection, DesignGraph, Param
from aicad.toolbox import BEARING

DEFAULT_SHAFT_D = 20.0
DEFAULT_MODULE = 2.0
DEFAULT_TEETH = 30
DEFAULT_SHAFT_LENGTH = 80.0   # a shaft sub-assembly with nothing else to size it (the standard planner's value)


def _ratio(g: DesignGraph) -> float | None:
    for c in g.connections:
        if c.kind == "gear_mesh" and isinstance(c.v("ratio"), int | float) and c.v("ratio") > 0:
            return float(c.v("ratio"))
    m = re.search(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", g.brief or "")
    if m and float(m.group(1)) > 0 and float(m.group(2)) > 0:
        a, b = float(m.group(1)), float(m.group(2))
        r = max(a, b) / min(a, b)
        if 1 < r <= 10:
            return r
    return None


def _hosted(g: DesignGraph, shaft: str, *kinds: str) -> list[tuple[Connection, Component]]:
    out = []
    for c in g.connections:
        if c.host == shaft and c.kind in kinds:
            comp = g.comp(c.guest)
            if comp is not None:
                out.append((c, comp))
    return out


def _host_shaft(g: DesignGraph, cid: str) -> Component | None:
    for c in g.connections:
        if c.guest == cid and c.kind in ("keyed_hub", "hub_fit"):
            return g.comp(c.host)
    return None


def _add_implied(g: DesignGraph) -> None:
    excluded = set(g.constraints.excluded)
    for c in list(g.connections):
        ct = registry.connection(c.kind)
        if ct is None or not ct.via_required:
            continue
        need = ct.via[0]
        if any((g.comp(v) or Component(id="", kind="", name="")).kind == need for v in c.via):
            continue
        scope_kind = registry.COMPONENTS[need].scope
        guest = g.comp(c.guest)
        if scope_kind in excluded or (g.constraints.exclusive and g.constraints.named and scope_kind not in
                                      g.constraints.named):
            if c.kind == "keyed_hub":
                c.kind = "hub_fit"
                g.notes.append(f"The brief leaves out keys, so {guest.name if guest else c.guest} is a plain fit "
                               "on its shaft.")
            continue
        n_same = sum(1 for x in g.connections if x.kind == c.kind)
        base = registry.COMPONENTS[need].label
        name = base if n_same == 1 else f"{guest.name if guest else 'Hub'} {base.split()[-1].lower()}"
        new = Component(id=g.new_id(name), kind=need, name=name, qty=1, group=guest.group if guest else "",
                        implied=True)
        g.components.append(new)
        c.via.append(new.id)
        g.notes.append(f"Added a {base.lower()} ({registry.COMPONENTS[need].standard}) for "
                       f"{guest.name if guest else c.guest}: the {ct.label} needs one.")


def resolve(graph: DesignGraph) -> DesignGraph:
    g = graph.model_copy(deep=True)
    _add_implied(g)
    ratio = _ratio(g)

    # 2. bearings with a written designation fix their shaft's journal
    for c in g.connections:
        if c.kind != "bearing_journal":
            continue
        sh, br = g.comp(c.host), g.comp(c.guest)
        if sh is None or br is None:
            continue
        des = br.v("designation")
        if isinstance(des, int | float) and int(des) in BEARING:
            d = standards.bearing_dims(int(des))["d"]
            if sh.v("d") is None and sh.v("journal_d") is None:
                sh.set("d", d, "standard", f"the bore of the {int(des)}")
            sh.set("journal_d", d, "standard", f"the bore of the {int(des)}")

    # shaft seat Ø: written, a hub's written bore, else (an output shaft) from the input and the ratio, else assumed
    shafts = g.of_kind("shaft")
    for sh in shafts:
        if sh.v("d") is not None:
            continue
        bores = [h.v("bore") for _c, h in _hosted(g, sh.id, "keyed_hub", "hub_fit") if h.v("bore") is not None]
        if bores:
            sh.set("d", float(bores[0]), "rule", "the bore of the hub it carries")
    ins = [s for s in shafts if s.v("role") == "input" or re.search(r"\binput\b|\bpinion\b", s.name, re.IGNORECASE)]
    for sh in shafts:
        if sh.v("d") is not None:
            continue
        out = sh.v("role") == "output" or re.search(r"\boutput\b", sh.name, re.IGNORECASE)
        d_in = next((s.v("d") for s in ins if s.v("d") is not None), None)
        if out and ratio and d_in:
            sh.set("d", standards.output_shaft(float(d_in), ratio), "rule",
                   f"Ø{float(d_in):g} x {ratio:g}^(1/3), up to a bearing bore")
        elif out and ratio and not d_in:
            for s in ins:
                if s.v("d") is None:
                    s.set("d", DEFAULT_SHAFT_D, "assumed", "no size in the brief")
            sh.set("d", standards.output_shaft(DEFAULT_SHAFT_D, ratio), "rule",
                   f"Ø{DEFAULT_SHAFT_D:g} x {ratio:g}^(1/3), up to a bearing bore")
        else:
            sh.set("d", DEFAULT_SHAFT_D, "assumed", "no size in the brief")

    # 3. stepped shafts: a shoulder stop on it, or "stepped" written
    for sh in shafts:
        stops = _hosted(g, sh.id, "shoulder_stop")
        if stops or sh.v("shoulder_d") is not None:
            sh.set("stepped", True, "rule", "a part locates against its shoulder")
        if sh.v("stepped") is True and sh.v("shoulder_d") is None:
            sh.set("shoulder_d", standards.shoulder_for(float(sh.v("d"))), "rule", standards.source_note("shoulder"))
        if sh.v("length") is None and sh.v("stepped") is True and not g.of_kind("bearing", "housing"):
            sh.set("length", DEFAULT_SHAFT_LENGTH, "assumed", "no length in the brief")

    # 4. gears: teeth from the ratio, module, face width, bore
    gears = g.of_kind("spur_gear")
    for c in g.connections:
        if c.kind != "gear_mesh":
            continue
        a, b = g.comp(c.host), g.comp(c.guest)
        if a is None or b is None:
            continue
        r = c.v("ratio") or ratio
        if r and a.v("teeth") is None and b.v("teeth") is None:
            z1, z2 = standards.teeth_for_ratio(float(r))
            a.set("teeth", z1, "rule", f"pinion z = {z1} (no undercut at 20 deg)")
            b.set("teeth", z2, "rule", f"round({float(r):g} x {z1})")
        elif r and a.v("teeth") is not None and b.v("teeth") is None:
            b.set("teeth", round(float(r) * int(a.v("teeth"))), "rule", f"ratio {float(r):g}")
        elif r and b.v("teeth") is not None and a.v("teeth") is None:
            a.set("teeth", round(int(b.v("teeth")) / float(r)), "rule", f"ratio {float(r):g}")
        m = a.v("module") or b.v("module")
        if m is not None:
            for x in (a, b):
                if x.v("module") is None:
                    x.set("module", float(m), "rule", "meshing gears share their module")
    for gr in gears:
        if gr.v("module") is None:
            gr.set("module", DEFAULT_MODULE, "assumed", "no module in the brief")
        if gr.v("teeth") is None:
            gr.set("teeth", DEFAULT_TEETH, "assumed", "no teeth count in the brief")
        if gr.v("face_width") is None:
            gr.set("face_width", standards.FACE_PER_MODULE * float(gr.v("module")), "rule", standards.source_note("face"))
        sh = _host_shaft(g, gr.id)
        if sh is not None and sh.v("d") is not None:
            gr.set("bore", float(sh.v("d")), "rule", f"bored to the Ø{float(sh.v('d')):g} seat")
    for hb in g.of_kind("pulley", "hub", "spacer"):
        sh = _host_shaft(g, hb.id)
        if sh is not None and sh.v("d") is not None:
            hb.set("bore", float(sh.v("d")), "rule", f"bored to the Ø{float(sh.v('d')):g} seat")

    # 5. keys, bearings, rings, the mesh
    for c in g.connections:
        sh, guest = g.comp(c.host), g.comp(c.guest)
        if c.kind == "keyed_hub" and sh is not None and guest is not None:
            d = float(sh.v("d"))
            width = guest.v("face_width") or guest.v("width") or guest.v("length")
            for vid in c.via:
                k = g.comp(vid)
                if k is None or k.kind != "key":
                    continue
                k.set("shaft_d", d, "rule", "the seat it sits in")
                try:
                    row = standards.key_for_shaft(d)
                except ValueError:
                    continue
                for n, v in row.items():
                    k.set(n, v, "standard", standards.source_note("key", d), force=True)
                if width:
                    k.set("length", standards.key_length(row["b"], float(width)), "rule",
                          "floor(max(b + 2, B - 2)) for the hub width")
            c.params.setdefault("fit", _p(standards.FIT_HUB, "standard", "ISO 286 transition fit"))
        elif c.kind == "bearing_journal" and sh is not None and guest is not None:
            jd = float(sh.v("journal_d") or sh.v("d"))
            des = guest.v("designation")
            got = standards.bearing_for_journal(jd, guest.v("series"), int(des) if des is not None else None)
            if got is not None:
                guest.set("designation", got, "standard", standards.source_note("bearing", jd))
                for n, v in standards.bearing_dims(got).items():
                    guest.set(n, v, "standard", f"ISO 15 {got}", force=True)
                sh.set("journal_d", standards.bearing_dims(got)["d"], "standard", f"the bore of the {got}")
            c.params.setdefault("count", _p(2, "rule", "two bearings per shaft"))
        elif c.kind == "ring_retained" and sh is not None:
            d = float(sh.v("d"))
            for vid in c.via:
                r = g.comp(vid)
                if r is not None and r.kind == "retaining_ring":
                    r.set("shaft_d", d, "rule", "the shaft it sits on")
                    try:
                        row = standards.circlip_groove(d)
                    except ValueError:
                        continue
                    for n in ("d2", "m", "s"):
                        r.set(n, row[n], "standard", standards.source_note("ring", d), force=True)
        elif c.kind == "gear_mesh" and sh is not None and guest is not None and sh.v("module") is not None                 and sh.v("teeth") is not None and guest.v("teeth") is not None:
            a = standards.centre_distance(float(sh.v("module")), int(sh.v("teeth")), int(guest.v("teeth")))
            c.params["centre_distance"] = _p(a, "rule", standards.source_note("mesh"))
            c.params["ratio"] = _p(round(int(guest.v("teeth")) / int(sh.v("teeth")), 4), "rule", "z2 / z1")
    return g


def _p(value: Any, source: str, note: str = "") -> Param:
    return Param(value=value, source=source, note=note)  # type: ignore[arg-type]
