"""
core.py · MCPForge 核心逻辑 v2（与传输层解耦，server.py / demo_app.py / verify.py 共用）

v2 相对 v1 的实质变更（每一条都对应一次对抗式复核发现）：
- [修复] 粘贴的 OpenAPI 文本不再被误判为文件路径（v1 会抛 FileNotFoundError）。
- [修复] IO 全部改为 async，不再用同步 httpx 阻塞事件循环。
- [修复] VERIFY 不再「任何响应都算可达」：区分 2xx 通过 / 鉴权失败 / 参数错误 / 不可达。
- [修复] 代码生成不再把原始路径缝进 f-string（v1 对 {account-id} 这类占位符会产出 NameError）。
- [修复] 代码生成的 docstring 做转义，避免 spec 里的三引号把生成文件弄成 SyntaxError。
- [修复] 生成物落盘做目录穿越防护；本地文件读取限定在允许根内。
- [修复] 出网做 SSRF 防护（默认拒绝回环/内网/链路本地地址）。
- [修复] 注册表原子写入，损坏文件留档而非静默清空。
- [新增] $ref 展开、path 级 parameters 合并、鉴权方案识别、分页参数识别。
- [新增] 每次调用写入真实用量计量（供 MONETIZE 出账）。

本模块不依赖 FastMCP，可独立单测。
合规：纯 API/MCP 工程能力，不含任何安全/审计/链上安全外壳。
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
import socket
import tempfile
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

import metering

VERSION = "2.1.0"
USER_AGENT = f"MCPForge/{VERSION}"
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
DEFAULT_TIMEOUT = 20.0

# 分页参数启发式（用于在 BUILD 阶段提示调用方如何翻页）
_PAGINATION_HINTS = {
    "limit", "offset", "page", "page_size", "pagesize", "per_page", "perpage",
    "cursor", "skip", "start", "count", "size", "next",
}


class SpecSourceError(ValueError):
    """spec 来源无法解析（URL 取不到 / 文件不存在 / 文本不是合法 spec）。"""


class PathNotAllowed(PermissionError):
    """路径越出安全边界。"""


# --------------------------------------------------------------------------- #
# 安全边界：读取根、写入根、出网白名单
# --------------------------------------------------------------------------- #
def _read_roots() -> list[Path]:
    """允许读取本地 spec 的根目录。默认当前工作目录，可用 MCPFORGE_READ_ROOTS 覆盖（os.pathsep 分隔）。"""
    env = os.getenv("MCPFORGE_READ_ROOTS", "")
    roots = [Path(p).expanduser().resolve() for p in env.split(os.pathsep) if p.strip()]
    return roots or [Path.cwd().resolve()]


def ensure_readable(path_str: str) -> Path:
    """把用户给的本地路径限定在允许根内，防止把工具面变成任意文件读取原语。"""
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p = p.resolve()
    if os.getenv("MCPFORGE_ALLOW_ANY_PATH", "") == "1":
        return p
    for root in _read_roots():
        if p == root or root in p.parents:
            return p
    raise PathNotAllowed(
        f"拒绝读取 {p}：超出允许目录 {[str(r) for r in _read_roots()]}。"
        "如需放宽，设置环境变量 MCPFORGE_ALLOW_ANY_PATH=1 或 MCPFORGE_READ_ROOTS。"
    )


_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def ensure_writable_dir(root: str, name: str) -> Path:
    """生成物落盘路径：名称白名单 + 结果必须位于 root 之内，拒绝目录穿越。"""
    if not _SAFE_NAME_RE.match(name or ""):
        raise PathNotAllowed(
            f"名称 {name!r} 不合法：仅允许字母/数字/._-，须以字母或数字开头，长度 1-64。"
        )
    root_p = Path(root).expanduser()
    if not root_p.is_absolute():
        root_p = Path.cwd() / root_p
    root_p = root_p.resolve()
    target = (root_p / name).resolve()
    if target != root_p and root_p not in target.parents:
        raise PathNotAllowed(f"输出目录 {target} 越出允许根 {root_p}，已拒绝。")
    return target


def assert_public_url(url: str) -> None:
    """出网前的 SSRF 防护：默认拒绝回环/内网/链路本地/保留地址。

    这不是完备防护（不防 DNS rebinding），但能挡掉云元数据端点与内网探测这两类最常见的滥用。
    本地联调可设 MCPFORGE_ALLOW_PRIVATE_NET=1 放行。
    """
    if os.getenv("MCPFORGE_ALLOW_PRIVATE_NET", "") == "1":
        return
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"仅支持 http/https，收到 {p.scheme!r}")
    host = p.hostname
    if not host:
        raise ValueError(f"URL 缺少主机名：{url}")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError(f"拒绝访问本机地址 {host}（如需放行设置 MCPFORGE_ALLOW_PRIVATE_NET=1）")
    port = p.port or (443 if p.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValueError(f"无法解析主机 {host}：{e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(
                f"拒绝访问 {host}：解析到非公网地址 {ip}。"
                "如需放行本机/内网，设置 MCPFORGE_ALLOW_PRIVATE_NET=1。"
            )


_REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})
MAX_REDIRECTS = 5


async def request_with_validated_redirects(
    method: str,
    url: str,
    *,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = MAX_REDIRECTS,
) -> httpx.Response:
    """带「逐跳校验」的 HTTP 请求。

    为什么不能直接用 httpx 的 follow_redirects=True：它只在初始 URL 上给我们
    一次校验机会，一个**公网**地址只要 302 到 169.254.169.254 或 127.0.0.1，
    SSRF 防护就被整体绕过。这一点已实测复现（公开 URL -> 302 -> 本地服务，
    返回体里读到了内网内容，status_code=200）。

    因此这里手动跟跳，**每一跳都重新调用 assert_public_url**，
    并按 RFC 语义处理 303/302 的方法改写。
    """
    current_url = url
    current_method = method.upper()
    current_params = params
    current_body = json_body

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            assert_public_url(current_url)
            resp = await client.request(
                current_method,
                current_url,
                params=current_params or None,
                json=current_body,
                headers=headers,
            )
            location = resp.headers.get("location")
            if resp.status_code not in _REDIRECT_CODES or not location:
                return resp
            current_url = urllib.parse.urljoin(str(resp.url), location)
            # 303 一律改 GET；302 对非 GET 按浏览器惯例改 GET
            if resp.status_code == 303 or (
                resp.status_code == 302 and current_method not in ("GET", "HEAD")
            ):
                current_method = "GET"
                current_body = None
            current_params = None  # 参数已并入当前 URL，避免二次拼接

    raise ValueError(f"重定向超过 {max_redirects} 次，已中止（可能是重定向环）。")


# --------------------------------------------------------------------------- #
# BUILD：解析、$ref 展开、operation 抽取
# --------------------------------------------------------------------------- #
def _looks_like_path(s: str) -> bool:
    if s.startswith(("./", "../", ".\\", "..\\")):
        return True
    if any(ch in s for ch in ("\n", "\r")):
        return False  # 多行必然是文本，不是路径
    if s.lower().endswith((".json", ".yaml", ".yml")):
        return True
    return ("/" in s or "\\" in s) and " " not in s.strip() and "{" not in s


def parse_spec_text(text: str, source: str = "<text>") -> dict:
    """把一段文本解析成 spec dict。JSON 优先，回退 YAML。失败时给出可诊断的错误。"""
    if not text or not text.strip():
        raise SpecSourceError(f"spec 内容为空（来源：{source}）")
    spec: Any = None
    err: Optional[Exception] = None
    try:
        spec = json.loads(text)
    except json.JSONDecodeError as e:
        err = e
        try:
            spec = yaml.safe_load(text)
        except yaml.YAMLError as e2:
            raise SpecSourceError(
                f"无法把内容解析为 JSON 或 YAML（来源：{source}）。JSON 错误：{e}；YAML 错误：{e2}"
            ) from e2
    if not isinstance(spec, dict):
        raise SpecSourceError(
            f"内容解析后不是 OpenAPI 对象，而是 {type(spec).__name__}（来源：{source}）。"
            "请确认传入的是 OpenAPI/Swagger 文档本身。"
        )
    if "paths" not in spec and "openapi" not in spec and "swagger" not in spec:
        raise SpecSourceError(
            f"内容不像 OpenAPI 文档：顶层缺少 paths/openapi/swagger 键（来源：{source}）。"
            f"实际顶层键：{sorted(spec.keys())[:10]}"
        )
    return spec


async def _fetch_text_async(url: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    r = await request_with_validated_redirects(
        "GET",
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*"},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.text


def _fetch_text(url: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    return asyncio.run(_fetch_text_async(url, timeout))


async def load_spec_async(source: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """异步加载 spec。

    来源判定顺序（这是 v1 出 bug 的地方，v2 改为「先试真身，再谈形状」）：
      1) http(s) URL        -> 拉取
      2) 存在的本地文件      -> 读取（受允许根约束）
      3) 其余一律当文本解析  -> 解析失败且形似路径，才报 FileNotFoundError
    """
    src = (source or "").strip()
    if not src:
        raise SpecSourceError("spec_source 不能为空")

    if src.startswith(("http://", "https://")):
        text = await _fetch_text_async(src, timeout)
        spec = parse_spec_text(text, src)
    elif Path(src).expanduser().is_file():
        p = ensure_readable(src)
        spec = parse_spec_text(p.read_text(encoding="utf-8"), str(p))
    else:
        try:
            spec = parse_spec_text(src, "<inline text>")
        except SpecSourceError as e:
            if _looks_like_path(src):
                raise FileNotFoundError(
                    f"本地 spec 文件不存在：{src}（若你本意是粘贴 spec 文本，"
                    "请确认它是合法的 OpenAPI JSON/YAML）"
                ) from e
            raise

    spec["x_base_url"] = resolve_base_url(spec, src)
    spec["x_source"] = src if src.startswith(("http://", "https://")) else "<local-or-inline>"
    return spec


def load_spec(source: str, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """同步封装（供脚本与单测使用）。MCP 工具请用 load_spec_async。"""
    return asyncio.run(load_spec_async(source, timeout))


def resolve_base_url(spec: dict, source: str = "") -> str:
    """解析 base_url。正确处理相对 server URL（如 petstore3 的 /api/v3）与缺前导斜杠的情况。"""
    servers = spec.get("servers") or []
    url = ""
    if isinstance(servers, list) and servers and isinstance(servers[0], dict):
        url = servers[0].get("url") or ""

    if url and url.startswith(("http://", "https://")):
        return url.rstrip("/")

    # OpenAPI 2.0
    if not url:
        schemes = spec.get("schemes") or ["https"]
        host = spec.get("host")
        base_path = spec.get("basePath", "")
        if host:
            return f"{schemes[0]}://{host}{base_path}".rstrip("/")

    # 相对 server URL：用 spec 来源的 origin 补全，并归一化分隔符
    if url and source.startswith(("http://", "https://")):
        p = urllib.parse.urlparse(source)
        if not url.startswith("/"):
            url = "/" + url
        return (f"{p.scheme}://{p.netloc}" + url).rstrip("/")
    return (url or "").rstrip("/")


def get_base_url(spec: dict) -> str:
    if isinstance(spec, dict) and spec.get("x_base_url"):
        return spec["x_base_url"]
    return resolve_base_url(spec, "")


def resolve_refs(node: Any, root: Optional[dict] = None, _seen: frozenset = frozenset()) -> Any:
    """就地展开本地 $ref（#/...）。带环保护，遇到自引用时保留原节点不递归。"""
    if root is None:
        root = node
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            if ref in _seen:
                return node  # 环：停止递归
            target: Any = root
            for part in ref[2:].split("/"):
                part = part.replace("~1", "/").replace("~0", "~")
                if isinstance(target, dict) and part in target:
                    target = target[part]
                else:
                    return node  # 解不开就原样保留
            merged = resolve_refs(target, root, _seen | {ref})
            if isinstance(merged, dict):
                extra = {k: resolve_refs(v, root, _seen) for k, v in node.items() if k != "$ref"}
                return {**merged, **extra}
            return merged
        return {k: resolve_refs(v, root, _seen) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_refs(v, root, _seen) for v in node]
    return node


