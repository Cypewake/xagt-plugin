"""
server.py · MCPForge v2 —— API→MCP 全链路工厂（X-Agent AI MCP Hackathon 2026 · 开放创新赛道）

严格映射官方口号 Build → Verify → MCPize → Monetize：

  BUILD     parse_openapi_spec / list_operations / call_rest_api
  VERIFY    verify_api（真实断言 2xx，非「有响应就算通」）
  MCPize    generate_mcp_tool_code / generate_mcp_bundle（完整可部署包）
  MONETIZE  build_manifest / usage_report / simulate_invoice（真实计量 → 出账）
  底座       register_api_from_spec / call_registered_api / list_registered_apis / health_check

合规：纯 API/MCP 工程能力，不含任何安全/审计/链上安全外壳，符合禁赛红线。

运行：
    pip install -r requirements.txt
    fastmcp dev server.py                                   # stdio 调试界面
    fastmcp run server.py --transport streamable-http --port 8080   # 暴露为 HTTP
"""

from __future__ import annotations

from typing import Optional

from fastmcp import FastMCP

import core
import metering
from fastmcp_kwargs import make_kwargs_tool, merge_params

mcp = FastMCP("MCPForge")


# ============================== BUILD ====================================== #
@mcp.tool()
async def parse_openapi_spec(spec_source: str) -> dict:
    """[BUILD] 解析 OpenAPI/Swagger 描述，返回结构化 operation 列表。

    spec_source 支持三种来源：http(s) URL、本地文件路径、直接粘贴的 JSON/YAML 文本。
    会展开本地 $ref、合并 path 级与 operation 级 parameters，并识别鉴权方案与分页参数。
    每个 operation 附带 input_schema（JSON Schema），可直接用于工具入参校验。
    """
    return await core.parse_openapi_spec_async(spec_source)


@mcp.tool()
async def list_operations(spec_source: str) -> str:
    """[BUILD] 列出某 API 的全部可调用操作（方法 / 路径 / operation_id），并标注是否需鉴权、支持分页、已废弃。"""
    return await core.list_operations_async(spec_source)


@mcp.tool()
async def call_rest_api(
    base_url: str,
    path: str,
    method: str = "GET",
    query: Optional[dict] = None,
    body: Optional[dict] = None,
) -> dict:
    """[BUILD] 通用 REST 调用：直接调通任意公开 API，返回状态码、耗时与响应预览（前 2000 字符）。

    这是本服务的 online-callable capability 本体——任何 Agent 都能拿它调通任意 REST 接口，
    无需先有 spec。出网带 SSRF 防护（默认拒绝回环/内网/链路本地地址）。
    """
    return await core.call_rest_api_async(base_url, path, method, query, body)


# ============================== VERIFY ===================================== #
@mcp.tool()
async def verify_api(
    spec_source: str,
    max_ops: int = 20,
    timeout: float = 8.0,
    concurrency: int = 8,
    scope: Optional[dict] = None,
) -> dict:
    """[VERIFY] 并发真实调用 spec 中前 max_ops 个 operation，给出可核对的通过/失败结论。

    判定口径是真实的，不是「有响应就算可达」：
      2xx        → passed
      401/403    → auth_required（端点在线，需凭据）
      404        → not_found
      429        → rate_limited
      其他 4xx   → bad_request（占位参数不满足业务校验）
      5xx        → server_error
      网络/超时   → unreachable

    scope 可先策展再验证，避免对无关端点做无效探测。
    """
    return await core.verify_api_async(spec_source, max_ops, timeout, concurrency, scope)


# ============================== MCPize ===================================== #
@mcp.tool()
async def generate_mcp_tool_code(
    spec_source: str,
    operation_id: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
) -> str:
    """[MCPize] 把指定 operation 生成为可直接部署的 FastMCP 工具代码。

    生成的代码：URL 用模板 + str.replace 构造（因此 {account-id} 这类非标识符占位符也不会出错）、
    带 3 次重试、带鉴权头读取。保存为 server.py 后 `fastmcp dev server.py` 即可运行。
    """
    return await core.generate_tool_code_async(spec_source, operation_id, server_name, require_auth)


@mcp.tool()
async def generate_mcp_bundle(
    spec_source: str,
    name: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
    output_dir: str = "generated",
    scope: Optional[dict] = None,
) -> dict:
    """[MCPize] 把 spec 生成完整可部署 bundle，落盘到 output_dir/name/。

    产出 server.py + requirements.txt（已钉大版本线）+ README.md + manifest.json，
    开箱即可 `fastmcp run`。名称与输出目录有白名单与目录穿越防护。

    scope 用于工具策展：例如只导出 tag=pet 的 GET 操作，或按意图取 top 5，
    避免把 100 个端点全部塞进 Agent 的上下文窗口。
    """
    return await core.generate_bundle_async(
        spec_source, name, server_name, require_auth, output_dir, scope
    )


