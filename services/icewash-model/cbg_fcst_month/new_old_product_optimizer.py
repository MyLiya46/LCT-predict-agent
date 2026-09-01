# -*- coding: utf-8 -*-
"""
================================================================================
新老品预测优化器 (New-Old Product Transition Optimizer)
================================================================================

核心功能：
    1. 多代替换关系链解析 —— 从主数据中自动发现新品→老品的替换关系，
       并通过 BFS 广度优先搜索实现多代穿透（g1→g2→g3 的传递闭合）
    2. 过渡期检测 —— 根据上市月、退市月等时机信息，识别当前预测月份
       存在哪些新老品过渡期，区分场景A（有明确退市计划）和场景B（无退市计划）
    3. 预测份额分配 —— 对过渡期内的预测结果，将新品的预测总量按比例
       分配给老品，实现"新品逐步替代老品"的业务逻辑

使用方式：
    # 1. 初始化优化器
    optimizer = NewOldProductOptimizer(config)

    # 2. 解析替换关系（只需执行一次）
    optimizer.build_replacement_chain(master_data)

    # 3. 在每次预测后调用分配方法
    adjusted = optimizer.apply_transition_split(
        forecast_results, historical_sales, master_data, forecast_month
    )

数据依赖：
    - master_data（主数据）：
      必须包含 型号-CRM最新名称(product_mode_code)、对应老品/备注(remark)、
      预计生产时间(expected_prod_time)、预计退市时间(expected_disc_time)、
      status(product_status) 等字段
    - historical_sales（历史销量）：
      按月份×型号×渠道粒度，包含 数量、月份 等字段
    - forecast_results（预测结果）：
      pipeline 中间格式，包含 y_pred、型号-CRM最新名称、3级渠道(channel_name_l3) 等字段
================================================================================
"""
import pandas as pd
import numpy as np
import calendar
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from collections import deque


SUPPORTED_DATE_FORMATS = (
    '%Y年%m月%d日', '%Y年%m月%d', '%Y年%m月',
    '%Y-%m-%d', '%Y/%m/%d', '%y-%m-%d', '%y/%m/%d',
    '%Y-%m', '%Y/%m', '%y-%m', '%y/%m',
)


def parse_flexible_date(date_value):
    """兼容主数据常见日期格式及 Excel 日期序列值。"""
    if date_value is None or pd.isna(date_value):
        return None

    if isinstance(date_value, (datetime, pd.Timestamp, np.datetime64)):
        return pd.to_datetime(date_value, errors='coerce')

    value = str(date_value).strip()
    if not value:
        return None

    # Excel 日期序列值，例如 45822 或 45822.0。
    try:
        numeric_value = float(value)
        if numeric_value.is_integer() and 40000 < numeric_value < 60000:
            return pd.to_datetime(
                numeric_value, unit='D', origin='1899-12-30', errors='coerce'
            )
    except (TypeError, ValueError, OverflowError):
        pass

    for date_format in SUPPORTED_DATE_FORMATS:
        result = pd.to_datetime(value, format=date_format, errors='coerce')
        if not pd.isna(result):
            return result

    # 最后交给 pandas 处理带时间等非标准但可识别的日期文本。
    return pd.to_datetime(value, errors='coerce')


# ---------------------------------------------------------------------------
# 过渡期信息数据类
# ---------------------------------------------------------------------------

@dataclass
class TransitionInfo:
    """
    过渡期信息载体

    每一条 TransitionInfo 代表一个"新品 → 单老品"的过渡关系。
    如果一个新品对应多个老品，会生成多条 TransitionInfo 记录。

    属性说明：
        new_product      : str  - 新品型号名称，如 "B80L2W"
        old_products     : list - 老品型号名称列表（通常只含1个元素）
        launch_month     : datetime - 新品上市月份（来自 预计生产时间 字段）
        phase_out_month  : datetime or None - 老品计划退市月份（来自 预计退市时间 字段），
                              如果老品没有计划退市时间则为 None
        transition_start : datetime - 过渡期起始月份（= 新品上市月份）
        transition_end   : datetime or None - 过渡期结束月份（= 老品退市月份），
                              None 表示过渡期尚未结束
        has_planned_phaseout : bool - True=场景A(有明确退市计划), False=场景B(无退市计划)
        old_status       : str  - 老品状态，只有 "主销" 状态的才参与过渡期分配
        month_index      : int  - 当前预测月份在过渡期中的序号（从1开始）
                                  例如：上市月=1月，预测月=3月 → month_index=3
        total_months     : int  - 过渡期总月数（仅在场景A下有值）
                                  N = (退市月 - 上市月) + 1
    """
    new_product: str
    old_products: List[str] = field(default_factory=list)
    launch_month: Optional[datetime] = None
    phase_out_month: Optional[datetime] = None
    transition_start: Optional[datetime] = None
    transition_end: Optional[datetime] = None
    has_planned_phaseout: bool = False
    old_status: str = ""
    month_index: int = 0
    total_months: int = 0


# ===========================================================================
# 新老品预测优化器
# ===========================================================================