def detect_auth(spec: dict) -> list[dict]:
    """识别 spec 声明的鉴权方案（OpenAPI 3 components.securitySchemes / 2.0 securityDefinitions）。"""
    schemes = (
        (spec.get("components") or {}).get("securitySchemes")
        or spec.get("securityDefinitions")
        or {}
    )
    out: list[dict] = []
    if not isinstance(schemes, dict):
        return out
    for name, s in schemes.items():
        if not isinstance(s, dict):
            continue
        t = s.get("type")
        if t == "apiKey":
            out.append({"name": name, "type": "apiKey", "in": s.get("in"), "key_name": s.get("name")})
        elif t == "http":
            out.append({"name": name, "type": "http", "scheme": (s.get("scheme") or "").lower()})
        elif t == "oauth2":
            flats = s.get("flows") or s.get("flow") or {}
            out.append({"name": name, "type": "oauth2", "flows": sorted(flats) if isinstance(flats, dict) else []})
        elif t == "basic":
            out.append({"name": name, "type": "basic"})
    return out


def _param_type(schema: Optional[dict]) -> str:
    t = (schema or {}).get("type")
    return {"integer": "int", "number": "float", "boolean": "bool"}.get(t, "str")


def _collect_params(raw_params: list, path_level: list) -> tuple[list, list, list]:
    """合并 path 级与 operation 级 parameters（后者按 name+in 覆盖前者）。"""
    merged: dict[tuple, dict] = {}
    for p in list(path_level) + list(raw_params):
        if not isinstance(p, dict) or not p.get("name"):
            continue
        merged[(p.get("name"), p.get("in"))] = p

    path_params, query_params, header_params = [], [], []
    for p in merged.values():
        where = p.get("in")
        entry = {
            "name": p.get("name"),
            "type": _param_type(p.get("schema") or p),
            "required": bool(p.get("required", where == "path")),
            "description": p.get("description", ""),
            "pagination_hint": where == "query" and (p.get("name") or "").lower() in _PAGINATION_HINTS,
        }
        if where == "path":
            path_params.append(entry)
        elif where == "query":
            query_params.append(entry)
        elif where == "header":
            header_params.append(entry)
    return path_params, query_params, header_params


