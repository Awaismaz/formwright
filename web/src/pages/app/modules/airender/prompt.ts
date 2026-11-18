/** Client-side helpers for the AI Render prompt review step (pure functions, unit-tested). */

export interface AirSettings {
  scene: string; finish: string; lighting: string; camera: string; background: string; style: string;
  size: string; quality: string; variants: number;
}

/** Negative instructions are edited as one per line. */
export function negativesToText(neg: string[]): string {
  return neg.join("\n");
}

export function textToNegatives(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/^[-•*]\s*/, "").replace(/\s+/g, " ").trim();
    if (line && !seen.has(line.toLowerCase())) { seen.add(line.toLowerCase()); out.push(line.slice(0, 160)); }
  }
  return out.slice(0, 12);
}

/** True when the edited prompt still carries the geometry-preservation clause (the server re-adds it otherwise). */
export function keepsGeometry(prompt: string, clause: string): boolean {
  const norm = (s: string) => s.replace(/\s+/g, " ").trim().toLowerCase();
  return !!clause && norm(prompt).includes(norm(clause));
}

/** A stable key of everything that feeds the prompt: when it changes after a refine, the prompt is out of date. */
export function refineKey(s: AirSettings, userPrompt: string): string {
  const { scene, finish, lighting, camera, background, style } = s;
  return JSON.stringify([scene, finish.trim(), lighting, camera, background, style, userPrompt.trim()]);
}

export function wordCount(text: string): number {
  const t = text.trim();
  return t ? t.split(/\s+/).length : 0;
}

/** "1536 × 1024" from "1536x1024". */
export function sizeLabel(size: string): string {
  const [w, h] = size.split("x");
  return w && h ? `${w} × ${h}` : size;
}

/** Rough wait shown while OpenAI works: the quality's typical time, a bit more per extra variant. */
export function etaSeconds(qualityEta: number, variants: number): number {
  return Math.round(qualityEta * (1 + 0.35 * Math.max(0, variants - 1)));
}
