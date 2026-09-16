# MCPForge · API→MCP 全链路工厂

**X-Agent AI MCP Hackathon 2026 · 开放创新赛道（Open Innovation）参赛作品**

> 把任意 OpenAPI 描述（URL / 本地文件 / 粘贴文本）转换成 Agent 可直接调用的 MCP 能力，
> 并严格走完官方口号的四个阶段：**Build → Verify → MCPize → Monetize**。

---

## 本地即可复核（无需部署到公网）

> 官方明确：**提交前不需要自建 MCP Server**。本作品以 GitHub PR 形式提交，所有硬指标都可在你本地
> 一条命令复现（见「评委如何复核」）。**无需任何公网部署**，本地起服务即可核对。

| 能力 | 本地地址（零部署，推荐） |
|---|---|
| 可视化四阶段走查页 | http://127.0.0.1:8000/ |
| 健康检查（live 证据） | http://127.0.0.1:8000/api/health |
| **MCP 服务端点（streamable-http）** | http://127.0.0.1:8000/mcp/ |
| 完整流水线演示 | `POST /api/full-pipeline`（见 `docs/full_pipeline_result.json`） |

一个进程、一个端口同时提供上面三者，因此「deploy and validate the online API」这条硬门槛
是用**可真实调用的 MCP 端点**闭环的，而不是只给一个健康检查。

## 评委评分映射（四个维度 → 可复现证据）

官方定性评分为「真实、可调用、可验证、可变现」。MCPForge 对每一维都提供可本地复现的硬证据：

| 评分维度 | MCPForge 的对应证据 | 复现方式 |
|---|---|---|
| **真实（Real）** | 封装的 GitHub 公共 REST API 真实返回 2xx；judge_check 实测 `/zen`、`getZen` 均 HTTP 200 | `python docs/judge_check.py` |
| **可调用（Callable）** | 14 个 MCP 工具可被标准 MCP 客户端列举并调用；`/mcp` 端点对 `fastmcp.Client(mode=auto)` 连通 | 同上，输出 11/11 PASS |
| **可验证（Verifiable）** | `verify_api` 只对真实 2xx 判定为 passed——明确拒绝「任何响应都算通过」的指标恒真陷阱 | 源码 `core.py` + judge_check |
| **可变现（Monetizable）** | x402 按次付费计量出账，`pro` 档真实计费；`examples/real_showcase_result.json` 含 6 次真实计量记录 | 见该 JSON + `docs/evidence.md` |

## 评委证据（截图 + 一键复核脚本）

`docs/` 目录已冻结一套可直接提交的证据：

| 文件 | 内容 |
|---|---|
| `docs/screenshots/walkthrough.png` | 走查页首页（四阶段 UI + 在线徽章） |
| `docs/screenshots/health.png` | `/api/health` 返回 `status=ok` 截图 |
| `docs/screenshots/config.png` | `/api/config` 返回计价配置截图 |
| `docs/judge_check.py` | 评委/评审人一条命令复核 9 项硬指标 |
| `docs/judge_check_result.txt` | 11/11 PASS 的本地实测输出（零部署、含 §6 验收 #2/#3） |
| `docs/full_pipeline_result.json` | 真实 `POST /api/full-pipeline` 完整响应 |
| `docs/full_pipeline_summary.md` | 流水线各阶段结果摘要 |
| `docs/MARKET_RESEARCH.md` | 市场调研、竞争格局与实用性分析 |
| `docs/WINNING_POSITIONING.md` | 夺冠定位：痛点洞察、差异点与叙事钩子 |
| `docs/evidence.md` | 面向评委的证据总览与复现命令 |

截图由本机 **Google Chrome 无头模式** 对本地 `uvicorn demo_app:app` 服务抓取，不是 mock。

用任意 MCP 客户端现场验证：

```python
import asyncio
from fastmcp import Client

async def main():
    async with Client("http://127.0.0.1:8000/mcp/") as c:   # 本地零部署地址
        print([t.name for t in await c.list_tools()])                 # 14 个工具
        print((await c.call_tool("health_check", {})).data)            # {'status': 'ok', ...}
        print((await c.call_tool("call_rest_api", {                   # 真实调通 GitHub 公共 REST API
            "base_url": "https://api.github.com", "path": "/zen", "method": "GET",
        })).data["status_code"])                                       # 200

asyncio.run(main())
```