def extract_operations(spec: dict) -> list[dict]:
    """从 spec 抽取 operation。会先展开 $ref，并合并 path 级 parameters。"""
    resolved = resolve_refs(spec)
    base = get_base_url(resolved)
    ops: list[dict] = []
    for path, item in (resolved.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        path_level = item.get("parameters") or []
        for method, meta in item.items():
            if not isinstance(meta, dict) or method.lower() not in HTTP_METHODS:
                continue
            op_id = meta.get("operationId") or f"{method}_{path}".replace("/", "_").strip("_")
            pp, qp, hp = _collect_params(meta.get("parameters") or [], path_level)
            body_schema = ((meta.get("requestBody") or {}).get("content") or {})
            has_body = bool(meta.get("requestBody")) or bool(body_schema)
            ops.append(
                {
                    "operation_id": op_id,
                    "method": method.upper(),
                    "path": path,
                    "summary": meta.get("summary") or meta.get("description") or "",
                    "tags": meta.get("tags", []),
                    "deprecated": bool(meta.get("deprecated")),
                    "path_params": pp,
                    "query_params": qp,
                    "header_params": hp,
                    "has_body": has_body,
                    "security": meta.get("security", spec.get("security", [])),
                    "paginated": any(p.get("pagination_hint") for p in qp),
                    "base_url": base,
                }
            )
    return ops


# --------------------------------------------------------------------------- #
# 工具策展：把 N 个端点聚合成 Agent 能消化的少量工具
# --------------------------------------------------------------------------- #
def _matches_any(text: str, patterns: list[str]) -> bool:
    """支持通配符 * 的简易匹配（* 匹配任意字符，其余按子串）。"""
    if not patterns:
        return False
    for pat in patterns:
        pat = (pat or "").strip()
        if not pat:
            continue
        if "*" in pat:
            regex = pat.replace("*", ".*")
            if re.search(regex, text, re.IGNORECASE):
                return True
        elif pat.lower() in text.lower():
            return True
    return False


def _intent_score(op: dict, intent: str) -> float:
    """按关键词对 operation 与意图的匹配度打分（用于无规则时的语义排序）。"""
    keywords = [k.strip().lower() for k in intent.replace(",", " ").split() if k.strip()]
    if not keywords:
        return 0.0
    haystack = " ".join(
        [
            op.get("operation_id", ""),
            op.get("path", ""),
            op.get("summary", ""),
            " ".join(str(t) for t in op.get("tags", [])),
        ]
    ).lower()
    matched = sum(1 for k in keywords if k in haystack)
    # 命中关键词比例 + 命中密度，让高匹配排在前面
    return matched / len(keywords) + matched * 0.05


def filter_operations(ops: list[dict], scope: Optional[dict] = None) -> list[dict]:
    """按 scope 规则过滤并排序 operation，解决「工具爆炸」问题。

    scope 字段（均为可选）：
      - include_operation_ids / exclude_operation_ids: list[str]
      - include_tags / exclude_tags: list[str]（支持 * 通配）
      - include_methods / exclude_methods: list[str]
      - include_path_patterns / exclude_path_patterns: list[str]（支持 * 通配）
      - intent: str — 语义意图描述，按关键词匹配 summary/path/tags/operation_id
      - top_n: int — 配合 intent 使用，只取最相关的 N 个
      - exclude_deprecated: bool — 默认 True，排除 deprecated 操作
    """
    if not scope:
        return ops
    if not isinstance(scope, dict):
        raise TypeError("scope 必须是字典")

    out = list(ops)

    if scope.get("exclude_deprecated", True):
        out = [o for o in out if not o.get("deprecated")]

    include_ids = scope.get("include_operation_ids") or []
    if include_ids:
        out = [o for o in out if o.get("operation_id") in include_ids]

    exclude_ids = scope.get("exclude_operation_ids") or []
    if exclude_ids:
        out = [o for o in out if o.get("operation_id") not in exclude_ids]

    include_tags = scope.get("include_tags") or []
    if include_tags:
        out = [o for o in out if any(_matches_any(str(t), include_tags) for t in o.get("tags", []))]

    exclude_tags = scope.get("exclude_tags") or []
    if exclude_tags:
        out = [o for o in out if not any(_matches_any(str(t), exclude_tags) for t in o.get("tags", []))]

    include_methods = [m.upper() for m in (scope.get("include_methods") or []) if m]
    if include_methods:
        out = [o for o in out if o.get("method", "").upper() in include_methods]

    exclude_methods = [m.upper() for m in (scope.get("exclude_methods") or []) if m]
    if exclude_methods:
        out = [o for o in out if o.get("method", "").upper() not in exclude_methods]

    include_paths = scope.get("include_path_patterns") or []
    if include_paths:
        out = [o for o in out if _matches_any(o.get("path", ""), include_paths)]

    exclude_paths = scope.get("exclude_path_patterns") or []
    if exclude_paths:
        out = [o for o in out if not _matches_any(o.get("path", ""), exclude_paths)]

    intent = (scope.get("intent") or "").strip()
    if intent:
        scored = [(o, _intent_score(o, intent)) for o in out]
        scored.sort(key=lambda x: x[1], reverse=True)
        top_n = scope.get("top_n")
        if top_n and int(top_n) > 0:
            scored = scored[: int(top_n)]
        # 只保留至少命中一个关键词的；如果全没命中，保留原顺序（避免空结果）
        if any(s > 0 for _, s in scored):
            out = [o for o, s in scored if s > 0]
        else:
            out = [o for o, _ in scored]

    return out


def suggest_scope(ops: list[dict]) -> dict:
    """基于 operation 集合自动推荐可用的策展维度（tags、methods、路径前缀）。"""
    tags: set[str] = set()
    methods: set[str] = set()
    prefixes: set[str] = set()
    for o in ops:
        methods.add(o.get("method", "").upper())
        for t in o.get("tags", []):
            if isinstance(t, str):
                tags.add(t)
        path = o.get("path", "")
        parts = [p for p in path.split("/") if p and not p.startswith("{")]
        if parts:
            prefixes.add("/" + parts[0])
    return {
        "tags": sorted(tags),
        "methods": sorted(methods),
        "path_prefixes": sorted(prefixes),
        "total_operations": len(ops),
        "deprecated_operations": sum(1 for o in ops if o.get("deprecated")),
    }


def op_input_schema(op: dict) -> dict:
    """为单个 operation 生成 JSON Schema（用于市场清单与生成代码的参数说明）。"""
    props: dict[str, Any] = {}
    required: list[str] = []
    for p in op.get("path_params", []) + op.get("query_params", []):
        props[p["name"]] = {
            "type": {"int": "integer", "float": "number", "bool": "boolean"}.get(p["type"], "string"),
            "description": p.get("description") or "",
            **({"x-pagination": True} if p.get("pagination_hint") else {}),
        }
        if p.get("required"):
            required.append(p["name"])
    if op.get("has_body"):
        props["body"] = {"type": "object", "description": "请求体（JSON）"}
    return {"type": "object", "properties": props, "required": required}


def list_operations(spec_source: str) -> str:
    """同步封装（供脚本使用）。"""
    return asyncio.run(list_operations_async(spec_source))


async def list_operations_async(spec_source: str) -> str:
    return format_operations(await load_spec_async(spec_source))


def format_operations(spec: dict) -> str:
    """纯函数：把 spec 渲染成可读操作清单。"""
    ops = extract_operations(spec)
    if not ops:
        return "该 spec 未发现任何可调用操作（paths 为空？）"
    lines = [f"共 {len(ops)} 个操作："]
    for o in ops:
        flags = []
        if o["deprecated"]:
            flags.append("已废弃")
        if o["paginated"]:
            flags.append("支持分页")
        if o["security"]:
            flags.append("需鉴权")
        suffix = f"  [{'/'.join(flags)}]" if flags else ""
        lines.append(
            f"- [{o['method']}] {o['path']}  →  {o['operation_id']}  ({o['summary']}){suffix}"
        )
    return "\n".join(lines)


def parse_openapi_spec(spec_source: str) -> dict:
    """同步封装（供脚本使用）。"""
    return asyncio.run(parse_openapi_spec_async(spec_source))


async def parse_openapi_spec_async(spec_source: str) -> dict:
    """契约 §4#2 点名的工具：解析 OpenAPI，返回结构化 operations 列表。"""
    return spec_overview(await load_spec_async(spec_source))


def spec_overview(spec: dict) -> dict:
    """纯函数：已解析的 spec -> 结构化概览。"""
    ops = extract_operations(spec)
    info = spec.get("info") or {}
    return {
        "title": info.get("title"),
        "version": info.get("version"),
        "description": info.get("description"),
        "openapi_version": spec.get("openapi") or spec.get("swagger"),
        "base_url": get_base_url(spec),
        "source_kind": "url" if str(spec.get("x_source", "")).startswith("http") else "local-or-inline",
        "auth_schemes": detect_auth(spec),
        "operation_count": len(ops),
        "operations": [
            {
                "operation_id": o["operation_id"],
                "method": o["method"],
                "path": o["path"],
                "summary": o["summary"],
                "tags": o["tags"],
                "deprecated": o["deprecated"],
                "paginated": o["paginated"],
                "requires_auth": bool(o["security"]),
                "input_schema": op_input_schema(o),
            }
            for o in ops
        ],
    }


def ingest_spec(source: str) -> dict:
    """parse_openapi_spec 的兼容别名（v1 名称，保留以便旧调用方不中断）。"""
    return parse_openapi_spec(source)


# --------------------------------------------------------------------------- #
# VERIFY：真实调用 + 真断言
# --------------------------------------------------------------------------- #
def _sample_value(param: dict) -> Any:
    name = (param.get("name") or "").lower()
    t = param.get("type")
    if t == "int":
        return 1
    if t == "bool":
        return True
    if t == "float":
        return 1.0
    if "email" in name:
        return "a@b.com"
    if "date" in name:
        return "2026-01-01"
    if "id" in name or "code" in name:
        return "1"
    return "sample"


def classify_response(status_code: int) -> tuple[str, bool]:
    """把 HTTP 状态码映射成明确结论。这是 v1「任何响应都算可达」的修复点。

    返回 (status, passed)。passed 只有在 2xx 时才为真。
    """
    if 200 <= status_code < 300:
        return "passed", True
    if status_code in (401, 403):
        return "auth_required", False
    if status_code == 404:
        return "not_found", False
    if status_code == 429:
        return "rate_limited", False
    if 400 <= status_code < 500:
        return "bad_request", False
    if 500 <= status_code < 600:
        return "server_error", False
    return "unexpected_status", False


async def verify_operation_async(
    base_url: str,
    op: dict,
    client: httpx.AsyncClient,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """真实调用一次 operation，并按状态码给出 pass/fail 结论（不是恒真的可达性）。"""
    path = op["path"]
    used_params: dict[str, Any] = {}
    for p in op.get("path_params", []):
        v = _sample_value(p)
        used_params[p["name"]] = v
        path = path.replace("{" + p["name"] + "}", urllib.parse.quote(str(v)))
    url = (base_url.rstrip("/") + "/" + path.lstrip("/")) if base_url else path
    query = {p["name"]: _sample_value(p) for p in op.get("query_params", [])}

    result: dict[str, Any] = {
        "operation_id": op["operation_id"],
        "method": op["method"],
        "url": url,
        "sample_params": used_params,
        "status": "unreachable",
        "passed": False,
        "http_status": None,
        "latency_ms": None,
        "error": None,
        "sample_body": "",
    }
    try:
        start = time.perf_counter()
        r = await client.request(
            op["method"],
            url,
            params=query or None,
            json={} if op["has_body"] else None,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            timeout=timeout,
        )
        result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
        result["http_status"] = r.status_code
        status, passed = classify_response(r.status_code)
        result["status"] = status
        result["passed"] = passed
        result["sample_body"] = (r.text or "")[:600]
    except (httpx.TransportError, httpx.TimeoutException) as e:
        result["error"] = f"{type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001 - 单点失败不应中断整体验证
        result["error"] = f"{type(e).__name__}: {e}"
    return result


async def verify_api_async(
    source: str,
    max_ops: int = 20,
    timeout: float = 8.0,
    concurrency: int = 8,
    scope: Optional[dict] = None,
) -> dict:
    """并发验证，单请求超时有界，整体耗时可控（v1 最坏 20×15=300 秒且阻塞事件循环）。

    支持 scope 先策展再验证：只对过滤后的 operation 做真实调用。
    """
    spec = await load_spec_async(source)
    all_ops = extract_operations(spec)
    ops = filter_operations(all_ops, scope)[:max_ops]
    base = get_base_url(spec)
    sem = asyncio.Semaphore(max(1, concurrency))

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:

        async def one(op: dict) -> dict:
            async with sem:
                return await verify_operation_async(base, op, client, timeout)

        results = await asyncio.gather(*(one(o) for o in ops)) if ops else []

    passed = sum(1 for r in results if r["passed"])
    reached = sum(1 for r in results if r["status"] != "unreachable")
    return {
        "title": (spec.get("info") or {}).get("title"),
        "version": (spec.get("info") or {}).get("version"),
        "base_url": base,
        "total_operations": len(all_ops),
        "filtered_operations": len(ops),
        "scope": scope,
        "verified": len(results),
        "passed": passed,
        "reached_but_failed": reached - passed,
        "unreachable": len(results) - reached,
        "verdict": (
            "全部通过"
            if results and passed == len(results)
            else ("部分通过" if passed else "无通过项（端点可能需要鉴权或真实参数）")
        ),
        "note": (
            "passed 仅统计 HTTP 2xx。401/403 记为 auth_required，404 记为 not_found，"
            "4xx 记为 bad_request（常见于占位参数不满足业务校验），网络失败记为 unreachable。"
        ),
        "results": results,
    }


def verify_api(source: str, max_ops: int = 20, timeout: float = 8.0, concurrency: int = 8, scope: Optional[dict] = None) -> dict:
    """同步封装（供 verify.py / 单测使用）。"""
    return asyncio.run(verify_api_async(source, max_ops, timeout, concurrency, scope))


def verify_operation(base_url: str, op: dict, timeout: float = 8.0) -> dict:
    """同步封装：单次验证。"""

    async def run() -> dict:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
            return await verify_operation_async(base_url, op, c, timeout)

    return asyncio.run(run())


# --------------------------------------------------------------------------- #
# MCPize：代码生成
# --------------------------------------------------------------------------- #
def _py_ident(raw: str) -> str:
    s = re.sub(r"\W", "_", raw or "").strip("_")
    if not s:
        s = "tool"
    if s[0].isdigit():
        s = "op_" + s
    return s


def _dedupe(names: list[str]) -> list[str]:
    """保证生成的函数名唯一（v1 中两个 operation 可能 sanitize 成同名而互相覆盖）。"""
    seen: dict[str, int] = {}
    out: list[str] = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 0
            out.append(n)
    return out


def _safe_docstring(text: str) -> str:
    """把任意 spec 文本安全地放进 Python docstring，避免三引号/反斜杠破坏生成文件。"""
    cleaned = (text or "").replace("\\", "\\\\").replace('"""', "'''")
    cleaned = cleaned.replace("\r", " ").replace("\n", " ").strip()
    return cleaned[:200] or "auto-generated tool"


def _auth_code(spec_auth: list[dict], require_auth: bool) -> tuple[str, str]:
    """根据 spec 声明的鉴权方案生成鉴权代码块。返回 (imports_block, headers_expr)。"""
    if not require_auth:
        return "", "HEADERS: dict[str, str] = {}"
    lines = [
        'import os',
        'API_KEY = os.getenv("API_KEY", "")',
        'API_KEY_HEADER = os.getenv("API_KEY_HEADER", "Authorization")',
        'HEADERS: dict[str, str] = {}',
        'if API_KEY:',
        '    HEADERS[API_KEY_HEADER] = API_KEY',
    ]
    return "\n".join(lines), "HEADERS"


def _path_const_name(func_name: str) -> str:
    return f"_PATH_{func_name.upper()}"


def _gen_single_tool(op: dict, func_name: str) -> str:
    """生成单个工具。

    关键点：不做 f-string 插值，改用模板常量 + str.replace，
    这样 {account-id}、{file.name} 这类非标识符占位符也能正确工作（v1 会产出 NameError）。
    """
    path_params = op.get("path_params", [])
    query_params = op.get("query_params", [])
    method = op["method"].lower()
    const = _path_const_name(func_name)
    doc = _safe_docstring(op.get("summary") or op["operation_id"])

    # 签名 + 原始参数名到合法标识符的映射
    sig_parts: list[str] = []
    mapping: list[tuple[str, str]] = []
    for p in path_params:
        ident = _py_ident(p["name"])
        mapping.append((p["name"], ident))
        sig_parts.append(f"{ident}: {p['type']}")
    for p in query_params:
        ident = _py_ident(p["name"])
        mapping.append((p["name"], ident))
        sig_parts.append(f"{ident}: Optional[{p['type']}] = None")
    if op["has_body"]:
        sig_parts.append("body: Optional[dict] = None")
    signature = ", ".join(sig_parts)

    body_lines: list[str] = [f'        url = BASE_URL.rstrip("/") + {const}']
    for original, ident in mapping:
        if any(original == pp["name"] for pp in path_params):
            body_lines.append(
                f'        url = url.replace("{{{original}}}", urllib.parse.quote(str({ident})))'
            )
    body_lines.append("        params: dict[str, Any] = {}")
    for original, ident in mapping:
        if any(original == qp["name"] for qp in query_params):
            body_lines.append(f"        if {ident} is not None:")
            body_lines.append(f'            params["{original}"] = {ident}')
    body_lines.append("        json_body = body" if op["has_body"] else "        json_body = None")
    body = "\n".join(body_lines)

    return f'''

{const} = "{op["path"]}"


def _register_{func_name}(mcp: FastMCP) -> None:
    """注册 operation {op["operation_id"]}（{op["method"]} {op["path"]}）。"""

    @mcp.tool()
    async def {func_name}({signature}) -> dict:
        """{doc}"""
{body}
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as c:
                    r = await c.{method}(
                        url, params=params or None, json=json_body, headers=HEADERS
                    )
                return {{
                    "status_code": r.status_code,
                    "url": str(r.url),
                    "body": r.text[:4000],
                }}
            except httpx.TransportError as e:
                last_err = e
                await asyncio.sleep(0.4 * (attempt + 1))
        return {{"error": f"{{type(last_err).__name__}}: {{last_err}}"}}
'''


def _module_header(server_name: str, base_url: str, auth_block: str, extra_note: str = "") -> str:
    return f'''"""
{server_name} · 由 MCPForge {VERSION} 自动生成

{extra_note}运行：
    pip install -r requirements.txt
    fastmcp dev server.py
"""
from __future__ import annotations

import asyncio
import os
import urllib.parse
from typing import Any, Optional

import httpx
from fastmcp import FastMCP

mcp = FastMCP("{server_name}")
BASE_URL = os.getenv("API_BASE_URL", "{base_url}")
{auth_block}
'''


def generate_tool_code(
    source: str,
    operation_id: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
) -> str:
    """同步封装（供脚本使用）。"""
    return asyncio.run(generate_tool_code_async(source, operation_id, server_name, require_auth))


async def generate_tool_code_async(
    source: str,
    operation_id: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
) -> str:
    """把单个 operation 生成为可直接部署的 FastMCP 工具代码。"""
    spec = await load_spec_async(source)
    return tool_code_from_spec(spec, operation_id, server_name, require_auth)


def tool_code_from_spec(
    spec: dict,
    operation_id: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
) -> str:
    """纯函数：已解析的 spec -> 单工具代码。"""
    ops = extract_operations(spec)
    op = next((o for o in ops if o["operation_id"] == operation_id), None)
    if not op:
        return (
            f"未找到 operation_id={operation_id!r}。可用 list_operations 查看全部；"
            f"本 spec 共 {len(ops)} 个操作。"
        )
    base = op["base_url"] or "https://REPLACE_WITH_API_BASE_URL"
    auth_block, _ = _auth_code(detect_auth(spec), require_auth)
    name = _py_ident(operation_id)
    return (
        _module_header(server_name, base, auth_block, f"来源 API：{base}\n")
        + _gen_single_tool(op, name)
        + f'\n_register_{name}(mcp)\n\nif __name__ == "__main__":\n    mcp.run()\n'
    )


def generate_bundle(
    source: str,
    name: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
    output_dir: str = "generated",
    scope: Optional[dict] = None,
) -> dict:
    """同步封装（供脚本使用）。"""
    return asyncio.run(
        generate_bundle_async(source, name, server_name, require_auth, output_dir, scope)
    )


async def generate_bundle_async(
    source: str,
    name: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
    output_dir: str = "generated",
    scope: Optional[dict] = None,
) -> dict:
    """生成完整可部署 bundle。落盘路径受 ensure_writable_dir 保护。

    scope 用于先策展再生成：把 100 个端点收敛到 5 个 Agent 可用的工具，
    避免撑爆 Agent 上下文窗口。见 filter_operations 文档。
    """
    spec = await load_spec_async(source)
    return bundle_from_spec(spec, name, server_name, require_auth, output_dir, scope)


def bundle_from_spec(
    spec: dict,
    name: str,
    server_name: str = "generated-mcp-server",
    require_auth: bool = False,
    output_dir: str = "generated",
    scope: Optional[dict] = None,
) -> dict:
    """纯函数：已解析的 spec -> 完整 bundle 落盘。"""
    all_ops = extract_operations(spec)
    ops = filter_operations(all_ops, scope)
    if not ops:
        raise SpecSourceError(
            f"spec 中没有任何 operation 符合 scope 规则，无法生成 bundle（API：{name}）"
        )
    base = get_base_url(spec) or "https://REPLACE_WITH_API_BASE_URL"
    auth_schemes = detect_auth(spec)
    out = ensure_writable_dir(output_dir, name)
    out.mkdir(parents=True, exist_ok=True)

    auth_block, _ = _auth_code(auth_schemes, require_auth)
    func_names = _dedupe([_py_ident(o["operation_id"]) for o in ops])

    note = f"来源 API：{base}\n"
    if scope:
        note += f"原始端点数：{len(all_ops)}；经 scope 策展后生成 {len(ops)} 个工具。\n"
    else:
        note += f"共 {len(ops)} 个工具。\n"
    if auth_schemes:
        note += f"该 API 声明了鉴权方案：{', '.join(s['name'] for s in auth_schemes)}。\n"
        if require_auth:
            note += "运行时请通过环境变量 API_KEY 提供凭据。\n"

    server_py = (
        _module_header(server_name, base, auth_block, note)
        + "".join(_gen_single_tool(op, fn) for op, fn in zip(ops, func_names))
        + "\n" + "".join(f"_register_{fn}(mcp)\n" for fn in func_names)
        + '\nif __name__ == "__main__":\n    mcp.run()\n'
    )
    (out / "server.py").write_text(server_py, encoding="utf-8")
    (out / "requirements.txt").write_text(
        "# 版本已钉死为生成与验证时所用的大版本线\nfastmcp>=4.0,<5.0\nhttpx>=0.27,<1.0\n",
        encoding="utf-8",
    )

    readme_lines = [
        f"# {name} · MCP Server（由 MCPForge 生成）",
        "",
        f"源 API：`{base}`",
        "",
    ]
    if scope:
        readme_lines.append(f"原始端点数：{len(all_ops)}；经 scope 策展后生成 **{len(ops)}** 个工具。")
    else:
        readme_lines.append(f"工具数：{len(ops)}")
    readme_lines.append("")
    readme_lines.append(
        "**该 API 需要鉴权**：运行时设置环境变量 `API_KEY`。" if require_auth else "该 API 无需鉴权。"
    )
    readme_lines.extend([
        "",
        "## 运行",
        "",
        "```bash",
        "pip install -r requirements.txt",
        "# stdio 调试",
        "fastmcp dev server.py",
        "# 暴露为 HTTP 服务",
        "fastmcp run server.py --transport streamable-http --port 8080",
        "```",
        "",
        "## 工具清单",
        "",
    ])
    readme_lines.extend(
        f"- `{fn}` — [{o['method']}] {o['path']}（{o['summary'] or '无摘要'}）"
        for o, fn in zip(ops, func_names)
    )
    readme_lines.append("")
    (out / "README.md").write_text("\n".join(readme_lines), encoding="utf-8")

    manifest = manifest_from_spec(
        spec, name, ops, base_url=base, auth_schemes=auth_schemes
    )
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "schema_version": metering.SCHEMA_VERSION,
        "name": name,
        "output_dir": str(out),
        "tools": len(ops),
        "original_operations": len(all_ops),
        "scope": scope,
        "function_names": func_names,
        "files": [str(p) for p in sorted(out.iterdir())],
    }


# --------------------------------------------------------------------------- #
# MONETIZE：市场清单
# --------------------------------------------------------------------------- #
def manifest_from_spec(
    spec: dict,
    name: str,
    operations: Optional[list[dict]] = None,
    base_url: str = "",
    auth_schemes: Optional[list[dict]] = None,
    category: str = "api-tool",
    pricing_tier: str = "free",
    description: str = "",
    currency: Optional[str] = None,
) -> dict:
    """纯函数：已解析的 spec + 操作列表 -> 市场清单。"""
    operations = operations if operations is not None else extract_operations(spec)
    if auth_schemes is None:
        auth_schemes = detect_auth(spec)
    auth_schemes = auth_schemes or []
    if not base_url:
        base_url = get_base_url(spec)
    tier = metering.PRICING_TIERS.get(pricing_tier, metering.PRICING_TIERS["free"])

    return {
        "schema_version": metering.SCHEMA_VERSION,
        "generated_by": f"MCPForge/{VERSION}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "listing": {
            "name": name,
            "display_name": name.replace("-", " ").replace("_", " ").title(),
            "category": category,
            "description": description
            or f"由 MCPForge 一键 MCP 化的 {name} API，共 {len(operations)} 个可调用工具。",
            "endpoint": base_url or "",
            "auth": {
                "required": bool(auth_schemes),
                "schemes": auth_schemes,
                "credential_env": "API_KEY" if auth_schemes else None,
            },
            "capabilities": {
                "tool_count": len(operations),
                "paginated_tools": sum(1 for o in operations if o.get("paginated")),
                "deprecated_tools": sum(1 for o in operations if o.get("deprecated")),
            },
        },
        "tools": [
            {
                "operation_id": o["operation_id"],
                "method": o["method"],
                "path": o["path"],
                "summary": o["summary"],
                "input_schema": op_input_schema(o),
            }
            for o in operations
        ],
        "pricing": {
            "tier": pricing_tier,
            "billing_model": tier["model"],
            "included_calls": tier["included_calls"],
            "price_per_1k_calls": tier["price_per_1k_calls"],
            "currency": currency or metering.DEFAULT_CURRENCY,
            "all_tiers": {
                k: {
                    "price_per_1k_calls": v["price_per_1k_calls"],
                    "included_calls": v["included_calls"],
                }
                for k, v in metering.PRICING_TIERS.items()
            },
        },
        "compliance": {
            "note": "本清单为工程作品产出，用于演示 API→MCP 的封装与计量能力。",
            "contains_security_audit_capability": False,
            "crypto_token_speculation": False,
        },
    }


