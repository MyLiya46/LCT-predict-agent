# -*- coding: utf-8 -*-
"""
Created on Fri Feb 28 10:43:11 2025

@author: Dylan
"""
import re
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import warnings

from sqlalchemy import create_engine
from new_old_product_optimizer import parse_flexible_date


warnings.filterwarnings("ignore")

class SalesDataProcessor:
    def __init__(self, config):
        self.config = config
        self.engine = create_engine(self.config.ENGINE_URL)
        self.rules = {
            2020: {'淘系大官旗舰店': '天猫大官旗','淘系冰箱旗舰店|淘系洗衣机旗舰店':'淘系直营'},
            2021: {'淘系洗衣机旗舰店|淘系冰箱旗舰店': '淘系直营','唯品会|综合自控':'会员商城'},
            2022: {'淘系洗衣机旗舰店|淘系冰箱旗舰店': '淘系直营','唯品会|综合自控':'会员商城'}, # 源数据手动剔除了原有的淘系直营
            # 2023: {'拼多多大官旗|拼多多品旗': '拼多多直营','京东FCS':'京东POP','唯品会':'会员商城'},
            # 2024: {'拼多多大官旗|拼多多品旗': '拼多多直营','唯品会|企业商城|微商城':'会员商城','京东FCS|京东POP直营':'京东POP','抖音自营大官旗|抖音自营品旗':'抖音'},
            # 2025: {'拼多多大官旗|拼多多品旗': '拼多多直营','唯品会|企业商城|微商城':'会员商城','京东FCS|京东POP直营':'京东POP','抖音自营大官旗|抖音自营品旗':'抖音'}
            2023: {'京东FCS':'京东POP','唯品会':'会员商城'},
            2024: {'唯品会|企业商城|微商城':'会员商城','京东FCS|京东POP直营':'京东POP','抖音自营大官旗|抖音自营品旗':'抖音'},
            2025: {'唯品会|企业商城|微商城':'会员商城','京东FCS|京东POP直营':'京东POP','抖音自营大官旗|抖音自营品旗':'抖音'}
        }
        self.combo_rules = {
            # 'GH200T10-W': ['G100T10-W', 'H100T10-W'],
            # 'GH200T10-S': ['G100T10-S', 'H100T10-S'],
            # 'GH200T10H-BIS': ['G100T10H-BIS', 'H100T10H-BIS'],
            # 'GH200T10H-BIW': ['G100T10H-BIW', 'H100T10H-BIW']
        }
        self.child_to_parent_map = {child: parent for parent, children in self.combo_rules.items() for child in children}

    def _map_child_to_parent_sku(self, df):
        """
        对输入的DataFrame中的'型号-CRM最新名称'列应用子件到父件的映射。
        如果一个SKU是子件，则替换为父件名称；否则保持不变。
        """
        # 使用 .get(x, x) 如果找不到映射，则返回原值
        df['型号-CRM最新名称'] = df['型号-CRM最新名称'].apply(
            lambda x: self.child_to_parent_map.get(x, x)
        )
        return df

    def _preprocess_columns(self, df, num_cols):
        """统一列预处理"""
        # 文本列处理
        # df['型号-CRM最新名称'] = df['product_mode_code'].str.replace(r'[（(].*?[）)]', '', regex=True)
        df['型号-CRM最新名称'] = df['product_mode_code']
        # 数值列处理
        df['数量'] = df['retail_qty'].apply(lambda x: x if pd.notna(x) else x)
        df['实收金额'] = df['retail_amt'].apply(lambda x: x if pd.notna(x) else x)
        
        df[num_cols] = df[num_cols].fillna(0)
        df['月份'] = pd.to_datetime(df['period_id'])
        df['年份'] = df['月份'].apply(lambda x: x.year)
        return df

    def _process_rules(self, df, year):
        """渠道处理优化"""
        rules = self.rules.get(year, {})

        for pattern, replacement in rules.items():
            mask = df['3级渠道'].str.contains(pattern, regex=True)
            df.loc[mask, '3级渠道'] = replacement
        return df

    def process_data(self, df):
        """统一数据处理流程"""
        # 预处理
        df.rename({'channel_name_l1': '1级渠道', 'channel_name_l3': '3级渠道'}, axis=1, inplace=True)

        # 去除渠道为空的行
        df = df.dropna(subset=['3级渠道'])

        df = self._preprocess_columns(
            df,
            num_cols=['数量', '实收金额'],
        )

        # 按年份分组
        group_data_list = []
        for year, group_data in df.groupby('年份'):
            group_data = self._process_rules(group_data, year)
            group_data_list.append(group_data)

        df = pd.concat(group_data_list, ignore_index=True)

        # df = df.dropna(subset=['3级渠道'])
        df = df[df['3级渠道'].isin(self.config.CHANNEL)]
        df['1级渠道'] = df['3级渠道'].map(self.config.CHANNEL_MAPPING)
        # df = df.dropna(subset=['1级渠道'])

        # 渠道处理
        df = df[~df['型号-CRM最新名称'].isna()]
        df = self._map_child_to_parent_sku(df)
        # 数据汇总
        df = df.groupby(['1级渠道','3级渠道','型号-CRM最新名称','月份', 'last_update_time'])[['数量','实收金额']].sum().reset_index(drop = False)
        return df.fillna(0)[self.config.DATA_COLUMNS].rename(columns={'last_update_time': '最后更新时间'})

    def process_all_years(self):
        all_processed_data = []
        
        # raw_data = pd.read_sql_table(self.config.DATA_TABLES['raw_data'], con=self.engine)
        raw_data = pd.read_csv(self.config.DATA_TABLES['raw_data'] + '.csv')

        raw_data = raw_data[raw_data['period_type'] == 'M']

        raw_data = raw_data[raw_data['product_line_code'] == self.config.PRODUCT_LINE_CODE]

        raw_data = raw_data[raw_data['category_name'].isin(self.config.CATEGORY_LIST)]

        results = self.process_data(raw_data)

        # 汇总所有年份的数据
        results = results[results['3级渠道'].isin(self.config.CHANNEL)]
        results['1级渠道'] = results['3级渠道'].map(self.config.CHANNEL_MAPPING)

        # 对属于组合机的父件进行数量和金额调整
        grouping_cols = ['月份', '1级渠道', '3级渠道', '型号-CRM最新名称', '最后更新时间']
        aggregated_results = results.groupby(grouping_cols, as_index=False)[['数量', '实收金额']].sum()

        # 对属于组合机的父件进行数量和金额调整
        combo_parents = list(self.combo_rules.keys())
        combo_mask = aggregated_results['型号-CRM最新名称'].isin(combo_parents)

        # 使用 .loc 进行高效的切片赋值
        if combo_mask.any():
            aggregated_results.loc[combo_mask, '数量'] = (aggregated_results.loc[combo_mask, '数量'] / 2).round().astype(int)
            aggregated_results.loc[combo_mask, '实收金额'] /= 2

        return aggregated_results.reset_index(drop = True)

    def filter_current_month_data(self, df, target_month):
        # current_date = datetime.now()

        current_date = (datetime.strptime(target_month, '%Y-%m-%d').replace(day=1)  - timedelta(days=1)).replace(day=1)

        current_year = current_date.year
        current_month = current_date.month

        df['月份'] = pd.to_datetime(df['月份'])
        current_month_data = df[(df['月份'].dt.year == current_year) & (df['月份'].dt.month == current_month)]
        
        if len(current_month_data) == 0:
            last_ym_series = pd.to_datetime(df['最后更新时间']).dt.strftime('%Y-%m')
            last_ym = last_ym_series.sort_values().unique()[-1]
            current_month_data = df[df['月份'] == last_ym]

        return current_month_data

    def update_current_month_data(self, current_month_df):
        current_month_df['最后更新时间'] = pd.to_datetime(current_month_df['最后更新时间'])
        current_month_df['已过天数'] = current_month_df['最后更新时间'].dt.day
        current_month_df['本月天数'] = current_month_df['最后更新时间'].dt.days_in_month
        current_month_df['更新数量'] = (current_month_df['数量'].clip(lower=0) / current_month_df['已过天数'] * current_month_df['本月天数']).round().astype(int)
        current_month_df['当月累计销量'] = current_month_df['数量']
        pass

    def get_begin_inv_data(self):
        # df = pd.read_sql_table(self.config.DATA_TABLES['raw_data'], con=self.engine)
        df = pd.read_csv(self.config.DATA_TABLES['raw_data'] + '.csv')
        df = df[df['period_type'] == 'M']

        df = df[df['product_line_code'] == self.config.PRODUCT_LINE_CODE]

        df = df[df['category_name'].isin(self.config.CATEGORY_LIST)]

        df['period_id'] = pd.to_datetime(df['period_id'])
        # df['product_mode_code'] = df['product_mode_code'].str.replace(r'[（(].*?[）)]', '', regex=True)
        df['product_mode_code'] = df['product_mode_code']
        # 去除渠道为空的行
        df = df.dropna(subset=['channel_name_l3'])
        final_df = df[['period_id', 'product_mode_code', 'channel_name_l3', 'begin_plan_inv_qty']]
        rename_dict = {
            'period_id': '月份',
            'product_mode_code': '型号',
            'channel_name_l3': '3级渠道',
            'begin_plan_inv_qty': '期初库存',
        }
        
        return final_df.rename(columns=rename_dict).drop_duplicates(subset=['月份', '型号', '3级渠道'])

