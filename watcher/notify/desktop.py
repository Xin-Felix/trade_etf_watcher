"""桌面通知 — macOS 原生 UserNotifications 框架 + 点击跳转对应标的."""
from __future__ import annotations

import sys
import uuid

from PySide6.QtCore import QObject, Signal as QtSignal
from PySide6.QtWidgets import QSystemTrayIcon

from watcher.config import Config
from watcher.models import Signal

# 通知呈现选项（原始值，避免不同 pyobjc 版本常量名不一致）
_PRESENT_SOUND = 1 << 1     # UNNotificationPresentationOptionSound
_PRESENT_LIST = 1 << 3      # ...OptionList
_PRESENT_BANNER = 1 << 4    # ...OptionBanner
_PRESENT_ALL = _PRESENT_SOUND | _PRESENT_LIST | _PRESENT_BANNER


def _build_delegate(on_click):
    """构造 UNUserNotificationCenterDelegate（点击通知回调 on_click(code, name)）.

    失败返回 None（未装 pyobjc / 非 macOS），调用方自行降级。
    """
    try:
        import objc
        from Foundation import NSObject
    except ImportError:
        return None

    class _NotifDelegate(NSObject):
        def initWithCallback_(self, cb):
            self = objc.super(_NotifDelegate, self).init()
            if self is None:
                return None
            self._cb = cb
            return self

        # 应用在前台时也弹横幅（否则系统默认静默塞进通知中心）
        def userNotificationCenter_willPresentNotification_withCompletionHandler_(
            self, center, notification, handler
        ):
            handler(_PRESENT_ALL)

        # 用户点击通知
        def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
            self, center, response, handler
        ):
            try:
                info = response.notification().request().content().userInfo()
                code = str(info.objectForKey_("code") or "") if info else ""
                name = str(info.objectForKey_("name") or "") if info else ""
                if code and self._cb:
                    self._cb(code, name)
            except Exception:  # noqa: BLE001
                pass
            finally:
                handler()

    try:
        return _NotifDelegate.alloc().initWithCallback_(on_click)
    except Exception:  # noqa: BLE001
        return None


class Notifier(QObject):
    """通知器：macOS 系统通知（可点击跳转）+ 托盘通知 + 应用内弹窗信号."""

    signal_received = QtSignal(Signal)
    # 用户点击通知 → (标的代码, 名称)，主窗口据此跳到对应 K 线图
    notification_clicked = QtSignal(str, str)

    def __init__(self, tray: QSystemTrayIcon | None, cfg: Config):
        super().__init__()
        self.tray = tray
        self.cfg = cfg
        self._center = None
        self._delegate = None            # 必须持有引用，否则会被 GC 掉
        self._last: tuple[str, str] = ("", "")   # 托盘通知点击时的兜底目标
        self._setup_notification_center()
        if tray is not None:
            # 托盘气泡通知的点击（osascript / 非 macOS 降级路径也能跳转）
            tray.messageClicked.connect(self._on_tray_message_clicked)

    def _setup_notification_center(self) -> None:
        """初始化 macOS UserNotifications：请求权限 + 注册点击代理."""
        if sys.platform != "darwin":
            return
        try:
            from UserNotifications import UNUserNotificationCenter

            center = UNUserNotificationCenter.currentNotificationCenter()
            # Alert(4) | Sound(2) | Badge(1)，用原始值避免常量名差异
            center.requestAuthorizationWithOptions_completionHandler_(
                4 | 2 | 1, lambda granted, error: None
            )
            delegate = _build_delegate(self._emit_clicked)
            if delegate is not None:
                center.setDelegate_(delegate)
                self._delegate = delegate
            self._center = center
        except Exception:  # noqa: BLE001
            self._center = None

    def _emit_clicked(self, code: str, name: str) -> None:
        """通知代理回调（Cocoa 主线程 = Qt 主线程，可直接 emit）."""
        self.notification_clicked.emit(code, name)

    def _on_tray_message_clicked(self) -> None:
        code, name = self._last
        if code:
            self.notification_clicked.emit(code, name)


    def notify(self, signal: Signal) -> None:
        """发送系统级通知（Banner 样式，点击可跳到对应标的 K 线）."""
        self._last = (signal.code, signal.name)
        if sys.platform == "darwin" and self._center:
            self._send_user_notification(signal)
        else:
            self._tray_notify(signal)
        # 同时发信号，让主窗口弹应用内浮窗
        self.signal_received.emit(signal)

    def _send_user_notification(self, signal: Signal) -> None:
        """通过 UserNotifications 框架发送系统通知（userInfo 带标的代码）."""
        try:
            from UserNotifications import (
                UNMutableNotificationContent,
                UNNotificationRequest,
                UNNotificationSound,
                UNTimeIntervalNotificationTrigger,
            )

            content = UNMutableNotificationContent.alloc().init()
            content.setTitle_(f"{signal.label} · {signal.name}")
            content.setBody_(signal.detail or "")
            content.setSound_(UNNotificationSound.defaultSound())
            # 点击通知时用它定位标的
            content.setUserInfo_({"code": signal.code, "name": signal.name})

            trigger = UNTimeIntervalNotificationTrigger.triggerWithTimeInterval_repeats_(
                1.0, False
            )
            request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
                str(uuid.uuid4()), content, trigger
            )
            self._center.addNotificationRequest_withCompletionHandler_(
                request, lambda error: None
            )
        except Exception:  # noqa: BLE001
            self._osascript_notify(signal)

    def _osascript_notify(self, signal: Signal) -> None:
        """osascript 兜底（不支持点击回调，同时补一条托盘通知以便点击跳转）."""
        import subprocess

        title = f"{signal.label} · {signal.name}"
        script = (
            f'display notification "{self._escape_applescript(signal.detail or "")}" '
            f'with title "{self._escape_applescript(title)}" '
            f'sound name "default"'
        )
        try:
            subprocess.Popen(
                ["osascript", "-e", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._tray_notify(signal)


    def _tray_notify(self, signal: Signal) -> None:
        if not self.tray:
            return
        icon = QSystemTrayIcon.Information
        if signal.level == "warning":
            icon = QSystemTrayIcon.Warning
        elif signal.level == "critical":
            icon = QSystemTrayIcon.Critical
        self.tray.showMessage(
            f"{signal.label} · {signal.name}",
            signal.detail,
            icon,
            10000,
        )

    @staticmethod
    def _escape_applescript(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
