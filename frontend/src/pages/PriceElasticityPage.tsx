import { DataBrowser } from "../components/DataBrowser";

const DATASETS = [{ key: "price_elasticity", title: "价格弹性" }];
const FILTER_CONFIG = {
  category: { hideAll: true },
};
const FILTER_ROWS = [["category", "series", "sku"]];

export default function PriceElasticityPage() {
  return (
    <DataBrowser
      title="价格弹性表"
      subtitle="型号级价格弹性系数 · 支撑 What-if 调价模拟"
      datasets={DATASETS}
      initialDataset="price_elasticity"
      showSubTabs={false}
      filterConfig={FILTER_CONFIG}
      filterRows={FILTER_ROWS}
    />
  );
}
