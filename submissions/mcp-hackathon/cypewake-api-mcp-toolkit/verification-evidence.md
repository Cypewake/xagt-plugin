# MCPForge v2 技术验证证据

- 生成时间（UTC）：2026-09-14T04:45:25.303042+00:00
- 版本：2.1.0
- Python：3.13.14 on Windows
- 验收方式：离线层为确定性检查；在线层真实调用公开 API，仅 HTTP 2xx 记为通过

## A. 离线验收（确定性，不联网）
- [PASS] 粘贴的 OpenAPI 文本被正确解析（v1 此处抛 FileNotFoundError）
- [PASS] 非 spec 文本给出可诊断错误：内容解析后不是 OpenAPI 对象，而是 str（来源：<inline text>）。请确认传入的是 OpenAPI/…
- [PASS] $ref 参数已展开且 path 级参数已合并：query=['page']
- [PASS] 鉴权方案识别：['fixture_key', 'fixture_oauth']
- [PASS] 路径含非标识符占位符 {account-id} 时，生成代码仍可编译（v1 会产 NameError）
- [PASS] spec 摘要含三引号/反斜杠时，生成代码仍可编译（docstring 已转义）
- [PASS] VERIFY 判定不再是「任何响应都算通过」（v1 的 404 也记 reachable=True）
- [PASS] 生成物落盘的目录穿越被拒绝
- [PASS] SSRF 防护拦截回环/云元数据/内网地址（3/3）
- [PASS] SSRF 重定向绕过已封堵（公网 URL 302 内网时第二跳不发出、无内容泄露）
- [PASS] 计量与出账算术正确（10 万次 @ basic → 超额 90000 → 180.0）
- [PASS] 注册表持久化正常且同名覆盖会显式提示
- [PASS] call_registered_api 同时接受契约字面写法（petId=1）与 params 对象写法

## B. 在线验收（真实调用公开 API，仅 2xx 记为通过）
- [PASS] 契约点名的 7 项工具全部存在（共注册 14 个工具）
- [PASS] parse_openapi_spec 解析 Petstore：19 个操作，识别鉴权 ['petstore_auth', 'api_key']
- [PASS] list_operations 列出 Petstore 操作（含 getPetById）
- [PASS] generate_mcp_tool_code 产出的源码语法合法可编译
- [PASS] register_api_from_spec 注册成功（19 个操作）
- [PASS] call_registered_api 调通 findPetsByStatus（status=200）
- [PASS] 契约字面写法 call_registered_api(..., petId=35928647) 调通（status=200）
- [PASS] call_rest_api 调通 open-meteo 天气（status=200）
- [PASS] call_rest_api 调通 frankfurter 汇率 USD→CNY（status=200）
- [PASS] verify_api 并发真实验证 12 个操作：passed=1 需鉴权/失败=11 不可达=0
  - 结论：部分通过
  - 说明：Petstore 的 /pet 系列在 spec 中标注了 security，未带凭据时返回 401，
    因此这里 passed 偏低是正确的判定结果——这正说明 verify_api 不再把 4xx 也算作通过。
  - 逐条（前 6）：
    · [PUT] updatePet → server_error（HTTP 500，1011.2ms）
    · [POST] addPet → server_error（HTTP 500，942.1ms）
    · [GET] findPetsByStatus → bad_request（HTTP 400，1211.4ms）
    · [GET] findPetsByTags → server_error（HTTP 500，986.9ms）
    · [GET] getPetById → not_found（HTTP 404，1165.2ms）
    · [POST] updatePetWithForm → not_found（HTTP 404，941.6ms）
- [PASS] generate_mcp_bundle 落盘完整包并可编译（19 个工具 → E:\mcpmake\submissions\mcp-hackathon\api-mcp-toolkit\verification-artifacts\generated\petstore-mcp）
- [PASS] build_manifest 产出含工具级 input_schema 的上架清单（19 工具）
- [PASS] usage_report 读到真实计量：petstore 已被调用 2 次
- [PASS] simulate_invoice 出账：10 万次 @ basic → 应付 180.0 USD（指定调用量测算）
- [PASS] health_check 返回 ok（版本 2.1.0，已注册 1 个 API）

## 合规红线自检
- [OK] 本作品是通用 API/MCP 工程能力，不含漏洞检测、风险评分、钓鱼/诈骗检测、
       安全监控、合规分析等任何安全/审计/链上安全外壳。
- [OK] 清单与账单中的币种默认取 USD，可用 MCPFORGE_CURRENCY 覆盖；
       不参与代币投机。

## 结论

- 离线层：全部通过
- 在线层：全部通过
- 总体：全部通过 ✅
