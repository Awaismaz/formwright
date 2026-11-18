import { useRef, useState } from "react";
import { Check, ChevronDown, ChevronRight, ClipboardCheck, HelpCircle, Pencil, ShieldCheck, ShieldAlert, X } from "lucide-react";
import type { AgentBrief, AgentReview } from "@/lib/types";
import { cx } from "@/lib/format";
import { Button } from "@/components/ui";

const lines = (s: string) => s.split("\n").map(l => l.replace(/^\s*[-•]\s*/, "").trim()).filter(Boolean);

/** The confirmed brief as the build instruction (mirrors `brief_to_prompt` on the server). */
export function briefPrompt(b: AgentBrief, answers: Record<number, string>): string {
  const out = ["Approved design brief. Build it now.", "", "Requirements:", ...b.requirements.map(r => `- ${r}`)];
  if (b.assumptions.length) out.push("", "Assumptions (confirmed):", ...b.assumptions.map(a => `- ${a}`));
  if (b.questions.length) out.push("", "Answers to open questions:", ...b.questions.map((q, i) => `- ${q.question} ${answers[i]?.trim() || q.default || "your call; state the assumption"}`));
  return out.join("\n");
}

function Section({ title, items, editing, value, onChange, tone }: {
  title: string; items: string[]; editing: boolean; value: string; onChange: (v: string) => void; tone: "req" | "asm";
}) {
  return (
    <div className="mb-2.5">
      <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-muted">{title}</div>
      {editing
        ? <textarea value={value} onChange={e => onChange(e.target.value)} rows={Math.max(2, items.length + 1)} aria-label={title}
            className="input h-auto w-full resize-y py-1.5 text-[12.5px] leading-snug" placeholder="One item per line" />
        : items.length
          ? <ul className="space-y-0.5 text-[12.5px] leading-snug">{items.map((t, i) => (
              <li key={i} className="flex gap-1.5"><span className={cx("mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full", tone === "req" ? "bg-primary" : "bg-warning")} />{t}</li>))}</ul>
          : <div className="text-[12px] italic text-muted">None</div>}
    </div>);
}

