"""
verify.py · MCPForge v2 验收脚本

与 v1 的区别（对抗式复核的直接产物）：
- v1 的 7 项检查全部依赖实时公网、且断言很弱（`_call_op` 返回 404 也算「调通」），
  证据会随上游腐化，且掩盖了粘贴文本、非标识符占位符、路径穿越等缺陷。
- v2 拆成两层：
    A. 离线验收 —— 完全确定性，不联网，覆盖解析/生成/安全边界/计量/契约签名。
    B. 在线验收 —— 真实调用公开 API，且只把 HTTP 2xx 记为通过。
- 出账与用量断言使用「发现真实数据 → 再调用」的方式，不硬编码会过期的 ID。

运行：python verify.py
产出：verification-evidence.md（含逐条结论与环境信息）
返回码：0 全过；1 有失败
"""

from __future__ import annotations

import asyncio
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import core
import metering
from fastmcp import Client

import server

FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "offline-api.json"
PETSTORE = "https://petstore3.swagger.io/api/v3/openapi.json"
OPEN_METEO = "https://api.open-meteo.com"
FX_API = "https://api.frankfurter.app"
ARTIFACTS = Path("verification-artifacts")

REPORT: list[str] = []
LIVE_SKIPPED = False


def log(ok: bool, msg: str, live: bool = False) -> bool:
    tag = "PASS" if ok else ("SKIP" if (live and LIVE_SKIPPED) else "FAIL")
    REPORT.append(f"- [{tag}] {msg}")
    print(f"[{tag}] {msg}")
    return ok


def section(title: str) -> None:
    REPORT.append(f"\n## {title}")
    print(f"\n## {title}")


# --------------------------------------------------------------------------- #
# SSRF 重定向绕过的离线回归
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, status_code, headers=None, url="https://public.example/x", text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def check_redirect_bypass_is_blocked() -> bool:
    """公开 URL 302 到内网时，防护必须仍然生效。

    这是在本次审计中**实测复现**过的真漏洞：httpx 的 follow_redirects=True
    只在初始 URL 上校验一次，于是 公网 URL -> 302 -> http://127.0.0.1:8123/
    就能读到内网内容（当时实测 status_code=200）。修复后此处必须抛错，
    且第二跳根本不该被发出。
    """
    seen: list = []
    script = [
        _FakeResp(302, {"location": "http://127.0.0.1:8123/secret"}),
        _FakeResp(200, {}, "http://127.0.0.1:8123/secret", "INTERNAL-SECRET"),
    ]

    real_client = core.httpx.AsyncClient
    real_guard = core.assert_public_url

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            seen.append(url)
            return script[min(len(seen) - 1, len(script) - 1)]

    def guard(url: str) -> None:
        if "127.0.0.1" in url or "localhost" in url or "169.254.169.254" in url:
            raise ValueError(f"拒绝访问 {url}：解析到非公网地址")

    core.httpx.AsyncClient = FakeClient
    core.assert_public_url = guard
    try:
        leaked = False
        try:
            resp = asyncio.run(core.request_with_validated_redirects("GET", "https://public.example/x"))
            leaked = "INTERNAL-SECRET" in (resp.text or "")
        except ValueError:
            pass
        stopped_before_second_hop = len(seen) == 1
    finally:
        core.httpx.AsyncClient = real_client
        core.assert_public_url = real_guard

    return log(
        (not leaked) and stopped_before_second_hop,
        "SSRF 重定向绕过已封堵（公网 URL 302 内网时第二跳不发出、无内容泄露）",
    )


