"""DroidCam 分帧边界、断线失效、重连及限速；HTTP 仿真仅验证协议。"""
from pathlib import Path
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import cv2
import numpy as np
from src.mobile.droidcam import MjpegDecoder, DroidCamReceiver, droidcam_url
from src.mobile.frame_buffer import PhoneFrameBuffer

JPEG=cv2.imencode('.jpg',np.full((60,80,3),80,np.uint8))[1].tobytes()
PART=b'--dcmjpeg\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(JPEG)).encode()+b'\r\n\r\n'+JPEG+b'\r\n'


class DecoderTests(unittest.TestCase):
    def test_arbitrary_network_boundaries(self):
        for size in [1,7,1024,len(PART)*3]:
            decoder=MjpegDecoder(); frames=[]; stream=PART*3
            for start in range(0,len(stream),size): frames.extend(decoder.feed(stream[start:start+size]))
            self.assertEqual(frames,[JPEG]*3)

    def test_rejects_unbounded_headers(self):
        with self.assertRaises(ValueError): list(MjpegDecoder().feed(b'x'*16385))

    def test_rejects_invalid_parts(self):
        for data in [b'Content-Length: 0\r\nContent-Type: image/jpeg\r\n\r\n',b'Content-Length: 2000000\r\nContent-Type: image/jpeg\r\n\r\n',b'Content-Type: text/html\r\n\r\n',b'Content-Length: 3\r\nContent-Type: image/jpeg\r\n\r\nbad']:
            with self.assertRaises(ValueError): list(MjpegDecoder().feed(data))

    def test_target_allowlist(self):
        for host in ['10.1.1.1','172.16.0.1','192.168.43.1']: self.assertIn(host,droidcam_url(host))
        for host in ['127.0.0.1','8.8.8.8','localhost','192.168.0.1/path','0.0.0.0']:
            with self.assertRaises(ValueError): droidcam_url(host)
        for port in [80,True,'4747',65536]:
            with self.assertRaises(ValueError): droidcam_url('10.1.1.1',port)


class FakeCamera(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args): pass
    def do_GET(self):
        self.server.paths.append(self.path)
        self.send_response(200); self.send_header('Content-Type','multipart/x-mixed-replace;boundary=--dcmjpeg'); self.end_headers()
        try:
            while not self.server.halt.is_set():
                if not self.server.available.is_set(): break
                self.wfile.write(PART); self.wfile.flush(); self.server.halt.wait(1/30)
        except (OSError,ConnectionError): pass
        self.close_connection=True


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(('127.0.0.1',0),FakeCamera)
        self.server.halt=threading.Event(); self.server.available=threading.Event(); self.server.available.set(); self.server.paths=[]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.buffer=PhoneFrameBuffer(); self.receiver=DroidCamReceiver(self.buffer,allow_loopback=True)
        self.receiver.connect('127.0.0.1',self.server.server_port,persist=False)

    def tearDown(self):
        self.receiver.stop(); self.server.halt.set(); self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def until(self,predicate,timeout=4):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if predicate(): return
            time.sleep(.03)
        self.fail('条件未在超时前满足')

    def test_receives_drains_at_24fps_and_clears_on_stop(self):
        self.until(lambda:self.buffer.count>=25)
        self.assertEqual(self.server.paths[0],'/video/640x480')
        self.assertTrue(self.buffer.read()[0]); self.assertEqual(self.buffer.status()['role'],'rear-main')
        start=time.monotonic(); count=self.buffer.count; time.sleep(2)
        rate=(self.buffer.count-count)/(time.monotonic()-start)
        self.assertGreater(rate,20); self.assertLess(rate,26)
        self.receiver.stop(); self.assertFalse(self.buffer.read()[0]); self.assertFalse(self.receiver.status()['connected'])

    def test_disconnect_clears_frame_and_reconnects_with_new_session(self):
        self.until(lambda:self.buffer.read()[0]); old=self.buffer.session
        self.server.available.clear()
        self.until(lambda:not self.buffer.read()[0])
        self.assertFalse(self.receiver.status()['connected'])
        self.server.available.set()
        self.until(lambda:self.buffer.read()[0],timeout=6)
        self.assertNotEqual(old,self.buffer.session)


if __name__=='__main__': unittest.main(verbosity=2)
