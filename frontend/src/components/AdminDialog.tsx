import type { FormEvent, ReactNode } from "react";
import { X } from "@phosphor-icons/react";

export function AdminDialog({ title, onClose, onSubmit, children, submitLabel = "保存", busy = false }: { title: string; onClose: () => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void; children: ReactNode; submitLabel?: string; busy?: boolean }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" role="dialog" aria-modal="true">
      <form onSubmit={onSubmit} className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-2xl border border-border bg-card p-5 shadow-2xl">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button type="button" onClick={onClose} className="rounded-lg p-1 text-muted-fg hover:bg-muted" aria-label="关闭"><X size={20} /></button>
        </div>
        <div className="space-y-4">{children}</div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded-lg border border-border bg-white px-3 py-2 text-sm hover:bg-muted">取消</button>
          <button type="submit" disabled={busy} className="rounded-lg border border-primary bg-primary px-3 py-2 text-sm text-white hover:bg-blue-800 disabled:opacity-50">{busy ? "保存中…" : submitLabel}</button>
        </div>
      </form>
    </div>
  );
}
