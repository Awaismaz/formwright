import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Eye, EyeOff, LinkIcon } from "lucide-react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { useSession } from "@/lib/session";
import { Button, Field, Input } from "@/components/ui";
import AuthLayout from "@/layouts/AuthLayout";
import { cx } from "@/lib/format";

function useSubmit() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<void>) => {
    setBusy(true); setError(null);
    try { await fn(); } catch (e) { setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again."); }
    finally { setBusy(false); }
  };
  return { busy, error, run };
}

function PasswordInput({ value, onChange, autoComplete }: { value: string; onChange: (v: string) => void; autoComplete: string }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input type={show ? "text" : "password"} value={value} onChange={e => onChange(e.target.value)} autoComplete={autoComplete} required className="pr-10" />
      <button type="button" onClick={() => setShow(!show)} className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-muted" aria-label={show ? "Hide password" : "Show password"}>
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  );
}

function strength(pw: string) {
  let s = 0;
  if (pw.length >= 10) s++;
  if (pw.length >= 14) s++;
  if (/[A-Za-z]/.test(pw) && /\d/.test(pw)) s++;
  if (/[^A-Za-z0-9]/.test(pw)) s++;
  return s;
}

const ErrorBox = ({ error }: { error: string | null }) =>
  error ? <div className="rounded border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">{error}</div> : null;

export function Login() {
  const { refresh } = useSession();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useSubmit();
  const next = params.get("next");
  const submit = (e: FormEvent) => { e.preventDefault(); run(async () => {
    await api.post("/api/auth/login", { email, password });
    await refresh();
    nav(next && next.startsWith("/") && !next.startsWith("//") ? next : "/app", { replace: true });
  }); };
  return (
    <AuthLayout title="Welcome back" subtitle="Sign in to your Formwright workspace."
      footer={<>New to Formwright? <Link to="/signup" className="link font-medium">Start a free trial</Link></>}>
      <form onSubmit={submit} className="space-y-4">
        <ErrorBox error={error} />
        <Field label="Work email"><Input type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" required autoFocus /></Field>
        <Field label="Password"><PasswordInput value={password} onChange={setPassword} autoComplete="current-password" /></Field>
        <div className="flex justify-end"><Link to="/forgot-password" className="link text-[13px]">Forgot password?</Link></div>
        <Button type="submit" className="w-full" size="lg" loading={busy}>Sign in</Button>
      </form>
    </AuthLayout>
  );
}

export function Signup() {
  const { refresh } = useSession();
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [password, setPassword] = useState("");
  const [agree, setAgree] = useState(false);
  const { busy, error, run } = useSubmit();
  const s = strength(password);
  const plan = params.get("plan");
  const next = params.get("next");
  const submit = (e: FormEvent) => { e.preventDefault(); run(async () => {
    if (!agree) throw new ApiError(422, "Please accept the terms to continue.");
    await api.post("/api/auth/signup", { name, email, password });
    try { if (plan) sessionStorage.setItem("fw_intended_plan", plan); } catch { /* ignore */ }
    await refresh();
    toast.success("Account created. We sent a confirmation link to your email; you can start right away.");
    nav(next && next.startsWith("/invite") ? next : "/onboarding", { replace: true });
  }); };
  return (
    <AuthLayout title="Start your free trial" subtitle="1,000 tokens and every module for 14 days. No credit card."
      footer={<>Already have an account? <Link to={`/login${next ? `?next=${encodeURIComponent(next)}` : ""}`} className="link font-medium">Sign in</Link></>}>
      <form onSubmit={submit} className="space-y-4">
        <ErrorBox error={error} />
        <Field label="Full name"><Input value={name} onChange={e => setName(e.target.value)} autoComplete="name" required autoFocus /></Field>
        <Field label="Work email"><Input type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" required /></Field>
        <Field label="Password" hint="At least 10 characters, with letters and numbers.">
          <PasswordInput value={password} onChange={setPassword} autoComplete="new-password" />
        </Field>
        {password && <div className="-mt-2 flex gap-1">{[0, 1, 2, 3].map(i => <span key={i} className={cx("h-1 flex-1 rounded-full", i < s ? (s >= 3 ? "bg-success" : "bg-warning") : "bg-border")} />)}</div>}
        <label className="flex items-start gap-2.5 text-[13px] text-muted">
          <input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[rgb(var(--primary))]" />
          <span>I agree to the <Link to="/legal/terms" className="link" target="_blank">Terms</Link> and <Link to="/legal/privacy" className="link" target="_blank">Privacy Policy</Link>.</span>
        </label>
        <Button type="submit" className="w-full" size="lg" loading={busy}>Create account</Button>
      </form>
    </AuthLayout>
  );
}

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const { busy, error, run } = useSubmit();
  return (
    <AuthLayout title="Reset your password" subtitle="We'll email you a secure link."
      footer={<Link to="/login" className="link">Back to sign in</Link>}>
      {sent ? <div className="rounded-lg border border-success/30 bg-success/5 p-4 text-sm">If an account exists for <b>{email}</b>, a reset link is on its way. It expires in 2 hours.</div> :
        <form onSubmit={e => { e.preventDefault(); run(async () => { await api.post("/api/auth/forgot-password", { email }); setSent(true); }); }} className="space-y-4">
          <ErrorBox error={error} />
          <Field label="Work email"><Input type="email" value={email} onChange={e => setEmail(e.target.value)} required autoFocus /></Field>
          <Button type="submit" className="w-full" size="lg" loading={busy}>Send reset link</Button>
        </form>}
    </AuthLayout>
  );
}

/** A dead link (missing, expired or used) gets a way forward, not a disabled form. */
export function LinkProblem({ title, body, action }: { title: string; body: string; action: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-border bg-panel2 px-6 py-8 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-warning/10 text-warning"><LinkIcon className="h-6 w-6" /></div>
      <div className="mt-4 font-medium">{title}</div>
      <p className="mt-1 text-sm text-muted">{body}</p>
      <div className="mt-5">{action}</div>
    </div>
  );
}

export function ResetPassword() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [password, setPassword] = useState("");
  const { busy, error, run } = useSubmit();
  const token = params.get("token") ?? "";
  const dead = !token || /invalid or has expired/i.test(error ?? "");
  if (dead) return (
    <AuthLayout title="Reset your password" footer={<Link to="/login" className="link">Back to sign in</Link>}>
      <LinkProblem title={token ? "This reset link has expired or was already used" : "This page needs the link from your reset email"}
        body="Reset links work once and expire after 2 hours. Ask for a new one; it arrives in a minute."
        action={<Link to="/forgot-password"><Button>Send a new link</Button></Link>} />
    </AuthLayout>
  );
  return (
    <AuthLayout title="Choose a new password" footer={<Link to="/login" className="link">Back to sign in</Link>}>
      <form onSubmit={e => { e.preventDefault(); run(async () => {
        await api.post("/api/auth/reset-password", { token, password });
        toast.success("Password updated. Please sign in."); nav("/login");
      }); }} className="space-y-4">
        <ErrorBox error={error} />
        <Field label="New password" hint="At least 10 characters, with letters and numbers."><PasswordInput value={password} onChange={setPassword} autoComplete="new-password" /></Field>
        <Button type="submit" className="w-full" size="lg" loading={busy}>Update password</Button>
      </form>
    </AuthLayout>
  );
}
