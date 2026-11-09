// Biblioteka komponentów UI w estetyce shadcn (Zinc + indygo), motywowana tokenami z index.css.
// Jedno źródło prawdy dla wyglądu: karty, przyciski, pola, tabele, stany puste, szkielety.
import { ChevronDown, Info } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

/* ---------------------------------- Karta --------------------------------- */

export function Card({
  className,
  interactive,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      className={cn(
        "rounded-xl border border-border bg-surface shadow-card",
        interactive && "transition-all hover:-translate-y-0.5 hover:border-border-strong hover:shadow-card-hover",
        className,
      )}
      {...props}
    />
  );
}

/* --------------------------------- Przycisk -------------------------------- */

type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "icon";

export function Button({
  className,
  variant = "primary",
  size = "md",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
}) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-lg font-medium whitespace-nowrap transition-all active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none";
  const sizes: Record<ButtonSize, string> = {
    sm: "h-8 px-3 text-xs",
    md: "h-10 px-4 text-sm",
    icon: "h-10 w-10 p-0 text-sm",
  };
  const variants: Record<ButtonVariant, string> = {
    // Wypełniony indygo - stały w obu motywach (biały tekst zawsze czytelny).
    primary: "bg-[#4F46E5] text-white shadow-sm hover:bg-[#4338CA]",
    secondary: "border border-border bg-surface text-text hover:bg-surface-2 hover:border-border-strong",
    outline: "border border-border-strong bg-transparent text-text hover:bg-surface-2",
    ghost: "text-text-muted hover:bg-surface-2 hover:text-text",
    danger: "border border-danger/30 bg-danger-soft text-danger hover:bg-danger/15",
  };
  return <button className={cn(base, sizes[size], variants[variant], className)} {...props} />;
}

/* ----------------------------- Pola formularza ---------------------------- */

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm text-text",
        "placeholder:text-text-subtle transition-colors hover:border-border-strong",
        "focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/25",
        "disabled:cursor-not-allowed disabled:opacity-60",
        className,
      )}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        "min-h-[92px] w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-text",
        "placeholder:text-text-subtle transition-colors hover:border-border-strong",
        "focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/25",
        className,
      )}
      {...props}
    />
  );
}

export function Select({
  className,
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <div className="relative">
      <select
        className={cn(
          "h-10 w-full appearance-none rounded-lg border border-border bg-surface px-3 pr-9 text-sm text-text",
          "transition-colors hover:border-border-strong",
          "focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/25",
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-subtle" />
    </div>
  );
}

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label className={cn("mb-1.5 block text-xs font-medium text-text-muted", className)} {...props} />
  );
}

/* ---------------------------------- Badge --------------------------------- */

type BadgeTone = "neutral" | "success" | "warning" | "danger" | "primary";

export function Badge({
  children,
  tone = "neutral",
  dot,
  className,
}: {
  children: React.ReactNode;
  tone?: BadgeTone;
  dot?: boolean;
  className?: string;
}) {
  const tones: Record<BadgeTone, string> = {
    neutral: "bg-surface-2 text-text-muted ring-border",
    success: "bg-success-soft text-success ring-success/25",
    warning: "bg-warning-soft text-warning ring-warning/25",
    danger: "bg-danger-soft text-danger ring-danger/25",
    primary: "bg-primary-soft text-primary ring-primary/25",
  };
  const dotTone: Record<BadgeTone, string> = {
    neutral: "bg-text-subtle",
    success: "bg-success",
    warning: "bg-warning",
    danger: "bg-danger",
    primary: "bg-primary",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        tones[tone],
        className,
      )}
    >
      {dot && <span className={cn("h-1.5 w-1.5 rounded-full", dotTone[tone])} />}
      {children}
    </span>
  );
}

/* --------------------------------- Spinner -------------------------------- */

export function Spinner({ label, className }: { label?: string; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2 text-sm text-text-muted", className)}>
      <div className="h-4 w-4 animate-spin rounded-full border-2 border-border border-t-primary" />
      {label}
    </div>
  );
}

/* -------------------------------- Skeleton -------------------------------- */

export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn("relative overflow-hidden rounded-md bg-surface-2", className)}>
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-black/[0.06] to-transparent dark:via-white/[0.06]" />
    </div>
  );
}

