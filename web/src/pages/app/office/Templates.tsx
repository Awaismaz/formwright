import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutTemplate, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { ago } from "@/lib/format";
import { Button, Card } from "@/components/ui";
import { BASE } from "./api";

export interface PartTemplate {
  id: string; name: string; family: string; features: Record<string, number>; params: number; mapped: number;
  finish: number; design: number; uses: number; material?: string | null; created_at?: string; created_by?: string;
  source: { program?: string; program_name?: string; title?: string; ticket?: string };
}

/** Plain words for a template's family ("hub:pulley" -> "pulley", "plate" -> "plate"). */
export function familyLabel(f: string): string {
  const tail = f.includes(":") ? f.split(":")[1] : f;
  return tail.replace(/_/g, " ");
}

export function useTemplates() {
  return useQuery({ queryKey: ["office-templates"], queryFn: () => api.get<{ items: PartTemplate[]; can_edit: boolean }>(`${BASE}/templates`),
    refetchInterval: 60_000 });
}

/** The workspace's part templates: kept from AI-designed parts, reused by the next ticket of the same family. */
export function TemplatesPanel() {
  const q = useTemplates();
  const qc = useQueryClient();
  const items = q.data?.items ?? [];
  const remove = async (t: PartTemplate) => {
    try {
      await api.del(`${BASE}/templates/${t.id}`);
      qc.invalidateQueries({ queryKey: ["office-templates"] });
      toast.success(`Template ${t.name} deleted`);
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not delete the template"); }
  };
  return (
    <section data-templates>
      <h2 className="label mb-3 flex items-center gap-1.5"><LayoutTemplate className="h-3.5 w-3.5" />Part templates</h2>
      <Card className="overflow-hidden">
        {items.length === 0 ? <div className="px-4 py-6 text-center text-[12.5px] text-muted">
          No templates yet. Keep an approved part the designer made with AI as a template, and the next part of the same kind starts from it (or is built from it without AI when every size maps).</div>
          : items.map(t => <div key={t.id} className="flex items-start gap-2 border-b border-border px-3 py-2.5 text-[12.5px] last:border-0" data-template={t.id}>
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{t.name} <span className="font-normal text-muted">· {familyLabel(t.family)}</span></div>
              <div className="text-[11.5px] text-muted">
                {t.mapped} of {t.params} sizes follow the interfaces{t.finish ? `, ${t.finish} finish` : ""}{t.design ? `, ${t.design} design choices` : ""}
                {t.uses ? ` · used ${t.uses}×` : ""} · from {t.source.title ?? "a part"}{t.source.program_name ? ` in ${t.source.program_name}` : ""}{t.created_at ? `, ${ago(t.created_at)}` : ""}
              </div>
            </div>
            {q.data?.can_edit && <Button size="sm" variant="ghost" aria-label={`Delete template ${t.name}`} icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => remove(t)} />}
          </div>)}
      </Card>
    </section>
  );
}
