import logging
import argparse
import asyncio
import contextvars
import json
import os
import sqlite3
import threading
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
import httpx

from main import main

from config import Config
from request_log import RequestLogSession, make_request_log_path
import whatif as whatif_engine
from reference_data import (
    REFERENCE_DIR,
    ReferenceDataError,
    _source_for,
    knowledge_markdown,
    load_workbench_dataset,
    parse_cost_upload,
)


cfg = Config()
LOG_DIR = Path(cfg.LOG_DIR)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # 输出到控制台
)
logger = logging.getLogger("prediction_api")

# 全局任务存储（工作线程写 progress，主线程读；需加锁）
task_store: Dict[str, Dict[str, Any]] = {}


def _task_db_path() -> Path:
    """任务持久化 SQLite 文件路径（与 log 同目录，跨重启可恢复）。"""
    return Path(cfg.LOG_DIR).parent / "task_store.sqlite3"


def _task_db_connect():
    """建连接（check_same_thread=False：多线程下由 task_store_lock 串行化访问）。"""
    conn = sqlite3.connect(str(_task_db_path()), check_same_thread=False)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
    )
    return conn


class _TaskDb:
    """进程内 SQLite 连接 + 锁（复用 task_store_lock 串行读写）。"""

    def __init__(self) -> None:
        self._conn: sqlite3.Connection | None = None
        self._init = False

    @property
    def conn(self) -> sqlite3.Connection:
        if not self._init:
            self._conn = _task_db_connect()
            self._init = True
        return self._conn  # type: ignore[return-value]


_task_db = _TaskDb()
task_store_lock = threading.Lock()


def _load_task_from_db(task_id: str) -> Dict[str, Any] | None:
    """从 SQLite 惰性加载任务（首次 GET 未命中内存时回补；重启后由此恢复）。"""
    try:
        row = _task_db.conn.execute(
            "SELECT payload FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        with task_store_lock:
            task_store[task_id] = data
        return data
    except Exception as e:  # noqa: BLE001 - 落盘异常不阻断查询路径
        logger.warning(f"任务落盘恢复失败 [{task_id[:8]}…]: {e}")
        return None


def _persist_task(task_id: str, task: Dict[str, Any]) -> None:
    """把任务字段 JSON 序列化写入 SQLite（随写随存）。失败仅告警不阻断。"""
    try:
        _task_db.conn.execute(
            "INSERT OR REPLACE INTO tasks (task_id, payload) VALUES (?, ?)",
            (task_id, json.dumps(task, ensure_ascii=False, default=str)),
        )
        _task_db.conn.commit()
    except Exception as e:  # noqa: BLE001 - 持久化失败只影响重启恢复，不影响在线查询
        logger.warning(f"任务落盘失败 [{task_id[:8]}…]: {e}")


def append_task_progress(task_id: str, message: str) -> None:
    """更新最新 progress，并追加到 progress_log；随写随存（终态后撤销内存可经落盘恢复）。"""
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": message,
    }
    with task_store_lock:
        task = task_store.get(task_id)
        if not task:
            return
        task["progress"] = message
        task.setdefault("progress_log", []).append(entry)
        _persist_task(task_id, task)
    logger.info(f"任务进度 [{task_id[:8]}…]: {message}")

# 从环境变量获取配置，提供默认值
callback_base_url = cfg.CALLBACK_BASE_URL
organization_id = cfg.ORGANIZATION_ID


class CategoryBatchMappingDTO(BaseModel):
    category: str = Field(..., description="品类")
    priceBatchNumber: str = Field(..., description="价格数据批次号")
    productBatchNumber: str = Field(..., description="产品数据批次号")


