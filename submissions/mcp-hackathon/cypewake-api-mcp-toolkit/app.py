"""
app.py · MCPForge 部署入口（单端口 HTTP 服务）

云平台（以及本工作区的发布能力）通常注入 PORT 环境变量并要求绑定 0.0.0.0，
因此这里提供标准入口，与 demo_app.py 共用同一个 FastAPI 应用：

    /            可视化四阶段走查页
    /api/health  健康检查（live 证据）
    /mcp         MCP 服务端点（streamable-http）

本地运行：
    python app.py
生产运行：
    PORT=8000 python app.py
"""

from __future__ import annotations

import os

import uvicorn

from demo_app import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
