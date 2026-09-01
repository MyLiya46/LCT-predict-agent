# -*- coding: utf-8 -*-
"""
Created on Fri Feb 28 10:43:11 2025

@author: Dylan
"""
from lunarcalendar import Lunar
import pandas as pd
import numpy as np
from new_old_product_optimizer import parse_flexible_date

class DataProcessing:
    def __init__(self, sales_data, master_data, prediction_month, optimizer=None):
        self.sales_data = sales_data
        self.master_data = master_data
        self.prediction_month = prediction_month
        self.optimizer = optimizer

    def merge_replacement_sales(self):
        """
        基于替代关系合并历史销量
        master_data - 主数据，包含[月份, 型号, 替代关系]三列
        sales_data 原始销量数据，需包含[月份, 渠道, 型号, 销量]等列
        返回：处理后的合并销量表
        """
        rename_dict = {
            'remark': '对应老品/备注',
            'expected_prod_time': '预计生产时间',
        }
        self.master_data = self.master_data.rename(columns=rename_dict)

        if self.optimizer is not None:
            self.optimizer.build_replacement_chain(self.master_data)
            replacement_chain = self.optimizer.replacement_chain

            chain_rows = []
            for new_model, old_models in replacement_chain.items():
                new_row = self.master_data[self.master_data['型号-CRM最新名称'] == new_model]
                if new_row.empty:
                    continue
                prod_time = new_row['预计生产时间'].iloc[0]
                for old_model in old_models:
                    chain_rows.append({
                        '型号-CRM最新名称': new_model,
                        '预计生产时间': prod_time,
                        '旧品型号': old_model,
                    })
            if chain_rows:
                master_processed = pd.DataFrame(chain_rows)
            else:
                master_processed = pd.DataFrame(columns=['型号-CRM最新名称', '预计生产时间', '旧品型号'])
        else:
            master_processed = (
                self.master_data.assign(旧品型号=lambda x: x['对应老品/备注'].str.split('、'))
                .explode('旧品型号')[['型号-CRM最新名称', '预计生产时间', '旧品型号']]
            )

        # 与过渡期检测共用同一日期解析口径，避免斜杠/横杠日期无法激活历史继承。
        master_processed['替代月份'] = master_processed['预计生产时间'].apply(parse_flexible_date)
        has_relation = master_processed.query(
            '旧品型号.notna() and 替代月份 <= @self.prediction_month'
        )

        related_old_models = has_relation['旧品型号'].unique()

        related_old_items = master_processed[
            master_processed['型号-CRM最新名称'].isin(related_old_models)
        ]

        master_processed = pd.concat(
            [has_relation, related_old_items],
            ignore_index=True
        ).drop_duplicates()

        master_processed['型号-CRM最新名称'] = master_processed['型号-CRM最新名称'].str.replace(r'[（(].*?[）)]', '',
                                                                                                regex=True)
        master_processed['旧品型号'] = master_processed['旧品型号'].str.replace(r'[（(].*?[）)]', '',
                                                                                regex=True)
        merged = pd.merge(
            master_processed,
            self.sales_data.rename(columns={'型号-CRM最新名称': '旧品型号'}),
            on='旧品型号',
            how='inner'
        )

        merged['月份'] = pd.to_datetime(merged['月份'])
        merged['替代月份'] = pd.to_datetime(merged['替代月份'])

        own_keys = ['月份', '1级渠道', '3级渠道', '型号-CRM最新名称']
        own_sales = (
            self.sales_data.groupby(own_keys, as_index=False)[['数量', '实收金额']]
            .sum()
            .rename(columns={'数量': '数量_自身', '实收金额': '实收金额_自身'})
        )
        own_sales['月份'] = pd.to_datetime(own_sales['月份'])

        final_df = pd.concat([self.sales_data, merged], ignore_index=True)
        final_df = final_df.groupby(['月份', '1级渠道', '3级渠道', '型号-CRM最新名称'])[['数量', '实收金额']].sum().reset_index()
        final_df['月份'] = pd.to_datetime(final_df['月份'])
        final_df = final_df.merge(own_sales, on=own_keys, how='left')
        final_df['数量_自身'] = final_df['数量_自身'].fillna(0)
        final_df['实收金额_自身'] = final_df['实收金额_自身'].fillna(0)
        final_df['avg_price'] = final_df.apply(
            lambda row: row['实收金额'] / row['数量'] if row['数量'] != 0 and row['实收金额'] != 0 else np.nan,
            axis=1)
        return final_df.sort_values(['月份', '3级渠道']).reset_index(drop=True)

    def fill_missing_dates(self):
        # 创建完整时间索引（按每个组合的最小月份）
        groups = []
        for (channel_1, channel_3, sku), group in self.sales_data.groupby(['1级渠道', '3级渠道', '型号-CRM最新名称']):
            start_date = group['月份'].min()
            end_date = self.prediction_month

            # 生成时间序列
            date_rng = pd.date_range(
                start=start_date,
                end=end_date,
                freq='MS'
            )

            # 构建基础数据框架
            base_df = pd.DataFrame({
                '月份': date_rng,
                '1级渠道': channel_1,
                '3级渠道': channel_3,
                '型号-CRM最新名称': sku
            })

            value_cols = ['数量', '实收金额']
            for extra in ('数量_自身', '实收金额_自身'):
                if extra in group.columns:
                    value_cols.append(extra)
            # 合并原始数据
            merged = pd.merge(
                base_df,
                group[['月份', '1级渠道', '3级渠道', '型号-CRM最新名称'] + value_cols].reset_index(drop=True),
                on=['月份', '1级渠道', '3级渠道', '型号-CRM最新名称'],
                how='left'
            )

            # 填充缺失值（自身销量缺失=该月无真实零售，不能用合并后的继承量回填）
            for col in value_cols:
                merged[col] = merged[col].fillna(0)
            groups.append(merged)

        # 合并所有组的数据
        filled_df = pd.concat(groups, ignore_index=True)
        filled_df = filled_df.sort_values(
            ['1级渠道', '3级渠道', '型号-CRM最新名称', '月份']
        ).reset_index(drop=True)

        print(f"完成数据填充，总记录数：{len(filled_df)}")
        return filled_df

    def data_processing(self):
        # 数据过滤
        self.sales_data['数量'] = pd.to_numeric(self.sales_data['数量'], errors='coerce')
        self.sales_data['实收金额'] = pd.to_numeric(self.sales_data['实收金额'], errors='coerce')
        self.sales_data = self.merge_replacement_sales()
        skulist = self.master_data.query('月份 <= @self.prediction_month')['型号-CRM最新名称'].unique().tolist()
        # 计划渠道与SKU筛选
        self.sales_data = self.sales_data[self.sales_data['型号-CRM最新名称'].isin(skulist)]
        # 补齐历史数据
        fullfill_set = self.fill_missing_dates()
        fullfill_set['avg_price'] = np.where(
            fullfill_set['数量'] == 0,  # 条件：数量为0
            0,  # 条件为真时的值（可改为np.nan表示NaN）
            fullfill_set['实收金额'] / fullfill_set['数量']
        )
        return fullfill_set,skulist


