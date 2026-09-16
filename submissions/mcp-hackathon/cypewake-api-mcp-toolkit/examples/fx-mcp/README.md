# fx-mcp · MCP Server（由 MCPForge 生成）

源 API：`https://api.exchangerate-api.com/v4`

工具数：1

该 API 无需鉴权。

## 运行

```bash
pip install -r requirements.txt
# stdio 调试
fastmcp dev server.py
# 暴露为 HTTP 服务
fastmcp run server.py --transport streamable-http --port 8080
```

## 工具清单

- `get__latest__base_currency` — [GET] /latest/{base_currency}（Returns latest exchange rates in parameter-supplied base currency.）
