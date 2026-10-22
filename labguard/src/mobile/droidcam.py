"""DroidCam 官方 MJPEG 接口接入；独立拉流、丢弃旧帧、会话隔离和断线失效。"""
import ipaddress
import re
import threading
import time
import urllib.request
from src.config import cfg, set_value
from src.mobile.frame_buffer import phone_frames


LAN_NETWORKS = [ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')]


def droidcam_url(host, port=4747, allow_loopback=False):
    try: address = ipaddress.IPv4Address(host)
    except (ValueError, ipaddress.AddressValueError): raise ValueError('请输入 DroidCam 显示的局域网 IPv4 地址')
    if not any(address in n for n in LAN_NETWORKS) and not (allow_loopback and address.is_loopback):
        raise ValueError('DroidCam 地址必须是手机热点或局域网地址')
    if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
        raise ValueError('DroidCam 端口应为 1024～65535')
    return f'http://{address}:{port}/video/640x480'


class MjpegDecoder:
    """按每个 part 的 Content-Length 分帧，支持任意 TCP 分片且限制内存占用。"""
    def __init__(self, max_jpeg=1500000):
        self.pending = bytearray()
        self.length = None
        self.max_jpeg = max_jpeg

    def feed(self, data):
        self.pending.extend(data)
        while True:
            if self.length is None:
                end = self.pending.find(b'\r\n\r\n')
                if end < 0:
                    if len(self.pending) > 16384: raise ValueError('DroidCam 视频帧头过大')
                    return
                header = bytes(self.pending[:end])
                match = re.search(br'(?im)^Content-Length:\s*(\d+)\s*$', header)
                if not match or b'image/jpeg' not in header.lower(): raise ValueError('DroidCam 未返回 JPEG 视频帧')
                self.length = int(match.group(1))
                if not 1 <= self.length <= self.max_jpeg: raise ValueError('DroidCam 视频帧大小无效')
                del self.pending[:end+4]
            if len(self.pending) < self.length: return
            jpeg = bytes(self.pending[:self.length])
            del self.pending[:self.length]
            self.length = None
            if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'): raise ValueError('DroidCam JPEG 不完整')
            yield jpeg


class DroidCamReceiver:
    def __init__(self, buffer=phone_frames, allow_loopback=False):
        self.buffer = buffer
        self.allow_loopback = allow_loopback
        self._lock = threading.RLock()
        self._lifecycle = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self._response = None
        self._host, self._port, self._rotation = '', 4747, 0
        self._enabled, self._error, self._session = False, '', None
        self._generation = 0

    def start(self):
        host = str(cfg('droidcam.host', '')).strip()
        if host and bool(cfg('droidcam.enabled', True)):
            self.connect(host, int(cfg('droidcam.port', 4747)), int(cfg('droidcam.rotation', 0)), persist=False)

    def connect(self, host, port=4747, rotation=0, persist=True):
        url = droidcam_url(host, port, self.allow_loopback)
        if rotation not in (0, 90, 180, 270): raise ValueError('旋转角应为 0/90/180/270')
        with self._lifecycle:
            with self._lock:
                same = self._enabled and (host, port, rotation) == (self._host, self._port, self._rotation)
            if same and self._thread and self._thread.is_alive(): return self.status()
            self._halt()
            with self._lock:
                self._host, self._port, self._rotation = host, port, rotation
                self._enabled, self._error = True, ''
                self._stop = threading.Event()
                self._generation += 1
                generation = self._generation
            if persist:
                for key, value in [('host',host),('port',port),('rotation',rotation),('enabled',True)]:
                    set_value('droidcam.'+key, value, persist=True)
            self._thread = threading.Thread(target=self._receive, args=(url, generation, self._stop), name='DroidCamWiFi', daemon=True)
            self._thread.start()
        return self.status()

    def _halt(self):
        self._stop.set()
        with self._lock:
            lease, self._session = self._session, None
            response = self._response
            self._enabled = False
        if lease: self.buffer.stop(lease)
        # read timeout 有限，避免阻塞界面等待断开的网络。
        if response:
            try:
                import socket
                response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
            except (AttributeError, OSError): pass
        if self._thread and self._thread is not threading.current_thread(): self._thread.join(3)
        self._thread = None

    def stop(self, persist=False):
        with self._lifecycle: self._halt()
        if persist: set_value('droidcam.enabled', False, persist=True)

    def status(self):
        status = self.buffer.status()
        with self._lock:
            return {**status, 'transport': 'DroidCam Wi-Fi', 'host': self._host, 'port': self._port,
                    'rotation': self._rotation, 'enabled': self._enabled, 'error': self._error}

    def _receive(self, url, generation, stop):
        # 局域网直连，不经系统 HTTP 代理。
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        retry = 1
        while not stop.is_set():
            lease = None
            try:
                request = urllib.request.Request(url, headers={'User-Agent':'LabGuard-DroidCam/2.0', 'Connection':'close'})
                with opener.open(request, timeout=2.0) as response:
                    if 'multipart/x-mixed-replace' not in response.headers.get('Content-Type','').lower():
                        raise ValueError('未找到 DroidCam 视频；请先打开手机上的 DroidCam')
                    with self._lock:
                        if stop.is_set() or generation != self._generation: return
                        self._response = response
                        lease = self.buffer.start('DroidCam Wi-Fi · '+self._host, 'rear-main')
                        self._session, self._error = lease, ''
                    decoder = MjpegDecoder(int(cfg('phone.max_jpeg_bytes',1500000)))
                    sequence, deadline = 0, 0.0
                    interval = 1/max(1, int(cfg('phone.target_fps',24)))
                    while not stop.is_set():
                        chunk = response.read1(65536)
                        if not chunk: raise OSError('DroidCam 视频已断开')
                        for jpeg in decoder.feed(chunk):
                            if stop.is_set() or generation != self._generation: return
                            now = time.monotonic()
                            if now < deadline: continue
                            deadline = now+interval if not deadline or now-deadline > 2*interval else deadline+interval
                            sequence += 1
                            self.buffer.put_jpeg(jpeg, lease, sequence, self._rotation)
                            retry = 1
            except Exception as error:
                if not stop.is_set():
                    with self._lock: self._error = 'DroidCam 连接中断，正在重连：'+str(error)[:180]
            finally:
                if lease: self.buffer.stop(lease)
                with self._lock:
                    if self._session == lease: self._session = None
                    self._response = None
            if stop.wait(retry): break
            retry = min(5, retry+1)


droidcam = DroidCamReceiver()
