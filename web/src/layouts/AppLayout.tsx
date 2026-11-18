import { useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell, ChevronDown, ChevronRight, ChevronsLeft, ChevronsRight, CircleHelp, Coins, CreditCard, FolderKanban, Home,
  LayoutGrid, Lock, LogOut, MailWarning, Menu as MenuIcon, Moon, Search, Settings as SettingsIcon, Shield, Sun, Users,
  UserRound, X, Zap,
} from "lucide-react";
import { toast } from "sonner";
import { api, setCurrentOrg } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";
import { useTitle } from "@/lib/title";
import type { Catalog, Project } from "@/lib/types";
import { ago, cx, num } from "@/lib/format";
import {
  Avatar, Badge, Button, Logo, LogoMark, Menu, MenuContent, MenuItem, MenuLabel, MenuSeparator, MenuTrigger, Tip,
} from "@/components/ui";
import { Icon } from "@/components/icons";
import GodPanel from "@/components/GodPanel";
import CommandPalette from "@/components/CommandPalette";
import { APP_TOUR, runTour } from "@/lib/tour";
import { Building2 } from "lucide-react"; // Design Office nav entry

/** Below this a trial can't make another typical part: the banner and the notification say so. */
export const LOW_TOKENS = 150;

function useStored(key: string, initial: boolean): [boolean, (v: boolean) => void] {
  const [c, setC] = useState(() => { try { const v = localStorage.getItem(key); return v === null ? initial : v === "1"; } catch { return initial; } });
  return [c, (v) => { setC(v); try { localStorage.setItem(key, v ? "1" : "0"); } catch { /* ignore */ } }];
}

function NavItem({ to, icon, label, collapsed, end, tour, right, indent }: {
  to: string; icon: React.ReactNode; label: string; collapsed: boolean; end?: boolean; tour?: string; right?: React.ReactNode; indent?: boolean;
}) {
  const link = (
    <NavLink to={to} end={end} data-tour={tour}
      className={({ isActive }) => cx("group flex items-center gap-3 rounded px-2.5 text-[13px] transition",
        indent ? "h-8 pl-[34px]" : "h-9",
        isActive ? "bg-primary text-white shadow-sm" : "text-chrome-fg/85 hover:bg-white/[.07] hover:text-white",
        collapsed && "justify-center px-0 pl-0")}>
      <span className={cx("shrink-0", indent ? "h-3.5 w-3.5 [&>svg]:h-3.5 [&>svg]:w-3.5" : "h-4 w-4 [&>svg]:h-4 [&>svg]:w-4")}>{icon}</span>
      {!collapsed && <span className="flex-1 truncate">{label}</span>}
      {!collapsed && right}
    </NavLink>
  );
  return collapsed ? <Tip content={label}>{link}</Tip> : link;
}

