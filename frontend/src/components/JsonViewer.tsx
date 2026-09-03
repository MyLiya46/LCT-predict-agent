export function JsonViewer({ value, label = "查看详情" }: { value: unknown; label?: string }) {
  const safe = value === undefined ? null : value;
  return <details className="max-w-md"><summary className="cursor-pointer text-xs text-primary">{label}</summary><pre className="mt-2 max-h-52 overflow-auto rounded-lg bg-slate-950 p-3 text-[11px] text-slate-100">{JSON.stringify(safe, null, 2)}</pre></details>;
}
