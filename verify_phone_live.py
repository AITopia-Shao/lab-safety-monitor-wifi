"""真实 Wi-Fi 双摄验收；仅访问应用接口，不依赖 USB 或 ADB。"""
from pathlib import Path
import json
import time
import urllib.request

ROOT=Path(__file__).resolve().parent
RUNTIME=ROOT/'labguard/runtime'
port=int((RUNTIME/'web_port.txt').read_text())
token=(RUNTIME/'web_token.txt').read_text().strip()
base=f'http://127.0.0.1:{port}'
direct=urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api(path,body=None,raw=False):
    req=urllib.request.Request(base+path,headers={'X-Token':token,'Content-Type':'application/json'},
        data=json.dumps(body).encode() if body is not None else None)
    with direct.open(req,timeout=6) as response: return response.read() if raw else json.load(response)


def until(predicate,timeout=12):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if predicate(): return True
        time.sleep(.2)
    return False


report={'timestamp':time.strftime('%Y-%m-%d %H:%M:%S'),'transport':'Wi-Fi only; API test uses no ADB','checks':{}}
restore=None


def check(name,value):
    report['checks'][name]=bool(value)
    print(name,'PASS' if value else 'FAIL',flush=True)
    assert value,name


try:
    current=api('/api/snapshot'); phone=api('/api/droidcam')
    check('wifi_camera_live',phone['connected'] and phone['host']!='127.0.0.1')
    check('external_usb_pano',current['vision']['pano_device']=='Web Camera' and current['vision']['pano_valid'])
    check('two_distinct_sources',current['vision']['sources']=={'pano':0,'desk':'droidcam://camera'} and current['vision']['desk_valid'])
    check('real_models_loaded',current['vision']['ok'])
    # 统计的是接收端唯一新帧，不是网页刷新或重复图像次数。
    started=time.monotonic(); first=phone['frames_received']; samples=[]
    for _ in range(30):
        time.sleep(1)
        phone=api('/api/droidcam'); samples.append(phone)
    elapsed=time.monotonic()-started
    rate=(phone['frames_received']-first)/elapsed
    report.update(receive_fps=round(rate,3),duration_s=round(elapsed,2),short_window_fps=[s['received_fps'] for s in samples],phone=phone)
    check('continuous_wifi_frames',all(s['connected'] for s in samples))
    check('target_24fps',22.5<rate<24.5)
    print('Wi-Fi measured FPS:',round(rate,3),flush=True)
    for name in ['pano','desk']:
        (RUNTIME/('wifi-'+name+'.jpg')).write_bytes(api('/api/preview/'+name+'.jpg',raw=True))
    restore={key:phone[key] for key in ['host','port','rotation']}
    api('/api/droidcam/disconnect',{})
    check('stop_clears_phone_frame',not api('/api/droidcam')['connected'])
    check('stop_invalidates_desk_decisions',until(lambda:not api('/api/snapshot')['vision']['desk_valid']))
    check('stop_preserves_external_pano',api('/api/snapshot')['vision']['pano_valid'])
    api('/api/droidcam/connect',restore)
    check('wifi_reconnect_recovers_camera',until(lambda:api('/api/droidcam')['connected'],20))
    check('wifi_reconnect_recovers_inference',until(lambda:api('/api/snapshot')['vision']['desk_valid']))
    api('/api/manual_snapshot',{})
    check('manual_snapshot_event',until(lambda:any(e['kind']=='manual' for e in api('/api/events')['events'])))
    event=next(e for e in api('/api/events')['events'] if e['kind']=='manual')
    check('snapshot_saved',until(lambda:bool(next(e for e in api('/api/events')['events'] if e['uid']==event['uid']).get('snapshot'))))
    api('/api/events/'+event['uid']+'/review',{'correct':True})
    check('review_result_shared',next(e for e in api('/api/events')['events'] if e['uid']==event['uid'])['review']==1)
    report['result']='PASS'
finally:
    if restore: api('/api/droidcam/connect',restore)
    (RUNTIME/'droidcam-wifi-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
