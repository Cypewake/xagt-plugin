"""
test_core.py · 离线单元测试（不依赖公网）

这些用例存在的意义是对抗式复核的直接产物：v1 的「7/7 全过」依赖实时公网、
且完全没有覆盖粘贴文本、非标识符占位符、路径穿越、SSRF 等分支，
导致缺陷被绿灯掩盖。此处全部改为离线可复现。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import core
import metering

FIXTURE = Path(__file__).parent / "fixtures" / "offline-api.json"


def asyncio_run(coro):
    """同步跑协程。测试本身是同步用例，避免引入事件循环夹具的隐式行为。"""
    return asyncio.run(coro)


@pytest.fixture()
def fixture_spec() -> dict:
    return core.parse_spec_text(FIXTURE.read_text(encoding="utf-8"), str(FIXTURE))


# ----------------------------- BUILD --------------------------------------- #
def test_paste_json_text_is_accepted():
    """回归 v1 缺陷：粘贴的 OpenAPI 文本曾被 _looks_like_path 误判为文件路径。"""
    pasted = json.dumps(
        {
            "openapi": "3.0.0",
            "info": {"title": "pasted", "version": "1.0"},
            "paths": {"/pets": {"get": {"operationId": "listPets", "responses": {"200": {"description": "ok"}}}}},
        }
    )
    overview = core.parse_openapi_spec(pasted)
    assert overview["title"] == "pasted"
    assert overview["operation_count"] == 1


def test_paste_yaml_text_is_accepted():
    yaml_text = (
        "openapi: 3.0.0\n"
        "info:\n  title: pasted-yaml\n  version: '1.0'\n"
        "paths:\n  /pets:\n    get:\n      operationId: listPets\n"
    )
    assert core.parse_openapi_spec(yaml_text)["title"] == "pasted-yaml"


def test_non_spec_text_gives_diagnostic_error():
    with pytest.raises(core.SpecSourceError) as ei:
        core.parse_openapi_spec("hello world")
    assert "不是 OpenAPI 对象" in str(ei.value)


def test_nonexistent_file_path_reports_file_error():
    with pytest.raises(FileNotFoundError):
        core.parse_openapi_spec("./definitely-not-here-12345.json")


def test_ref_and_path_level_parameters_are_merged(fixture_spec):
    """$ref 参数应被展开，且 path 级 parameters 应与 operation 级合并。"""
    ops = {o["operation_id"]: o for o in core.extract_operations(fixture_spec)}
    get_pet = ops["getPetById"]
    names = [p["name"] for p in get_pet["query_params"]]
    assert "page" in names, "path 级 $ref 参数未被合并"
    assert [p["name"] for p in get_pet["path_params"]] == ["petId"]


def test_auth_and_pagination_detected(fixture_spec):
    schemes = {s["name"] for s in core.detect_auth(fixture_spec)}
    assert {"fixture_key", "fixture_oauth"} <= schemes
    ops = {o["operation_id"]: o for o in core.extract_operations(fixture_spec)}
    assert ops["getPetById"]["paginated"] is True
    assert ops["deletePet"]["security"], "operation 级 security 未被保留"


def test_relative_base_url_is_completed_with_origin():
    spec = core.parse_spec_text(
        json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "t", "version": "1"},
                "servers": [{"url": "/api/v3"}],
                "paths": {"/x": {"get": {"operationId": "x"}}},
            }
        )
    )
    assert core.resolve_base_url(spec, "https://host.example.com/openapi.json") == "https://host.example.com/api/v3"


def test_relative_base_url_without_leading_slash_gets_separator():
    """回归 v1 缺陷：servers.url='v3' 曾被拼成 https://hostv3。"""
    spec = {"servers": [{"url": "v3"}]}
    assert core.resolve_base_url(spec, "https://host.example.com/spec.json") == "https://host.example.com/v3"


# ----------------------------- MCPize -------------------------------------- #
def test_weird_placeholder_codegen_compiles(fixture_spec):
    """回归 v1 缺陷：{account-id} 曾被原样塞进 f-string，生成文件 NameError。"""
    code = core.tool_code_from_spec(fixture_spec, "getWeirdBalance")
    assert "f\"" not in code.split("_PATH_")[0]
    compile(code, "generated.py", "exec")


