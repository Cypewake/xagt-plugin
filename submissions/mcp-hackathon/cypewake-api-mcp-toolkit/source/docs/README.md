# docs/ · 复核材料

这个目录只放**给复核者用的东西**，不是产品文档（产品说明在仓库根的 `README.md`，
交付全过程与已知限制在 `OVERVIEW.md`）。

---

## 一条命令复核在线提交

```bash
pip install "fastmcp>=4.0,<5.0"
python docs/judge_check.py
```

脚本会依次核对 11 项硬指标（下表为关键核对项，另含 §6 生成/注册实调），全部通过时退出码为 0：

| # | 核对项 | 对应的提交要求 |
|---|---|---|
| 1 | `GET /api/health` 返回 `status=ok` | live 证据 |
| 2 | `GET /` 返回完整的四阶段走查页 | 可视化 demo |
| 3 | `GET /api/config` 可读到计价档位 | MONETIZE 有真实定价口径 |
| 4 | MCP 端点能列出工具 | 是**真 MCP 服务**，不是 HTTP 外壳 |
| 5 | 交付规格点名的 7 个工具名称齐全 | 资格检查 |
| 6 | `health_check` 可调用 | live 证据 |
| 7 | `parse_openapi_spec` 能解析本地 Petstore 风格规格 | BUILD |
| 8 | `list_operations` 输出可读操作清单 | BUILD |
| 9 | `call_rest_api` 真实出网（GitHub 公共 REST API /zen） | online-callable capability |

指向其它实例：

```bash
python docs/judge_check.py --url http://127.0.0.1:8000
```

---

## 复核时值得特别看一眼的两处

**一、VERIFY 的判定口径是不是真的。**
很多同类作品的「验证通过」是「有 HTTP 响应就算可达」，于是 404 / 500 也全绿、指标恒为真。
本项目的口径写在 `core.classify_response()`：**只有 2xx 记为 passed**，
401/403 记为需鉴权，404 / 429 / 其它 4xx / 5xx / 网络失败分别归类。
`verify.py` 里有一条离线断言专门守住这条线。

**二、SSRF 防护有没有被重定向绕过。**
`httpx` 的 `follow_redirects=True` 只在初始 URL 上校验一次，
一个**公网**地址 302 到 `127.0.0.1` 或 `169.254.169.254` 就能整体绕过。
这个洞我们实测复现过，修法是 `core.request_with_validated_redirects()`（逐跳校验），
回归用例在 `tests/test_core.py::test_redirect_to_internal_target_is_blocked` 等 4 条。
想自己验一遍：

```bash
pytest tests/test_core.py -q -k redirect
```

---

## 本地完整复现

```bash
pip install -r requirements-dev.txt

pytest                    # 53 项离线用例（确定性，不联网）
pytest -m live -v         # 6 项在线用例（真实调用公开 API）
python verify.py          # 双层验收，产出 verification-evidence.md

python app.py             # 本地起服务，访问 http://localhost:8000
```