class SimulateRow(BaseModel):
    """per-SKU 基线行（simulate/optimize 传入）。elasticity_coef/class/category/status 可缺省。"""
    sku: str = Field(..., description="型号")
    channel_l3: str = Field("", description="3级渠道")
    category: Optional[str] = Field(None, description="品类")
    status: Optional[str] = Field(None, description="状态（淘汰/新品/主销…）")
    baseline_qty: float = Field(..., description="最终预测值基线")
    plan_price: Optional[float] = Field(None, description="计划价")
    elasticity_coef: Optional[float] = Field(None, description="价格弹性系数（缺省走类别 fallback）")
    elasticity_class: Optional[str] = Field(None, description="弹性类别")


class SimulateRequest(BaseModel):
    strategy_id: str = Field(..., description="策略 id（见 /whatif/strategies）")
    param: Optional[str] = Field(None, description="策略参数，如 '-8%' / '+12%'")
    traffic_tier: Optional[str] = Field(None, description="投流档位 conservative|medium|aggressive")
    rows: List[SimulateRow] = Field(..., description="per-SKU 基线行列表")


class OptimizeRequest(BaseModel):
    target_qty: float = Field(..., description="目标销量")
    param: Optional[str] = Field(None, description="策略参数（候选按 statuses 过滤）")
    traffic_tier: Optional[str] = Field(None, description="投流档位")
    rows: List[SimulateRow] = Field(..., description="per-SKU 基线行列表")

# 定义请求体模型
class PredictionRequest(BaseModel):
    systemForecastNumber: str = Field(..., description="系统预测编号")
    productLine: str = Field(..., description="产线编码")
    reporter: str = Field(..., description="填报人")
    generateTime: str = Field(..., description="生成时间")

    customCallbackUrl: Optional[str] = Field(None, description="自定义回调URL，覆盖默认配置；本地可传 null")
    forecastMonth: Optional[str] = Field(None, description="预测月份，可选")
    # 与 main.py 一致：允许 null；null/False 均不写测试表
    saveTestData: Optional[bool] = Field(default=False, description="是否保存用于测试的结果数据，可传 null")

    categoryBatchMappingDTOList: List[CategoryBatchMappingDTO] = Field(
        ..., 
        description="品类批次号映射列表"
    )

    class Config:
        schema_extra = {
            "example": {
                "systemForecastNumber": "YC_001",
                "productLine": "PL003",
                "categoryList": [],
                "reporter": "测试",
                "generateTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                
                "categoryBatchMappingDTOList": [
                    {
                        "category": "冰箱",
                        "priceBatchNumber": "JG_PL003",
                        "productBatchNumber": "SX_PL003"
                    },
                    {
                        "category": "洗衣机",
                        "priceBatchNumber": "JG_PL003",
                        "productBatchNumber": "SX_PL003"
                    }
                ],

                'customCallbackUrl': None,
                'forecastMonth': '2025-10-01',
                'saveTestData': False,
            }
        }

# 定义响应模型
class PredictionResponse(BaseModel):
    task_id: str
    status: str
    message: str
    systemForecastNumber: str
    productLine: str
    callback_url: Optional[str] = None
    log_file: Optional[str] = None
    categoryBatchMappingDTOList: List[CategoryBatchMappingDTO]


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    progress: Optional[str] = None
    progress_log: Optional[List[Dict[str, Any]]] = None
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    created_time: str
    completed_time: Optional[str] = None
    log_file: Optional[str] = None

class CallbackNotification(BaseModel):
    task_id: str
    status: str
    systemForecastNumber: str
    productLine: str
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
    categoryBatchMappingDTOList: List[CategoryBatchMappingDTO]
    completed_time: str
    reporter: str
    generateTime: str

def create_app():
    """创建FastAPI应用实例"""
    return FastAPI(
        title="预测Pipeline API服务",
        description="封装预测pipeline的REST API - 异步版本",
        version="2.0.0"
    )

app = create_app()

def build_callback_url(system_forecast_number: str, custom_url: Optional[str] = None) -> str:
    """构建回调URL"""
    if custom_url:
        return custom_url
    
    return f"{callback_base_url}/api/predict/v1/{organization_id}/forecast-result-infos/completed/{system_forecast_number}"

