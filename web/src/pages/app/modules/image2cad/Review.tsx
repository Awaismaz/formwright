import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowLeft, Check, CheckCircle2, CircleHelp, Eye, EyeOff, Loader2, Pencil, Plus, RefreshCw, Ruler, Scale,
  Sparkles, Type, X,
} from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { cx } from "@/lib/format";
import { Badge, Button, Input, PageLoader, Tip } from "@/components/ui";
import SourcePane, { type Pin } from "./SourcePane";
import { BASE, KIND_LABEL, type Answer, type Dim, type Full, type Need, type RefAnswer, type Review, type ReviewState, type View } from "./types";

const fmt = (v: number | null | undefined) => (v == null ? "?" : String(Math.round(v * 10000) / 10000));

export default function ReviewScreen({ uid, targetProject, onBack }: { uid: string; targetProject: string | null; onBack: () => void }) {
  const qc = useQueryClient();
  const key = useMemo(() => ["i2c-upload", uid], [uid]);
  const q = useQuery({
    queryKey: key, queryFn: () => api.get<Full>(`${BASE}/uploads/${uid}`),
    refetchInterval: d => (d.state.data?.upload.status === "reading" ? 1500 : false),
  });
  if (q.isLoading) return <PageLoader />;
  if (q.error || !q.data) return <div className="p-10 text-center text-sm text-muted">{(q.error as Error)?.message ?? "Not found"}</div>;
  const f = q.data;
  if (f.upload.status === "reading" || f.upload.status === "failed" || !f.read || !f.state) {
    return <Pending f={f} onBack={onBack} onRetry={async () => {
      try { qc.setQueryData(key, await api.post<Full>(`${BASE}/uploads/${uid}/reread`)); }
      catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); }
    }} />;
  }
  return <Workspace f={f} uid={uid} targetProject={targetProject} onBack={onBack} />;
}

function Pending({ f, onBack, onRetry }: { f: Full; onBack: () => void; onRetry: () => void }) {
  const failed = f.upload.status === "failed";
  return (
    <div className="flex h-full flex-col">
      <Toolbar name={f.upload.name} onBack={onBack} />
      <div className="flex flex-1 items-center justify-center bg-[#e9edf2] p-6 dark:bg-[#1b2027]">
        <div className="w-full max-w-md rounded-xl border border-border bg-panel p-6 text-center shadow-card">
          {failed ? <AlertTriangle className="mx-auto h-8 w-8 text-danger" /> : <Loader2 className="mx-auto h-8 w-8 animate-spin text-primary" />}
          <div className="mt-3 text-[15px] font-semibold">{failed ? "We couldn't read this file" : (f.upload.step ?? "Reading the drawing")}</div>
          <p className="mt-1.5 text-[13px] text-muted">
            {failed ? f.upload.error
              : f.upload.method === "vision" ? "AI vision is reading every value it can see, with a confidence for each. This usually takes under a minute."
              : "Extracting the dimension texts, views and title block."}
          </p>
          {failed && f.can_edit && <Button className="mt-4" variant="secondary" icon={<RefreshCw className="h-4 w-4" />} onClick={onRetry}>Try again</Button>}
        </div>
      </div>
    </div>
  );
}

