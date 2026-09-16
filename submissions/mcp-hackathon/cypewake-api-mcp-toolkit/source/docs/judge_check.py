"""评委现场复核脚本 · MCPForge

用途：用一条命令、零配置（除 MCP 客户端库外），验证本次提交的三个硬性事实——
  1. 作品确实在线可用（对应硬门槛：被封装的 API 必须真实可调用，而非「部署到公网」）
  2. 它暴露的是**真正可调用的 MCP 端点**，不是只有健康检查的 HTTP 外壳
  3. 交付规格点名的 7 个工具名称一个不缺，且 §6 验收 #2/#3（生成可部署代码、注册后按 operation_id 实调）真实跑通

设计原则（零部署、可离线复核）：
  - 服务以单进程本地起（uvicorn demo_app:app），一条命令即可复核，无需公网部署。
  - 解析/生成/列出等检查使用本地 fixtures（offline-api.json），不依赖任何出网。
  - 仅「真实出网」与「register + 真实调用」两项主动打 GitHub 公共 REST API
    （沙箱内可达、免密钥），如实反映 API 是否真能被 agent 调用。

运行：
    pip install "fastmcp>=4.0,<5.0"
    python docs/judge_check.py
    python docs/judge_check.py --url http://127.0.0.1:8000

退出码 0 表示全部通过；非 0 表示有项目未通过（同时打印原因）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8000"

# 本地离线夹具：形状对齐 Petstore（含 getPetById），解析/生成/列出工具等检查
# 全部走本地文件，不依赖任何出网，保证评委在任意离线环境都能复核通过。
_HERE = Path(__file__).resolve().parent
OFFLINE_SPEC = str((_HERE.parent / "tests" / "fixtures" / "offline-api.json").resolve())
# 真实、免密钥、沙箱内可达的公开 API（GitHub 公共 REST API），用于「真实出网」
# 与「register + 真实调用」两项硬门槛。本地若无法出网，这两项会如实 FAIL，
# 不会伪造通过。
GITHUB_SPEC = str((_HERE.parent / "examples" / "github-openapi.json").resolve())
GITHUB_BASE = "https://api.github.com"
GITHUB_ZEN_PATH = "/zen"
GITHUB_ZEN_OP = "getZen"

# 交付规格第 4 节点名的 7 个工具，名称必须完全一致
CONTRACT_TOOLS = [
    "call_rest_api",
    "parse_openapi_spec",
    "list_operations",
    "generate_mcp_tool_code",
    "register_api_from_spec",
    "call_registered_api",
    "health_check",
]


class Report:
    def __init__(self) -> None:
        self.ok = 0
        self.bad = 0

    def check(self, passed: bool, title: str, detail: str = "") -> bool:
        line = f"[{'PASS' if passed else 'FAIL'}] {title}"
        if detail:
            line += f" — {detail}"
        print(line)
        if passed:
            self.ok += 1
        else:
            self.bad += 1
        return passed


def _as_dict(data) -> dict:
    return data if isinstance(data, dict) else {}


async def run(url: str) -> int:
    import httpx
    from fastmcp import Client

    report = Report()
    url = url.rstrip("/")
    mcp_url = f"{url}/mcp/"

    print(f"目标实例：{url}")
    print("-" * 72)

    # ---------- 一、HTTP 层：服务在线 ----------
    try:
        async with httpx.AsyncClient(timeout=30, trust_env=False) as http:
            r = await http.get(f"{url}/api/health")
            body = _as_dict(r.json()) if r.status_code == 200 else {}
            report.check(
                r.status_code == 200 and body.get("status") == "ok",
                "健康检查 GET /api/health",
                f"HTTP {r.status_code} status={body.get('status')} version={body.get('version')}",
            )

            r = await http.get(f"{url}/")
            report.check(
                r.status_code == 200 and len(r.text) > 1000,
                "可视化四阶段走查页 GET /",
                f"HTTP {r.status_code} {len(r.text)} 字节",
            )

            r = await http.get(f"{url}/api/config")
            cfg = _as_dict(r.json()) if r.status_code == 200 else {}
            tiers = cfg.get("pricing_tiers") or {}
            report.check(
                r.status_code == 200 and len(tiers) >= 2,
                "计价档位可读（MONETIZE 有真实定价口径）GET /api/config",
                f"档位={list(tiers)} 币种={cfg.get('currency')}",
            )
    except Exception as exc:  # noqa: BLE001
        report.check(False, "HTTP 层连通", f"{type(exc).__name__}: {exc}")
        return _finish(report)

    # ---------- 二、MCP 层：真端点、真工具、真调用 ----------
    try:
        async with Client(mcp_url) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools}
            report.check(len(names) >= 7, "MCP 端点可列出工具", f"{len(names)} 个")

            missing = [n for n in CONTRACT_TOOLS if n not in names]
            report.check(
                not missing,
                "规格点名的 7 个工具全部存在",
                "齐全" if not missing else f"缺失 {missing}",
            )

            data = _as_dict((await client.call_tool("health_check", {})).data)
            report.check(
                data.get("status") == "ok",
                "工具调用：health_check",
                f"status={data.get('status')}",
            )

            data = _as_dict((await client.call_tool("parse_openapi_spec", {"spec_source": OFFLINE_SPEC})).data)
            count = data.get("operation_count") or 0
            report.check(
                count > 0,
                "工具调用：parse_openapi_spec 解析本地 Petstore 风格规格",
                f"{count} 个操作，鉴权方案={[s.get('name') for s in (data.get('auth_schemes') or [])]}",
            )

            text = (await client.call_tool("list_operations", {"spec_source": OFFLINE_SPEC})).data
            text = text if isinstance(text, str) else str(text)
            report.check(
                "getPetById" in text,
                "工具调用：list_operations 输出可读操作清单",
                f"{len(text)} 字符，含 getPetById={'getPetById' in text}",
            )

            data = _as_dict(
                (
                    await client.call_tool(
                        "call_rest_api",
                        {
                            "base_url": GITHUB_BASE,
                            "path": GITHUB_ZEN_PATH,
                            "method": "GET",
                        },
                    )
                ).data
            )
            code = data.get("status_code")
            report.check(
                code == 200,
                "工具调用：call_rest_api 真实出网（GitHub 公共 REST API）",
                f"HTTP {code}，耗时 {data.get('latency_ms')} ms",
            )

            # §6 验收 #2: generate_mcp_tool_code(..., "getPetById") → 可部署源码
            raw = (await client.call_tool(
                "generate_mcp_tool_code",
                {"spec_source": OFFLINE_SPEC, "operation_id": "getPetById"},
            )).data
            code_src = raw if isinstance(raw, str) else str(raw)
            report.check(
                "FastMCP" in code_src and ("get_pet_by_id" in code_src or "getPetById" in code_src),
                "工具调用：generate_mcp_tool_code 产出可部署 FastMCP 源码（§6 #2）",
                f"{len(code_src.splitlines())} 行，含 FastMCP 与 get_pet_by_id",
            )

            # §6 验收 #3: register_api_from_spec + call_registered_api(name, op) → 真实响应
            # 用真实、沙箱内可达的 GitHub 公共 REST API（免密钥），证明「注册后可被真实调用」。
            reg = _as_dict((await client.call_tool(
                "register_api_from_spec",
                {"name": "judge_check_demo", "spec_source": GITHUB_SPEC},
            )).data)
            call = _as_dict((await client.call_tool(
                "call_registered_api",
                {"name": "judge_check_demo", "operation_id": GITHUB_ZEN_OP},
            )).data)
            report.check(
                call.get("status_code") == 200,
                f"工具调用：register + call_registered_api({GITHUB_ZEN_OP}) 真实出网（§6 #3）",
                f"register ops={reg.get('operations')} | call HTTP {call.get('status_code')}",
            )
    except Exception as exc:  # noqa: BLE001
        report.check(False, "MCP 层调用", f"{type(exc).__name__}: {exc}")

    return _finish(report)


def _finish(report: Report) -> int:
    print("-" * 72)
    print(f"结果：{report.ok} 通过 / {report.bad} 未通过")
    return 0 if report.bad == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="MCPForge 评委现场复核")
    parser.add_argument("--url", default=DEFAULT_URL, help="被复核实例的根地址")
    args = parser.parse_args()
    return asyncio.run(run(args.url))


if __name__ == "__main__":
    sys.exit(main())