def test_docstring_injection_is_escaped():
    spec = core.parse_spec_text(
        json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "t", "version": "1"},
                "servers": [{"url": "https://a.example.com"}],
                "paths": {
                    "/x": {
                        "get": {
                            "operationId": "x",
                            "summary": 'bad """ triple \\ backslash',
                            "responses": {"200": {"description": "ok"}},
                        }
                    }
                },
            }
        )
    )
    code = core.tool_code_from_spec(spec, "x")
    compile(code, "generated.py", "exec")


def test_generated_tool_names_are_unique(fixture_spec):
    ops = core.extract_operations(fixture_spec)
    names = core._dedupe([core._py_ident(o["operation_id"]) for o in ops])
    assert len(names) == len(set(names))


def test_bundle_lands_on_disk(tmp_path, fixture_spec, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = core.bundle_from_spec(fixture_spec, "offline-mcp")
    files = {Path(f).name for f in result["files"]}
    assert {"server.py", "requirements.txt", "README.md", "manifest.json"} <= files
    compile((tmp_path / "generated" / "offline-mcp" / "server.py").read_text(encoding="utf-8"), "s.py", "exec")


def test_manifest_has_tool_schemas_and_pricing(fixture_spec):
    manifest = core.manifest_from_spec(fixture_spec, "offline", pricing_tier="pro")
    assert manifest["listing"]["capabilities"]["tool_count"] > 0
    assert manifest["pricing"]["tier"] == "pro"
    assert manifest["pricing"]["currency"] == metering.DEFAULT_CURRENCY
    assert all("input_schema" in t for t in manifest["tools"])
    assert manifest["listing"]["auth"]["required"] is True


# ----------------------------- 安全边界 ------------------------------------ #
@pytest.mark.parametrize("name", ["../escape", "a/b", "", ".", "x" * 65])
def test_output_name_whitelist_rejects_unsafe(name, tmp_path):
    with pytest.raises(core.PathNotAllowed):
        core.ensure_writable_dir(str(tmp_path), name)


def test_output_dir_traversal_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "generated"
    root.mkdir()
    assert core.ensure_writable_dir("generated", "ok-name") == root / "ok-name"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/x",
        "http://localhost/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/internal",
        "ftp://example.com/x",
    ],
)
def test_ssrf_guard_blocks_non_public_targets(url):
    with pytest.raises(ValueError):
        core.assert_public_url(url)


