import type { AgentEdit, ImpactChange, ManualFeature } from "@/lib/types";
import { edgeMid } from "@/viewer/measure";
import type { Pick, Topo, V3 } from "@/viewer/types";

/** DS-035: how an agent edit opens the real PropertyManager (pure, so it is unit-tested). */
export type PmOpen =
  | { kind: "feature"; op: ManualFeature["op"]; editing: ManualFeature | null; preset: Record<string, unknown>; selection: Pick[]; note?: string }
  | { kind: "params"; rows: NonNullable<AgentEdit["params"]> }
  | { kind: "error"; message: string };

const dist = (a: V3, b: V3) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

function tol(topo: Topo): number {
  const b = topo.bbox;
  return Math.max(0.05, 2e-3 * Math.hypot(b[3] - b[0], b[4] - b[1], b[5] - b[2]));
}

/** The viewer picks for the edit's targets. Same build: the server's ids. Another build (the model changed since the
 *  suggestion): each target point is matched to the nearest edge middle / face centre, or dropped. */
export function targetPicks(edit: AgentEdit, topo: Topo | null, buildId?: string | number | null): { picks: Pick[]; lost: number } {
  const t = edit.targets;
  if (!t || !topo) return { picks: [], lost: t?.picks.length ?? 0 };
  const same = edit.build_id != null && buildId != null && String(edit.build_id) === String(buildId);
  const out: Pick[] = [];
  let lost = 0;
  for (const p of t.picks) {
    if (t.kind === "edge") {
      let id: number | null = same && topo.edges[p.id] ? p.id : null;
      if (id === null) {
        let best = Infinity;
        for (const e of topo.edges) { const d = dist(edgeMid(topo, e.id), p.point); if (d < best) { best = d; id = e.id; } }
        if (best > tol(topo)) id = null;
      }
      if (id === null) lost++; else if (!out.some(x => x.kind === "edge" && x.id === id)) out.push({ kind: "edge", id, point: edgeMid(topo, id) });
    } else {
      let id: number | null = same && topo.faces[p.id] ? p.id : null;
      if (id === null) {
        let best = Infinity;
        for (const f of topo.faces) { const d = dist(f.center, p.point); if (d < best) { best = d; id = f.id; } }
        if (best > tol(topo)) id = null;
      }
      if (id === null) lost++; else if (!out.some(x => x.kind === "face" && x.id === id)) out.push({ kind: "face", id, point: topo.faces[id]!.center });
    }
  }
  return { picks: out, lost };
}

/** Map an agent edit onto the PropertyManager: the op, the feature being edited (with the new values merged in), the
 *  preset for a new feature, and the selection to highlight. */
