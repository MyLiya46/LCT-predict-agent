# T02 · 前端就位（frontend-scaffold）

- **任务 ID**：T02
- **标题与目标**：把 `reference_repo/predict-agent/frontend-ref` 原样复制为根目录 `frontend/`，vite proxy 指到后端 `:8000`，`npm install` + `npm run build` 基线绿，作为后续前端任务的唯一工作区。
- **关联文档章节**：feat-icewash.md §10.1（前端以 ref 为主，原地重建）；CLAUDE.md「常用命令」前端节
- **前置依赖 blockedBy**：无

## 实施要点

### 1. 复制前端目录（排除产物）
- 复制 `reference_repo/predict-agent/frontend-ref/` → `frontend/`，排除 `node_modules/`、`dist/`、`preview/`、`design-mockups/`、`tsconfig.tsbuildinfo`、`vite.log`；保留受版本控制的 `package-lock.json`，确保依赖解析可复现。
  ```bash
  mkdir -p frontend && rsync -a --exclude 'node_modules' --exclude 'dist' --exclude 'preview' \
    --exclude 'design-mockups' --exclude 'tsconfig.tsbuildinfo' --exclude 'vite.log' \
    reference_repo/predict-agent/frontend-ref/ frontend/
  ```

### 2. 修正 vite proxy（关键接缝）
- 编辑 `frontend/vite.config.ts`：`server.proxy['/api'].target` 由 `http://127.0.0.1:8001` 改为 `http://127.0.0.1:8000`（对齐 `scripts/start_dev_stack.sh` 后端端口）。`bypass` 逻辑保留（`GET /api` 走 SPA）。

### 3. 依赖与构建
- `cd frontend && npm ci`（严格按保留的 `package-lock.json` 安装依赖）。
- `npm run build`（= `tsc -b && vite build`），确认产物 `dist/` 生成、TS 类型检查零错误。

## 验收标准
- [ ] `cd frontend && npm run build` 成功退出（exit code 0），`dist/index.html` 存在。
- [ ] `Test-Path frontend/package-lock.json` 返回 `True`，且 `cd frontend && npm ci` 成功退出。
- [ ] `grep "target" frontend/vite.config.ts` 显示 `http://127.0.0.1:8000`（非 8001）。
- [ ] `npm run dev` 后浏览器访问 `http://127.0.0.1:5173/login` 能渲染登录页（此时后端未接，登录请求报错属预期）。
- [ ] `frontend/node_modules`、`frontend/dist` 由命令生成，无从 reference 复制来的旧产物。
