from PySide6.QtCore import QObject, Signal

class SignalBus(QObject):
    """全局事件总线：用于跨组件发送状态与通知。"""
    # 状态栏通知
    status_message = Signal(str)
# 全局单例
bus = SignalBus()
