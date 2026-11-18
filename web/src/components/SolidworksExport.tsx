import { useState } from "react";
import { Download, Info } from "lucide-react";
import { Button, Modal } from "@/components/ui";
import { cx } from "@/lib/format";
import { saveNative } from "@/components/NativeExport";

/** CAD-070 disclosure, shown wherever "Export for SOLIDWORKS" is offered (Studio Files panel, Projects menu). */
export const SOLIDWORKS_DISCLOSURE =
  "SOLIDWORKS opens this as an imported solid: exact geometry, but no Formwright feature history, sketches or driving dimensions. " +
  "The parameters come in a separate sheet for reference; they do not drive the imported body. To change the part, edit it here and export again.";

const SCHEMAS = [
  { id: "ap214", label: "STEP AP214", hint: "Recommended. Opens in every SOLIDWORKS version, with the part name and colour." },
  { id: "ap242", label: "STEP AP242", hint: "Newer standard, for teams that standardise on AP242." },
] as const;

/** "Export for SOLIDWORKS": a zip with a SOLIDWORKS-friendly STEP (mm, named body, material colour), the parameter
 *  sheet (CSV) and a README with this disclosure. Native feature trees are on the roadmap (Native CAD bridge). */
export function SolidworksExportDialog({ open, onOpenChange, projectId, name }: {
  open: boolean; onOpenChange: (v: boolean) => void; projectId: string; name: string;
}) {
  const [schema, setSchema] = useState<"ap214" | "ap242">("ap214");
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    const ok = await saveNative(`/api/projects/${projectId}/export/solidworks?schema=${schema}`, `${name}_SOLIDWORKS.zip`, "zip");
    setBusy(false);
    if (ok) onOpenChange(false);
  };
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Export for SOLIDWORKS"
      description="A STEP file prepared for SOLIDWORKS (millimetres, the part's name on the body, the material colour), its parameter sheet and a short read-me, in one zip."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button icon={<Download className="h-4 w-4" />} loading={busy} onClick={() => void go()} data-testid="solidworks-download">Download zip</Button></>}>
      <div className="space-y-3">
        <div className="flex gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-[12.5px]" data-testid="solidworks-disclosure">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <div><p>{SOLIDWORKS_DISCLOSURE}</p>
            <p className="mt-1 text-muted">Native SOLIDWORKS feature trees are planned (Native CAD bridge). Until then, STEP is the path.</p></div>
        </div>
        <div role="radiogroup" aria-label="STEP format" className="space-y-1.5">
          {SCHEMAS.map(s => (
            <label key={s.id} className={cx("flex cursor-pointer items-start gap-3 rounded-lg border p-2.5", schema === s.id ? "border-primary/60 bg-primary-soft" : "border-border hover:border-primary/40")}>
              <input type="radio" name="sw-schema" className="mt-1" checked={schema === s.id} onChange={() => setSchema(s.id)} />
              <div><div className="text-sm font-medium">{s.label}</div><div className="text-xs text-muted">{s.hint}</div></div>
            </label>))}
        </div>
      </div>
    </Modal>
  );
}
