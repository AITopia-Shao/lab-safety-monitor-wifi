"""真实模型 + 原生主控卡片：手机抓拍和跨界面复核的回归检查。"""
import os
from pathlib import Path
import sys
import tempfile
import time
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'LabSafetyMonitor'))
os.environ.update(QT_QPA_PLATFORM='offscreen',YOLO_OFFLINE='true',YOLO_AUTOINSTALL='false',
                  YOLO_CONFIG_DIR=str(ROOT/'runtime/yolo'))
from PyQt6.QtWidgets import QApplication
from src.config import set_value
from src.core.engine import SafetyEngine
from src.core.events import events
from src.ui.main_window import MainWindow,load_pixel_font
app=QApplication([])
load_pixel_font()
events.persist_enabled=False
set_value('droidcam.enabled',False,persist=False)
engine=SafetyEngine()
engine._command('samples',None)
window=MainWindow(engine)
window.show()
engine.start()


def until(predicate,timeout=20):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        app.processEvents()
        if predicate():return True
        time.sleep(.02)
    return False


try:
    assert until(lambda:window.latest_pano is not None),'no real inference frame'
    assert engine.dual_system.vision_ok,'model not loaded'
    # 较早的模型结果不得倒灌到实时显示，防止视频向后跳动。
    source=engine.dual_system.media_source2
    engine.dual_system.media_source2='droidcam://camera'
    recent=np.full((60,80,3),200,np.uint8);old=np.full_like(recent,10)
    window.update_preview(recent,recent)
    before_key=window.lbl_pano.pixmap().cacheKey()
    window.update_display(old,old,{'vision_ok':True,'desk_valid':True},[],0,0,'')
    assert window.lbl_pano.pixmap().cacheKey()==before_key,'delayed inference overwrote live preview'
    window.show_live_preview=False
    window.update_display(old,old,{'vision_ok':True,'desk_valid':True},[],0,0,'')
    assert window.lbl_pano.pixmap().cacheKey()!=before_key,'analysis mode failed to update'
    window.show_live_preview=True;engine.dual_system.media_source2=source
    before=len(window.snapshots)
    engine._command('snapshot',None)
    assert until(lambda:len(window.snapshots)>before),'phone snapshot did not create desktop card'
    item=window.snapshots[-1]
    events.set_review(item['uid'],True)
    assert until(lambda:item['reviewed']),'peer review did not update desktop card'
    path=ROOT/'runtime/gui-smoke-export.jpg'
    window.save_combined_image(item,str(path))
    assert path.stat().st_size>1000,'export failed'
    window.grab().save(str(ROOT/'runtime/gui-smoke.png'))
    print('GUI_SMOKE_PASS: real_models, live_preview_no_rewind, analysis_mode, phone_snapshot_card, peer_review, image_export',flush=True)
finally:
    window.close();engine.stop()
