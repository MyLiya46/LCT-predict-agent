import { DataBrowser } from "../components/DataBrowser";

const INPUT_DATASETS = [
  { key: "raw_data", title: "零售统计" },
  { key: "master_data", title: "产品主数据" },
  { key: "price_data", title: "计划价格" },
  { key: "rebate_data", title: "渠道返利" },
  { key: "dsi_data", title: "DSI 价格" },
  { key: "cost_data", title: "商品成本" },
];

export default function InputDataPage() {
  return (
    <DataBrowser
      title="输入数据"
      subtitle="按源表浏览与筛选 · 本地演示库"
      datasets={INPUT_DATASETS}
      initialDataset="raw_data"
      showSubTabs
    />
  );
}
