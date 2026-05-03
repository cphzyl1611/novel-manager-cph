from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch novel_repo_manager desktop GUI.")
    parser.parse_args()
    try:
        from novel_manager.gui.app import run
    except ImportError as exc:
        print(f"PySide6 is required to launch the GUI: {exc}")
        print("Install dependencies with: python -m pip install -r requirements.txt")
        return 1
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
