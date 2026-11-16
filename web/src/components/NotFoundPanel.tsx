import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { SearchX } from "lucide-react";
import { Button } from "./ui";

/** One "not found" language inside the app: unknown pages, modules and projects (deleted or not yours). */
export default function NotFoundPanel({ title = "This page doesn't exist", body, action }: { title?: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-16">
      <div className="max-w-md text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary-soft text-primary"><SearchX className="h-6 w-6" /></div>
        <h1 className="text-lg font-semibold">{title}</h1>
        <p className="mt-1.5 text-sm text-muted">{body ?? "The link may be broken, or the page may have moved."}</p>
        <div className="mt-6 flex justify-center gap-2">{action ?? <Link to="/app"><Button>Go to Home</Button></Link>}</div>
      </div>
    </div>
  );
}
