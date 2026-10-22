"""电脑与安卓小屏共用的局域网鉴权接口，台面由电脑直连 DroidCam 拉取。"""
import asyncio
import secrets
import socket
import threading
from pathlib import Path
from typing import Literal
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from src.config import cfg, resolve_path
from src.core.events import events
from src.mobile.droidcam import droidcam, droidcam_url

ROOT = Path(__file__).resolve().parents[1]
_token = ''
_port = 0
_server = None
_thread = None


def web_token(): return _token
def web_port(): return _port


class Review(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    correct: bool


class DroidCamSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    host: str = Field(min_length=7, max_length=15)
    port: int = Field(default=4747, ge=1024, le=65535)
    rotation: Literal[0, 90, 180, 270] = 0

    @field_validator('host')
    @classmethod
    def local_phone_only(cls, value):
        droidcam_url(value)
        return value


class CameraMode(BaseModel):
    mode: Literal['samples', 'live']


def create_app(engine, token):
    app = FastAPI(title='实验室视觉安全监测·比赛版', docs_url=None, redoc_url=None)

    def authorized(request: Request):
        provided = request.headers.get('X-Token') or request.query_params.get('token', '')
        if not secrets.compare_digest(provided, token): raise HTTPException(401, '请先连接电脑主控端')

    @app.get('/')
    def index(): return FileResponse(ROOT/'web/static/index.html')

    @app.get('/phone')
    def phone(): return FileResponse(ROOT/'web/static/phone.html')

    @app.get('/api/ping')
    def ping(): return {'ok': True, 'edition': 'competition-vision'}

    @app.get('/font/pixel.ttf')
    def font(): return FileResponse(ROOT.parent/'LabSafetyMonitor/Zpix.ttf')

    app.mount('/static', StaticFiles(directory=ROOT/'web/static'), name='static')

    @app.get('/api/snapshot', dependencies=[Depends(authorized)])
    def snapshot(): return engine.snapshot()

    @app.get('/api/events', dependencies=[Depends(authorized)])
    def history(): return {'events': events.history(60), 'stats': events.stats()}

    @app.post('/api/events/{uid}/review', dependencies=[Depends(authorized)])
    def review(uid: str, body: Review):
        if not events.get_event(uid): raise HTTPException(404, '事件不存在')
        events.set_review(uid, body.correct)
        return {'ok': True}

    @app.get('/api/events/{uid}/snapshot.jpg', dependencies=[Depends(authorized)])
    def event_image(uid: str):
        event = events.get_event(uid)
        path = Path((event or {}).get('snapshot') or '').resolve()
        base = Path(resolve_path(cfg('events.snapshot_dir'))).resolve()
        if not path.is_relative_to(base) or not path.is_file(): raise HTTPException(404, '截图尚未就绪')
        return FileResponse(path, media_type='image/jpeg')

    @app.post('/api/manual_snapshot', dependencies=[Depends(authorized)])
    def manual():
        engine.command.emit('snapshot', None)
        return {'ok': True}

    @app.post('/api/mute', dependencies=[Depends(authorized)])
    def mute():
        engine.mute()
        return {'ok': True}

    @app.post('/api/call_admin', dependencies=[Depends(authorized)])
    def call_admin():
        engine.call_admin()
        return {'ok': True, 'message': '已在电脑主控端留下求助记录'}

    @app.post('/api/camera', dependencies=[Depends(authorized)])
    def camera(body: CameraMode):
        engine.command.emit(body.mode, None)
        return {'ok': True}

    @app.get('/api/droidcam', dependencies=[Depends(authorized)])
    def camera_status(): return droidcam.status()

    @app.post('/api/droidcam/connect', dependencies=[Depends(authorized)])
    def connect_droidcam(body: DroidCamSettings):
        try: status = droidcam.connect(body.host, body.port, body.rotation)
        except ValueError as error: raise HTTPException(422, str(error))
        engine.activate_phone()
        return {'ok': True, 'camera': status}

    @app.post('/api/droidcam/disconnect', dependencies=[Depends(authorized)])
    def disconnect_droidcam():
        droidcam.stop(persist=True)
        return {'ok': True}

    @app.get('/api/preview/{which}.jpg', dependencies=[Depends(authorized)])
    def preview(which: Literal['pano', 'desk']):
        data = engine.live_jpeg(which)
        if data is None: raise HTTPException(503, '实时画面准备中')
        return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})

    @app.get('/api/frame/{which}.jpg', dependencies=[Depends(authorized)])
    def frame(which: Literal['pano', 'desk']):
        data = engine.latest_jpeg(which)
        if data is None: raise HTTPException(503, '画面准备中')
        return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})

    @app.get('/stream/{which}.mjpg', dependencies=[Depends(authorized)])
    async def stream(which: Literal['pano', 'desk'], request: Request, view: Literal['live', 'analysis'] = 'live'):
        async def frames():
            loop = asyncio.get_running_loop()
            interval = 1/float(cfg('web.stream_fps', 24))
            deadline = loop.time()
            while not await request.is_disconnected():
                data = engine.live_jpeg(which) if view == 'live' else engine.latest_jpeg(which)
                if data:
                    yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+data+b'\r\n'
                deadline += interval
                if loop.time()-deadline > 2*interval: deadline = loop.time()+interval
                await asyncio.sleep(max(0, deadline-loop.time()))
        return StreamingResponse(frames(), media_type='multipart/x-mixed-replace; boundary=frame')

    @app.websocket('/ws')
    async def ws(websocket: WebSocket):
        if not secrets.compare_digest(websocket.query_params.get('token', ''), token):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(engine.snapshot())
                await asyncio.sleep(.5)
        except (WebSocketDisconnect, RuntimeError): pass

    return app


def start_server(engine):
    global _token, _port, _server, _thread
    runtime = ROOT.parent/'runtime'
    runtime.mkdir(exist_ok=True)
    path = runtime/'web_token.txt'
    _token = str(cfg('web.token', '') or (path.read_text().strip() if path.exists() else secrets.token_urlsafe(24)))
    path.write_text(_token, encoding='utf-8')
    host = str(cfg('web.host', '0.0.0.0'))
    sock = None
    for candidate in range(int(cfg('web.port', 8080)), int(cfg('web.port', 8080))+20):
        trial = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            trial.bind((host, candidate))
            trial.listen(128)
            sock, _port = trial, candidate
            break
        except OSError: trial.close()
    if sock is None: raise RuntimeError('无法找到空闲本机端口')
    _server = uvicorn.Server(uvicorn.Config(create_app(engine, _token), host=host, port=_port,
                                          log_level='warning', access_log=False))
    _thread = threading.Thread(target=lambda: _server.run(sockets=[sock]), name='PhoneWeb', daemon=True)
    _thread.start()
    url = f'http://127.0.0.1:{_port}/?token={_token}'
    (runtime/'web_url.txt').write_text(url, encoding='utf-8')
    (runtime/'web_port.txt').write_text(str(_port), encoding='ascii')
    print(f'[Web] 主控页面已启动，端口 {_port}；手机通过 Wi-Fi 连接。')
    return url


def stop_server():
    if _server: _server.should_exit = True
    if _thread: _thread.join(5)