def build_manifest(
    name: str,
    source: str = "",
    operations: Optional[list[dict]] = None,
    base_url: str = "",
    auth_schemes: Optional[list[dict]] = None,
    category: str = "api-tool",
    pricing_tier: str = "free",
    description: str = "",
    currency: Optional[str] = None,
    scope: Optional[dict] = None,
) -> dict:
    """同步封装（供脚本使用）。"""
    return asyncio.run(
        build_manifest_async(
            name, source, operations, base_url, auth_schemes,
            category, pricing_tier, description, currency, scope,
        )
    )


def preview_scope(spec_source: str, scope: Optional[dict] = None) -> dict:
    """同步封装（供脚本使用）。"""
    return asyncio.run(preview_scope_async(spec_source, scope))


async def preview_scope_async(spec_source: str, scope: Optional[dict] = None) -> dict:
    """在不生成代码的前提下，预览 scope 策展结果：原始数、过滤后数、保留了哪些 operation。"""
    spec = await load_spec_async(spec_source)
    all_ops = extract_operations(spec)
    filtered = filter_operations(all_ops, scope)
    return {
        "total_operations": len(all_ops),
        "filtered_operations": len(filtered),
        "reduction_percent": round((1 - len(filtered) / len(all_ops)) * 100, 1) if all_ops else 0.0,
        "scope": scope,
        "suggestions": suggest_scope(all_ops),
        "kept_operations": [
            {
                "operation_id": o["operation_id"],
                "method": o["method"],
                "path": o["path"],
                "summary": o["summary"],
                "tags": o["tags"],
            }
            for o in filtered
        ],
    }