# --------- SSRF 重定向绕过回归（实测复现过的真漏洞，必须锁死） --------------- #
class _FakeResp:
    def __init__(self, status_code, headers=None, url="https://public.example/x", text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _patch_httpx(monkeypatch, script, seen):
    """把 httpx.AsyncClient 换成按脚本逐次应答的假客户端。"""

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            seen.append((method, url))
            return script[min(len(seen) - 1, len(script) - 1)]

    monkeypatch.setattr(core.httpx, "AsyncClient", FakeClient)


def _patch_guard(monkeypatch):
    """只判断公网的轻量守卫：真实守卫的地址判定已由上方的参数化用例覆盖。"""

    def guard(url: str) -> None:
        if "127.0.0.1" in url or "localhost" in url or "169.254.169.254" in url:
            raise ValueError(f"拒绝访问 {url}：解析到非公网地址")

    monkeypatch.setattr(core, "assert_public_url", guard)


def test_redirect_to_internal_target_is_blocked(monkeypatch):
    """回归真漏洞：公开 URL 302 到 127.0.0.1 时，防护曾整体失效。

    httpx 的 follow_redirects=True 只在初始 URL 上校验一次，
    因此一个公网地址只要 302 到内网/云元数据端点就能绕过 SSRF 防护。
    本用例断言：第二跳被拦下，且内网请求根本没发出去。
    """
    seen: list = []
    _patch_guard(monkeypatch)
    _patch_httpx(
        monkeypatch,
        [
            _FakeResp(302, {"location": "http://127.0.0.1:8123/secret"}),
            _FakeResp(200, {}, "http://127.0.0.1:8123/secret", "INTERNAL-SECRET"),
        ],
        seen,
    )

    with pytest.raises(ValueError) as ei:
        asyncio_run(core.request_with_validated_redirects("GET", "https://public.example/x"))

    assert "127.0.0.1" in str(ei.value)
    assert seen == [("GET", "https://public.example/x")], "第二跳不应被真正请求"


def test_redirect_to_metadata_endpoint_is_blocked(monkeypatch):
    """同一类漏洞的云元数据变体：302 -> 169.254.169.254 必须被拦。"""
    seen: list = []
    _patch_guard(monkeypatch)
    _patch_httpx(
        monkeypatch,
        [
            _FakeResp(302, {"location": "http://169.254.169.254/latest/meta-data/"}),
            _FakeResp(200, {}, "http://169.254.169.254/latest/meta-data/", "SECRET"),
        ],
        seen,
    )

    with pytest.raises(ValueError):
        asyncio_run(core.request_with_validated_redirects("GET", "https://public.example/x"))
    assert len(seen) == 1


def test_redirect_chain_is_followed_and_rewritten_semantics(monkeypatch):
    """正常场景不能被误伤：公网 -> 公网跳转应正常跟随，303 改写为 GET。"""
    seen: list = []
    _patch_guard(monkeypatch)
    _patch_httpx(
        monkeypatch,
        [
            _FakeResp(303, {"location": "https://cdn.example/final"}),
            _FakeResp(200, {}, "https://cdn.example/final", "ok"),
        ],
        seen,
    )

    resp = asyncio_run(core.request_with_validated_redirects("POST", "https://public.example/x"))
    assert resp.status_code == 200
    assert seen == [("POST", "https://public.example/x"), ("GET", "https://cdn.example/final")]


def test_redirect_loop_is_aborted(monkeypatch):
    """重定向环必须有界退出，不能把服务拖死。"""
    seen: list = []
    _patch_guard(monkeypatch)
    _patch_httpx(
        monkeypatch,
        [_FakeResp(302, {"location": "https://public.example/x"})],
        seen,
    )

    with pytest.raises(ValueError) as ei:
        asyncio_run(core.request_with_validated_redirects("GET", "https://public.example/x"))
    assert "重定向" in str(ei.value)
    assert len(seen) == core.MAX_REDIRECTS + 1


def test_read_outside_allowed_root_is_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    outside = tmp_path.parent / "outside-spec.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(core.PathNotAllowed):
        core.ensure_readable(str(outside))


# ----------------------------- VERIFY 判定 --------------------------------- #
@pytest.mark.parametrize(
    "status,expected_status,expected_passed",
    [
        (200, "passed", True),
        (201, "passed", True),
        (400, "bad_request", False),
        (401, "auth_required", False),
        (403, "auth_required", False),
        (404, "not_found", False),
        (429, "rate_limited", False),
        (500, "server_error", False),
    ],
)
def test_classify_response_is_not_always_true(status, expected_status, expected_passed):
    """回归 v1 缺陷：任何响应（含 4xx/5xx）都曾被记为 reachable=True。"""
    got_status, got_passed = core.classify_response(status)
    assert (got_status, got_passed) == (expected_status, expected_passed)


# ----------------------------- MONETIZE ------------------------------------ #
def test_metering_records_and_invoice_math(tmp_path):
    meter = metering.UsageMeter(tmp_path / "usage.json")
    for i in range(5):
        meter.record("demo", "opA", ok=i < 4, status_code=200 if i < 4 else 500, latency_ms=12.5)

    rep = meter.report("demo")
    assert rep["apis"]["demo"]["total_calls"] == 5
    assert rep["apis"]["demo"]["ok_calls"] == 4
    assert rep["apis"]["demo"]["operations"][0]["calls"] == 5

    # basic 档：10000 次额度，2.0 / 1000 次。10 万次 -> 9 万超额 -> 180.0
    inv = meter.simulate_invoice("demo", "basic", basis="actual", projected_calls=100_000)
    assert inv["billable_overage_calls"] == 90_000
    assert inv["amount_due"] == 180.0


def test_metering_survives_corrupt_file(tmp_path):
    path = tmp_path / "usage.json"
    path.write_text("{ this is not json", encoding="utf-8")
    meter = metering.UsageMeter(path)
    assert meter.report()["total_calls_all_apis"] == 0
    assert (tmp_path / "usage.corrupt.json").exists(), "损坏文件应留档而非静默丢弃"


def test_registry_persists_atomically_and_warns_on_overwrite(tmp_path, fixture_spec):
    path = tmp_path / "registry.json"
    reg = core.Registry(path)
    first = reg.register("demo", str(FIXTURE))
    assert first["overwrote_existing"] is False
    second = reg.register("demo", str(FIXTURE))
    assert second["overwrote_existing"] is True
    assert core.Registry(path).list_names() == ["demo"]


def test_registry_reports_unknown_operation_helpfully(tmp_path):
    reg = core.Registry(tmp_path / "registry.json")
    reg.register("demo", str(FIXTURE))
    res = reg.call("demo", "no-such-op", {})
    assert "error" in res and "可用" in res["error"]


# ----------------------------- 工具策展 ------------------------------------ #
def test_scope_filter_by_tag_and_method(fixture_spec):
    ops = core.extract_operations(fixture_spec)
    filtered = core.filter_operations(ops, {"include_tags": ["pet"], "include_methods": ["GET"]})
    ids = {o["operation_id"] for o in filtered}
    assert ids == {"getPetById"}


def test_scope_exclude_deprecated_and_path_pattern():
    spec = core.parse_spec_text(
        json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "t", "version": "1"},
                "servers": [{"url": "https://a.example.com"}],
                "paths": {
                    "/pet/{id}": {
                        "get": {"operationId": "getPet", "tags": ["pet"], "responses": {"200": {"description": "ok"}}},
                        "delete": {"operationId": "delPet", "deprecated": True, "responses": {"200": {"description": "ok"}}},
                    },
                    "/store/inv": {
                        "get": {"operationId": "getInv", "responses": {"200": {"description": "ok"}}},
                    },
                },
            }
        )
    )
    ops = core.extract_operations(spec)
    filtered = core.filter_operations(ops, {"exclude_deprecated": True, "include_path_patterns": ["/pet/*"]})
    assert [o["operation_id"] for o in filtered] == ["getPet"]


