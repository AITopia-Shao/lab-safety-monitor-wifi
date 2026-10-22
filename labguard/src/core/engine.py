"""纯视觉安全引擎；沿用上游的线程、事件和统一快照接口。"""
import copy
import threading
import time
import cv2
import numpy as np
try:
    from PySide6.QtCore import QObject, QThread, Signal, QTimer, Qt
except ImportError:
    from PyQt6.QtCore import QObject, QThread, pyqtSignal as Signal, QTimer, Qt
from src.config import cfg, resolve_path
from src.core.events import events
from src.core.state_machine import SafetyStateMachine
from src.mobile.frame_buffer import phone_frames
from src.mobile.droidcam import droidcam
from LabSafetyMonitor.dual_inference import DualInferenceSystem

PPE_ITEMS = [('ppe_goggles', '护目镜'), ('ppe_coat', '实验服'), ('ppe_gloves', '手套'), ('ppe_mask', '口罩')]


class InferenceThread(QThread):
    update_frames_signal = Signal(np.ndarray, np.ndarray, dict, list, int, int, str)

    def __init__(self):
        super().__init__()
        self.running = False
        self.dual_system = DualInferenceSystem()

    def run(self):
        self.running = True
        self.dual_system.start()
        while self.running:
            result = self.dual_system.get_results()
            if result is not None: self.update_frames_signal.emit(*result)
            self.msleep(20)

    def stop(self):
        self.running = False
        self.dual_system.stop()
        self.wait(5000)


