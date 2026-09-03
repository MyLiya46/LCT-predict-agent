/** 品类 ↔ SKU 选项（空选 = 全部） */
export const CATEGORIES = ["洗衣机", "冰箱", "空调", "TV", "显示器"] as const;

export const SKU_BY_CATEGORY: Record<string, string[]> = {
  冰箱: ["R112L5-BPD", "R116L5-B", "R650T3-S", "R645L1M-S", "R190V5M-B", "R405T3-U"],
  洗衣机: ["B80L2R", "B75L2R", "B75L2W", "B100V2R", "XQB65-D01", "G70L100", "B70L2R", "B80V2R"],
};

export const TIME_OPTIONS = [
  { label: "1个月", months: 1 },
  { label: "3个月", months: 3 },
  { label: "6个月", months: 6 },
  { label: "1年", months: 12 },
] as const;

/** 渠道多选（空选 = 全部） */
export const CHANNEL_OPTIONS = [
  "京东自营",
  "京东POP",
  "淘系",
  "拼多多",
  "快手抖音",
  "综合",
  "其他",
] as const;

export function skusForCategory(category?: string | null): string[] {
  if (!category) return [];
  return SKU_BY_CATEGORY[category] || [];
}