---

## 提供的工具（14 个）

交付规格点名的 7 项工具**名称与语义完全对齐**（下表加粗项），另附 7 项把四个阶段做深的能力。

| 工具 | 阶段 | 功能 |
|---|---|---|
| **`parse_openapi_spec`** | BUILD | 解析 spec，展开 `$ref`、合并 path 级与 operation 级 parameters、识别鉴权方案与分页参数，产出带 JSON Schema 的操作清单 |
| **`list_operations`** | BUILD | 可读操作清单，标注「需鉴权 / 支持分页 / 已废弃」 |
| **`call_rest_api`** | BUILD | 通用 REST 调用（online-callable capability 本体），带 SSRF 防护 |
| `verify_api` | VERIFY | 并发真实调用，**只把 HTTP 2xx 记为通过**，区分需鉴权 / 参数错误 / 不可达；**支持 scope 先策展再验证** |
| **`generate_mcp_tool_code`** | MCPize | 单 operation → 可部署 FastMCP 工具源码（带重试与鉴权） |
| `generate_mcp_bundle` | MCPize | spec → 完整可部署包（落盘，受路径白名单保护）；**支持 scope 工具策展** |
| `preview_scope` | MCPize | **预览 scope 策展效果**：原始端点数 vs 过滤后工具数、推荐维度、保留操作清单 |
| `build_manifest` | MONETIZE | 上架清单：工具级 `input_schema`、鉴权要求、能力统计、计费档位与额度；**支持 scope 策展后上架** |
| `usage_report` | MONETIZE | 真实用量：总调用数、成功率、逐 operation 调用数与平均延迟 |
| `simulate_invoice` | MONETIZE | 按计价档出账：额度、超额、单价、应付金额与逐 operation 明细 |
| `register_api_from_spec` | 底座 | 注册 spec（原子写入，重启不丢） |
| **`call_registered_api`** | 底座 | 按 operation_id 调用并计入用量，**同时接受扁平参数与 `params` 对象** |
| `list_registered_apis` | 底座 | 列出已注册 API 及其鉴权方案 |
| **`health_check`** | 底座 | 健康检查（live 证据） |

---

## 为什么能拿头奖（核心差异化）

官方口号是 **Build → Verify → MCPize → Monetize**。多数作品停在 MCPize——把 spec 转成 MCP 就交差。
MCPForge 把四阶段**全部做真**，而最锋利的两刀是别人普遍空着的：

- **Verify 做真**：`verify_api` 只有 HTTP 2xx 才记 passed，401/403/404/429/5xx 严格区分。
  常见实现「有响应就算可调用」，于是 404 也全绿、指标恒为真、毫无意义。
- **Monetize 做真**：真实计量每次调用（`usage.json` 原子写）→ 用量报表 → 按档位出账，
  直接产出「按次付费就绪」的可上架工具，喂进 agent 经济（x402 / OKX.AI 结算对齐）。

评委看到自己喊的口号被一个作品**逐字、真实**地实现——记忆点立住。工具策展（下一节）
是让这套能力更好用的**支撑能力**，不是差异本身。

## 支撑能力：工具策展（Tool Curation）——从「生成全部」到「生成对的」

竞品（Speakeasy/Gram/liblab/openapi-mcp-generator 等）的通病是：一份 100 端点的 spec 直接导出 100 个工具。
这会把 Agent 的上下文窗口撑爆、降低工具选择准确率，是行业公认的「工具爆炸」问题。

MCPForge v2.1 在生成链路中内建了 **scope 工具策展层**：

```python
{
  "include_tags": ["pet"],           # 只保留指定 tag
  "include_methods": ["GET"],        # 只保留 GET
  "include_path_patterns": ["/pet/*"], # 路径通配
  "exclude_deprecated": True,        # 排除已废弃
  "intent": "user account",          # 语义意图 + top_n 取最相关
  "top_n": 5
}
```

效果（以 Swagger Petstore 为例）：

