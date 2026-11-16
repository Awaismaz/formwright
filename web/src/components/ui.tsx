import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import * as Tooltip from "@radix-ui/react-tooltip";
import * as SwitchP from "@radix-ui/react-switch";
import * as TabsP from "@radix-ui/react-tabs";
import { Loader2, X } from "lucide-react";
import { cx, initials } from "@/lib/format";

/* ---------------------------------------------------------------- brand */
export function LogoMark({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={className} aria-hidden="true">
      <path d="M16 2.5 27.7 9.25v13.5L16 29.5 4.3 22.75V9.25z" fill="#1F5FBF" />
      <path d="M16 2.5 27.7 9.25 16 16 4.3 9.25z" fill="#5C93E6" />
      <path d="M16 16 27.7 9.25v13.5L16 29.5z" fill="#174A96" />
      <path d="M8.2 11.1 16 6.6l3.2 1.85-7.8 4.5v3.4l5.6-3.2 3.2 1.85-8.8 5.05v4.6L8.2 21.8z" fill="#fff" />
      <path d="m22.6 15.3 5.1-2.95v4.6l-5.1 2.95z" fill="#C8742E" />
    </svg>
  );
}

export function Logo({ size = 28, dark = false, className }: { size?: number; dark?: boolean; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-2 select-none", className)}>
      <LogoMark size={size} />
      <span className={cx("font-semibold tracking-tight", dark ? "text-white" : "text-text")}
            style={{ fontSize: size * 0.68 }}>
        Form<span className="text-accent">wright</span>
      </span>
    </span>
  );
}

/* ---------------------------------------------------------------- button */
type Variant = "primary" | "secondary" | "ghost" | "danger" | "accent" | "chrome";
type Size = "sm" | "md" | "lg";
interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant; size?: Size; loading?: boolean; icon?: ReactNode;
}
const V: Record<Variant, string> = {
  primary: "bg-primary text-primary-fg hover:brightness-110 border-transparent shadow-sm",
  secondary: "bg-panel text-text border-border hover:bg-panel2",
  ghost: "bg-transparent text-text border-transparent hover:bg-text/5",
  danger: "bg-danger text-white border-transparent hover:brightness-110",
  accent: "bg-accent text-white border-transparent hover:brightness-110 shadow-sm",
  chrome: "bg-white/10 text-chrome-fg border-white/10 hover:bg-white/15",
};
const S: Record<Size, string> = { sm: "h-8 px-3 text-[13px] gap-1.5", md: "h-9 px-4 text-sm gap-2", lg: "h-11 px-6 text-[15px] gap-2" };

export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button(
  { variant = "primary", size = "md", loading, icon, className, children, disabled, ...rest }, ref) {
  return (
    <button ref={ref} disabled={disabled || loading}
      className={cx("inline-flex items-center justify-center rounded border font-medium transition",
        "disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2",
        "focus-visible:ring-primary/50 whitespace-nowrap", V[variant], S[size], className)} {...rest}>
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
});

/* ---------------------------------------------------------------- inputs */
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...rest }, ref) {
  return <input ref={ref} className={cx("input", className)} {...rest} />;
});

export function Field({ label, hint, error, children }: { label: string; hint?: ReactNode; error?: string | null; children: ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-[13px] font-medium text-text">{label}</span>
      {children}
      {error ? <span className="block text-xs text-danger">{error}</span>
        : hint ? <span className="block text-xs text-muted">{hint}</span> : null}
    </label>
  );
}

export function Toggle({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label?: string; disabled?: boolean }) {
  return (
    <SwitchP.Root checked={checked} onCheckedChange={onChange} disabled={disabled} aria-label={label}
      className="relative h-5 w-9 shrink-0 rounded-full bg-border data-[state=checked]:bg-primary transition disabled:opacity-50">
      <SwitchP.Thumb className="block h-4 w-4 translate-x-0.5 rounded-full bg-white shadow transition data-[state=checked]:translate-x-[18px]" />
    </SwitchP.Root>
  );
}

/* ---------------------------------------------------------------- display */
export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("card", className)} {...rest}>{children}</div>;
}

type Tone = "neutral" | "primary" | "success" | "warning" | "danger" | "accent" | "live" | "preview";
const T: Record<Tone, string> = {
  neutral: "bg-text/[.06] text-muted border-border",
  primary: "bg-primary-soft text-primary border-primary/20",
  success: "bg-success/10 text-success border-success/25",
  warning: "bg-warning/10 text-warning border-warning/25",
  danger: "bg-danger/10 text-danger border-danger/25",
  accent: "bg-accent/10 text-accent border-accent/25",
  live: "bg-success/10 text-success border-success/25",
  preview: "bg-accent/10 text-accent border-accent/25",
};
export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cx("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-semibold leading-4", T[tone], className)}>{children}</span>;
}

export function StatusBadge({ status }: { status: "live" | "preview" }) {
  return status === "live"
    ? <Badge tone="live"><span className="h-1.5 w-1.5 rounded-full bg-success" />Live</Badge>
    : <Badge tone="preview">Preview</Badge>;
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("h-5 w-5 animate-spin text-muted", className)} />;
}

export function PageLoader() {
  return <div className="flex h-full min-h-[40vh] items-center justify-center"><Spinner className="h-6 w-6" /></div>;
}

