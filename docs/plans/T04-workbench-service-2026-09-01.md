# T04 · 工作台域服务迁入（workbench-service）

- **任务 ID**：T04
- **标题与目标**：把工作台查询服务迁入 backend 壳；三个新增 Excel 与知识库由 icewash-model 持有、读取和导出，商品成本与价格弹性同步为 PG 工作台缓存，backend/frontend 不直接访问 `docs/`。
- **关联文档章节**：`docs/feat-icewash.md` §3.1、§4.3、§10.2；`backend-ref/app/services/workbench.py`、`backend-ref/app/seed_workbench.py`、`backend-ref/app/api/routes.py`；`frontend-ref/src/api.ts`、`frontend-ref/src/pages/WhatIfPage.tsx`、`frontend-ref/src/pages/StrategyKnowledgePage.tsx`；`docs/UI设计稿/*.xlsx`、`docs/知识库/*.md`
- **前置依赖 blockedBy**：T03
- **状态**：pending

## 实施要点

### 1. 将新增参考资料归属到 icewash-model
- 在目标模型目录创建 `services/icewash-model/data/reference/` 和 `services/icewash-model/data/reference/knowledge/`。
- 将以下文件复制为运行时副本，文件名固定，不允许 backend 运行时从 `docs/` 读取：
  - `docs/UI设计稿/商品成本.xlsx` → `services/icewash-model/data/reference/cost_data.xlsx`；
  - `docs/UI设计稿/价格弹性表.xlsx` → `services/icewash-model/data/reference/price_elasticity.xlsx`；
  - `docs/UI设计稿/模拟策略库.xlsx` → `services/icewash-model/data/reference/strategy_library.xlsx`；
  - `docs/知识库/大家电电商销量因子量化知识库 (2).md` → `services/icewash-model/data/reference/knowledge/sales_factor_knowledge.md`；
  - `docs/知识库/architecture.md` → `services/icewash-model/data/reference/knowledge/architecture.md`。
- `docs/UI设计稿` 和 `docs/知识库` 保留为设计/参考资料；运行时模型统一使用 `services/icewash-model`，目标代码不得 import 任何旧模型目录。

### 2. 在模型侧实现参考数据 loader 和导出接口
- 新建 `services/icewash-model/cbg_fcst_month/reference_data.py`，把 `REFERENCE_DIR` 固定为 `services/icewash-model/data/reference`，仅允许 `cost_data`、`price_elasticity`、`strategy_library` 三个 dataset key。
- 对 `cost_data.xlsx` 强制校验列 `品类`、`型号`、`建议零售价`、`成本价`；对 `price_elasticity.xlsx` 强制校验列 `品类`、`系列`、`型号`、`均价`、`均销`、`价格弹性系数`、`波动分类`、`弹性分类`、`产品分类`；缺列时返回包含文件名和缺列名的 400 错误。
- 对 `strategy_library.xlsx` 固定读取 `Sheet1`，保留所有非空表头列，将每行规范化为 JSON 对象；空表头、重复表头或没有数据行时返回 400。Markdown 只读取 `sales_factor_knowledge.md` 和 `architecture.md`，按“模拟策略库 / 量化知识库 / 推导指南”顺序合并。
- 在 `services/icewash-model/cbg_fcst_month/server.py` 增加内部参考接口：
  - `GET /reference/workbench/{dataset}`：返回 `dataset/source/columns/rows/row_count`；`dataset` 只接受上述三个值；
  - `GET /reference/knowledge/strategy`：返回 `title/source/markdown`，`source` 固定为三个文件名用 `; ` 连接；
  - `POST /reference/workbench/cost_data`：multipart 字段名固定为 `file`，接收 `.csv` 或 `.xlsx`，校验四个成本列后以临时文件替换 `cost_data.xlsx`，返回 `dataset/row_count/source`。
- 参考接口只绑定 icewash 内网监听地址；接口不接受客户端路径，不允许覆盖 `REFERENCE_DIR`，上传失败时保留旧的 `cost_data.xlsx`。

### 3. 让 backend 从模型接口同步 PG 派生缓存
- 新建 `backend/src/app/services/model_reference_client.py`，使用 `ICEWASH_BASE_URL`，默认值为 `http://127.0.0.1:8001`；请求超时固定为 10 秒，失败最多重试 3 次，重试间隔固定为 1 秒。
- 将 `GET /reference/workbench/cost_data` 和 `GET /reference/workbench/price_elasticity` 的规范化 rows 写入 T03 的 `workbench_dataset_rows`：每个 dataset 在同一事务中先删除旧行，再按批次 append；`cost_data` 的索引字段使用 `category=品类、sku=型号`，`price_elasticity` 额外使用 `series=系列`，payload 保留模型导出的全部列。
- `strategy_library`、两个 Markdown 文件不写入 `workbench_dataset_rows`；`GET /api/workbench/knowledge/strategy` 每次通过 `model_reference_client.py` 调用模型知识接口，返回 frontend-ref 要求的 `title/source/markdown`。
- 改造 `backend/src/app/seed_workbench.py`：CSV 与预测输出仍按现有 row cap 幂等导入；成本和价格弹性只能调用模型接口同步，删除直接读取 `docs/UI设计稿`、从 `price_data` 推导成本的代码。
- 在 `backend/src/app/api/workbench.py` 的成本上传处理中，先把 `file` 原样转发至 `POST {ICEWASH_BASE_URL}/reference/workbench/cost_data`，模型返回 200 后再执行 `cost_data` 的 PG 替换同步；模型接口非 2xx 时 backend 返回 400，PG 写入失败时返回 502 并保留模型侧新文件，下一次同步可恢复缓存。