class DailySalesProcessor:
    """
    处理月中生成的日销报表，通过流速法预估当月全量数据。
    只负责计算和输出预估数量，不涉及价格或金额的计算
    """
    def __init__(self, config):
        self.config = config
        self.engine = create_engine(self.config.ENGINE_URL)
        # 映射关系-sheet
        self.channel_mapping_rules = {
            '抖音分销': '抖音分销',
            '抖音自营零售-大官旗': '抖音', #修改映射
            '抖音自营零售-品旗': '抖音', #修改映射
            '京东POP-大官旗': '京东POP大官旗',
            '京东POP-分销': '京东POP分销',
            '京东POP-品旗': '京东POP',
            '京东主站': '京东自营',
            '拼多多分销': '拼多多分销',
            '拼多多自营零售-大官旗': '拼多多直营',
            '拼多多自营零售-品旗': '拼多多直营',
            '淘系分销': '淘系分销',
            '淘系自营零售-大官旗': '天猫大官旗',
            '淘系自营零售-品旗': '淘系直营',
            '唯品会': '会员商城',
            'TCL微商城':'会员商城',
            '京东POP-FCS+': '京东POP',
        }

    def process_daily_sales(self, current_month_data, fcst_results, sg_results, price_data, rebate_data, child_to_parent_map=None,combo_rules=None):
        """
        核心处理函数：读取、解析、转换和预估月中销售数据。
        """
        try:
            df = current_month_data[current_month_data['数量'] > 0].copy()
            if df.empty: return pd.DataFrame(), pd.DataFrame()

            df['最后更新时间'] = pd.to_datetime(df['最后更新时间'])
            df['已过天数'] = df['最后更新时间'].dt.day - 1
            df['本月天数'] = df['最后更新时间'].dt.days_in_month

            # 判定条件：月份间隔超过一个月
            month_diff = (df['最后更新时间'].dt.year - df['月份'].dt.year) * 12 + \
                    (df['最后更新时间'].dt.month - df['月份'].dt.month)
            mask = (month_diff >= 1)
            # 月份间隔超过一个月则不做计算
            df.loc[mask, '已过天数'] = df.loc[mask, '月份'].dt.days_in_month
            df.loc[mask, '本月天数'] = df.loc[mask, '月份'].dt.days_in_month
            
            # 1. 流速法计算推算销量
            df['更新数量'] = (df['数量'].clip(lower=0) / df['已过天数'] * df['本月天数']).round().astype(int)
            # 2. 保留原始累计销量
            df['当月累计销量'] = df['数量']
            # df['型号-CRM最新名称'] = df['型号-CRM最新名称'].str.replace(r'[（(].*?[）)]', '', regex=True)
            df['型号-CRM最新名称'] = df['型号-CRM最新名称']

            # 3. 组合机名称映射
            if child_to_parent_map:
                df['型号-CRM最新名称'] = df['型号-CRM最新名称'].map(child_to_parent_map).fillna(df['型号-CRM最新名称'])

            # 4. 渠道映射和价格合并
            df.dropna(subset=['3级渠道'], inplace=True)
            df = df[df['3级渠道'].isin(self.config.CHANNEL)]
            if df.empty: return pd.DataFrame()

            # 4.1. 筛选出当月的计划价格
            report_month_start = df['月份'].iloc[0]

            current_month_prices = price_data[price_data['月份'] == report_month_start].copy()
            current_month_prices = current_month_prices.rename(columns={'型号': '型号-CRM最新名称'})

            # 4.2. 将计划价格合并到预估数据中
            df = pd.merge(
                df[['型号-CRM最新名称', '3级渠道', '更新数量', '当月累计销量']],
                current_month_prices[['型号-CRM最新名称', 'avg_price']],
                on='型号-CRM最新名称',
                how='left'
            ).rename(columns={'更新数量': '数量'})
            df['avg_price'].fillna(0, inplace=True)

            df = pd.merge(
                df,
                fcst_results,
                on=['型号-CRM最新名称', '3级渠道'],
                how='left'
            )

            df = pd.merge(
                df,
                sg_results,
                on=['型号-CRM最新名称', '3级渠道'],
                how='left'
            )

            # 按优先级填充
            df['手工预测'] = df['手工预测'].fillna(df['模型预测']).fillna(df['数量'])
            df['模型预测'] = df['模型预测'].fillna(df['手工预测']).fillna(df['数量'])

            # 加权计算
            weights = [0.15, 0.25, 0.6]
            df['数量'] = df['手工预测'] * weights[0] + df['模型预测'] * weights[1] + df['数量'] * weights[2]
            df = df.drop(['手工预测', '模型预测'], axis=1)
            df['数量'] = df['数量'].round().astype(int)

            # 4.3. 应用渠道返点
            if rebate_data is not None and not rebate_data.empty:
                df = pd.merge(df, rebate_data, on=['3级渠道'], how='left')
                df['零售扣点'].fillna(0, inplace=True)
                df['avg_price'] = df['avg_price'] * (1 - df['零售扣点'])

            # 5. 构建最终DataFrame，确保包含所有必要的列
            df['月份'] = pd.to_datetime(report_month_start)
            df['1级渠道'] = df['3级渠道'].map(self.config.CHANNEL_MAPPING)
            # 计算实收金额以保持数据完整性
            df['实收金额'] = df['数量'] * df['avg_price']

            # 6. 先聚合，得到以父件为单位的总量
            grouping_cols = ['月份', '1级渠道', '3级渠道', '型号-CRM最新名称']
            # 聚合时，同时聚合推算数量和累计销量
            final_df = df.groupby(grouping_cols, as_index=False).agg({
                '数量': 'sum',
                '实收金额': 'sum',
                '当月累计销量': 'sum'
            })

            # 7. 组合机逻辑 - 数量调整
            if combo_rules and not final_df.empty:
                combo_parents = list(combo_rules.keys())
                combo_mask = final_df['型号-CRM最新名称'].isin(combo_parents)
                if combo_mask.any():
                    final_df.loc[combo_mask, '数量'] /= 2
                    final_df.loc[combo_mask, '实收金额'] /= 2

            # 8. 整理并返回，确保列顺序与 historical_sales_data 一致
            # 第一个DataFrame：推算数据，用于合并历史
            estimated_df = final_df[['月份', '1级渠道', '3级渠道', '型号-CRM最新名称', '数量', '实收金额']]
            # 第二个DataFrame：累计数据，用于详情页
            cumulative_df = final_df[['3级渠道', '型号-CRM最新名称', '当月累计销量']]

            print(f"月中报表处理完成，成功生成 {len(final_df)} 条带价预估数据。")
            return estimated_df, cumulative_df
        except Exception as e:
            print(f"处理月中销售报告时发生严重错误: {e}")
            return pd.DataFrame(), pd.DataFrame()