function Toolbar({ name, onBack, children }: { name: string; onBack: () => void; children?: ReactNode }) {
  return (
    <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border bg-panel px-3">
      <Tip content="All uploads" side="bottom"><button onClick={onBack} aria-label="All uploads" className="rounded p-1.5 text-muted hover:bg-text/5 hover:text-text"><ArrowLeft className="h-4 w-4" /></button></Tip>
      <Ruler className="h-4 w-4 shrink-0 text-primary" />
      <span className="truncate text-[14px] font-semibold">{name}</span>
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------ workspace */
function Workspace({ f, uid, targetProject, onBack }: { f: Full; uid: string; targetProject: string | null; onBack: () => void }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const read = f.read!;
  const st: ReviewState = f.state!;
  const [rv, setRv] = useState<Review>(f.review);
  const [hot, setHot] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const timer = useRef<number | null>(null);
  const pending = useRef<Review | null>(null);
  const editable = f.can_edit;

  const flush = useCallback(async () => {
    const body = pending.current;
    if (!body) return;
    pending.current = null;
    setSaving(true);
    try {
      const res = await api.post<Full>(`${BASE}/uploads/${uid}/review`, body);
      qc.setQueryData(["i2c-upload", uid], res);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Couldn't save");
      const cur = qc.getQueryData<Full>(["i2c-upload", uid]);
      if (cur) setRv(cur.review);
    } finally { setSaving(false); }
  }, [qc, uid]);

  const save = useCallback((next: Review, now = false) => {
    setRv(next);
    pending.current = next;
    if (timer.current) window.clearTimeout(timer.current);
    if (now) void flush();
    else timer.current = window.setTimeout(() => void flush(), 350);
  }, [flush]);
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);

  const setAnswer = (id: string, a: Answer | null) => {
    const answers = { ...rv.answers };
    if (a) answers[id] = a; else delete answers[id];
    save({ ...rv, answers }, true);
  };
  const setDim = (id: string, patch: Review["dims"][string] | null) => {
    const dims = { ...rv.dims };
    if (patch === null) delete dims[id]; else dims[id] = { ...(dims[id] ?? {}), ...patch };
    save({ ...rv, dims }, true);
  };

  const views = read.views;
  const vmap = Object.fromEntries(views.map(v => [v.id, v])) as Record<string, View>;
  const needByDim = new Map<string, Need>();
  st.needs.forEach(n => { if (n.dim && !n.answered) needByDim.set(n.dim, n); });
  const number = new Map<string, number>();
  st.dims.forEach((d, i) => number.set(d.id, i + 1));
  const refDim = st.scale.reference?.dim ?? null;
  const front = rv.answers.front_view?.choice ?? null;

  const pins: Pin[] = [];
  st.dims.forEach(d => {
    if (d.x == null || d.y == null) return;
    // pin beside the text, not on it: the box corner for PDF text, a small offset from the centre for vision reads
    const corner = true;
    const px = d.box ? d.box[2]! : Math.min(d.x + 0.018, 0.995);
    const py = d.box ? d.box[1]! : Math.max(d.y - 0.012, 0.005);
    pins.push({ id: d.id, x: px, y: py, corner, n: number.get(d.id)!, title: d.label,
      tone: d.excluded ? "off" : refDim === d.id ? "ref" : needByDim.has(d.id) ? "ask" : "read" });
  });
  st.needs.forEach(n => {
    if (n.dim || n.x == null || n.y == null) return;
    pins.push({ id: n.id, x: n.x, y: n.y, n: 0, title: n.question, tone: n.answered ? "done" : "ask" });
  });
  const boxes = views.filter(v => v.box).map(v => ({ id: v.id, box: v.box!, label: v.id === front ? `${v.name} · Front` : v.name }));

  const openNeeds = st.needs.filter(n => !n.answered);
  const doneNeeds = st.needs.filter(n => n.answered);
  const method = read.method === "vector" ? "Read from the drawing text" : "Read by AI vision";

  return (
    <div className="flex h-full flex-col">
      <Toolbar name={f.upload.name} onBack={onBack}>
        <Badge tone={read.method === "vector" ? "primary" : "accent"}>{read.method === "vector" ? <Type className="h-3 w-3" /> : <Sparkles className="h-3 w-3" />}{method}</Badge>
        {(read.pages ?? 1) > 1 && <Badge tone="warning">Page 1 of {read.pages} read</Badge>}
        <span className="ml-auto flex items-center gap-2 text-[12px] text-muted">{saving ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />Saving</> : editable ? "Saved" : "View only"}</span>
      </Toolbar>
      <div className="flex min-h-0 flex-1">
        <div className="relative min-w-0 flex-1">
          <SourcePane src={`${BASE}/uploads/${uid}/preview.png`} pins={pins} boxes={boxes} hot={hot} onHot={setHot}
            onPick={id => { setHot(id); document.querySelector(`[data-row="${id}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }} />
        </div>
        <aside className="flex w-[460px] shrink-0 flex-col border-l border-border bg-panel">
          <div className="min-h-0 flex-1 overflow-y-auto" data-testid="checklist">
            <ScaleCard st={st} read={read} />
            <Section title="What we need" count={openNeeds.length} tone={openNeeds.length ? "warning" : "success"}
              empty={openNeeds.length === 0 ? "Nothing open. Every value is read or answered." : undefined}
              action={editable && openNeeds.filter(n => n.kind === "missing").length >= 2 ? (
                <Tip content="Every open missing size will be estimated by the designer and listed as an assumption" side="left">
                  <button type="button" className="text-[12px] text-primary hover:underline" data-testid="estimate-rest"
                    onClick={() => save({ ...rv, answers: { ...rv.answers, ...Object.fromEntries(openNeeds.filter(n => n.kind === "missing").map(n => [n.id, { choice: "estimate" }])) } }, true)}>
                    Estimate all missing sizes (flagged)</button>
                </Tip>) : undefined}>
              {openNeeds.map(n => (
                <NeedCard key={n.id} n={n} rv={rv} st={st} hot={hot === n.id || (!!n.dim && hot === n.dim)} onHot={setHot}
                  num={n.dim ? number.get(n.dim) : undefined} number={number} disabled={!editable}
                  setAnswer={setAnswer} setRef={r => save({ ...rv, reference: r }, true)} />
              ))}
              {doneNeeds.length > 0 && (
                <details className="group mt-1" open={openNeeds.length === 0 && doneNeeds.length <= 3}>
                  <summary className="cursor-pointer list-none py-1 text-[12px] text-muted hover:text-text">
                    <span className="group-open:hidden">Show {doneNeeds.length} answered</span><span className="hidden group-open:inline">Answered</span>
                  </summary>
                  <div className="space-y-2 pt-1">
                    {doneNeeds.map(n => (
                      <NeedCard key={n.id} n={n} rv={rv} st={st} hot={hot === n.id} onHot={setHot} num={n.dim ? number.get(n.dim) : undefined} number={number}
                        disabled={!editable} setAnswer={setAnswer} setRef={r => save({ ...rv, reference: r }, true)} />
                    ))}
                  </div>
                </details>
              )}
            </Section>
            <Section title="What we read" count={st.dims.filter(d => !d.excluded).length}>
              <ReadList st={st} views={views} vmap={vmap} front={front} number={number} needByDim={needByDim} hot={hot} onHot={setHot}
                refDim={refDim} disabled={!editable} setDim={setDim} read={read}
                onAdd={(text, describes) => save({ ...rv, added: [...rv.added, { text, describes }] }, true)}
                onRemoveAdded={id => save({ ...rv, added: rv.added.filter((_, i) => `u${i + 1}` !== id) }, true)} />
            </Section>
            {st.assumptions.length > 0 && (
              <Section title="Will be stated as assumptions">
                <ul className="space-y-1.5 text-[12.5px] text-muted">
                  {st.assumptions.map(a => <li key={a} className="flex gap-2"><span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-muted" />{a}</li>)}
                </ul>
              </Section>
            )}
            <Section title="Notes for the designer">
              <textarea className="input min-h-[64px] w-full resize-y py-2 text-[13px]" placeholder="Optional: material, purpose, anything the drawing doesn't say"
                disabled={!editable} defaultValue={rv.notes} onChange={e => save({ ...rv, notes: e.target.value })} data-testid="notes" />
            </Section>
          </div>
          <CreateBar f={f} st={st} uid={uid} targetProject={targetProject} disabled={!editable || saving}
            onCreated={pid => nav(`/app/projects/${pid}`)} />
        </aside>
      </div>
    </div>
  );
}

function Section({ title, count, tone, empty, action, children }: { title: string; count?: number; tone?: "warning" | "success"; empty?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-b border-border px-4 py-3.5">
      <div className="mb-2.5 flex items-center gap-2">
        <h2 className="label">{title}</h2>
        {count != null && <span className={cx("rounded-full px-1.5 text-[11px] font-semibold tabular-nums",
          tone === "warning" ? "bg-warning/15 text-warning" : tone === "success" ? "bg-success/15 text-success" : "bg-text/[.06] text-muted")}>{count}</span>}
        {action && <span className="ml-auto">{action}</span>}
      </div>
      {empty && <p className="flex items-center gap-1.5 text-[12.5px] text-success"><CheckCircle2 className="h-4 w-4" />{empty}</p>}
      <div className="space-y-2">{children}</div>
    </section>
  );
}

/* ------------------------------------------------------------------ scale */
function ScaleCard({ st, read }: { st: ReviewState; read: Full["read"] }) {
  const s = st.scale;
  const ok = s.status !== "undefined";
  return (
    <div className="border-b border-border px-4 py-3.5" data-testid="scale-card">
      <div className={cx("relative overflow-hidden rounded-lg border p-3", ok ? "border-success/30 bg-success/[.06]" : "border-warning/40 bg-warning/[.06]")}>
        {!ok && <div className="pointer-events-none absolute inset-0 opacity-60 [background:repeating-linear-gradient(135deg,transparent_0_10px,rgb(var(--warning)/.07)_10px_20px)]" />}
        <div className="relative flex items-center gap-2">
          <Scale className={cx("h-4 w-4", ok ? "text-success" : "text-warning")} />
          <span className="text-[13px] font-semibold">Scale</span>
          <span data-testid="scale-status" className={cx("rounded-full px-2 py-px text-[11px] font-semibold", ok ? "bg-success/15 text-success" : "bg-warning/15 text-warning")}>
            {ok ? (s.status === "corrected" ? "Confirmed (corrected)" : "Confirmed") : "Undefined"}</span>
          {s.reference && <span className="ml-auto font-mono text-[12.5px] font-semibold">{fmt(s.reference.value)} {s.reference.unit}</span>}
        </div>
        <p className="relative mt-1.5 text-[12.5px] leading-snug text-text/80">{s.summary}</p>
        <ul className="relative mt-2 space-y-1 text-[12px] text-muted">
          <li className="flex gap-1.5"><span className="w-[72px] shrink-0 text-text/60">Stated</span>{s.stated ? <span><b className="text-text">{s.stated.text}</b> · {s.stated.evidence}</span> : "No scale written on the drawing"}</li>
          <li className="flex gap-1.5"><span className="w-[72px] shrink-0 text-text/60">Units</span>{s.units ? <span><b className="text-text">{s.units.value}</b> · {s.units.evidence}</span>
            : s.reference ? <span><b className="text-text">{s.reference.unit}</b> · set by your reference</span> : "Not stated: set them with the reference"}</li>
          {s.evidence.map(e => <li key={e} className="flex gap-1.5"><span className="w-[72px] shrink-0 text-text/60">Geometry</span><span className="flex gap-1"><Check className="mt-0.5 h-3 w-3 shrink-0 text-success" />{e}</span></li>)}
          {read?.method === "vision" && <li className="flex gap-1.5"><span className="w-[72px] shrink-0 text-text/60">Image</span>Not to scale. Sizes are never measured from it.</li>}
        </ul>
        {s.warning && <p className="relative mt-2 flex gap-1.5 text-[12px] text-warning"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{s.warning}</p>}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ needs */
function Chip({ active, suggested, onClick, children, disabled, title }: { active?: boolean; suggested?: boolean; onClick: () => void; children: ReactNode; disabled?: boolean; title?: string }) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} title={title}
      className={cx("inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[12.5px] transition disabled:cursor-not-allowed disabled:opacity-60",
        active ? "border-primary bg-primary text-primary-fg" : "border-border bg-panel hover:border-primary/60 hover:bg-primary-soft/50",
        suggested && !active && "border-primary/50")}>
      {children}{suggested && !active && <span className="text-[10.5px] font-semibold uppercase tracking-wide text-primary">· suggested</span>}
    </button>
  );
}

function UnitToggle({ value, onChange, disabled }: { value: string | null | undefined; onChange: (u: string) => void; disabled?: boolean }) {
  return (
    <div className="flex rounded-md border border-border bg-panel2 p-0.5" role="radiogroup" aria-label="Units">
      {["mm", "in"].map(u => (
        <button key={u} type="button" role="radio" aria-checked={value === u} disabled={disabled} onClick={() => onChange(u)}
          className={cx("rounded px-2.5 py-0.5 text-[12.5px]", value === u ? "bg-panel font-semibold shadow-sm" : "text-muted hover:text-text")}>{u}</button>
      ))}
    </div>
  );
}

function NeedCard({ n, rv, st, hot, onHot, num, disabled, setAnswer, setRef, number }: {
  n: Need; rv: Review; st: ReviewState; hot: boolean; onHot: (id: string | null) => void; num?: number; disabled: boolean; number?: Map<string, number>;
  setAnswer: (id: string, a: Answer | null) => void; setRef: (r: RefAnswer | null) => void;
}) {
  const [editing, setEditing] = useState(false);
  const a = (rv.answers[n.id] ?? {}) as Answer;
  const shell = (body: ReactNode, summary?: ReactNode) => (
    <div data-row={n.id} data-need={n.kind} onMouseEnter={() => onHot(n.dim ?? n.id)} onMouseLeave={() => onHot(null)}
      className={cx("rounded-lg border p-3 transition", n.answered ? "border-border bg-panel" : "border-warning/40 bg-warning/[.04]",
        hot && "ring-2 ring-primary/40")}>
      <div className="flex items-start gap-2">
        {n.answered ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" />
          : num ? <span className="mt-px flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-warning px-1 text-[10.5px] font-bold text-white">{num}</span>
          : <CircleHelp className="mt-0.5 h-4 w-4 shrink-0 text-warning" />}
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium leading-snug">{n.question}</div>
          {n.answered && !editing && summary ? (
            <div className="mt-1 flex items-center gap-2 text-[12.5px] text-muted">{summary}
              {!disabled && <button type="button" className="link text-[12px]" onClick={() => setEditing(true)}>Change</button>}</div>
          ) : (
            <>
              {n.detail && <p className="mt-0.5 text-[12px] leading-snug text-muted">{n.detail}</p>}
              <div className="mt-2">{body}</div>
            </>
          )}
        </div>
      </div>
    </div>
  );

  if (n.kind === "reference") return <ReferenceCard n={n} st={st} rv={rv} shell={shell} number={number} disabled={disabled} done={() => setEditing(false)} setRef={setRef} />;

  const choose = (choice: string, extra: Partial<Answer> = {}) => { setAnswer(n.id, { choice, ...extra }); setEditing(false); };
  const needsInput = (c?: string) => (n.input === "callout" && (c === "callout" || n.kind === "confirm")) || (n.input === "text" && c === "text") || (n.input === "value" && c === "value");
  const label = n.options.find(o => o.value === a.choice)?.label;
  const summary = a.choice === "value" ? <span><b className="text-text">{fmt(a.value)} {a.unit}</b></span>
    : a.choice === "text" ? <span>“{a.text}”</span>
    : a.choice === "callout" ? <span className="font-mono text-text">{a.text}</span>
    : <span>{label ?? a.choice}</span>;
  return shell(
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {n.options.map(o => (
          <Chip key={o.value} active={a.choice === o.value} suggested={n.default === o.value} disabled={disabled} title={o.hint}
            onClick={() => (needsInput(o.value) && o.value !== "keep" && o.value !== "exclude" && n.kind !== "confirm"
              ? setAnswer(n.id, { ...a, choice: o.value, ...(o.value === "value" && !a.unit && n.default_unit ? { unit: n.default_unit } : {}) })
              : choose(o.value))}>
            {o.label}{o.hint && <span className="text-[11px] opacity-70">· {o.hint}</span>}
          </Chip>
        ))}
      </div>
      {n.kind === "confirm" && <InlineCallout placeholder="Or type the correct value, e.g. Ø12" disabled={disabled} onSubmit={t => choose(t)} />}
      {n.input === "callout" && n.kind !== "confirm" && a.choice === "callout" && <InlineCallout placeholder="e.g. Ø12 H7, R5, 25±0.1" initial={a.text} disabled={disabled} onSubmit={t => choose("callout", { text: t })} />}
      {n.input === "text" && a.choice === "text" && <InlineText placeholder="What it says" initial={a.text} disabled={disabled} onSubmit={t => choose("text", { text: t })} />}
      {n.input === "value" && a.choice === "value" && <ValueInput initial={a.value} unit={a.unit ?? n.default_unit ?? null} disabled={disabled} onSubmit={(v, u) => choose("value", { value: v, unit: u })} />}
    </div>, n.answered ? summary : undefined);
}

function InlineCallout({ placeholder, initial, disabled, onSubmit }: { placeholder: string; initial?: string; disabled?: boolean; onSubmit: (t: string) => void }) {
  const [t, setT] = useState(initial ?? "");
  return (
    <form className="flex gap-1.5" onSubmit={e => { e.preventDefault(); if (t.trim()) onSubmit(t.trim()); }}>
      <Input value={t} onChange={e => setT(e.target.value)} placeholder={placeholder} disabled={disabled} className="h-8 flex-1 font-mono text-[13px]" />
      <Button size="sm" variant="secondary" disabled={disabled || !t.trim()} type="submit">Use</Button>
    </form>
  );
}

function InlineText({ placeholder, initial, disabled, onSubmit }: { placeholder: string; initial?: string; disabled?: boolean; onSubmit: (t: string) => void }) {
  const [t, setT] = useState(initial ?? "");
  return (
    <form className="flex gap-1.5" onSubmit={e => { e.preventDefault(); if (t.trim()) onSubmit(t.trim()); }}>
      <Input value={t} onChange={e => setT(e.target.value)} placeholder={placeholder} disabled={disabled} className="h-8 flex-1 text-[13px]" />
      <Button size="sm" variant="secondary" disabled={disabled || !t.trim()} type="submit">Save</Button>
    </form>
  );
}

function ValueInput({ initial, unit, disabled, onSubmit, cta = "Save" }: { initial?: number; unit: string | null; disabled?: boolean; onSubmit: (v: number, u: string) => void; cta?: string }) {
  const [v, setV] = useState(initial != null ? String(initial) : "");
  const [u, setU] = useState<string | null>(unit);
  const num = Number(v.replace(",", "."));
  const ok = v.trim() !== "" && Number.isFinite(num) && num > 0 && !!u;
  return (
    <form className="flex items-center gap-1.5" onSubmit={e => { e.preventDefault(); if (ok) onSubmit(num, u!); }}>
      <Input value={v} onChange={e => setV(e.target.value)} inputMode="decimal" placeholder="Value" disabled={disabled} className="h-8 w-24 font-mono text-[13px]" data-testid="value-input" />
      <UnitToggle value={u} onChange={setU} disabled={disabled} />
      <Button size="sm" disabled={disabled || !ok} type="submit">{cta}</Button>
    </form>
  );
}

function ReferenceCard({ n, st, rv, shell, disabled, done, setRef, number }: {
  n: Need; st: ReviewState; rv: Review; number?: Map<string, number>; shell: (body: ReactNode, summary?: ReactNode) => ReactNode; disabled: boolean;
  done: () => void; setRef: (r: RefAnswer | null) => void;
}) {
  const cur = rv.reference ?? {};
  const [pick, setPick] = useState<string | null>(cur.dim ?? (cur.describes ? "__custom" : n.default));
  const [describes, setDescribes] = useState(cur.describes ?? "");
  const dim = st.dims.find(d => d.id === pick);
  const unit = cur.unit ?? n.default_unit ?? null;
  const r = st.scale.reference;
  const summary = r ? <span><b className="text-text">{r.describes} = {fmt(r.value)} {r.unit}</b></span> : undefined;
  return <>{shell(
    <div className="space-y-2.5">
      <div className="flex flex-wrap gap-1.5">
        {n.options.map(o => (
          <Chip key={o.value} active={pick === o.value} suggested={n.default === o.value} disabled={disabled} title={o.hint} onClick={() => setPick(o.value)}>
            {number?.get(o.value) && <span className={cx("flex h-4 min-w-4 items-center justify-center rounded-full px-0.5 text-[9.5px] font-bold",
              pick === o.value ? "bg-white/25 text-white" : "bg-primary/15 text-primary")}>{number.get(o.value)}</span>}
            <span className="font-mono">{o.label}</span>{o.matched && <Check className="h-3 w-3 text-success" />}
          </Chip>
        ))}
        <Chip active={pick === "__custom"} disabled={disabled} onClick={() => setPick("__custom")}>Another size I know…</Chip>
      </div>
      {pick === "__custom" && (
        <Input value={describes} onChange={e => setDescribes(e.target.value)} placeholder="What it is, e.g. overall length" disabled={disabled} className="h-8 text-[13px]" data-testid="ref-describes" />
      )}
      {pick && pick !== "__custom" && dim && (
        <p className="text-[12px] text-muted">{n.options.find(o => o.value === pick)?.hint}{n.options.find(o => o.value === pick)?.matched ? " · matches the drawn size at the stated scale" : ""}. Check the value and units, then confirm.</p>
      )}
      {pick && (pick !== "__custom" || describes.trim()) && (
        <ValueInput key={pick} initial={pick === "__custom" ? cur.value : (cur.dim === pick && cur.value) || dim?.value || undefined} unit={unit} disabled={disabled} cta="Confirm reference"
          onSubmit={(v, u) => { setRef(pick === "__custom" ? { dim: null, describes: describes.trim(), value: v, unit: u } : { dim: pick, value: v, unit: u, describes: dim?.describes ?? null }); done(); }} />
      )}
    </div>, summary)}</>;
}

/* ------------------------------------------------------------------ read list */
function ReadList({ st, views, vmap, front, number, needByDim, hot, onHot, refDim, disabled, setDim, onAdd, onRemoveAdded, read }: {
  st: ReviewState; views: View[]; vmap: Record<string, View>; front: string | null; number: Map<string, number>;
  needByDim: Map<string, Need>; hot: string | null; onHot: (id: string | null) => void; refDim: string | null; disabled: boolean;
  setDim: (id: string, p: Review["dims"][string] | null) => void; onAdd: (text: string, describes: string) => void;
  onRemoveAdded: (id: string) => void; read: NonNullable<Full["read"]>;
}) {
  const groups: { id: string | null; title: string; sub?: string; dims: Dim[] }[] = [];
  for (const v of views) {
    const ds = st.dims.filter(d => d.view === v.id);
    if (ds.length) groups.push({ id: v.id, title: v.name, sub: [v.id === front ? "front" : null, v.place, v.drawn_mm ? `drawn ${fmt(v.drawn_mm[0])} × ${fmt(v.drawn_mm[1])} mm` : null].filter(Boolean).join(" · "), dims: ds });
  }
  const loose = st.dims.filter(d => !d.view || !vmap[d.view]);
  if (loose.length) groups.push({ id: null, title: views.length ? "Not tied to a view" : "Dimensions", dims: loose });
  const [adding, setAdding] = useState(false);
  return (
    <div className="space-y-3">
      {groups.length === 0 && <p className="text-[12.5px] text-muted">No dimensions were read{read.method === "vision" ? " from this image" : ""}. Add the ones you know below.</p>}
      {groups.map(g => (
        <div key={g.id ?? "loose"}>
          <div className="mb-1 flex items-baseline gap-2">
            <span className="text-[12.5px] font-semibold">{g.title}</span>
            {g.sub && <span className="truncate text-[11.5px] text-muted">{g.sub}</span>}
          </div>
          <div className="overflow-hidden rounded-md border border-border">
            {g.dims.map(d => <DimRow key={d.id} d={d} n={number.get(d.id)!} ask={needByDim.has(d.id)} isRef={refDim === d.id}
              hot={hot === d.id} onHot={onHot} disabled={disabled} setDim={setDim} onRemoveAdded={onRemoveAdded} />)}
          </div>
        </div>
      ))}
      {!disabled && (adding ? <AddDim onAdd={(t, w) => { onAdd(t, w); setAdding(false); }} onCancel={() => setAdding(false)} />
        : <button type="button" className="inline-flex items-center gap-1 text-[12.5px] text-primary hover:underline" onClick={() => setAdding(true)} data-testid="add-dim"><Plus className="h-3.5 w-3.5" />Add a dimension you know</button>)}
    </div>
  );
}

function Confidence({ d }: { d: Dim }) {
  if (d.source === "text") return <Tip content="Read exactly from the text in the PDF" side="left"><span className="rounded bg-primary-soft px-1.5 py-px text-[10.5px] font-semibold text-primary">TEXT</span></Tip>;
  if (d.source === "user") return <span className="rounded bg-text/[.06] px-1.5 py-px text-[10.5px] font-semibold text-muted">YOU</span>;
  const pct = Math.round(d.confidence * 100);
  const tone = d.confidence >= 0.85 ? "text-success bg-success/10" : d.confidence >= 0.75 ? "text-primary bg-primary-soft" : "text-warning bg-warning/10";
  return <Tip content="Vision confidence for this reading" side="left"><span className={cx("rounded px-1.5 py-px text-[10.5px] font-semibold tabular-nums", tone)}>{pct}%</span></Tip>;
}

function DimRow({ d, n, ask, isRef, hot, onHot, disabled, setDim, onRemoveAdded }: {
  d: Dim; n: number; ask: boolean; isRef: boolean; hot: boolean; onHot: (id: string | null) => void; disabled: boolean;
  setDim: (id: string, p: Review["dims"][string] | null) => void; onRemoveAdded: (id: string) => void;
}) {
  const [edit, setEdit] = useState(false);
  const [t, setT] = useState(d.label);
  useEffect(() => setT(d.label), [d.label]);
  const what = d.describes || (d.dir && d.kind === "linear" ? `${d.dir} length` : KIND_LABEL[d.kind] ?? d.kind);
  return (
    <div data-row={d.id} onMouseEnter={() => onHot(d.id)} onMouseLeave={() => onHot(null)}
      className={cx("flex items-center gap-2 border-b border-border px-2 py-1.5 last:border-b-0", hot && "bg-primary-soft/60", d.excluded && "opacity-50")}>
      <span className={cx("flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-full px-1 text-[10.5px] font-bold text-white",
        d.excluded ? "bg-muted" : isRef ? "bg-[#111827] ring-2 ring-accent" : ask ? "bg-warning" : "bg-primary")}>{n}</span>
      {edit ? (
        <form className="flex flex-1 gap-1" onSubmit={e => { e.preventDefault(); setDim(d.id, { text: t.trim() }); setEdit(false); }}>
          <Input autoFocus value={t} onChange={e => setT(e.target.value)} className="h-7 flex-1 font-mono text-[13px]"
            onKeyDown={e => { if (e.key === "Escape") { setT(d.label); setEdit(false); } }} />
          <button type="submit" className="rounded p-1 text-success hover:bg-success/10" aria-label="Save"><Check className="h-4 w-4" /></button>
          <button type="button" className="rounded p-1 text-muted hover:bg-text/5" aria-label="Cancel" onClick={() => { setT(d.label); setEdit(false); }}><X className="h-4 w-4" /></button>
        </form>
      ) : (
        <>
          <span className={cx("min-w-0 shrink-0 font-mono text-[13px] font-semibold", d.excluded && "line-through")}>{d.label}</span>
          <span className="min-w-0 flex-1 truncate text-[11.5px] text-muted">
            {isRef && <b className="mr-1 text-accent">REFERENCE</b>}{what}{d.edited && d.read_text ? ` · was ${d.read_text}` : ""}
          </span>
          <Confidence d={d} />
          {!disabled && d.source !== "user" && <>
            <Tip content="Correct this value" side="left"><button type="button" className="rounded p-1 text-muted hover:bg-text/5 hover:text-text" aria-label="Edit" onClick={() => setEdit(true)}><Pencil className="h-3.5 w-3.5" /></button></Tip>
            <Tip content={d.excluded ? "Include it in the model" : "Leave it out of the model"} side="left">
              <button type="button" className="rounded p-1 text-muted hover:bg-text/5 hover:text-text" aria-label={d.excluded ? "Include" : "Exclude"}
                onClick={() => setDim(d.id, { excluded: !d.excluded })}>{d.excluded ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}</button>
            </Tip>
          </>}
          {!disabled && d.source === "user" && d.id.startsWith("u") &&
            <button type="button" className="rounded p-1 text-muted hover:bg-danger/10 hover:text-danger" aria-label="Remove" onClick={() => onRemoveAdded(d.id)}><X className="h-3.5 w-3.5" /></button>}
        </>
      )}
    </div>
  );
}

function AddDim({ onAdd, onCancel }: { onAdd: (t: string, w: string) => void; onCancel: () => void }) {
  const [t, setT] = useState("");
  const [w, setW] = useState("");
  return (
    <form className="space-y-1.5 rounded-md border border-border p-2" onSubmit={e => { e.preventDefault(); if (t.trim()) onAdd(t.trim(), w.trim()); }}>
      <div className="flex gap-1.5">
        <Input autoFocus value={t} onChange={e => setT(e.target.value)} placeholder="Ø12 H7" className="h-8 w-32 font-mono text-[13px]" />
        <Input value={w} onChange={e => setW(e.target.value)} placeholder="What it measures" className="h-8 flex-1 text-[13px]" />
      </div>
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="ghost" type="button" onClick={onCancel}>Cancel</Button>
        <Button size="sm" type="submit" disabled={!t.trim()}>Add</Button>
      </div>
    </form>
  );
}

/* ------------------------------------------------------------------ create */
function CreateBar({ f, st, uid, targetProject, disabled, onCreated }: {
  f: Full; st: ReviewState; uid: string; targetProject: string | null; disabled: boolean; onCreated: (pid: string) => void;
}) {
  const projects = useQuery({ queryKey: ["projects-min"], queryFn: () => api.get<{ items: { id: string; name: string }[] }>("/api/projects") });
  const [target, setTarget] = useState<string>(targetProject ?? "new");
  const [name, setName] = useState(f.upload.name.replace(/\.[^.]+$/, "").slice(0, 80));
  const [busy, setBusy] = useState(false);
  const can = st.ready && !disabled && (target !== "new" || name.trim().length > 0);
  const create = async () => {
    setBusy(true);
    try {
      const r = await api.post<{ project_id: string }>(`${BASE}/uploads/${uid}/create`, target === "new" ? { name: name.trim() } : { project_id: target });
      toast.success("Model requested. The design agent is working from your confirmed values.");
      onCreated(r.project_id);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Couldn't create the model"); }
    finally { setBusy(false); }
  };
  if (!f.can_edit) return null;
  return (
    <div className="shrink-0 space-y-2 border-t border-border bg-panel2 px-4 py-3">
      {f.upload.status === "created" && f.project && (
        <p className="text-[12px] text-muted">A model was already requested in <Link className="link" to={`/app/projects/${f.project.id}`}>{f.project.name}</Link>. You can create another.</p>
      )}
      <div className="flex items-center gap-2">
        <select className="input h-8 w-[170px] py-0 text-[13px]" value={target} onChange={e => setTarget(e.target.value)} aria-label="Target project" data-testid="target">
          <option value="new">New project</option>
          {(projects.data?.items ?? []).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        {target === "new" && <Input value={name} onChange={e => setName(e.target.value)} placeholder="Project name" className="h-8 flex-1 text-[13px]" aria-label="Project name" />}
      </div>
      <div className="flex items-center gap-3">
        <span className="flex-1 text-[12px] leading-snug text-muted">
          {st.ready ? "The design agent gets exactly the confirmed values and the drawing as a reference."
            : `${st.open} open item${st.open === 1 ? "" : "s"} to answer before modelling.`}
        </span>
        <Button disabled={!can} loading={busy} onClick={() => void create()} data-testid="create-model" icon={<Sparkles className="h-4 w-4" />}>Create model</Button>
      </div>
    </div>
  );
}