export function Progress({ value, max = 100, tone = "primary", className }: { value: number; max?: number; tone?: "primary" | "success" | "warning" | "danger"; className?: string }) {
  const pct = Math.max(0, Math.min(100, (value / Math.max(max, 1)) * 100));
  const bg = { primary: "bg-primary", success: "bg-success", warning: "bg-warning", danger: "bg-danger" }[tone];
  return <div className={cx("h-1.5 w-full overflow-hidden rounded-full bg-text/10", className)}><div className={cx("h-full rounded-full transition-all", bg)} style={{ width: `${pct}%` }} /></div>;
}

export function Avatar({ name, size = 28, className }: { name: string; size?: number; className?: string }) {
  const hue = [...name].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  return (
    <span className={cx("inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white", className)}
      style={{ width: size, height: size, fontSize: size * 0.38, background: `hsl(${hue} 45% 45%)` }}>
      {initials(name)}
    </span>
  );
}

export function EmptyState({ icon, title, body, action }: { icon: ReactNode; title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border bg-panel/60 px-6 py-14 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-primary-soft text-primary">{icon}</div>
      <h3 className="text-[15px] font-semibold">{title}</h3>
      {body && <p className="mt-1 max-w-md text-sm text-muted">{body}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="mb-1">{eyebrow}</div>}
        <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, icon }: { label: string; value: ReactNode; sub?: ReactNode; icon?: ReactNode }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between"><span className="label">{label}</span>{icon && <span className="text-muted">{icon}</span>}</div>
      <div className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </Card>
  );
}

/* ---------------------------------------------------------------- overlays */
export function Modal({ open, onOpenChange, title, description, children, footer, wide }: {
  open: boolean; onOpenChange: (v: boolean) => void; title: ReactNode; description?: ReactNode;
  children?: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px] animate-fade-in" />
        <Dialog.Content className={cx("fixed left-1/2 top-1/2 z-50 w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2",
          "max-h-[calc(100vh-48px)] overflow-y-auto rounded-xl border border-border bg-panel shadow-pop animate-fade-in",
          wide ? "max-w-3xl" : "max-w-lg")}>
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div>
              <Dialog.Title className="text-[16px] font-semibold">{title}</Dialog.Title>
              {description && <Dialog.Description className="mt-1 text-sm text-muted">{description}</Dialog.Description>}
            </div>
            <Dialog.Close className="rounded p-1 text-muted hover:bg-text/5" aria-label="Close"><X className="h-4 w-4" /></Dialog.Close>
          </div>
          {children && <div className="px-5 py-4">{children}</div>}
          {footer && <div className="flex justify-end gap-2 border-t border-border bg-panel2/60 px-5 py-3">{footer}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export const Menu = Dropdown.Root;
export const MenuTrigger = Dropdown.Trigger;
export function MenuContent({ children, align = "end", className }: { children: ReactNode; align?: "start" | "end" | "center"; className?: string }) {
  return (
    <Dropdown.Portal>
      <Dropdown.Content align={align} sideOffset={6}
        className={cx("z-50 min-w-[200px] rounded-lg border border-border bg-panel p-1 shadow-pop animate-fade-in", className)}>
        {children}
      </Dropdown.Content>
    </Dropdown.Portal>
  );
}
export function MenuItem({ children, onSelect, danger, icon }: { children: ReactNode; onSelect?: () => void; danger?: boolean; icon?: ReactNode }) {
  return (
    <Dropdown.Item onSelect={onSelect}
      className={cx("flex cursor-pointer select-none items-center gap-2 rounded px-2.5 py-1.5 text-sm outline-none",
        "data-[highlighted]:bg-primary-soft data-[highlighted]:text-primary", danger && "text-danger")}>
      {icon && <span className="h-4 w-4 text-muted [&>svg]:h-4 [&>svg]:w-4">{icon}</span>}{children}
    </Dropdown.Item>
  );
}
export const MenuSeparator = () => <Dropdown.Separator className="my-1 h-px bg-border" />;
export function MenuLabel({ children }: { children: ReactNode }) {
  return <Dropdown.Label className="px-2.5 py-1.5 text-xs text-muted">{children}</Dropdown.Label>;
}

export function Tip({ content, children, side = "right" }: { content: ReactNode; children: ReactNode; side?: "top" | "right" | "bottom" | "left" }) {
  return (
    <Tooltip.Root delayDuration={250}>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content side={side} sideOffset={8} className="z-50 rounded bg-chrome px-2 py-1 text-xs text-chrome-fg shadow-pop">
          {content}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
export const TipProvider = Tooltip.Provider;

export const Tabs = TabsP.Root;
export function TabList({ children, className }: { children: ReactNode; className?: string }) {
  return <TabsP.List className={cx("flex gap-1 border-b border-border", className)}>{children}</TabsP.List>;
}
export function Tab({ value, children, compact, title }: { value: string; children: ReactNode; compact?: boolean; title?: string }) {
  return (
    <TabsP.Trigger value={value} title={title}
      className={cx("-mb-px inline-flex items-center gap-1.5 border-b-2 border-transparent py-2 text-sm text-muted transition hover:text-text data-[state=active]:border-primary data-[state=active]:font-medium data-[state=active]:text-text",
        compact ? "px-2 text-[12.5px]" : "px-3")}>
      {children}
    </TabsP.Trigger>
  );
}
export const TabPanel = TabsP.Content;
