"""比赛版入口：电脑主控窗 + 安卓小屏服务；默认完全离线运行。"""
import argparse
import faulthandler
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'LabSafetyMonitor'))
os.chdir(ROOT)
for name in ('yolo', 'matplotlib'):
    (ROOT/'runtime'/name).mkdir(parents=True, exist_ok=True)
os.environ.update(YOLO_CONFIG_DIR=str(ROOT/'runtime/yolo'), MPLCONFIGDIR=str(ROOT/'runtime/matplotlib'),
                  YOLO_OFFLINE='true', YOLO_AUTOINSTALL='false')
for stream in (sys.stdout, sys.stderr):
    if stream: stream.reconfigure(errors='replace')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--samples', action='store_true')
    parser.add_argument('--quit-after', type=int, default=0)
    args = parser.parse_args()
    crash = open(ROOT/'runtime/crash.log', 'a', encoding='utf-8', buffering=1)
    faulthandler.enable(file=crash, all_threads=True)
    import torch
    try:
        from PySide6.QtCore import QTimer, QLockFile, QCoreApplication
        from PySide6.QtWidgets import QApplication, QScrollArea
    except ImportError:
        from PyQt6.QtCore import QTimer, QLockFile, QCoreApplication
        from PyQt6.QtWidgets import QApplication, QScrollArea
    app = QCoreApplication(sys.argv) if args.headless else QApplication(sys.argv)
    lock = QLockFile(str(ROOT/'runtime/competition.lock'))
    if not lock.tryLock(100):
        print('比赛版已运行，请从任务栏切回窗口。')
        return 0
    from src.core.engine import SafetyEngine
    from src.web.server import start_server, stop_server
    engine = SafetyEngine()
    url = start_server(engine)
    if args.samples: engine.command.emit('samples', None)
    if not args.headless:
        from src.ui.main_window import MainWindow, load_pixel_font
        load_pixel_font()
        window = MainWindow(engine)
        content = window.takeCentralWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        window.setCentralWidget(scroll)
        menu = window.menuBar().addMenu('比赛演示')
        menu.addAction('真实样本回放', lambda: engine.command.emit('samples', None))
        menu.addAction('外置 USB 摄像头 + 安卓手机', lambda: engine.command.emit('live', None))
        menu.addAction('安卓小屏 Wi-Fi 配对信息', window.connect_phone_camera)
        preview_action = menu.addAction('实时画面（24 帧目标；取消勾选查看识别标注）')
        preview_action.setCheckable(True)
        preview_action.setChecked(True)
        preview_action.toggled.connect(window.set_live_preview)
        def open_web(phone=False):
            import webbrowser
            webbrowser.open(url.replace('/?token=', '/phone?token=') if phone else url)
        menu.addAction('打开网页主控屏', open_web)
        menu.addAction('预览手机小屏', lambda: open_web(True))
        window.statusBar().showMessage('全景：外置 USB 摄像头｜台面：DroidCam 手机主摄｜Wi-Fi 接收目标 24 FPS｜比赛演示菜单可切换识别标注')
        connection_timer = QTimer(window)
        def connection_status():
            status = engine.snapshot()
            phone = status.get('phone', {})
            window.statusBar().showMessage('全景：外置 USB 摄像头｜台面：DroidCam 手机主摄｜Wi-Fi 实收 '+str(phone.get('received_fps', 0))+' / 24 FPS｜'+engine.fps_text+'｜菜单可切换识别标注')
        connection_timer.timeout.connect(connection_status)
        connection_timer.start(1000)
        window.showMaximized()
    engine.start()
    def ready():
        if not engine.frame_seq:
            QTimer.singleShot(500, ready)
            return
        data = {'pid': os.getpid(), 'timestamp': time.time(), 'snapshot': engine.snapshot()}
        (ROOT/'runtime/ready.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        if not args.headless: window.grab().save(str(ROOT/'runtime/desktop.png'))
        print('COMPETITION_READY', flush=True)
    QTimer.singleShot(2000, ready)
    if args.quit_after: QTimer.singleShot(args.quit_after*1000, app.quit)
    try: return app.exec()
    finally:
        stop_server()
        engine.stop()
        lock.unlock()
        crash.close()


if __name__ == '__main__':
    sys.exit(main())
