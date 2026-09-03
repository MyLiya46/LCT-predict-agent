import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useMemo } from "react";
import { DownloadSimple } from "@phosphor-icons/react";
import { useAppStore } from "../store";
import { Skeleton } from "./InsightPanel";
import type { AgentResultEnvelope } from "../types";

function formatCell(value: unknown): string | number {
  if (typeof value === "number") return value.toLocaleString();
  if (value == null) return "";
  return String(value);
}

function exportCsv(envelope: AgentResultEnvelope) {
  if (!envelope.table) return;
  const headers = envelope.table.columns.map((c) => c.title).join(",");
  const lines = envelope.table.rows.map((row) =>
    envelope.table!.columns.map((c) => JSON.stringify(row[c.key] ?? "")).join(","),
  );
  const blob = new Blob([[headers, ...lines].join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `forecast-${envelope.intent}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function TableBody({ envelope }: { envelope: AgentResultEnvelope }) {
  const columns = useMemo(() => {
    const cols = envelope.table?.columns || [];
    return cols.map((c) => ({
      accessorKey: c.key,
      header: c.title,
      meta: { align: c.align || "left" },
    }));
  }, [envelope]);

  const data = envelope.table?.rows || [];

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 8 } },
  });

  if (!envelope.table || data.length === 0) return null;

  return (
    <div>
      <div className="mb-2 flex items-center justify-between text-sm font-semibold">
        <span>数据表</span>
        <button
          type="button"
          onClick={() => exportCsv(envelope)}
          className="inline-flex cursor-pointer items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-primary transition hover:bg-muted"
          aria-label="导出 CSV"
        >
          <DownloadSimple size={14} /> 导出 CSV
        </button>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-muted text-xs uppercase tracking-wide text-muted-fg">
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => (
                  <th key={h.id} className="px-3 py-2 font-medium">
                    {flexRender(h.column.columnDef.header, h.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-t border-border hover:bg-muted/50">
                {row.getVisibleCells().map((cell) => {
                  const align =
                    (cell.column.columnDef.meta as { align?: string } | undefined)?.align ||
                    "left";
                  return (
                    <td
                      key={cell.id}
                      className={`px-3 py-2 ${align === "right" ? "text-right font-mono text-[13px]" : ""}`}
                    >
                      {formatCell(cell.getValue())}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center justify-between text-xs text-muted-fg">
        <span>
          第 {table.getState().pagination.pageIndex + 1} / {table.getPageCount() || 1} 页 · 共{" "}
          {data.length} 行
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            className="cursor-pointer rounded border border-border px-2 py-1 hover:bg-muted disabled:opacity-40"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            上一页
          </button>
          <button
            type="button"
            className="cursor-pointer rounded border border-border px-2 py-1 hover:bg-muted disabled:opacity-40"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            下一页
          </button>
        </div>
      </div>
    </div>
  );
}

export function TablePanel() {
  const envelope = useAppStore((s) => s.envelope);
  const loading = useAppStore((s) => s.loading);

  if (loading && !envelope) {
    return <Skeleton title="数据表" height="h-56" />;
  }
  if (!envelope?.table || !envelope.table.rows.length) {
    return (
      <section className="rounded-xl border border-dashed border-border bg-card p-4 text-sm text-muted-fg shadow-panel">
        暂无表格数据
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-panel">
      <TableBody envelope={envelope} />
    </section>
  );
}
