import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, setCurrentOrg } from "./api";
import type { Me } from "./types";

interface SessionValue {
  me: Me | undefined;
  loading: boolean;
  refresh: () => Promise<void>;
}

const Ctx = createContext<SessionValue>({ me: undefined, loading: true, refresh: async () => {} });

export function SessionProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/auth/me"), staleTime: 30_000 });
  const me = q.data;

  useEffect(() => {
    if (me?.org?.id) setCurrentOrg(me.org.id);
  }, [me?.org?.id]);

  useEffect(() => {
    const pref = me?.user?.preferences?.theme ?? "light";
    const dark = pref === "dark" || (pref === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
    document.documentElement.classList.toggle("dark", dark);
  }, [me?.user?.preferences?.theme]);

  const refresh = async () => { await qc.invalidateQueries(); };
  return <Ctx.Provider value={{ me, loading: q.isLoading, refresh }}>{children}</Ctx.Provider>;
}

export const useSession = () => useContext(Ctx);

export function useOrg() {
  const { me } = useSession();
  return me?.org ?? null;
}

export function canManage(role?: string | null) {
  return role === "owner" || role === "admin";
}
