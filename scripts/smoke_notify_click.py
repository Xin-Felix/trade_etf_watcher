"""冒烟测试：发一条真实系统通知，验证点击后能回调出标的代码.

运行后点屏幕右上角弹出的通知，终端应打印 "点击回调: sz159952 ..."。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from watcher.config import Config
from watcher.models import Signal
from watcher.notify.desktop import Notifier


def main() -> None:
    app = QApplication(sys.argv)
    cfg = Config.load()
    notifier = Notifier(None, cfg)

    print("通知中心可用:", notifier._center is not None)
    print("点击代理已注册:", notifier._delegate is not None)

    notifier.notification_clicked.connect(
        lambda code, name: print(f"✅ 点击回调: {code} {name}")
    )

    sig = Signal(
        key="test",
        code="sz159952",
        name="创业板ETF易方达",
        label="买认购",
        detail="探底回升 — 点这条通知应跳转到该 ETF 的 K 线图",
        level="warning",
        ts="",
    )
    notifier.notify(sig)
    print("\n已发送通知，请点击它（20 秒后自动退出）...")

    QTimer.singleShot(20000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