async def send_callback_notification(callback_url: str, notification: CallbackNotification):
    """发送回调通知"""
    try:
        logger.info(f"发送回调通知 - URL: {callback_url}, 任务ID: {notification.task_id}")
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                callback_url,
                json=notification.model_dump(),
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            logger.info(f"回调通知发送成功 - 任务ID: {notification.task_id}, 状态码: {response.status_code}")
            
            res_json = response.json()
            logger.info('=' * 40)
            logger.info(f'{res_json}')
            logger.info('=' * 40)
            
            return True
    except httpx.TimeoutException:
        logger.error(f"回调通知超时 - 任务ID: {notification.task_id}, URL: {callback_url}")
        return False
    except Exception as e:
        logger.error(f"回调通知发送失败 - 任务ID: {notification.task_id}, 错误: {str(e)}")
        return False

async def execute_prediction_task(task_id: str, request_data: dict, log_path: str):
    """执行预测任务的异步函数；运行输出写入按请求时间戳命名的日志文件。"""
    callback_sent = False
    log_session = RequestLogSession(Path(log_path))
    log_session.start(
        header=(
            f"===== 请求日志开始 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} =====\n"
            f"task_id={task_id}\n"
            f"systemForecastNumber={request_data.get('systemForecastNumber')}\n"
            f"productLine={request_data.get('productLine')}\n"
            f"log_file={log_path}\n"
            f"request_data={request_data}\n"
        )
    )

    try:
        logger.info(f"开始执行预测任务 - 任务ID: {task_id}, 日志: {log_path}")

        # 更新任务状态为运行中
        with task_store_lock:
            task_store[task_id].update({
                "status": "running",
                "log_file": log_path,
            })
            _persist_task(task_id, task_store[task_id])
        append_task_progress(task_id, "预测任务开始执行")

        def on_progress(message: str) -> None:
            append_task_progress(task_id, message)

        def run_main_with_log():
            # 在工作线程内捕获 pipeline/main 的 print 输出
            log_session.bind_prints()
            try:
                return main(
                    request_data["systemForecastNumber"],
                    request_data["productLine"],
                    request_data["reporter"],
                    request_data["generateTime"],
                    request_data["forecastMonth"],
                    request_data["saveTestData"],
                    request_data["categoryBatchMappingDTOList"],
                    progress_callback=on_progress,
                )
            finally:
                log_session.unbind_prints()

        # 在线程池中执行同步的main函数（copy_context 继承请求日志 token）
        loop = asyncio.get_event_loop()
        ctx = contextvars.copy_context()
        with ThreadPoolExecutor() as executor:
            results = await loop.run_in_executor(executor, ctx.run, run_main_with_log)

        # 构建回调通知数据
        completed_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        notification = CallbackNotification(
            task_id=task_id,
            status="completed",
            systemForecastNumber=request_data["systemForecastNumber"],
            productLine=request_data["productLine"],
            success=True,
            message="预测任务完成",
            data=results.get('data'),
            categoryBatchMappingDTOList=request_data["categoryBatchMappingDTOList"],
            completed_time=completed_time,
            reporter=request_data["reporter"],
            generateTime=request_data["generateTime"]
        )

        # 更新任务状态为完成
        append_task_progress(task_id, "预测任务执行完成")
        with task_store_lock:
            task_store[task_id].update({
                "status": "completed",
                "result": results,
                "completed_time": completed_time,
                "callback_notification": notification.model_dump()
            })
            _persist_task(task_id, task_store[task_id])

        logger.info(f"预测任务执行完成 - 任务ID: {task_id}")

        # 发送回调通知
        callback_url = build_callback_url(
            request_data["systemForecastNumber"],
            request_data.get("customCallbackUrl")
        )

        callback_sent = await send_callback_notification(callback_url, notification)
        with task_store_lock:
            task_store[task_id]["callback_sent"] = callback_sent
            task_store[task_id]["callback_url"] = callback_url
            _persist_task(task_id, task_store[task_id])

    except Exception as e:
        # 处理任务执行失败的情况
        error_msg = f"预测任务执行失败: {str(e)}"
        completed_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 构建错误通知
        notification = CallbackNotification(
            task_id=task_id,
            status="failed",
            systemForecastNumber=request_data["systemForecastNumber"],
            productLine=request_data["productLine"],
            success=False,
            message=error_msg,
            categoryBatchMappingDTOList=request_data["categoryBatchMappingDTOList"],
            completed_time=completed_time,
            reporter=request_data["reporter"],
            generateTime=request_data["generateTime"]
        )

        # 更新任务状态为失败
        append_task_progress(task_id, error_msg)
        with task_store_lock:
            task_store[task_id].update({
                "status": "failed",
                "error_message": error_msg,
                "completed_time": completed_time,
                "callback_notification": notification.model_dump()
            })
            _persist_task(task_id, task_store[task_id])

        logger.error(f"预测任务执行失败 - 任务ID: {task_id}, 错误: {error_msg}", exc_info=True)

        # 发送错误回调通知
        callback_url = build_callback_url(
            request_data["systemForecastNumber"],
            request_data.get("customCallbackUrl")
        )

        callback_sent = await send_callback_notification(callback_url, notification)
        with task_store_lock:
            task_store[task_id]["callback_sent"] = callback_sent
            task_store[task_id]["callback_url"] = callback_url
            _persist_task(task_id, task_store[task_id])
    finally:
        log_session.stop()

