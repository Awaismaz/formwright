import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useSession } from "@/lib/session";
import { PageLoader } from "@/components/ui";
import MarketingLayout from "@/layouts/MarketingLayout";
import AppLayout from "@/layouts/AppLayout";
import Landing from "@/pages/marketing/Landing";
import Pricing from "@/pages/marketing/Pricing";
import Legal from "@/pages/marketing/Legal";
import { ForgotPassword, Login, ResetPassword, Signup } from "@/pages/auth/AuthPages";
import { AcceptInvite, VerifyEmail } from "@/pages/auth/VerifyPages";
import Onboarding from "@/pages/auth/Onboarding";
import Dashboard from "@/pages/app/Dashboard";
import Projects from "@/pages/app/Projects";
import Modules, { ModulePage } from "@/pages/app/Modules";
import Billing, { Checkout } from "@/pages/app/Billing";
import Team from "@/pages/app/Team";
import Settings from "@/pages/app/Settings";
import Help from "@/pages/app/Help";
import NotFound from "@/pages/NotFound";

const ProjectStudio = lazy(() => import("@/pages/app/ProjectStudio"));
const Admin = lazy(() => import("@/pages/admin/Admin"));

function RequireAuth({ children }: { children: ReactNode }) {
  const { me, loading } = useSession();
  const loc = useLocation();
  if (loading) return <PageLoader />;
  if (!me?.user) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  return <>{children}</>;
}

/** Routes the user to the next step of the customer journey before the main app. */
function JourneyGate({ children }: { children: ReactNode }) {
  const { me } = useSession();
  if (me?.next_step === "verify_email") return <Navigate to="/verify-email" replace />;
  if (me?.next_step === "onboarding") return <Navigate to="/onboarding" replace />;
  return <>{children}</>;
}

function PublicOnly({ children }: { children: ReactNode }) {
  const { me, loading } = useSession();
  const loc = useLocation();
  if (loading) return <PageLoader />;
  if (me?.user) {
    const next = new URLSearchParams(loc.search).get("next");
    return <Navigate to={next && next.startsWith("/") && !next.startsWith("//") ? next : "/app"} replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Suspense fallback={<PageLoader />}>
      <Routes>
        <Route element={<MarketingLayout />}>
          <Route path="/" element={<Landing />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/legal/:doc" element={<Legal />} />
        </Route>
        <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
        <Route path="/signup" element={<PublicOnly><Signup /></PublicOnly>} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route path="/verify-email" element={<VerifyEmail />} />
        <Route path="/invite" element={<AcceptInvite />} />
        <Route path="/onboarding" element={<RequireAuth><Onboarding /></RequireAuth>} />
        <Route path="/app" element={<RequireAuth><JourneyGate><AppLayout /></JourneyGate></RequireAuth>}>
          <Route index element={<Dashboard />} />
          <Route path="projects" element={<Projects />} />
          <Route path="projects/:id" element={<ProjectStudio />} />
          <Route path="modules" element={<Modules />} />
          <Route path="modules/:code" element={<ModulePage />} />
          <Route path="billing" element={<Billing />} />
          <Route path="checkout/:id" element={<Checkout />} />
          <Route path="team" element={<Team />} />
          <Route path="settings" element={<Settings />} />
          <Route path="help" element={<Help />} />
          <Route path="admin/*" element={<Admin />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  );
}
