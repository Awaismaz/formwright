import { Link } from "react-router-dom";
import { Coins } from "lucide-react";
import { cx } from "@/lib/format";
import type { CostLine, Estimate } from "./types";

/** "about 275 tokens" or "about 275 tokens (up to 320)" */
export function about(c: CostLine): string {
  return c.high > c.tokens ? `about ${c.tokens} tokens (up to ${c.high})` : `about ${c.tokens} tokens`;
}

/** A run starts only when the balance covers the upper measured estimate (the server checks the same rule). */
export function covers(e: Estimate | undefined, kind: "read" | "build"): boolean {
  return !e || e.unlimited || (e.balance ?? 0) >= e[kind].high;
}

const BASIS = "Measured on recent runs. A run starts only when your balance covers the upper figure.";

/** One line under the drop zone: what a read and a build cost, and what the workspace has. */
export function CostStrip({ e }: { e: Estimate }) {
  const short = !covers(e, "read");
  return (
    <div className={cx("mt-1 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[12.5px]", short ? "text-warning" : "text-muted")}
      title={BASIS} data-testid="cost-strip">
      <Coins className="h-3.5 w-3.5" />
      <span>Image read by AI vision: <b className="font-semibold text-text">{about(e.read)}</b></span>
      <span aria-hidden>·</span>
      <span>Model build: <b className="font-semibold text-text">{about(e.build)}</b></span>
      {e.unlimited ? <span>· No token limit on this workspace</span>
        : <span>· You have <b className="font-semibold tabular-nums text-text">{e.balance?.toLocaleString("en-GB")}</b>{short && <> · <Link className="pointer-events-auto underline" to="/app/billing#tokens">Top up to read images</Link></>}</span>}
    </div>
  );
}
