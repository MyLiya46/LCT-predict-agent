/**
 * 快捷意图 Query（仅按钮点击时使用）。
 * 不再拼接品类/SKU/渠道/时间窗口；槽位由对话文本与后端解析补全。
 * 用户手动输入不经过本模块，原样发给 Agent。
 */
import type { Intent } from "./types";

/** 按意图生成固定引导话术（不含筛选条件拼接） */
export function composeIntentQuery(intent: Intent): string {
  switch (intent) {
    case "history":
      return "查询历史销量";
    case "forecast":
      return "做销量预测";
    case "attribution":
      return "做销量归因分析";
    case "whatif":
      return "做 What-if 沙盘推演";
    default:
      return "开始分析";
  }
}
