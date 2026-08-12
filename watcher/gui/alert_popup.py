"""预警弹窗."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal as QtSignal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from watcher.models import Signal


class AlertPopup(QWidget):
    # 用户想查看该标的 K 线 → (代码, 名称)
    jump_requested = QtSignal(str, str)

    def __init__(self, signal: Signal, parent=None):
        super().__init__(parent)
        self.signal = signal
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowStaysOnTopHint
            | Qt.FramelessWindowHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setMinimumSize(360, 160)

        self._build_ui()
        self._auto_close()

    def _build_ui(self) -> None:
        container = QWidget(self)
        container.setObjectName("alertContainer")
        container.setStyleSheet(
            """
            #alertContainer {
                background-color: #2d2d2d;
                border-radius: 10px;
                border: 2px solid #ff9800;
            }
            QLabel { color: #ffffff; }
            QLabel#title { font-size: 16px; font-weight: bold; color: #ff9800; }
            QLabel#detail { font-size: 13px; color: #eeeeee; }
            QPushButton {
                background-color: #ff9800;
                color: #1a1a1a;
                border: none;
                border-radius: 5px;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #ffb74d; }
            """
        )

        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel(f"{self.signal.label} · {self.signal.name}")
        title.setObjectName("title")
        layout.addWidget(title)

        detail = QLabel(self.signal.detail)
        detail.setObjectName("detail")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        view_btn = QPushButton("查看 K 线")
        view_btn.clicked.connect(self._on_view)
        btn_layout.addWidget(view_btn)

        ack_btn = QPushButton("知道了")
        ack_btn.setStyleSheet(
            "background-color: #3a3a3a; color: #ddd;"
        )
        ack_btn.clicked.connect(self.close)
        btn_layout.addWidget(ack_btn)

        layout.addLayout(btn_layout)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(container)

        self._position()

    def _position(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 20, screen.bottom() - self.height() - 60)

    def _auto_close(self) -> None:
        if self.signal.level != "critical":
            QTimer.singleShot(60000, self.close)

    def _on_view(self) -> None:
        self.jump_requested.emit(self.signal.code, self.signal.name)
        self.close()

    def mousePressEvent(self, event) -> None:
        """点弹窗任意位置也跳转（跟系统通知行为一致）."""
        self.jump_requested.emit(self.signal.code, self.signal.name)
        self.close()