class SKUDataProcessor:
    def __init__(self, config):
        self.config = config
        self.engine = create_engine(self.config.ENGINE_URL)
        self.combo_rules = {
        'GH200T10-W': ['G100T10-W', 'H100T10-W'],
        'GH200T10-S': ['G100T10-S', 'H100T10-S'],
        'GH200T10H-BIS': ['G100T10H-BIS', 'H100T10H-BIS'],
        'GH200T10H-BIW': ['G100T10H-BIW', 'H100T10H-BIW']
        }
        self.combo_parents = list(self.combo_rules.keys())

        # self.master_rules = {
        #     "拼多多大官旗": "拼多多直营",
        #     # "拼多多": "拼多多直营",
        #     "拼多多品旗": "拼多多直营",
        # }

    def load_master_data(self , target_month):
        """加载主数据"""

        # sql = f"SELECT * FROM {self.config.DATA_TABLES['master_data']}"
        # master_data = pd.read_sql(sql, con=self.engine)

        # master_data = pd.read_sql_table(self.config.DATA_TABLES['master_data'], con=self.engine)
        master_data = pd.read_csv(self.config.DATA_TABLES['master_data'] + '.csv')
        # master_data = pd.read_excel(self.config.DATA_TABLES['master_data'] + '.xlsx')

        master_data = master_data[master_data['product_line_code'] == self.config.PRODUCT_LINE_CODE]

        master_data = master_data[master_data['category_name'].isin(self.config.CATEGORY_LIST)]

        master_data = master_data[master_data['version_number'].isin(self.config.PRODUCT_VERSION_LIST)]

        
        # master_data['channel_name_l3'] = master_data['channel_name_l3'].replace(self.master_rules)

        target_month = pd.to_datetime(target_month)
        # 核心逻辑实现
        master_data['月份'] = master_data['expected_prod_time'].apply(parse_flexible_date)

        # 向量化操作：日期+1月，并处理越界情况
        new_dates = master_data['月份'] + pd.DateOffset(months=0)
        master_data['月份'] = new_dates.mask(new_dates < target_month, target_month).fillna(target_month)

        # 格式化输出
        master_data['月份'] = master_data['月份'].dt.strftime('%Y-%m-%d')
        # master_data = master_data.query('是否做计销 == "Y"').reset_index(drop=True)

        # 文本列处理
        # master_data['型号-CRM最新名称'] = master_data['product_mode_code'].str.replace(r'[（(].*?[）)]', '', regex=True)
        master_data['型号-CRM最新名称'] = master_data['product_mode_code']
        
        # 渠道状态填充商品状态
        mask = master_data['channel_status'].notna()
        master_data.loc[mask, 'product_status'] = master_data.loc[mask, 'channel_status']

        return master_data