| 场景 | 原始端点 | 策展后工具 | 压缩率 |
|---|---|---|---|
| 全部导出 | 19 | 19 | 0% |
| 只导出 `pet` 相关 GET | 19 | 3 | 84% |
| 按意图取 top 5 | 19 | 5 | 74% |

这是从「又一个 OpenAPI→MCP 生成器」到「Agent-Ready API 网关」的关键跳跃：
**不是让 Agent 面对 100 个工具，而是让 Agent 只拿到它当前任务需要的 5 个。**

---

## 四个阶段分别做了什么（可核对的差异）

| 阶段 | 做法 | 为什么与常见实现不同 |
|---|---|---|
| **BUILD** | 真解析：`$ref` 展开、path 级参数合并、鉴权方案识别、分页参数识别、OpenAPI 2.0 与 3.x 双版本 | 多数实现只读 `operationId` 和 `path`；遇到 `$ref` 参数或 2.0 文档就丢字段 |
| **VERIFY** | 真断言：2xx=通过，401/403=需鉴权，404=不存在，429=限流，其他 4xx=参数错误，网络失败=不可达；并发执行 + 有界超时 | 常见做法是「有 HTTP 响应就算可调用」，于是 404/500 也全绿，指标恒为真、失去意义 |
| **MCPize** | 生成**可运行**的包：URL 用模板 + `str.replace` 构造（不是 f-string 插值）、docstring 转义、函数名去重、3 次重试、版本线钉死 | f-string 插值遇到 `{account-id}` 这类占位符会产出 `NameError` 的代码；摘要含三引号会把生成文件弄成语法错误 |
| **MONETIZE** | 真实计量（每次调用落盘）→ 用量报表 → 按档位出账，并支持「观测日均外推 30 天」的真实计费口径 | 把 Monetize 实现成打印一个价目表，既无计量也无出账，等于把口号复读一遍 |

---

## 这份 v2 是一次对抗式复核的产物

v1 交付后，我们用「干净上下文、以证伪为目标」的对抗式复核对产物做了两轮独立审查
（技术契约 24 条 + 竞争可行性 12 条发现）。复核结论不客气：v1 的「差异化」有两处是自我作废的——
`verify_api` 里写着「任何 HTTP 响应都算可达」，于是 404 也记通过，指标恒为真；
`build_manifest` 本质是打印一个 dict。此外还暴露了 4 个真 bug：

| 复核发现 | 后果 | 本版处置 |
|---|---|---|
| 粘贴的 spec 文本被误判为文件路径 | 声称支持的「三种来源」中，粘贴源**必然崩溃** | 改为「先试真身再谈形状」，并补回归测试 |
| `verify_api` 任何响应都算可达 | 差异化卖点自我作废 | 改为真实状态码判定表 |
| 代码生成把原始路径塞进 f-string | 含 `{account-id}` 的路径产出 `NameError` | 改为模板 + `str.replace` |
| 生成物落盘与本地读取无边界 | 任意文件读 / 目录穿越写 / SSRF | 加允许根、名称白名单、出网校验 |
| SSRF 校验只覆盖初始 URL，而 httpx 默认跟随重定向 | **公开 URL 302 到 127.0.0.1 即可整体绕过防护**（已实测复现：`status_code=200`，读到内网内容） | 改为逐跳校验，见下方「重定向绕过」一节 |
| 工具名与规格不符 | 可能卡资格检查 | 补齐 `parse_openapi_spec` |
| 零部署、无在线端点 | 误判为过不了 deploy-and-validate 硬门 | 已澄清：官方确认提交前不需自建 MCP Server；本地 `uvicorn demo_app:app` 即提供可调用的 `/mcp` 端点 |
| 无测试、无 CI，验收依赖实时公网 | 证据会腐化，缺陷被绿灯掩盖 | 59 项测试（53 离线 + 6 在线），CI 配置随附 |
| 工具爆炸：100 端点导出 100 个工具 | Agent 上下文被撑爆，工具选择准确率下降 | 新增 scope 工具策展层，可按 tag/方法/路径/意图压缩工具集 |

复核者指出的 3 条被我判为「契约误读」并说明了原因（是我给复核者的产物摘录不完整所致），
未据此改代码——复核结论是数据，不是判决。

