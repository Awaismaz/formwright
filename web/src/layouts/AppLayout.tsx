import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell, ChevronsLeft, ChevronsRight, CircleHelp, Coins, CreditCard, FolderKanban, Home, LayoutGrid, Lock, LogOut,
  Moon, Search, Settings as SettingsIcon, Shield, Sun, Users, UserRound, Zap,
} from "lucide-react";
import { toast } from "sonner";
import { api, setCurrentOrg } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";
import type { Catalog } from "@/lib/types";
import { ago, cx, num } from "@/lib/format";
import {
  Avatar, Badge, Button, Logo, LogoMark, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Tip,
} from "@/components/ui";
import { Icon } from "@/components/icons";
import GodPanel from "@/components/GodPanel";
import CommandPalette from "@/components/CommandPalette";
import { APP_TOUR, runTour } from "@/lib/tour";

function useCollapsed(): [boolean, (v: boolean) => void] {
  const [c, setC] = useState(() => { try { return localStorage.getItem("fw_sidebar") === "1"; } catch { return false; } });
  return [c, (v) => { setC(v); try { localStorage.setItem("fw_sidebar", v ? "1" : "0"); } catch { /* ignore */ } }];
}

function NavItem({ to, icon, label, collapsed, end, tour, right }: {
  to: string; icon: React.ReactNode; label: string; collapsed: boolean; end?: boolean; tour?: string; right?: React.ReactNode;
}) {
  const link = (
    <NavLink to={to} end={end} data-tour={tour}
      className={({ isActive }) => cx("group flex h-9 items-center gap-3 rounded px-2.5 text-[13px] transition",
        isActive ? "bg-primary text-white shadow-sm" : "text-chrome-fg/85 hover:bg-white/[.07] hover:text-white",
        collapsed && "justify-center px-0")}>
      <span className="h-4 w-4 shrink-0 [&>svg]:h-4 [&>svg]:w-4">{icon}</span>
      {!collapsed && <span className="flex-1 truncate">{label}</span>}
      {!collapsed && right}
    </NavLink>
  );
  return collapsed ? <Tip content={label}>{link}</Tip> : link;
}

