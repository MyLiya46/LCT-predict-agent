# T02 · 前端就位（frontend-scaffold）

- 任务 ID：T02
- **标题与目标**：把 `reference_repo/predict-agent/frontend-ref` 原样复制为根目录 `frontend/`，vite proxy 指到后端 `:8000`，`npm install` + `npm run build` 基线绿，作为后续前端任务的唯一工作区。
- **关联文档章节**：feat-icewash.md §10.1（前端以 ref 为主，原地重建）；CLAUDE.md「常用命令」前端节
- 前置依赖 blockedBy：无

## 问题
- 任务 T02 当前需要完成本计划标题对应的交付；旧版计划结构无法被 plan-generator v1.2.0 的结构化校验直接读取。

## 决策
- 保留本计划既有技术边界、参数、实施内容和验收命令；仅补齐 v1.2.0 要求的元数据、章节与结构化执行入口。

## 范围
- 包含：本计划既有实施要点、涉及路径、接口、数据约束和验收项。
- 不包含：改变任务目标、blockedBy 依赖、代码实现或项目业务口径。

## 风险与回滚
- 风险：旧计划正文中的命令或外部服务依赖可能在执行环境中不可用，导致该任务验收失败。
- 回滚：执行前保存本任务涉及文件的补丁；失败时使用 `git apply -R /tmp/T02-plan.patch` 反向应用补丁并恢复前一阶段。

## 实施步骤

### 步骤 1：执行原计划实施内容
- 对象：T02 对应的目标模块、接口和验收对象。
- 动作：按下方保留的原实施内容执行，并使用其中的命令完成验证。
- 参数：严格使用正文中给出的路径、端口、字段、超时、权限和命令参数。
- 文件：docs/plans/T02-frontend-scaffold-2026-09-01.md
- 命令：
  ```bash
  python /c/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T02-frontend-scaffold-2026-09-01.md
  ```
#### 1. 复制前端目录（排除产物）
- 复制 `reference_repo/predict-agent/frontend-ref/` → `frontend/`，排除 `node_modules/`、`dist/`、`preview/`、`design-mockups/`、`tsconfig.tsbuildinfo`、`vite.log`；保留受版本控制的 `package-lock.json`，确保依赖解析可复现。
  ```bash
  mkdir -p frontend && rsync -a --exclude 'node_modules' --exclude 'dist' --exclude 'preview' \
    --exclude 'design-mockups' --exclude 'tsconfig.tsbuildinfo' --exclude 'vite.log' \
    reference_repo/predict-agent/frontend-ref/ frontend/
  ```

#### 2. 修正 vite proxy（关键接缝）
- 编辑 `frontend/vite.config.ts`：`server.proxy['/api'].target` 由 `http://127.0.0.1:8001` 改为 `http://127.0.0.1:8000`（对齐 `scripts/start_dev_stack.sh` 后端端口）。`bypass` 逻辑保留（`GET /api` 走 SPA）。

#### 3. 依赖与构建
- `cd frontend && npm ci`（严格按保留的 `package-lock.json` 安装依赖）。
- `npm run build`（= `tsc -b && vite build`），确认产物 `dist/` 生成、TS 类型检查零错误。

## 完成标准
- 验收命令：
  ```bash
  python /c/Users/jie32.guo/.codex/skills/plan-generator/scripts/plan_state.py lint-plan --plan docs/plans/T02-frontend-scaffold-2026-09-01.md
  ```
- 通过条件：命令退出码为 0，且本节保留的原验收项全部满足。
- [ ] `cd frontend && npm run build` 成功退出（exit code 0），`dist/index.html` 存在。
- [ ] `Test-Path frontend/package-lock.json` 返回 `True`，且 `cd frontend && npm ci` 成功退出。
- [ ] `grep "target" frontend/vite.config.ts` 显示 `http://127.0.0.1:8000`（非 8001）。
- [ ] `npm run dev` 后浏览器访问 `http://127.0.0.1:5173/login` 能渲染登录页（此时后端未接，登录请求报错属预期）。
- [ ] `frontend/node_modules`、`frontend/dist` 由命令生成，无从 reference 复制来的旧产物。
