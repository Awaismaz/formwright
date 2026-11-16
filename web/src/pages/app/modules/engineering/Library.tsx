import { Card } from "@/components/ui";
import { LevelBadge } from "./CalcForm";
import { type Catalog, fmt } from "./types";

export default function LibraryPanel({ cat }: { cat: Catalog }) {
  const L = cat.library;
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
      <Card className="overflow-hidden" data-panel="materials">
        <div className="border-b border-border px-4 py-3"><h3 className="text-[14px] font-semibold">Material properties</h3><p className="mt-0.5 text-[12px] text-muted">{L.materials_note} Library {L.materials_version}.</p></div>
        <div className="overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead className="bg-panel2 text-left text-[11px] text-muted"><tr>{["Material", "Condition", "Basis", "Sut MPa", "Sy MPa", "E GPa", "ν", "Fatigue MPa", "Source"].map(h => <th key={h} className="px-3 py-1.5 font-medium">{h}</th>)}</tr></thead>
            <tbody>{L.materials.map(m => (
              <tr key={m.code} className="border-t border-border align-top">
                <td className="px-3 py-1.5 font-medium">{m.name}</td><td className="px-3 py-1.5">{m.condition}</td><td className="px-3 py-1.5">{m.basis}</td>
                <td className="px-3 py-1.5 tabular-nums">{fmt(m.Sut_MPa)}</td><td className="px-3 py-1.5 tabular-nums">{m.Sy_MPa === null ? "— (brittle)" : fmt(m.Sy_MPa)}</td>
                <td className="px-3 py-1.5 tabular-nums">{fmt(m.E_GPa)}</td><td className="px-3 py-1.5 tabular-nums">{fmt(m.nu)}</td>
                <td className="px-3 py-1.5 tabular-nums" title={m.fatigue_note}>{m.fatigue_MPa ? fmt(m.fatigue_MPa) : "—"}</td>
                <td className="px-3 py-1.5 text-[11.5px] text-muted">{m.source}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </Card>
      <div className="space-y-4">
        <Card className="p-4">
          <h3 className="text-[14px] font-semibold">Standards and handbook tables</h3>
          <p className="mt-0.5 text-[12px] text-muted">Version {L.standards_version}. Values transcribed from the cited references; verify against the current edition before release.</p>
          <ul className="mt-3 space-y-2 text-[12.5px]">{L.tables.map(t => <li key={t.table}><div className="font-medium">{t.table} <span className="font-normal text-muted">({t.rows} rows)</span></div><div className="text-[11.5px] text-muted">{t.source}</div></li>)}</ul>
        </Card>
        <Card className="p-4">
          <h3 className="text-[14px] font-semibold">Advice levels</h3>
          <ul className="mt-3 space-y-2.5 text-[12.5px]">{Object.entries(cat.levels).map(([k, l]) => <li key={k} className="flex items-start gap-2"><LevelBadge level={k} cat={cat} className="shrink-0" /><span className="text-muted">{l.meaning}</span></li>)}</ul>
          <p className="mt-3 text-[11.5px] text-muted">Calculator engine {cat.engine}. Units are converted with pint; a value in the wrong dimension is rejected.</p>
        </Card>
      </div>
    </div>
  );
}
