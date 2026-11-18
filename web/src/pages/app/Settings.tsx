import DesktopOnly from "@/components/DesktopOnly";
import { useState } from "react";
import { toast } from "sonner";
import { KeyRound, Lock, Monitor, Moon, Sun } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";
import { Badge, Button, Card, Field, Input, PageHeader, Tab, TabList, TabPanel, Tabs, Toggle } from "@/components/ui";
import { cx, PAGE } from "@/lib/format";

function Section({ title, desc, children }: { title: string; desc?: string; children: React.ReactNode }) {
  return (
    <Card className="grid gap-6 p-6 md:grid-cols-[240px_1fr]">
      <div><h2 className="font-semibold">{title}</h2>{desc && <p className="mt-1 text-sm text-muted">{desc}</p>}</div>
      <div className="max-w-md space-y-4">{children}</div>
    </Card>
  );
}

export default function Settings() {
  const { me, refresh } = useSession();
  const user = me!.user!;
  const org = me?.org;
  const [name, setName] = useState(user.name);
  const [orgName, setOrgName] = useState(org?.name ?? "");
  const [pw, setPw] = useState({ current: "", next: "" });
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (k: string, fn: () => Promise<unknown>, ok: string) => {
    setBusy(k);
    try { await fn(); await refresh(); toast.success(ok); } catch (e) { toast.error(e instanceof ApiError ? e.message : "Failed"); } finally { setBusy(null); }
  };
  const prefs = user.preferences;
  const setPref = (p: Record<string, unknown>) => run("pref", () => api.patch("/api/auth/profile", { preferences: p }), "Preferences saved");

  return (
    <div className={PAGE}>
      <PageHeader title="Settings" />
      <Tabs defaultValue="profile">
        <TabList className="mb-6"><Tab value="profile">Profile</Tab><Tab value="prefs">Preferences</Tab><Tab value="security">Security</Tab>{org && <Tab value="workspace">Workspace</Tab>}<Tab value="api">API & integrations</Tab></TabList>
        <TabPanel value="profile" className="space-y-6">
          <Section title="Profile" desc="How you appear to teammates.">
            <Field label="Full name"><Input value={name} onChange={e => setName(e.target.value)} /></Field>
            <Field label="Email" hint="Contact support to change your sign-in email."><Input value={user.email} disabled /></Field>
            <Button loading={busy === "name"} disabled={name === user.name} onClick={() => run("name", () => api.patch("/api/auth/profile", { name }), "Profile updated")}>Save</Button>
          </Section>
        </TabPanel>
        <TabPanel value="prefs" className="space-y-6">
          <Section title="Appearance" desc="Light mirrors the classic CAD workspace; dark is easier at night.">
            <div className="grid grid-cols-3 gap-2">
              {([["light", Sun, "Light"], ["dark", Moon, "Dark"], ["system", Monitor, "System"]] as const).map(([v, I, l]) => (
                <button key={v} onClick={() => setPref({ theme: v })} className={cx("flex flex-col items-center gap-2 rounded-lg border p-3 text-sm", (prefs.theme ?? "light") === v ? "border-primary bg-primary-soft text-primary" : "border-border")}><I className="h-5 w-5" />{l}</button>))}
            </div>
          </Section>
          <Section title="Units" desc="Sizes on project cards, the catalogue and size search; default units for new designs.">
            <div className="inline-flex rounded-lg border border-border p-1">{(["mm", "in"] as const).map(u =>
              <button key={u} onClick={() => setPref({ units: u })} className={cx("rounded px-4 py-1.5 text-sm", (prefs.units ?? "mm") === u ? "bg-primary text-white" : "text-muted")}>{u === "mm" ? "Millimetres" : "Inches"}</button>)}</div>
          </Section>
          <Section title="Design agent" desc="How the agent starts a new part.">
            <div className="flex items-center justify-between gap-4"><div><div className="text-sm font-medium">Confirm the brief before building new parts</div><div className="text-xs text-muted">The agent first shows its reading of your request: requirements, assumptions and open questions. You edit and approve it before anything is built. You can skip it for a single message in the chat.</div></div>
              <Toggle checked={prefs.confirm_brief !== false} onChange={v => setPref({ confirm_brief: v })} /></div>
          </Section>
          <Section title="Notifications">
            <div className="flex items-center justify-between"><div><div className="text-sm font-medium">Email me about billing & usage</div><div className="text-xs text-muted">Failed payments and receipts. Run results and teammates' changes arrive in the bell.</div></div>
              <Toggle checked={prefs.notifications_email !== false} onChange={v => setPref({ notifications_email: v })} /></div>
          </Section>
        </TabPanel>
        <TabPanel value="security" className="space-y-6">
          <Section title="Password" desc="Changing your password signs you out on other devices.">
            <Field label="Current password"><Input type="password" value={pw.current} onChange={e => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" /></Field>
            <Field label="New password" hint="At least 10 characters, with letters and numbers."><Input type="password" value={pw.next} onChange={e => setPw({ ...pw, next: e.target.value })} autoComplete="new-password" /></Field>
            <Button loading={busy === "pw"} disabled={!pw.current || !pw.next} icon={<KeyRound className="h-4 w-4" />}
              onClick={() => run("pw", () => api.post("/api/auth/change-password", { current_password: pw.current, new_password: pw.next }).then(() => setPw({ current: "", next: "" })), "Password changed")}>Change password</Button>
          </Section>
          <Section title="Two-factor authentication" desc="Add a second step at sign-in.">
            <div className="flex items-center gap-2"><Badge tone="preview">Preview</Badge><span className="text-sm text-muted">Authenticator-app 2FA and SSO (Enterprise) are on the roadmap.</span></div>
          </Section>
        </TabPanel>
        {org && <TabPanel value="workspace" className="space-y-6">
          <Section title="Workspace" desc="Shown to everyone in this workspace and on invoices.">
            <Field label="Workspace name"><Input value={orgName} onChange={e => setOrgName(e.target.value)} disabled={!canManage(org.role)} /></Field>
            {canManage(org.role) && <Button loading={busy === "org"} disabled={orgName === org.name} onClick={() => run("org", () => api.patch("/api/team/org", { name: orgName }), "Workspace renamed")}>Save</Button>}
          </Section>
          <Section title="Data & privacy" desc="Your designs belong to your organization.">
            <p className="text-sm text-muted">Project files are isolated per workspace. Deleting a project permanently removes its files and revisions. Workspace export and deletion requests: <a className="link" href="mailto:privacy@formwright.dev">privacy@formwright.dev</a>.</p>
          </Section>
        </TabPanel>}
        <TabPanel value="api" className="space-y-6">
          <Section title="API keys" desc="Automate designs from your own tools and scripts.">
            <div className="flex items-start gap-3 rounded-lg border border-dashed border-border p-4 text-sm"><Lock className="mt-0.5 h-4 w-4 text-muted" /><div><Badge tone="preview">Preview</Badge><p className="mt-2 text-muted">A REST API is planned. Join early access from the Help page.</p></div></div>
          </Section>
          <Section title="CAD plugins" desc="Open and update Formwright parts from the CAD program on your computer.">
            <DesktopOnly what="CAD plugins">
              <div className="flex items-start gap-3 rounded-lg border border-dashed border-border p-4 text-sm"><Lock className="mt-0.5 h-4 w-4 text-muted" /><div><Badge tone="preview">Preview</Badge><p className="mt-2 text-muted">Plugins for SOLIDWORKS and Creo are planned. Join early access from the Help page.</p></div></div>
            </DesktopOnly>
          </Section>
        </TabPanel>
      </Tabs>
    </div>
  );
}
