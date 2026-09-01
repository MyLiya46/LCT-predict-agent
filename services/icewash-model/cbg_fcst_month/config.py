# -*- coding: utf-8 -*-
"""
Created on Tue Mar 18 14:29:49 2025

@author: Dylan
"""
from datetime import date, timedelta
from pathlib import Path


class Config:
    # 包目录 / 上级「冰洗预测模型」目录（本地 CSV 在 ../data，与 cwd 无关）
    _PKG_DIR = Path(__file__).resolve().parent
    _PROJECT_DIR = _PKG_DIR.parent
    _DATA_DIR = _PROJECT_DIR / 'data'

    # LGBM 模型落盘目录（品类_系列_训练截止月-N{1~7}，如 冰箱_L_2026-07-N1.txt）
    MODEL_FILE_DIR = str(_PKG_DIR / 'model_file')
    # 接口每次请求的运行日志目录（按请求时间戳命名 .txt）— 与 data 同级：冰洗预测模型/log
    LOG_DIR = str(_PROJECT_DIR / 'log')
    # 产线编码
    # PRODUCT_LINE_CODE = 'PL003'

    # 回调函数配置
    CALLBACK_BASE_URL = 'http://localhost:8001'
    # CALLBACK_BASE_URL = 'https://api-gw-uat.tcl.com'
    ORGANIZATION_ID = '18'

    # MySQL数据库配置
    HOST = '10.126.124.44'
    PORT = '4000'
    USERNAME = 'bigata_cbg_fcst_rw'
    PASSWORD = 'Bcny_3fdd'
    DB_NAME = 'cbg_fcst'
    ENGINE_URL = f'mysql+pymysql://{USERNAME}:{PASSWORD}@{HOST}:{PORT}/{DB_NAME}'
    # DATA_TABLES = {
    #     'raw_data': 'ads_cbg_rt_fcst_retail_stat',
    #     'master_data': 'tof_fcst_product_info',
    #     'price_data':'tof_fcst_product_plan_price',
    #     'rebate_data': 'dwd_cbg_sl_tb_fcst_channel_rebate_detail',
    #     'dsi_data': 'dwd_cbg_sl_tb_fcst_dsi_price_detail',
    #     'result': 'ads_cbg_rt_fcst_result_month',
    #     # 存放预测结果数据，用于测算模型准确率
    #     'test_result': 'test_result_month',

    #     # 预测结果数据
    #     'fcst_result': 'dwd_cbg_rt_fcst_result_month_detail',

    #     # 中怡康数据补充
    #     'zyk_data': 'dwd_cbg_bd_cmp_zyk_detail',
    # }

    DATA_TABLES = {
        'raw_data': str(_DATA_DIR / 'ads_cbg_rt_fcst_retail_stat'),
        'master_data': str(_DATA_DIR / 'tof_fcst_product_info'),
        'price_data': str(_DATA_DIR / 'tof_fcst_product_plan_price'),
        'rebate_data': str(_DATA_DIR / 'dwd_cbg_sl_tb_fcst_channel_rebate_detail'),
        'dsi_data': str(_DATA_DIR / 'dwd_cbg_sl_tb_fcst_dsi_price_detail'),
        'result': 'ads_cbg_rt_fcst_result_month',

        'test_result': 'test_result_month',
        'fcst_result': str(_DATA_DIR / 'dwd_cbg_rt_fcst_result_month_detail'),

        # 中怡康数据补充
        'zyk_data': str(_DATA_DIR / 'dwd_cbg_bd_cmp_zyk_detail'),
    }

    OUTPUT_FORMAT = 'excel'

    OUTPUT_TEST_FORMAT = 'excel'

    # Predictability Check Params
    PREDICTABILITY_WINDOW_MONTHS = 3  # 有效历史窗口月数
    PREDICTABILITY_MIN_SALES = 10     # 可预测性判断阈值

    # 预测月份数
    FORECAST_MONTHS = 7

    # 新老品预测优化配置
    NEW_OLD_TRANSITION_DEFAULT_RATIO = 0.2
    ENABLE_MULTI_GEN_CHAIN = True

    # 核心业务参数
    # DATE_SETTINGS = '2025-10-01'
    DATE_SETTINGS = str((date.today().replace(day=1) + timedelta(days=32)).replace(day=1))

    # 数据预处理配置
    DATA_COLUMNS = [
        '月份', '1级渠道', '3级渠道',
        '型号-CRM最新名称', '数量',
        '实收金额',
        'last_update_time',
    ]

    # 渠道映射关系
    CHANNEL_MAPPING = {
           "抖音分销": "抖音",
           "抖音": "抖音",
           "京东POP大官旗": "京东POP",
           "京东POP分销": "京东POP",
           "京东POP": "京东POP",
        #    "拼多多直营": "拼多多",
           "拼多多分销": "拼多多",
           "淘系分销": "淘系",
           "淘系直营": "淘系",
           "天猫大官旗": "淘系",
           "京东自营": "京东自营",
           "会员商城":"会员商城",
           # 新添加映射关系
           "快手": "快手",
        #    "拼多多": "拼多多",
           "拼多多大官旗": "拼多多",
           "拼多多品旗": "拼多多"
           }

    # Model Params
    # CHANNEL = ['淘系直营','天猫大官旗','淘系分销','京东自营','拼多多直营','拼多多分销',\
    #            '抖音分销','抖音','会员商城','京东POP大官旗','京东POP分销','京东POP','快手']
    
    CHANNEL = ['淘系直营','天猫大官旗','淘系分销','京东自营','拼多多分销','拼多多大官旗','拼多多品旗', \
               '抖音分销','抖音','会员商城','京东POP大官旗','京东POP分销','京东POP', '快手']

    MODEL_PARAMS = {
        'objective': 'regression_l1',
        'metric': 'mape',
        'n_estimators': 800,
        'learning_rate': 0.08,
        'max_depth': 4,
        'num_leaves': 5,
        'min_data_in_leaf': 3,
        'feature_fraction': 0.9,
        'bagging_fraction': 0.9,
        'bagging_freq': 5,
        'reg_alpha': 0.9,
        'reg_lambda': 0.1,
        'force_col_wise': True,
        'seed': 66,
    }

    SERIES_CONFIG = {
        '冰箱V': {
            'MODEL_FEATURES': [
                '3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'month', 'type',
                'qty_lag1', 'qty_lag2', 'qty_lag3', 'qty_lag4', 'qty_lag5', 'qty_lag6',
                'qty_lag9', 'qty_lag12',
                'qty_lag1_3m_cv', 'qty_lag1_3m_min', 'qty_lag1_3m_max',
                'qty_lag1_6m_mean', 'qty_lag1_6m_min', 'qty_lag1_6m_kurt', 'qty_lag1_6m_max',
                'qty_lag1_12m_max', 'qty_lag1_12m_mean', 'qty_lag1_12m_std', 'qty_lag1_12m_kurt',
                'volume', 'lag1_diff1',
                'avg_price', 'share_6m_mean',

            ],
            'CATEGORICAL_FEATURES': ['3级渠道', '型号-CRM最新名称', 'is_onsale',
                                     'is_spring_festival', 'type', 'month', ],
            'WEIGHTS': {
                'lag12_weight': 0,
                '3m_mean_weight': 0.1,
                'model_weight': 0.9,
                'model_bias_weight': 0,
            },
        },
        '冰箱T': {
            'MODEL_FEATURES': [
                '3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'month',
                'type',
                'qty_lag1', 'qty_lag2', 'qty_lag3', 'qty_lag4', 'qty_lag5', 'qty_lag6',
                'qty_lag9', 'qty_lag12',
                'qty_lag1_3m_max', 'qty_lag1_3m_cv', 'qty_lag1_3m_min',
                'qty_lag1_6m_max', 'qty_lag1_6m_mean', 'qty_lag1_6m_min', 'qty_lag1_6m_kurt',
                'qty_lag1_12m_max', 'qty_lag1_12m_mean', 'qty_lag1_12m_std',
                'lag1_diff1',
                'avg_price', 'price_elasticity',
                'volume', 'share_lag1',
            ],
            'CATEGORICAL_FEATURES': ['3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'type', ],

            'WEIGHTS': {
                'lag12_weight': 0.1,
                '3m_mean_weight': 0.0,
                'model_weight': 0.9,
                'model_bias_weight': 0,
            },
        },
        '冰箱L': {
            'MODEL_FEATURES': [
                '3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'month', 'type',
                'qty_lag1', 'qty_lag2', 'qty_lag3', 'qty_lag6',
                'qty_lag7', 'qty_lag8', 'qty_lag9', 'qty_lag10', 'qty_lag11', 'qty_lag12',
                'qty_lag1_3m_max', 'qty_lag1_3m_min', 'qty_lag1_3m_cv',
                'qty_lag1_6m_mean', 'qty_lag1_6m_max', 'qty_lag1_6m_std',
                'qty_lag1_6m_skew', 'qty_lag1_6m_min',
                'qty_lag1_12m_skew',
                'total_series_lag1_qty',
                'avg_price', 'lag1_diff1',
                'volume', 'share_3m_mean', 'share_lag1',
                # 'share_lag2','share_3m_mean','share_6m_mean'
            ],
            'CATEGORICAL_FEATURES': ['3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'type'],

            'WEIGHTS': {
                'lag12_weight': 0,
                '3m_mean_weight': 0.1,
                'model_weight': 0.9,
                'model_bias_weight': 0.9,
            },
        },
        '冰箱S': {
            'MODEL_FEATURES': [
                '3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'year', 'month', 'type',
                'qty_lag1', 'qty_lag2', 'qty_lag3', 'qty_lag6', 'qty_lag7', 'qty_lag9', 'qty_lag12',
                'qty_lag4', 'qty_lag5',
                'qty_lag1_3m_mean', 'qty_lag1_3m_min',
                'qty_lag1_6m_cv', 'qty_lag1_6m_kurt', 'qty_lag1_6m_min',
                'qty_lag1_12m_skew',
                'price_change', 'avg_price',
                'share_3m_mean',
            ],
            'CATEGORICAL_FEATURES': ['3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'type', ],
            'WEIGHTS': {
                'lag12_weight': 0.1,
                '3m_mean_weight': 0,
                'model_weight': 0.9,
                'model_bias_weight': 0,
            },
        },
        '洗衣机V': {
            'MODEL_FEATURES': [
                '3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'month',
                'qty_lag1', 'qty_lag2', 'qty_lag3', 'qty_lag6',
                'qty_lag9', 'qty_lag12',
                'qty_lag1_3m_mean', 'qty_lag1_3m_std', 'qty_lag1_3m_max', 'qty_lag1_3m_min',
                'qty_lag1_6m_mean', 'qty_lag1_6m_skew', 'qty_lag1_6m_max', 'qty_lag1_6m_cv',
                'qty_lag1_12m_skew', 'qty_lag1_12m_cv', 'lag1_diff1',
                'avg_price', 'price_lag1', 'share_3m_mean',
            ],
            'CATEGORICAL_FEATURES': ['3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival'],

            'WEIGHTS': {
                'lag12_weight': 0,
                '3m_mean_weight': 0.1,
                'model_weight': 0.9,
                'model_bias_weight': 0,
            },
        },
        '洗衣机T': {
            'MODEL_FEATURES': [
                '3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'month', 'type',
                'qty_lag1', 'qty_lag2', 'qty_lag3', 'qty_lag6', 'qty_lag9', 'qty_lag12',
                'qty_lag1_3m_max', 'qty_lag1_3m_min', 'qty_lag1_3m_cv',
                'qty_lag1_6m_cv', 'qty_lag1_6m_mean', 'qty_lag1_6m_skew', 'qty_lag1_6m_max',
                'qty_lag1_12m_skew', 'qty_lag1_12m_cv',
                'avg_price', 'price_lag1', 'lag1_diff1',
                'share_3m_mean',
                'share_lag1', 'share_lag3',
            ],
            'CATEGORICAL_FEATURES': ['3级渠道', '型号-CRM最新名称', 'is_onsale', 'type',
                                     'is_spring_festival', 'month'],

            'WEIGHTS': {
                'lag12_weight': 0,
                '3m_mean_weight': 0.2,
                'model_weight': 0.8,
                'model_bias_weight': 0,
            },
        },
        '洗衣机L': {
            'MODEL_FEATURES': [
                '3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'month', 'type',
                'qty_lag1', 'qty_lag2', 'qty_lag3', 'qty_lag6',
                'qty_lag9', 'qty_lag12',
                'qty_lag1_3m_max', 'qty_lag1_3m_min', 'qty_lag1_3m_mean', 'qty_lag1_3m_std',
                'qty_lag1_6m_mean', 'qty_lag1_6m_skew', 'qty_lag1_6m_max',
                'qty_lag1_12m_skew', 'qty_lag1_12m_cv', 'qty_lag1_12m_max',
                'avg_price', 'price_change', 'lag1_diff1',
                'share_6m_mean'

            ],
            'CATEGORICAL_FEATURES': ['3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'type', ],
            'WEIGHTS': {
                'lag12_weight': 0.0,
                '3m_mean_weight': 0.2,
                'model_weight': 0.8,
                'model_bias_weight': 0,
            },
        },
        '洗衣机Q': {
            'MODEL_FEATURES': [
                '3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'month', 'type',
                'qty_lag1', 'qty_lag2', 'qty_lag3', 'qty_lag4', 'qty_lag6',
                'qty_lag7', 'qty_lag8', 'qty_lag9', 'qty_lag10', 'qty_lag11', 'qty_lag12',
                'qty_lag1_3m_max', 'qty_lag1_3m_min', 'qty_lag1_3m_mean', 'qty_lag1_3m_std',
                'qty_lag1_6m_mean', 'qty_lag1_6m_skew', 'qty_lag1_6m_max',
                'qty_lag1_12m_max', 'qty_lag1_12m_skew',
                'avg_price', 'price_lag1', 'lag1_diff1',
                'volume',
            ],
            'CATEGORICAL_FEATURES': ['3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'type', ],
            'WEIGHTS': {
                'lag12_weight': 0,
                '3m_mean_weight': 0,
                'model_weight': 1,
                'model_bias_weight': 0,
            },
        },
        '洗衣机S': {
            'MODEL_FEATURES': [
                '3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'month', 'type',
                'qty_lag1', 'qty_lag2', 'qty_lag3', 'qty_lag4', 'qty_lag6',
                'qty_lag7', 'qty_lag8', 'qty_lag9', 'qty_lag10', 'qty_lag11', 'qty_lag12',
                'qty_lag1_3m_max', 'qty_lag1_3m_min', 'qty_lag1_3m_mean', 'qty_lag1_3m_std',
                'qty_lag1_6m_mean', 'qty_lag1_6m_skew', 'qty_lag1_6m_max',
                'qty_lag1_12m_max', 'qty_lag1_12m_skew',
                'avg_price', 'price_lag1', 'lag1_diff1',
                'volume',
            ],
            'CATEGORICAL_FEATURES': ['3级渠道', '型号-CRM最新名称', 'is_onsale', 'is_spring_festival', 'type', ],
            'WEIGHTS': {
                'lag12_weight': 0,
                '3m_mean_weight': 0,
                'model_weight': 1,
                'model_bias_weight': 0,
            },
        },
    }