class PlanningPrice:
    def __init__(self, config):
        self.config = config
        self.engine = create_engine(self.config.ENGINE_URL)

        # self.rebate_rules = {
        #     "拼多多大官旗": "拼多多直营",
        #     # "拼多多": "拼多多直营",
        #     "拼多多品旗": "拼多多直营",
        # }

    @staticmethod
    def _process_column(col):
        top = str(col[0]).strip()
        bottom = str(col[1]).strip()
        if re.match(r'\d+月', top):
            month = re.search(r'(\d+)月', top).group(1)
            return f"{month}月_{bottom}" if bottom else f"{month}月"
        return top if top != 'nan' else bottom

    def process_price_data(self):
        # 读取数据
        price_keywords = ['daily_price_n', 'min_price_n']
        
        # sql = f"SELECT * FROM {self.config.DATA_TABLES['price_data']}"
        # df = pd.read_sql(sql, con=self.engine)

        # df = pd.read_sql_table(self.config.DATA_TABLES['price_data'], con=self.engine)
        # with self.engine.connect() as conn:
        #     df = pd.read_sql_table(
        #         self.config.DATA_TABLES['price_data'],
        #         con=conn
        #     )
        df = pd.read_csv(self.config.DATA_TABLES['price_data'] + '.csv')
        # df = pd.read_excel(self.config.DATA_TABLES['price_data'] + '.xlsx')

        df['period_id'] = pd.to_datetime(df['period_id'])

        current_month = pd.to_datetime(self.config.DATE_SETTINGS) - pd.DateOffset(months=1)

        df = df[df['product_line_code'] == self.config.PRODUCT_LINE_CODE]

        df = df[df['category_name'].isin(self.config.CATEGORY_LIST)]

        df = df[df['version_number'].isin(self.config.PRICE_VERSION_LIST)]

        if not df[df['period_id'] == current_month].empty:
            df = df[df['period_id'] == current_month]

        # 处理复合列名
        # df['型号'] = df['product_mode_code'].str.replace(r'[（(].*?[）)]', '', regex=True)
        df['型号'] = df['product_mode_code']
        
        # 预留大单机相关列
        big_supply_col = 'big_supply_price'
        # big_supply_prices = df.drop_duplicates(subset=['型号'])[['型号', big_supply_col]]
        big_supply_prices = df[['型号', big_supply_col]]

        # 筛选价格相关列
        price_cols = [c for c in df.columns
                      if any(k in c for k in price_keywords) and c != '型号']
                
        df = df[['period_id', '型号'] + price_cols]

        # 添加 n+7 月数据
        n7_data = df[['min_price_n6', 'daily_price_n6']].copy()
        n7_data = n7_data.rename(columns={'min_price_n6': 'min_price_n7', 'daily_price_n6': 'daily_price_n7'})
        df = pd.concat([df, n7_data], axis=1)

        # 数据重塑
        melted = df.melt(id_vars=['period_id', '型号'], var_name='temp', value_name='价格')
        split = melted['temp'].str.split('_price_', n=1, expand=True)
        melted['period_id'] = pd.to_datetime(melted['period_id'])
        # pandas 2.x：split 列多为 StringDtype，不能写回 int；月份偏移单独算
        month_offsets = split.iloc[:, 1].map(
            lambda x: 0 if (x is None or (isinstance(x, float) and pd.isna(x))) else (0 if str(x)[-1] == 'n' else int(str(x)[-1]))
        )

        melted['月份'] = melted['period_id'] + month_offsets.map(lambda x: pd.DateOffset(months=int(x)))
        
        t_map = {'min': '最低售价', 'daily': '日销价'}
        melted['价格类型'] = split[0].apply(lambda x: t_map[x] if x is not None else None)
        melted['价格类型'] = melted['价格类型'].fillna('统一价格')
        
        # 将空值全部填充为0
        melted['价格'] = melted['价格'].fillna(0)

        result = melted.pivot_table(
            index=['型号', '月份'],
            columns='价格类型',
            values='价格',
            aggfunc='first'
        ).reset_index().rename_axis(None, axis=1)

        # 互相填充缺失值
        result[['日销价', '最低售价']] = result[['日销价', '最低售价']].replace(0, np.nan)
        result['日销价'] = result['日销价'].fillna(result['最低售价'])
        result['最低售价'] = result['最低售价'].fillna(result['日销价'])

        # 计算平均价格
        result['avg_price'] = result['最低售价'].combine_first(result['日销价']).fillna(0)

        # 合并大单机出货价
        final_df = pd.merge(
            result,
            big_supply_prices,
            on=['型号'],
            how='left'
        ).rename(columns={big_supply_col: '大单机出货价'})
        
        final_df[['日销价', '最低售价', 'avg_price']] = final_df[['日销价', '最低售价', 'avg_price']].astype('float64')

        return final_df

    def process_rebate_date(self):
        filter_cols = ['channel_name_l2', 'channel_name_l3', \
                       'retail_rebate_rate', 'fee_rebate_rate', 'income_rebate_rate', \
                        'big_retail_rebate_rate', 'big_fee_rebate_rate', 'big_income_rebate_rate']
        rename_cols = ['渠道', '3级渠道', '零售扣点', '费用扣点', '收入扣点', '大单机零售扣点', '大单机费用扣点', '大单机收入扣点']
        rename_dict = dict(zip(filter_cols, rename_cols))
        # df = pd.read_sql_table(self.config.DATA_TABLES['rebate_data'], con=self.engine)
        df = pd.read_csv(self.config.DATA_TABLES['rebate_data'] + '.csv')
        # df = pd.read_excel(self.config.DATA_TABLES['rebate_data'] + '.xlsx')

        df = df[df['product_line_code'] == self.config.PRODUCT_LINE_CODE]

        df = df[df['category_name'].isin(self.config.CATEGORY_LIST)]

        # mask = df['channel_name_l3'] == '京东自营'
        # df.loc[mask, ['retail_rebate_rate', 'fee_rebate_rate', 'income_rebate_rate']] = df.loc[mask, ['big_retail_rebate_rate', 'big_fee_rebate_rate', 'big_income_rebate_rate']].values

        # df['channel_name_l3'] = df['channel_name_l3'].replace(self.rebate_rules)

        return df[filter_cols].rename(columns=rename_dict).drop_duplicates().reset_index().iloc[:, 1:]


