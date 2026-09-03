import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

export function AdminTable({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-panel">
      <table className="min-w-full divide-y divide-border text-left text-sm">{children}</table>
    </div>
  );
}

export function AdminTh({ children }: { children: ReactNode }) {
  return <th className="whitespace-nowrap bg-muted px-4 py-3 text-xs font-semibold text-muted-fg">{children}</th>;
}

export function AdminTd({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <td className={`border-t border-border px-4 py-3 align-top ${className}`}>{children}</td>;
}

export function AdminPage({ title, description, actions, children }: { title: string; description?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="h-full overflow-y-auto bg-background p-5 md:p-8">
      <div className="mx-auto max-w-7xl space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-foreground">{title}</h1>
            {description ? <p className="mt-1 text-sm text-muted-fg">{description}</p> : null}
          </div>
          {actions}
        </div>
        {children}
      </div>
    </section>
  );
}

export function AdminNotice({ children, kind = "error" }: { children: ReactNode; kind?: "error" | "success" }) {
  return <div className={`rounded-lg border px-3 py-2 text-sm ${kind === "success" ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "border-rose-200 bg-rose-50 text-rose-700"}`}>{children}</div>;
}

export function AdminButton({ children, busy, variant = "primary", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; variant?: "primary" | "secondary" | "danger" }) {
  const colors = variant === "danger" ? "border-rose-200 text-destructive hover:bg-rose-50" : variant === "secondary" ? "border-border bg-white text-foreground hover:bg-muted" : "border-primary bg-primary text-white hover:bg-blue-800";
  return <button {...props} disabled={busy || props.disabled} className={`inline-flex items-center justify-center rounded-lg border px-3 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-50 ${colors} ${props.className || ""}`}>{busy ? "处理中…" : children}</button>;
}

export function AdminInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`w-full rounded-lg border border-border bg-white px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/10 ${props.className || ""}`} />;
}

export function AdminSelect(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`rounded-lg border border-border bg-white px-3 py-2 text-sm outline-none focus:border-primary ${props.className || ""}`} />;
}

export function AdminTextarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`w-full rounded-lg border border-border bg-white px-3 py-2 font-mono text-xs outline-none focus:border-primary focus:ring-2 focus:ring-primary/10 ${props.className || ""}`} />;
}
