"""
fastmcp_kwargs.py · 让 FastMCP 支持 **kwargs 形态的工具（契约精确性所需）

为什么需要这个文件
------------------
本赛事交付规格要求第 6 项工具签名为：

    call_registered_api(name, operation_id, **params)

即「参数名在编译期不可知」，必须靠 JSON Schema 的 additionalProperties 透传。
但 FastMCP 4.0.3 的 `Tool.from_function()` 与 `FastMCP.tool()` 装饰器都会直接拒绝
任何带 VAR_KEYWORD 的函数（实测报错原文）：

    ValueError: Functions with **kwargs are not supported as tools

因此该签名无法用常规装饰器实现。两种常规绕法也已实测排除：

    Tool.from_function(fn, parameters={...})  -> TypeError: unexpected keyword argument 'parameters'
    print(mcp.tool(parameters={...}))          -> TypeError: unexpected keyword argument 'parameters'

解法
----
`fastmcp.tools.Tool` 是 Pydantic 模型，其字段包含 `parameters`，并且执行入口是
可覆写的 `run(arguments: dict) -> ToolResult`。因此直接子类化 `Tool`：

  - 用显式 inputSchema 声明 additionalProperties=true；
  - 在 run() 里把 arguments 原样 kwargs 展开交给目标函数。

实测两种调用形式均可通过 MCP 协议栈成功（见 tests/test_contract_compat.py）：
    {"name":"petstore","operation_id":"getPetById","petId":1}      # 契约字面写法
    {"name":"petstore","operation_id":"getPetById","params":{...}} # 等价写法

这是一个刻意的、有边界的最小绕行：只影响一个工具的入参编解码，不触碰 FastMCP 其他行为。
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Optional

from fastmcp.tools import Tool, ToolResult

# 允许把「操作参数」以这些键名装进一个对象一并传入（同时兼容扁平写法）
PARAMS_KEY = "params"


class KwargsTool(Tool):
    """把任意额外属性展开为关键字参数的工具。

    `fn` 接受 (name, operation_id, params=None, **extra)，
    两种调用形式最终会被合并成同一份参数字典。
    """

    fn: Callable[..., Any]

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            data = self.fn(**arguments)
            if inspect.isawaitable(data):
                data = await data
        except Exception as e:  # noqa: BLE001 - 工具级错误应作为结果返回而非中断会话
            data = {"error": f"{type(e).__name__}: {e}"}
        if not isinstance(data, dict):
            data = {"result": data}
        return ToolResult(structured_content=data)


def make_kwargs_tool(
    name: str,
    description: str,
    fn: Callable[..., Any],
    required: Optional[list[str]] = None,
    properties: Optional[dict[str, Any]] = None,
) -> KwargsTool:
    """构造一个接受任意额外属性的工具。"""
    schema = {
        "type": "object",
        "properties": properties
        or {
            "name": {"type": "string", "description": "已注册 API 的名称"},
            "operation_id": {"type": "string", "description": "operation 标识"},
            PARAMS_KEY: {
                "type": "object",
                "description": "把路径/查询参数放进一个对象（也可直接作为顶层属性传入）",
                "additionalProperties": True,
            },
        },
        "required": required or ["name", "operation_id"],
        "additionalProperties": True,
    }
    return KwargsTool(name=name, description=description, parameters=schema, fn=fn)


def merge_params(params: Optional[dict], extra: dict) -> dict:
    """把 `params` 对象与顶层扁平参数合并（扁平写法优先，便于覆盖）。"""
    merged: dict[str, Any] = dict(params or {})
    merged.update({k: v for k, v in extra.items() if k != PARAMS_KEY})
    return merged