@app.get("/")
async def root():
    """服务根路径，用于健康检查"""
    logger.info("收到根路径请求，服务健康检查")
    return {
        "message": "预测Pipeline API服务正在运行 - 异步版本",
        "status": "active",
        "version": "2.0.0",
        "docs_url": "/docs",
        "callback_base_url": callback_base_url,
        "organization_id": organization_id
    }

@app.post("/predict-sit", response_model=PredictionResponse)
@app.post("/predict-uat", response_model=PredictionResponse)
@app.post("/predict", response_model=PredictionResponse)
async def run_prediction(request: PredictionRequest, background_tasks: BackgroundTasks):
    """
    提交预测任务 - 异步版本
    
    立即返回任务ID，预测任务在后台执行，完成后通过回调通知
    """
    # 生成唯一任务ID，并按请求时间戳创建日志文件
    task_id = str(uuid.uuid4())
    request_time = datetime.now()
    log_path = str(make_request_log_path(LOG_DIR, when=request_time))

    logger.info(
        f"收到预测请求 - 任务ID: {task_id}, 系统预测编号: {request.systemForecastNumber}, "
        f"产线: {request.productLine}, 提交人: {request.reporter}, 日志: {log_path}"
    )

    logger.info('=' * 10 + ' 参数 ' + '=' * 10)
    logger.info(request.model_dump())
    logger.info('=' * 20)

    # 构建回调URL
    callback_url = build_callback_url(
        request.systemForecastNumber,
        request.customCallbackUrl
    )

    # 存储任务信息
    created_time = request_time.strftime("%Y-%m-%d %H:%M:%S")
    with task_store_lock:
        task_store[task_id] = {
            "status": "pending",
            "request_data": request.model_dump(),
            "created_time": created_time,
            "progress": "任务已提交，等待执行",
            "progress_log": [
                {"time": created_time, "message": "任务已提交，等待执行"}
            ],
            "callback_url": callback_url,
            "log_file": log_path,
        }
        _persist_task(task_id, task_store[task_id])

    # 在后台启动预测任务（运行输出写入时间戳日志）
    background_tasks.add_task(
        execute_prediction_task, task_id, request.model_dump(), log_path
    )

    # 立即返回响应
    return PredictionResponse(
        task_id=task_id,
        status="pending",
        message="预测任务已提交，正在后台处理",
        systemForecastNumber=request.systemForecastNumber,
        productLine=request.productLine,
        callback_url=callback_url,
        log_file=log_path,
        categoryBatchMappingDTOList=request.categoryBatchMappingDTOList
    )

