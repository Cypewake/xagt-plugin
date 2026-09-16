"""
metering.py · MCPForge 计量与计费层（MONETIZE 阶段的真实落地）

设计目标（针对对抗式复核发现的「MONETIZE 只是打印一个 dict」问题）：
- 每一次经本服务发生的 API 调用都被真实计数并落盘，而不是事后编造数字。
- 用量可查询（usage_report），可折算成账单（simulate_invoice），可用于配额判断。
- 计费模型与价目表集中定义，可配置币种，不把任何加密资产写死为默认。

存储：与注册表同目录的 usage.json，原子写入（临时文件 + os.replace），
     绝不因一次损坏读取就静默清空历史用量。

本模块不依赖 fastmcp，也不依赖 core，可独立单测。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = "2.0"

# 计费档位（每 1000 次调用）。集中定义，便于审计与调整。
PRICING_TIERS: dict[str, dict[str, Any]] = {
    "free": {"price_per_1k_calls": 0.0, "included_calls": 1000, "model": "free"},
    "basic": {"price_per_1k_calls": 2.0, "included_calls": 10000, "model": "pay-per-call"},
    "pro": {"price_per_1k_calls": 8.0, "included_calls": 50000, "model": "pay-per-call"},
    "enterprise": {"price_per_1k_calls": 25.0, "included_calls": 500000, "model": "pay-per-call"},
}

# 默认结算币种：可用环境变量覆盖。刻意不默认任何加密资产，
# 以对齐「本作品仅作工程作品集，不参与代币投机」的合规口径。
DEFAULT_CURRENCY = os.getenv("MCPFORGE_CURRENCY", "USD")


def _default_usage_path() -> Path:
    return Path(os.getenv("MCPFORGE_USAGE", "usage.json"))


class UsageMeter:
    """调用用量计。JSON 落盘，原子写，损坏时保守恢复而非清空。"""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or _default_usage_path())
        self._data: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "apis": {}}
        self._load()

    # ----------------------------- 持久化 ----------------------------- #
    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            # 不静默清空：把损坏文件改名留档，再以空表继续，避免历史被无声抹掉。
            try:
                self.path.replace(self.path.with_suffix(".corrupt.json"))
            except Exception:
                pass
            return
        if isinstance(loaded, dict) and isinstance(loaded.get("apis"), dict):
            self._data = loaded

    def _save(self) -> None:
        """原子写：先写同目录临时文件，再 os.replace 覆盖，避免进程中断留下截断 JSON。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except Exception:
                pass
            raise

    # ----------------------------- 记账 ----------------------------- #
    def record(
        self,
        api_name: str,
        operation_id: str,
        ok: bool,
        status_code: Optional[int] = None,
        latency_ms: Optional[float] = None,
    ) -> None:
        apis = self._data.setdefault("apis", {})
        entry = apis.setdefault(
            api_name,
            {
                "total_calls": 0,
                "ok_calls": 0,
                "failed_calls": 0,
                "operations": {},
                "daily": {},
                "first_seen": datetime.now(timezone.utc).isoformat(),
            },
        )
        entry["total_calls"] += 1
        entry["ok_calls" if ok else "failed_calls"] += 1
        entry["last_seen"] = datetime.now(timezone.utc).isoformat()

        # 按天分桶：支撑「观测速率 → 月度外推」这一真实计费概念
        daily = entry.setdefault("daily", {})
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily[today] = daily.get(today, 0) + 1

        op = entry["operations"].setdefault(
            operation_id, {"calls": 0, "ok": 0, "failed": 0, "latency_ms_total": 0.0}
        )
        op["calls"] += 1
        op["ok" if ok else "failed"] += 1
        if latency_ms is not None:
            op["latency_ms_total"] = round(op["latency_ms_total"] + latency_ms, 1)
        if status_code is not None:
            op["last_status"] = status_code
        self._save()

    # ----------------------------- 查询 ----------------------------- #
    def report(self, api_name: Optional[str] = None, days: Optional[int] = None) -> dict:
        apis = self._data.get("apis", {})
        if api_name:
            if api_name not in apis:
                return {
                    "api": api_name,
                    "found": False,
                    "message": f"暂无 {api_name!r} 的用量记录（注册并通过本服务调用后会开始计数）",
                }
            scoped = {api_name: apis[api_name]}
        else:
            scoped = apis

        since = None
        if days:
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        out_apis = {}
        grand_total = 0
        for name, entry in scoped.items():
            if since and entry.get("last_seen", "") < since:
                continue
            ops = entry.get("operations", {})
            per_op = []
            for op_name, st in sorted(ops.items()):
                calls = st.get("calls", 0)
                avg = round(st.get("latency_ms_total", 0.0) / calls, 1) if calls else None
                per_op.append(
                    {
                        "operation_id": op_name,
                        "calls": calls,
                        "ok": st.get("ok", 0),
                        "failed": st.get("failed", 0),
                        "avg_latency_ms": avg,
                        "success_rate": round(st.get("ok", 0) / calls, 3) if calls else None,
                    }
                )
            total = entry.get("total_calls", 0)
            grand_total += total
            daily = entry.get("daily", {})
            active_days = len(daily) or 1
            per_day = round(total / active_days, 2)
            out_apis[name] = {
                "total_calls": total,
                "ok_calls": entry.get("ok_calls", 0),
                "failed_calls": entry.get("failed_calls", 0),
                "success_rate": round(entry.get("ok_calls", 0) / total, 3) if total else None,
                "first_seen": entry.get("first_seen"),
                "last_seen": entry.get("last_seen"),
                "active_days": active_days,
                "calls_per_day": per_day,
                "projected_monthly_calls": int(round(per_day * 30)),
                "daily": daily,
                "operations": per_op,
            }

        return {
            "found": bool(out_apis),
            "currency_note": f"计费币种：{DEFAULT_CURRENCY}（可用 MCPFORGE_CURRENCY 覆盖）",
            "total_calls_all_apis": grand_total,
            "apis": out_apis,
        }

    # ----------------------------- 计费 ----------------------------- #
    def simulate_invoice(
        self,
        api_name: str,
        pricing_tier: str = "basic",
        basis: str = "actual",
        projected_calls: int = 0,
    ) -> dict:
        """把真实用量折算成账单。

        计费基准（basis）：
          actual            —— 按已记录的真实调用数出账（默认）
          projected_monthly —— 把「观测到的日均调用量」外推到 30 天出账
        也可用 projected_calls 直接指定一个要测算的调用量（用于容量/报价推演）。

        这个「观测速率 → 月度外推」正是真实 SaaS 计费的做法，
        也让账单在演示场景下能给出有意义的数字，而不是永远为 0。
        """
        tier = PRICING_TIERS.get(pricing_tier)
        if tier is None:
            return {
                "error": f"未知计价档 {pricing_tier!r}",
                "available_tiers": sorted(PRICING_TIERS.keys()),
            }
        rep = self.report(api_name)
        if not rep.get("found"):
            return {
                "api": api_name,
                "error": f"暂无 {api_name!r} 的用量记录，无法出账。请先注册并调用后重试。",
            }

        entry = rep["apis"][api_name]
        actual = entry["total_calls"]
        if projected_calls > 0:
            billable = projected_calls
            basis_label = "指定调用量测算"
        elif basis == "projected_monthly":
            billable = entry["projected_monthly_calls"]
            basis_label = "按观测日均外推至 30 天"
        else:
            billable = actual
            basis_label = "实际已记录用量"

        included = tier["included_calls"]
        overage = max(0, billable - included)
        rate = tier["price_per_1k_calls"]
        amount = round(overage / 1000.0 * rate, 4)

        line_items = [
            {
                "operation_id": o["operation_id"],
                "actual_calls": o["calls"],
                "share_of_actual_calls": round(o["calls"] / actual, 3) if actual else 0,
                "projected_calls": int(round(billable * (o["calls"] / actual))) if actual else 0,
            }
            for o in entry["operations"]
        ]

        return {
            "schema_version": SCHEMA_VERSION,
            "api": api_name,
            "pricing_tier": pricing_tier,
            "billing_model": tier["model"],
            "currency": DEFAULT_CURRENCY,
            "billing_basis": basis_label,
            "metered_actual": {
                "total_calls": actual,
                "ok_calls": entry["ok_calls"],
                "failed_calls": entry["failed_calls"],
                "success_rate": entry["success_rate"],
                "active_days": entry["active_days"],
                "calls_per_day": entry["calls_per_day"],
            },
            "billable_calls": billable,
            "included_calls": included,
            "billable_overage_calls": overage,
            "price_per_1k_calls": rate,
            "amount_due": amount,
            "line_items": line_items,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "用量来自本服务真实计量（usage.json），非凭空估值；外推口径已在 billing_basis 标明。",
        }

    def reset(self, api_name: Optional[str] = None) -> dict:
        apis = self._data.setdefault("apis", {})
        if api_name:
            removed = apis.pop(api_name, None) is not None
        else:
            removed = bool(apis)
            apis.clear()
        self._save()
        return {"reset": removed, "api": api_name or "<all>"}


# 模块级单例（与 core 的注册表同生命周期）
_meter = UsageMeter()


def get_meter() -> UsageMeter:
    return _meter