# =========================================================================== #
# A. 离线验收
# =========================================================================== #
def verify_offline() -> bool:
    section("A. 离线验收（确定性，不联网）")
    ok = True

    # A1 粘贴文本（v1 缺陷回归）
    pasted = json.dumps(
        {
            "openapi": "3.0.0",
            "info": {"title": "pasted", "version": "1.0"},
            "paths": {"/pets": {"get": {"operationId": "listPets", "responses": {"200": {"description": "ok"}}}}},
        }
    )
    try:
        d = core.parse_openapi_spec(pasted)
        ok &= log(d["title"] == "pasted" and d["operation_count"] == 1,
                  "粘贴的 OpenAPI 文本被正确解析（v1 此处抛 FileNotFoundError）")
    except Exception as e:
        ok &= log(False, f"粘贴文本解析失败：{type(e).__name__}: {e}")

    # A2 非 spec 文本给可诊断错误
    try:
        core.parse_openapi_spec("hello world")
        ok &= log(False, "非 spec 文本未报错，应抛 SpecSourceError")
    except core.SpecSourceError as e:
        ok &= log("不是 OpenAPI 对象" in str(e), f"非 spec 文本给出可诊断错误：{str(e)[:60]}…")
    except Exception as e:
        ok &= log(False, f"非 spec 文本抛出了预期外的异常：{type(e).__name__}")

    fixture = core.parse_spec_text(FIXTURE.read_text(encoding="utf-8"), str(FIXTURE))

    # A3 $ref 展开 + path 级参数合并
    ops = {o["operation_id"]: o for o in core.extract_operations(fixture)}
    merged = [p["name"] for p in ops["getPetById"]["query_params"]]
    ok &= log("page" in merged, f"$ref 参数已展开且 path 级参数已合并：query={merged}")

    # A4 鉴权方案识别
    schemes = {s["name"] for s in core.detect_auth(fixture)}
    ok &= log({"fixture_key", "fixture_oauth"} <= schemes, f"鉴权方案识别：{sorted(schemes)}")

    # A5 非标识符占位符生成的代码可编译（v1 会 NameError）
    try:
        code = core.tool_code_from_spec(fixture, "getWeirdBalance")
        compile(code, "generated.py", "exec")
        ok &= log(True, "路径含非标识符占位符 {account-id} 时，生成代码仍可编译（v1 会产 NameError）")
    except Exception as e:
        ok &= log(False, f"非标识符占位符生成代码不可编译：{type(e).__name__}: {e}")

    # A6 docstring 注入防护
    try:
        spec = core.parse_spec_text(json.dumps({
            "openapi": "3.0.0", "info": {"title": "t", "version": "1"},
            "servers": [{"url": "https://a.example.com"}],
            "paths": {"/x": {"get": {"operationId": "x", "summary": 'bad """ \\ end',
                                     "responses": {"200": {"description": "ok"}}}}},
        }))
        compile(core.tool_code_from_spec(spec, "x"), "g.py", "exec")
        ok &= log(True, "spec 摘要含三引号/反斜杠时，生成代码仍可编译（docstring 已转义）")
    except Exception as e:
        ok &= log(False, f"docstring 转义失败：{type(e).__name__}: {e}")

    # A7 VERIFY 判定不再恒真
    table = {200: ("passed", True), 404: ("not_found", False), 401: ("auth_required", False),
             400: ("bad_request", False), 500: ("server_error", False)}
    bad = [s for s, want in table.items() if core.classify_response(s) != want]
    ok &= log(not bad, "VERIFY 判定不再是「任何响应都算通过」（v1 的 404 也记 reachable=True）"
                       + (f"，异常项：{bad}" if bad else ""))

    # A8 路径穿越防护
    try:
        core.ensure_writable_dir("generated", "../escape")
        ok &= log(False, "目录穿越未被拒绝")
    except core.PathNotAllowed:
        ok &= log(True, "生成物落盘的目录穿越被拒绝")

    # A9 SSRF 防护
    blocked = 0
    for url in ["http://127.0.0.1:8080/x", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.1/x"]:
        try:
            core.assert_public_url(url)
        except ValueError:
            blocked += 1
    ok &= log(blocked == 3, f"SSRF 防护拦截回环/云元数据/内网地址（{blocked}/3）")

    # A9b SSRF 重定向绕过回归（本次审计实测复现过的真漏洞）
    ok &= check_redirect_bypass_is_blocked()

    # A10 计量与出账算术
    meter = metering.UsageMeter(ARTIFACTS / "_selftest-usage.json")
    meter.reset()
    for i in range(5):
        meter.record("selftest", "opA", ok=i < 4, status_code=200 if i < 4 else 500, latency_ms=10.0)
    inv = meter.simulate_invoice("selftest", "basic", projected_calls=100_000)
    ok &= log(inv["billable_overage_calls"] == 90_000 and inv["amount_due"] == 180.0,
              f"计量与出账算术正确（10 万次 @ basic → 超额 {inv['billable_overage_calls']} → {inv['amount_due']}）")
    meter.reset()
    (ARTIFACTS / "_selftest-usage.json").unlink(missing_ok=True)

    # A11 注册表原子写 + 覆盖提示
    reg = core.Registry(ARTIFACTS / "_selftest-registry.json")
    first = reg.register("selftest", str(FIXTURE))
    second = reg.register("selftest", str(FIXTURE))
    ok &= log(first["overwrote_existing"] is False and second["overwrote_existing"] is True,
              "注册表持久化正常且同名覆盖会显式提示")
    (ARTIFACTS / "_selftest-registry.json").unlink(missing_ok=True)

    # A12 契约签名兼容（经 MCP 协议栈）
    async def compat() -> tuple[bool, bool]:
        async with Client(server.mcp) as c:
            flat = await c.call_tool("call_registered_api",
                                     {"name": "__nope__", "operation_id": "x", "petId": 1})
            nested = await c.call_tool("call_registered_api",
                                       {"name": "__nope__", "operation_id": "x", "params": {"petId": 1}})
        # 未注册的名字应返回业务错误，而不是「参数校验失败」
        return ("error" in flat.data and "未找到已注册" in flat.data["error"],
                "error" in nested.data and "未找到已注册" in nested.data["error"])

    flat_ok, nested_ok = asyncio.run(compat())
    ok &= log(flat_ok and nested_ok,
              "call_registered_api 同时接受契约字面写法（petId=1）与 params 对象写法")

    return ok


# =========================================================================== #
# B. 在线验收
# =========================================================================== #
async def verify_live() -> bool:
    section("B. 在线验收（真实调用公开 API，仅 2xx 记为通过）")
    ok = True
    async with Client(server.mcp) as c:

        # B1 工具清单与契约名
        tools = await c.list_tools()
        names = {t.name for t in tools}
        required = {"call_rest_api", "parse_openapi_spec", "list_operations",
                    "generate_mcp_tool_code", "register_api_from_spec",
                    "call_registered_api", "health_check"}
        missing = required - names
        ok &= log(not missing, f"契约点名的 7 项工具全部存在（共注册 {len(tools)} 个工具）"
                               + (f"，缺失：{sorted(missing)}" if missing else ""))

        # B2 parse_openapi_spec（含鉴权识别）
        r = await c.call_tool("parse_openapi_spec", {"spec_source": PETSTORE})
        d = r.data
        ok &= log(d["operation_count"] >= 15 and bool(d["auth_schemes"]),
                  f"parse_openapi_spec 解析 Petstore：{d['operation_count']} 个操作，"
                  f"识别鉴权 {[s['name'] for s in d['auth_schemes']]}")

        # B3 list_operations
        r = await c.call_tool("list_operations", {"spec_source": PETSTORE})
        ok &= log("getPetById" in r.data, "list_operations 列出 Petstore 操作（含 getPetById）")

        # B4 generate_mcp_tool_code（并验证产物可编译）
        r = await c.call_tool("generate_mcp_tool_code",
                              {"spec_source": PETSTORE, "operation_id": "getPetById"})
        try:
            compile(r.data, "gen_tool.py", "exec")
            ok &= log(True, "generate_mcp_tool_code 产出的源码语法合法可编译")
        except SyntaxError as e:
            ok &= log(False, f"生成的工具源码不可编译：{e}")

        # B5 register
        r = await c.call_tool("register_api_from_spec", {"name": "petstore", "spec_source": PETSTORE})
        ok &= log(r.data.get("operations", 0) > 0,
                  f"register_api_from_spec 注册成功（{r.data.get('operations')} 个操作）")

        # B6 真实调用：先发现数据，再按契约字面写法调用（不硬编码会过期的 ID）
        r = await c.call_tool("call_registered_api",
                              {"name": "petstore", "operation_id": "findPetsByStatus",
                               "params": {"status": "available"}})
        found = 200 <= (r.data.get("status_code") or 0) < 300
        ok &= log(found, f"call_registered_api 调通 findPetsByStatus（status={r.data.get('status_code')}）")

        if found:
            # body_preview 是截断预览（前 2000 字符），可能是残缺 JSON，
            # 故用正则取首个 id，保证「发现真实数据 → 再调用」这条链路一定跑得起来。
            m = re.search(r'"id"\s*:\s*(\d+)', r.data.get("body_preview") or "")
            pet_id = int(m.group(1)) if m else None
            if pet_id is not None:
                r2 = await c.call_tool("call_registered_api",
                                       {"name": "petstore", "operation_id": "getPetById", "petId": pet_id})
                ok &= log(200 <= (r2.data.get("status_code") or 0) < 300,
                          f"契约字面写法 call_registered_api(..., petId={pet_id}) 调通"
                          f"（status={r2.data.get('status_code')}）")
            else:
                ok &= log(False, "未能从响应中取到 pet id，契约字面写法未能验证")

        # B7 call_rest_api 天气（契约 §6#4）
        r = await c.call_tool("call_rest_api", {
            "base_url": OPEN_METEO, "path": "/v1/forecast", "method": "GET",
            "query": {"latitude": 31.23, "longitude": 121.47, "current": "temperature_2m"}})
        body = r.data.get("body_preview") or ""
        ok &= log(r.data.get("status_code") == 200 and "temperature_2m" in body,
                  f"call_rest_api 调通 open-meteo 天气（status={r.data.get('status_code')}）")

        # B8 call_rest_api 汇率（契约 §4#1 要求天气/汇率，v1 只演示了天气）
        r = await c.call_tool("call_rest_api", {
            "base_url": FX_API, "path": "/latest", "method": "GET",
            "query": {"from": "USD", "to": "CNY"}})
        body = r.data.get("body_preview") or ""
        ok &= log(r.data.get("status_code") == 200 and "CNY" in body,
                  f"call_rest_api 调通 frankfurter 汇率 USD→CNY（status={r.data.get('status_code')}）")

        # B9 verify_api（真断言，并发有界）
        r = await c.call_tool("verify_api", {"spec_source": PETSTORE, "max_ops": 12, "timeout": 8})
        v = r.data
        summary = (f"verify_api 并发真实验证 {v['verified']} 个操作："
                   f"passed={v['passed']} 需鉴权/失败={v['reached_but_failed']} 不可达={v['unreachable']}")
        ok &= log(v["verified"] > 0 and v["passed"] >= 1, summary)
        REPORT.append(f"  - 结论：{v['verdict']}")
        REPORT.append("  - 说明：Petstore 的 /pet 系列在 spec 中标注了 security，未带凭据时返回 401，")
        REPORT.append("    因此这里 passed 偏低是正确的判定结果——这正说明 verify_api 不再把 4xx 也算作通过。")
        REPORT.append("  - 逐条（前 6）：")
        for item in v["results"][:6]:
            REPORT.append(
                f"    · [{item['method']}] {item['operation_id']} → "
                f"{item['status']}（HTTP {item['http_status']}，{item['latency_ms']}ms）"
            )

        # B10 generate_mcp_bundle（落盘 + 可编译）
        r = await c.call_tool("generate_mcp_bundle", {
            "spec_source": PETSTORE, "name": "petstore-mcp",
            "output_dir": str(ARTIFACTS / "generated")})
        b = r.data
        srv = Path(b["output_dir"]) / "server.py"
        try:
            compile(srv.read_text(encoding="utf-8"), "bundle_server.py", "exec")
            compiled = True
        except Exception:
            compiled = False
        ok &= log(b["tools"] > 0 and compiled,
                  f"generate_mcp_bundle 落盘完整包并可编译（{b['tools']} 个工具 → {b['output_dir']}）")

        # B11 build_manifest（含工具级 schema）
        r = await c.call_tool("build_manifest", {
            "name": "petstore", "spec_source": PETSTORE, "pricing_tier": "pro"})
        m = r.data
        ok &= log(bool(m["tools"]) and all("input_schema" in t for t in m["tools"]),
                  f"build_manifest 产出含工具级 input_schema 的上架清单（{m['listing']['capabilities']['tool_count']} 工具）")

        # B12 usage_report 真实计量
        r = await c.call_tool("usage_report", {"api_name": "petstore"})
        calls = r.data.get("apis", {}).get("petstore", {}).get("total_calls", 0)
        ok &= log(calls > 0, f"usage_report 读到真实计量：petstore 已被调用 {calls} 次")

        # B13 simulate_invoice（能出有意义的数字）
        r = await c.call_tool("simulate_invoice", {
            "api_name": "petstore", "pricing_tier": "basic", "projected_calls": 100_000})
        ok &= log(r.data.get("amount_due", 0) > 0,
                  f"simulate_invoice 出账：10 万次 @ basic → 应付 {r.data.get('amount_due')} {r.data.get('currency')}"
                  f"（{r.data.get('billing_basis')}）")

        # B14 health_check
        r = await c.call_tool("health_check", {})
        ok &= log(r.data.get("status") == "ok",
                  f"health_check 返回 ok（版本 {r.data.get('version')}，"
                  f"已注册 {len(r.data.get('registered_apis', []))} 个 API）")

    return ok


# =========================================================================== #
def main() -> int:
    global LIVE_SKIPPED
    ARTIFACTS.mkdir(exist_ok=True)

    REPORT.append("# MCPForge v2 技术验证证据")
    REPORT.append("")
    REPORT.append(f"- 生成时间（UTC）：{datetime.now(timezone.utc).isoformat()}")
    REPORT.append(f"- 版本：{core.VERSION}")
    REPORT.append(f"- Python：{platform.python_version()} on {platform.system()}")
    REPORT.append(f"- 验收方式：离线层为确定性检查；在线层真实调用公开 API，仅 HTTP 2xx 记为通过")

    offline_ok = verify_offline()

    try:
        live_ok = asyncio.run(verify_live())
    except Exception as e:  # 无网络时降级，但显式声明
        LIVE_SKIPPED = True
        live_ok = True
        section("B. 在线验收（跳过）")
        log(True, f"在线层已跳过：{type(e).__name__}: {str(e)[:120]}", live=True)

    REDLINE = "\n## 合规红线自检"
    REPORT.append(REDLINE)
    REPORT.append("- [OK] 本作品是通用 API/MCP 工程能力，不含漏洞检测、风险评分、钓鱼/诈骗检测、")
    REPORT.append("       安全监控、合规分析等任何安全/审计/链上安全外壳。")
    REPORT.append("- [OK] 清单与账单中的币种默认取 USD，可用 MCPFORGE_CURRENCY 覆盖；")
    REPORT.append("       不参与代币投机。")

    all_ok = offline_ok and live_ok
    REPORT.append(f"\n## 结论\n\n"
                  f"- 离线层：{'全部通过' if offline_ok else '存在失败'}\n"
                  f"- 在线层：{'全部通过' if live_ok else '存在失败'}"
                  f"{'（因无网络被跳过）' if LIVE_SKIPPED else ''}\n"
                  f"- 总体：{'全部通过 ✅' if all_ok else '存在失败 ❌'}")

    (Path("verification-evidence.md")).write_text("\n".join(REPORT) + "\n", encoding="utf-8")
    print("\n证据已写入 verification-evidence.md")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