function Section({ label, collapsed, children }: { label: string; collapsed: boolean; children: React.ReactNode }) {
  return (
    <div className="mt-5">
      {!collapsed ? <div className="mb-1.5 px-2.5 text-[10.5px] font-semibold uppercase tracking-[.12em] text-chrome-muted">{label}</div>
        : <div className="mx-auto mb-2 h-px w-6 bg-white/10" />}
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

interface Note { id: string; title: string; body: string; link: string | null; read: boolean; created_at: string }

function Notifications() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => api.get<{ items: Note[]; unread: number }>("/api/notifications"), refetchInterval: 30_000 });
  const unread = q.data?.unread ?? 0;
  return (
    <Menu onOpenChange={(o) => { if (!o && unread) api.post("/api/notifications/read-all").then(() => qc.invalidateQueries({ queryKey: ["notifications"] })); }}>
      <MenuTrigger asChild>
        <button className="relative rounded p-2 text-muted hover:bg-text/5 hover:text-text" aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"}>
          <Bell className="h-[18px] w-[18px]" />
          {unread > 0 && <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">{unread}</span>}
        </button>
      </MenuTrigger>
      <MenuContent className="w-[min(320px,calc(100vw-24px))] p-0">
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
  const [sent, setSent] = useState(false);
  const out: React.ReactNode[] = [];
  const unlimited = !!(me?.god?.enabled && me.god.bypass_tokens);
  if (me?.impersonating) out.push(
    <div key="imp" className="flex items-center justify-center gap-3 bg-accent px-4 py-1.5 text-[13px] text-white">
      <UserRound className="h-4 w-4" /> Viewing as <b>{me.user?.email}</b> (signed in as {me.impersonating.actor_email})
      <button className="rounded bg-white/20 px-2 py-0.5 font-medium hover:bg-white/30"
        onClick={async () => { await api.post("/api/admin/stop-impersonation"); await refresh(); nav("/app/admin/users"); }}>Stop</button>
    </div>);
  if (me?.user && !me.user.email_verified && me.user.verify_by) {
    const hours = Math.max(1, Math.round((new Date(me.user.verify_by + "Z").getTime() - Date.now()) / 3_600_000));
    out.push(
      <div key="verify" className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-primary/20 bg-primary-soft px-4 py-1.5 text-[13px] text-text">
        <MailWarning className="h-4 w-4 text-primary" />
        <span>Confirm your email to keep going: we sent a link to <b>{me.user.email}</b>. Your workspace stays open for {hours} more hour{hours === 1 ? "" : "s"}.</span>
        <button disabled={sent} className="font-semibold text-primary hover:underline disabled:text-muted disabled:no-underline"
          onClick={async () => { try { await api.post("/api/auth/resend-verification"); setSent(true); toast.success("Link sent again."); } catch { toast.error("Could not resend. Try again in a few minutes."); } }}>
          {sent ? "Sent" : "Resend link"}</button>
      </div>);
  }
  if (org?.plan_status === "past_due") out.push(
    <div key="pd" className="flex items-center justify-center gap-3 bg-danger px-4 py-1.5 text-[13px] text-white">
      Your last payment failed. Update billing to avoid interruption.
      <Link to="/app/billing" className="rounded bg-white/20 px-2 py-0.5 font-medium hover:bg-white/30">Fix billing</Link>
    </div>);
  else if (org?.on_trial && !unlimited && (org.expired || (org.days_left ?? 99) <= 3 || org.token_balance < LOW_TOKENS)) out.push(
    <div key="trial" className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-warning/30 bg-warning/10 px-4 py-1.5 text-[13px] text-text">
      <Zap className="h-4 w-4 text-warning" />
      {org.expired ? "Your free trial has ended. Your parts stay open; design runs and the other modules need a plan."
        : org.token_balance < LOW_TOKENS ? `${num(Math.max(0, org.token_balance))} trial tokens left, less than a typical new part.`
        : `${org.days_left} day${org.days_left === 1 ? "" : "s"} left in your trial.`}
      <Link to="/app/billing" className="font-semibold text-primary hover:underline">Choose a plan →</Link>
    </div>);
  return <>{out}</>;
}

const TITLES: [RegExp, string][] = [
  [/^\/app\/?$/, "Home"], [/^\/app\/projects\/?$/, "Projects"], [/^\/app\/modules\/?$/, "Modules"],
  [/^\/app\/billing/, "Billing & tokens"], [/^\/app\/checkout/, "Checkout"], [/^\/app\/team/, "Team"],
  [/^\/app\/settings/, "Settings"], [/^\/app\/help/, "Help"], [/^\/app\/admin/, "Admin"],
];

export default function AppLayout() {
  const { me, refresh } = useSession();
  const loc = useLocation();
  const nav = useNavigate();
  const qc = useQueryClient();
  const studio = /^\/app\/projects\/[^/]+\/?$/.test(loc.pathname);
  // the Design Studio starts with the sidebar collapsed (remembered separately) so the ribbon and viewer get the width (STU-09)
  const [appCollapsed, setAppCollapsed] = useStored("fw_sidebar", false);
  const [studioCollapsed, setStudioCollapsed] = useStored("fw_sidebar_studio", true);
  const [collapsed, setCollapsed] = studio ? [studioCollapsed, setStudioCollapsed] : [appCollapsed, setAppCollapsed];
  const [modsOpen, setModsOpen] = useStored("fw_nav_modules", false);
  const [peek, setPeek] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api.get<Catalog>("/api/billing/catalog"), staleTime: 300_000 });
  const org = me?.org;
  const user = me?.user;
  const owned = useMemo(() => new Set(org?.god_unlock ? catalog.data?.modules.map(m => m.code) : org?.modules), [org, catalog.data]);

  // Workspace pages (a project in the Studio, a module on a part) get the room: the sidebar folds to icons.
  const projectMatch = useMatch("/app/projects/:id");
  const moduleMatch = useMatch("/app/modules/:code");
  const workspace = !!projectMatch || !!moduleMatch;
  const folded = collapsed || (workspace && !peek);
  useEffect(() => { setPeek(false); setMobileOpen(false); }, [loc.pathname]);

  const projectId = projectMatch?.params.id;
  const project = useQuery({ queryKey: ["project", projectId], enabled: !!projectId,
    queryFn: () => api.get<Project>(`/api/projects/${projectId}`) });
  const moduleName = catalog.data?.modules.find(m => m.code === moduleMatch?.params.code)?.name;
  useTitle(projectId ? project.data?.name : moduleName ?? TITLES.find(([rx]) => rx.test(loc.pathname))?.[1]);

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
  const lowTokens = !unlimited && (org?.token_balance ?? 0) < LOW_TOKENS;
  const modules = (catalog.data?.modules ?? []).filter(m => m.code !== "design" && m.status === "live");
  const onModules = loc.pathname.startsWith("/app/modules");
  const showMods = (modsOpen || (onModules && !folded));

  const sidebar = (f: boolean) => (<>
    <div className={cx("flex h-14 items-center border-b border-white/[.06]", f ? "justify-center" : "px-4")}>
      <Link to="/app" aria-label="Formwright home">{f ? <LogoMark size={26} /> : <Logo size={24} dark />}</Link>
      <button className="ml-auto rounded p-1.5 text-chrome-muted hover:text-white md:hidden" onClick={() => setMobileOpen(false)} aria-label="Close menu"><X className="h-4 w-4" /></button>
    </div>
    {!f && org && (
      <Menu>
        <MenuTrigger asChild>
          <button className="mx-3 mt-3 flex items-center gap-2.5 rounded-md border border-white/[.08] bg-white/[.04] px-2.5 py-2 text-left hover:bg-white/[.08]">
            <span className="flex h-7 w-7 items-center justify-center rounded bg-gradient-to-br from-primary to-[#174A96] text-[11px] font-bold text-white">{org.name.slice(0, 2).toUpperCase()}</span>
            <span className="min-w-0 flex-1"><span className="block truncate text-[13px] font-medium text-white">{org.name}</span>
              <span className="block text-[11px] text-chrome-muted">{org.plan_name} · <span className="capitalize">{org.role}</span></span></span>
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
      <Section label="Workspace" collapsed={f}>
        <NavItem to="/app" end icon={<Home />} label="Home" collapsed={f} />
        <NavItem to="/app/projects" icon={<FolderKanban />} label="Projects" collapsed={f} tour="nav-projects" />
        <NavItem to="/app/office" icon={<Building2 />} label="Design Office" collapsed={f} />
        <div data-tour="nav-modules">
          {f ? <NavItem to="/app/modules" icon={<LayoutGrid />} label="Modules" collapsed /> : (
            <div className={cx("flex h-9 items-center rounded text-[13px] transition", loc.pathname === "/app/modules" ? "bg-primary text-white shadow-sm" : "text-chrome-fg/85 hover:bg-white/[.07] hover:text-white")}>
              <Link to="/app/modules" className="flex h-full flex-1 items-center gap-3 px-2.5"><LayoutGrid className="h-4 w-4" />Modules</Link>
              <button onClick={() => setModsOpen(!showMods)} className="mr-1 rounded p-1 hover:bg-white/10" aria-label={showMods ? "Hide modules" : "Show modules"} aria-expanded={showMods}>
                {showMods ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}</button>
            </div>)}
          {showMods && !f && <div className="mt-0.5 space-y-0.5">
            {modules.map(m => (
              <NavItem key={m.code} to={`/app/modules/${m.code}`} indent icon={<Icon name={m.icon} />} label={m.name} collapsed={false}
                right={!owned.has(m.code) ? <Lock className="h-3 w-3 text-chrome-muted" aria-label="Not in your plan" /> : undefined} />))}
          </div>}
        </div>
      </Section>
      <Section label="Account" collapsed={f}>
        <NavItem to="/app/billing" icon={<CreditCard />} label="Billing & tokens" collapsed={f} />
        <NavItem to="/app/team" icon={<Users />} label="Team" collapsed={f} />
        <NavItem to="/app/settings" icon={<SettingsIcon />} label="Settings" collapsed={f} />
        {me?.user?.is_superadmin && <NavItem to="/app/admin" icon={<Shield />} label="Admin console" collapsed={f} />}
      </Section>
    </nav>
    {!f && org?.on_trial && (
      <div className="mx-3 mb-3 flex items-center gap-2 rounded-md border border-white/[.08] bg-white/[.04] px-2.5 py-2">
        <div className="min-w-0 flex-1 text-[11.5px] leading-tight">
          <div className="font-semibold text-white">Free trial</div>
          <div className="text-chrome-muted">{org.expired ? "Ended" : `${org.days_left} days`} · {num(Math.max(0, org.token_balance))} tokens</div>
        </div>
        <Button size="sm" variant="accent" className="h-7 px-2.5" onClick={() => nav("/app/billing")}>Upgrade</Button>
      </div>
    )}
    <button onClick={() => (workspace && collapsed === false ? setPeek(!peek) : setCollapsed(!collapsed))}
      className="hidden h-10 items-center justify-center gap-2 border-t border-white/[.06] text-[12px] text-chrome-muted hover:text-white md:flex"
      aria-label={f ? "Expand sidebar" : "Collapse sidebar"}>
      {f ? <ChevronsRight className="h-4 w-4" /> : <><ChevronsLeft className="h-4 w-4" /> Collapse</>}
    </button>
  </>);

  return (
    <div className="flex h-full flex-col">
      <Banners />
      <div className="flex min-h-0 flex-1">
        {/* ---------------- sidebar: fixed rail on desktop, drawer on phones */}
        <aside className={cx("hidden shrink-0 flex-col bg-chrome text-chrome-fg transition-[width] duration-200 md:flex", folded ? "w-[60px]" : "w-[244px]")}>
          {sidebar(folded)}
        </aside>
        {mobileOpen && <div className="fixed inset-0 z-50 flex md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <aside className="relative flex w-[264px] max-w-[85vw] flex-col bg-chrome text-chrome-fg shadow-pop animate-fade-in">{sidebar(false)}</aside>
        </div>}

        {/* ---------------- main */}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border bg-panel px-3 sm:gap-3 sm:px-4">
            <button className="rounded p-2 text-muted hover:bg-text/5 md:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu"><MenuIcon className="h-5 w-5" /></button>
            <button onClick={() => setPaletteOpen(true)} aria-label="Search"
              className="flex h-9 min-w-0 items-center gap-2 rounded border border-border bg-panel2 px-3 text-left text-sm text-muted hover:border-primary/40 max-sm:w-9 max-sm:justify-center max-sm:px-0 sm:flex-1 sm:max-w-md">
              <Search className="h-4 w-4 shrink-0" /> <span className="flex-1 truncate max-sm:hidden">Search parts, sizes, modules…</span><span className="kbd max-sm:hidden">Ctrl K</span>
            </button>
            <div className="ml-auto flex items-center gap-1 sm:gap-1.5">
              {me?.god?.available && <div className="mr-1 max-sm:hidden"><GodPanel /></div>}
              {org && (
                <Tip content={unlimited ? "God mode: unlimited tokens — runs are not charged" : "Token balance for design-agent runs"} side="bottom">
                  <Link to="/app/billing#tokens" data-tour="tokens"
                    className={cx("mr-1 inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] font-medium tabular-nums",
                      lowTokens ? "border-warning/40 bg-warning/10 text-warning" : "border-border bg-panel2 text-text hover:border-primary/40")}>
                    <Coins className="h-4 w-4" /> {unlimited ? "∞" : num(org.token_balance)} <span className="hidden text-muted sm:inline">{unlimited ? "unlimited" : "tokens"}</span>
                  </Link>
                </Tip>
              )}
              <Notifications />
              <Tip content="Help, guides and tours" side="bottom">
                <Link to="/app/help" data-tour="help" className="rounded p-2 text-muted hover:bg-text/5 hover:text-text" aria-label="Help"><CircleHelp className="h-[18px] w-[18px]" /></Link>
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
            {workspace && <div className="border-b border-border bg-panel2 px-4 py-2 text-[12.5px] text-muted md:hidden">
              The Studio and modules are built for a larger screen. You can review parts here; model and edit on a desktop.</div>}
            <Outlet />
          </main>
        </div>
      </div>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} modules={catalog.data?.modules ?? []} />
    </div>
  );
}