export function prefillPm(edit: AgentEdit, topo: Topo | null, manual: ManualFeature[], buildId?: string | number | null): PmOpen {
  if (edit.op === "multi") return edit.steps?.length ? prefillPm(edit.steps[0]!, topo, manual, buildId) : { kind: "error", message: "No change to make" };
  if (edit.op === "params") return edit.params && Object.keys(edit.params).length ? { kind: "params", rows: edit.params } : { kind: "error", message: "No parameter to change" };
  if (edit.op === "extrude" || edit.op === "pattern") {
    // changes to an existing hand-made feature: its own panel (the sketch editor for a sketched extrude), new values merged in
    const e = manual.find(m => m.id === edit.feature_id);
    if (!e) return { kind: "error", message: "That feature is no longer in the feature tree" };
    const v = edit.values;
    let merged: ManualFeature = { ...e };
    if (edit.op === "extrude") merged = { ...merged, ...(v.end ? { end: v.end } : {}), ...(v.distance != null ? { distance: v.distance } : {}) };
    else {
      if (v.count != null) merged = { ...merged, count: v.count };
      if (v.spacing != null && e.step) { const n = Math.hypot(...e.step) || 1; merged = { ...merged, step: e.step.map(c => +(c / n * v.spacing!).toFixed(9)) as [number, number, number] }; }
      if (v.angle != null) merged = { ...merged, angle: v.angle };
    }
    return { kind: "feature", op: e.op, editing: merged, preset: {}, selection: [] };
  }
  const op = edit.op;
  const { picks, lost } = targetPicks(edit, topo, buildId);
  const note = lost ? `The model changed since the suggestion: ${lost} ${edit.targets?.kind === "edge" ? "edge" : "face"}${lost > 1 ? "s" : ""} could not be found. Pick ${lost > 1 ? "them" : "it"} again.` : undefined;
  const size = edit.values.size;
  const hole = edit.values.hole;
  if (edit.feature_id) {
    const e = manual.find(m => m.id === edit.feature_id);
    if (!e) return { kind: "error", message: "That feature is no longer in the feature tree" };
    let merged: ManualFeature = { ...e };
    if (op === "fillet" && size != null) merged = { ...merged, r: size };
    if (op === "chamfer" && size != null) merged = { ...merged, d: size };
    if (op === "shell" && size != null) merged = { ...merged, t: size };
    if (op === "hole" && hole) {
      if (hole.type === "simple") merged = { ...merged, d: hole.d ?? merged.d, spec: undefined };
      else if (hole.type) merged = { ...merged, spec: { ...(merged.spec ?? { fit: "medium" }), type: hole.type, size: hole.size ?? merged.spec?.size ?? 6 } as ManualFeature["spec"] };
    }
    return { kind: "feature", op, editing: merged, preset: {}, selection: picks, note };
  }
  const preset: Record<string, unknown> = op === "hole" ? { hole: { ...hole } } : size != null ? { size } : {};
  return { kind: "feature", op, editing: null, preset, selection: picks, note };
}

/** The PropertyManager steps of an agent edit: several for a multi-step block, else the edit itself. */
export function agentSteps(edit: AgentEdit): AgentEdit[] {
  return edit.op === "multi" ? edit.steps ?? [] : [edit];
}

/** The impact-preview request for an edit as the agent proposed it (the card in the chat). */
export function impactChange(edit: AgentEdit): ImpactChange | null {
  if (edit.op === "multi") {
    const changes = (edit.steps ?? []).map(impactChange);
    return changes.length && changes.every(Boolean) ? { kind: "sequence", changes: changes as ImpactChange[] } : null;
  }
  if (edit.op === "params") {
    const values = Object.fromEntries(Object.entries(edit.params ?? {}).map(([k, r]) => [k, r.to]));
    return Object.keys(values).length ? { kind: "params", values } : null;
  }
  if (!edit.feature) return null;
  return edit.feature_id ? { kind: "edit", id: edit.feature_id, feature: edit.feature as Record<string, unknown> }
    : { kind: "feature", feature: edit.feature as Record<string, unknown> };
}

/** A feature-tree or typed-command action as an impact-preview request (ASM-018 follow-up): suppress / unsuppress,
 *  delete, move up or down, and the same on the design agent's own steps. */
export type TreeAction =
  | { kind: "toggle"; feature: ManualFeature } | { kind: "delete"; feature: ManualFeature }
  | { kind: "move"; ids: string[]; id: string; by: -1 | 1 }
  | { kind: "design_suppress"; name: string; suppressed: boolean } | { kind: "design_delete"; name: string };

export function treeChange(a: TreeAction): ImpactChange | null {
  switch (a.kind) {
    case "toggle": return { kind: "suppress", id: a.feature.id, suppressed: !a.feature.suppressed };
    case "delete": return { kind: "delete", id: a.feature.id };
    case "move": {
      const ids = [...a.ids]; const i = ids.indexOf(a.id), j = i + a.by;
      if (i < 0 || j < 0 || j >= ids.length) return null;
      [ids[i], ids[j]] = [ids[j]!, ids[i]!];
      return { kind: "reorder", ids };
    }
    case "design_suppress": return { kind: "design_suppress", name: a.name, suppressed: a.suppressed };
    case "design_delete": return { kind: "design_delete", name: a.name };
  }
}
