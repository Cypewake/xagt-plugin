# MCPForge — API→MCP 全链路工厂

> 本文件按官方 `submissions/TEMPLATE.md` 填写；部署 URL 与审查 commit 在公开部署后回填（见 `verification/README.md`）。

## Capability

- **一句话描述**：把「已有 REST API」变成「AI Agent 能直接调用的 MCP 工具」，完整覆盖官方四段式 **Build → Verify → MCPize → Monetize**。
- **服务对象**：需要把内部或第三方 REST API 接入 Agent 的开发者与团队。
- **能力边界**：输入 OpenAPI/Swagger 规格或在线 API，产出可部署的 MCP 工具集 + 真实可验证调用 + 按次计费出账。不做安全/审计/链上风控类外壳（符合赛道红线）。

## Live API

- **API base URL**：`https://mcpforge-cypewake.app.workbuddy.host`
- **Health-check URL**：`https://mcpforge-cypewake.app.workbuddy.host/api/health`
- **鉴权**：none（公开、免密钥，仅供评审窗口调用）
- **限流 / 已知限制**：演示用单进程；真实出网依赖 `api.github.com` 可达。
- **API 契约**：`source/examples/github-openapi.json` 与生成代码 `source/examples/*/server.py`。

## Source and reproducibility

- **Source repository**：https://github.com/cypewake/xagt-plugin
- **Review commit**：`41ed4e5160e52fc51908c6bbc648d325a2d685de`
- **Source submitted in this PR**：`source/`
- **Run tests**：`pip install -r source/requirements.txt && pytest source/tests`（53 离线 + 6 在线标记，全绿）
- **Run locally**：`pip install "fastmcp>=4.0,<5.0"` 然后 `uvicorn demo_app:app --host 0.0.0.0 --port 8000`
- **Deploy**：`uvicorn demo_app:app --host 0.0.0.0 --port $PORT`，并设置环境变量 `REVIEW_COMMIT=41ed4e5160e52fc51908c6bbc648d325a2d685de`
- **Version binding**：部署服务通过环境变量 `REVIEW_COMMIT` 暴露审查 commit；`/api/health` 与 `/.well-known/xagent-verification.json` 回传该 commit。

部署服务必须暴露：

```json
// GET https://mcpforge-cypewake.app.workbuddy.host/api/health
{"status":"ok","commit":"41ed4e5160e52fc51908c6bbc648d325a2d685de"}
```

```json
// GET https://mcpforge-cypewake.app.workbuddy.host/.well-known/xagent-verification.json
{"schemaVersion":1,"slug":"cypewake-api-mcp-toolkit","commit":"41ed4e5160e52fc51908c6bbc648d325a2d685de"}
```

## Verification

可复现调用说明与脱敏示例响应见 `verification/README.md`。

- **Health-check 结果**：`status=ok`，`commit=41ed4e5160e52fc51908c6bbc648d325a2d685de`。
- **Capability call**：通过 MCP 端点调用 `call_rest_api`（GitHub `/zen`）或 `register(github_live)+call_registered_api(getZen)`，均返回 HTTP 200。
- **预期错误行为**：传入未注册 API 名 → 明确错误；传入内网 URL → 被 `assert_public_url` 拒绝（SSRF 防护）。

## 真实任务（Real task）

评分最高的一项是「能否完成有意义的真实任务，胜过纯 prompt demo」。本作品用一个
**必须依赖实时数据**的任务来回答，而不是靠单步探测充数。

**任务**：为某个技术主题生成选型简报（默认主题 `model-context-protocol`）。

**为什么纯 prompt 做不到**：结论依赖实时的 star / fork / open issues / 最近更新时间，
这些数值每天都在变，模型凭训练记忆给不出真实数字，必须调用工具回源。

**三步编排**（每步都是真实 HTTP，可在部署页面现场重跑）：

1. `searchRepositories` —— 检索候选仓库
2. `getRepository` —— 逐个回源核实（搜索摘要可能过期，必须核实）
3. 本地聚合 —— 排序并生成简报

**最近一次真实结果**（完整证据：`source/examples/real_agent_task_result.json`）：

| # | 仓库 | Star | Fork | Open issues | 语言 |
|---|---|---:|---:|---:|---|
| 1 | modelcontextprotocol/servers | 90384 | 11640 | 536 | TypeScript |
| 2 | HKUDS/nanobot | 48216 | 8523 | 784 | Python |
| 3 | DeusData/codebase-memory-mcp | 43513 | 3541 | 591 | C |

**变现口径**：该任务实际产生 4 次真实调用。按 pro 档（$8 / 1k 次，含 5 万次免费额度）
测算，规模化到 100 万次/月为 **7,600 USD/月**（字段 `invoice_scaled_1m`）。
实际账单为 0 是因用量未超出免费额度，属预期行为，并非计费未生效——
因此证据里同时给出「实际口径」与「规模化口径」两张账单。

**现场复现**：打开部署页 → 「真实任务演示」区块 → 点「运行真实任务」；
或直接 `POST /api/real-task {"topic":"..."}` 查看逐步真实调用与状态码。

## Security and data handling

- **采集数据**：无用户数据持久化；仅运行时内存计量计数（进程退出即失）。
- **目的与留存**：计量用于演示 Monetize 按次出账，不做长期留存。
- **第三方 / 出站**：仅 `api.github.com`（真实出网验证）；`assert_public_url` + 逐跳重定向校验防护内网跳转（SSRF）。
- **密钥**：无密钥提交；评审访问仅在批准后私信道提供。
- **已知风险 / 限制**：演示服务无鉴权，仅用于评审窗口（9/20–10/1）可达。

## Support

- **团队 / 作者**：cypewake
- **联系**：GitHub @cypewake
- **许可 / 权利**：提交者拥有源码权利，并授权 X-Agent 评审与归档。

## 身份映射（Identity mapping）

> 用于评审对账：以下两个标识为**同一参与者**。

| 渠道 | 标识 |
| --- | --- |
| Luma 报名（选 Open Innovation 赛道） | **wake** |
| GitHub 账号 / 本 PR 提交账号 | **cypewake** |
| 公开部署域名 | mcpforge-cypewake.app.workbuddy.host |
| 本 PR | xagentAI/xagt-plugin#61 |

若评审需要把报名记录与本 PR 关联，请以上表为准：`wake`（Luma）= `cypewake`（GitHub），同一人。
