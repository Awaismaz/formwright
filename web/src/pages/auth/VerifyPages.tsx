import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Inbox, MailCheck, Users } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Button, Spinner } from "@/components/ui";
import AuthLayout from "@/layouts/AuthLayout";

function DevMailbox() {
  const { me } = useSession();
  const q = useQuery({ queryKey: ["dev-mailbox"], queryFn: () => api.get<{ items: { subject: string; link: string | null; created_at: string }[] }>("/api/auth/dev-mailbox"),
    enabled: me?.system.env !== "production" && !!me?.user, retry: false, refetchInterval: 4000 });
  const latest = q.data?.items.find(i => i.subject.toLowerCase().includes("verify"));
  if (!latest?.link) return null;
  const path = new URL(latest.link).pathname + new URL(latest.link).search;
  return (
    <div className="mt-6 rounded-lg border border-dashed border-accent/50 bg-accent/5 p-4 text-sm">
      <div className="flex items-center gap-2 font-medium text-accent"><Inbox className="h-4 w-4" /> Development mailbox</div>
      <p className="mt-1 text-muted">No email server is configured, so emails are kept in the local outbox.</p>
      <Link to={path} className="link mt-2 inline-block font-medium">Open: {latest.subject} →</Link>
    </div>
  );
}

export function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const { me, refresh } = useSession();
  const nav = useNavigate();
  const [state, setState] = useState<"idle" | "verifying" | "done" | "error">(token ? "verifying" : "idle");
  const [error, setError] = useState("");
  const ran = useRef(false);

  useEffect(() => {
    if (!token || ran.current) return;
    ran.current = true;
    api.post("/api/auth/verify-email", { token })
      .then(async () => { setState("done"); await refresh(); })
      .catch(e => { setState("error"); setError(e instanceof ApiError ? e.message : "Verification failed."); });
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  if (state === "verifying") return <AuthLayout title="Verifying your email…"><Spinner /></AuthLayout>;
  if (state === "done") return (
    <AuthLayout title="Email verified" subtitle="Your account is active.">
      <div className="flex items-center gap-3 rounded-lg border border-success/30 bg-success/5 p-4 text-sm"><CheckCircle2 className="h-5 w-5 text-success" /> You're all set.</div>
      <Button className="mt-6 w-full" size="lg" onClick={() => nav(me?.user ? "/onboarding" : "/login")}>{me?.user ? "Set up your workspace" : "Sign in"}</Button>
    </AuthLayout>
  );
  if (me?.user?.email_verified && !token) return (
    <AuthLayout title="Your email is verified">
      <Button className="w-full" size="lg" onClick={() => nav("/app")}>Continue</Button>
    </AuthLayout>
  );
  return (
    <AuthLayout title="Check your inbox" subtitle={me?.user ? <>We sent a verification link to <b className="text-text">{me.user.email}</b>.</> : "Open the verification link we emailed you."}
      footer={me?.user ? <button className="link" onClick={async () => { await api.post("/api/auth/logout"); location.href = "/login"; }}>Use a different account</button> : <Link to="/login" className="link">Sign in</Link>}>
      {state === "error" && <div className="mb-4 rounded border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">{error}</div>}
      <div className="flex flex-col items-center rounded-xl border border-border bg-panel2 px-6 py-8 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary-soft text-primary"><MailCheck className="h-7 w-7" /></div>
        <p className="mt-4 text-sm text-muted">Click the link in the email to activate your account. It's valid for 48 hours.</p>
        {me?.user && <Button variant="secondary" className="mt-5" onClick={async () => {
          try { await api.post("/api/auth/resend-verification"); toast.success("Verification email sent again."); }
          catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not resend"); }
        }}>Resend email</Button>}
      </div>
      <DevMailbox />
    </AuthLayout>
  );
}

export function AcceptInvite() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const { me, refresh, loading } = useSession();
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const here = `/invite?token=${encodeURIComponent(token)}`;
  if (loading) return <AuthLayout title="Loading…"><Spinner /></AuthLayout>;
  if (!me?.user) return (
    <AuthLayout title="You've been invited" subtitle="Join your team's Formwright workspace.">
      <div className="flex items-center gap-3 rounded-lg border border-border bg-panel2 p-4 text-sm"><Users className="h-5 w-5 text-primary" /> Create an account with the invited email, or sign in if you already have one.</div>
      <div className="mt-6 grid gap-2">
        <Link to={`/signup?next=${encodeURIComponent(here)}`}><Button className="w-full" size="lg">Create account</Button></Link>
        <Link to={`/login?next=${encodeURIComponent(here)}`}><Button className="w-full" size="lg" variant="secondary">Sign in</Button></Link>
      </div>
    </AuthLayout>
  );
  return (
    <AuthLayout title="Join the workspace" subtitle={<>Signed in as <b className="text-text">{me.user.email}</b>.</>}>
      {error && <div className="mb-4 rounded border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">{error}</div>}
      <Button className="w-full" size="lg" loading={busy} onClick={async () => {
        setBusy(true); setError(null);
        try { await api.post("/api/team/invites/accept", { token }); await refresh(); toast.success("Welcome to the team!"); nav("/app"); }
        catch (e) { setError(e instanceof ApiError ? e.message : "Could not accept the invitation."); }
        finally { setBusy(false); }
      }}>Accept invitation</Button>
    </AuthLayout>
  );
}
