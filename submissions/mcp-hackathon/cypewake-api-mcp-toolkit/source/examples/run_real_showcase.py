"""
run_real_showcase.py · 用「真实、有用、agent 会调用」的 API 跑通 MCPForge 全链路，
产出可复核的端到端证据（真实 2xx 校验 + 真实用量计量 + 真实出账）。

不部署、不联网提交。仅本地离线运行，调用公网真实接口做 Verify 与 Metering。
用法：NO_PROXY=* .venv/Scripts/python.exe examples/run_real_showcase.py
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import metering  # noqa: E402

SPEC = str(HERE / "github-openapi.json")
OUT = HERE / "real_showcase_result.json"
API_NAME = "github_live"


async def main() -> None:
    result: dict = {}

    # 1) VERIFY —— 真实调用公网接口，只把 2xx 记为 passed
    verify = await core.verify_api_async(SPEC, max_ops=20)
    result["verify"] = {
        "base_url": verify["base_url"],
        "total_operations": verify["total_operations"],
        "filtered_operations": verify["filtered_operations"],
        "passed": verify["passed"],
        "verified": verify["verified"],
        "verdict": verify["verdict"],
        "detail": [
            {
                "operation_id": r["operation_id"],
                "http_status": r["http_status"],
                "passed": r["passed"],
                "status": r["status"],
                "latency_ms": r["latency_ms"],
            }
            for r in verify["results"]
        ],
    }

    # 2) BUILD / REGISTER —— 把 spec 注册进本地注册表（持久化）
    reg = await core._registry.register_async(API_NAME, SPEC)
    result["register"] = {"name": API_NAME, "ops": reg.get("operations")}

    # 3) 真实调用若干次 —— 产生可核对的真实用量计量（MONETIZE 的原材料）
    calls = []
    for op_id in ["getZen", "getRateLimit", "listPublicEvents"]:
        for _ in range(2):
            r = await core._registry.call_async(API_NAME, op_id, {})
            calls.append(
                {
                    "operation_id": op_id,
                    "ok": r.get("ok"),
                    "status_code": r.get("status_code"),
                    "metered": r.get("metered", False),
                }
            )
    result["calls"] = calls

    # 4) MONETIZE —— 真实用量报告 + 计价档出账
    report = metering.get_meter().report(API_NAME)
    result["usage_report"] = report
    invoice = metering.get_meter().simulate_invoice(API_NAME, pricing_tier="pro", basis="actual")
    result["invoice"] = invoice

    # 5) BUILD manifest —— 市场格式上架清单（带计价档 + 真实 usage 映射）
    manifest = await core.build_manifest_async(
        API_NAME,
        source=SPEC,
        category="api-tool",
        pricing_tier="pro",
        description="CoinGecko 公共行情，真实可调用、按次计费就绪。",
        currency="USD",
    )
    result["manifest"] = {
        "name": manifest.get("listing", {}).get("name"),
        "pricing_tier": manifest.get("pricing", {}).get("tier"),
        "currency": manifest.get("pricing", {}).get("currency"),
        "tool_count": len(manifest.get("tools", [])),
        "billing_model": manifest.get("pricing", {}).get("billing_model"),
    }

    # 6) 走查页验证口径：健康检查
    result["health"] = core.health_check()

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[OK] 证据写入 {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
