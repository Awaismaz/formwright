import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import {
  Compass, CornerDownLeft, CreditCard, FolderKanban, LifeBuoy, Plus, Ruler, Search, Settings, UserPlus,
} from "lucide-react";
import { api } from "@/lib/api";
import type { Module, Project } from "@/lib/types";
import { cx } from "@/lib/format";
import { Icon } from "./icons";
import { useTemplates } from "./NewProjectDialog";

interface Item { key: string; label: string; hint?: string; icon: React.ReactNode; to: string }

const ACTIONS: Item[] = [
  { key: "new", label: "New project", hint: "Action", icon: <Plus className="h-4 w-4" />, to: "/app/projects?new=1" },
  { key: "billing", label: "Billing & tokens", hint: "Page", icon: <CreditCard className="h-4 w-4" />, to: "/app/billing" },
  { key: "team", label: "Invite teammates", hint: "Page", icon: <UserPlus className="h-4 w-4" />, to: "/app/team" },
  { key: "settings", label: "Settings", hint: "Page", icon: <Settings className="h-4 w-4" />, to: "/app/settings" },
  { key: "tour", label: "Restart guided tour", hint: "Help", icon: <Compass className="h-4 w-4" />, to: "/app?tour=1" },
  { key: "help", label: "Help and guides", hint: "Help", icon: <LifeBuoy className="h-4 w-4" />, to: "/app/help" },
];

const SIZE = /\d\s*(mm|in|")?\s*[x×*]\s*\d/i;

export default function CommandPalette({ open, onOpenChange, modules }: { open: boolean; onOpenChange: (v: boolean) => void; modules: Module[] }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const nav = useNavigate();
  const projects = useQuery({ queryKey: ["projects", false], queryFn: () => api.get<{ items: Project[] }>("/api/projects"), enabled: open });
  const tpl = useTemplates();

  const groups = useMemo(() => {
    const s = q.trim().toLowerCase();
    const all = projects.data?.items ?? [];
    const match = (i: Item) => !s || i.label.toLowerCase().includes(s) || i.hint?.toLowerCase().includes(s);
    const out: [string, Item[]][] = [];
    if (SIZE.test(q)) out.push(["Search", [{ key: "size", label: `Parts sized like ${q.trim()}`, hint: "Size search", icon: <Ruler className="h-4 w-4" />, to: `/app/projects?q=${encodeURIComponent(q.trim())}` }]]);
    const projs = all.map(p => ({ key: `p-${p.id}`, label: p.name, hint: p.last_status?.material ?? "Project", icon: <FolderKanban className="h-4 w-4" />, to: `/app/projects/${p.id}` }))
      .filter(i => !s || i.label.toLowerCase().includes(s) || (i.hint ?? "").toLowerCase().includes(s));
    if (projs.length) out.push([s ? "Projects" : "Recent projects", projs.slice(0, s ? 8 : 5)]);
    const acts = ACTIONS.filter(match);
    if (acts.length) out.push(["Actions", acts]);
    const mods = modules.filter(m => m.code !== "design").map(m => ({ key: `m-${m.code}`, label: m.name, hint: "Module", icon: <Icon name={m.icon} />, to: `/app/modules/${m.code}` })).filter(match);
    if (mods.length) out.push(["Modules", mods]);
    const tps = (tpl.data?.items ?? []).map(t => ({ key: `t-${t.code}`, label: t.name, hint: "Start from this brief", icon: <Icon name={t.icon} />, to: `/app?template=${t.code}` })).filter(match);
    if (tps.length && s) out.push(["Templates", tps]);
    return out;
  }, [q, modules, projects.data, tpl.data]);
  const flat = groups.flatMap(([, xs]) => xs);

  useEffect(() => { setSel(0); }, [q, open]);
  const go = (i?: Item) => { if (!i) return; onOpenChange(false); setQ(""); nav(i.to); };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-[12vh] z-50 w-[calc(100vw-32px)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-border bg-panel shadow-pop animate-fade-in">
          <Dialog.Title className="sr-only">Search</Dialog.Title>
          <div className="flex items-center gap-2 border-b border-border px-4">
            <Search className="h-4 w-4 text-muted" />
            <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search parts, a size like 120x80x10, pages…"
              className="h-12 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted"
              onKeyDown={e => {
                if (e.key === "ArrowDown") { e.preventDefault(); setSel(s => Math.min(s + 1, flat.length - 1)); }
                if (e.key === "ArrowUp") { e.preventDefault(); setSel(s => Math.max(s - 1, 0)); }
                if (e.key === "Enter") go(flat[sel]);
              }} />
          </div>
          <div className="max-h-[50vh] overflow-y-auto p-1.5">
            {flat.length === 0 && <div className="px-3 py-8 text-center text-sm text-muted">No matches</div>}
            {groups.map(([label, xs]) => (
              <div key={label}>
                <div className="px-3 pb-1 pt-2 text-[10.5px] font-semibold uppercase tracking-[.1em] text-muted">{label}</div>
                {xs.map(i => {
                  const n = flat.indexOf(i);
                  return (
                    <button key={i.key} onMouseEnter={() => setSel(n)} onClick={() => go(i)}
                      className={cx("flex w-full items-center gap-3 rounded px-3 py-2 text-left text-sm", n === sel && "bg-primary-soft text-primary")}>
                      <span className="text-muted">{i.icon}</span><span className="flex-1 truncate">{i.label}</span>
                      <span className="max-w-[40%] truncate text-xs text-muted">{i.hint}</span>
                      {n === sel && <CornerDownLeft className="h-3.5 w-3.5 shrink-0" />}
                    </button>);
                })}
              </div>))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
