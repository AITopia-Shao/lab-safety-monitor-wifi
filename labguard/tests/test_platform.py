"""局域网配对、DroidCam 接入及小屏原有功能回归。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from src.web.server import create_app
from src.core.events import events


class Command:
    def __init__(self): self.calls=[]
    def emit(self,*args): self.calls.append(args)


class Engine:
    def __init__(self): self.command=Command()
    def snapshot(self): return {'state':'NORMAL','vision':{},'phone':{}}
    def latest_jpeg(self,which): return b'annotated'
    def live_jpeg(self,which): return b'live'
    def activate_phone(self): self.command.emit('phone',None)
    def mute(self): self.command.emit('mute',None)
    def call_admin(self): self.command.emit('call_admin',None)


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.engine=Engine()
        self.receiver=Mock()
        self.receiver.status.return_value={'connected':False,'transport':'DroidCam Wi-Fi'}
        self.receiver.connect.return_value={'enabled':True}
        self.mock=patch('src.web.server.droidcam',self.receiver); self.mock.start()
        self.client=TestClient(create_app(self.engine,'test-token'))
        self.h={'X-Token':'test-token'}

    def tearDown(self): self.client.close(); self.mock.stop()

    def test_all_camera_routes_require_pairing(self):
        for method,path in [('get','/api/snapshot'),('get','/api/droidcam'),('get','/api/preview/pano.jpg'),('post','/api/droidcam/connect'),('post','/api/droidcam/disconnect')]:
            self.assertEqual(getattr(self.client,method)(path).status_code,401,path)

    def test_status_with_pairing(self): self.assertEqual(self.client.get('/api/snapshot',headers=self.h).status_code,200)
    def test_public_phone_page(self): self.assertIn('实验台随身小屏',self.client.get('/phone').text)
    def test_local_font_exists(self): self.assertEqual(self.client.get('/font/pixel.ttf').status_code,200)

    def test_connect_selects_two_distinct_sources(self):
        r=self.client.post('/api/droidcam/connect',json={'host':'10.67.54.21','port':4747},headers=self.h)
        self.assertEqual(r.status_code,200)
        self.receiver.connect.assert_called_once_with('10.67.54.21',4747,0)
        self.assertEqual(self.engine.command.calls[-1][0],'phone')

    def test_rejects_external_loopback_and_url_targets(self):
        for host in ['8.8.8.8','127.0.0.1','169.254.169.254','198.18.0.1','http://192.168.1.1','example.com','::1']:
            r=self.client.post('/api/droidcam/connect',json={'host':host},headers=self.h)
            self.assertEqual(r.status_code,422,host)
        self.receiver.connect.assert_not_called()

    def test_rejects_bad_port_rotation_and_extra_fields(self):
        for extra in [{'port':80},{'port':'4747'},{'rotation':45},{'path':'/arbitrary'}]:
            self.assertEqual(self.client.post('/api/droidcam/connect',json={'host':'192.168.1.3',**extra},headers=self.h).status_code,422)

    def test_disconnect_invalidates_receiver(self):
        self.assertEqual(self.client.post('/api/droidcam/disconnect',headers=self.h).status_code,200)
        self.receiver.stop.assert_called_once_with(persist=True)

    def test_live_preview_is_separate_from_annotated_frame(self):
        self.assertEqual(self.client.get('/api/preview/pano.jpg',headers=self.h).content,b'live')
        self.assertEqual(self.client.get('/api/frame/pano.jpg',headers=self.h).content,b'annotated')

    def test_offline_preview_is_unavailable(self):
        self.engine.live_jpeg=lambda which:None
        self.assertEqual(self.client.get('/api/preview/desk.jpg',headers=self.h).status_code,503)

    def test_camera_mode_allowlist(self): self.assertEqual(self.client.post('/api/camera',headers=self.h,json={'mode':'unknown'}).status_code,422)
    def test_manual_snapshot(self):
        self.assertEqual(self.client.post('/api/manual_snapshot',headers=self.h).status_code,200)
        self.assertEqual(self.engine.command.calls[-1][0],'snapshot')
    def test_mute_and_local_assistance(self):
        for action in ['mute','call_admin']:
            self.assertEqual(self.client.post('/api/'+action,headers=self.h).status_code,200)
            self.assertEqual(self.engine.command.calls[-1][0],action)
    def test_removed_features_and_usb_upload_have_no_routes(self):
        for route in ['/api/phone/start','/api/phone/frame','/api/phone/stream','/api/phone/stop','/api/power/cut','/api/power/on','/api/env','/api/demo/start','/api/agent','/api/forecast']:
            self.assertEqual(self.client.post(route,headers=self.h).status_code,404,route)
    def test_unknown_event_cannot_be_reviewed(self): self.assertEqual(self.client.post('/api/events/missing/review',headers=self.h,json={'correct':True}).status_code,404)
    def test_review_body_is_strict(self): self.assertEqual(self.client.post('/api/events/x/review',headers=self.h,json={'correct':'yes'}).status_code,422)


if __name__=='__main__': unittest.main(verbosity=2)
