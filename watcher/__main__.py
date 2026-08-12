"""命令行入口（兼容 python -m watcher）."""
from watcher.main import main

if __name__ == "__main__":
    raise SystemExit(main())
