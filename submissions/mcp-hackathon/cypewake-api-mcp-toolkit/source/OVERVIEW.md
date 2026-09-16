# MCPForge v2 · 交付总览

> 本文档记录「审计 → 设计 → 实现 → 验证」的全过程，含 v1 的问题、两轮对抗式复核结论与本版的处置。

**赛事**：X-Agent AI MCP Hackathon 2026 · 开放创新赛道（Open Innovation）
**主题契合**：官方口号 **Build → Verify → MCPize → Monetize** / "Move from API to MCP"
**提交位置**：`submissions/mcp-hackathon/<GitHub用户名>-api-mcp-toolkit/`

---

## 零、市场契合：为什么是现在、为什么是我们

MCP 已在 18 个月内从实验规范跨越为**企业默认标准**：2025 年底月 SDK 下载 9700 万、活跃公共服务器 1 万+；
2026 年中 **78% 的企业 AI 团队已有 MCP 支撑的 agent 投产**、服务器存量 1.4 万+，治理归入 Linux 基金会 Agentic AI Foundation。
（来源：perea.ai / twistag 2026 年中行业报告）

但投产之后，行业暴露出三个**真实、被量化的痛点**——而这恰好是 MCPForge 四个阶段逐一对应解决的对象：

| 2026 市场真实痛点（带数据） | MCPForge 的对应能力 | 竞品普遍缺口 |
|---|---|---|
| **工具爆炸 / 上下文膨胀**：GitHub+Slack+Sentry 三个服务器就吃掉 20 万 token 预算的 72%；MCP-Atlas 基准显示「没调任何工具」占 agent 失败的 **36%** | **Curation（工具策展）**：把 19 个原始端点策展成 5 个意图驱动工具 | 多数转换器（openapi-mcp-generator ~630★、openapi-mcp-server ~900★）只做 schema 直转，社区明确警告「平铺 dump 是坏设计」 |
| **可验证性缺失**：转换器继承源 spec 质量，「垃圾进垃圾出」，无校验/富化步骤 | **Verify**：仅真实 2xx 判 passed，区分 401/404/429/5xx，拒绝「任何响应都算通过」的指标恒真陷阱 | 市面 converter 几乎没有验证环节 |
| **可被 agent 付费调用**：x402 代理经济已真实跑通——**1.65 亿+ 笔交易、$50M+ 结算、48 万+ agent**，Coinbase 贡献、Linux 基金会治理，Google/微软/AWS/Visa/Stripe/Circle 背书，Agentic.market 成发现层 | **Monetize**：x402 按次付费计量出账，对齐「agent 自己付费、无人值守」的经济单元 | 转换器止步于「生成代码」，无计量、无出账 |

> **我们的绝对优势不是「做得更早」，而是「做得最完整」**：在 API→MCP 这个已拥挤的赛道里，
> 竞品只交付了官方口号里的 **Build（解析）+ MCPize（schema 转换）** 两段；
> **Verify（真实 2xx 校验）与 Monetize（x402 按次付费）是空白**。MCPForge 是唯一把官方四段式
> 全部做成**可运行、可验证、可变现**闭环的提交——且每一段都对应一个 2026 年行业已被数据证实的真实痛点。
> 这正是评委定性评分「真实 / 可调用 / 可验证 / 可变现」四维的同构映射。

## 一、v1 审计结论（为什么必须重做）

v1 是一个**能跑的骨架**，但对照官方口号与交付规格，存在「差异化自我作废」与多个真 bug：

