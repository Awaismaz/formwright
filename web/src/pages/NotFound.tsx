import { Link } from "react-router-dom";
import { Button, Logo } from "@/components/ui";

export default function NotFound() {
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-6 bg-bg px-6 text-center">
      <Logo size={28} />
      <div><div className="text-6xl font-semibold tracking-tight text-text/20">404</div><h1 className="mt-2 text-xl font-semibold">This page doesn't exist</h1>
        <p className="mt-1 text-sm text-muted">The link may be broken or the page may have moved.</p></div>
      <Link to="/"><Button>Back to Formwright</Button></Link>
    </div>
  );
}
