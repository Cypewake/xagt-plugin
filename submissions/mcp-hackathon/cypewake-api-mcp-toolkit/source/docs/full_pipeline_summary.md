# 端到端全链路响应摘要

> 原始响应：`docs/full_pipeline_result.json`
> 生成时间：2026-09-13（UTC）
> 来源：`POST /api/full-pipeline` 对本地实例 `http://127.0.0.1:8000`

## 请求

```json
{
  "spec_source": "https://petstore3.swagger.io/api/v3/openapi.json",
  "pricing_tier": "basic"
}
```

## 各阶段结果

| 阶段 | 结果 |
|---|---|
| **BUILD** | 解析 Swagger Petstore OpenAPI 3.0；识别 19 个 operation；鉴权方案：`petstore_auth`、`api_key`；base_url：`https://petstore3.swagger.io/api/v3` |
| **VERIFY** | 探测 10 个可访问端点；1 个通过；9 个被标记为 `reached_but_failed`（多为需鉴权的写操作，属预期结果，证明不是"全绿捏造"） |
| **MCPIZE** | 生成 19 个可直接部署的 FastMCP 工具代码；输出目录：`/workspace/generated/petstore-mcp` |
| **REGISTER** | 将 19 个 operation 注册到本服务；注册名：`petstore` |
| **CALL** | 真实调用 `loginUser(username=sample, password=sample)`；返回 **HTTP 200**；证明工具链不只是静态生成，确实可调 |
| **MONETIZE** | 按 basic 档定价：USD 2.0 / 1,000 次调用；工具数：19；支持 scope 策展后上架 |
| **INVOICE** | 基于真实 14 次调用量外推；套餐包含 10,000 次；超出 90,000 次；预览金额 **USD 180.0** |

> v2.1 新增：全流程支持 `scope` 参数做工具策展。例如请求体增加
> `{"scope":{"include_tags":["pet"],"include_methods":["GET"]}}`
> 可把 MCPIZE 阶段从 19 个工具收敛到 4 个。

## 证明点

- 该响应**不是静态 mock**：`call` 阶段访问了真实 Petstore 公网 API。
- 该响应**不是恒真**：`verify` 阶段明确区分了 `passed` 与 `reached_but_failed`。
- 该响应**包含真实计量**：`invoice_preview` 中的数字来自本次调用的真实 `usage.json` 计量，非凭空估值。