@app.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """查询任务状态（内存未命中 → SQLite 惰性恢复，支持跨重启）。"""
    with task_store_lock:
        task_info = dict(task_store[task_id]) if task_id in task_store else None
    if task_info is None:
        task = _load_task_from_db(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        task_info = dict(task)
    progress_log = list(task_info.get("progress_log") or [])
    return TaskStatusResponse(
        task_id=task_id,
        status=task_info["status"],
        progress=task_info.get("progress"),
        progress_log=progress_log,
        result=task_info.get("result"),
        error_message=task_info.get("error_message"),
        created_time=task_info["created_time"],
        completed_time=task_info.get("completed_time"),
        log_file=task_info.get("log_file"),
    )

@app.get("/tasks")
async def list_tasks(limit: int = 50, status: Optional[str] = None):
    """列出所有任务（支持按状态过滤）"""
    tasks = []
    for task_id, task_info in list(task_store.items())[-limit:]:
        if status and task_info["status"] != status:
            continue
        request_data = task_info.get("request_data") or {}
        tasks.append({
            "task_id": task_id,
            "status": task_info["status"],
            "systemForecastNumber": request_data.get("systemForecastNumber"),
            "productLine": request_data.get("productLine"),
            "created_time": task_info["created_time"],
            "completed_time": task_info.get("completed_time"),
            "callback_sent": task_info.get("callback_sent", False)
        })
    
    return {
        "total_tasks": len(tasks),
        "tasks": tasks
    }

@app.post("/tasks/{task_id}/retry-callback")
async def retry_callback(task_id: str):
    """重新发送回调通知"""
    task_info = task_store.get(task_id) or _load_task_from_db(task_id)
    if task_info is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task_info["status"] not in ["completed", "failed"]:
        raise HTTPException(status_code=400, detail="任务尚未完成，无法发送回调")
    
    notification_data = task_info.get("callback_notification")
    if not notification_data:
        raise HTTPException(status_code=400, detail="任务没有回调通知数据")
    
    callback_url = task_info.get("callback_url")
    if not callback_url:
        raise HTTPException(status_code=400, detail="任务没有回调URL")
    
    notification = CallbackNotification(**notification_data)
    success = await send_callback_notification(callback_url, notification)

    with task_store_lock:
        task_store[task_id]["callback_sent"] = success
        task_store[task_id]["last_callback_retry"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _persist_task(task_id, task_store[task_id])

    return {
        "task_id": task_id,
        "callback_sent": success,
        "callback_url": callback_url
    }

@app.delete("/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除任务记录（内存 + SQLite 同删）。"""
    with task_store_lock:
        if task_id not in task_store:
            raise HTTPException(status_code=404, detail="任务不存在")
        del task_store[task_id]
    try:
        _task_db.conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
        _task_db.conn.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"任务删除落盘失败 [{task_id[:8]}…]: {e}")
    return {"message": f"任务 {task_id} 已删除"}

@app.get("/health")
async def health_check():
    """健康检查端点"""
    active_tasks = len([t for t in task_store.values() if t["status"] in ["pending", "running"]])
    completed_tasks = len([t for t in task_store.values() if t["status"] == "completed"])
    failed_tasks = len([t for t in task_store.values() if t["status"] == "failed"])
    
    return {
        "status": "healthy", 
        "service": "prediction-pipeline",
        "active_tasks": active_tasks,
        "completed_tasks": completed_tasks,
        "failed_tasks": failed_tasks,
        "total_tasks": len(task_store),
        "callback_base_url": callback_base_url,
        "organization_id": organization_id
    }


@app.get("/reference/workbench/{dataset}")
async def get_workbench_reference(dataset: str):
    """导出固定参考目录中的工作台数据，供 backend 内网同步。"""
    try:
        return load_workbench_dataset(dataset)
    except ReferenceDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/reference/knowledge/strategy")
async def get_strategy_knowledge():
    """导出模型侧策略知识展示内容。"""
    try:
        return knowledge_markdown()
    except ReferenceDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/reference/workbench/cost_data")
async def upload_workbench_cost_reference(file: UploadFile = File(...)):
    """校验成本文件后原子替换模型侧固定 cost_data.xlsx。"""
    filename = file.filename or ""
    try:
        content = await file.read()
        columns, rows, frame = parse_cost_upload(content, filename)
        REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
        target = REFERENCE_DIR / "cost_data.xlsx"
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", suffix=".xlsx", prefix=".cost_data.", dir=REFERENCE_DIR, delete=False
            ) as temporary:
                temporary_path = temporary.name
            frame.to_excel(temporary_path, index=False)
            os.replace(temporary_path, target)
            temporary_path = None
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
        return {
            "dataset": "cost_data",
            "row_count": len(rows),
            "source": _source_for(target),
            "columns": columns,
        }
    except ReferenceDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("成本参考文件替换失败")
        raise HTTPException(status_code=400, detail=f"成本参考文件替换失败: {exc}") from exc

@app.get("/config")
async def get_config():
    """获取当前配置"""
    return {
        "callback_base_url": callback_base_url,
        "organization_id": organization_id
    }


@app.get("/whatif/strategies")
async def get_whatif_strategies(status: Optional[str] = None):
    """策略目录只读（backend/前端下拉与 LLM 解析的唯一来源）。"""
    return whatif_engine.strategies_response(status=status)


def _simulate_rows(req: SimulateRequest) -> List[Dict[str, Any]]:
    """逐行演算，返回结果列表（含 per-SKU 变量变更说明）。"""
    results = []
    for row in req.rows:
        ed = whatif_engine.resolve_ed(row.elasticity_coef, row.elasticity_class)
        res = whatif_engine.simulate_row(
            baseline_qty=row.baseline_qty,
            plan_price=row.plan_price,
            strategy_id=req.strategy_id,
            param=req.param,
            ed=ed,
            traffic_tier=req.traffic_tier,
        )
        results.append({
            "sku": row.sku,
            "channel_l3": row.channel_l3,
            "category": row.category,
            "strategy_id": req.strategy_id,
            "baseline_qty": row.baseline_qty,
            **res,
        })
    return results


@app.post("/simulate")
async def simulate(request: SimulateRequest, background_tasks: BackgroundTasks):
    """规则式 simulate：创建 taskid → 后台演算 → 结果经 GET /tasks/{id} 取（跨重启可恢复）。"""
    task_id = str(uuid.uuid4())
    created_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with task_store_lock:
        task_store[task_id] = {
            "status": "pending",
            "kind": "simulate",
            "created_time": created_time,
            "progress": "模拟任务已提交",
            "progress_log": [{"time": created_time, "message": "模拟任务已提交"}],
            "request_data": request.model_dump(),
        }
        _persist_task(task_id, task_store[task_id])

    def run_simulate() -> None:
        try:
            append_task_progress(task_id, "规则演算开始")
            results = _simulate_rows(request)
            with task_store_lock:
                task_store[task_id].update({
                    "status": "completed",
                    "result": {"rows": results},
                    "completed_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                _persist_task(task_id, task_store[task_id])
            append_task_progress(task_id, "模拟演算完成")
        except Exception as e:  # noqa: BLE001
            with task_store_lock:
                task_store[task_id].update({
                    "status": "failed",
                    "error_message": f"模拟演算失败: {e}",
                    "completed_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                _persist_task(task_id, task_store[task_id])

    background_tasks.add_task(run_simulate)
    return {"task_id": task_id, "status": "pending"}


@app.post("/optimize")
async def optimize(request: OptimizeRequest, background_tasks: BackgroundTasks):
    """规则式 optimize：逐 SKU 候选 argmin|销量-目标| → 最优策略 + 对应销量。"""
    task_id = str(uuid.uuid4())
    created_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with task_store_lock:
        task_store[task_id] = {
            "status": "pending",
            "kind": "optimize",
            "created_time": created_time,
            "progress": "优化任务已提交",
            "progress_log": [{"time": created_time, "message": "优化任务已提交"}],
            "request_data": request.model_dump(),
        }
        _persist_task(task_id, task_store[task_id])

    def run_optimize() -> None:
        try:
            append_task_progress(task_id, "候选中逐条 simulate 搜索最优策略")
            per_sku = []
            for row in request.rows:
                ed = whatif_engine.resolve_ed(row.elasticity_coef, row.elasticity_class)
                best = whatif_engine.search_optimize(
                    baseline_qty=row.baseline_qty,
                    plan_price=row.plan_price,
                    target_qty=request.target_qty,
                    ed=ed,
                    param=request.param,
                    traffic_tier=request.traffic_tier,
                )
                per_sku.append({
                    "sku": row.sku,
                    "channel_l3": row.channel_l3,
                    "category": row.category,
                    "target_qty": request.target_qty,
                    "baseline_qty": row.baseline_qty,
                    **best,
                })
            with task_store_lock:
                task_store[task_id].update({
                    "status": "completed",
                    "result": {"rows": per_sku},
                    "completed_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                _persist_task(task_id, task_store[task_id])
            append_task_progress(task_id, "优化搜索完成")
        except Exception as e:  # noqa: BLE001
            with task_store_lock:
                task_store[task_id].update({
                    "status": "failed",
                    "error_message": f"优化搜索失败: {e}",
                    "completed_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                _persist_task(task_id, task_store[task_id])

    background_tasks.add_task(run_optimize)
    return {"task_id": task_id, "status": "pending"}

def cleanup_old_tasks(max_age_hours: int = 24):
    """清理旧任务（可选：可以定时运行）"""
    current_time = datetime.now()
    expired_tasks = []
    
    for task_id, task_info in task_store.items():
        created_time = datetime.fromisoformat(task_info["created_time"])
        age_hours = (current_time - created_time).total_seconds() / 3600
        
        if age_hours > max_age_hours:
            expired_tasks.append(task_id)
    
    for task_id in expired_tasks:
        del task_store[task_id]
    
    if expired_tasks:
        logger.info(f"清理了 {len(expired_tasks)} 个过期任务")

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="预测Pipeline API服务 - 异步版本")
    parser.add_argument(
        "--host", 
        type=str, 
        default="0.0.0.0",
        help="服务绑定的主机地址 (默认: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8000,
        help="服务监听的端口号 (默认: 8000)"
    )
    parser.add_argument(
        "--reload", 
        action="store_true",
        help="是否启用热重载 (开发模式)"
    )
    parser.add_argument(
        "--workers", 
        type=int, 
        default=1,
        help="工作进程数量 (默认: 1)"
    )
    parser.add_argument(
        "--log-level", 
        type=str, 
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="日志级别 (默认: INFO)"
    )
    
    return parser.parse_args()

def run_server():
    """主函数，用于启动服务"""
    args = parse_args()
    
    # 设置日志级别
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    logger.info(f"启动预测API服务(异步版本) - 主机: {args.host}, 端口: {args.port}")
    logger.info(f"服务配置 - 重载: {args.reload}, 工作进程: {args.workers}, 日志级别: {args.log_level}")
    logger.info(f"回调配置 - 基础URL: {callback_base_url}, 组织ID: {organization_id}")
    
    import uvicorn
    
    # 启动服务
    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        log_level=args.log_level.lower()
    )

if __name__ == "__main__":
    run_server()