class SafetyEngine(QObject):
    frames_ready = Signal(object, object, dict, list, int, int, str, str)
    preview_ready = Signal(object, object)
    alert = Signal(dict)
    command = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.started_at = time.time()
        self.inference_thread = InferenceThread()
        self.dual_system = self.inference_thread.dual_system
        self.state_machine = SafetyStateMachine(self)
        self.state_machine.alert_triggered.connect(self.alert.emit)
        self.latest_alarms, self.latest_violations = {}, []
        self.latest_chem_items, self.latest_unattended = [], False
        self.progress, self.fps_text = (0, 0), ''
        self.media_label = '外置 USB 摄像头 + DroidCam Wi-Fi'
        self._lock = threading.RLock()
        self._frames, self._frame_seq, self._jpeg_cache = (None, None), 0, {}
        self._snapshot, self._last_result, self._started = {}, 0.0, False
        self.inference_thread.update_frames_signal.connect(self._on_frames)
        self.command.connect(self._command)
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._evaluate)
        self._evaluate()
        self._preview_tick = QTimer(self)
        self._preview_tick.setTimerType(Qt.TimerType.PreciseTimer)
        self._preview_tick.timeout.connect(self._refresh_preview)

    def start(self):
        if self._started: return
        self._started = True
        droidcam.start()
        self.inference_thread.start()
        self._tick.start(500)
        self._preview_tick.start(int(1000/float(cfg('phone.target_fps', 24))))

    def stop(self):
        self._tick.stop()
        self._preview_tick.stop()
        droidcam.stop()
        if self._started: self.inference_thread.stop()
        self._started = False

    def _on_frames(self, pano, desk, alarms, violations, curr_f, tot_f, log_str):
        self.latest_alarms, self.latest_violations = dict(alarms), list(violations)
        self.latest_chem_items = list(alarms.get('chem_items', []))
        self.latest_unattended = alarms.get('unattended', False)
        self.progress, self._last_result = (curr_f, tot_f), time.monotonic()
        self.fps_text = next((x.replace('[系统] ', '').split('|')[0].strip()
                              for x in log_str.splitlines() if x.startswith('[系统]')), '')
        with self._lock:
            self._frames, self._frame_seq = (pano, desk), self._frame_seq+1
        self._evaluate()
        self.frames_ready.emit(pano, desk, alarms, violations, curr_f, tot_f, log_str, self.state_machine.current_state)

    def _evaluate(self):
        a = self.latest_alarms
        stale = self._last_result > 0 and time.monotonic()-self._last_result > 5
        events.update('vision_stale', stale, 'WARNING', '识别画面中断', '请检查摄像头和识别进程', snapshot=False)
        if self._last_result:
            events.update('pano_offline', not a.get('pano_valid', False), 'WARNING', '全景画面未接入', '无法判断人员是否在场', snapshot=False)
            events.update('desk_offline', not a.get('desk_valid', False), 'NOTICE', '台面画面未接入', '请连接手机热点，在小屏接入 DroidCam', snapshot=False)
        self.state_machine.evaluate(events.active_events())
        ppe = []
        for kind, name in PPE_ITEMS:
            # 未检测到违规不代表确认合格；佩戴证据不足显示“待确认”。
            observed = a.get('ppe_observed', {})
            status = 'bad' if events.is_active(kind) else ('ok' if observed.get(kind) else 'unknown')
            if a.get('person_present') is not True or stale: status = 'unknown'
            ppe.append({'kind': kind, 'name': name, 'status': status})
        state = self.state_machine.current_state
        snap = {'ts': time.time(), 'uptime_s': round(time.time()-self.started_at), 'state': state,
                'state_text': {'NORMAL': '正常守护', 'NOTICE': '请关注', 'WARNING': '需要处理'}.get(state, '请关注'),
                'vision': {'ok': a.get('vision_ok', False) and not stale,
                           'person_present': None if stale else a.get('person_present'),
                           'unattended': False if stale else a.get('unattended', False),
                           'pano_valid': a.get('pano_valid', False) and not stale,
                           'desk_valid': a.get('desk_valid', False) and not stale,
                           'chem_items': [] if stale else self.latest_chem_items,
                           'violations': [] if stale else self.latest_violations,
                           'fps': self.fps_text, 'ppe': ppe, 'progress': list(self.progress), 'media': self.media_label,
                           'sources': {'pano': self.dual_system.media_source1, 'desk': self.dual_system.media_source2},
                           'pano_device': getattr(self.dual_system, 'laptop_camera_name', '')},
                'phone': droidcam.status(), 'active_events': events.active_events(),
                'stats': events.stats(), 'mute_until': events.mute_until}
        with self._lock: self._snapshot = snap

    def snapshot(self):
        with self._lock: return copy.deepcopy(self._snapshot)

    def latest_frames(self):
        with self._lock: return self._frames

    def live_frames(self):
        pano, desk = self.dual_system.preview_frames()
        # 手机上传不被笔记本采集线程或模型耗时限制；只读取最新有效手机帧。
        if self.dual_system.media_source2 == 'droidcam://camera':
            ok, phone = phone_frames.read()
            if ok: desk = phone
            elif desk is not None: desk = np.zeros_like(desk)
        return pano, desk

    def _refresh_preview(self):
        if self.dual_system.media_source2 == 'droidcam://camera':
            pano, desk = self.live_frames()
            if pano is not None and desk is not None: self.preview_ready.emit(pano, desk)

    def live_jpeg(self, which='pano'):
        frame = self.live_frames()[0 if which == 'pano' else 1]
        if frame is None: return None
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        return encoded.tobytes() if ok else None

    @property
    def frame_seq(self):
        with self._lock: return self._frame_seq

    def latest_jpeg(self, which='pano', width=None, quality=75):
        width = int(width or cfg('web.stream_width', 640))
        key = (which, width, quality)
        with self._lock:
            seq, frame, cached = self._frame_seq, self._frames[0 if which == 'pano' else 1], self._jpeg_cache.get(key)
        if frame is None: return None
        if cached and cached[0] == seq: return cached[1]
        if frame.shape[1] > width: frame = cv2.resize(frame, (width, round(frame.shape[0]*width/frame.shape[1])))
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok: return None
        data = encoded.tobytes()
        with self._lock: self._jpeg_cache[key] = (seq, data)
        return data

    def activate_phone(self): self.command.emit('phone', None)
    def mute(self, seconds=60): self.command.emit('mute', None)
    def call_admin(self, who='实验员'): self.command.emit('call_admin', None)

    def _command(self, name, value):
        if name == 'phone':
            if self.dual_system.media_source1 != 0 or self.dual_system.media_source2 != 'droidcam://camera':
                self.dual_system.load_media(src1=0, src2='droidcam://camera', force_reload=True)
            self.media_label = '外置 USB 摄像头 + DroidCam Wi-Fi'
        elif name == 'samples':
            self.dual_system.load_media(resolve_path('media/macro_sample.jpg'), resolve_path('media/micro_sample.jpg'))
            self.media_label = '真实样本回放（功能展示）'
        elif name == 'live':
            self.dual_system.load_media(src1=0, src2='droidcam://camera', force_reload=True)
            self.media_label = '外置 USB 摄像头 + DroidCam Wi-Fi'
        elif name == 'snapshot': events.log('手动抓拍', '记录当前双路画面', level='NOTICE', kind='manual', snapshot=True)
        elif name == 'mute':
            events.mute_until = time.time()+60
            events.log('提示音已静音', '60 秒后恢复；视觉提示和事件记录继续工作', kind='mute')
        elif name == 'call_admin': events.log('现场求助', '手机端在电脑主控屏留下求助记录，请联系现场工作人员', level='WARNING', kind='call_admin', snapshot=True)
