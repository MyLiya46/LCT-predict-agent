import { GearSix } from "@phosphor-icons/react";

export default function ParamsPage() {
  return (
    <div className="flex h-full min-h-0 flex-col p-4">
      <div className="mb-3">
        <h2 className="text-lg font-semibold tracking-tight text-foreground">参数设置</h2>
        <p className="mt-0.5 text-xs text-muted-fg">预测任务参数配置</p>
      </div>
      <section className="flex flex-1 flex-col items-center justify-center rounded-xl border border-border bg-card px-6 py-16 text-center shadow-panel">
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-muted text-primary">
          <GearSix size={26} aria-hidden />
        </div>
        <h3 className="mb-2 text-base font-semibold text-foreground">参数设置即将开放</h3>
        <p className="max-w-md text-sm leading-relaxed text-muted-fg">
          后续可在此配置品类、预测基准月、产线、渠道范围等，并作为预测任务输入。本次迭代仅提供占位页。
        </p>
      </section>
    </div>
  );
}