/** CAD-028: interpreted requirements, assumptions and open questions, editable, approved before anything is built. */
export function BriefCard({ brief, active, onApprove }: { brief: AgentBrief; active: boolean; onApprove: (text: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [req, setReq] = useState(brief.requirements.join("\n"));
  const [asm, setAsm] = useState(brief.assumptions.join("\n"));
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [sent, setSent] = useState(false);
  const live = active && !sent;
  const current: AgentBrief = { ...brief, requirements: lines(req), assumptions: lines(asm) };
  return (
    <div className="rounded-lg border border-primary/35 bg-panel shadow-sm" data-testid="brief-card">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <ClipboardCheck className="h-4 w-4 text-primary" />
        <div className="min-w-0 flex-1">
          <div className="text-[12.5px] font-semibold">Design brief{brief.title ? `: ${brief.title}` : ""}</div>
          <div className="text-[11px] text-muted">{sent ? "Approved, building" : active ? "Check it, edit anything, then approve. Nothing is built until you do." : "Not approved"}</div>
        </div>
        {sent && <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-[11px] font-medium text-success"><Check className="h-3 w-3" />Approved</span>}
      </div>
      <div className="px-3 pt-2.5">
        <Section title="Requirements" items={current.requirements} editing={editing && live} value={req} onChange={setReq} tone="req" />
        <Section title="Assumptions" items={current.assumptions} editing={editing && live} value={asm} onChange={setAsm} tone="asm" />
        {brief.questions.length > 0 && (
          <div className="mb-2.5">
            <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-muted">Open questions</div>
            <div className="space-y-1.5">{brief.questions.map((q, i) => (
              <label key={i} className="block text-[12.5px] leading-snug">
                <span className="flex gap-1.5"><HelpCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-accent" />{q.question}</span>
                <input disabled={!live} value={answers[i] ?? q.default ?? ""} onChange={e => setAnswers({ ...answers, [i]: e.target.value })}
                  placeholder="Your answer (or leave it to the agent)" aria-label={q.question}
                  className="mt-1 h-7 w-full rounded-md border border-border bg-panel2 px-2 text-[12px] outline-none focus:border-primary disabled:opacity-70" />
              </label>))}</div>
          </div>)}
      </div>
      {live && <div className="flex items-center justify-end gap-2 border-t border-border px-3 py-2">
        <Button size="sm" variant="secondary" data-testid="brief-edit" icon={editing ? <Check className="h-3.5 w-3.5" /> : <Pencil className="h-3.5 w-3.5" />} onClick={() => setEditing(!editing)}>{editing ? "Done editing" : "Edit"}</Button>
        <Button size="sm" data-testid="brief-approve" disabled={!current.requirements.length} icon={<Check className="h-3.5 w-3.5" />}
          onClick={() => { setSent(true); setEditing(false); onApprove(briefPrompt(current, answers)); }}>Approve &amp; build</Button>
      </div>}
    </div>);
}

/** AGT-006: the agent's self-review after a build. The pass/fail line is the checks' verdict, never the agent's. */
export function SelfReview({ review }: { review: AgentReview }) {
  const overridden = review.items.filter(i => i.kind === "overridden").length;
  const [open, setOpen] = useState(overridden > 0);
  const ref = useRef<HTMLDivElement>(null);
  const toggle = () => { setOpen(!open); if (!open) setTimeout(() => ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 30); };
  const n = (k: string) => review.items.filter(i => i.kind === k).length;
  const g = review.gates;
  return (
    <div ref={ref} className="rounded-lg border border-border bg-panel2/60 text-[12px]" data-testid="self-review">
      <button onClick={toggle} className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left" aria-expanded={open}>
        {open ? <ChevronDown className="h-3.5 w-3.5 text-muted" /> : <ChevronRight className="h-3.5 w-3.5 text-muted" />}
        <span className="whitespace-nowrap font-medium">Self-review</span>
        <span className="truncate text-[11px] text-muted" title={`${n("observed")} observed, ${n("uncertain")} uncertain${overridden ? `, ${overridden} overridden` : ""}`}>
          {n("observed")} ✓ · {n("uncertain")} ?{overridden ? ` · ${overridden} ✗` : ""}</span>
        <span className={cx("ml-auto inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-1.5 py-px text-[10.5px] font-medium",
          g.ok === true ? "bg-success/10 text-success" : g.ok === false ? "bg-danger/10 text-danger" : "bg-text/5 text-muted")}>
          {g.ok === true ? <ShieldCheck className="h-3 w-3" /> : <ShieldAlert className="h-3 w-3" />}
          {g.ok === true ? "Checks passed" : g.ok === false ? `Checks failed${g.failed.length ? `: ${g.failed.join(", ")}` : ""}` : "No build"}
        </span>
      </button>
      {open && <ul className="space-y-1 border-t border-border px-2.5 py-2">
        {review.items.map((i, k) => (
          <li key={k} className="flex items-start gap-1.5 leading-snug">
            <span className={cx("mt-px inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-bold",
              i.kind === "observed" ? "bg-success/15 text-success" : i.kind === "uncertain" ? "bg-warning/15 text-warning" : "bg-danger/15 text-danger")}
              aria-label={i.kind}>{i.kind === "observed" ? <Check className="h-3 w-3" /> : i.kind === "uncertain" ? "?" : <X className="h-3 w-3" />}</span>
            <span className={cx(i.kind === "overridden" && "text-muted line-through decoration-danger/60")}>{i.text}</span>
            <span className="ml-auto shrink-0 rounded bg-text/5 px-1 text-[10px] text-muted">{i.basis}</span>
          </li>))}
        {overridden > 0 && <li className="pt-0.5 text-[11px] text-danger">Struck-through findings contradict a failed check. The checks decide.</li>}
        <li className="pt-0.5 text-[10.5px] text-muted">The agent's own reading of the build. Pass/fail comes from the deterministic checks only.</li>
      </ul>}
    </div>);
}