class NewOldProductOptimizer:
    """
    新老品预测优化器

    封装多代关系解析、过渡期检测、预测分配三大功能。

    核心数据结构：

        replacement_chain : dict[str, list[str]]
            {新品型号: [所有老品型号列表（含多代穿透）]}
            示例：{"B80L2W": ["B80L2R", "B80L2"]}
            B80L2W → B80L2R（直接替换），B80L2R → B80L2（间接替换）
            通过 BFS 穿透后，B80L2W 可以关联到 B80L2

        old_to_new_map : dict[str, str]
            {老品型号: 最新一代新品型号} 反向映射
            用于老品反向查找其对应的"最新替代者"

        chain_depth : dict[str, int]
            {新品型号: 代际深度} 该新品关联了多少代老品
            depth=2 表示该新品穿透了两代老品

    设计说明：
        - 替换关系完全从 master_data 的 对应老品/备注 字段动态解析，不硬编码
        - 老品用 、（顿号）分隔，支持一个新品同时替代多个老品
        - 只有 status="主销" 的老品才参与过渡期份额分配
        - 支持跨 series 分组的替换（如 B80V2W(V) ↔ B80V2R(L)），
          但受限于 combined DataFrame 的 groupby 结构，跨系列可能无法匹配
    """

    def __init__(self, config):
        """
        初始化优化器

        参数：
            config : 配置对象
                需要包含以下属性：
                - NEW_OLD_TRANSITION_DEFAULT_RATIO : float
                  场景B下新品首月的默认分配比例，默认 0.2（即新品占20%）
                - ENABLE_MULTI_GEN_CHAIN : bool
                  是否启用多代替换链穿透，默认 True
        """
        self.config = config
        # {新品: [老品列表]} —— 多代穿透后的完整替换关系
        self.replacement_chain: Dict[str, List[str]] = {}
        # {老品: 最新新品} —— 反向映射，用于老品查找其替代者
        self.old_to_new_map: Dict[str, str] = {}
        # {新品: 代际深度} —— 该新品的多代替换层级数
        self.chain_depth: Dict[str, int] = {}

    # =======================================================================
    # 第一步：解析多代替换关系链
    # =======================================================================

    def build_replacement_chain(self, master_data):
        """
        解析多代替换关系链

        从主数据的 "对应老品/备注" 字段中提取新老品替换关系，
        并通过 BFS（广度优先搜索）实现多代穿透闭合。

        业务背景：
            产品迭代中可能存在多代替换关系：
            g1(最新) → g2 → g3(最老)，其中 g2 既是 g1 的老品，又是 g3 的新品。
            这种链式关系在 master_data 中通过 对应老品/备注 字段表达。
            通过 BFS 可以自动发现 g1 → [g2, g3] 的完整穿透关系。

        算法步骤：
            Step 1 — 构建 direct_map（直接替换关系）：
                    遍历 master_data 中所有有 对应老品/备注 的行，
                    将 对应老品/备注 按 、（顿号）拆分，
                    建立 {新品: [直接老品列表]} 映射。
            Step 2 — 构建 reverse_map（反向映射，用于后续方向推导）：
                    将 direct_map 反转：{老品: 其直接替代者（新品）}
            Step 3 — BFS 穿透（多代闭合）：
                    对每个新品 start_new，将其直接老品加入队列，
                    对每个出队的型号，查询该型号是否同时也是其他型号的"替代品"
                    （即它作为某型号的老品出现），如果是，则将该型号的老品也加入
                    结果集。重复直到队列为空。
            Step 4 — 构建反向映射 old_to_new_map：
                    遍历所有穿透后的老品，通过 reverse_map 链式查找，
                    找到该老品对应的"最新一代新品"。

        输入：
            master_data : pd.DataFrame
                主数据表，必须包含以下字段之一：
                - 型号-CRM最新名称 / product_mode_code : 型号名称
                - 对应老品/备注 / remark : 用顿号分隔的老品型号列表
                  （例如："B80L2R、B75L2R"）

        输出：
            tuple (replacement_chain, old_to_new_map, chain_depth)
            - replacement_chain : dict — {新品: [所有穿透后的老品]}
            - old_to_new_map    : dict — {老品: 对应最新新品}
            - chain_depth       : dict — {新品: 代际层级数}

        示例：
            假设 master_data 中有：
            ┌─────────┬──────────────┐
            │ 型号    │ 对应老品/备注  │
            ├─────────┼──────────────┤
            │ B80L2W  │ B80L2R       │
            │ B80L2R  │ B80L2        │
            └─────────┴──────────────┘

            解析结果：
            - direct_map = {"B80L2W": ["B80L2R"], "B80L2R": ["B80L2"]}
            - BFS 后：replacement_chain = {"B80L2W": ["B80L2R", "B80L2"], "B80L2R": ["B80L2"]}
            - 穿透深度：chain_depth = {"B80L2W": 2, "B80L2R": 1}
        """
        # -------------------------------------------------------------------
        # Step 0: 自适应列名
        # -------------------------------------------------------------------
        col_model = '型号-CRM最新名称' if '型号-CRM最新名称' in master_data.columns else 'product_mode_code'
        col_remark = '对应老品/备注' if '对应老品/备注' in master_data.columns else 'remark'
        # col_prod_time = '预计生产时间' if '预计生产时间' in master_data.columns else 'expected_prod_time'

        # -------------------------------------------------------------------
        # Step 1: 构建直接替换关系 direct_map
        # -------------------------------------------------------------------
        # 筛选出有老品备注信息的行
        df = master_data[[col_model, col_remark]].dropna(subset=[col_remark]).copy()
        df[col_remark] = df[col_remark].astype(str)

        # direct_map: {新品: [直接老品列表]}
        direct_map: Dict[str, List[str]] = {}
        for _, row in df.iterrows():
            new_model = str(row[col_model]).strip()        # 当前行型号 = 新品
            old_models_str = str(row[col_remark]).strip()   # 备注中的老品字符串
            if not old_models_str or old_models_str == 'nan':
                continue
            # 按顿号拆分（如 "B80L2R、B75L2R" → ["B80L2R", "B75L2R"]）
            old_models = [m.strip() for m in old_models_str.split('、') if m.strip()]
            if new_model not in direct_map:
                direct_map[new_model] = []
            for om in old_models:
                if om not in direct_map[new_model]:
                    direct_map[new_model].append(om)

        # -------------------------------------------------------------------
        # Step 2: 构建反向映射 reverse_map
        # -------------------------------------------------------------------
        # reverse_map: {老品: 其直接的替代者（新品）}
        # 用于后续 BFS 和反向查找链
        reverse_map: Dict[str, str] = {}
        for new_model, old_list in direct_map.items():
            for old_model in old_list:
                # 只保留第一个映射关系（同一老品被多个新品替代时取最先出现的）
                if old_model not in reverse_map:
                    reverse_map[old_model] = new_model

        # -------------------------------------------------------------------
        # Step 3: BFS 多代穿透
        # -------------------------------------------------------------------
        self.replacement_chain = {}
        self.chain_depth = {}

        for start_new, direct_olds in direct_map.items():
            # 初始化：当前新品的所有直接老品
            all_olds = list(direct_olds)
            visited = set(direct_olds)   # 已访问集合，防止环形引用死循环
            queue = deque(direct_olds)   # BFS 队列

            # BFS 主循环：逐层展开多代替换关系
            while queue:
                current = queue.popleft()
                # 如果当前出队的型号同时也是某型号的"新品"（即它有对应的老品）
                if current in direct_map:
                    for older in direct_map[current]:
                        if older not in visited:
                            visited.add(older)
                            all_olds.append(older)
                            queue.append(older)

            # 存储穿透后的完整老品列表
            self.replacement_chain[start_new] = all_olds
            # 代际深度 = 穿透到的老品总数
            self.chain_depth[start_new] = len(all_olds)

        # -------------------------------------------------------------------
        # Step 4: 构建老品→最新新品 的反向映射
        # -------------------------------------------------------------------
        self.old_to_new_map = {}
        for new_model, old_list in self.replacement_chain.items():
            for old_model in old_list:
                # 从 reverse_map 链式查找，直到找不到更"新"的替代者
                newest = reverse_map.get(old_model, new_model)
                current = newest
                while current in reverse_map:
                    current = reverse_map[current]
                # current 此时是该老品能追溯到的"最新一代新品"
                self.old_to_new_map[old_model] = current

        return self.replacement_chain, self.old_to_new_map, self.chain_depth

    # =======================================================================
    # 第二步：检测当前预测月份的过渡期
    # =======================================================================

    def detect_transition_periods(self, master_data, forecast_month):
        """
        检测当前预测月份存在的过渡期关系

        遍历所有替换关系链，根据上市时间、退市时间、老品状态等信息，
        筛选出当前预测月份正在发生的新老品过渡关系。

        分场景判断逻辑：

            场景A（has_planned_phaseout = True）：
                条件：老品有 预计退市时间 且不为空
                计算：
                  N = (退市月 - 上市月) + 1  （过渡期总月数）
                  i = (预测月 - 上市月) + 1  （当前月份序号）
                  i = clamp(i, 1, N)        （限制在 [1, N] 范围内）
                分配方式：线性分配（_calculate_linear_split）
                  new_ratio = min(i / N, 1.0)
                  old_ratio = 1.0 - new_ratio

            场景B（has_planned_phaseout = False）：
                条件：老品没有 预计退市时间 或该字段为空
                计算：
                  i = (预测月 - 上市月) + 1  （当前月份序号，不设上限）
                分配方式：按渠道比例延续（_calc_ratio_for_row）
                  首月：新品比例 = 0.2 × (上市天数/当月天数)
                  后续月：按上月该渠道实际销量比例分配

        输入：
            master_data : pd.DataFrame
                主数据，需包含上市时间、退市时间（可选）、status 字段
            forecast_month : str or datetime
                预测月份，如 "2025-07-01" 或 datetime(2025, 7, 1)

        输出：
            List[TransitionInfo]
                过渡期信息对象列表，每个元素代表一个 新品→老品 的过渡关系

        过滤规则（不满足以下条件的关系将被跳过）：
            1. 新品在 master_data 中不存在 → 跳过
            2. 新品没有 预计生产时间（上市时间）→ 跳过
            3. 上市时间无法解析为合法日期 → 跳过
            4. 老品在 master_data 中不存在 → 跳过
            5. 老品 status ≠ "主销" → 跳过（只有主销状态的老品才参与分配）
        """
        # -------------------------------------------------------------------
        # Step 0: 自适应列名
        # -------------------------------------------------------------------
        col_model = '型号-CRM最新名称' if '型号-CRM最新名称' in master_data.columns else 'product_mode_code'
        col_remark = '对应老品/备注' if '对应老品/备注' in master_data.columns else 'remark'
        col_prod_time = '预计生产时间' if '预计生产时间' in master_data.columns else 'expected_prod_time'
        col_disc_time = '预计退市时间' if '预计退市时间' in master_data.columns else 'expected_disc_time'
        col_status = 'status' if 'status' in master_data.columns else 'product_status'

        # 统一将预测月份转为 datetime 类型
        if isinstance(forecast_month, str):
            forecast_month = pd.to_datetime(forecast_month)

        if not self.replacement_chain:
            self.replacement_chain, self.old_to_new_map, self.chain_depth = self.build_replacement_chain(master_data)
        if not self.replacement_chain:
            return []

        transitions: List[TransitionInfo] = []

        # -------------------------------------------------------------------
        # 遍历 replacement_chain 中的所有 新品→老品 关系
        # -------------------------------------------------------------------
        for new_model, old_list in self.replacement_chain.items():
            # 检查新品是否存在于主数据中
            new_row = master_data[master_data[col_model] == new_model]
            if new_row.empty:
                continue

            # ---- 解析新品上市月份 ----
            prod_times = new_row[col_prod_time].dropna()
            if len(prod_times) == 0:
                continue
            launch_time_str = prod_times.iloc[0]
            try:
                launch_month = self._parse_date(launch_time_str)
            except Exception:
                continue
            if launch_month is None or pd.isna(launch_month):
                continue

            # ---- 遍历该新品对应的每个老品 ----
            for old_model in old_list:
                old_row = master_data[master_data[col_model] == old_model]
                if old_row.empty:
                    continue

                # ---- 检查老品状态 ----
                # 只有 "主销" 状态的老品才参与分配
                # 例如：已退市、停产的型号 skip
                old_status = str(old_row[col_status].iloc[0]) if col_status in old_row.columns else ''
                if old_status != '主销':
                    continue

                # ---- 解析老品退市时间 ----
                disc_time_str = None
                if col_disc_time in old_row.columns:
                    disc_times = old_row[col_disc_time].dropna()
                    if len(disc_times) > 0:
                        disc_time_str = disc_times.iloc[0]
                has_planned_phaseout = False
                phase_out_month = None
                total_months = 0
                month_index = 0

                if disc_time_str is not None:
                    try:
                        phase_out_month = self._parse_date(disc_time_str)
                    except Exception:
                        phase_out_month = None

                # ---- 根据是否有退市时间分场景计算 ----
                if phase_out_month is not None and not pd.isna(phase_out_month):
                    # ============================================
                    # 场景A：有明确退市计划 → 线性分配
                    # ============================================
                    has_planned_phaseout = True
                    # 过渡期总月数 N = (退市月 - 上市月) + 1
                    total_months = ((phase_out_month.year - launch_month.year) * 12 +
                                    phase_out_month.month - launch_month.month) + 1
                    # 当前月份序号 i = (预测月 - 上市月) + 1
                    month_index = ((forecast_month.year - launch_month.year) * 12 +
                                   forecast_month.month - launch_month.month) + 1
                    # 限制在 [1, N] 范围内
                    month_index = max(1, min(month_index, total_months))
                else:
                    # ============================================
                    # 场景B：无退市计划 → 按渠道比例延续
                    # ============================================
                    total_months = 0   # 无上限
                    month_index = ((forecast_month.year - launch_month.year) * 12 +
                                   forecast_month.month - launch_month.month) + 1
                    month_index = max(1, month_index)

                # 创建过渡期信息对象
                transition = TransitionInfo(
                    new_product=new_model,
                    old_products=[old_model],
                    launch_month=launch_month,
                    phase_out_month=phase_out_month,
                    transition_start=launch_month,
                    transition_end=phase_out_month,
                    has_planned_phaseout=has_planned_phaseout,
                    old_status=old_status,
                    month_index=month_index,
                    total_months=total_months,
                )
                transitions.append(transition)

        return transitions

    # =======================================================================
    # 第三步-A：场景A 的线性分配算法
    # =======================================================================

    def _calculate_linear_split(self, base_forecast, month_index, total_months):
        """
        场景A：线性分配（有明确退市计划的过渡期）

        分配公式：
            N = 过渡期总月数（从上市月到退市月）
            i = 当前预测月份在过渡期中的序号（1-based）
            new_ratio = min(i / N, 1.0)
            old_ratio = 1.0 - new_ratio

        业务含义：
            新品从上市开始，每月线性增长份额。
            第1个月 新占 1/N，老占 (N-1)/N
            第2个月 新占 2/N，老占 (N-2)/N
            ...
            第N个月 新占 100%，老占 0%（替代完成）

        示例：
            上市月 = 1月，退市月 = 6月 → N = 6
            预测月 = 3月 → i = 3
            new_ratio = 3/6 = 0.5 → 新品50%，老品50%

        输入：
            base_forecast : pd.Series or np.ndarray
                预测基准值（新品在各渠道的原始预测）
            month_index : int
                当前月份在过渡期中的序号（从1开始）
            total_months : int
                过渡期总月数

        输出：
            tuple (new_forecast, old_forecast)
            - new_forecast : 新品分配到的预测值
            - old_forecast : 老品分配到的预测值
        """
        # 边界保护：退市月≤上市月时，新品占100%
        if total_months <= 0:
            return base_forecast, base_forecast * 0

        # 新品比例 = i / N（上限100%）
        new_ratio = min(month_index / total_months, 1.0)
        # 老品比例 = 剩余部分
        old_ratio = 1.0 - new_ratio

        new_forecast = base_forecast * new_ratio
        old_forecast = base_forecast * old_ratio
        return new_forecast, old_forecast

    # =======================================================================
    # 第三步-B：场景B 的按渠道比例延续算法
    # =======================================================================

    def _calc_ratio_for_row(self, base_val, new_model, old_model,
                            historical_sales, forecast_month, launch_month, channel):
        """
        场景B：按渠道计算比例延续（无退市计划的过渡期）

        适用场景：
            老品没有明确的退市时间，新品逐渐蚕食老品份额。
            分配比例不按线性增长，而是延续上月该渠道的实际销量比例。

        算法分阶段：

            【上市首月】（month_index = 1）：
                新品刚上市，只有部分天数在售。
                new_ratio = DEFAULT_RATIO(0.2) × (上市天数 / 当月总天数)
                → 新品上市首月仅占很小比例
                示例：7月15日上市 → days_on_market=16 → new_ratio=0.2×16/31≈0.103

            【第2个月】（month_index = 2）：
                基于上月真实销量比例，但首月天数不完整需要归一化：
                - 从 historical_sales 读取上月该渠道的新品销量 prev_new_sales
                - 计算新品归一化销量 = prev_new_sales / new_factor
                  （new_factor = 上月新品上市天数占比，压缩回去得到"满月等效销量"）
                - new_ratio = 新品归一化销量 / (新品归一化销量 + 老品销量)
                → 消除"上市天数不完整"对比例的影响

            【第3个月及以后】（month_index >= 3）：
                - 从 historical_sales 读取上月该渠道的新品销量 prev_new_sales
                  （此时新品已在市整月，new_factor = 1.0）
                - new_ratio = 新品上月销量 / (新品上月销量 + 老品上月销量)
                → 直接按上月实际销量比例延续

            兜底机制：
                如果 historical_sales 为空、或上月无该渠道销量数据、
                或新老品总销量为0，则 fallback 到默认比例 DEFAULT_RATIO(0.2)。

        输入：
            base_val : float
                该行新品的预测基准值
            new_model : str
                新品型号名称
            old_model : str
                老品型号名称
            historical_sales : pd.DataFrame or None
                历史销量数据，按 月份×型号×渠道 粒度
            forecast_month : datetime
                预测月份
            launch_month : datetime
                新品上市月份
            channel : str
                当前渠道名称

        输出：
            tuple (new_forecast, old_forecast)
            - new_forecast : float, 该渠道新品分配到的预测值
            - old_forecast : float, 该渠道老品分配到的预测值
        """
        # 统一预测月份格式
        if isinstance(forecast_month, str):
            forecast_month = pd.to_datetime(forecast_month)

        # 计算当前月份在过渡期中的序号
        month_index = ((forecast_month.year - launch_month.year) * 12 +
                       forecast_month.month - launch_month.month) + 1

        # -------------------------------------------------------------------
        # 上市首月：新品从月中开始销售
        # -------------------------------------------------------------------
        if month_index <= 1:
            # 当月总天数
            days_in_month = calendar.monthrange(forecast_month.year, forecast_month.month)[1]
            # 新品当月在售天数
            days_on_market = days_in_month - launch_month.day + 1
            # 新品比例 = 默认比例 × (在售天数 / 当月天数)
            # 例如：0.2 × 22/31 ≈ 0.1419
            new_ratio = self.config.NEW_OLD_TRANSITION_DEFAULT_RATIO * (days_on_market / days_in_month)
            new_ratio = min(max(new_ratio, 0), 1.0)
        else:
            # -------------------------------------------------------------------
            # 第2个月及以后：基于上月实际销量比例
            # -------------------------------------------------------------------
            prev_month = forecast_month - pd.DateOffset(months=1)
            prev_new_sales = 0
            prev_old_sales = 0

            # 从历史销量中读取上月数据
            if historical_sales is not None and not historical_sales.empty:
                col_model = '型号-CRM最新名称'
                col_ch = '3级渠道' if '3级渠道' in historical_sales.columns else 'channel_name_l3'

                # 筛选出新品上月销量
                new_sales_data = historical_sales[
                    (historical_sales[col_model] == new_model) &
                    (historical_sales['月份'] == prev_month)
                    ]
                # 筛选出老品上月销量
                old_sales_data = historical_sales[
                    (historical_sales[col_model] == old_model) &
                    (historical_sales['月份'] == prev_month)
                    ]

                # 按渠道进一步筛选（如果数据包含渠道字段）
                if col_ch in new_sales_data.columns:
                    new_sales_data = new_sales_data[new_sales_data[col_ch] == channel]
                    old_sales_data = old_sales_data[old_sales_data[col_ch] == channel]

                if not new_sales_data.empty:
                    prev_new_sales = new_sales_data['数量'].sum()
                if not old_sales_data.empty:
                    prev_old_sales = old_sales_data['数量'].sum()

            # 计算新品销量归一化因子（new_factor）
            if month_index == 2:
                # 上个月（上市首月）新品只卖了部分天数
                # 需要计算"满月等效销量"：新品实销量 / (当月天数占比)
                days_in_month_first = calendar.monthrange(launch_month.year, launch_month.month)[1]
                days_on_market_first = days_in_month_first - launch_month.day + 1
                new_factor = days_on_market_first / days_in_month_first
            else:
                # 第3个月及以后，新品已完整在售
                new_factor = 1.0

            # 新品归一化销量 = 实际销量 / 天数占比（补偿校正）
            new_normalized = prev_new_sales / max(new_factor, 0.01)
            # 总归一化销量
            total_normalized = new_normalized + prev_old_sales

            if total_normalized > 0:
                # 新品占比 = 新品归一化销量 / 总归一化销量
                new_ratio = min(new_normalized / total_normalized, 1.0)
            else:
                # 兜底：使用默认比例
                new_ratio = self.config.NEW_OLD_TRANSITION_DEFAULT_RATIO

        # 老品比例 = 剩余部分
        old_ratio = 1.0 - new_ratio
        new_forecast = base_val * new_ratio
        old_forecast = base_val * old_ratio
        return new_forecast, old_forecast

    # =======================================================================
    # 已废弃：场景B 旧版分配方法（保留向后兼容）
    # =======================================================================

    def _calculate_ratio_split(self, base_forecast, new_model, old_model,
                                historical_sales, forecast_month, launch_month):
        """
        【已废弃】场景B：比例延续（旧版聚合计算）

        注意：此方法已被 _calc_ratio_for_row 替代。
        旧版在聚合层面计算比例（不分渠道），新版本改为逐行按渠道计算，
        逻辑更精确。保留此方法仅为向后兼容，不建议新代码使用。

        如果调用此方法，会忽略渠道差异，取全局（不分渠道）的历史销量
        来计算新老品比例。
        """
        if isinstance(forecast_month, str):
            forecast_month = pd.to_datetime(forecast_month)

        month_index = ((forecast_month.year - launch_month.year) * 12 +
                       forecast_month.month - launch_month.month) + 1

        if month_index <= 1:
            days_in_month = calendar.monthrange(forecast_month.year, forecast_month.month)[1]
            days_on_market = days_in_month - launch_month.day + 1
            new_ratio = self.config.NEW_OLD_TRANSITION_DEFAULT_RATIO * (days_on_market / days_in_month)
            new_ratio = min(max(new_ratio, 0), 1.0)
        else:
            prev_month = forecast_month - pd.DateOffset(months=1)
            prev_new_sales = 0
            prev_old_sales = 0

            if historical_sales is not None and not historical_sales.empty:
                col_model = '型号-CRM最新名称'
                # 注意：旧版不做渠道级别筛选，取全局销量
                new_sales_data = historical_sales[
                    (historical_sales[col_model] == new_model) &
                    (historical_sales['月份'] == prev_month)
                    ]
                old_sales_data = historical_sales[
                    (historical_sales[col_model] == old_model) &
                    (historical_sales['月份'] == prev_month)
                    ]
                if not new_sales_data.empty:
                    prev_new_sales = new_sales_data['数量'].sum()
                if not old_sales_data.empty:
                    prev_old_sales = old_sales_data['数量'].sum()

            if month_index == 2:
                days_in_month_first = calendar.monthrange(launch_month.year, launch_month.month)[1]
                days_on_market_first = days_in_month_first - launch_month.day + 1
                new_factor = days_on_market_first / days_in_month_first
            else:
                new_factor = 1.0

            new_normalized = prev_new_sales / max(new_factor, 0.01)
            total_normalized = new_normalized + prev_old_sales

            if total_normalized > 0:
                new_ratio = min(new_normalized / total_normalized, 1.0)
            else:
                new_ratio = self.config.NEW_OLD_TRANSITION_DEFAULT_RATIO

        old_ratio = 1.0 - new_ratio
        new_forecast = base_forecast * new_ratio
        old_forecast = base_forecast * old_ratio
        return new_forecast, old_forecast

    # =======================================================================
    # 安全赋值工具（绕过 pandas .loc 布尔索引静默失败问题）
    # =======================================================================

    @staticmethod
    def _safe_assign(df, mask, col, values):
        pos = np.where(mask.values)[0]
        col_idx = df.columns.get_loc(col)
        if len(pos) != len(values):
            raise ValueError(f"长度不匹配: mask={len(pos)}, values={len(values)}")
        df.iloc[pos, col_idx] = values

    @staticmethod
    def _parse_date(date_str):
        return parse_flexible_date(date_str)

    # =======================================================================
    # 第三步：应用过渡期份额分配（主入口）
    # =======================================================================

    def _get_combined_base(self, adjusted, new_mask, old_products, col_model, col_channel):
        """返回单一需求池：优先使用已继承老品历史的新品预测。"""
        return adjusted.loc[new_mask, 'y_pred'].copy()

    @staticmethod
    def _old_has_valid_price(adjusted, old_products, channel, col_model, col_channel):
        """判断指定渠道下是否至少有一个老品仍维护有效计划价格。"""
        if 'avg_price' not in adjusted.columns:
            # 兼容没有价格字段的旧调用方，不改变其原有分配行为。
            return True

        old_rows = adjusted[
            adjusted[col_model].isin(old_products) &
            (adjusted[col_channel] == channel)
        ]
        if old_rows.empty:
            return False

        prices = pd.to_numeric(old_rows['avg_price'], errors='coerce').fillna(0)
        return bool((prices > 0).any())

    # =======================================================================

    def apply_transition_split(self, forecast_results, historical_sales,
                                master_data, forecast_month, debug=False):
        """
        对预测结果应用新老品过渡期份额分配（主入口方法）

        这是优化器的核心方法，负责：
            1. 调用 detect_transition_periods 获取当前有效的过渡期
            2. 对每个过渡期中的新品，按场景A/B分别计算分配比例
            3. 削减新品预测值，将削减部分分配给对应的老品
            4. 处理 pandas index 对齐问题（新品和老品索引范围不同）

        Pandas Index 对齐说明：
            combined DataFrame 中，新品行和老品行使用不同的索引。
            当旧代码尝试 `adjusted.loc[old_mask, 'y_pred'] = old_values`
            时，old_values 的索引源于新品行的索引，与 old_mask 的索引
            不匹配，导致 pandas 静默失败（assign 0 或 NaN）。

            修复方案：
            1. 优先尝试长度匹配（len(old_values) == old_mask.sum()）：
               直接赋值（因为长度相同，但索引不同），使用 .values 转为
               numpy 数组后赋值可以绕过 index 对齐问题
            2. 长度不匹配时，使用渠道映射兜底：
               构建 {渠道: old_value} 字典，对 old_mask 的每一行
               按其渠道查找对应的分配值，逐行赋值。

        输入：
            forecast_results : pd.DataFrame
                pipeline 中间格式的预测结果，包含：
                - 型号-CRM最新名称 : 型号名称
                - 3级渠道(channel_name_l3) : 渠道
                - y_pred : 预测值
            historical_sales : pd.DataFrame or None
                历史销量数据（场景B需要）
            master_data : pd.DataFrame
                主数据
            forecast_month : str or datetime
                预测月份
            debug : bool, default=False
                是否启用调试输出（打印分配详情）

        输出：
            pd.DataFrame
                调整后的 forecast_results 副本，y_pred 值已按过渡期分配
        """
        # ---- 边界检查 ----
        if forecast_results.empty:
            return forecast_results

        # ---- 第一步：获取当前有效的过渡期 ----
        transitions = self.detect_transition_periods(master_data, forecast_month)
        if not transitions:
            if debug:
                print('  [DEBUG] 无过渡期，跳过')
            return forecast_results

        # 创建副本，不修改原始数据
        adjusted = forecast_results.copy().reset_index(drop=True)

        # ---- 自适应列名 ----
        col_model = '型号-CRM最新名称'
        col_channel = '3级渠道' if '3级渠道' in adjusted.columns else 'channel_name_l3'

        if debug:
            print(f'  [DEBUG] 过渡期数={len(transitions)} col_model={col_model} col_channel={col_channel}')
            print(f'  [DEBUG] 型号样本: {list(adjusted[col_model].unique()[:10])}')

        # ---- 第二步：逐过渡期处理 ----
        for trans in transitions:
            # ---------------------------------------------------------------
            # 2.1 定位新品行
            # ---------------------------------------------------------------
            new_mask = adjusted[col_model] == trans.new_product
            if not new_mask.any():
                if debug:
                    print(f'  [DEBUG] 新品 {trans.new_product} 不在结果中')
                continue

            # 保存新品原始预测值（用于判断反向分配）
            new_base_vals = adjusted.loc[new_mask, 'y_pred'].copy()
            base_sum = new_base_vals.sum()

            # ---------------------------------------------------------------
            # 判断分配方向
            #   正常方向：新品有预测值 → 从新品切份额给老品
            #   反向分配：新品预测值为0 → 从老品切份额给新品
            # ---------------------------------------------------------------
            reverse_direction = base_sum == 0
            if not reverse_direction:
                # 正常方向：新品已继承老品历史，只使用新品预测作为单一需求池。
                base_forecast_val = self._get_combined_base(
                    adjusted, new_mask, trans.old_products, col_model, col_channel
                )
            else:
                base_forecast_val = new_base_vals
            if reverse_direction:
                # 尝试从所有老品获取基数进行反向分配
                combined_base_parts = []
                _reverse_old_masks_list = []
                for old_model in trans.old_products:
                    old_mask_check = adjusted[col_model] == old_model
                    if old_mask_check.any():
                        old_base_vals = adjusted.loc[old_mask_check, 'y_pred']
                        if old_base_vals.sum() > 0:
                            combined_base_parts.append(old_base_vals)
                            _reverse_old_masks_list.append(old_mask_check)
                if not combined_base_parts:
                    reverse_direction = False
                else:
                    base_forecast_val = pd.concat(combined_base_parts)

            if debug:
                print(f'  [DEBUG] {trans.new_product}: 行数={new_mask.sum()} '
                      f'base_sum={base_sum:.0f} reverse={reverse_direction}')

            # ---------------------------------------------------------------
            # 2.2 按场景计算新老品分配值
            # ---------------------------------------------------------------
            if trans.has_planned_phaseout:
                # =========================================================
                # 场景A：线性分配
                # =========================================================
                new_pred, old_pred = self._calculate_linear_split(
                    base_forecast_val, trans.month_index, trans.total_months
                )
                # 四舍五入取整、裁剪负值、转为 numpy 数组（绕过 index 对齐）
                new_values = new_pred.round(0).astype(int).clip(lower=0).values
                old_values = old_pred.round(0).astype(int).clip(lower=0).values

                # 老品当月无有效价格时，不允许分配后重新产生销量。
                source_channels = adjusted.loc[base_forecast_val.index, col_channel].values
                base_values = base_forecast_val.round(0).astype(int).clip(lower=0).values
                for pos, channel in enumerate(source_channels):
                    if not self._old_has_valid_price(
                            adjusted, trans.old_products, channel, col_model, col_channel):
                        new_values[pos] = base_values[pos]
                        old_values[pos] = 0

                # 构建渠道字典，供统一赋值使用
                old_values_per_ch = dict(zip(
                    source_channels,
                    old_values
                ))
            else:
                # =========================================================
                # 场景B：按渠道比例延续（逐行计算）
                # =========================================================
                new_indices = adjusted.loc[new_mask].index
                new_values = []
                old_values_per_ch = {}       # {渠道: 老品分配值} 字典

                for idx in new_indices:
                    ch = adjusted.loc[idx, col_channel]
                    if reverse_direction:
                        old_rows = adjusted.loc[
                            adjusted[col_model].isin(trans.old_products) &
                            (adjusted[col_channel] == ch), 'y_pred'
                        ]
                        base_val = old_rows.sum()
                    else:
                        base_val = adjusted.loc[idx, 'y_pred']

                    if not self._old_has_valid_price(
                            adjusted, trans.old_products, ch, col_model, col_channel):
                        # 老品无价格：全部需求由新品承接。
                        new_val, old_val = base_val, 0
                    else:
                        # 逐行按渠道计算分配
                        new_val, old_val = self._calc_ratio_for_row(
                            base_val, trans.new_product, trans.old_products[0],
                            historical_sales, forecast_month, trans.launch_month, ch
                        )
                    new_values.append(max(int(round(new_val)), 0))
                    old_values_per_ch[ch] = max(int(round(old_val)), 0)

                new_values = np.array(new_values)

            # ---------------------------------------------------------------
            # 2.3 更新预测值（按方向分配）
            # ---------------------------------------------------------------
            if reverse_direction:
                # =========================================================
                # 反向分配：base_forecast_val 来自老品，索引为老品行
                #   new_values → 新品（需渠道映射）
                #   old_values → 老品（按渠道分配回各老品）
                # =========================================================
                if trans.has_planned_phaseout:
                    # 场景A: old_values 长度 = 合并后老品行数
                    # 按各老品行数切分 old_values 并回写
                    offset = 0
                    for mask in _reverse_old_masks_list:
                        n = mask.sum()
                        self._safe_assign(adjusted, mask, 'y_pred',
                                          old_values[offset:offset + n])
                        offset += n
                else:
                    # 场景B: old_values_per_ch 已按渠道计算
                    # 遍历各老品行，按渠道查找 old_value 并回写
                    for mask in _reverse_old_masks_list:
                        for old_idx in adjusted.loc[mask].index:
                            ch = adjusted.loc[old_idx, col_channel]
                            if ch in old_values_per_ch:
                                adjusted.at[old_idx, 'y_pred'] = int(old_values_per_ch[ch])

                if debug:
                    orig_old_sum = base_forecast_val.sum()
                    if trans.has_planned_phaseout:
                        old_sum = old_values.sum()
                    else:
                        old_sum = sum(old_values_per_ch.values())
                    print(f'    老品y_pred: {orig_old_sum:.0f} -> {old_sum:.0f}')

                # ---- 更新新品（按渠道从所有老品映射回新品）----
                if trans.has_planned_phaseout:
                    old_channels_combined = np.concatenate([
                        adjusted.loc[mask, col_channel].values
                        for mask in _reverse_old_masks_list
                    ])
                    ch_to_new_val = dict(zip(old_channels_combined, new_values))
                    assigned = 0
                    for new_idx in adjusted.loc[new_mask].index:
                        ch = adjusted.loc[new_idx, col_channel]
                        if ch in ch_to_new_val:
                            adjusted.at[new_idx, 'y_pred'] = int(ch_to_new_val[ch])
                            assigned += 1
                else:
                    for i, new_idx in enumerate(adjusted.loc[new_mask].index):
                        adjusted.at[new_idx, 'y_pred'] = int(new_values[i])
                    assigned = new_mask.sum()
                    ch_to_new_val = {}
                if debug:
                    print(f'    反向→新品 渠道映射: {ch_to_new_val}')
                    print(f'    反向→新品 赋值: {assigned}/{new_mask.sum()} 行, '
                          f'接收={sum(ch_to_new_val.values()) if ch_to_new_val else new_values.sum():.0f}')
            else:
                # =========================================================
                # 正常方向：base_forecast_val 来自新品，索引为新品行
                #   new_values → 新品（直接赋值）
                #   old_values → 老品（需渠道映射）
                # =========================================================
                # ---- 更新新品预测值（削减）----
                self._safe_assign(adjusted, new_mask, 'y_pred', new_values)
                if debug:
                    print(f'    新品y_pred: {base_forecast_val.sum():.0f} -> {new_values.sum():.0f}')

                # ---- 更新老品预测值（接收）----
                for old_model in trans.old_products:
                    old_mask = adjusted[col_model] == old_model
                    if not old_mask.any():
                        if debug:
                            print(f'    *** 老品 {old_model} 不在结果中! ***')
                        continue

                    old_orig = adjusted.loc[old_mask, 'y_pred'].sum()
                    # 按老品行的渠道顺序构建 old_values，保证长度天然匹配
                    old_values = np.array([old_values_per_ch.get(ch, 0)
                                           for ch in adjusted.loc[old_mask, col_channel].values])
                    self._safe_assign(adjusted, old_mask, 'y_pred', old_values)
                    if debug:
                        new_sum = adjusted.loc[old_mask, 'y_pred'].sum()
                        print(f'    老品 {old_model}: 行数={old_mask.sum()} '
                              f'old_orig_sum={old_orig:.0f} old_val_sum={old_values.sum():.0f} '
                              f'-> {new_sum:.0f}')

        return adjusted
