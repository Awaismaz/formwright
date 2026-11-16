import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as Dialog from "@radix-ui/react-dialog";
import { CornerDownLeft, FolderKanban, Plus, Search } from "lucide-react";
import { api } from "@/lib/api";
import type { Module, Project } from "@/lib/types";
import { cx } from "@/lib/format";
import { Icon } from "./icons";

interface Item { key: string; label: string; hint?: string; icon: React.ReactNode; to: string }

const ACTIONS: Item[] = [
  { key: "new", label: "New project", hint: "Action", icon: <Plus className="h-4 w-4" />, to: "/app/projects?new=1" },
  { key: "billing", label: "Billing & tokens", hint: "Page", icon: <Icon name="box" />, to: "/app/billing" },
  { key: "team", label: "Invite teammates", hint: "Page", icon: <Icon name="boxes" />, to: "/app/team" },
  { key: "settings", label: "Settings", hint: "Page", icon: <Icon name="cog" />, to: "/app/settings" },
  { key: "tour", label: "Restart guided tour", hint: "Help", icon: <Icon name="circle-dot" />, to: "/app?tour=1" },
  { key: "help", label: "Help center", hint: "Help", icon: <Icon name="square" />, to: "/app/help" },
];

export default function CommandPalette({ open, onOpenChange, modules }: { open: boolean; onOpenChange: (v: boolean) => void; modules: Module[] }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const nav = useNavigate();
  const projects = useQuery({ queryKey: ["projects", false], queryFn: () => api.get<{ items: Project[] }>("/api/projects"), enabled: open });

  const items = useMemo(() => {
    const all: Item[] = [
      ...ACTIONS,
      ...modules.map(m => ({ key: `m-${m.code}`, label: m.name, hint: m.status === "live" ? "Module · Live" : "Module · Preview",
        icon: <Icon name={m.icon} />, to: m.code === "design" ? "/app/projects" : `/app/modules/${m.code}` })),
      ...(projects.data?.items ?? []).map(p => ({ key: `p-${p.id}`, label: p.name, hint: "Project",
        icon: <FolderKanban className="h-4 w-4" />, to: `/app/projects/${p.id}` })),
    ];
    const s = q.trim().toLowerCase();
    return s ? all.filter(i => i.label.toLowerCase().includes(s) || i.hint?.toLowerCase().includes(s)) : all;
  }, [q, modules, projects.data]);

  useEffect(() => { setSel(0); }, [q, open]);
  const go = (i?: Item) => { if (!i) return; onOpenChange(false); setQ(""); nav(i.to); };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Dialog.Content className="fixed left-1/2 top-[12vh] z-50 w-[calc(100vw-32px)] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border border-border bg-panel shadow-pop animate-fade-in">
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <div className="flex items-center gap-2 border-b border-border px-4">
            <Search className="h-4 w-4 text-muted" />
            <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Type a command or search…"
              className="h-12 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted"
              onKeyDown={e => {
                if (e.key === "ArrowDown") { e.preventDefault(); setSel(s => Math.min(s + 1, items.length - 1)); }
                if (e.key === "ArrowUp") { e.preventDefault(); setSel(s => Math.max(s - 1, 0)); }
                if (e.key === "Enter") go(items[sel]);
              }} />
          </div>
          <div className="max-h-[50vh] overflow-y-auto p-1.5">
            {items.length === 0 && <div className="px-3 py-8 text-center text-sm text-muted">No matches</div>}
            {items.map((i, n) => (
              <button key={i.key} onMouseEnter={() => setSel(n)} onClick={() => go(i)}
                className={cx("flex w-full items-center gap-3 rounded px-3 py-2 text-left text-sm", n === sel && "bg-primary-soft text-primary")}>
                <span className="text-muted">{i.icon}</span><span className="flex-1">{i.label}</span>
                <span className="text-xs text-muted">{i.hint}</span>
                {n === sel && <CornerDownLeft className="h-3.5 w-3.5" />}
              </button>
            ))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