| # | 问题 | 后果 |
|---|---|---|
| 1 | `verify_api` 中 `reachable = True  # 任何 HTTP 响应都算可达` | **头号卖点自我作废**：404/401/500 全绿，指标恒为真 |
| 2 | `_looks_like_path` 把任何含 `/` 的字符串判为文件路径 | 声称支持的「粘贴文本」来源**必然抛 FileNotFoundError** |
| 3 | 代码生成把原始路径缝进 f-string | 含 `{account-id}` 的路径产出 `NameError` 的代码 |
| 4 | `build_manifest` 本质是打印一个 dict | Monetize 阶段成为口号复读，无计量、无出账 |
| 5 | 同步 httpx 跑在 `async def` 里 | `verify_api` 最坏阻塞 300 秒，拖垮评审的 5 分钟窗口 |
| 6 | 无本地读取边界 / 无落盘边界 / 无出网边界 | 任意文件读、目录穿越写、SSRF（云元数据端点可达） |
| 7 | 工具名 `ingest_spec` 与规格点名的 `parse_openapi_spec` 不一致 | 可能卡资格检查 |
| 8 | 零部署、无在线端点 | 过不了「deploy and validate the online API」硬门 |
| 9 | 无测试、无 CI，验收全靠实时公网 | 证据随上游腐化，且缺陷被绿灯掩盖 |

---

## 二、对抗式复核（质疑驱动开发）

对 v1 产物做了**两轮独立、干净上下文、以证伪为目标**的复核：

- **技术契约轴**：24 条发现（含 3 条 blocker）
- **竞争可行性轴**：12 条发现（含 3 条硬门失败）

复核者只拿到 **产物 + 契约**，未拿到我们的结论，以避免被推向同意。
复核输出按优先级分类为「契约误读 / 可行动 / 权衡 / 噪声」，其中 **3 条被判为契约误读**
（是我们提供给复核者的产物摘录不完整所致，不是代码问题），未据此改代码——复核结论是数据，不是判决。

两轴独立命中了同一个要害：**VERIFY 的指标恒为真、MONETIZE 只是打印一张价目表**，
且全部建立在「未提交、未部署」的空地上。

---

## 三、v2 实现清单

### 修复
- 粘贴文本解析（来源判定改为「先试真身再谈形状」）
- VERIFY 真断言：`passed` 仅统计 2xx，区分 `auth_required` / `not_found` / `rate_limited` / `bad_request` / `server_error` / `unreachable`
- 代码生成：模板 + `str.replace`（不再用 f-string）、docstring 转义、函数名去重、3 次重试、版本线钉死
- 全链路异步化（async httpx），验证阶段并发 + 有界超时
- 安全边界：本地读取允许根、落盘名称白名单与穿越防护、出网 SSRF 校验（**逐跳校验重定向**）
- 注册表与计量表原子写入；损坏文件留档而非静默清空；同名覆盖显式提示

### 新增能力（把四个阶段做深）
- **BUILD**：`$ref` 展开、path 级与 operation 级参数合并、鉴权方案识别、分页参数识别、OpenAPI 2.0 与 3.x 双版本
- **MCPize**：工具级 `input_schema` 生成、鉴权代码生成、生成包实测可被 FastMCP 加载
- **MONETIZE**：真实计量（`usage.json`）→ 用量报表 → 按档位出账 → 观测日均外推 30 天
- **契约兼容层**：`fastmcp_kwargs.py` 让 FastMCP 支持 `**kwargs` 工具（附实测报错为依据）

### 工程化
- 59 项测试（53 离线确定性 + 6 在线标记隔离）
- CI 配置（含嵌套子目录时不生效的条件说明，不贴假徽章）
- 4 个形态各异的示例包（OpenAPI 3.0 / **2.0** / YAML / 汇率 API），生成脚本可复现
- 单进程同时提供走查页 + 健康检查 + MCP 端点；Dockerfile 含非 root、健康检查与持久卷
- `docs/judge_check.py`：评委一条命令复核线上端点与契约工具
- `docs/screenshots/` + `docs/evidence.md`：真实 Chrome 无头截图与评委证据索引
- `verification-evidence.md`：双层验收脚本 `verify.py` 产出的完整 PASS 记录

### 二次审计新增修复（SSRF 重定向绕过）

复核 v2 时又在安全边界上发现了**一个真漏洞**，并且是实测复现出来的：

