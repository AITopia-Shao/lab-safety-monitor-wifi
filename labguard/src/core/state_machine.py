"""纯视觉事件等级汇总；安全逻辑独立于电脑和手机界面。"""
try:
    from PySide6.QtCore import QObject, Signal
except ImportError:
    from PyQt6.QtCore import QObject, pyqtSignal as Signal
from src.core.events import LEVEL_RANK


class SafetyStateMachine(QObject):
    alert_triggered = Signal(dict)
    state_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_state = 'NORMAL'

    def evaluate(self, active_events):
        level = max((LEVEL_RANK.get(e.get('level'), 0) for e in active_events), default=0)
        state = 'WARNING' if level >= 2 else ('NOTICE' if level else 'NORMAL')
        if state != self.current_state:
            self.current_state = state
            self.state_changed.emit(state)
            if state != 'NORMAL':
                self.alert_triggered.emit({'level': state, 'title': '视觉监测提醒'})
        return state
