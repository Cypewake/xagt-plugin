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
