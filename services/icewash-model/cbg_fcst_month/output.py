import openpyxl
import pandas as pd
import numpy as np
from openpyxl.utils.dataframe import dataframe_to_rows
from dateutil.relativedelta import relativedelta

from datetime import datetime
from sqlalchemy import text


def create_price_pivot(price_data, forecast_months, results_df):
    """创建价格透视表"""
    # 获取所有需要的SKU-渠道组合
    sku_channel_combinations = results_df[['型号-CRM最新名称', '3级渠道']].drop_duplicates()

    # 为每个预测月份创建价格数据
    price_list = []
    for month in forecast_months:
        # 获取该月份的价格数据
        month_prices = price_data[price_data['月份'].dt.floor('D') == month.floor('D')]

        if month_prices.empty:
            # 如果没有该月份的价格数据，使用0填充
            for _, row in sku_channel_combinations.iterrows():
                price_list.append({
                    '型号-CRM最新名称': row['型号-CRM最新名称'],
                    '3级渠道': row['3级渠道'],
                    '月份': month,
                    'avg_price': 0,
                    '大单机出货价': np.nan,
                })
        else:
            # 为每个SKU-渠道组合分配价格
            for _, row in sku_channel_combinations.iterrows():
                sku_price = month_prices[month_prices['型号'] == row['型号-CRM最新名称']]
                price_val = sku_price['avg_price'].iloc[0] if not sku_price.empty else 0

                big_supply_price = sku_price['大单机出货价'].iloc[0] if not sku_price.empty else np.nan

                price_list.append({
                    '型号-CRM最新名称': row['型号-CRM最新名称'],
                    '3级渠道': row['3级渠道'],
                    '月份': month,
                    'avg_price': price_val,
                    '大单机出货价': big_supply_price,
                })

    price_df = pd.DataFrame(price_list)

    # 创建价格透视表
    price_pivot = price_df.pivot_table(
        index=['型号-CRM最新名称', '3级渠道'],
        columns='月份',
        values='avg_price',
        aggfunc='first',
        fill_value=0
    )

    # 重命名列为月份标签，并添加前缀
    # price_pivot.columns = [f"价格_{col.strftime('%m月')}" for col in price_pivot.columns]
    price_pivot.columns = [f"价格_n月" if i == 0 else f"价格_n{i}月" for i in range(len(price_pivot.columns))]

    return price_pivot


def create_factory_pivot(price_data, forecast_months, results_df):
    """创建出货价透视表"""
    # 获取所有需要的SKU-渠道组合
    sku_channel_combinations = results_df[['型号-CRM最新名称', '3级渠道']].drop_duplicates()

    # 为每个预测月份创建价格数据
    price_list = []
    for month in forecast_months:
        # 获取该月份的价格数据
        month_prices = price_data[price_data['月份'].dt.floor('D') == month.floor('D')]

        if month_prices.empty:
            # 如果没有该月份的价格数据，使用0填充
            for _, row in sku_channel_combinations.iterrows():
                price_list.append({
                    '型号-CRM最新名称': row['型号-CRM最新名称'],
                    '3级渠道': row['3级渠道'],
                    '月份': month,
                    'avg_price': 0,
                    '大单机出货价': 0,
                    '是否大单机': False  # 添加判断列
                })
        else:
            # 为每个SKU-渠道组合分配价格
            for _, row in sku_channel_combinations.iterrows():
                sku_price = month_prices[month_prices['型号'] == row['型号-CRM最新名称']]
                price_val = sku_price['avg_price'].iloc[0] if not sku_price.empty else 0

                big_supply_price = sku_price['大单机出货价'].iloc[0] if not sku_price.empty else np.nan

                avg_price = big_supply_price if pd.notna(big_supply_price) and row['3级渠道'] == '京东自营' else price_val

                price_list.append({
                    '型号-CRM最新名称': row['型号-CRM最新名称'],
                    '3级渠道': row['3级渠道'],
                    '月份': month,
                    'avg_price': avg_price,  # 如果出货价非空则使用出货价
                    '大单机出货价': big_supply_price if pd.notna(big_supply_price) else 0,
                    '是否大单机': pd.notna(big_supply_price)  # 添加判断列
                })

    price_df = pd.DataFrame(price_list)

    # 创建价格透视表
    price_pivot = price_df.pivot_table(
        index=['型号-CRM最新名称', '3级渠道'],
        columns='月份',
        values='avg_price',
        aggfunc='first',
        fill_value=0
    )

    # 重命名列为月份标签，并添加前缀
    price_pivot.columns = [f"最低出货价_n月" if i == 0 else f"最低出货价_n{i}月" for i in range(len(price_pivot.columns))]
    
    # 添加一列判断大单机出货价是否为空
    # 我们取第一个月份的数据作为判断依据
    first_month = forecast_months[0]
    first_month_data = price_df[price_df['月份'] == first_month]
    is_empty_series = first_month_data.groupby(['型号-CRM最新名称', '3级渠道'])['是否大单机'].first()
    
    # 将判断列添加到价格透视表中
    price_pivot['是否大单机'] = is_empty_series

    return price_pivot


