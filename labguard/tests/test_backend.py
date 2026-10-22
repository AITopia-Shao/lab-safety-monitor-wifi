"""纯视觉后端回归：保留上游防抖语义，覆盖手机断线和旧帧隔离。"""
import io
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['YOLO_OFFLINE']='true'
os.environ['YOLO_AUTOINSTALL']='false'
os.environ['YOLO_CONFIG_DIR']=str(ROOT/'runtime/yolo')
import cv2
import numpy as np
from src.config import cfg, set_value
from src.mobile.frame_buffer import PhoneFrameBuffer
from src.mobile.laptop_camera import select_laptop_camera, LaptopCapture
from src.core.events import EventCenter
from LabSafetyMonitor.dual_inference import TemporalVoter, DualInferenceSystem, put_latest


class VisionTests(unittest.TestCase):
    def test_laptop_never_returns_frame_before_real_callback(self):
        import threading
        from unittest.mock import Mock
        camera=LaptopCapture.__new__(LaptopCapture)
        camera._open=True;camera.graph=Mock();camera._pump=lambda _:None
        camera._lock=threading.Lock();camera._frame=None;camera._received=0
        camera._time=lambda:100
        self.assertEqual(camera.read(),(False,None))
        frame=np.zeros((20,30,3),np.uint8)
        camera._arrived(frame)
        ok,returned=camera.read();self.assertTrue(ok);self.assertFalse(returned is frame)
        camera._time=lambda:104
        self.assertEqual(camera.read(),(False,None))

    def test_device_name_wins_over_virtual_camera_order(self):
        self.assertEqual(select_laptop_camera(devices=['Phone Virtual Camera','Integrated Camera','Web Camera']),(2,'Web Camera'))
        with self.assertRaises(RuntimeError):select_laptop_camera(devices=['Phone Virtual Camera','Integrated IR Camera','Integrated Camera'])

    def test_pano_cannot_be_configured_as_phone(self):
        with patch('LabSafetyMonitor.dual_inference.cfg', return_value='droidcam://camera'):
            self.assertEqual(DualInferenceSystem._map_default(0, 'pano'), 0)

    def test_phone_connection_always_selects_distinct_sources(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from src.core.engine import SafetyEngine
        dual = SimpleNamespace(media_source1='sample.jpg', media_source2='sample2.jpg', load_media=Mock())
        engine = SimpleNamespace(dual_system=dual)
        SafetyEngine._command(engine, 'phone', None)
        dual.load_media.assert_called_once_with(src1=0, src2='droidcam://camera', force_reload=True)

    def test_latest_frame_wins(self):
        import queue
        q=queue.Queue(1)
        put_latest(q,1);put_latest(q,2)
        self.assertEqual(q.get(),2)

    def test_voting_ignores_single_hit(self):
        voter=TemporalVoter();voter.update(0,{'x'},{'x'})
        self.assertFalse(voter.active.get('x',False))

    def test_voting_on_and_off(self):
        voter=TemporalVoter()
        for i in range(8): voter.update(i*.15,{'x'},{'x'})
        self.assertTrue(voter.active['x'])
        for i in range(30): voter.update(2+i*.2,set(),{'x'})
        self.assertFalse(voter.active['x'])

    def presence(self):
        obj=DualInferenceSystem.__new__(DualInferenceSystem)
        obj.person_last_seen=0;obj._present_since=None;obj.is_unattended=False
        return obj

    def test_absent_waits_for_timeout(self):
        obj=self.presence();obj._update_presence(14,True,False)
        self.assertFalse(obj.is_unattended)
        obj._update_presence(16,True,False)
        self.assertTrue(obj.is_unattended)

    def test_invalid_camera_is_not_absence(self):
        obj=self.presence();obj._update_presence(100,False,False)
        self.assertFalse(obj.is_unattended)

    def test_recovery_requires_continuous_evidence(self):
        obj=self.presence();obj.is_unattended=True
        obj._update_presence(10,True,True);self.assertTrue(obj.is_unattended)
        obj._update_presence(11.1,True,True);self.assertFalse(obj.is_unattended)

    def test_geometry_is_normalized(self):
        obj=self.presence()
        self.assertGreater(obj._edge_distance(.5,.5),.3)
        self.assertLess(abs(obj._edge_distance(.5,.92)),.001)


class PhoneTests(unittest.TestCase):
    def setUp(self):
        self.phone=PhoneFrameBuffer();self.session=self.phone.start('test')
        self.jpeg=cv2.imencode('.jpg',np.zeros((120,160,3),np.uint8))[1].tobytes()

    def test_accept_and_rotate(self):
        self.phone.put_jpeg(self.jpeg,self.session,1,90)
        ok,img=self.phone.read();self.assertTrue(ok);self.assertEqual(img.shape[:2],(160,120))

    def test_old_sequence_is_dropped(self):
        self.phone.put_jpeg(self.jpeg,self.session,2)
        self.assertFalse(self.phone.put_jpeg(self.jpeg,self.session,1))

    def test_stale_camera_has_no_frame(self):
        self.phone.put_jpeg(self.jpeg,self.session,1)
        self.phone.received_at-=10
        self.assertFalse(self.phone.read()[0]);self.assertFalse(self.phone.status()['connected'])

    def test_stop_invalidates_pending_upload(self):
        self.phone.stop(self.session)
        with self.assertRaises(PermissionError):self.phone.put_jpeg(self.jpeg,self.session,1)

    def test_bad_jpeg_rejected(self):
        with self.assertRaises(ValueError):self.phone.put_jpeg(b'not-a-jpeg',self.session,1)

    def test_second_active_device_is_rejected(self):
        self.phone.put_jpeg(self.jpeg,self.session,1)
        with self.assertRaises(RuntimeError):self.phone.start('other')

    def test_wrong_session_cannot_stop_camera(self):
        self.phone.put_jpeg(self.jpeg,self.session,1);self.phone.stop('wrong')
        self.assertTrue(self.phone.read()[0])

    def test_received_rate_uses_actual_arrivals_and_resets(self):
        with patch('src.mobile.frame_buffer.time.monotonic', return_value=100.0):
            for i in range(25):
                with patch('src.mobile.frame_buffer.time.monotonic', return_value=100+i/24):
                    self.phone.put_jpeg(self.jpeg,self.session,i)
            with patch('src.mobile.frame_buffer.time.monotonic', return_value=101.0):
                self.assertEqual(self.phone.status()['received_fps'],24.0)
                self.phone.stop(self.session)
                self.assertEqual(self.phone.status()['received_fps'],0)
                self.assertFalse(self.phone.status()['connected'])
        self.phone.start('new','0')
        self.assertEqual(self.phone.status()['received_fps'],0)
        self.assertEqual(self.phone.status()['camera_id'],'0')

class EventTests(unittest.TestCase):
    def setUp(self): self.events=EventCenter();self.events.persist_enabled=False

    def test_repeated_event_only_one_card(self):
        self.events.update('x',True,title='test');self.events.update('x',True,title='test')
        self.assertEqual(len(self.events.history()),1)

    def test_end_and_retrigger_reuses_event(self):
        self.events.update('x',True,title='test');uid=self.events.history()[0]['uid']
        self.events.update('x',False);self.events.update('x',True,title='test')
        self.assertEqual(self.events.active_events()[0]['uid'],uid)

    def test_review_updates_record(self):
        self.events.update('x',True,title='test');uid=self.events.history()[0]['uid']
        self.events.set_review(uid,True)
        self.assertEqual(self.events.get_event(uid)['review'],1)

    def test_resolved_event_no_longer_active(self):
        self.events.update('x',True,title='test');self.events.update('x',False)
        self.assertEqual(self.events.active_events(),[])


if __name__=='__main__':unittest.main(verbosity=2)
