"""系统托盘."""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QCursor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from watcher.config import Config
from watcher.watcher_loop import WatcherLoop


def _default_icon() -> QIcon:
    """生成一个默认的托盘图标（红色圆角方块 + 金 字）."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    from PySide6.QtGui import QColor
    painter.setBrush(QColor(220, 40, 40))  # 红色
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(4, 4, size - 8, size - 8, 12, 12)
    painter.setPen(QColor(255, 215, 0))  # 金色字
    font = painter.font()
    font.setBold(True)
    font.setPointSize(26)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "金")
    painter.end()
    return QIcon(pixmap)


class TrayManager(QSystemTrayIcon):
    def __init__(self, cfg: Config, watcher: WatcherLoop, main_window=None):
        super().__init__()
        self.cfg = cfg
        self.watcher = watcher
        self.main_window = main_window
        self._menu = None

        self.setToolTip(cfg.app.name)
        self.setIcon(_default_icon())

        self.activated.connect(self._on_activated)
        self._build_menu()

    def _build_menu(self) -> None:
        menu = QMenu()

        show_action = QAction("打开主窗口", self)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)

        pause_action = QAction("暂停", self)
        pause_action.setCheckable(True)
        pause_action.triggered.connect(self._toggle_pause)
        menu.addAction(pause_action)
        self._pause_action = pause_action

        test_action = QAction("测试预警", self)
        test_action.triggered.connect(self._test_alert)
        menu.addAction(test_action)

        menu.addSeparator()

        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self._menu = menu

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._show_window()
        elif reason == QSystemTrayIcon.Context:
            # 手动弹出菜单，绕过 Qt 在 macOS 上的自动弹出崩溃
            if self._menu:
                self._menu.popup(QCursor.pos())

    def _show_window(self) -> None:
        if self.main_window:
            self.main_window.showNormal()
            self.main_window.raise_()
            self.main_window.activateWindow()

    def _toggle_pause(self, checked: bool) -> None:
        if checked:
            self.watcher.pause()
            self._pause_action.setText("继续")
            self.setToolTip(f"{self.cfg.app.name} [已暂停]")
        else:
            self.watcher.resume()
            self._pause_action.setText("暂停")
            self.setToolTip(self.cfg.app.name)

    def _test_alert(self) -> None:
        from watcher.models import Signal
        from watcher.calendar import ts_now

        sig = Signal(
            key="test",
            code="sh510300",
            name="沪深300ETF",
            label="测试预警",
            detail="这是一条测试预警，用于验证弹窗和通知是否正常工作。",
            level="warning",
            ts=ts_now(),
        )
        self.watcher.signals.signals_fired.emit([sig])

    def _quit(self) -> None:
        from PySide6.QtWidgets import QApplication

        # 清理统一由 app.aboutToQuit -> watcher.stop() 处理
        QApplication.quit()
