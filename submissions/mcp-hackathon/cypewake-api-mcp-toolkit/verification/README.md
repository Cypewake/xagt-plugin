# Verification evidence

复制本文件至 `submissions/mcp-hackathon/cypewake-api-mcp-toolkit/verification/README.md` 并替换占位符。

## Prerequisites

- Review commit: `<REVIEW_COMMIT>`
- API base URL: `<DEPLOY_URL>`
- Authentication: none

## 1. Health check

```bash
curl --fail --silent --show-error <DEPLOY_URL>/api/health
```

Expected response:

```json
{"status":"ok","commit":"<REVIEW_COMMIT>"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error <DEPLOY_URL>/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"cypewake-api-mcp-toolkit","commit":"<REVIEW_COMMIT>"}
```

## 3. Capability call

评审可本地 `uvicorn demo_app:app --port 8000` 后，用任意 MCP 客户端（或 `source/docs/judge_check.py`）复现真实能力调用：

- `call_rest_api`：`base_url=https://api.github.com`、`path=/zen` → HTTP 200
- `register(github_live)` + `call_registered_api(getZen)` → HTTP 200

完整可复现脚本见 `source/docs/judge_check.py`（本地稳定运行 **11/11 PASS**）。

预期成功响应：HTTP 200，body 含 GitHub zen 文案或仓库元数据。
预期安全失败：传入未注册 API 名 → 明确错误；传入内网 URL → 被 `assert_public_url` 拒绝（防 SSRF）。
