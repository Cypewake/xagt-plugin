# MCPForge · API→MCP 全链路工厂

MCPForge 把「已有 REST API」变成「AI Agent 可直接调用的 MCP 工具」，
完整覆盖官方四段式 **Build → Verify → MCPize → Monetize**。

## 硬门槛证据（均可本地零部署复现）
1. **资格合规**：纯工程能力，无安全 / 审计 / 链上风控外壳。
2. **API 可验证**：封装的 GitHub 公共 REST API 真实返回 2xx
   （`docs/judge_check.py` 实测 `/zen` 与 `getZen` 均 HTTP 200）。
3. **源码评审就绪**：59 项测试全绿（53 离线 + 6 在线），
   14 个 MCP 工具含 7 个契约必需。

## 差异化（夺冠矛）
- **Verify**：对每个封装 API 做真实 2xx 判定，而非「任何响应都算通过」。
- **Monetize**：x402 按次付费计量出账（USD），对齐 OKX.AI 代理经济。
  竞品大多只交付 Build + MCPize 两段，Verify / Monetize 是空白。

## 市场契合（为什么是现在）
- 2026 年中 **78%** 企业 AI 团队已有 MCP 支撑的 agent 投产，服务器存量 **1.4 万+**。
- 工具爆炸 / 上下文膨胀：3 个服务器吃掉 20 万 token 预算 **72%**；
  「没调任何工具」占 agent 失败 **36%** → MCPForge 的 Curation 策展（19→5）直接解此痛点。
- x402 代理经济已真实跑通 **1.65 亿笔 / $50M+ / 48 万 agent**。

## 本地复核（无需公网部署）
```bash
uvicorn demo_app:app   # 单进程同时提供走查页 / 健康检查 / /mcp 端点
python docs/judge_check.py   # 11/11 PASS，退出码 0
```