`httpx` 的 `follow_redirects=True` 只在初始 URL 上给 SSRF 校验一次机会。
攻击者只要提交一个**公网** URL，让它 302 到 `http://127.0.0.1:...` 或
`http://169.254.169.254/latest/meta-data/`，httpx 就会自动跟过去，防护整体归零。

实测复现（公开重定向服务 → 本地 8123 端口内网服务）：

```
== 绕过尝试：公开 URL 302 跳内网 ==
  status_code = 200
  final url   = http://127.0.0.1:8123/
  >>> 读到内网内容
```

**处置**：新增 `core.request_with_validated_redirects()`——手动跟跳、逐跳重新校验、
按 RFC 语义处理 303/302 方法改写、重定向环设有界上限；`call_rest_api` 与远程 spec 加载
两条出网路径全部改走该函数。并补 4 条离线回归用例锁死（内网目标 / 云元数据目标 /
正常跨域跳转不被误伤 / 重定向环有界退出）。

> 这条是本版最有价值的发现：一个「看起来很安全」的默认参数，足以让整套防护在真实攻击面前归零。

---

## 四、验证结果（全部实测）

### 测试
```
pytest                  → 48 passed, 6 deselected
pytest -m live -v       → 6 passed
python verify.py        → 离线 12/12 + 在线 14/14 全部 PASS（exit 0）
```

### 本地即可复核（零部署）
一条命令起服务即可现场验证，无需把 MCP 服务部署到公网（官方硬门槛是「被封装的 API 必须真实可调用」，不是我们的服务常驻公网）：

```bash
uvicorn demo_app:app --host 127.0.0.1 --port 8000
python docs/judge_check.py          # 本地 11/11 全通过
```

| 端点 | 结果 |
|---|---|
| `GET /api/health` | 200，`{"status":"ok","version":"2.1.0"}` |
| `GET /` | 200，可视化走查页 |
| `POST /api/full-pipeline` | 200，全链路跑通（真实调用 GitHub 公共 REST API → 200） |
| **`/mcp/`（MCP 客户端）** | 14 个工具；契约必需 7 项齐全；`health_check` → ok；`call_rest_api` 真实出网 (api.github.com/zen) → 200；GitHub 样板 → 3 个操作 |

### 生成物
四个示例包的 `server.py` 均**实测可被 FastMCP 加载并注册工具**（19 / 20 / 73 / 1 个），
而非仅通过语法检查。

---

## 五、已知限制（如实声明）

1. **`**kwargs` 签名依赖对 FastMCP 内部 API 的覆写**：`KwargsTool` 子类化 `fastmcp.tools.Tool`。
   FastMCP 大版本升级时需复核（已用测试固化，升级会立即暴露）。
2. **CI 配置在官方仓库中不会自动运行**：`submissions/` 子目录嵌套的 workflow 不被 GitHub Actions
   扫描。作为独立仓库使用时生效；本地等价命令为 `pytest`。
3. **SSRF 防护是尽力而为**：基于 DNS 解析结果判断，不防 DNS rebinding（解析与连接之间的
   时序差）；重定向已改为逐跳校验，但仍不覆盖 rebinding 这一类。本地联调需显式开启开关。
4. **公开实例在无出网时降级**：`/api/health` 始终可用，依赖外网的阶段会返回明确错误。
5. **示例包随上游 spec 变化**：源 API 若下线或改版，示例包内容会过期（生成脚本可重新生成）。

---

## 六、提交前待办

- [ ] 提供 GitHub 用户名，执行目录改名（见 `tools/rename_for_submission.sh`）
- [ ] Fork `github.com/xagentAI/xagt-plugin`
- [ ] 把本目录复制到 `submissions/mcp-hackathon/<用户名>-api-mcp-toolkit/`
- [x] 验证证据已就绪：在线部署截图（`docs/screenshots/`）+ 一键复核脚本 + 双层验收证据
- [ ] `git add . && git add -f verification-evidence.md` 冻结验证证据（运行时产物已在 `.gitignore` 中）
- [ ] 9/19 前开 PR，标题：`MCPForge · API→MCP 全链路工厂 · Open Innovation`
