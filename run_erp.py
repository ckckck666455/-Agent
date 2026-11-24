#!/usr/bin/env python
"""启动 Mock ERP：python run_erp.py --port 8100"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock ERP/OMS for Xiaomei Agent")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    import uvicorn

    print("Mock ERP: http://%s:%s/erp/health" % (args.host, args.port))
    uvicorn.run("shopagent.mock_erp:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
