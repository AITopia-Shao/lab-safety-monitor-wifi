"""有时效与会话隔离的手机最新帧；断线后不沿用旧画面做判断。"""
import io
import secrets
import threading
import time
from collections import deque
import cv2
import numpy as np
from PIL import Image
from src.config import cfg


class PhoneFrameBuffer:
    def __init__(self):
        self._lock = threading.Lock()
        self.session = None
        self.frame = None
        self.received_at = 0.0
        self.sequence = -1
        self.count = 0
        self.device = ''
        self.camera_id = ''
        self._arrivals = deque()

    def start(self, device, camera_id=''):
        with self._lock:
            if self.session and time.monotonic()-self.received_at < float(cfg('phone.stale_seconds', 2.5)):
                raise RuntimeError('台面接收会话尚未结束，请先停止原连接')
            self.session = secrets.token_urlsafe(24)
            self.frame = None
            self.sequence = -1
            self.received_at = 0
            self.device = str(device)[:80]
            self.camera_id = str(camera_id)[:32]
            self._arrivals.clear()
            return self.session

    def put_jpeg(self, data, session, sequence, rotation=0):
        if len(data) > int(cfg('phone.max_jpeg_bytes', 1500000)) or rotation not in (0, 90, 180, 270):
            raise ValueError('图片大小或旋转角度无效')
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format != 'JPEG' or image.width*image.height > 2560*1920:
                    raise ValueError('仅接受有限分辨率的 JPEG')
            frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception as error:
            raise ValueError('无法读取 JPEG') from error
        if frame is None:
            raise ValueError('无法读取 JPEG')
        if rotation:
            frame = cv2.rotate(frame, {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                                      270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rotation])
        with self._lock:
            if not self.session or not secrets.compare_digest(session, self.session):
                raise PermissionError('手机会话已结束')
            if sequence <= self.sequence:
                return False
            self.frame, self.sequence, self.received_at = frame, sequence, time.monotonic()
            self.count += 1
            self._arrivals.append((self.received_at, len(data)))
            self._trim(self.received_at)
            return True

    def _trim(self, now):
        while self._arrivals and now-self._arrivals[0][0] > 3:
            self._arrivals.popleft()

    def read(self):
        with self._lock:
            fresh = self.frame is not None and time.monotonic()-self.received_at <= float(cfg('phone.stale_seconds', 2.5))
            return (True, self.frame.copy()) if fresh else (False, None)

    def stop(self, session):
        with self._lock:
            if self.session and secrets.compare_digest(session, self.session):
                self.session, self.frame = None, None

    def status(self):
        with self._lock:
            now = time.monotonic()
            age = now-self.received_at
            self._trim(now)
            elapsed = now-self._arrivals[0][0] if self._arrivals else 0
            live = self.session is not None and self.frame is not None and age <= float(cfg('phone.stale_seconds', 2.5))
            fps = (len(self._arrivals)-1)/elapsed if live and elapsed > .1 else 0
            mbps = sum(size for _, size in list(self._arrivals)[1:])*8/elapsed/1e6 if live and elapsed > .1 else 0
            return {'connected': live,
                    'device': self.device, 'age_s': round(age, 1) if self.received_at else None,
                    'frames_received': self.count, 'received_fps': round(fps, 1), 'received_mbps': round(mbps, 2),
                    'target_fps': int(cfg('phone.target_fps', 24)), 'camera_id': self.camera_id,
                    'role': 'rear-main'}


phone_frames = PhoneFrameBuffer()


class PhoneCapture:
    def __init__(self): self.open = True
    def isOpened(self): return self.open
    def read(self): return phone_frames.read() if self.open else (False, None)
    def release(self): self.open = False
    def set(self, *args): return False
    def get(self, *args): return 0
