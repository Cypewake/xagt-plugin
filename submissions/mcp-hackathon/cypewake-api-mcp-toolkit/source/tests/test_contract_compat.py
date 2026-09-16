"""
test_contract_compat.py · 契约签名兼容性与工具清单测试

背景：交付规格第 6 项要求 call_registered_api(name, operation_id, **params)，
而 FastMCP 4.0.3 原生拒绝 VAR_KEYWORD 签名。本文件既锁住绕行方案有效，
也用一条用例把这个框架限制本身记录在案，避免后来者重新踩坑。
"""

from __future__ import annotations

import asyncio
import inspect

import pytest
from fastmcp import Client, FastMCP

import server
from fastmcp_kwargs import PARAMS_KEY, make_kwargs_tool, merge_params

# 契约 §4 点名的 7 项工具，名字必须完全一致
CONTRACT_REQUIRED_TOOLS = {
    "call_rest_api",
    "parse_openapi_spec",
    "list_operations",
    "generate_mcp_tool_code",
    "register_api_from_spec",
    "call_registered_api",
    "health_check",
}


def _tool_names() -> list[str]:
    async def run() -> list[str]:
        async with Client(server.mcp) as c:
            return [t.name for t in await c.list_tools()]

    return asyncio.run(run())


def test_all_contract_required_tools_exist():
    names = set(_tool_names())
    missing = CONTRACT_REQUIRED_TOOLS - names
    assert not missing, f"契约要求的工具缺失：{sorted(missing)}"


def test_fastmcp_natively_rejects_kwargs_tools():
    """把这个框架限制固化为可执行的事实，说明绕行为何必要。"""
    probe = FastMCP("probe")

    with pytest.raises(ValueError, match=r"\*\*kwargs"):

        @probe.tool()
        async def bad(name: str, **params):  # pragma: no cover - 仅用于触发限制
            return {}


def test_kwargs_tool_accepts_flat_and_nested_params():
    """契约字面写法（扁平）与等价写法（params 对象）必须都走通。"""
    captured: dict = {}

    async def impl(name: str, operation_id: str, params=None, **extra) -> dict:
        captured.clear()
        captured.update({"name": name, "operation_id": operation_id, "merged": merge_params(params, extra)})
        return dict(captured)

    mcp = FastMCP("compat")
    mcp.add_tool(
        make_kwargs_tool(
            name="call_registered_api",
            description="test double",
            fn=impl,
        )
    )

    async def run() -> tuple[dict, dict, dict]:
        async with Client(mcp) as c:
            tools = await c.list_tools()
            flat = await c.call_tool(
                "call_registered_api", {"name": "petstore", "operation_id": "getPetById", "petId": 1}
            )
            nested = await c.call_tool(
                "call_registered_api",
                {"name": "petstore", "operation_id": "getPetById", PARAMS_KEY: {"petId": 2}},
            )
            return tools[0].input_schema, flat.data, nested.data

    schema, flat, nested = asyncio.run(run())

    assert schema["additionalProperties"] is True, "必须允许额外属性，否则契约签名的语义无法表达"
    assert flat["merged"] == {"petId": 1}, "扁平写法（契约字面）未生效"
    assert nested["merged"] == {"petId": 2}, "params 对象写法未生效"


def test_flat_params_override_nested():
    assert merge_params({"petId": 1, "x": 1}, {"petId": 9}) == {"petId": 9, "x": 1}


def test_kwargs_tool_surfaces_errors_as_result_not_crash():
    async def boom(**kwargs):
        raise RuntimeError("nope")

    mcp = FastMCP("compat-err")
    mcp.add_tool(make_kwargs_tool("boom", "d", boom, required=[]))

    async def run() -> dict:
        async with Client(mcp) as c:
            return (await c.call_tool("boom", {})).data

    assert "RuntimeError" in asyncio.run(run())["error"]


def test_health_check_shape():
    health = server.core.health_check()
    assert health["status"] == "ok"
    assert "version" in health and "registered_apis" in health


def test_server_tools_are_async():
    """所有常规工具必须是协程，避免同步 IO 阻塞事件循环（v1 的缺陷）。"""
    for name in ("verify_api", "call_rest_api", "parse_openapi_spec", "generate_mcp_bundle"):
        fn = getattr(server, name)
        assert inspect.iscoroutinefunction(fn), f"{name} 不是协程函数"