class DSI_Processor:
    def __init__(self, config):
        self.config = config
        self.engine = create_engine(self.config.ENGINE_URL)

    def load_dsi_data(self):
        # df = pd.read_sql_table(self.config.DATA_TABLES['dsi_data'], con=self.engine)
        df = pd.read_csv(self.config.DATA_TABLES['dsi_data'] + '.csv')
        # df = pd.read_excel(self.config.DATA_TABLES['dsi_data'] + '.xlsx')

        df = df[df['product_line_code'] == self.config.PRODUCT_LINE_CODE]

        # df = df[df['category_name'].isin(self.config.CATEGORY_LIST)]

        df['period_month'] = pd.to_datetime(df['period_month'])
        # df['product_mode_code'] = df['product_mode_code'].str.replace(r'[（(].*?[）)]', '', regex=True)
        df['product_mode_code'] = df['product_mode_code']
        final_df = df[['period_month', 'product_mode_code', 'channel_name_l3', 'sell_price']]
        rename_dict = {
            'period_month': '月份',
            'product_mode_code': '型号',
            'channel_name_l3': '3级渠道',
            'sell_price': '出货价',
        }
        return final_df.rename(columns=rename_dict)
    

class FCST_Results:
    def __init__(self, config):
        self.config = config
        self.engine = create_engine(self.config.ENGINE_URL)

    def load_fcst_results(self):
        # df_fcst = pd.read_sql_table(self.config.DATA_TABLES['fcst_result'], con=self.engine)
        df_fcst = pd.read_csv(self.config.DATA_TABLES['fcst_result'] + '.csv')
        # df_fcst = pd.read_excel(self.config.DATA_TABLES['fcst_result'] + '.xlsx')

        mask = ~df_fcst['fcst_no'].str.startswith('SGTZ')
        mask_sgtz = df_fcst['fcst_no'].str.startswith('SGTZ')

        df_fcst_raw = df_fcst[mask]
        df_fcst_sgtz = df_fcst[mask_sgtz]

        category_list = self.config.CATEGORY_LIST
        results = []
        sg_results = []
        for category in category_list:
            df = df_fcst_raw[df_fcst_raw['category_name'] == category]
            version_sorted = sorted(df['fcst_no'].unique())
            if len(version_sorted) == 0:
                df_latest = df.copy()
            else:
                latest_version = version_sorted[-1]
                df_latest = df[df['fcst_no'] == latest_version]
            
            results.append(df_latest)
            
            df_sg = df_fcst_sgtz[df_fcst_sgtz['category_name'] == category]
            version_sorted_sg = sorted(df_sg['fcst_no'].unique())
            if len(version_sorted_sg) == 0:
                df_latest_sg = df_sg.copy()
            else:
                latest_version_sg = version_sorted_sg[-1]
                df_latest_sg = df_sg[df_sg['fcst_no'] == latest_version_sg]
            sg_results.append(df_latest_sg)

        df_result = pd.concat(results, ignore_index=True)
        df_result_sg = pd.concat(sg_results, ignore_index=True)

        # 只获取 N+1月 预测结果
        current_month = (datetime.strptime(self.config.DATE_SETTINGS, '%Y-%m-%d').replace(day=1)  - timedelta(days=1)).replace(day=1)
        last_month = (current_month.replace()  - timedelta(days=1)).replace(day=1).strftime('%Y-%m')
        # fcst_period = df_result['fcst_period'].unique()[0]
        # fcst_period_sg = df_result_sg['fcst_period'].unique()[0]
        # latest_fcst_date = datetime.strptime(fcst_period, "%Y-%m")
        # latest_fcst_date_sg = datetime.strptime(fcst_period_sg, "%Y-%m")

        df_result= df_result[df_result['fcst_period'] == last_month]
        df_result_sg = df_result_sg[df_result_sg['fcst_period'] == last_month]

        qty_cols_k = ['retail_qty_n1']
        qty_cols_v = [1]
        qty_cols_dict = dict(zip(qty_cols_k, qty_cols_v))

        rename_dict = {
            'fcst_period': 'period_id',
            'channel_name': 'channel3',
            'product_mode_name': 'product',
            **qty_cols_dict
        }

        df_result = df_result.rename(columns=rename_dict)
        df_result = df_result[rename_dict.values()]

        df_result_sg = df_result_sg.rename(columns=rename_dict)
        df_result_sg = df_result_sg[rename_dict.values()]

        df_result_melt = df_result.melt(
            id_vars=['period_id', 'channel3', 'product'],
            var_name='month',    # 新列：存放原来的列名
            value_name='y_pred'   # 新列：存放原来的值
        )

        df_result_melt_sg = df_result_sg.melt(
            id_vars=['period_id', 'channel3', 'product'],
            var_name='month',    # 新列：存放原来的列名
            value_name='y_pred'   # 新列：存放原来的值
        )

        # df_result_melt['channel1'] = df_result_melt['channel3'].map(self.config.CHANNEL_MAPPING)
        # mask_chn1 = (df_result_melt['channel1'].isnull()) & (df_result_melt['channel3'] == '拼多多')
        # df_result_melt.loc[mask_chn1, 'channel1'] = '拼多多'

        # df_result_melt_sg['channel1'] = df_result_melt_sg['channel3'].map(self.config.CHANNEL_MAPPING)
        # mask_chn1_sg = (df_result_melt_sg['channel1'].isnull()) & (df_result_melt_sg['channel3'] == '拼多多')
        # df_result_melt_sg.loc[mask_chn1_sg, 'channel1'] = '拼多多'
        

        # df_result_melt['period_id'] = pd.to_datetime(df_result_melt['period_id'])
        # df_result_melt['date'] = [d + DateOffset(months=m) for d, m in zip(df_result_melt['period_id'], df_result_melt['month'])]

        # df_result_melt_sg['period_id'] = pd.to_datetime(df_result_melt_sg['period_id'])
        # df_result_melt_sg['date'] = [d + DateOffset(months=m) for d, m in zip(df_result_melt_sg['period_id'], df_result_melt_sg['month'])]

        # df_final = df_result_melt[['date', 'channel1', 'channel3', 'product', 'y_pred']]
        # df_final_sg = df_result_melt_sg[['date', 'channel1', 'channel3', 'product', 'y_pred']]
        df_final = df_result_melt[['channel3', 'product', 'y_pred']]
        df_final_sg = df_result_melt_sg[['channel3', 'product', 'y_pred']]

        df_final = df_final.rename(columns = {
            # 'date': '月份',
            # 'channel1': '1级渠道',
            'channel3': '3级渠道',
            'product': '型号-CRM最新名称',
            'y_pred': '模型预测'
        })

        df_final_sg = df_final_sg.rename(columns = {
            # 'date': '月份',
            # 'channel1': '1级渠道',
            'channel3': '3级渠道',
            'product': '型号-CRM最新名称',
            'y_pred': '手工预测'
        })

        return df_final, df_final_sg
