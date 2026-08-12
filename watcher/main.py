"""ETF Watcher 启动入口."""
from __future__ import annotations

from watcher.gui.app import run_app


def main() -> int:
    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