async def build_manifest_async(
    name: str,
    source: str = "",
    operations: Optional[list[dict]] = None,
    base_url: str = "",
    auth_schemes: Optional[list[dict]] = None,
    category: str = "api-tool",
    pricing_tier: str = "free",
    description: str = "",
    currency: Optional[str] = None,
    scope: Optional[dict] = None,
) -> dict:
    """生成市场格式清单。含工具级 JSON Schema、鉴权要求、额度与计费模型。

    支持 scope 先策展再生成清单。
    """
    spec: dict = {}
    if operations is None and source:
        spec = await load_spec_async(source)
        operations = filter_operations(extract_operations(spec), scope)
    if auth_schemes is None and spec:
        auth_schemes = detect_auth(spec)
    return manifest_from_spec(
        spec, name, operations, base_url, auth_schemes,
        category, pricing_tier, description, currency,
    )


# --------------------------------------------------------------------------- #
# 调用：通用 REST + 注册表
# --------------------------------------------------------------------------- #
async def _call_op_async(
    base_url: str,
    op: dict,
    kwargs: dict,
    query: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    path = op["path"]
    for p in op.get("path_params", []):
        if p["name"] in kwargs:
            path = path.replace(
                "{" + p["name"] + "}", urllib.parse.quote(str(kwargs.pop(p["name"])))
            )
    url = (base_url.rstrip("/") + "/" + path.lstrip("/")) if base_url else path
    if query is None:
        query_names = {p["name"] for p in op.get("query_params", [])}
        query = {k: v for k, v in kwargs.items() if k in query_names}
    body = kwargs.get("__body__")
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    start = time.perf_counter()
    try:
        r = await request_with_validated_redirects(
            op["method"],
            url,
            params=query or None,
            json_body=body,
            headers=headers,
            timeout=timeout,
        )
        return {
            "status_code": r.status_code,
            "url": str(r.url),
            "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            "ok": 200 <= r.status_code < 300,
            "body_preview": r.text[:2000],
        }
    except Exception as e:  # noqa: BLE001
        return {
            "status_code": None,
            "url": url,
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        }


def _call_op(base_url: str, op: dict, kwargs: dict, query: Optional[dict] = None) -> dict:
    return asyncio.run(_call_op_async(base_url, op, kwargs, query))


async def call_rest_api_async(
    base_url: str,
    path: str,
    method: str = "GET",
    query: Optional[dict] = None,
    body: Optional[dict] = None,
) -> dict:
    op = {
        "path": path,
        "method": method.upper(),
        "path_params": [],
        "query_params": [],
        "has_body": bool(body),
        "base_url": base_url,
    }
    kwargs = dict(query or {})
    if body is not None:
        kwargs["__body__"] = body
    return await _call_op_async(base_url, op, kwargs, query=query)


def call_rest_api(
    base_url: str,
    path: str,
    method: str = "GET",
    query: Optional[dict] = None,
    body: Optional[dict] = None,
) -> dict:
    """通用 REST 调用：调通任意公开 API（online-callable capability 本体）。"""
    return asyncio.run(call_rest_api_async(base_url, path, method, query, body))


def _registry_path() -> Path:
    return Path(os.getenv("MCPFORGE_REGISTRY", "registry.json"))


class Registry:
    """持久化注册表。原子写入；损坏文件留档而非静默清空；同名覆盖会显式提示。"""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or _registry_path())
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            try:
                self.path.replace(self.path.with_suffix(".corrupt.json"))
            except Exception:
                pass
            return
        if isinstance(loaded, dict):
            self._data = loaded

    def _save(self) -> None:
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

    def register(self, name: str, source: str, base_url: str = "", ops: Optional[list] = None) -> dict:
        """同步封装（供脚本使用）。"""
        return asyncio.run(self.register_async(name, source, base_url, ops))

    async def register_async(
        self, name: str, source: str, base_url: str = "", ops: Optional[list] = None
    ) -> dict:
        spec = await load_spec_async(source)
        if ops is None:
            ops = extract_operations(spec)
        if not base_url:
            base_url = get_base_url(spec)
        overwrote = name in self._data
        self._data[name] = {
            "name": name,
            "source": source,
            "base_url": base_url,
            "auth_schemes": detect_auth(spec),
            "operations": ops,
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()
        return {"name": name, "operations": len(ops), "overwrote_existing": overwrote}

    def get(self, name: str) -> Optional[dict]:
        return self._data.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._data.keys())

    def unregister(self, name: str) -> bool:
        removed = self._data.pop(name, None) is not None
        if removed:
            self._save()
        return removed

    async def call_async(self, name: str, operation_id: str, params: dict) -> dict:
        entry = self.get(name)
        if not entry:
            return {"error": f"未找到已注册 API {name!r}。请先 register_api_from_spec。已注册：{self.list_names()}"}
        op = next((o for o in entry["operations"] if o["operation_id"] == operation_id), None)
        if not op:
            avail = [o["operation_id"] for o in entry["operations"]][:20]
            return {"error": f"未找到 operation {operation_id!r}。可用（前 20）：{avail}"}

        kwargs = dict(params or {})
        body = kwargs.pop("__body__", None)
        if body is not None:
            kwargs["__body__"] = body
        res = await _call_op_async(entry["base_url"], op, kwargs)
        metering.get_meter().record(
            name,
            operation_id,
            ok=bool(res.get("ok")),
            status_code=res.get("status_code"),
            latency_ms=res.get("latency_ms"),
        )
        res["metered"] = True
        return res

    def call(self, name: str, operation_id: str, params: dict) -> dict:
        return asyncio.run(self.call_async(name, operation_id, params))


def health_check() -> dict:
    """健康检查：返回 ok 即代表服务在线可调用（live 证据）。"""
    return {
        "status": "ok",
        "service": "MCPForge",
        "version": VERSION,
        "registered_apis": _registry.list_names(),
        "counters": {
            "registered_apis": len(_registry.list_names()),
            "metered_calls": metering.get_meter().report().get("total_calls_all_apis", 0),
        },
        "time": datetime.now(timezone.utc).isoformat(),
    }


# 全局单例
_registry = Registry()