### 4. 保留工作台 API 契约并隔离执行策略
- `backend/src/app/services/workbench.py` 只引用 T03 的 `WorkbenchDatasetRow` 和 PostgreSQL JSONB 查询；将 SQLite `json_each` 替换为 PostgreSQL `jsonb_each`，保留 `DATASET_META` 的 8 个 dataset：`raw_data`、`master_data`、`price_data`、`rebate_data`、`dsi_data`、`cost_data`、`price_elasticity`、`fcst_detail`。
- 新建 `backend/src/app/api/workbench.py`，挂载以下接口并沿用 frontend-ref 参数名：`GET /api/workbench/datasets`、`GET /api/workbench/filter-options/{dataset}`、`GET /api/workbench/tables/{dataset}`、`GET /api/workbench/charts/{dataset}`、`POST /api/workbench/upload/cost_data`、`GET /api/workbench/knowledge/strategy`。
- 工作台所有查询使用 `chat:read`，成本上传使用 `chat:send`；表格默认 `page=1&page_size=50`，上传字段名固定为 `file`，按 `品类+型号` 覆盖 PG 缓存。
- 不在 T04 复制或生成可执行策略目录；`whatif` 的可执行策略和公式只由 icewash-model 的 `whatif` 代码提供，策略 Excel 仅作为模型侧知识展示来源，T05/T14 的策略接口继续沿用模型代码契约。

### 5. 生命周期、修复命令与测试
- 在 backend `main.py` lifespan 中按“PG migration 完成 → CSV/预测输出种子 → 模型参考数据同步 → 应用启动”顺序执行；模型参考接口不可用或列校验失败时阻止启动，并记录具体 URL、文件名和列名。
- 更新 `scripts/start_dev_stack.sh`：backend 启动前先确认 `http://127.0.0.1:8001/health` 返回 HTTP 200 且 body 含 `status=healthy`；最多轮询 30 次、每次间隔 2 秒，超时输出模型日志路径并以非零状态退出，不进入 backend 启动阶段。
- 新增 `scripts/sync_workbench_reference.sh`，在仓库根目录的 Git Bash 中执行 `cd backend && uv run python -m app.seed_workbench --reference-only`，用于模型恢复后重新同步 `cost_data` 和 `price_elasticity`；该命令不得读取 `docs/`。
- 新增 `backend/tests/test_workbench_service.py` 和 `backend/tests/test_model_reference_client.py`：使用固定 mock response 验证 8 个 dataset 元数据、JSONB 筛选、分页默认值、两张模型参考表有行、重复同步不增加行数、成本上传转发及权限返回码。

## 验收标准
- [ ] `uv run pytest tests/test_workbench_service.py tests/test_model_reference_client.py` 通过；重复执行参考同步前后，`cost_data` 与 `price_elasticity` 行数不增加。
- [ ] 模型启动后，`curl -s http://127.0.0.1:8001/reference/workbench/cost_data` 和 `curl -s http://127.0.0.1:8001/reference/workbench/price_elasticity` 返回 `row_count>0`、`source` 位于 `services/icewash-model/data/reference/`，`curl -s http://127.0.0.1:8001/reference/knowledge/strategy` 返回三个文件名和非空 `markdown`。
- [ ] 执行 `bash scripts/start_dev_stack.sh` 时，模型未达到 `health.status=healthy` 会在 backend 启动前失败；模型健康后 backend 才进入参考数据同步和 `:8000` 启动阶段。
- [ ] `curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "http://127.0.0.1:8000/api/workbench/datasets"` 返回 8 个元素，元素含 `key/title/group/row_count`。
- [ ] `curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "http://127.0.0.1:8000/api/workbench/tables/price_elasticity?category=冰箱&page=1&page_size=5"` 返回 `columns/rows/total`，`total` 大于 0；`cost_data` 查询同样返回非空行。
- [ ] `curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "http://127.0.0.1:8000/api/workbench/knowledge/strategy"` 返回 `title/source/markdown`，且 `source` 同时包含 `strategy_library.xlsx`、`sales_factor_knowledge.md`、`architecture.md`。
- [ ] 使用 `chat:read` 用户查询工作台返回 200；无登录请求返回 401；仅有 `chat:read` 的用户上传成本返回 403；`grep -RInE "docs/UI设计稿|docs/知识库" backend/src/app` 零命中。
- [ ] `psql agent_platform -c "SELECT dataset, count(*) FROM workbench_dataset_rows GROUP BY dataset ORDER BY dataset"` 返回 8 个 dataset，且 `cost_data`、`price_elasticity` 行数均大于 0。
