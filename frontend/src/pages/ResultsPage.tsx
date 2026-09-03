import { DataBrowser } from "../components/DataBrowser";

const DATASETS = [{ key: "fcst_detail", title: "预测明细" }];
const FILTER_CONFIG = {
  category: { hideAll: true },
  version: { linkLatestVersionToCategory: true },
};
const FILTER_ROWS = [
  ["category", "version"],
  ["channel_l1", "channel", "sku", "period", "series", "status"],
];

export default function ResultsPage() {
  return (
    <DataBrowser
      title="预测结果"
      subtitle="模板：Excel「预测详情」· 前端展示为预测明细"
      datasets={DATASETS}
      initialDataset="fcst_detail"
      showSubTabs={false}
      filterConfig={FILTER_CONFIG}
      filterRows={FILTER_ROWS}
      showTrendChart
    />
  );
}