def create_quantity_pivot(results_df):
    quantity_pivot = results_df.pivot_table(
        index=['型号-CRM最新名称', '3级渠道'],
        columns='月份',
        values='y_pred',
        aggfunc='first',
        fill_value=0
    )
    # quantity_pivot.columns = [f'零售量_{col.strftime('%m月')}' for col in quantity_pivot.columns]
    quantity_pivot.columns = [f"零售量_n月" if i == 0 else f"零售量_n{i}月" for i in range(len(quantity_pivot.columns))]

    return quantity_pivot


def create_sales_pivot(dsi_data, begin_inv_data, results_df):
    results_df = results_df.rename(columns={'型号-CRM最新名称': '型号'})

    merged_df = pd.merge(results_df, begin_inv_data, on=['型号', '3级渠道', '月份'], how='left')
    merged_df = pd.merge(merged_df, dsi_data, on=['型号', '3级渠道', '月份'], how='left')
    
    # 创建滞后特征
    merged_df = merged_df.sort_values(['型号', '3级渠道', '月份'])
    merged_df['y_pred_n1'] = merged_df.groupby(['型号', '3级渠道'])['y_pred'].shift(-1)
    merged_df['出货价_n1'] = merged_df.groupby(['型号', '3级渠道'])['出货价'].shift(-1)

    merged_df['y_pred_n-1'] = merged_df.groupby(['型号', '3级渠道'])['y_pred'].shift(1)
    merged_df['出货价_n-1'] = merged_df.groupby(['型号', '3级渠道'])['出货价'].shift(1)

    # 1. 首先筛选出目标渠道的数据，避免处理整个DataFrame
    current_month = merged_df['月份'].unique().min()
    
    # N+1 到 N+6月处理
    target_mask1 = ((merged_df['3级渠道'] == '京东自营') & (merged_df['月份'] > current_month))
    target_data1 = merged_df.loc[target_mask1]

    # 2. 在筛选出的数据上执行计算
    # calculation_result = (
    #     target_data['y_pred_n1'] * target_data['出货价_n1'] + 
    #     target_data['y_pred'] - 
    #     target_data['y_pred'] * target_data['出货价']
    # )
    calculation_result1 = (
        target_data1['y_pred_n1'] * target_data1['出货价'] + 
        target_data1['y_pred'] - 
        target_data1['y_pred'] * target_data1['出货价_n-1']
    )

    # 3. 找出计算结果非空的行
    valid_calc_mask1 = calculation_result1.notnull()

    # 4. 组合最终条件：是目标渠道，且计算结果有效
    final_mask1 = target_mask1 & target_mask1.index.isin(calculation_result1[valid_calc_mask1].index)

    # 5. 仅对同时满足两个条件的行进行赋值
    merged_df.loc[final_mask1, 'y_pred'] = calculation_result1[valid_calc_mask1]


    # N月处理
    target_mask2 = ((merged_df['3级渠道'] == '京东自营') & (merged_df['月份'] == current_month))
    target_data2 = merged_df.loc[target_mask2]

    # 2. 在筛选出的数据上执行计算
    calculation_result2 = (
        target_data2['y_pred_n1'] * target_data2['出货价'] + 
        target_data2['y_pred'] - 
        target_data2['期初库存']
    )

    # 3. 找出计算结果非空的行
    valid_calc_mask2 = calculation_result2.notnull()

    # 4. 组合最终条件：是目标渠道，且计算结果有效
    final_mask2 = target_mask2 & target_mask2.index.isin(calculation_result2[valid_calc_mask2].index)

    # 5. 仅对同时满足两个条件的行进行赋值
    merged_df.loc[final_mask2, 'y_pred'] = calculation_result2[valid_calc_mask2]

    
    sales_pivot = merged_df.pivot_table(
        index=['型号', '3级渠道'],
        columns='月份',
        values='y_pred',
        aggfunc='first',
        fill_value=0
    )
    # sales_pivot.columns = [f'销量_{col.strftime('%m月')}' for col in sales_pivot.columns]
    sales_pivot.columns = [f"销量_n月" if i == 0 else f"销量_n{i}月" for i in range(len(sales_pivot.columns))]
    
    return sales_pivot


