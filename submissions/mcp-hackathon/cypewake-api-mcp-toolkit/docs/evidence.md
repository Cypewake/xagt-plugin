# MCPForge · 现场验证证据包

> 本文档面向评委：直接给出**可复现的链接、截图与命令**，证明作品满足 X-Agent AI MCP Hackathon 2026 的所有硬性提交与验证要求。

## 1. 本地即可复核（零部署）

作品以 GitHub PR 形式提交，**官方确认提交前不需要自建 MCP Server**。所有硬指标都可在你本地一条命令复现：

```bash
cd submissions/mcp-hackathon/api-mcp-toolkit
pip install "fastmcp>=4.0,<5.0"
uvicorn demo_app:app --port 8000        # 一个进程同时提供走查页 / 健康检查 / MCP 端点
```

- `GET /api/health` → `{"status":"ok","version":"2.1.0"}`（HTTP 200）
- `GET /` → 四阶段可视化走查页（HTTP 200，含「工具策展」面板）
- `GET /api/config` → 当前支持的计价档位与配置（HTTP 200）
- `POST /api/preview-scope` → 预览 scope 策展效果（HTTP 200）
- `POST /api/full-pipeline` → 端到端全链路演示（见下方 JSON）

## 2. 可视化截图（docs/screenshots/）

| 文件 | 内容 | 证明点 |
|---|---|---|
| `walkthrough-v2.1-scope.png` | **v2.1 走查页首页截图（本地 v2.1 服务）** | 顶部新增「工具策展（Tool Curation）」面板；四阶段卡片完整展示 |
| `walkthrough.png` | 走查页首页截图（本地服务） | UI 完整展示 Build → Verify → MCPize → Monetize 四阶段 |
| `health.png` | `/api/health` 返回 JSON 截图 | 健康检查端点正常 |
| `config.png` | `/api/config` 返回 JSON 截图 | 计价/配置接口可访问 |

> 所有截图均由本机安装的 **Google Chrome 无头模式** 对本地 `uvicorn demo_app:app` 服务抓取，非 mock。

## 2.5 真实样板端到端证据（GitHub 公共 API，非 Petstore 自嗨）

为证明"genuinely useful, online-callable"，样板选用 **GitHub 公共 REST API**（`api.github.com`，免密钥、agent 高频调用）。
本地运行 `examples/run_real_showcase.py`，对**真实公网**完成 Build → Verify → MCPize → Monetize 全链路，原始结果见
`examples/real_showcase_result.json`，规格见 `examples/coingecko-openapi.json`（文件名为历史遗留，内容已是 GitHub 样板）。

| 指标 | 结果 |
|---|---|
| Verify 真实 2xx | **3/3 全部通过**（真实公网 HTTP 200，含 `/zen`、`/rate_limit`、`/events`） |
| 真实调用计量 | 6 次真实 200 调用，成功率 100%，逐 operation 真实延迟 |
| 计价档出账 | pro 档，每千次 $8，按真实用量折算（pay-per-call） |
| 市场清单 | 3 个可调用工具，pay-per-call 模型，币种 USD |
| 合规声明 | `contains_security_audit_capability: false`、`crypto_token_speculation: false` |

> 说明：加密行情类 API（CoinGecko）在本沙箱出网策略下被拦截，故选 GitHub；
> 这反而更贴"agent 真正会调用"的评委口径。币种保持 USD，不碰代币投机红线。
> 该证据为**本地真实调用产出**，无需部署公网即可复核：
> `python examples/run_real_showcase.py`（沙箱可直连 `api.github.com`）。


## 3. 一键复核脚本

```bash
cd submissions/mcp-hackathon/api-mcp-toolkit
pip install "fastmcp>=4.0,<5.0"
python docs/judge_check.py --url http://127.0.0.1:8000
```

预期结果（`exit 0`）：

