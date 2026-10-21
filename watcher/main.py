"""ETF Watcher 启动入口."""
from __future__ import annotations

import sys
import os


def _redirect_output():
    """打包环境下将 stdout/stderr 重定向到日志文件（macOS .app 无终端）."""
    if getattr(sys, "frozen", False):
        import platformdirs
        from pathlib import Path
        log_dir = Path(platformdirs.user_data_dir("ETFWatcher"))
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "app.log"
        # 保留最近的日志（截断到 1MB）
        try:
            if log_path.exists() and log_path.stat().st_size > 1_000_000:
                log_path.write_text("")
        except OSError:
            pass
        f = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = f
        sys.stderr = f
        print(f"\n{'='*60}")
        print(f"日进斗金 启动 (frozen={getattr(sys, 'frozen', False)})")
        print(f"sys._MEIPASS = {getattr(sys, '_MEIPASS', 'N/A')}")
        print(f"cwd = {os.getcwd()}")
        print(f"{'='*60}")


_redirect_output()

from watcher.gui.app import run_app


def main() -> int:
    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