@mcp.tool()
async def preview_scope(spec_source: str, scope: Optional[dict] = None) -> dict:
    """[MCPize] 预览 scope 策展效果：原始 operation 数 vs 过滤后工具数，并给出推荐维度。

    在真正生成 bundle 之前先用它做实验，避免反复落盘。
    """
    return await core.preview_scope_async(spec_source, scope)


# ============================== MONETIZE =================================== #
@mcp.tool()
async def build_manifest(
    name: str,
    spec_source: str = "",
    category: str = "api-tool",
    pricing_tier: str = "free",
    description: str = "",
    base_url: str = "",
    currency: str = "",
    scope: Optional[dict] = None,
) -> dict:
    """[MONETIZE] 生成市场格式上架清单：工具级 JSON Schema、鉴权要求、能力统计、计费档位与额度。

    与「打印一张价目表」的区别在于：清单里每个工具都带可校验的 input_schema，
    并且定价直接对接 usage_report 的真实计量口径，可出账核对。

    scope 可先策展再生成清单，让上架工具集保持精简。
    """
    return await core.build_manifest_async(
        name,
        source=spec_source,
        base_url=base_url,
        category=category,
        pricing_tier=pricing_tier,
        description=description,
        currency=currency or None,
        scope=scope,
    )


@mcp.tool()
async def usage_report(api_name: str = "", days: int = 0) -> dict:
    """[MONETIZE] 查询真实调用用量：总调用数、成功率、逐 operation 调用数与平均延迟。

    数据来自本服务每次调用时的真实计量（usage.json），不是估算。
    api_name 留空则汇总全部已注册 API；days > 0 时只统计最近 N 天有活动的 API。
    """
    return metering.get_meter().report(api_name or None, days or None)


@mcp.tool()
async def simulate_invoice(
    api_name: str,
    pricing_tier: str = "basic",
    basis: str = "actual",
    projected_calls: int = 0,
) -> dict:
    """[MONETIZE] 按计价档把真实用量折算成账单：额度、超额调用数、单价、应付金额与逐 operation 明细。

    计费基准 basis：
      actual（默认）        —— 按已记录的真实调用数出账
      projected_monthly    —— 把观测到的日均调用量外推到 30 天，用于真实报价推演
    projected_calls > 0 时直接按指定调用量测算（容量/报价推演）。

    这是把「可商业化」做成可核对数字的一步：先 register + 调用产生真实用量，再出账。
    """
    return metering.get_meter().simulate_invoice(api_name, pricing_tier, basis, projected_calls)


# ============================== 底座 ======================================= #
@mcp.tool()
async def register_api_from_spec(name: str, spec_source: str) -> dict:
    """把整份 OpenAPI spec 注册进本服务（持久化到 registry.json，原子写入，重启不丢）。

    注册后可用 call_registered_api 按 operation_id 直接调用；
    同名重复注册会返回 overwrote_existing=true（不会静默覆盖）。
    """
    result = await core._registry.register_async(name, spec_source)
    result["hint"] = "可用 call_registered_api 调用，或用 generate_mcp_bundle 导出独立服务。"
    return result


async def _call_registered(name: str, operation_id: str, params: Optional[dict] = None, **extra) -> dict:
    """实现体：同时接受 params 对象与顶层扁平参数，并写入真实用量计量。"""
    merged = merge_params(params, extra)
    return await core._registry.call_async(name, operation_id, merged)


# 契约要求签名为 call_registered_api(name, operation_id, **params)；
# FastMCP 原生不支持 **kwargs（见 fastmcp_kwargs.py 的实测说明），故用 KwargsTool 实现。
mcp.add_tool(
    make_kwargs_tool(
        name="call_registered_api",
        description=(
            "调用已注册 API 的某个 operation，返回真实响应并计入用量。"
            "参数既可扁平传入（如 petId=1），也可放在 params 对象里（params={\"petId\": 1}）；"
            "请求体放在 params[\"__body__\"]。"
        ),
        fn=_call_registered,
    )
)


@mcp.tool()
async def list_registered_apis() -> dict:
    """列出本服务已注册的全部 API：名称、基址、操作数、鉴权方案与注册时间。"""
    names = core._registry.list_names()
    items = []
    for n in names:
        entry = core._registry.get(n) or {}
        items.append(
            {
                "name": n,
                "base_url": entry.get("base_url"),
                "operation_count": len(entry.get("operations", [])),
                "auth_schemes": [s.get("name") for s in entry.get("auth_schemes", [])],
                "registered_at": entry.get("registered_at"),
            }
        )
    return {"count": len(items), "apis": items}


@mcp.tool()
async def health_check() -> dict:
    """健康检查（提交要求的 live 证据）。返回 status=ok 即代表服务在线可调用。"""
    return core.health_check()


if __name__ == "__main__":
    mcp.run()
