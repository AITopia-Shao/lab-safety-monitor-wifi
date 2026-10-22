"""按 DirectShow 精确设备名定位物理全景相机，只接受真实帧回调。"""
def select_laptop_camera(preferred='Web Camera', devices=None):
    if devices is None:
        import comtypes
        comtypes.CoInitialize()
        try:
            from pygrabber.dshow_graph import FilterGraph
            graph = FilterGraph()
            devices = graph.get_input_devices()
            del graph
        finally:
            comtypes.CoUninitialize()
    matches = [(i, name) for i, name in enumerate(devices) if name.casefold() == preferred.casefold()]
    if len(matches) != 1:
        raise RuntimeError('未找到唯一的全景摄像头 '+preferred+'；可用设备：'+', '.join(devices))
    return matches[0]


class LaptopCapture:
    """只接受物理采集图的帧回调，杜绝超时读取返回的未初始化图像缓冲。"""
    def __init__(self, preferred='Web Camera', width=640, height=480):
        import time
        import threading
        import comtypes
        from pygrabber.dshow_graph import FilterGraph
        from comtypes.client import PumpEvents
        self._time, self._pump = time.monotonic, PumpEvents
        self._lock = threading.Lock()
        self._frame, self._received = None, 0.0
        self._width = width
        self._started, self._open = time.monotonic(), False
        comtypes.CoInitialize()
        self._com = comtypes
        self.graph = None
        try:
            self.graph = FilterGraph()
            index, self.name = select_laptop_camera(preferred, self.graph.get_input_devices())
            self.graph.add_video_input_device(index)
            device = self.graph.get_input_device()
            formats = device.get_formats()
            choices = [f for f in formats if f['width']==width and f['height']==height]
            chosen = next((f for f in choices if f['media_type_str']=='YUY2'), next(iter(choices), None))
            if chosen: device.set_format(chosen['index'])
            self.graph.add_sample_grabber(self._arrived)
            self.graph.add_null_render()
            self.graph.prepare_preview_graph()
            self.graph.run()
            self._open = True
            self.graph.grab_frame()
        except Exception:
            self.release()
            raise

    def _arrived(self, frame):
        import cv2
        if frame.shape[1] > getattr(self, '_width', frame.shape[1]):
            width = self._width
            frame = cv2.resize(frame, (width, round(frame.shape[0]*width/frame.shape[1])))
        with self._lock:
            self._frame, self._received = frame.copy(), self._time()

    def isOpened(self):
        return self._open and self._time()-max(self._started,self._received) < 5

    def read(self):
        if not self._open: return False, None
        self.graph.grab_frame()
        self._pump(.002)
        with self._lock:
            if self._frame is None or self._time()-self._received > 2.5: return False, None
            return True, self._frame.copy()

    def release(self):
        self._open = False
        if self.graph:
            try: self.graph.stop(); self.graph.remove_filters()
            except Exception: pass
            self.graph = None
        if self._com:
            self._com.CoUninitialize()
            self._com = None

    def get(self, *args): return 0
    def set(self, *args): return False
