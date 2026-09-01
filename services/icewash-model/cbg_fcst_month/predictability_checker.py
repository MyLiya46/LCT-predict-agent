# -*- coding: utf-8 -*-
"""
Created on Tue Mar 18 14:30:19 2025

@author: Dylan
"""
import pandas as pd

class PredictabilityChecker:
    def __init__(self, config):
        self.config = config
        
    def _calculate_effective_window(self, target_date):
        """计算有效历史时间窗口"""
        window_start = target_date - pd.DateOffset(months=self.config.PREDICTABILITY_WINDOW_MONTHS)
        window_end = target_date - pd.DateOffset(months=1)
        return window_start, window_end

    def check_predictability(self, sku_data, target_date):
        """执行可预测性判断"""
        # 计算有效时间窗口
        window_start, window_end = self._calculate_effective_window(target_date)
        valid_data = sku_data[(sku_data['月份'] >= window_start) & 
                             (sku_data['月份'] <= window_end)]
        # 计算关键指标
        try:
            qty_lag1_3m_mean = sku_data[sku_data['月份'] == target_date]['qty_lag1_3m_mean'].iloc[0]
            qty_lag12 = sku_data[sku_data['月份'] == target_date]['qty_lag12'].iloc[0]
        except:
            qty_lag1_3m_mean = 0
            qty_lag12 = 0

        # 组合预测值计算
        combined_avg = self._combine_metrics(qty_lag1_3m_mean, qty_lag12)
        if len(sku_data) <= self.config.PREDICTABILITY_WINDOW_MONTHS:
            return False, combined_avg
        
        # 判断条件
        # 如果近3月非零均值小于最小销量，则直接使用滑窗平均值 combined_avg
        if qty_lag1_3m_mean < self.config.PREDICTABILITY_MIN_SALES:
            return False, combined_avg
        # if (valid_data['数量'] == 0).any():
        #     print(f"存在历史销量为0,{len(valid_data[valid_data['数量'] == 0])}")
        #     return False, combined_avg
        return True, None

    def _combine_metrics(self, avg, qty_lag12):
        """组合历史指标"""
        if avg <= 0:
            return 0
        elif qty_lag12 > 0:
            return (avg * 3 + qty_lag12) / 4
        return avg