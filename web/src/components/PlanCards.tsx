import { Check } from "lucide-react";
import type { Product } from "@/lib/types";
import { money } from "@/lib/format";
import { Badge, Button } from "./ui";
import { cx } from "@/lib/format";

export function PlanCards({ plans, current, onChoose, busy, ctaLabel }: {
  plans: Product[]; current?: string | null; busy?: string | null;
  onChoose: (p: Product) => void; ctaLabel?: (p: Product) => string;
}) {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {plans.map(p => {
        const isCurrent = current === p.code;
        return (
          <div key={p.code} className={cx("card relative flex flex-col p-5", p.highlight && "border-primary ring-1 ring-primary")}>
            {p.highlight && <Badge tone="primary" className="absolute -top-2.5 left-5 bg-primary text-white">Most popular</Badge>}
            <div className="flex items-center justify-between">
              <h3 className="text-[15px] font-semibold">{p.name}</h3>
              {isCurrent && <Badge tone="success">Current</Badge>}
            </div>
            <p className="mt-1 min-h-[36px] text-[13px] text-muted">{p.tagline}</p>
            <div className="mt-4 flex items-baseline gap-1">
              {p.contact_sales ? <span className="text-2xl font-semibold">Custom</span> : <>
                <span className="text-3xl font-semibold tracking-tight">{money(p.price_cents)}</span>
                {p.interval && p.price_cents > 0 && <span className="text-sm text-muted">/ {p.interval}</span>}
              </>}
            </div>
            <ul className="mt-5 flex-1 space-y-2 text-[13px]">
              {p.features.map(f => <li key={f} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-success" />{f}</li>)}
            </ul>
            <Button className="mt-6 w-full" variant={p.highlight ? "primary" : "secondary"} loading={busy === p.code}
              disabled={isCurrent || (!p.purchasable && !p.contact_sales)} onClick={() => onChoose(p)}>
              {isCurrent ? "Current plan" : ctaLabel ? ctaLabel(p) : p.contact_sales ? "Contact sales" : "Choose " + p.name}
            </Button>
          </div>
        );
      })}
    </div>
  );
}
