#!/usr/bin/env python
"""NovelHub dual-end server entry point.

Usage:
    python server.py --repo "D:/NovelRepo_Test"
    python server.py --repo "D:/NovelRepo_Test" --host 0.0.0.0 --port 8765
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from novel_manager.server.config import DEFAULT_HOST, DEFAULT_PORT


def main():
    parser = argparse.ArgumentParser(description="NovelHub server")
    parser.add_argument("--repo", required=True, help="小说仓库根目录")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"监听地址 (默认: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"端口 (默认: {DEFAULT_PORT})")
    args = parser.parse_args()

    repo = str(Path(args.repo).expanduser().resolve())
    if not Path(repo).exists():
        print(f"仓库路径不存在: {repo}")
        sys.exit(1)

    if args.host == "0.0.0.0":
        print("=" * 60)
        print(" 当前服务已开放到局域网，请确认网络可信。")
        print(f" 手机访问: http://<电脑IP>:{args.port}")
        print("=" * 60)

    print(f"NovelHub server starting on http://{args.host}:{args.port}")
    print(f"Repo: {repo}")

    from novel_manager.server.app import create_app

    app = create_app(repo_path=repo)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
