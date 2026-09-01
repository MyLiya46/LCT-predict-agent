# PRD：通用 AI Agent 平台（内部人机对话助手）

> 版本：v0.10
> 日期：2026-08-21  

---

## 目录

- [PRD：通用 AI Agent 平台（内部人机对话助手）](#prd通用-ai-agent-平台内部人机对话助手)
  - [目录](#目录)
  - [1. 概述](#1-概述)
    - [1.1 背景与定位](#11-背景与定位)
    - [1.2 目标与非目标](#12-目标与非目标)
    - [1.3 本期明确不做（禁止展开）](#13-本期明确不做禁止展开)
    - [1.4 术语表](#14-术语表)
    - [1.5 假设汇总（可检索）](#15-假设汇总可检索)
  - [2. 目标用户与会话角色](#2-目标用户与会话角色)
    - [2.1 用户画像](#21-用户画像)
    - [2.2 双端功能边界](#22-双端功能边界)
  - [3. 功能分级清单（P0/P1/P2）](#3-功能分级清单p0p1p2)
    - [3.1 P0 MVP 功能](#31-p0-mvp-功能)
    - [3.2 P1 增强功能](#32-p1-增强功能)
    - [3.3 P2 远期功能](#33-p2-远期功能)
    - [3.4 禁止展开条目](#34-禁止展开条目)
  - [4. 总体架构与技术选型](#4-总体架构与技术选型)
    - [4.1 顶层架构图](#41-顶层架构图)
    - [4.2 模块划分（高内聚 · 低耦合 · 依赖单向）](#42-模块划分高内聚--低耦合--依赖单向)
    - [4.3 技术栈与选型推荐](#43-技术栈与选型推荐)
  - [5. 用户端 P0 详设](#5-用户端-p0-详设)
    - [5.1 功能模块](#51-功能模块)
    - [5.2 接口清单](#52-接口清单)
    - [5.3 主流程时序](#53-主流程时序)
  - [6. 管理员端 P0 详设](#6-管理员端-p0-详设)
    - [6.1 功能模块](#61-功能模块)
    - [6.2 接口清单](#62-接口清单)
  - [7. Agent 执行引擎与工具编排](#7-agent-执行引擎与工具编排)
    - [7.1 Agent 执行循环](#71-agent-执行循环)
    - [7.2 工具调用协议](#72-工具调用协议)
    - [7.3 错误重试与降级策略](#73-错误重试与降级策略)
    - [7.4 中断与恢复](#74-中断与恢复)
    - [7.5 场景编排](#75-场景编排)
    - [7.6 自定义预测模型接入规范](#76-自定义预测模型接入规范)
  - [8. 数据源接入与沙箱隔离](#8-数据源接入与沙箱隔离)
    - [8.1 结构化数据源接入](#81-结构化数据源接入)
    - [8.2 沙箱隔离](#82-沙箱隔离)
  - [9. 权限与隔离体系](#9-权限与隔离体系)
    - [9.1 RBAC 权限模型](#91-rbac-权限模型)
    - [9.2 权限矩阵](#92-权限矩阵)
    - [9.3 三类隔离闭环](#93-三类隔离闭环)
    - [9.4 审计与越权响应](#94-审计与越权响应)
  - [10. 全链路追溯日志](#10-全链路追溯日志)
    - [10.1 追溯目标](#101-追溯目标)
    - [10.2 事件模型与字段](#102-事件模型与字段)
    - [10.3 还原能力验证](#103-还原能力验证)
  - [11. 数据模型与主流程](#11-数据模型与主流程)
    - [11.1 核心实体概览](#111-核心实体概览)
    - [11.2 关键数据表字段](#112-关键数据表字段)
    - [11.3 主流程时序](#113-主流程时序)
  - [12. 接口规范](#12-接口规范)
    - [12.1 接口约定](#121-接口约定)
    - [12.2 用户端接口](#122-用户端接口)
    - [12.3 管理员端接口](#123-管理员端接口)
    - [12.4 SSE 事件协议](#124-sse-事件协议)
    - [12.5 鉴权与错误码](#125-鉴权与错误码)
  - [13. 部署与运维](#13-部署与运维)
    - [13.1 部署拓扑与 compose 编排](#131-部署拓扑与-compose-编排)
    - [13.2 数据库初始化与依赖顺序](#132-数据库初始化与依赖顺序)
    - [13.3 环境与密钥管理](#133-环境与密钥管理)
    - [13.4 健康检查、监控与备份](#134-健康检查监控与备份)
  - [14. 路线图与验收要点](#14-路线图与验收要点)
    - [14.1 里程碑总览](#141-里程碑总览)
    - [14.2 P0 验收清单](#142-p0-验收清单)
    - [14.3 P1 / P2 节奏建议](#143-p1--p2-节奏建议)
  - [15. 风险与开放问题](#15-风险与开放问题)
    - [15.1 风险清单](#151-风险清单)
    - [15.2 开放问题](#152-开放问题)
  - [附录 A：双端权限矩阵核验表](#附录-a双端权限矩阵核验表)
  - [附录 B：追溯日志字段还原对照](#附录-b追溯日志字段还原对照)

---

## 1. 概述

### 1.1 背景与定位

技术部门为业务部门搭建一个人机对话智能助手平台，首期承载两个业务场景：

1. 用户通过自然语言对话，**自动查询历史销售数据**；
2. 调用**销售预测工具**完成预测，结果返回前端**可视化展示**；
3. 全过程**可追溯**——用户能看到「发出一条消息后，后端执行了哪些工具、每步结果是什么、最终返回了什么」。

平台定位为**通用 AI Agent 平台**（形态参考 ChatGPT 网页端），面向公司内部团队**私有化部署**，采用「用户端 + 管理员端多角色设计」，并按通用 Agent 平台能力标准搭建，为后续接入更多业务工具（如自定义预测模型）预留高扩展性。

**为什么从销售数据场景起步**：它天然覆盖 Agent 平台三要素——自然语言理解（查询意图）、工具调用（数据查询/预测）、结构化结果可视化（表格/图表），是验证平台核心链路最集约的样本；同时为后续通用工具接入沉淀协议与隔离能力。

### 1.2 目标与非目标

| 目标 | 非目标 |
|---|---|
| 交付可用的对话查询 + 销售预测 MVP | 公网计费、多租户、开放注册市场 |
| 全链路可追溯（每步工具执行可还原） | 公网直接暴露、开放 API（P2 再议） |
| 双端多角色 + RBAC 权限模型闭环 | 文档型 RAG 知识库（P1） |
| Docker Compose 一键私有化部署 | SQL 直连数据源（P1） |
| 多供应商 LLM 抽象层就位 | 管理台数据看板（P1）等 P1/P2 清单内容 |

### 1.3 本期明确不做（禁止展开）

- 公网计费、多租户、开放注册市场、公网直接暴露；
- 普通用户自助注册为管理员；
- 自定义角色界面化配置（RBAC 骨架保留，P1 再做）；
- RAG 文档知识库、SQL 直连、多模型切换、数据看板、审计导出等（列入 3.2/3.3）。

### 1.4 术语表

| 缩写 | 全称/中文 | 说明 |
|---|---|---|
| Agent | AI Agent | 能自主规划、调用工具并完成任务的智能体 |
| LLM | Large Language Model，大语言模型 | 对话与任务拆解的推理基座 |
| RAG | Retrieval-Augmented Generation，检索增强生成 | 文档外挂知识库技术，P1 再做 |
| JWT | JSON Web Token | 无状态访问令牌，本平台认证基础 |
| OAuth | Open Authorization | 授权协议，P1 接入 GitHub 企业登录 |
| RBAC | Role-Based Access Control，基于角色的访问控制 | 本平台权限模型 |
| SSE | Server-Sent Events | HTTP 单向事件流，用于流式输出 |
| IAM | Identity and Access Management | 身份与访问管理（延伸概念） |
| JSONB | PostgreSQL 二进制 JSON 类型 | 存储工具入参/结果、事件链 |
| SQL | Structured Query Language | 结构化查询语言 |
| Worker | 后台任务执行单元 | 平台独立于 API 的异步执行进程，P0 用轻量进程内队列，P1 升级为独立进程 |
| MCP | 预留将标注为「内部工具协议即可」 | 工具协议扩展点，本期不使用 |

（补充：`BFF` = Backend for Frontend，前端网关；`ORM` = Object-Relational Mapping 对象关系映射；`ER` = Entity-Relationship 实体关系。）

### 1.5 假设汇总（可检索）

| 编号 | 假设内容 | 影响范围 |
|---|---|---|
| H1 | 内部注册用户 ≤200，同时在线 ≤50，并发工作会话 ≤30；单机/单实例可承载，预留水平扩容 | 容量设计 |
| H2 | 销售数据存放于内部数据服务：HTTP API + JSON 返回（如 `http://sales-data.internal/api/v1/query`），P0 内网免登 + 服务账号 Token 访问；SQL 直连放 P1 | 数据源接入 |
| H3 | 历史对话默认保留 180 天，到期归档/删除；审计日志保留 365 天，均可配置 | 数据保留 |
| H4 | 管理员端首版 = 最小可用管理台（用户管理 + 工具/数据源管理 + LLM 配置 + 日志审计查看），统计图表类放 P1 | 管理端范围 |
| H5 | 模型服务采用 OpenAI 协议兼容接口（`/v1/chat/completions`、`/v1/models`），自建或第三方供应商均可 | LLM 接入 |
| H6 | P0 允许邮箱+密码自助注册，仅限内部邮箱后缀白名单；新用户默认普通用户角色 | 账号体系 |
| H7 | 部署形态为内网单台服务器（或多机共享入口）Docker Compose，PostgreSQL 单实例 | 部署形态 |
| H8 | 工具执行语言为 Python 3.11，与后端一致，打包为独立镜像进沙箱 | 沙箱工具 |
| H9 | 个人设置默认值：注册时昵称默认取邮箱 @ 前缀；昵称 1~32 字符可含中文；P0 头像菜单仅展示「基础设置」入口，模型设置入口随 P1 上线 | 个人设置（【变更 v0.10】） |
| H10 | BYOK 安全与降级：用户模型 API Key 与管理员 LLM 配置同标准加密存储、仅本人可见；用户模型不可用时自动降级平台默认模型 | 用户级模型配置（P1 预留） |
| H11 | 置顶交互默认值：置顶无数量上限；置顶/取消置顶后列表即时刷新排序 | 会话列表（【变更 v0.10】） |

---

## 2. 目标用户与会话角色

### 2.1 用户画像

**业务人员（普通用户）**
- 特征：日均 5~10 次对话，查询历史销售、发起预测；对技术细节无感知。
- 诉求：自然语言到达结果、可视化清晰、关注追溯解释（知道背后用了什么数据/模型）。
- 行为：新建/管理会话，看重流式反馈与透明执行过程。

**技术管理员（管理员）**
- 特征：技术部/平台运营人员，负责账号、工具、模型、日志日常治理。
- 诉求：用户管理、工具/数据源启停、LLM 配置、全量审计检索。
- 行为：操作留痕、越权拦截、异常定位。

### 2.2 双端功能边界

| 能力域 | 用户端（普通用户） | 管理员端（管理员） |
|---|---|---|
| 会话/对话 | ✅ 对话、管理自己会话 | ✅ 只读审计全量会话/日志 |
| 追溯日志 | ✅ 查看自己会话的执行过程 | ✅ 全量检索 + 审计留痕 |
| 数据源/工具 | ❌ 不可见/不可配置 | ✅ 注册、启停、参数配置、连通性测试 |
| LLM 配置 | ❌（P1 预留：BYOK 用户级模型配置，见 3.2 P1-10） | ✅ 供应商/端点/Key/模型/默认模型/健康检查 |
| 系统参数 | ❌ | ✅ 保留天数、并发上限、默认模型等 |
| 管理台首页 | ❌ | ✅ 导航入口（按权限点渲染） |
| 个人设置 | ✅ 基础设置（昵称/密码修改、邮箱只读展示）；模型设置页 P1 预留 | ✅ 基础设置（与用户端同套页面，【变更 v0.10】） |

---

## 3. 功能分级清单（P0/P1/P2）

### 3.1 P0 MVP 功能

**P0-A 账号与权限体系**

| 编号 | 功能 | 目标 | 分级理由 |
|---|---|---|---|
| P0-A1 | 注册/登录/令牌管理 | 邮箱+密码注册（内部白名单）、登录、JWT 无状态认证、刷新令牌、登出、重置密码 | 平台入口，无它不可用 |
| P0-A2 | RBAC 双角色与权限校验 | 预置普通用户/管理员；后端中间件 + 前端路由守卫双重校验 | 双端边界安全基线，管理接口必须受控 |
| P0-A3 | 数据权限隔离 | 用户仅能访问本人会话/消息/追溯日志；管理员只读审计全量 | 用户隔离/会话隔离数据层落地 |
| P0-A4 | 管理员账号初始化 | 首启种子脚本，由技术部线下创建/指派 | 【确认】管理员线下创建的落地 |

**P0-B 用户端（业务部门）**

| 编号 | 功能 | 目标 | 分级理由 |
|---|---|---|---|
| P0-B1 | 对话工作台 | ChatGPT 风格：会话列表 + 消息流；markdown/代码块/表格/图表渲染；发送/停止 | 平台主界面，核心入口 |
| P0-B2 | 会话管理 | 新建/列表/重命名/删除/恢复历史、**置顶**（hover 菜单操作，【变更 v0.10】）；**会话间上下文完全隔离、互不串扰** | 会话隔离前端载体 |
| P0-B3 | 流式展示 | 用户消息、Agent 中间过程、工具调用状态、最终回复实时渲染 | Agent 执行耗时，无即时反馈不可用 |
| P0-B4 | 全链路追溯面板 | 单会话执行轨迹：消息→工具名→入参→结果→最终回复，失败原因可见 | 「全过程可追溯」核心差异化能力，对标 deepseek-harness |
| P0-B5 | 销售数据查询 | 自然语言 → 结构化查询（销售数据 API），结果表格渲染 | 首期业务场景 1 |
| P0-B6 | 销售预测与可视化 | 对话触发预测工具，结果图表可视化 | 首期业务场景 2 |
| **P0-B7** | **停止生成** | 用户在流式执行中停止生成，Agent 收到中断信号，终止当前循环，已完成工具结果落库、未完成不被写入 | 流式体验必需；直接支撑对话交互闭环（P0-B3） |
| **P0-B8** | **个人设置-基础信息** | 头像菜单 → 基础设置页：昵称修改、密码修改（走 `PATCH /auth/password`）、**邮箱只读展示不提供修改入口**（【确认】） | 账号自助维护闭环；模型设置（BYOK）为 P1 预留见 P1-10（【变更 v0.10】） |

**P0-C Agent 执行引擎与工具**

| 编号 | 功能 | 目标 | 分级理由 |
|---|---|---|---|
| P0-C1 | Agent 执行循环 | LLM 规划→工具调用→结果回灌→错误重试/降级→最终回复；支持中断 | 【确认】参考 Claude Code 执行循环，Agent 平台标配 |
| P0-C2 | 工具调用协议 | 工具统一 schema（名称/描述/入参/出参）、参数校验、结构化结果、错误语义 | 多工具统一接入前提 |
| P0-C3 | 工具注册与场景编排 | 工具中心（注册/启停/校验）；「场景 = 模型配置 + 工具集 + 系统提示词」可组合 | 高扩展性核心，自定义预测模型按此规范接入 |
| P0-C4 | 沙箱执行环境 | 容器化执行工具代码 + 内网白名单出网 + 资源/超时限制 | 【确认】沙箱隔离，外部不可控代码安全边界 |
| P0-C5 | 全链路追溯日志 | 事件链式记录 Agent 每一步，可完整还原一次执行 | 「不可追溯则不做」硬性要求 |
| P0-C6 | SSE 事件通道 | SSE 事件：agent_process / tool_call / tool_result / tool_error / content_delta / done / error | 流式展示服务端基础 |

**P0-D 管理员端（最小可用管理台，【假设 H4】）**

| 编号 | 功能 | 目标 | 分级理由 |
|---|---|---|---|
| P0-D1 | 用户管理 | 列表/搜索/创建/禁用/启用/重置密码/分配角色 | 账号运营必需 |
| P0-D2 | 工具/数据源管理 | 注册/启停/参数配置/连通性测试 | 工具化能力运营必需 |
| P0-D3 | LLM 模型配置 | 多供应商/端点/Key/模型管理、默认模型、健康检查 | 多供应商抽象层（【确认】）运营落地 |
| P0-D4 | 会话与日志审计 | 全量会话/消息/工具调用/追溯日志只读检索；**审计行为自身留痕** | 管理员职责，权限越大留痕越重 |
| P0-D5 | 系统参数 | 会话保留天数、并发上限、默认模型等 | 运维可控性 |

**P0-E 平台基础设施**

| 编号 | 功能 | 目标 | 分级理由 |
|---|---|---|---|
| P0-E1 | docker-compose 一键部署 | 应用 + 数据库 + 沙箱运行时编排；PostgreSQL 初始化与依赖顺序；健康检查 | 交付与验收前提 |
| P0-E2 | 审计与异常框架 | 登录/越权访问/敏感操作审计；统一错误码与异常日志 | 「越权即拒绝并写入审计」要求落地 |

### 3.2 P1 增强功能

| 编号 | 功能 | 目标 | 分级理由 |
|---|---|---|---|
| P1-1 | GitHub OAuth 企业登录 | 免密单点登录 | 账号体系 P0 已闭环，OAuth 安全回调需专项配置，增强项 |
| P1-2 | 自定义角色与权限点管理 | 角色分级、自定义角色组合 | RBAC 骨架已预留，界面化配置一次性投入大 |
| P1-3 | 文档型 RAG 知识库 | 非结构化文档问答 | 跨入结构化数据域外，需向量库与文档管线，成本高 |
| P1-4 | 多模型切换与路由 | 场景/用户级模型选择、故障切换 | LLM 抽象层 P0 已就位，产品化路由管理次期做 |
| P1-5 | SQL 直连数据源 | 支持 SQL/数据库查询工具 | 直连库涉及账号/脱敏/审计治理，安全评审成本高 |
| P1-6 | 管理台数据看板 | 用量/Token/工具调用统计图表 | 运营优化，非闭环必需（与 H4 一致） |
| P1-7 | 操作审计导出 | 审计日志 CSV/JSON 导出 | 合规增强 |
| P1-8 | 会话导出与只读分享 | 结果协作沉淀 | 非核心，协作增强 |
| P1-9 | 长任务异步队列 | 大批量预测批处理 + 进度推送 | 首期并发 ≤30 会话，队列机暂不需要，扩量再上 |
| P1-10 | 用户级模型配置（BYOK） | 普通用户配置个人模型（供应商/类型/ID/URL/APIKey），会话优先用用户自己的模型，未配置则用平台默认；数据模型预留 `user_llm_config` 表（【预留】，见 11.2） | LLM 抽象层 P0 已就位；用户级配置涉及 Key 保管与降级策略（H10），次期做；双端边界影响：用户端 LLM 配置能力由 ❌ 变 P1 提供（【变更 v0.10】） |

### 3.3 P2 远期功能

| 编号 | 功能 | 目标 | 分级理由 |
|---|---|---|---|
| P2-1 | 多模型负载均衡与故障切换深化 | 规模化模型调度 | 依赖 P1-4 后运营数据支撑 |
| P2-2 | 部门/团队级数据权限 | 数据源级权限细分 | 需组织架构模型支撑，首期无诉求 |
| P2-3 | 会话智能摘要与自动归档 | 长会话治理 | 需评估既有数据与体验 |
| P2-4 | 沙箱强隔离升级（gVisor/Kata） | 纵深安全 | 当前威胁模型下 Docker 限制已够，成本高 |
| P2-5 | 内部工具/提示词市场 | 跨团队复用 | 需工具生态成熟后才有价值 |
| P2-6 | 开放 API 与外部系统集成 | 平台能力外溢 | 需网关/限流设计，后置 |
| P2-7 | 限流与 QPS 精细化治理 | 高并发加固 | 内部私有化场景暂不触发 |

### 3.4 禁止展开条目

公网计费、多租户、开放注册市场、公网直接暴露、普通用户自助注册为管理员。以上在 P0 均不设计、不展开，仅在 P1/P2 清单中列名。

---

## 4. 总体架构与技术选型

### 4.1 顶层架构图

```
┌───────────────────────── 浏览器 ─────────────────────────┐
│        用户端 (Vue3 SPA)          管理员端 (Vue3 SPA)      │
│  对话工作台·会话管理·追溯面板   用户/工具/LLM管理·日志审计   │
└────────────────────────────┬──────────────────────────────┘
                   HTTPS / JWT（同一入口按角色分流）
┌────────────────────────────▼──────────────────────────────┐
│                      FastAPI 应用层                        │
│  ┌─────────────── 认证/权限(RBAC) ──────────────┐          │
│  │ Auth│RBAC│会话模块│追溯模块│管理端模块│SSE│   │          │
│  └───────────────┬──────┬──────┬──────┬──────┘            │
└───────────────────┼──────┼──────┼──────┼──────────────────┘
                    ▼      ▼      ▼      ▼
        ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
        │Postgres │ │Agent执行 │ │沙箱管理器│ │ LLM 抽象 │
        │JSONB/CTE│ │引擎·编排 │ │容器运行池│ │ OpenAPI │
        └─────────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘
                         └──────┬─────┴───────┐    │
                                ▼             ▼    ▼
                        内网业务服务：销售数据API / 模型服务
```

### 4.2 模块划分（高内聚 · 低耦合 · 依赖单向）

```
api/           HTTP 层：路由、鉴权、入参校验、SSE 出口        依赖：无
auth/          JWT 签发/校验、Register/Login、密码hash       依赖：无
rbac/          权限点定义、角色绑定、鉴权依赖库               依赖：auth
chat/          会话/消息 CRUD、上下文组装、发送编排            依赖：rbac, agent
agent_engine/  执行循环、状态机、中断、重试/降级              依赖：tools, sandbox, datasource, tracing
tools/         注册中心、schema校验、启停、场景编排            依赖：rbac
sandbox/       容器生命周期、出网白名单、资源/超时限制         依赖：config
datasource/    结构化数据源类型化封装、Token 保管             依赖：config
tracing/       事件链追加、审计事件、还原查询                  依赖：chat, agent_engine
sse/           连接管理、事件发布/订阅                       依赖：无（被调）
models/        SQLAlchemy ORM 与迁移                       依赖：无
config/        pydantic-settings 环境配置                   依赖：无
background/    长任务队列预留位（本期空实现）                 依赖：无
```

依赖方向：`api → (auth → rbac) → chat → agent_engine → tools → sandbox/datasource`，单向无环；`tracing` 被 agent_engine 与 chat 依赖；`sse` 仅被 api 调用。

**为什么这样切**：功能只向内依赖、不向外暴露概念；后续接入新工具/新数据源仅扩展 `tools`/`datasource`，不动其他模块，符合高扩展目标（【确认】）。

### 4.3 技术栈与选型推荐

| 域 | 选型 | 推荐理由 / 取舍 |
|---|---|---|
| 后端 | **FastAPI**（Python 3.11+） | 异步原生适合 SSE 与高并发 IO；Pydantic 天然校验工具 schema；生态成熟 |
| 前端 | **Vue 3 + Vite + TypeScript** | 组合式 API + Vite 构建，契合流式/表格式双模式应用 |
| UI 组件库 | **Element Plus** + **ECharts** | 管理端表格/表单密集场景主场；对话流式区自定义 markdown 渲染；ECharts 图表成熟稳定 |
| 数据库 | **PostgreSQL 15+** | JSONB+GIN 承载工具入参/结果与事件链，递归 CTE 还原层级；pgvector 为 P1 RAG 预留免迁移通道 |
| 沙箱 | **Docker 受限运行时**（只读 rootfs、非 root、资源/超时限制、iptables 出网白名单默认拒绝公网） | 内部威胁模型下够用；gVisor/Kata 升级列入 P2 |
| 流式通道 | **SSE** | HTTP 天然兼容代理/自动重连；「停止」用独立 `POST /stop` 实现 |
| 权限模型 | **RBAC 表驱动**（角色/权限点/角色-权限三表） | P0 与硬编码几乎同成本，天然支持 P1 自定义角色 |
| 部署 | **Docker + docker-compose** | 单机一键；PostgreSQL 初始化 + 依赖顺序见第 13 章 |
| 环境管理 | **uv + venv**，依赖锁定文件 `uv.lock` 纳入版本管理 | 可复现构建、团队一致 |

**为什么不用刀 MySQL / Ant Design Vue / WebSocket / Casbin / Podman / K8s**：已在第 1 轮对比表给出理由（JSONB 与 CTE 缺失、管理后台能力与生态、单向推送无需双工、P0 成本与 P1 需求）、团队技能栈与规模错配，均不入选。

---

## 5. 用户端 P0 详设

### 5.1 功能模块

**登录页（公共入口）**
- 邮箱 + 密码登录；内部邮箱白名单注册。
- 成功后：`/auth/me` 返回 roles 与权限点 → **按权限点渲染导航**：普通用户仅见对话，管理员额外见管理台入口。

**会话列表**
- 展示本人全部会话（分页），新建/重命名/删除/恢复历史。
- **hover 编辑菜单（【变更 v0.10】）**：每项（conv-item）悬停时右侧出现 `...` 按钮 → 点击弹出菜单：重命名、删除、置顶/取消置顶；重命名/删除复用既有接口（`PATCH/DELETE /conversations/{id}`），置顶走 `PATCH /conversations/{id}/pin`。
- **排序规则（【变更 v0.10】）**：置顶项排最前（按置顶时间倒序），未置顶项按更新时间倒序。
- 会话隔离：`WHERE conversation_id = {id} AND owner_id = {me}` 硬条件。

**对话工作台**
- 消息流：用户/助手气泡、markdown、代码块、表格、图表。
- 流式：用户消息实时显示，Agent 中间过程、工具调用状态实时渲染，最终回复逐字追加。
- 失败：流式中断 → 前端提示 + SSE 自动重连；API 错误按错误码表处理。

**追溯面板**（对话工作台内嵌抽屉）
- 每轮回复对应该轮 `trace`：消息 → 工具名 → 入参 → 结果 → 模型最终回复。
- 工具项展开/折叠；失败项红框「失败: 原因」「已重试 N 次 / 降级 X」。
- 字段级还原：`trace_id → node → events` 完整链，见 10.2。

**聊天输入与停止**
- 输入框 + 发送；`POST /chat/conversations/{id}/messages` 触发会话流。
- 「停止」调 `POST /chat/conversations/{id}/messages/{mid}/stop`，服务端 `cancel_event` 终止当前循环；单会话单字节级（同一时间一个会话只允许一个活动 flow，防止并发写同一上下文）。

**失败处理**
- 流断开：前端重连；LLM 超时/沙箱超时：agent_process 记录「超时 → 重试/降级」并继续。
- **注册/登录错误提示（【变更 v0.10】，三层方案【确认】）**：
  a. 前端注册/登录表单提交前前置校验（邮箱格式、白名单后缀、密码强度规则提示），提交前拦截大部分错误；
  b. 后端返回可读 message（如「邮箱后缀不在白名单内（允许：@corp.com）」「密码必须同时包含大小写字母与数字」），响应不裸堆技术异常堆栈，完整堆栈仅留后端日志；
  c. 前端统一展示后端 message 而非仅错误码，错误码仅作技术标识。

**头像菜单与个人设置（【变更 v0.10】）**
- 入口：点击头像弹出菜单栏 →「基础设置」页（P0 头像菜单仅展示此入口，【假设 H9】）。
- 基础设置：昵称可改（`PATCH /auth/me`）、密码可改（`PATCH /auth/password`，需校验原密码）、**邮箱只读展示、不提供修改入口**（【确认】）。
- 「模型设置」页为 P1 预留（BYOK 用户级模型配置，见 3.2 P1-10）：本期仅列入口不实现，不展开 P1 设计。
- 修改昵称/密码为敏感操作，写入审计（见 9.4）。

### 5.2 接口清单

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | `/auth/register` | 内部邮箱注册 | 未认证 |
| POST | `/auth/login` | 登录，返回 access+refresh | 未认证 |
| GET | `/auth/me` | 当前用户信息+权限点 | 已认证 |
| POST | `/auth/refresh` | 刷新令牌 | — |
| POST | `/auth/logout` | 注销+吊销 refresh | 已认证 |
| PATCH | `/auth/password` | 修改密码（校验原密码，【变更 v0.10】） | 已认证 |
| PATCH | `/auth/me` | 更新昵称（【变更 v0.10】） | 已认证 |
| GET | `/conversations` | 我的会话列表（分页） | 本人 |
| POST | `/conversations` | 新建会话 | 本人 |
| GET | `/conversations/{id}` | 会话详情 | 本人 |
| PATCH | `/conversations/{id}` | 重命名 | 本人 |
| PATCH | `/conversations/{id}/pin` | 置顶/取消置顶（body `{pinned}`，【变更 v0.10】） | 本人 |
| DELETE | `/conversations/{id}` | 删除（级联消息/工具/事件） | 本人 |
| POST | `/conversations/{id}/messages` | 触发 SSESTREAM 会话 | 本人 |
| POST | `/conversations/{id}/messages/{mid}/stop` | 停止当前生成 | 本人 |
| GET | `/conversations/{id}/messages` | 历史消息分页 | 本人 |
| GET | `/conversations/{id}/messages/{mid}/trace` | 追溯事件链 | 本人 |
| GET | `/conversations/{id}/messages/{mid}/trace/export` | 可读文本导出 | 本人 |

公共约定：响应统一 `{code, message, data}`；错误码表见 12.5；ID 全部 UUID；分页 cursor 制。

### 5.3 主流程时序

```
前端           FastAPI            AgentEngine          沙箱           LLM
 │ POST messages │                    │                │               │
 │──────────────▶│ 鉴权+建message     │                │               │
 │               │─创建 trace─▶      │                │               │
 │ SSE open      │                   │ prompt 组装     │               │
 │◀ message.created─│                │  LLM 调用───────┴──────────────▶│
 │◀ tool.call / tool.result（含重试）│  ◀──执行──       │               │
 │◀ agent.process（阶段/重试/降级）  │  ◀──循环继续──   │               │
 │◀ done（最终回复已持久化）          │                                │
```

**为什么单会话单字节级**：隔离覆盖「同一会话并发写」与「同一用户跨会话隔离」两层；单会话强制串行避免上下文竞争。

---

## 6. 管理员端 P0 详设

### 6.1 功能模块

**用户管理**
- 列表/搜索（邮箱、昵称、角色）/创建/禁用/启用/重置密码/分配角色。
- 管理操作均写入 `audit_log`（操作者 + 时间 + 目标 + 摘要）。
- **不能自禁用 / 不能移除最后一名管理员**（防锁死，编辑校验）。

**工具 / 数据源管理**
- 工具中心：注册、启停、schema 校验、参数配置、连通性测试。
- 数据源：类型化配置（HTTP API / 内网服务 Token 等），Token 加密存储（后端密钥 + 安全存储）。
- 启停即时生效（配置热更新，通过 `GET /config/effective` 支持运行时校验）。

**LLM 配置管理**
- 供应商 CRUD（OpenAI 协议兼容端点）、模型管理、Key 管理（加密存储）、默认模型、健康检查（`/v1/models` 可达性）。
- 多供应商抽象层：统一 `chat(messages, tools) → stream`，供应商适配器管理（第 7.2 节）。

**会话 / 日志审计**
- 全量会话/消息/工具调用/追溯日志只读检索（时间、用户、工具名、状态过滤）。
- **审计行为自身留痕**：所有只读检索本身写入追踪审计（audit_log type=audit.view）。

**系统参数**
- 会话保留天数、并发上限、默认模型、沙箱超时、重试次数等；修改写审计。

**失败处理**
- 数据源连通性测试失败：返回「连接失败: 原因」，不落状态变更。
- 模型健康检查失败：标记该供应商状态为 unhealthy，`/auth/me` 与调用处提示，不影响其他供应商。

### 6.2 接口清单

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | `/admin/users` | 用户分页列表/搜索 | admin |
| POST | `/admin/users` | 创建用户 | admin |
| PATCH | `/admin/users/{id}` | 编辑（角色/状态/重置密码） | admin |
| POST | `/admin/users/{id}/reset-password` | 重置密码 | admin |
| GET | `/admin/tools` | 工具列表 | admin |
| POST | `/admin/tools` | 注册工具 | admin |
| PATCH | `/admin/tools/{id}` | 启停/参数配置 | admin |
| POST | `/admin/tools/{id}/test` | 连通性测试 | admin |
| GET | `/admin/datasources` | 数据源列表 | admin |
| POST | `/admin/datasources` | 注册数据源 | admin |
| PATCH | `/admin/datasources/{id}` | 编辑/测试 | admin |
| GET | `/admin/llm` | 供应商/模型列表 | admin |
| POST | `/admin/llm` | 新增供应商 | admin |
| PATCH | `/admin/llm/{id}` | 编辑 Key/端点/默认模型 | admin |
| POST | `/admin/llm/{id}/health` | 健康检查 | admin |
| GET | `/admin/config` | 系统参数 | admin |
| PATCH | `/admin/config` | 修改系统参数 | admin |
| GET | `/admin/audits` | 审计日志列表 | admin |
| GET | `/admin/audits/{id}` | 审计详情 | admin |
| POST | `/admin/audits/export` | 审计导出（P1 占位） | admin |

**关键管控规则**：所有 `/admin/**` 走 RBAC 中间件（权限点 `adm`）；数据隔离以各模块的 owner/tenant 条件为准；只读检索类型写审计。

---

## 7. Agent 执行引擎与工具编排

### 7.1 Agent 执行循环

参考 Claude Code / Anthropic Agent 循环：

```
用户消息 → 组装 messages + tools(schema) → LLM 轮询：
  如果 stop_reason == tool_use：
      依次执行 tool，收集 tool_result，回灌 messages
      重复
  否则：返回最终回复
```

- 状态机：`pending → running → interrupted → done`；重试/降级事件均为 `agent_process` 事件变体。
- 每次执行前 Checkpoint 落库（见 11.2），实现中断恢复与新会话断点续跑。
- 中断：收到 `POST {mid}/stop` → `cancel_event.set()` → 循环在下一个安全点退出，已完成的工具结果落库，未完成的丢弃；中断状态写入 `agent_process`，前端标「已停止」。

**为什么在「每轮 LLM 前」Checkpoint**：天然覆盖「单次回复边界」，即恢复粒度与 AGENT 步骤一致，避免恢复后出现半工具状态。

### 7.2 工具调用协议

统一协议（对齐 OpenAI 工具调用 JSON Schema 风格）：

```json
{
  "name": "tool_name",
  "description": "工具描述",
  "input_schema": {
    "type": "object",
    "properties": {...},
    "required": [...]
  }
}
```

- 执行结果统一返回 `tool_result`（含耗时、状态、结构化结果或错误信息）。
- 错误语义统一：`{ "ok": true/false, "error_code": "TIMEOUT|VALIDATION|UPSTREAM", "message": "...", "retryable": true/false }`。
- 参数校验：执行前 Pydantic 校验，失败返回 `VALIDATION`，LLM 可作为上下文重新请求。

**多供应商 LLM 抽象层**（对齐第 1 轮方案 A）：

```
LLMProvider + factory
 ├── OpenAICompatProvider    (任选 OpenAI / 自建 vLLM / Azure OpenAI)
 └── AnthropicCompatProvider (预留)
统一接口：chat(messages, tools, config) → AsyncIterator[StreamEvent]
```

- 供应商差异由各自的 adapter 消化，`agent_engine` 只看统一事件。
- 流式：统一 `content.delta / tool_call.batch / tool_result / done` 事件，屏蔽供应商事件命名差异。

**为什么 OpenAI 协议兼容为主**：生态最广、自建 vLLM / 任意 OpenAI 兼容供应商零适配，是中台扩展性的最低阻力路径。

### 7.3 错误重试与降级策略

| 错误 | 处理 | 重试 |
|---|---|---|
| LLM 超时/上游 5xx | 重试，指数退避；超 max_retries 则降级（切换备用供应商模型） | 至多 3 次 |
| 工具 VALIDATION | 参数错误，LLM 修正后重试（不计数） | 允许 |
| 工具 UPSTREAM（数据源）失败 | 最近一次失败原因写入追溯；会话继续，Agent 尝试换表述/换工具 | ≤2 次 |
| 工具 TIMEOUT | 杀沙箱容器，失败原因写入追溯，Agent 降级/重试 | ≤2 次 |
| 沙箱拉起失败（资源不足） | 触发一次全局限流，提示稍后 | — |

- 全部重试/降级动作均写入 `agent_process` 事件（见 10.2），保证可追溯。
- 失败不中断会话：会话继续，Agent 按策略处理；「失败亦记录」为不可违背原则。

### 7.4 中断与恢复

**中断（用户主动停止）**
1. 前端 `POST /stop`；
2. 服务端 `cancel_event.set()`；
3. 循环在安全点退出，已完成的工具结果落库、未完成的丢弃；
4. 中断状态写入事件，前端标「已停止」。

**恢复（异常崩溃 / 主动续跑）**
- Checkpoint 已保存上下文 state（`checkpoint.state`，含 messages 快照）与 `trace_id`。
- 恢复策略：P0 仅支持从 Checkpoint 重新发起（不自动续跑），避免死代码路径；P1 再支持多轮续跑。

**为什么 P0 只做 Checkpoint 重发起**：自动续跑涉及多轮上下文状态还原，成本高于收益；P0 保证不丢现场、可重发即可闭环业务。

### 7.5 场景编排

- 「场景」= 模型配置 + 工具集 + 系统提示词 的可组合实体（`scenario` 表）。
- 首版预置「销售查询预测」场景：绑定查询工具 + 预测工具 + 提示词。
- 编排支持在 P0-D2 工具中心配置，新场景创建流程走 `/admin/tools` + `/admin/llm`。
- **为什么场景化**：把「工具集 + 模型 + 提示词」建模为一等实体后，新增业务无需改引擎，只需新增场景配置。

### 7.6 自定义预测模型接入规范

- 目标：业务自定义预测模型通过标准工具协议接入。
- 规范：提供 `tools/` 目录下 `predict_*` 工具，声明 `name/description/input_schema/output_schema`。
- 实现为一个 Python 规范接口：`def handle(args) -> ToolResult`（可含异步、可含内网调用）。
- 工具打包为独立沙箱镜像，注册到工具中心即可被场景使用。
- 数据协议：入参/出参封装 `{ data, meta }`；异常映射到统一错误语义。
- **为什么这样做**：自定义模型与内置工具同一协议，天然继承沙箱/追溯/权限三类能力，降低成本与隔离缺口。

---

## 8. 数据源接入与沙箱隔离

### 8.1 结构化数据源接入

- **内部数据服务 API（P0）**：HTTP + JSON 返回，`http://sales-data.internal/api/v1/query`；内网免登录 + 服务账号 Token（Bearer）访问。
- 数据源统一模型：`datasource` 表记录类型（HTTP API / 预留 SQL）、base_url、凭据（加密存储）、状态。
- 连接安全：Token 仅存在于沙箱容器内白色环境变量，不回流到日志/上下文。
- 查询工具：`query_sales_data(dimensions, time_range, filters)` → 结构化结果（表格数据）。
- **白名单策略（H2）**：沙箱仅可访问内网白名单 IP:PORT；默认拒绝公网。「为什么」：走沙箱做统一出口网关，凭据与出网边界双收口，业务方无需自己管理凭据。

### 8.2 沙箱隔离

- 运行时：Docker daemon + 资源限制：
  - 只读 rootfs、非 root 用户、
  - `--memory / --cpus / --pids-limit`、
  - 独立 bridge 网络 + iptables 出网白名单（仅放行内网白名单 IP:PORT，默认拒绝公网）。
- 工具包为独立镜像启动容器，执行后销毁。
- 超时上限（默认 30s，可配置）与资源配额，超限杀容器。
- 「为什么选择 Docker 受限运行时」：内部威胁模型下 Docker 限制满足需求；gVisor/Kata 升级列入 P2。
- 失败处理：容器拉起失败 / 超时 / OOM → 错误语义 `SANDBOX` 写入追溯，Agent 按 7.3 重试/降级。

---

## 9. 权限与隔离体系

### 9.1 RBAC 权限模型

三表模型：**角色（role）/ 权限点（permission）/ 角色-权限（role_permission）**。

- **预置角色**：`user`（普通用户）、`admin`（管理员）。
- **权限点定义**：
  - `chat:read` / `chat:send` / `chat:stop` / `chat:delete`（会话域）
  - `trace:read`（追溯域）
  - `adm:user.manage` / `adm:tool.manage` / `adm:llm.manage` / `adm:config.manage`（管理端）
  - `audit:read`（审计只读）
- **为什么表驱动而非硬编码**：P0 与写死成本几乎一致，直接打通 P1 自定义角色，避免返工。【确认】

### 9.2 权限矩阵

| 动作 | user | admin |
|---|---|---|
| 创建/访问自己的会话 | ✅ | ✅ |
| 发送/停止消息 | ✅ | ✅ |
| 查看自己的追溯 | ✅ | ✅ |
| 管理他人会话 | ❌ | ❌（仅只读审计） |
| 用户管理 | ❌ | ✅ |
| 工具/数据源管理 | ❌ | ✅ |
| LLM 配置 | ❌ | ✅ |
| 系统参数 | ❌ | ✅ |
| 全量审计检索 | ❌ | ✅ |

### 9.3 三类隔离闭环

| 隔离 | 落点 | 闭环要求 |
|---|---|---|
| **用户隔离** | 所有会话/消息/追溯查询强制 `owner_id = 当前用户`；管理员审计只读 | 越权 → 403 + 写入审计 |
| **会话隔离** | 会话上下文（messages、checkpoint、trace）按 `conversation_id` 严格切分；单会话单字节级；**置顶仅对本人会话生效、owner 校验不变，不破坏隔离（【变更 v0.10】）** | 会话间零交叉 |
| **沙箱隔离** | 执行环境专属容器；对象/网络/凭据隔离；白名单出网 | 工具互不干扰，凭据不泄露 |

**用户隔离的服务端强约束**：任何 `GET/POST/PATCH/DELETE` 对会话/消息先校验 `owner_id` 再落库，不依赖前端过滤。

### 9.4 审计与越权响应

- 所有越权访问（403）写入审计：`{actor, target, action, reason: "permission_denied"}`。
- 管理员审计检索本身留痕（type=`audit.view`）。
- 敏感操作（创建用户、重置密码、用户自助修改密码【变更 v0.10】、改 key、删会话）均写审计。
- 「为什么管理员只读」：审计域保持只读，管理员可看不可改，防篡改；管理行为本身留痕，形成「权限越大、留痕越重」约束。

---

## 10. 全链路追溯日志

### 10.1 追溯目标

- 还原一次 Agent 执行：`消息 → 工具名 → 入参 → 结果 → 最终回复 → 失败原因/重试过程`。
- 用户与管理员均可查看；用户看自己，管理员看全量（只读）。

### 10.2 事件模型与字段

核心概念：`trace_id（一次消息执行）→ node（阶段）→ events(有序事件数组)`。

**trace 事件类型与字段**

| 事件 | 关键字段 | 说明 |
|---|---|---|
| `message_created` | trace_id, message_id, direction | 用户消息入队 |
| `agent_process` | state（starting/planning/executing/retrying/degrading/interrupted/done）, detail | Agent 阶段 |
| `tool_call` | tool_name, input(payload), plan_index | 工具执行 |
| `tool_result` | tool_name, output(result), duration_ms, status | 工具结果 |
| `tool_error` | tool_name, error_code, message, retried | 失败与重试信息 |
| `content_delta` | text | 流式文本增量 |
| `done` | final_text | 最终回复 |

统一 `events` 数组按序存储（JSONB），关键字段满足「还原一次执行」的最小集。

### 10.3 还原能力验证

对一次销售预测对话，还原链应为：

```
message_created（用户: "预测下月华东区销量"）
  └─ agent_process.starting
       └─ agent_process.executing
            ├─ tool_call {query_sales_data(input:{region:华东, period:近6月})}
            │    └─ tool_result {rows:[...], status:ok, duration_ms:1200}
            │    └─ tool_error (若上游失败: error_code: UPSTREAM, retried: true)
            ├─ tool_call {predict_sales_tool(input:{model:default, ...})}
            │    └─ tool_result {forecast:[...], status:ok, duration_ms:3400}
            └─ agent_process.done
  └─ message_created（最终回复）或 content_delta 流式结束
```

**为什么这是可还原的**：任一环节的输入输出与状态均有事件留存，用户能逐条确认「做了什么/为何失败/如何降级」；这也是对标 deepseek-harness 的产物标准。

---

## 11. 数据模型与主流程

### 11.1 核心实体概览

```
user ─1─n─ conversation(status) ─1─n─ message(status)
message(status) ─1─n─ message_event(status)      # 追溯事件链
conversation ─1─1─ checkpoint(state)
user ─1─n─ role_binding ─n─1─ role ─n─m─ role_permission ─n─1─ permission
tool
datasource
llm_provider
scenario
sandbox_instance(status)   # 沙箱实例生命周期
audit_log
```

**status 字段说明**：user(active/disabled)；conversation(active/archived/deleted)；message(sent/running/interrupted/completed/failed)；message_event(normal/anomaly)（追溯链完整性保护）。状态借助 status 支撑「运行中」显式呈现，避免与已终止执行混淆。

### 11.2 关键数据表字段

**user**：`id, email, password_hash, nickname, status, created_at, updated_at`
**role**：`id, code, name, scope(system), builtin(bool)`
**permission**：`id, code, name, desc`
**role_permission**：`role_id, permission_id`
**conversation**：`id, owner_id, title, status, pinned(bool), pinned_at, created_at, updated_at`（pinned/pinned_at 为【变更 v0.10】置顶能力）
**message**：`id, conversation_id, role(user/assistant/system), content, trace_id, status, created_at`
**message_event**：`id, trace_id, message_id, seq, type, payload(JSONB), created_at`
**checkpoint**：`id, conversation_id, message_id, state(JSONB), trace_id, created_at`
**tool**：`id, name, code, desc, status, scenario_id, config(JSONB), created_at, updated_at`
**datasource**：`id, name, type(http_api/sql), base_url, credential_encrypted, whitelist, status`
**llm_provider**：`id, name, base_url, api_key_encrypted, models(JSONB), default_model, vendor, status`
**scenario**：`id, name, tool_ids, model_ref, system_prompt, enabled`
**sandbox_instance**：`id, tool_id, container_id, status, created_at, terminated_at`
**audit_log**：`id, actor_id, action, target_type, target_id, ip, detail(JSONB), created_at`
**system_config**：`key, value(JSONB), updated_by, updated_at`
**user_llm_config（【预留】P1，【变更 v0.10】）**：`id, user_id(unique), vendor, model_type, model_id, base_url, api_key_encrypted, status, created_at, updated_at`（BYOK 用户级模型配置预留表；用户未配置时回平台默认 `llm_provider`；API Key 与管理员 LLM 配置同标准加密存储，仅本人可见，见 H10）

### 11.3 主流程时序

**对话 → 工具 -> 沙箱 -> LLM 全链路时序**

```
前端 → POST /chat/conversations/{id}/messages   (JWT)
  → RBAC: chat:send + owner 校验
  → 建 message(status=running)
  → 建 trace → sse 开始 → 组装(对话消息+工具 schema)
  → AgentLoop:
       LLM 调用(provider)
       → 若 stop_reason=tool_use:
            execute tool → sandbox(容器 + 出网) → 结果回灌 → 继续
       → 否则: 最终回复
  → 事件全程写 audit_log / message_event
  → SSE done 结束流 ↓
前端渲染: 工具卡片 + 结果表格/图表 + 最终回复
```

**管理员审计查看**

```
GET /admin/audits → RBAC: audit:read → 列表(只读) → 本次查看本身写 audit_log(type=audit.view)
```

---

## 12. 接口规范

### 12.1 接口约定

- Base URL：`/api/v1`；响应统一 `{code, message, data}`。
- 认证：`Authorization: Bearer <access_token>`（JWT 无状态）。
- 分页：cursor 制，`?cursor=&limit=20`。
- 幂等：重要写操作支持 `Idempotency-Key` 防重复。

### 12.2 用户端接口

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| POST | `/auth/register` | 内部邮箱注册 | 未认证 |
| POST | `/auth/login` | 登录，返回 access+refresh | 未认证 |
| GET | `/auth/me` | 用户信息+权限点 | 已认证 |
| POST | `/auth/refresh` | 刷新令牌 | — |
| POST | `/auth/logout` | 注销+吊销 refresh | 已认证 |
| PATCH | `/auth/password` | 修改密码（校验原密码，【变更 v0.10】） | 已认证 |
| PATCH | `/auth/me` | 更新昵称（【变更 v0.10】） | 已认证 |
| GET | `/conversations` | 我的会话列表 | 本人 |
| POST | `/conversations` | 新建会话 | 本人 |
| GET | `/conversations/{id}` | 会话详情 | 本人 |
| PATCH | `/conversations/{id}` | 重命名 | 本人 |
| PATCH | `/conversations/{id}/pin` | 置顶/取消置顶（body `{pinned}`，【变更 v0.10】） | 本人 |
| DELETE | `/conversations/{id}` | 删除（级联） | 本人 |
| POST | `/conversations/{id}/messages` | 触发 SSE 会话 | 本人 |
| POST | `/conversations/{id}/messages/{mid}/stop` | 停止当前生成 | 本人 |
| GET | `/conversations/{id}/messages` | 历史消息分页 | 本人 |
| GET | `/conversations/{id}/messages/{mid}/trace` | 追溯事件链 | 本人 |
| GET | `/conversations/{id}/messages/{mid}/trace/export` | 可读导出 | 本人 |

### 12.3 管理员端接口

| 方法 | 路径 | 说明 | 权限 |
|---|---|---|---|
| GET | `/admin/users` | 用户列表/搜索 | admin |
| POST | `/admin/users` | 创建用户 | admin |
| PATCH | `/admin/users/{id}` | 编辑（角色/状态） | admin |
| POST | `/admin/users/{id}/reset-password` | 重置密码 | admin |
| GET | `/admin/tools` | 工具列表 | admin |
| POST | `/admin/tools` | 注册工具 | admin |
| PATCH | `/admin/tools/{id}` | 启停/参数配置 | admin |
| POST | `/admin/tools/{id}/test` | 连通性测试 | admin |
| GET | `/admin/datasources` | 数据源列表 | admin |
| POST | `/admin/datasources` | 注册数据源 | admin |
| PATCH | `/admin/datasources/{id}` | 编辑/测试 | admin |
| GET | `/admin/llm` | 供应商/模型列表 | admin |
| POST | `/admin/llm` | 新增供应商 | admin |
| PATCH | `/admin/llm/{id}` | 编辑 Key/端点/默认模型 | admin |
| POST | `/admin/llm/{id}/health` | 健康检查 | admin |
| GET | `/admin/config` | 系统参数 | admin |
| PATCH | `/admin/config` | 修改系统参数 | admin |
| GET | `/admin/audits` | 审计日志列表 | admin |
| GET | `/admin/audits/{id}` | 审计详情 | admin |
| POST | `/admin/audits/export` | 审计导出（P1 占位） | admin |

### 12.4 SSE 事件协议

| 事件名 | 载荷 | 前端行为 |
|---|---|---|
| `message.created` | message_id | 新增助手消息占位 |
| `message.delta` | text | 逐字追加 |
| `agent.status` | state | 阶段状态卡 |
| `agent.process` | state, detail | 阶段/重试/降级 |
| `tool.call` | tool_name, input | 工具卡片折叠头 |
| `tool.result` | tool_name, output_summary | 结果摘要 |
| `tool_error` | tool_name, error_code, retried | 失败红标+原因+重试次数 |
| `done` | final_text | 结束流；最终回复持久化 |
| `error` | code, message | 终止 + 错误提示 |

### 12.5 鉴权与错误码

- JWT：access（15min）+ refresh（7d）双令牌；`/auth/refresh` 轮换；登出吊销。
- 统一错误码：`401_UNAUTHORIZED / 403_FORBIDDEN（越权，触发审计） / 404_NOT_FOUND / 400_VALIDATION / 409_CONFLICT / 500_INTERNAL / 429_RATE_LIMIT`。
- **错误提示语义（【变更 v0.10】）**：业务失败响应的 `message` 必须为可读文案（如「邮箱后缀不在白名单内（允许：@corp.com）」「密码必须同时包含大小写字母与数字」），错误码仅作技术标识、不作为用户展示内容；响应不裸堆技术异常堆栈，完整堆栈仅留存于后端日志。

---

## 13. 部署与运维

### 13.1 部署拓扑与 compose 编排

```
用户端 Vue 静态 / nginx 静态入口
 └─ FastAPI 容器 (api) ×1
 └─ PostgreSQL 15 容器 ×1
 └─ 沙箱 daemon 容器（Docker 权限、独立网络、iptables 白名单）
 └─ Redis（P1 队列/缓存预留，P0 可不部署）
```

`docker-compose.yml` 服务：`api`、`worker`（预留独立异步执行，见 P1-9）、`db`、`sandbox-daemon`、`nginx`（静态+反代）。

### 13.2 数据库初始化与依赖顺序

1. `db` 服务先启动（healthcheck `pg_isready`）。
2. `api` 依赖 `db` healthy → 运行迁移（Alembic 自动 + 种子脚本创建默认 admin / 预置角色权限点 / 默认场景）。
3. `sandbox-daemon` 构建工具基础镜像 + 拉取白名单网段。
4. `nginx` 最后就绪，承载前端资源与反代 `/api`。

**为什么用 Alembic 而非裸 SQL**：变更可版本化、可回滚，与「依赖锁定文件进版本管理」同一维护心智。

### 13.3 环境与密钥管理

- 后端配置环境变量（`.env`，不入版本库）：`DB_URL`、`JWT_SECRET`、`LLM_API_KEYS`、`INTERNAL_TOKEN`、`SANDBOX_WHITELIST_CIDRS` 等。
- 密钥支持 Docker Secret / 外部 KMS（P1+）。
- **为什么密钥不入库**：防泄密与生产安全事故，只进 Secret 管理。

### 13.4 健康检查、监控与备份

- 健康检查：`/healthz`（DB、LLM provider、沙箱 daemon 状态）。
- 监控（P1）：结构化日志 + Prometheus 指标（请求量、Latency、Token 用量）。
- 备份（P1）：PostgreSQL 每日 dump + 保留策略；快照前 MySQL（若选 MySQL）同方案。
- `docker compose up -d` 单命令拉起；P0 验收需验证拉起到可注册/登录/对话一次。

---

## 14. 路线图与验收要点

### 14.1 里程碑总览

| 阶段 | 周期（预估） | 交付重点 |
|---|---|---|
| P0 | 6~8 周 | MVP：双端、对话、追溯、沙箱、LLM、部署 |
| P1 | 4~6 周 | GitHub OAuth、RAG、多模型切换、数据看板、审计导出、SQL 直连 |
| P2 | 持续 | 深水区能力：负载均衡、数据权限细分、沙箱升级、市场/API 等 |

### 14.2 P0 验收清单

| # | 验收项 | 判定 |
|---|---|---|
| 1 | 注册/登录/内部邮箱白名单 | 白名单外注册被拒 |
| 2 | 对话查询销售数据 | 自然语言→表格结果 |
| 3 | 预测工具调用 + 可视化 | 前端可渲染预测图表 |
| 4 | 追溯面板 | 消息→工具→入参→结果→最终回复可完整还原 |
| 5 | 权限矩阵 | user/admin 行为严格匹配 9.2；越权 403 |
| 6 | 三类隔离 | 会话/用户/沙箱交叉访问全部被拒 |
| 7 | 流式输出 | SSE 事件实时、断线自动重连 |
| 8 | 停止生成 | 中断后状态正确、无未完成工具残留 |
| 9 | 管理员审计 | 全量检索 + 检索行为留痕 |
| 10 | docker-compose 拉起 | `up -d`→迁移→种子→注册/登录/对话一次通过 |
| 11 | 全链路日志还原 | 事件模型满足 10.3 用例 |
| 12 | 失败处理 | 数据源故障可见失败原因，会话不中断 |
| 13 | 注册失败原因可见 | 白名单外邮箱/弱密码提交后页面显示可读原因（非仅错误码，【变更 v0.10】） |
| 14 | 个人设置-基础信息 | 昵称修改生效；改密后新密码可登录、旧密码失效；邮箱只读展示（【变更 v0.10】） |
| 15 | 会话置顶 | 置顶项排最前（置顶时间倒序）、取消后恢复；他人会话不可置顶（403）（【变更 v0.10】） |

### 14.3 P1 / P2 节奏建议

- P1 优先级排序：GitHub OAuth → 管理台数据看板 → SQL 直连 → 自定义角色 → RAG → 审计导出 → 长任务队列。
- P2 按运营反馈决策，不做排队承诺。

---

## 15. 风险与开放问题

### 15.1 风险清单

| 风险 | 影响 | 应对 |
|---|---|---|
| 内部数据接口 SLA 不稳 | 查询工具高频超时 | 沙箱超时与重试梯度 + 失败原因透出 |
| LLM 供应商不稳定/不可用 | 对话整体不可用 | 多供应商 + 健康检查 + 降级切换（P1） |
| 沙箱逃逸/内网穿透 | 内网白名单被绕 | 最小权限、出网白名单、读网/凭据不放行回传 |
| Key/凭据泄露 | 数据与模型成本 | 加密存储 + 最小化 Token 范围 + 审计 |
| 追溯数据量膨胀 | 存储/查询变慢 | JSONB+事件数组、保留策略、分区（P1） |
| 管理员误操作 | 权限配置破坏 | 二次确认 + 审计 + 防自禁用 |
| 业务对接自定义模型排期不确定 | P1 范围风险 | 工具规范提前定稿，测试覆盖搭建 |
| 用户自配模型 Key 泄露/成本失控（P1 BYOK） | 用户模型 Key 泄露或误配高成本模型 | 与管理员 LLM 配置同标准加密存储 + 仅本人可见（H10）；P1 上线前评审 Key 保管与额度控制（【变更 v0.10】） |

### 15.2 开放问题

1. 内部销售数据接口真实 SLA / 白名单网段确认。
2. 模型供应商/自建推理实际可用性。
3. P0 阶段是否需要远程 DeepSeek 兼容网关（可后续接入）。
4. 管理员多级（超级管理员/普通管理员）是否有诉求（默认 P1 自定义角色承接）。
5. 业务方对预测模型接入接口细节的确认（7.6 规范是否满足其需求）。

---

## 附录 A：双端权限矩阵核验表

| 能力 | user | admin | 核验点 |
|---|---|---|---|
| 自己会话 CRUD | ✅ | ✅ | owner_id 条件 |
| 发送/停止消息 | ✅ | ✅ | chat:send/stop |
| 查自己追溯 | ✅ | ✅ | trace:read + owner |
| 修改自己昵称/密码（个人设置） | ✅ | ✅ | 本人认证 + 敏感操作写审计（【变更 v0.10】） |
| 全量会话/日志审计 | ❌ | ✅（只读） | admin + audit:read |
| 用户管理 | ❌ | ✅ | adm:user.manage |
| 工具/数据源管理 | ❌ | ✅ | adm:tool.manage |
| LLM 配置 | ❌（P1 预留：BYOK 用户级） | ✅ | adm:llm.manage |
| 系统参数 | ❌ | ✅ | adm:config.manage |
| 审计检索自身留痕 | — | 始终 | audit.view 写入 |

## 附录 B：追溯日志字段还原对照

| 还原目标 | 依赖字段 | 验证 |
|---|---|---|
| 用户发了什么 | message.content + message_created | ✅ |
| 执行了哪些工具 | message_event type=tool_call | ✅ |
| 工具入参 | message_event.payload.input | ✅ |
| 工具结果 | message_event.payload.output | ✅ |
| 失败原因 | message_event.payload.error_code + error_message | ✅ |
| 重试次数 | message_event.payload.retried | ✅ |
| 最终回复 | message.content / done.final_text | ✅ |
| 沙箱生命周期 | sandbox_instance(container_id, status, terminated_at) | ✅ |

---
