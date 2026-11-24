#!/usr/bin/env python
"""启动 Web API：python run_api.py --port 8000"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="小美电商导购 Agent API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    parser.add_argument("--offline", action="store_true", help="强制离线规则引擎")
    args = parser.parse_args()
    if args.offline:
        os.environ["LLM_MODE"] = "offline"
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    import uvicorn

    print("小美 Agent: http://%s:%s" % (args.host, args.port))
    print("API 文档:   http://%s:%s/docs" % (args.host, args.port))
    uvicorn.run(
        "shopagent.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
