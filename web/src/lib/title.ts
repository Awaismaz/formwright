import { useEffect } from "react";

/** Browser tab title per route: "Billing · Formwright". */
export function useTitle(title?: string | null) {
  useEffect(() => {
    document.title = title ? `${title} · Formwright` : "Formwright";
  }, [title]);
}
