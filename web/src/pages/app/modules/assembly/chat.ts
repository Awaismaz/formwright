/** The assembly agent's conversation (WORKLIST 51): types and small pure helpers. */

export interface ChatQuestion { id: string; question: string; options: string[]; default: string | null; multi: boolean; other: boolean }
export interface ChatStep {
  label: string; status: "ok" | "warn" | "fail" | "info"; lines: string[]; parts: string[];
  matches?: { kind: "instance" | "part" | "toolbox"; id?: string; code?: string; name: string }[];
  project_id?: string; job?: string;
  /** ASM-OW: a part brought in with a check open (the engineer may fix it or mark it as verified) */
  unverified?: boolean; open?: { id: string; name: string }[];
}
export interface ChatState { parts: number; mates: number; ok: number; bad: number; unplaced: number; unplaced_names: string[]; clashes: number | null }
export interface ChatMessage {
  id: string; role: "user" | "agent"; text: string; at: string; by?: string | null;
  steps?: ChatStep[]; questions?: ChatQuestion[]; state?: ChatState | null; state_text?: string;
  tokens?: number; seconds?: number; offline?: boolean; job?: string;
}
export interface ChatJob {
  id: string; name: string; status: "running" | "question" | "done" | "failed"; step: string; project_id: string; started_at: string;
  /** the design agent's questions, relayed here (answered in this chat, never in the Design Studio) */
  questions?: ChatQuestion[] | null;
}
export interface ChatView {
  messages: ChatMessage[]; busy: { since: string; step: string } | null; jobs: ChatJob[]; ai: boolean; can_edit: boolean;
}

export const EXAMPLES = [
  "make a stepped shaft Ø20 with a keyseat, then bring a spur gear m2 z40 and a key, then assemble them",
  "bring two 6204 bearings for that shaft and put them on",
  "assemble everything",
  "check for clashes",
];

/** "Which shaft? Shaft B": what a clicked chip sends (the question and the answer, so the reply has the context). */
export function answerText(q: ChatQuestion, answer: string): string {
  return `${q.question} ${answer}`;
}

/** The footer line of an agent reply: time and tokens, honestly (0 tokens when it ran without AI). */
export function replyMeta(m: Pick<ChatMessage, "tokens" | "seconds" | "offline">): string {
  const bits: string[] = [];
  if (typeof m.seconds === "number") bits.push(`${m.seconds < 10 ? m.seconds.toFixed(1) : Math.round(m.seconds)} s`);
  bits.push(m.offline ? "no AI used" : `${m.tokens ?? 0} token${m.tokens === 1 ? "" : "s"}`);
  return bits.join(" · ");
}

/** A compact status chip for the state after a reply. */
export function stateTone(s: ChatState | null | undefined): "success" | "warning" | "danger" | "neutral" {
  if (!s) return "neutral";
  if (s.bad || (s.clashes ?? 0) > 0) return "danger";
  if (s.unplaced) return "warning";
  return "success";
}

/** What a reply posts: a design job's question is answered for that job (relayed to its design agent). */
export function sayBody(text: string, job?: string | null): { text: string; job?: string } {
  return job ? { text, job } : { text };
}

/** The questions of the last agent message are live until the engineer says something newer. */
export function liveQuestions(msgs: ChatMessage[], index: number, busy: boolean): boolean {
  return !busy && !msgs.slice(index + 1).some(m => m.role === "user");
}
