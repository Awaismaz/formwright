import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ExternalLink, KeyRound, ShieldCheck, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago } from "@/lib/format";
import { Badge, Button, Card, Input, Spinner } from "@/components/ui";
import type { Integration } from "./types";

export const INTEGRATION_KEY = ["airender-integration"];

export function useIntegration(enabled = true) {
  return useQuery({ queryKey: INTEGRATION_KEY, enabled, retry: false, queryFn: () => api.get<Integration>("/api/m/airender/integration") });
}

/** Add / replace / delete the workspace's OpenAI key. The key is sent once, validated by the server, stored encrypted
 * and only ever shown back as a masked hint. */
export function OpenAIKeyCard({ compact = false }: { compact?: boolean }) {
  const qc = useQueryClient();
  const q = useIntegration();
  const [key, setKey] = useState("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (q.error) return <p className="text-sm text-muted">{q.error instanceof ApiError ? q.error.message : "Couldn't load the OpenAI integration."}</p>;
  if (!q.data) return <Spinner />;
  const st = q.data;
  const save = async () => {
    setBusy("save"); setErr(null);
    try {
      const r = await api.post<Integration>("/api/m/airender/integration/key", { api_key: key.trim() });
      qc.setQueryData(INTEGRATION_KEY, r); setKey(""); setEditing(false); toast.success("OpenAI key checked and saved");
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Couldn't save the key"); } finally { setBusy(null); }
  };
  const remove = async () => {
    if (!confirm("Delete the workspace's OpenAI key? AI renders stop until a key is added again.")) return;
    setBusy("del");
    try { qc.setQueryData(INTEGRATION_KEY, await api.del<Integration>("/api/m/airender/integration/key")); toast.success("OpenAI key deleted"); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Couldn't delete the key"); } finally { setBusy(null); }
  };
  const form = (
    <div className="space-y-2" data-key-form>
      <Input type="password" autoComplete="off" spellCheck={false} placeholder="sk-…" value={key} onChange={e => { setKey(e.target.value); setErr(null); }}
        onKeyDown={e => { if (e.key === "Enter" && key.trim()) save(); }} aria-label="OpenAI API key" data-key-input />
      {err && <p className="text-[12.5px] text-danger" data-key-error>{err}</p>}
      <div className="flex flex-wrap items-center gap-2">
        <Button loading={busy === "save"} disabled={key.trim().length < 10} onClick={save} icon={<KeyRound className="h-4 w-4" />} data-action="save-key">Check and save key</Button>
        {editing && <Button variant="ghost" onClick={() => { setEditing(false); setKey(""); setErr(null); }}>Cancel</Button>}
      </div>
      <p className="text-[11.5px] leading-snug text-muted">We make one free call to OpenAI to check the key, then store it encrypted. It is never shown again, only its last four characters. Create a key at{" "}
        <a className="link inline-flex items-center gap-0.5" href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">platform.openai.com/api-keys<ExternalLink className="h-3 w-3" /></a>.</p>
    </div>
  );
  return (
    <div className="space-y-3 text-sm" data-openai-key={st.has_key ? "set" : "none"}>
      {!compact && <p className="text-muted">AI Render Studio uses your own OpenAI account: image generation is billed by OpenAI to that key, not by Formwright.</p>}
      {st.has_key && !editing ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-panel2/50 px-3 py-2.5">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-success" />
          <div className="min-w-0 flex-1"><div className="font-mono text-[13px]" data-key-hint>{st.key_hint}</div>
            <div className="text-[11.5px] text-muted">Added{st.key_added_by ? ` by ${st.key_added_by}` : ""}{st.key_added_at ? ` ${ago(st.key_added_at)}` : ""} · encrypted at rest</div></div>
          {st.can_manage && <div className="flex gap-1.5">
            <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>Replace</Button>
            <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} loading={busy === "del"} onClick={remove} data-action="delete-key">Delete</Button>
          </div>}
        </div>
      ) : st.can_manage ? form : <p className="rounded-lg border border-dashed border-border p-3 text-muted">Ask a workspace owner or admin to add an OpenAI API key.</p>}
      {st.fake && <Badge tone="warning">Development: simulated OpenAI (no real calls)</Badge>}
    </div>
  );
}

/** One-time, per-workspace consent that the reference image and prompt go to OpenAI. */
export function ConsentCard() {
  const qc = useQueryClient();
  const q = useIntegration();
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!q.data) return null;
  const c = q.data.consent;
  const set = async (accept: boolean) => {
    setBusy(true);
    try { qc.setQueryData(INTEGRATION_KEY, await api.post<Integration>("/api/m/airender/integration/consent", { accept })); }
    catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(false); }
  };
  if (c.given) return (
    <div className="flex items-start gap-2 text-[12.5px] text-muted" data-consent="given">
      <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" />
      <span>{c.by ? `${c.by} agreed` : "Agreed"}{c.at ? ` ${ago(c.at)}` : ""} that reference images and prompts are sent to OpenAI. <button className="link" onClick={() => set(false)}>Withdraw</button></span>
    </div>
  );
  return (
    <div className="space-y-3 text-sm" data-consent="needed">
      <p className="leading-relaxed text-muted">{c.text}</p>
      <label className="flex items-start gap-2"><input type="checkbox" className="mt-0.5" checked={ok} onChange={e => setOk(e.target.checked)} data-consent-check />
        <span>I agree, for this workspace.</span></label>
      <Button disabled={!ok} loading={busy} onClick={() => set(true)} icon={<ShieldCheck className="h-4 w-4" />} data-action="consent">Allow AI renders</Button>
    </div>
  );
}

/** Shown instead of the studio until the workspace has a key and has agreed to send images to OpenAI. */
export function Setup({ st }: { st: Integration }) {
  return (
    <div className="mx-auto w-full max-w-2xl px-6 py-10" data-setup>
      <h2 className="text-[20px] font-semibold tracking-tight">{st.has_key ? "One more step" : "Add your OpenAI key to enable AI renders"}</h2>
      <p className="mt-1.5 text-sm text-muted">AI Render Studio turns a render of your real part into marketing visuals with OpenAI image generation. It runs on your own OpenAI API key, so OpenAI bills that usage to your account.</p>
      <Card className="mt-6 p-5">
        <div className="mb-3 flex items-center gap-2"><span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary-soft text-[12px] font-semibold text-primary">1</span><h3 className="font-semibold">OpenAI API key</h3>{st.has_key && <CheckCircle2 className="h-4 w-4 text-success" />}</div>
        <OpenAIKeyCard compact />
      </Card>
      <Card className={`mt-4 p-5 ${st.has_key ? "" : "opacity-60"}`}>
        <div className="mb-3 flex items-center gap-2"><span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary-soft text-[12px] font-semibold text-primary">2</span><h3 className="font-semibold">Sending images to OpenAI</h3></div>
        {st.has_key ? <ConsentCard /> : <p className="text-sm text-muted">Add a key first.</p>}
      </Card>
    </div>
  );
}