def save_results(results, engine, output_table, target_month, api_param, format, save_test_data, test_format, test_output_table,
                 detailed_results=None, attribution_factors=None, history_results=None):
    """Persist the formatted result using the horizons actually requested.

    The legacy export schema was hard-coded for N+1..N+7.  A shorter API
    request still produces the base month plus its requested forecast months,
    so indexing the seven-month column list raises before the Excel/PG write
    can happen.  Keep the legacy names, but only map columns present in the
    formatted frame (up to the public 12-month limit).
    """
    def horizon_columns(source_prefix, output_prefix):
        mapped = {}
        for index in range(13):
            source = f'{source_prefix}_n{"月" if index == 0 else str(index) + "月"}'
            if source not in results.columns:
                continue
            target = f'{output_prefix}_n{"" if index == 0 else index}'
            mapped[source] = target
        return mapped

    factory_dict = {
        **horizon_columns('最低出货价', 'min_sell_price'),
    }
    price_dict = {
        **horizon_columns('价格', 'min_retail_price'),
    }
    quantity_dict = {
        **horizon_columns('零售量', 'retail_qty'),
    }
    sales_dict = {
        **horizon_columns('销量', 'sales_qty'),
    }
    
    columns_mapping = {
        '产线编码': 'product_line_code',
        '产线名称': 'product_line_name',
        '品类': 'category_name',
        '3级渠道': 'channel_name_l3',
        '型号-CRM最新名称': 'product_mode_code',
        '定位': 'product_series',
        '状态': 'product_status',
        '零售扣点': 'retail_rebate_rate',
        '费用扣点': 'fee_rebate_rate',
        **factory_dict,
        **price_dict,
        **quantity_dict,
        **sales_dict
    }

    results = results.rename(columns=columns_mapping)

    # 计算统计月份
    current_date = pd.to_datetime(target_month) - pd.DateOffset(months=1)
    results['period_id'] = [current_date] * len(results)

    results['submitter'] = [api_param['reporter']] * len(results)
    results['submit_time'] = [api_param['generateTime']] * len(results)
    results['version_number'] = [api_param['systemForecastNumber']] * len(results)

    try:
        # 获取数据库时间
        with engine.connect() as conn:
            last_update_time = conn.execute(text("SELECT NOW()")).scalar()
    except:
        last_update_time = pd.to_datetime(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    results['last_update_time'] = [last_update_time] * len(results)

    final_cols = ['period_id', *columns_mapping.values(), 'submitter', 'submit_time', 'version_number', 'last_update_time']

    test_preferred = [
        'period_id', 'product_line_code', 'category_name', 'channel_name_l3',
        'product_mode_code', 'product_series', 'min_sell_price_n',
        'min_sell_price_n1', 'retail_qty_n', 'retail_qty_n1',
        'sales_qty_n', 'sales_qty_n1',
    ]
    test_cols = [column for column in test_preferred if column in final_cols]

    final_results = results[final_cols]

    nums = len(final_results)

    # 是否保存测试结果
    if save_test_data:
        final_test_results = results[test_cols]
        test_nums = len(final_test_results)

        if test_format == 'sql':
            try:
                final_test_results.to_sql(
                    name=test_output_table,
                    con=engine,
                    if_exists='append',
                    index=False
                )
                print(f'测试数据保存成功, 共 {test_nums} 条')
            except Exception as e:
                print(f'测试数据保存报错: {e}')

        elif test_format == 'csv':
            try:
                final_test_results.to_csv(f"output_test_{api_param['systemForecastNumber']}.csv", index=False)
                print(f'测试数据保存成功, 共 {test_nums} 条')
            except Exception as e:
                print(f'测试数据保存报错: {e}')
            
        elif test_format == 'excel':
            try:
                final_test_results.to_excel(f"output_test_{api_param['systemForecastNumber']}.xlsx", sheet_name='result', index=False)
                print(f'测试数据保存成功, 共 {test_nums} 条')
            except Exception as e:
                print(f'测试数据保存报错: {e}')

    if format == 'sql':
        try:
            final_results.to_sql(
                name=output_table,
                con=engine,
                if_exists='append',
                index=False
            )
            return {'saved_success': True, 'saved_count': nums, 'message': '数据保存成功'}
        except Exception as e:
            print(f'保存报错: {e}')
            return {'saved_success': False, 'saved_count': nums, 'message': f'数据保存失败: {e}'}

    elif format == 'csv':
        try:
            final_results.to_csv(f"output_{api_param['systemForecastNumber']}.csv", index=False)
            return {'saved_success': True, 'saved_count': nums, 'message': '数据保存成功'}
        except Exception as e:
            print(f'保存报错: {e}')
            return {'saved_success': False, 'saved_count': nums, 'message': f'数据保存失败: {e}'}
        
    elif format == 'excel':
        try:
            from attribution import format_attribution_sheet, build_attribution_mapping_sheet

            out_path = f"output_{api_param['systemForecastNumber']}.xlsx"
            with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
                final_results.to_excel(writer, sheet_name='result', index=False)
                if detailed_results is not None and not getattr(detailed_results, 'empty', True):
                    format_detailed_results(detailed_results).to_excel(
                        writer, sheet_name='预测详情', index=False
                    )
                if history_results is not None and not getattr(history_results, 'empty', True):
                    format_history_results(history_results).to_excel(
                        writer, sheet_name='历史数据', index=False
                    )
                if attribution_factors is not None and not getattr(attribution_factors, 'empty', True):
                    format_attribution_sheet(attribution_factors).to_excel(
                        writer, sheet_name='白盒归因', index=False
                    )
                build_attribution_mapping_sheet().to_excel(
                    writer, sheet_name='归因映射', index=False
                )
            return {'saved_success': True, 'saved_count': nums, 'message': '数据保存成功'}
        except Exception as e:
            print(f'保存报错: {e}')
            return {'saved_success': False, 'saved_count': nums, 'message': f'数据保存失败: {e}'}


def create_three_level_header_output(forecast_results, master_data, price_data, rebate_data, target_month):
    """
    创建三级表头的输出格式 - 整合所有数据处理功能
    """
    # 1. 数据预处理
    results_df = forecast_results.copy()
    results_df['月份'] = pd.to_datetime(results_df['月份'])

    forecast_months = sorted(results_df['月份'].unique())
    month_labels = [month.strftime('%m月') for month in forecast_months]
    print(f"预测月份: {month_labels}")

    # 2. 合并主数据信息
    master_rename_dict = {
            'category_name': '品类',
            'product_type': 'type',
            'product_series': 'series',
            'product_status': 'status',
    }
    master_data = master_data.rename(columns=master_rename_dict)

    master_info = master_data[['型号-CRM最新名称', '品类', 'series', 'status']].drop_duplicates()
    existing_cols = set(results_df.columns)
    master_cols_to_merge = ['型号-CRM最新名称']

    for col in ['品类', 'series', 'status']:
        if col not in existing_cols:
            master_cols_to_merge.append(col)

    if len(master_cols_to_merge) > 1:
        results_df = pd.merge(results_df, master_info[master_cols_to_merge], on='型号-CRM最新名称', how='left')

    # 3. 合并返点信息
    rebate_info = rebate_data[['3级渠道', '零售扣点', '费用扣点']].drop_duplicates()
    results_df = pd.merge(results_df, rebate_info, on='3级渠道', how='left')
    results_df['零售扣点'] = results_df['零售扣点'].fillna(0)
    results_df['费用扣点'] = results_df['费用扣点'].fillna(0)

    # 4. 处理重复列名问题
    column_mapping = {}
    for col in results_df.columns:
        if col.endswith('_x'):
            base_col = col[:-2]
            column_mapping[col] = base_col
            y_col = base_col + '_y'
            if y_col in results_df.columns:
                results_df = results_df.drop(columns=[y_col])
        elif col.endswith('_y'):
            base_col = col[:-2]
            if base_col + '_x' not in results_df.columns:
                column_mapping[col] = base_col

    if column_mapping:
        results_df = results_df.rename(columns=column_mapping)

    # 5. 准备基础信息
    required_columns = ['品类', 'series', 'status', '1级渠道', '3级渠道', '型号-CRM最新名称', '零售扣点', '费用扣点']
    base_info = results_df.groupby(['型号-CRM最新名称', '3级渠道']).first().reset_index()
    base_info_data = base_info[required_columns].rename(columns={'series': '定位','status': '状态'})

    # 6. 创建价格和数量透视表
    price_pivot = create_price_pivot(price_data, forecast_months, results_df)

    quantity_pivot = results_df.pivot_table(
        index=['型号-CRM最新名称', '3级渠道'],
        columns='月份',
        values='y_pred',
        aggfunc='first',
        fill_value=0
    )
    quantity_pivot.columns = [col.strftime('%m月') for col in quantity_pivot.columns]

    # 7. 合并所有数据
    merged_data = pd.merge(base_info_data, price_pivot,
                           left_on=['型号-CRM最新名称', '3级渠道'],
                           right_index=True, how='left')
    merged_data = pd.merge(merged_data, quantity_pivot,
                           left_on=['型号-CRM最新名称', '3级渠道'],
                           right_index=True, how='left')

    # 8. 直接构建三级表头Excel
    merged_data = merged_data.sort_values(by=['1级渠道', '3级渠道']).reset_index(drop=True)

    return build_three_level_header_excel(merged_data, month_labels)


def build_three_level_header_excel(merged_data, month_labels):
    """
    构建三级表头的Excel结构 - 整合数据计算和Excel构建
    """

    # 创建工作簿
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "预测结果"

    # 基础信息列
    base_info_cols = ['品类', '定位', '状态', '1级渠道', '3级渠道', '型号-CRM最新名称', '零售扣点', '费用扣点']
    base_col_count = len(base_info_cols)
    value = 0
    # 指标定义
    indicators = ['最低售价', '零售量', '零售额', '收入量', '收入额']

    # 第1行：派生变量维度名称
    row1_data = [''] * base_col_count
    for indicator in indicators:
        row1_data.extend([indicator] * len(month_labels))

    # 第2行：月份
    row2_data = [''] * base_col_count
    for indicator in indicators:
        row2_data.extend(month_labels)

    # 第3行：列标题 + 汇总值
    row3_data = base_info_cols.copy()

    # 计算汇总值并构建第3行
    for indicator in indicators:
        for month in month_labels:
            if indicator == '最低售价':
                # 最低售价不显示汇总量，显示月份
                row3_data.append('')
            elif indicator == '零售量':
                col_name = month
                if col_name in merged_data.columns:
                    total_value = merged_data[col_name].sum()
                else:
                    total_value = 0
                row3_data.append(f"{total_value:.0f}")
            elif indicator == '零售额':
                # 零售额 = 零售量 × 最低售价 × (1 - 零售扣点)
                price_col = f"价格_{month}"
                quantity_col = month
                if price_col in merged_data.columns and quantity_col in merged_data.columns:
                    revenue_values = (merged_data[quantity_col] *
                                      merged_data[price_col] *
                                      (1 - merged_data['零售扣点']) / 10000)
                    total_value = revenue_values.sum()
                else:
                    total_value = 0
                row3_data.append(f"{total_value:.0f}")
            elif indicator == '收入量':
                # 收入量 = 零售量
                col_name = month
                if col_name in merged_data.columns:
                    total_value = merged_data[col_name].sum()
                else:
                    total_value = 0
                row3_data.append(f"{total_value:.0f}")
            elif indicator == '收入额':
                # 收入额 = 零售量 × 最低售价 × (1 - 费用扣点)
                price_col = f"价格_{month}"
                quantity_col = month
                if price_col in merged_data.columns and quantity_col in merged_data.columns:
                    income_values = (merged_data[quantity_col] *
                                     merged_data[price_col] *
                                     (1 - merged_data['费用扣点']) / 11300)
                    total_value = income_values.sum()
                else:
                    total_value = 0
                row3_data.append(f"{total_value:.0f}")

    # 写入前三行
    for col_idx, value in enumerate(row1_data, 1):
        ws.cell(row=1, column=col_idx, value=value)

    for col_idx, value in enumerate(row2_data, 1):
        ws.cell(row=2, column=col_idx, value=value)

    for col_idx, value in enumerate(row3_data, 1):
        ws.cell(row=3, column=col_idx, value=value)

    # 写入数据行（从第4行开始）
    current_row = 4

    for _, row_data in merged_data.iterrows():
        # 写入基础信息
        for col_idx, col_name in enumerate(base_info_cols, 1):
            # 1. 获取单元格对象
            cell = ws.cell(row=current_row, column=col_idx, value=row_data[col_name])

            # 2. 如果是返点列，则设置其数字格式为百分比
            if col_name in ['零售扣点', '费用扣点']:
                cell.number_format = '0%'
            ws.cell(row=current_row, column=col_idx, value=row_data[col_name])

        # 写入指标数据
        col_offset = base_col_count
        for indicator in indicators:
            for month in month_labels:
                if indicator == '最低售价':
                    col_name = f"价格_{month}"
                    value = row_data[col_name] if col_name in row_data.index else 0
                elif indicator == '零售量':
                    col_name = month
                    value = row_data[col_name] if col_name in row_data.index else 0
                elif indicator == '零售额':
                    price_col = f"价格_{month}"
                    quantity_col = month
                    if price_col in row_data.index and quantity_col in row_data.index:
                        value = (row_data[quantity_col] *
                                 row_data[price_col] *
                                 (1 - row_data['零售扣点']) / 10000)
                    else:
                        value = 0
                elif indicator == '收入量':
                    col_name = month
                    value = row_data[col_name] if col_name in row_data.index else 0
                elif indicator == '收入额':
                    price_col = f"价格_{month}"
                    quantity_col = month
                    if price_col in row_data.index and quantity_col in row_data.index:
                        value = (row_data[quantity_col] *
                                 row_data[price_col] *
                                 (1 - row_data['费用扣点']) / 11300)
                    else:
                        value = 0

                # 零售额和收入额应用格式
                cell = ws.cell(row=current_row, column=col_offset + 1, value=value)
                if indicator in ['零售额', '收入额']:
                    cell.number_format = '#,##0.0'  # 使用千位分隔符并保留一位小数
                elif indicator == '最低售价':
                    cell.number_format = '###0'
                col_offset += 1
        current_row += 1

    # 设置样式
    apply_three_level_header_styles(ws, base_col_count, len(month_labels), len(indicators))

    return wb


def apply_three_level_header_styles(ws, base_col_count, months_per_indicator, indicator_count):
    """
    应用三级表头的样式
    """
    from openpyxl.styles import Alignment, Font, Border, Side, PatternFill
    from openpyxl.utils import get_column_letter

    # 边框样式
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # 标题字体
    header_font = Font(bold=True)
    center_alignment = Alignment(horizontal='center', vertical='center')

    # 设置格式
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        for cell in row:
            # 应用居中对齐和边框
            cell.alignment = center_alignment
            cell.border = thin_border

            # 如果是表头行（前3行），则加粗字体
            if cell.row <= 3:
                cell.font = header_font

    # 合并第1行的指标标题单元格
    start_col = base_col_count + 1
    for i in range(indicator_count):
        end_col = start_col + months_per_indicator - 1
        if start_col <= end_col:
            ws.merge_cells(start_row=1, start_column=start_col, end_row=1, end_column=end_col)
        start_col = end_col + 1

    # 设置列宽
    for col in range(1, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(col)].width = 12


def save_multi_sheet_excel(forecast_results, detailed_results, master_data, price_data, rebate_data, target_month,
                           output_path):
    """
    保存双 Sheet Excel：
    - Sheet1: 三级表头汇总预测
    - Sheet2: N+1~N+7 预测明细（同维度多行，含输入特征与后处理过程）
    """
    wb = create_three_level_header_output(
        forecast_results,
        master_data,
        price_data,
        rebate_data,
        target_month
    )

    ws2 = wb.create_sheet("预测详情")
    detail_output_df = format_detailed_results(detailed_results)

    for r in dataframe_to_rows(detail_output_df, index=False, header=True):
        ws2.append(r)

    from openpyxl.styles import Alignment, Font

    center_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    header_font = Font(bold=True)
    for row in ws2.iter_rows(min_row=1, max_row=ws2.max_row, min_col=1, max_col=ws2.max_column):
        for cell in row:
            cell.alignment = center_alignment
            if cell.row == 1:
                cell.font = header_font

    for idx in range(1, ws2.max_column + 1):
        col_letter = ws2.cell(row=1, column=idx).column_letter
        header = ws2.cell(row=1, column=idx).value or ''
        width = 14
        if header in ('型号', '型号-CRM最新名称'):
            width = 20
        elif header in ('后处理规则', 'post_process_rule'):
            width = 22
        elif len(str(header)) > 12:
            width = min(28, len(str(header)) + 2)
        ws2.column_dimensions[col_letter].width = width

    wb.save(output_path)
    print(f"预测结果已导出至: {output_path}")


def format_detailed_results(detailed_results: pd.DataFrame) -> pd.DataFrame:
    """整理 N+1~N+7 预测明细列顺序与中文表头。"""
    if detailed_results is None or detailed_results.empty:
        return pd.DataFrame()

    df = detailed_results.copy()
    if '月份' in df.columns:
        df['月份'] = pd.to_datetime(df['月份']).dt.strftime('%Y-%m')

    rename_map = {
        'horizon': '预测期',
        'horizon_offset': '预测期序号',
        '月份': '预测月份',
        '品类': '品类',
        'series': '系列',
        'status': '状态',
        '1级渠道': '1级渠道',
        '3级渠道': '3级渠道',
        '型号-CRM最新名称': '型号',
        'plan_price': '计划价格',
        '当月累计销量': '当月累计销量',
        '当月推算销量': '当月推算销量',
        'baseline_model': '基线模型',
        'method': '方法',
        'baseline_pred': '基线预测值',
        'model_pred': '模型原始预测',
        'strategy_pred': '策略合成值',
        'y_pred_before_transition': '过渡调整前预测',
        'y_pred': '最终预测值',
        'pred_bias': '模型偏差bias',
        'eol_ratio': '淘汰下滑比率',
        'post_process_rule': '后处理规则',
        'weight_model_weight': '权重_模型',
        'weight_3m_mean_weight': '权重_近3月均',
        'weight_lag12_weight': '权重_去年同期',
        'weight_model_bias_weight': '权重_偏差修正',
        'term_model': '过程项_模型',
        'term_3m_mean': '过程项_近3月均',
        'term_lag12': '过程项_去年同期',
        'term_bias': '过程项_偏差修正',
        'product_line_code': '产线编码',
        'product_line_name': '产线名称',
    }

    head_cols = [
        'horizon', 'horizon_offset', '月份', '品类', 'series', 'status',
        '1级渠道', '3级渠道', '型号-CRM最新名称', 'plan_price',
        '当月累计销量', '当月推算销量',
        'baseline_model', 'method', 'baseline_pred', 'model_pred', 'strategy_pred',
        'y_pred_before_transition', 'y_pred',
        'pred_bias', 'eol_ratio', 'post_process_rule',
        'weight_model_weight', 'weight_3m_mean_weight', 'weight_lag12_weight', 'weight_model_bias_weight',
        'term_model', 'term_3m_mean', 'term_lag12', 'term_bias',
        'product_line_code', 'product_line_name',
    ]
    # 其余列为模型输入特征（保持原字段名，便于对照 MODEL_FEATURES）
    feature_cols = [c for c in df.columns if c not in head_cols and c not in ('avg_price',)]
    ordered = [c for c in head_cols if c in df.columns] + sorted(feature_cols)
    out = df.reindex(columns=ordered).rename(columns=rename_map)
    sort_keys = [c for c in ['品类', '3级渠道', '型号', '预测期序号'] if c in out.columns]
    if sort_keys:
        out = out.sort_values(by=sort_keys).reset_index(drop=True)
    return out


def format_history_results(history_results: pd.DataFrame) -> pd.DataFrame:
    """整理历史数据 sheet：与预测详情同颗粒度（月份+品类+各级渠道+型号）。"""
    if history_results is None or history_results.empty:
        return pd.DataFrame()

    df = history_results.copy()
    if '月份' in df.columns:
        df['月份'] = pd.to_datetime(df['月份']).dt.strftime('%Y-%m')

    rename_map = {
        '月份': '月份',
        '品类': '品类',
        'series': '系列',
        'status': '状态',
        '1级渠道': '1级渠道',
        '3级渠道': '3级渠道',
        '型号-CRM最新名称': '型号',
        '数量': '零售量',
        '实收金额': '零售额',
        'avg_price': '平均成交价',
        'product_line_code': '产线编码',
        'product_line_name': '产线名称',
    }
    head_cols = [
        '月份', '品类', 'series', 'status',
        '1级渠道', '3级渠道', '型号-CRM最新名称',
        '数量', '实收金额', 'avg_price',
        'product_line_code', 'product_line_name',
    ]
    ordered = [c for c in head_cols if c in df.columns]
    out = df.reindex(columns=ordered).rename(columns=rename_map)
    sort_keys = [c for c in ['品类', '3级渠道', '型号', '月份'] if c in out.columns]
    if sort_keys:
        out = out.sort_values(by=sort_keys).reset_index(drop=True)
    return out


# def save_three_level_header_excel(forecast_results, master_data, price_data, rebate_data, target_month, output_path):
#     """
#     保存三级表头格式的Excel文件
#     """
#     wb = create_three_level_header_output(forecast_results, master_data, price_data, rebate_data, target_month)
#     wb.save(output_path)
#     print(f"三级表头格式预测结果已导出至: {output_path}")


def format_output(forecast_results, master_data, price_data, rebate_data, dsi_data, begin_inv_data):
    """
    格式化输出结果
    """
    # 1. 数据预处理
    results_df = forecast_results.copy()
    results_df['月份'] = pd.to_datetime(results_df['月份'])

    forecast_months = sorted(results_df['月份'].unique())
    month_labels = [month.strftime('%m月') for month in forecast_months]
    print(f"预测月份: {month_labels}")

    # 2. 合并主数据信息
    master_rename_dict = {
            'category_name': '品类',
            'product_type': 'type',
            'product_series': 'series',
            'product_status': 'status',
    }
    master_data = master_data.rename(columns=master_rename_dict)

    master_info = master_data[['型号-CRM最新名称', '品类', 'series', 'status']].drop_duplicates()
    existing_cols = set(results_df.columns)
    master_cols_to_merge = ['型号-CRM最新名称']

    for col in ['品类', 'series', 'status']:
        if col not in existing_cols:
            master_cols_to_merge.append(col)

    if len(master_cols_to_merge) > 1:
        results_df = pd.merge(results_df, master_info[master_cols_to_merge], on='型号-CRM最新名称', how='left')

    # 3. 合并返点信息
    rebate_info = rebate_data[['3级渠道', '零售扣点', '费用扣点', '大单机零售扣点', '大单机费用扣点']].drop_duplicates()
    results_df = pd.merge(results_df, rebate_info, on='3级渠道', how='left')
    results_df['零售扣点'] = results_df['零售扣点'].fillna(0)
    results_df['费用扣点'] = results_df['费用扣点'].fillna(0)

    # 4. 处理重复列名问题
    column_mapping = {}
    for col in results_df.columns:
        if col.endswith('_x'):
            base_col = col[:-2]
            column_mapping[col] = base_col
            y_col = base_col + '_y'
            if y_col in results_df.columns:
                results_df = results_df.drop(columns=[y_col])
        elif col.endswith('_y'):
            base_col = col[:-2]
            if base_col + '_x' not in results_df.columns:
                column_mapping[col] = base_col

    if column_mapping:
        results_df = results_df.rename(columns=column_mapping)

    # 5. 准备基础信息
    required_columns = ['品类', 'product_line_code', 'product_line_name', 'series', 'status', '1级渠道', '3级渠道', '型号-CRM最新名称', '零售扣点', '费用扣点', '大单机零售扣点', '大单机费用扣点']
    base_info = results_df.groupby(['型号-CRM最新名称', '3级渠道']).first().reset_index()
    base_info_data = base_info[required_columns].rename(
        columns={'series': '定位','status': '状态', 'product_line_code': 
                 '产线编码', 'product_line_name': '产线名称'}
        )

    # 6. 创建价格透视表
    price_pivot = create_price_pivot(price_data, forecast_months, results_df)
    # 创建出货价透视表
    factory_pivot = create_factory_pivot(price_data, forecast_months, results_df)
    # 创建零售量透视表
    quantity_pivot = create_quantity_pivot(results_df)
    # 创建销量透视表
    sales_pivot = create_sales_pivot(dsi_data, begin_inv_data, results_df)

    # 7. 合并所有数据
    merged_data = pd.merge(base_info_data, factory_pivot,
                           left_on=['型号-CRM最新名称', '3级渠道'],
                           right_index=True, how='left')
    merged_data = pd.merge(merged_data, price_pivot,
                           left_on=['型号-CRM最新名称', '3级渠道'],
                           right_index=True, how='left')
    merged_data = pd.merge(merged_data, quantity_pivot,
                           left_on=['型号-CRM最新名称', '3级渠道'],
                           right_index=True, how='left')
    merged_data = pd.merge(merged_data, sales_pivot,
                           left_on=['型号-CRM最新名称', '3级渠道'],
                           right_index=True, how='left')
    
    # 大单机处理
    drop_cols = ['大单机零售扣点', '大单机费用扣点', '是否大单机']
    mask = merged_data['是否大单机'] & merged_data['大单机零售扣点'].notna() & merged_data['大单机费用扣点'].notna()
    merged_data.loc[mask, ['零售扣点', '费用扣点']] = merged_data.loc[mask, ['大单机零售扣点', '大单机费用扣点']].values
    merged_data = merged_data.drop(drop_cols, axis=1)

    # 8. 直接构建三级表头Excel
    merged_data = merged_data.sort_values(by=['1级渠道', '3级渠道']).reset_index(drop=True)

    sales_cols = [f"销量_n月" if i == 0 else f"销量_n{i}月" for i in range(len(sales_pivot.columns))]
    merged_data[sales_cols] = merged_data[sales_cols].astype('int64').astype('float64')

    merged_data[sales_cols] = merged_data[sales_cols].clip(lower=0)

    return merged_data


def insert_results_to_database(forecast_results, master_data, price_data, rebate_data, dsi_data,
                                begin_inv_data, target_month, engine, output_table, api_param,
                                output_format, save_test_data, output_test_format, test_output_table,
                                detailed_results=None, attribution_factors=None, history_results=None):

    output = format_output(
        forecast_results,
        master_data,
        price_data,
        rebate_data,
        dsi_data,
        begin_inv_data
    )

    # 结果保存至数据库
    save_info = save_results(
        output, engine, output_table, target_month, api_param, output_format,
        save_test_data, output_test_format, test_output_table,
        detailed_results=detailed_results,
        attribution_factors=attribution_factors,
        history_results=history_results,
    )

    return save_info
