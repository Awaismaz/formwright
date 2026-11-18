import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Home, OfficeEvent, Program } from "./types";

export const BASE = "/api/office";

export function useHome() {
  return useQuery({ queryKey: ["office-home"], queryFn: () => api.get<Home>(`${BASE}/home`), refetchInterval: 20_000 });
}

export function useProgram(pid: string | undefined) {
  return useQuery({
    queryKey: ["office-program", pid], enabled: !!pid,
    queryFn: () => api.get<Program>(`${BASE}/programs/${pid}`),
    // the live stream drives updates; polling is the safety net (and picks up Studio builds on linked parts)
    refetchInterval: q => (q.state.data?.status === "planning" ? 1500 : 15_000),
  });
}

/** Live events for one program (SSE). Every event refreshes the program; the latest few are returned for a
 * "just happened" strip. Falls back silently to polling if the stream drops. */
export function useProgramEvents(pid: string | undefined) {
  const qc = useQueryClient();
  const [recent, setRecent] = useState<OfficeEvent[]>([]);
  const [live, setLive] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (!pid) return;
    const es = new EventSource(`${BASE}/programs/${pid}/events`);
    es.onopen = () => setLive(true);
    es.onerror = () => setLive(false);
    es.onmessage = (m) => {
      let ev: OfficeEvent | { type: "hello" };
      try { ev = JSON.parse(m.data); } catch { return; }
      if (ev.type === "hello") { setLive(true); return; }
      const e = ev as OfficeEvent;
      setRecent(r => [e, ...r.filter(x => x.seq !== e.seq)].slice(0, 6));
      // coalesce bursts (approval opens many tickets at once)
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        qc.invalidateQueries({ queryKey: ["office-program", pid] });
        qc.invalidateQueries({ queryKey: ["office-activity", pid] });
        qc.invalidateQueries({ queryKey: ["office-home"] });
      }, 120);
    };
    return () => { es.close(); if (timer.current) clearTimeout(timer.current); };
  }, [pid, qc]);
  return { recent, live };
}
