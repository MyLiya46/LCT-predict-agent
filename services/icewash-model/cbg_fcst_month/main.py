# new_main.py
from config import Config
from output import insert_results_to_database
from pipeline import SalesForecastingPipeline
from dataloader import SKUDataProcessor, PlanningPrice, DSI_Processor, SalesDataProcessor

from sqlalchemy import create_engine

from datetime import datetime, date, timedelta

from pg_sync import write_forecast_and_attribution


def _report(progress_callback, message: str) -> None:
    if progress_callback:
        progress_callback(message)


def main(systemForecastNumber, productLine, reporter, generateTime,
         forecastMonth, saveTestData, categoryBatchMappingDTOList,
         progress_callback=None, forecast_horizon=None):
    # 初始化配置
    cfg = Config()
    engine = create_engine(cfg.ENGINE_URL)

    cfg.PRODUCT_LINE_CODE = productLine
    cfg.API_PARAM = {
        'systemForecastNumber': systemForecastNumber,
        'reporter': reporter,
        'generateTime': generateTime,
        'categoryBatchMappingDTOList': categoryBatchMappingDTOList
    }

    cfg.CATEGORY_LIST = [item["category"] for item in categoryBatchMappingDTOList]
    cfg.PRICE_VERSION_LIST = list(set([item["priceBatchNumber"] for item in categoryBatchMappingDTOList]))
    cfg.PRODUCT_VERSION_LIST = list(set([item["productBatchNumber"] for item in categoryBatchMappingDTOList]))


    cfg.DATE_SETTINGS = str((date.today().replace(day=1) + timedelta(days=32)).replace(day=1))

    print(f'===> forecast month (API): {cfg.DATE_SETTINGS}')
    if forecastMonth is not None:
        cfg.DATE_SETTINGS = forecastMonth
        print(f'===> update forecast month: {cfg.DATE_SETTINGS}')
    if forecast_horizon is not None:
        cfg.FORECAST_MONTHS = max(1, min(int(forecast_horizon), 12))
        print(f'===> forecast horizon: {cfg.FORECAST_MONTHS}')

    _report(
        progress_callback,
        f"配置完成：产线={productLine}，预测月={cfg.DATE_SETTINGS}，品类={','.join(cfg.CATEGORY_LIST)}"
    )

    # 初始化预测流水线
    pipeline = SalesForecastingPipeline(cfg)

    # 执行预测
    forecast_results, detailed_results, attribution_factors, history_results = pipeline.run(
        cfg.DATE_SETTINGS,
        progress_callback=progress_callback,
        forecast_horizon=cfg.FORECAST_MONTHS,
    )
    print(f"预测完成，共生成 {len(forecast_results)} 条预测结果")
    _report(progress_callback, f"预测流水线完成，共生成 {len(forecast_results)} 条预测结果")

    # 加载额外需要的数据
    _report(progress_callback, "结果落盘准备：加载主数据/价格/返点/DSI/期初库存")
    master_processor = SKUDataProcessor(cfg)
    price_processor = PlanningPrice(cfg)

    dsi_processor = DSI_Processor(cfg)
    sales_processor = SalesDataProcessor(cfg)


    master_data = master_processor.load_master_data(cfg.DATE_SETTINGS)
    price_data = price_processor.process_price_data()
    rebate_data = price_processor.process_rebate_date()

    dsi_data = dsi_processor.load_dsi_data()

    begin_inv_data = sales_processor.get_begin_inv_data()

    _report(progress_callback, "正在保存预测结果（Excel/数据库）")
    save_info = insert_results_to_database(
        forecast_results,
        master_data,
        price_data,
        rebate_data,
        dsi_data,
        begin_inv_data,
        cfg.DATE_SETTINGS,
        engine,
        cfg.DATA_TABLES['result'],
        cfg.API_PARAM,
        cfg.OUTPUT_FORMAT,

        saveTestData,
        cfg.OUTPUT_TEST_FORMAT,
        cfg.DATA_TABLES['test_result'],
        detailed_results=detailed_results,
        attribution_factors=attribution_factors,
        history_results=history_results,
    )

    if save_info['saved_success']:
        print(f"预测结果已保存至数据库！")
        _report(
            progress_callback,
            f"结果已保存：success={save_info.get('saved_success')}，条数={save_info.get('saved_count')}"
        )
    else:
        print(f"预测结果保存失败!")
        _report(
            progress_callback,
            f"结果保存失败：{save_info.get('message', '未知错误')}"
        )

    # 冰洗中转表写 PG（T53：预测结果 + 归因因子明细；失败仅告警不阻断）
    pg_write = write_forecast_and_attribution(
        system_forecast_number=systemForecastNumber,
        detailed_results=detailed_results,
        attribution_factors=attribution_factors,
    )
    _report(
        progress_callback,
        f"PG 中转落库：forecast={pg_write['forecast_rows']} 行，attribution={pg_write['attribution_rows']} 行"
    )
    return {'data': save_info, 'pg_write': pg_write, 'productLine': cfg.PRODUCT_LINE_CODE, **cfg.API_PARAM}

if __name__ == "__main__":
    systemForecastNumber = f'test_202608_{datetime.now().strftime("%m%d_%H%M")}'
    productLine = 'PL003'
    reporter = 'test_user'
    generateTime = '2026-03-16 00:00:00'
    forecastMonth = '2026-08-01'
    saveTestData = None
    categoryBatchMappingDTOList = [
        {
            "category": "冰箱",
            "productBatchNumber": "SX_PL003_20260615_004",
            "priceBatchNumber": "JG_PL003_20260615_001"
        },
        {
            "category": "洗衣机",
            "productBatchNumber": "SX_PL003_20260609_006",
            "priceBatchNumber": "JG_PL003_20260624_001"
        }
    ]

    main(systemForecastNumber, productLine, reporter, generateTime, forecastMonth, saveTestData, categoryBatchMappingDTOList)