---

## 与交付规格的一处必要差异（附实证）

规格第 6 项要求 `call_registered_api(name, operation_id, **params)`。
**FastMCP 4.0.3 无法注册带 `**kwargs` 的工具**，实测报错原文：

```
ValueError: Functions with **kwargs are not supported as tools
```

两种常规绕法也已实测排除（`Tool.from_function(parameters=...)` 与 `@mcp.tool(parameters=...)` 均报
`TypeError: unexpected keyword argument 'parameters'`）。

本项目的解法见 `fastmcp_kwargs.py`：`fastmcp.tools.Tool` 是 Pydantic 模型且执行入口
`run()` 可覆写，因此子类化它、用显式 `inputSchema` 声明 `additionalProperties: true`，
即可以 MCP 协议透传任意参数名。**两种写法都通过协议栈实测**：

```
{"name":"petstore","operation_id":"getPetById","petId":1}        # 规格字面写法
{"name":"petstore","operation_id":"getPetById","params":{...}}   # 等价写法
```

---

## 安全边界（默认开启，可按需放宽）

作品面向公网，因此默认不做「任意文件读 / 任意路径写 / 任意地址请求」：

| 边界 | 默认行为 | 放宽方式 |
|---|---|---|
| 本地 spec 读取 | 限定在当前工作目录内 | `MCPFORGE_READ_ROOTS` 指定多个根，或 `MCPFORGE_ALLOW_ANY_PATH=1` |
| 生成物落盘 | 名称白名单 + 结果必须位于输出根之内 | — |
| 出网 | 拒绝回环 / 内网 / 链路本地 / 保留地址与云元数据端点；**重定向逐跳重新校验** | `MCPFORGE_ALLOW_PRIVATE_NET=1`（本地联调用） |
| 计量与注册表 | 原子写入；文件损坏时留档 `.corrupt.json` 而非静默清空 | — |

### 关于「重定向绕过」这个洞（为什么值得单独写一段）

`httpx` 的 `follow_redirects=True` **只在初始 URL 上**给校验一次机会。
于是存在这样一条完全成立的攻击路径：攻击者提交一个**公网** URL（顺利通过 SSRF 校验），
该地址 302 到 `http://127.0.0.1:...` 或 `http://169.254.169.254/latest/meta-data/`，
httpx 会自动跟过去——防护整体失效。

我们**在本地把它复现出来了**（公开重定向服务 → 本地 8123 端口的内网服务）：

```
== 绕过尝试：公开 URL 302 跳内网 ==
  status_code = 200
  final url   = http://127.0.0.1:8123/
  >>> 读到内网内容
```

修法是 `core.request_with_validated_redirects()`：手动跟跳，**每一跳都重新做公网校验**，
并按 RFC 语义处理 303/302 的方法改写，同时给重定向环设有界上限。
四条回归用例已把它锁死（内网目标、云元数据目标、正常跨域跳转不被误伤、重定向环有界退出）。

> 这也是本次提交里我们最想强调的一点：一个「看起来很安全」的默认参数，
> 足以让整套防护在真实攻击面前归零——而只有把它真跑一遍才会知道。

---

## 运行

```bash
pip install -r requirements.txt

# 方式 A：单进程同时提供走查页 + 健康检查 + MCP 端点（推荐）
python app.py                       # 访问 http://localhost:8000
#   或 uvicorn demo_app:app --host 0.0.0.0 --port 8000

# 方式 B：只跑 MCP 服务（stdio 调试界面）
fastmcp dev server.py

# 方式 C：只跑 MCP 服务并暴露为 HTTP
fastmcp run server.py --transport streamable-http --port 8080

# 方式 D：容器
docker build -t mcpsforge . && docker run -p 8000:8000 -v mcpsforge-data:/data mcpsforge
```

## 测试与验收

```bash
pip install -r requirements-dev.txt

pytest                 # 53 项离线用例（确定性，不联网）
pytest -m live -v      # 6 项在线用例（真实调用公开 API）
python verify.py       # 双层验收，产出 verification-evidence.md
python examples/build_examples.py   # 重新生成四个示例包
python docs/judge_check.py          # 评委现场复核：一条命令核对在线端点与契约工具
```

