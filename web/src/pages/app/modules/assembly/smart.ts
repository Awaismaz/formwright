import type { SmartAction, SmartItem, SmartPlan, ToolboxParam } from "./types";

export const SOURCE_LABEL: Record<SmartItem["source"], string> = { toolbox: "Toolbox", project: "Your part", new: "New design" };
export const ACTION_LABEL: Record<SmartAction, string> = {
  base: "base part", mount: "mount", seat: "on a shaft seat", dowel: "into holes", fasten: "fasten", place: "place", design: "not inserted",
};

export function confidenceTone(c: SmartItem["confidence"]): "success" | "warning" | "danger" {
  return c === "high" ? "success" : c === "medium" ? "warning" : "danger";
}

/** "D 8 mm · L 20 mm", values the user did not write marked "(default)". */
export function paramLine(it: Pick<SmartItem, "params" | "read">, meta?: ToolboxParam[]): string {
  if (!it.params) return "";
  const read = new Set(it.read ?? []);
  return Object.entries(it.params).map(([k, v]) => {
    const m = meta?.find(p => p.name === k);
    const unit = m?.unit ? ` ${m.unit}` : "";
    return `${m?.label ?? k} ${v}${unit}${read.has(k) ? "" : " (default)"}`;
  }).join(" · ");
}

/** Honest token line for a plan. */
export function tokenLine(p: Pick<SmartPlan, "tokens" | "ai_used">): string {
  return p.ai_used ? `AI reading: ${p.tokens} token${p.tokens === 1 ? "" : "s"}` : "0 tokens · read without AI";
}
