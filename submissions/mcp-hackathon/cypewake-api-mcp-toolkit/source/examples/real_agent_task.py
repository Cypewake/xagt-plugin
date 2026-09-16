"""
real_agent_task.py · 用 MCPForge 生成的工具完成一个「真实任务」

任务：技术选型简报 —— 找出 GitHub 上最受欢迎的 MCP 相关项目，并核实它们的
实时指标（star / fork / open issues / 主语言 / 最近更新），输出可决策的简报。

为什么这是「真实任务」而不是 prompt demo：
  1. 结论依赖实时数据。star 数、issue 数、最近更新时间每天都在变，
     LLM 凭训练记忆给不出真实数值，必须调用工具。
  2. 需要多步工具调用：检索候选 → 逐个核实 → 聚合排序 → 生成简报。
     单步探针做不成这件事，正好体现「工具能被 agent 真正编排」。
  3. 每一步都是真实 HTTP，可复核：记录 status_code / latency / 用量 / 计费。

用法：NO_PROXY=* .venv/Scripts/python.exe examples/real_agent_task.py
产出：examples/real_agent_task_result.json（可复核证据）
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core  # noqa: E402
import metering  # noqa: E402

SPEC = str(HERE / "github-openapi.json")
OUT = HERE / "real_agent_task_result.json"
API_NAME = "github_live"
TOPIC = "model-context-protocol"
TOP_N = 3


def _brief_item(repo: dict) -> dict:
    """从仓库详情中抽取决策所需字段，避免把整包响应塞给模型。"""
    return {
        "full_name": repo.get("full_name"),
        "stars": repo.get("stargazers_count"),
        "forks": repo.get("forks_count"),
        "open_issues": repo.get("open_issues_count"),
        "language": repo.get("language"),
        "pushed_at": repo.get("pushed_at"),
        "description": (repo.get("description") or "")[:120],
    }


async def main() -> None:
    result: dict = {"task": f"生成「{TOPIC}」技术选型简报", "topic": TOPIC}

    # 1) VERIFY —— 真实调用，只有 2xx 记 passed
    verify = await core.verify_api_async(SPEC, max_ops=20)
    result["verify"] = {
        "total_operations": verify["total_operations"],
        "filtered_operations": verify["filtered_operations"],
        "passed": verify["passed"],
        "verified": verify["verified"],
        "verdict": verify["verdict"],
        "detail": [
            {"operation_id": r["operation_id"], "http_status": r["http_status"],
             "passed": r["passed"], "latency_ms": r["latency_ms"]}
            for r in verify["results"]
        ],
    }

    # 2) REGISTER —— 注册进注册表，得到可编排的工具
    await core._registry.register_async(API_NAME, SPEC)

    # 3) 步骤一：检索候选
    search = await core._registry.call_async(
        API_NAME, "searchRepositories",
        {"q": TOPIC, "sort": "stars", "order": "desc", "per_page": 5},
    )
    items = (search.get("data") or {}).get("items") or []
    candidates = [
        {"full_name": it.get("full_name"), "stars_at_search": it.get("stargazers_count")}
        for it in items[:TOP_N]
    ]
    result["step1_search"] = {
        "status_code": search.get("status_code"),
        "ok": search.get("ok"),
        "returned": len(items),
        "data_truncated": search.get("data_truncated"),
        "candidates": candidates,
    }

    # 4) 步骤二：逐个核实实时指标（搜索摘要可能过期，必须回源核实）
    verified_repos = []
    for c in candidates:
        fn = c.get("full_name") or ""
        if "/" not in fn:
            continue
        owner, repo = fn.split("/", 1)
        r = await core._registry.call_async(
            API_NAME, "getRepository", {"owner": owner, "repo": repo}
        )
        data = r.get("data") or {}
        verified_repos.append({
            "status_code": r.get("status_code"),
            "ok": r.get("ok"),
            **_brief_item(data),
        })
    verified_repos.sort(key=lambda x: (x.get("stars") or 0), reverse=True)
    result["step2_verify_details"] = verified_repos

    # 5) 步骤三：聚合生成简报
    result["brief"] = {
        "generated_from": "GitHub 实时 API（非模型记忆）",
        "top_pick": (verified_repos[0]["full_name"] if verified_repos else None),
        "ranking": [
            {"rank": i + 1, **v} for i, v in enumerate(verified_repos)
        ],
    }

    # 6) MONETIZE —— 真实用量与出账
    report = metering.get_meter().report(API_NAME)
    api_usage = (report.get("apis") or {}).get(API_NAME) or {}
    result["usage_report"] = report
    # 实际口径：真实发生了多少次调用、按档如何计价
    result["invoice_actual"] = metering.get_meter().simulate_invoice(
        API_NAME, pricing_tier="pro", basis="actual"
    )
    # 规模化口径：演示用量远低于免费额度，实际账单必然是 0；
    # 只给这一张会让人误以为「变现没跑通」，故按 100 万次/月推演收入模型。
    result["invoice_scaled"] = metering.get_meter().simulate_invoice(
        API_NAME, pricing_tier="pro", projected_calls=1_000_000
    )

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[任务] {result['task']}")
    print(f"[VERIFY] {verify['passed']}/{verify['filtered_operations']} passed -> {verify['verdict']}")
    for v in verified_repos:
        print(f"  - {v['full_name']}: ★{v['stars']} forks={v['forks']} "
              f"issues={v['open_issues']} lang={v['language']}")
    act = result["invoice_actual"]
    scaled = result["invoice_scaled"]
    print(f"[计费] 实际 {api_usage.get('total_calls')} 次 -> {act.get('amount_due')} "
          f"{act.get('currency')}（免费额度 {act.get('included_calls')} 次未用尽）")
    print(f"[计费] 规模化 100 万次/月 -> {scaled.get('amount_due')} {scaled.get('currency')}")
    print(f"[OK] 证据写入 {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