function Section({ label, collapsed, children, tour }: { label: string; collapsed: boolean; children: React.ReactNode; tour?: string }) {
  return (
    <div className="mt-5" data-tour={tour}>
      {!collapsed ? <div className="mb-1.5 px-2.5 text-[10.5px] font-semibold uppercase tracking-[.12em] text-chrome-muted">{label}</div>
        : <div className="mx-auto mb-2 h-px w-6 bg-white/10" />}
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function Notifications() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => api.get<{ items: { id: string; title: string; body: string; link: string | null; read: boolean; created_at: string }[]; unread: number }>("/api/notifications"), refetchInterval: 30_000 });
  const unread = q.data?.unread ?? 0;
  return (
    <Menu onOpenChange={(o) => { if (!o && unread) api.post("/api/notifications/read-all").then(() => qc.invalidateQueries({ queryKey: ["notifications"] })); }}>
      <MenuTrigger asChild>
        <button className="relative rounded p-2 text-muted hover:bg-text/5 hover:text-text" aria-label="Notifications">
          <Bell className="h-[18px] w-[18px]" />
          {unread > 0 && <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">{unread}</span>}
        </button>
      </MenuTrigger>
      <MenuContent className="w-80 p-0">
        <div className="border-b border-border px-3 py-2.5 text-sm font-semibold">Notifications</div>
        <div className="max-h-96 overflow-y-auto">
          {(q.data?.items ?? []).length === 0 && <div className="px-3 py-8 text-center text-sm text-muted">You're all caught up.</div>}
          {(q.data?.items ?? []).map(n => (
            <button key={n.id} onClick={() => n.link && nav(n.link)}
              className={cx("block w-full border-b border-border px-3 py-2.5 text-left last:border-0 hover:bg-panel2", !n.read && "bg-primary-soft/50")}>
              <div className="text-[13px] font-medium">{n.title}</div>
              {n.body && <div className="mt-0.5 text-xs text-muted">{n.body}</div>}
              <div className="mt-1 text-[11px] text-muted">{ago(n.created_at)}</div>
            </button>
          ))}
        </div>
      </MenuContent>
    </Menu>
  );
}

function Banners() {
  const { me, refresh } = useSession();
  const org = me?.org;
  const nav = useNavigate();
  const out: React.ReactNode[] = [];
  if (me?.impersonating) out.push(
    <div key="imp" className="flex items-center justify-center gap-3 bg-accent px-4 py-1.5 text-[13px] text-white">
      <UserRound className="h-4 w-4" /> Viewing as <b>{me.user?.email}</b> (signed in as {me.impersonating.actor_email})
      <button className="rounded bg-white/20 px-2 py-0.5 font-medium hover:bg-white/30"
        onClick={async () => { await api.post("/api/admin/stop-impersonation"); await refresh(); nav("/app/admin/users"); }}>Stop</button>
    </div>);
  if (org?.plan_status === "past_due") out.push(
    <div key="pd" className="flex items-center justify-center gap-3 bg-danger px-4 py-1.5 text-[13px] text-white">
      Your last payment failed. Update billing to avoid interruption.
      <Link to="/app/billing" className="rounded bg-white/20 px-2 py-0.5 font-medium hover:bg-white/30">Fix billing</Link>
    </div>);
  else if (org?.on_trial && (org.expired || (org.days_left ?? 99) <= 3 || org.token_balance < 50)) out.push(
    <div key="trial" className="flex items-center justify-center gap-3 border-b border-warning/30 bg-warning/10 px-4 py-1.5 text-[13px] text-text">
      <Zap className="h-4 w-4 text-warning" />
      {org.expired ? "Your free trial has ended." : org.token_balance < 50 ? `Only ${Math.max(0, org.token_balance)} trial tokens left.` : `${org.days_left} days left in your trial.`}
      <Link to="/app/billing" className="font-semibold text-primary hover:underline">Choose a plan →</Link>
    </div>);
  return <>{out}</>;
}

export default function AppLayout() {
  const { me, refresh } = useSession();
  const loc = useLocation();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [collapsed, setCollapsed] = useCollapsed();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
  const org = me?.org;
  const user = me?.user;
  const unlocked = useMemo(() => new Set(org?.god_unlock ? catalog.data?.modules.map(m => m.code) : org?.modules), [org, catalog.data]);

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPaletteOpen(true); } };
    addEventListener("keydown", h);
    return () => removeEventListener("keydown", h);
  }, []);

  // Guided tour: first visit to the dashboard after onboarding, or ?tour=1 from anywhere.
  useEffect(() => {
    const force = new URLSearchParams(loc.search).get("tour") === "1";
    if (loc.pathname === "/app" && (force || (user && !user.tour_completed))) {
      const t = setTimeout(() => runTour(APP_TOUR, "app", () => refresh()), 700);
      return () => clearTimeout(t);
    }
    if (force && loc.pathname !== "/app") nav("/app?tour=1", { replace: true });
  }, [loc.pathname, loc.search, user?.tour_completed]); // eslint-disable-line react-hooks/exhaustive-deps

  const switchOrg = async (id: string) => { setCurrentOrg(id); await qc.invalidateQueries(); nav("/app"); };
  const logout = async () => { await api.post("/api/auth/logout"); setCurrentOrg(null); qc.clear(); location.href = "/"; };
  const setTheme = async (theme: string) => { await api.patch("/api/auth/profile", { preferences: { theme } }); await refresh(); };
  const dark = user?.preferences?.theme === "dark";
  const unlimited = !!(me?.god?.enabled && me.god.bypass_tokens);
  const lowTokens = !unlimited && (org?.token_balance ?? 0) < 50;

  return (
    <div className="flex h-full flex-col">
      <Banners />
      <div className="flex min-h-0 flex-1">
        {/* ---------------- sidebar */}
        <aside className={cx("flex shrink-0 flex-col bg-chrome text-chrome-fg transition-[width] duration-200", collapsed ? "w-[60px]" : "w-[244px]")}>
          <div className={cx("flex h-14 items-center border-b border-white/[.06]", collapsed ? "justify-center" : "px-4")}>
            <Link to="/app" aria-label="Formwright home">{collapsed ? <LogoMark size={26} /> : <Logo size={24} dark />}</Link>
          </div>
          {!collapsed && org && (
            <Menu>
              <MenuTrigger asChild>
                <button className="mx-3 mt-3 flex items-center gap-2.5 rounded-md border border-white/[.08] bg-white/[.04] px-2.5 py-2 text-left hover:bg-white/[.08]">
                  <span className="flex h-7 w-7 items-center justify-center rounded bg-gradient-to-br from-primary to-[#174A96] text-[11px] font-bold text-white">{org.name.slice(0, 2).toUpperCase()}</span>
                  <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium text-white">{org.name}</span>
                    <span className="block text-[11px] text-chrome-muted">{org.plan_name} · {org.role}</span></span>
                </button>
              </MenuTrigger>
              <MenuContent align="start">
                <MenuLabel>Workspaces</MenuLabel>
                {(me?.orgs ?? []).map(o => <MenuItem key={o.id} onSelect={() => switchOrg(o.id)}>{o.name}{o.id === org.id && <Badge tone="primary" className="ml-auto">Current</Badge>}</MenuItem>)}
                <MenuSeparator />
                {canManage(org.role) && <MenuItem icon={<Users />} onSelect={() => nav("/app/team")}>Manage team</MenuItem>}
                <MenuItem icon={<CreditCard />} onSelect={() => nav("/app/billing")}>Plan & billing</MenuItem>
              </MenuContent>
            </Menu>
          )}
          <nav className="flex-1 overflow-y-auto px-2.5 pb-4">
            <Section label="Workspace" collapsed={collapsed}>
              <NavItem to="/app" end icon={<Home />} label="Home" collapsed={collapsed} />
              <NavItem to="/app/projects" icon={<FolderKanban />} label="Projects" collapsed={collapsed} tour="nav-projects" />
            </Section>
            <Section label="Modules" collapsed={collapsed} tour="nav-modules">
              {(catalog.data?.modules ?? []).map(m => (
                <NavItem key={m.code} to={m.code === "design" ? "/app/projects?module=design" : `/app/modules/${m.code}`}
                  icon={<Icon name={m.icon} />} label={m.name} collapsed={collapsed}
                  right={m.status === "live" ? <span className="h-1.5 w-1.5 rounded-full bg-success" title="Live" />
                    : !unlocked.has(m.code) ? <Lock className="h-3 w-3 text-chrome-muted" />
                    : <span className="rounded bg-accent/25 px-1 text-[9.5px] font-bold uppercase text-[#F2B784]">Prev</span>} />
              ))}
              <NavItem to="/app/modules" end icon={<LayoutGrid />} label="All modules" collapsed={collapsed} />
            </Section>
            <Section label="Account" collapsed={collapsed}>
              <NavItem to="/app/billing" icon={<CreditCard />} label="Billing & tokens" collapsed={collapsed} />
              <NavItem to="/app/team" icon={<Users />} label="Team" collapsed={collapsed} />
              <NavItem to="/app/settings" icon={<SettingsIcon />} label="Settings" collapsed={collapsed} />
              <NavItem to="/app/help" icon={<CircleHelp />} label="Help & tour" collapsed={collapsed} tour="help" />
              {me?.user?.is_superadmin && <NavItem to="/app/admin" icon={<Shield />} label="Admin console" collapsed={collapsed} />}
            </Section>
          </nav>
          {!collapsed && org?.on_trial && (
            <div className="mx-3 mb-3 rounded-md border border-white/[.08] bg-gradient-to-br from-primary/30 to-transparent p-3">
              <div className="text-[12px] font-semibold text-white">Free trial</div>
              <div className="mt-0.5 text-[11px] text-chrome-muted">{org.expired ? "Ended" : `${org.days_left} days left`} · {num(Math.max(0, org.token_balance))} tokens</div>
              <Button size="sm" variant="accent" className="mt-2.5 w-full" onClick={() => nav("/app/billing")}>Upgrade</Button>
            </div>
          )}
          <button onClick={() => setCollapsed(!collapsed)} className="flex h-10 items-center justify-center gap-2 border-t border-white/[.06] text-[12px] text-chrome-muted hover:text-white">
            {collapsed ? <ChevronsRight className="h-4 w-4" /> : <><ChevronsLeft className="h-4 w-4" /> Collapse</>}
          </button>
        </aside>

        {/* ---------------- main */}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border bg-panel px-4">
            <button onClick={() => setPaletteOpen(true)}
              className="flex h-9 w-full max-w-md items-center gap-2 rounded border border-border bg-panel2 px-3 text-left text-sm text-muted hover:border-primary/40">
              <Search className="h-4 w-4" /> <span className="flex-1">Search projects, modules, actions…</span><span className="kbd">Ctrl K</span>
            </button>
            <div className="ml-auto flex items-center gap-1.5">
              {org && (
                <Tip content={unlimited ? "God mode: unlimited tokens — runs are not charged" : "Token balance — metered AI usage"} side="bottom">
                  <Link to="/app/billing#tokens" data-tour="tokens"
                    className={cx("mr-1 inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] font-medium tabular-nums",
                      lowTokens ? "border-warning/40 bg-warning/10 text-warning" : "border-border bg-panel2 text-text hover:border-primary/40")}>
                    <Coins className="h-4 w-4" /> {unlimited ? "∞" : num(org.token_balance)} <span className="hidden text-muted sm:inline">{unlimited ? "unlimited" : "tokens"}</span>
                  </Link>
                </Tip>
              )}
              <Notifications />
              <Tip content="Help & guided tour" side="bottom">
                <Link to="/app/help" className="rounded p-2 text-muted hover:bg-text/5 hover:text-text"><CircleHelp className="h-[18px] w-[18px]" /></Link>
              </Tip>
              <Menu>
                <MenuTrigger asChild>
                  <button className="ml-1 flex items-center gap-2 rounded-full p-0.5 hover:ring-2 hover:ring-primary/30" aria-label="Account menu">
                    <Avatar name={user?.name ?? "?"} size={30} />
                  </button>
                </MenuTrigger>
                <MenuContent>
                  <div className="px-2.5 py-2"><div className="text-sm font-medium">{user?.name}</div><div className="text-xs text-muted">{user?.email}</div></div>
                  <MenuSeparator />
                  <MenuItem icon={<SettingsIcon />} onSelect={() => nav("/app/settings")}>Settings</MenuItem>
                  <MenuItem icon={dark ? <Sun /> : <Moon />} onSelect={() => setTheme(dark ? "light" : "dark")}>{dark ? "Light theme" : "Dark theme"}</MenuItem>
                  <MenuItem icon={<CircleHelp />} onSelect={() => nav("/app?tour=1")}>Restart guided tour</MenuItem>
                  <MenuSeparator />
                  <MenuItem icon={<LogOut />} danger onSelect={() => logout().catch(() => toast.error("Sign out failed"))}>Sign out</MenuItem>
                </MenuContent>
              </Menu>
            </div>
          </header>
          <main className="min-h-0 flex-1 overflow-y-auto">
            <Outlet />
          </main>
        </div>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} modules={catalog.data?.modules ?? []} />
      {me?.god?.available && <GodPanel />}
    </div>
  );
}