```
目标实例：http://127.0.0.1:8000（本地单进程：uvicorn demo_app:app，零部署即可复核）
[PASS] 健康检查 GET /api/health — HTTP 200 status=ok version=2.1.0
[PASS] 可视化四阶段走查页 GET / — HTTP 200 15770 字节
[PASS] 计价档位可读 GET /api/config — 档位=['free', 'basic', 'pro', 'enterprise'] 币种=USD
[PASS] MCP 端点可列出工具 — 14 个
[PASS] 规格点名的 7 个工具全部存在 — 齐全
[PASS] 工具调用：health_check — status=ok
[PASS] 工具调用：parse_openapi_spec 解析本地 Petstore 风格规格 — 5 个操作
[PASS] 工具调用：list_operations 输出可读操作清单 — 276 字符，含 getPetById=True
[PASS] 工具调用：call_rest_api 真实出网（GitHub 公共 REST API） — HTTP 200
[PASS] 工具调用：generate_mcp_tool_code 产出可部署 FastMCP 源码（§6 #2） — 59 行
[PASS] 工具调用：register + call_registered_api(getZen) 真实出网（§6 #3） — HTTP 200
结果：11 通过 / 0 未通过
```

> 说明：`judge_check_result.txt` 为本地零部署实跑结果（11/11，退出码 0）。评委本地一条命令即可复现，无需任何公网实例。

最新复核输出已保存为 `docs/judge_check_result.txt`。

## 4. 完整端到端流水线响应

`POST /api/full-pipeline` 请求体示例：

```json
{
  "spec_source": "https://petstore3.swagger.io/api/v3/openapi.json",
  "pricing_tier": "basic"
}
```

响应摘要：

| 阶段 | 关键结果 |
|---|---|
| **build** | 解析 Petstore OpenAPI 3.0，19 个 operation，base_url 已识别 |
| **verify** | 10 个端点可探测，含 1 个通过，9 个因鉴权/状态返回非 2xx 被标记为 reached_but_failed；支持 scope 先策展再验证 |
| **mcpize** | 生成 19 个 FastMCP 工具代码到 `/workspace/generated/petstore-mcp`；支持 scope 策展（如 19 → 4） |
| **register** | 19 个 operation 注册到本服务，名为 `petstore` |
| **call** | 真实调用 `loginUser`（sample/sample），返回 HTTP 200，验证工具确实可调 |
| **monetize** | 按 basic 档（USD 2.0 / 1k 次）生成计费配置；支持 scope 策展后上架 |
| **invoice_preview** | 基于真实调用量外推，预览账单 USD 180.0 |

完整响应见 `docs/full_pipeline_result.json`，摘要见 `docs/full_pipeline_summary.md`。

## 5. 本地验证

```bash
cd submissions/mcp-hackathon/api-mcp-toolkit
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
fastmcp dev server.py
# 然后打开 http://127.0.0.1:3000 的调试界面，逐个点工具验证
```

测试套件（无需联网）：

```bash
python -m pytest        # 80 项离线用例（含 5 项工具策展回归）
```

在线用例（联网）：

```bash
python -m pytest -m live -v   # 6 项在线用例
```

双层验收脚本：

```bash
python verify.py        # 离线 + 在线双层验收，exit 0 通过
```

## 6. 与官方要求的逐项对齐

| 官方要求 | 本项目状态 | 证据 |
|---|---|---|
| 对 `xagentAI/xagt-plugin` 开 PR | 待用户提供 GitHub 用户名后完成 | `tools/rename_for_submission.sh` 已准备就绪 |
| 目录在 `submissions/mcp-hackathon/<用户名>-api-mcp-toolkit/` | 待重命名 | 当前为 `api-mcp-toolkit/` |
| 7 个契约工具齐全 | ✅ 通过 | `judge_check.py` 第 5 条 PASS |
| 可真实调用（本地零部署）/ health check | ✅ 通过 | `walkthrough.png`、`health.png`、`judge_check_result.txt` |
| 无安全/审计外壳 | ✅ 通过 | 源码仅含通用 API→MCP 转换，无风险/合规/攻击检测 |
| README + requirements + pyproject | ✅ 通过 | 仓库根目录已提供 |
| 验证证据（截图/录屏/可调用示例） | ✅ 通过 | 本目录 screenshots + judge_check + full_pipeline |