def test_scope_intent_top_n():
    spec = core.parse_spec_text(
        json.dumps(
            {
                "openapi": "3.0.0",
                "info": {"title": "t", "version": "1"},
                "servers": [{"url": "https://a.example.com"}],
                "paths": {
                    "/users/{id}": {"get": {"operationId": "getUser", "summary": "get user", "tags": ["user"], "responses": {"200": {"description": "ok"}}}},
                    "/orders/{id}": {"get": {"operationId": "getOrder", "summary": "get order", "tags": ["order"], "responses": {"200": {"description": "ok"}}}},
                    "/pets/{id}": {"get": {"operationId": "getPet", "summary": "get pet", "tags": ["pet"], "responses": {"200": {"description": "ok"}}}},
                },
            }
        )
    )
    ops = core.extract_operations(spec)
    filtered = core.filter_operations(ops, {"intent": "user account", "top_n": 1})
    assert len(filtered) == 1
    assert filtered[0]["operation_id"] == "getUser"


def test_preview_scope_shows_reduction(fixture_spec):
    preview = core.preview_scope(str(FIXTURE), {"include_methods": ["GET"]})
    assert preview["total_operations"] == len(core.extract_operations(fixture_spec))
    assert preview["filtered_operations"] < preview["total_operations"]
    assert preview["reduction_percent"] > 0
    assert "suggestions" in preview


def test_bundle_with_scope_reduces_tool_count(tmp_path, fixture_spec, monkeypatch):
    monkeypatch.chdir(tmp_path)
    full = core.bundle_from_spec(fixture_spec, "offline-mcp")
    scoped = core.bundle_from_spec(fixture_spec, "offline-mcp-scoped", scope={"include_methods": ["GET"]})
    assert scoped["tools"] < full["tools"]
    assert scoped["original_operations"] == full["tools"]
    assert scoped["scope"]["include_methods"] == ["GET"]