class FeatureEngineering:
    # todo 1. 初始化接收 horizon_offset
    def __init__(self, df, master_data, price_data, prediction_month, skulist, rebate_set, config, horizon_offset=0):
        self.df = df
        self.master_data = master_data
        self.price_data = price_data
        self.prediction_month = prediction_month
        self.window_stats = ['mean', 'max', 'skew', 'std', 'kurt', 'min', 'median']  # 统计指标集合
        self.skulist = skulist
        self.rebate_set = rebate_set
        self.config = config
        self.horizon_offset = horizon_offset  # todo 新增

    @staticmethod
    def calculate_elasticity(group):
        """计算分组内的价格弹性，包含分母保护"""
        price_change = group['price_change'].astype(float)
        quantity_diff = group['qty_lag1'].diff().abs().astype(float)
        # 分母保护：当差值绝对值小于阈值时视为0
        threshold = 1e-9  # 可根据数据精度调整
        protected = np.where(
            quantity_diff < threshold,
            0,
            quantity_diff
        )
        # 计算弹性并限制输出范围
        elasticity = price_change / protected
        elasticity = np.clip(elasticity, -10, 10)  # 防止极端值
        return elasticity

    def get_spring_festival_years(self):
        """自动计算需要覆盖的春节年份范围"""
        # 解析目标月份
        target_date = pd.to_datetime(self.prediction_month)
        end_year = target_date.year + 1  # 目标年份+1
        return range(2015, end_year)  # 包含结束年

    def generate_spring_features(self):
        """生成春节相关特征集合"""
        # 获取年份范围
        years = self.get_spring_festival_years()

        # 生成春节月份字典
        spring_dict = {}
        for year in years:
            try:
                date_obj = Lunar(year, 1, 1).to_date()
                spring_dict[year] = date_obj.month
            except Exception as e:
                print(f"Warning: 获取{year}年春节日期失败 - {str(e)}")
                continue

        # 生成特征集合
        spring_months = set((y, m) for y, m in spring_dict.items())

        # 计算春节前月（自动处理跨年）
        pre_spring_months = set()
        for year, month in spring_dict.items():
            if month == 1:
                pre_spring_months.add((year - 1, 12))
            else:
                pre_spring_months.add((year, month - 1))

        return {
            'spring_festival': spring_months,
            'pre_spring': pre_spring_months,
            'spring_dict': spring_dict
        }

    # todo 2. 在 feature_engineering 方法中增加偏移量
    def feature_engineering(self, df, window_size=None, lags=None):
        if lags is None:
            lags = [1, 2, 3, 6, 12]
        if window_size is None:
            window_size = [3, 6]

        # 3. 主数据合并优化
        # 主数据合并
        master_rename_dict = {
            'channel_name_l3': '3级渠道',
            'category_name': '品类',
            'product_type': 'type',
            'product_series': 'series',
            'product_status': 'status',
        }
        self.master_data = self.master_data.rename(columns=master_rename_dict)

        df = pd.merge(df, self.master_data[['product_line_code', 'product_line_name', '3级渠道', '型号-CRM最新名称', '品类', 'type', 'series', 'status']].drop_duplicates(),
                      on=['3级渠道', '型号-CRM最新名称'], how='right')

        # 填充补充型号空值
        miss_mask = df['月份'].isna()
        df_miss = df[miss_mask]

        df_miss = df_miss.drop(columns=['零售扣点', '费用扣点', '收入扣点'])
        rebate_cols = ['3级渠道', '零售扣点', '费用扣点', '收入扣点']

        df_miss = pd.merge(df_miss, self.rebate_set[rebate_cols], on=['3级渠道'], how='left')
        df_miss[['数量', '实收金额', 'avg_price']] = df_miss[['数量', '实收金额', 'avg_price']].fillna(0)
        for own_col in ('数量_自身', '实收金额_自身'):
            if own_col in df_miss.columns:
                df_miss[own_col] = df_miss[own_col].fillna(0)
        df_miss['1级渠道'] = df_miss['3级渠道'].replace(self.config.CHANNEL_MAPPING)
        df_miss['月份'] = self.prediction_month

        # 将处理后的缺失数据补充到df
        df.loc[miss_mask] = df_miss[df.columns].values

        df = df.sort_values(by=['1级渠道', '3级渠道', 'series', '型号-CRM最新名称'])

        # 快速生成滞后特征(todo：加上 horizon_offset)
        for lag in lags:
            actual_lag = lag + self.horizon_offset
            df[f'qty_lag{lag}'] = df.groupby(['1级渠道', '3级渠道', 'series', '型号-CRM最新名称'])['数量'].shift(actual_lag)
        # pandas 2.x：StringDtype 列不能 fillna(0)，只对数值列填 0
        num_cols = df.select_dtypes(include=[np.number]).columns
        df[num_cols] = df[num_cols].fillna(0)
        # 批量生成滑动窗口特征

        for size in window_size:
            for stat in self.window_stats:
                df[f'qty_lag1_{size}m_{stat}'] = df.groupby(['1级渠道', '3级渠道', 'series', '型号-CRM最新名称'])[
                    'qty_lag1'].transform(
                    lambda x: x.rolling(window=size, min_periods=1).agg(stat)
                )
        for size in window_size:
            df[f'qty_lag1_{size}m_cv'] = df.apply(
                lambda x: x[f'qty_lag1_{size}m_std'] / x[f'qty_lag1_{size}m_mean'] if x[
                    f'qty_lag1_{size}m_mean'] else 0, axis=1)

        # 差分特征
        # lag1的1阶差分：当前值 - 前1期值
        df['lag1_diff1'] = df.groupby(['1级渠道', '3级渠道', 'series', '型号-CRM最新名称'])['qty_lag1'].diff(1)
        df['lag1_diff2'] = df.groupby(['1级渠道', '3级渠道', 'series', '型号-CRM最新名称'])['lag1_diff1'].diff(1)

        # 新增特征部分
        # 1. 时间特征扩展
        df['year'] = df['月份'].dt.year
        df['month'] = df['月份'].dt.month
        df['quarter'] = df['月份'].dt.quarter
        df['is_onsale'] = df['月份'].dt.month.isin([6, 11, 12]).astype(int)
        # 生成春节特征
        spring_features = self.generate_spring_features()
        df['is_spring_festival'] = df[['year', 'month']].apply(
            lambda x: (x['year'], x['month']) in spring_features['spring_festival'],
            axis=1
        )
        df['is_pre_spring'] = df[['year', 'month']].apply(
            lambda x: (x['year'], x['month']) in spring_features['pre_spring'],
            axis=1
        )

        # 2. 价格特征
        group_avg = df.query('月份 < @self.prediction_month and 数量 > 0').groupby(
            ['1级渠道', '3级渠道', 'series', '型号-CRM最新名称'])[['数量', '实收金额']].sum().reset_index()
        group_avg['group_avg_price'] = group_avg['实收金额'] / group_avg['数量']

        # 价格数据
        df = pd.merge(df, group_avg[['1级渠道', '3级渠道', 'series', '型号-CRM最新名称', 'group_avg_price']],
                      how='left',
                      on=['1级渠道', '3级渠道', 'series', '型号-CRM最新名称'])
        df.loc[(df['月份'] < self.prediction_month) & (df['avg_price'].isna() | (df['avg_price'] <= 0)), 'avg_price'] = df['group_avg_price']

        # todo：price_lag 也加上偏移量，提取对应 horizon 前的实际价格
        df['price_lag1'] = df.groupby(['1级渠道', '3级渠道', 'series', '型号-CRM最新名称'])['avg_price'].shift(1 + self.horizon_offset)
        # 修改 price_change：用当前预估目标月的当月（计划）价格 - 前N期的已知真实价格
        df['price_change'] = df['avg_price'] - df['price_lag1']

        df['price_elasticity'] = df.groupby(['1级渠道', '3级渠道', 'series', '型号-CRM最新名称']).apply(
            self.calculate_elasticity).reset_index(drop=True)

        # 3. 销量占比
        # 计算分母：每个“渠道-月份-系列”的总销量(防止除以0)
        epsilon = 1e-6
        df['series_monthly_total_sales'] = df.groupby( ['3级渠道', '月份', 'series'])['数量'].transform('sum') + epsilon
        # 计算当月销量在系列内的占比
        df['sales_share_in_series'] = df['数量'] / df['series_monthly_total_sales']
        # 创建占比的滞后特征 (todo:加上 horizon_offset)
        for lag in [1, 2, 3, 4, 5, 6]:
            actual_lag = lag + self.horizon_offset
            df[f'share_lag{lag}'] = df.groupby(['3级渠道', '型号-CRM最新名称'])['sales_share_in_series'].shift(actual_lag)
        # 创建占比的滑动窗口和趋势特征
        df['share_3m_mean'] = df.groupby(['3级渠道', '型号-CRM最新名称'])['share_lag1'].transform(
            lambda x: x.rolling(3, 1).mean())
        df['share_6m_mean'] = df.groupby(['3级渠道', '型号-CRM最新名称'])['share_lag1'].transform(
            lambda x: x.rolling(6, 1).mean())
        df['share_diff_1m'] = df.groupby(['3级渠道', '型号-CRM最新名称'])['share_lag1'].diff()
        # 清理临时列和填充NaN
        df.drop(columns=['series_monthly_total_sales', 'sales_share_in_series'], inplace=True)
        share_cols = [col for col in df.columns if 'share' in col]
        df[share_cols] = df[share_cols].fillna(0)


        # 4. 渠道聚合特征
        for lag in [1, 2, 3, 6, 12]:
            df[f'total_series_lag{lag}_qty'] = df.groupby(['1级渠道', '3级渠道', '月份', 'series'])[
                f'qty_lag{lag}'].transform('sum')

        # 5. 文本特征提取
        df['volume'] = df['型号-CRM最新名称'].str.extract(r'(\d{3})').astype(float).fillna(0)

        # 6. 历史特征
        max_history = df.groupby(['1级渠道', '3级渠道', 'series', '型号-CRM最新名称']).agg(
            history_max=('qty_lag1', 'max'),
            history_max_idx=('qty_lag1', 'idxmax')  # 获取最大值对应月份
        ).reset_index()

        df = pd.merge(df, max_history, on=['1级渠道', '3级渠道', 'series', '型号-CRM最新名称'], how='left')
        df['max_qty_related_price'] = df['history_max_idx'].apply(
            lambda idx: df['price_lag1'].get(idx, 0) if idx != -1 else 0)
        df['max_price_gap'] = df['max_qty_related_price'] - df['avg_price']

        min_history = df.groupby(['1级渠道', '3级渠道', 'series', '型号-CRM最新名称']).agg(
            history_price_min=('price_lag1', 'min'),
            history_price_min_idx=('price_lag1', 'idxmin')  # 获取最大值对应月份
        ).reset_index()

        df = pd.merge(df, min_history, on=['1级渠道', '3级渠道', 'series', '型号-CRM最新名称'], how='left')
        # 处理 NaN 并转换为整数索引
        df['history_price_min_idx'] = df['history_price_min_idx'].fillna(-1).astype(int)

        # 避免 KeyError
        df['min_price_related_qty'] = df['history_price_min_idx'].apply(
            lambda idx: df['qty_lag1'].get(idx, 0) if idx != -1 else 0)
        df['min_price_gap'] = df['history_price_min'] - df['avg_price']
        return df

    def prepare_prediction_set(self, price_df,prediction_month,mapping):
        """
        生成预测用价格特征集
        参数：
        price_df: 处理后的价格数据
        sku_list: 有效型号列表
        prediction_month: 预测月份(datetime)
        channels: 3级渠道列表
        """
        filtered = price_df[
            (price_df['型号'].isin(self.skulist)) &
            (price_df['月份'].dt.floor('1D') == prediction_month)
            ].rename(columns={'型号': '型号-CRM最新名称'})

        # 生成渠道笛卡尔积
        channel_df = pd.DataFrame(mapping.items(), columns=["3级渠道", "1级渠道"])

        # 添加一个临时列用于交叉连接（笛卡尔积）
        filtered['temp'] = 1
        channel_df['temp'] = 1

        # 执行交叉连接获取笛卡尔积
        pred_set = pd.merge(filtered, channel_df, on='temp').drop('temp', axis=1)
        pred_set['数量'] = 0
        # 调整列的顺序
        pred_set = pred_set[['月份','1级渠道', '3级渠道', '型号-CRM最新名称', 'avg_price', '数量', '大单机出货价']]

        return pred_set

    def run_feature_engineer(self, window_size=[3,6,9,12], lags=[1,2,3,4,5,6,7,8,9,10,11,12]):

        pred_set = self.prepare_prediction_set(self.price_data,self.prediction_month,self.config.CHANNEL_MAPPING)

        pred_set = pd.merge(pred_set, self.rebate_set, on=['3级渠道'], how='left') # .drop_duplicates()
        
        # mask = pred_set['大单机出货价'].notna() & pred_set['大单机零售扣点'].notna() & pred_set['大单机费用扣点'].notna()
        # pred_set.loc[mask, ['零售扣点', '费用扣点']] = pred_set.loc[mask, ['大单机零售扣点', '大单机费用扣点']].values
        # pred_set = pred_set.drop(['大单机零售扣点', '大单机费用扣点', '大单机收入扣点'], axis=1)

        pred_set['avg_price'] = pred_set['avg_price'] * (1 - pred_set['零售扣点'])
        self.df = self.df[self.df['月份'] < self.prediction_month].reset_index(drop=True)
        self.df = pd.concat([self.df, pred_set], ignore_index=True)
        feature_set = self.feature_engineering(self.df,window_size, lags)
        return feature_set