/* ------------------------------ Podpowiedź (i) ---------------------------- */

export function InfoHint({ text }: { text: string }) {
  return (
    <span title={text} className="inline-flex cursor-help text-text-subtle transition-colors hover:text-text-muted">
      <Info className="h-3.5 w-3.5" />
    </span>
  );
}

/* ------------------------------ Nagłówek sekcji --------------------------- */

export function PageHead({
  title,
  subtitle,
  actions,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {title && <h2 className="text-base font-semibold tracking-tight text-text">{title}</h2>}
        {subtitle && <p className="mt-0.5 text-sm text-text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

/* ------------------------------- Karta KPI -------------------------------- */

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  footer,
  delta,
  deltaGoodWhenUp = true,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  icon?: React.ComponentType<{ className?: string }>;
  footer?: React.ReactNode;
  delta?: number | null; // zmiana % vs poprzedni okres
  deltaGoodWhenUp?: boolean; // dla CAC/kosztów wzrost jest „zły"
}) {
  const showDelta = delta !== undefined && delta !== null && Number.isFinite(delta);
  const up = (delta ?? 0) >= 0;
  const good = up === deltaGoodWhenUp;
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1 text-xs font-medium text-text-muted">
          {label}
          {hint && <InfoHint text={hint} />}
        </span>
        {Icon && (
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary-soft text-primary">
            <Icon className="h-4 w-4" />
          </span>
        )}
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <div className="tabnum text-2xl font-semibold tracking-tight text-text">{value}</div>
        {showDelta && (
          <span
            className={cn(
              "tabnum inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-xs font-medium",
              good ? "bg-success-soft text-success" : "bg-danger-soft text-danger",
            )}
            title="Zmiana względem poprzedniego okresu"
          >
            {up ? "▲" : "▼"} {Math.abs(delta as number).toFixed(1).replace(".", ",")}%
          </span>
        )}
      </div>
      {footer && <div className="mt-1 text-xs text-text-subtle">{footer}</div>}
    </Card>
  );
}

/* ------------------------------ Dialog potwierdzenia ---------------------- */

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Potwierdź",
  cancelLabel = "Anuluj",
  danger,
  busy,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm animate-fade-in"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onCancel}
    >
      <Card
        className="w-full max-w-sm p-5 shadow-pop animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        {message && <div className="mt-1.5 text-sm text-text-muted">{message}</div>}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </Button>
        </div>
      </Card>
    </div>
  );
}

/* -------------------------------- Stan pusty ------------------------------ */

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-3 px-6 py-14 text-center", className)}>
      {Icon && (
        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-text-subtle">
          <Icon className="h-6 w-6" />
        </div>
      )}
      <div>
        <p className="text-sm font-medium text-text">{title}</p>
        {description && <p className="mx-auto mt-1 max-w-sm text-sm text-text-muted">{description}</p>}
      </div>
      {action}
    </div>
  );
}

/* ---------------------------------- Tabela -------------------------------- */
// Spójny wygląd tabel w całej aplikacji. Table opakowuje w kontener z poziomym
// przewijaniem (responsywność), THead sam renderuje wiersz nagłówka.

export function Table({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn("w-full border-collapse text-sm", className)}>{children}</table>
    </div>
  );
}

export function THead({ children }: { children: React.ReactNode }) {
  return (
    <thead className="border-b border-border bg-surface-2 text-left text-xs uppercase tracking-wide text-text-muted">
      <tr>{children}</tr>
    </thead>
  );
}

export function Th({
  children,
  align = "left",
  className,
}: {
  children?: React.ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
}) {
  return (
    <th
      className={cn(
        "px-4 py-2.5 font-medium",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function TBody({ children }: { children: React.ReactNode }) {
  return <tbody>{children}</tbody>;
}

export function Tr({
  children,
  className,
  ...props
}: React.HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn(
        "border-b border-border/70 transition-colors last:border-0 hover:bg-surface-2/70",
        props.onClick && "cursor-pointer",
        className,
      )}
      {...props}
    >
      {children}
    </tr>
  );
}

export function Td({
  children,
  align = "left",
  className,
}: {
  children?: React.ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
}) {
  return (
    <td
      className={cn(
        "px-4 py-3 align-middle",
        align === "right" && "tabnum text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </td>
  );
}