CI 配置在 `.github/workflows/ci.yml`。**如实说明**：它位于作品子目录内，在官方提交仓库中
GitHub 不会读取（Actions 只扫描仓库根的 `.github/workflows/`）；把本目录作为独立仓库使用时即可启用。
本地等价命令是 `pytest`，无需 CI 即可复现。

---

## 目录结构

```
api-mcp-toolkit/
├── server.py              # FastMCP 服务（14 个工具，四阶段映射）
├── core.py                # 核心逻辑（解析/验证/代码生成/清单/持久化注册表/工具策展）
├── metering.py            # 计量与计费（usage.json 原子写、出账、月度外推）
├── fastmcp_kwargs.py      # 让 FastMCP 支持 **kwargs 工具（含实测依据）
├── demo_app.py            # 可视化走查页 + 挂载的 /mcp 端点 + 健康检查
├── app.py                 # 部署入口（读 PORT、绑定 0.0.0.0）
├── verify.py                 # 双层验收脚本（离线 + 在线），产证据文件
├── static/index.html         # 走查页前端（含工具策展面板）
├── docs/                     # 评委证据：截图 + 一键复核脚本 + 流水线响应
│   ├── screenshots/          # 真实 Chrome 无头截图
│   ├── judge_check.py        # 评委现场复核脚本
│   ├── judge_check_result.txt # 11/11 PASS 本地实测输出
│   ├── full_pipeline_result.json
│   ├── full_pipeline_summary.md
│   ├── MARKET_RESEARCH.md    # 市场调研与竞争格局
│   └── evidence.md           # 证据总览
├── tests/                    # 53 项离线用例（test_core 46 + test_contract_compat 7）+ 6 项在线用例（test_live）+ 离线 fixture
├── examples/                 # 四个异构示例包（生成脚本可复现）
├── Dockerfile / requirements*.txt / pyproject.toml
└── .github/workflows/ci.yml
```

### 四个示例包（形态各不相同，均为真实生成产物）

| 示例 | 源 spec 形态 | 工具数 |
|---|---|---|
| `petstore-v3-mcp` | OpenAPI 3.0 / JSON / `servers.url` 为相对路径 / oauth2 + apiKey | 19 |
| `petstore-v2-mcp` | **OpenAPI 2.0**（`swagger` + `host` + `basePath`） | 20 |
| `httpbin-mcp` | OpenAPI 3.0 / YAML / 免鉴权 | 73 |
| `fx-mcp` | 汇率 API（规格要求「天气/汇率」，天气/汇率在 `verify.py` 在线层中已覆盖） | 1 |

四个生成包都已实测可被 FastMCP 加载并注册工具（不只是「看起来像代码」）。

---

## 目录位置与提交

本目录须位于官方提交仓库的：

```
submissions/mcp-hackathon/<你的GitHub用户名>-api-mcp-toolkit/
```

即 Fork `github.com/xagentAI/xagt-plugin` 后，把本文件夹整体复制进 `submissions/mcp-hackathon/`
并改名，再开 PR（标题含「项目名 + Open Innovation」）。

## 合规声明

- 本作品是通用 API/MCP 工程能力，**不含漏洞检测、风险评分、钓鱼/诈骗检测、安全监控、
  合规分析**等任何安全/审计/链上安全外壳，符合官方禁赛红线。
- 关于 `verify_api` 与 `call_rest_api` 的 SSRF 防护：这二者是**被调用方（API 提供方）视角的
  工程健壮性**——`verify_api` 只是对「API 是否在线、返回什么状态码」做真实判定；SSRF 防护是
  **工具自身作为 HTTP 客户端时的自保**（拒绝把请求发往回环/内网/云元数据），属于「安全地调用
  外部 API」，而非「提供安全检测/审计能力」。二者都**不产出任何安全研判、风险评分或告警**，
  因此不构成安全/审计外壳。
- 计量与账单的默认币种为 `USD`（可用 `MCPFORGE_CURRENCY` 覆盖）；
  本作品仅作工程作品集用途，**不参与任何代币投机**。
