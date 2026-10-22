"""首次通过 USB 更新小屏和配对；实际状态与视频始终走 Wi-Fi，不建立 USB 隧道。"""
from pathlib import Path
import ipaddress
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
sdk = Path(os.environ.get('ANDROID_SDK_ROOT', r'C:\Program Files (x86)\Android\android-sdk'))
bundled = ROOT/'labguard/.runtime/platform-tools/adb.exe'
adb = Path(os.environ.get('LABGUARD_ADB', str(bundled if bundled.is_file() else sdk/'platform-tools/adb.exe')))


def run(*args, capture=False):
    result = subprocess.run([str(adb), *map(str,args)], check=True, capture_output=capture,
                            text=True, encoding='utf-8', errors='replace', timeout=120 if 'install' in args else 20)
    return result.stdout if capture else ''


def wifi_pairing(serial):
    """选与手机 Wi-Fi/AP 接口同网段的电脑地址，排除 VPN 与 USB 网卡。"""
    data = run('-s',serial,'shell','ip','-f','inet','addr','show',capture=True)
    interface = ''
    candidates = []
    for line in data.splitlines():
        match = re.match(r'\d+: ([^:]+):',line)
        if match: interface=match.group(1)
        match = re.search(r'\binet ([0-9.]+/\d+)',line)
        if not match or not re.search(r'wlan|^ap|^br',interface): continue
        address=ipaddress.ip_interface(match.group(1))
        if not address.ip.is_private or address.ip.is_loopback: continue
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as route:
            route.connect((str(address.ip),4747))
            computer=ipaddress.ip_address(route.getsockname()[0])
        if computer != address.ip and computer in address.network:
            candidates.append((str(computer),str(address.ip)))
    if not candidates: raise RuntimeError('电脑与手机不在同一 Wi-Fi。请先让电脑连接手机热点，再重试。')
    return candidates[-1]


def main():
    if not adb.is_file(): raise RuntimeError('找不到 adb，请设置 ANDROID_SDK_ROOT。')
    listing=run('devices',capture=True)
    devices=[line.split()[0] for line in listing.splitlines()[1:] if len(line.split())>1 and line.split()[1]=='device' and not line.startswith('emulator-')]
    if len(devices)!=1: raise RuntimeError('首次更新请通过 USB 只连接一部已授权手机；后续使用 Wi-Fi，无需 USB。')
    serial=devices[0]
    computer,phone=wifi_pairing(serial)
    runtime=ROOT/'labguard/runtime'
    direct=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline=time.monotonic()+20
    while True:
        try:
            port=int((runtime/'web_port.txt').read_text().strip())
            token=(runtime/'web_token.txt').read_text().strip()
            with direct.open(f'http://127.0.0.1:{port}/api/ping',timeout=2) as response:
                if response.status==200: break
        except (OSError,ValueError): pass
        if time.monotonic()>=deadline: raise RuntimeError('请先启动电脑比赛版。')
        time.sleep(.5)
    apk=ROOT/'android/LabGuard-Pocket.apk'
    if not apk.is_file(): raise RuntimeError('请先运行 android/build_apk.py 构建手机端。')
    run('-s',serial,'install','-r','--no-incremental',apk)
    # 只清理项目旧版通道，保留其他软件的 adb 配置。
    for args in [('reverse','--remove','tcp:8080'),('forward','--remove','tcp:14747')]:
        subprocess.run([str(adb),'-s',serial,*args],capture_output=True,timeout=10)
    base=f'http://{computer}:{port}'
    run('-s',serial,'shell','am','start','-n','edu.labguard.pocket/.MainActivity',
        '--es','server',base,'--es','token',token,capture=True)
    print(f'小屏已配对：电脑 {computer}:{port}；DroidCam 手机 {phone}:4747。')
    print('在小屏点“启动 / 设置 DroidCam”，选择后置主摄，再返回小屏。视频和状态都走 Wi-Fi，可以拔掉 USB。')
    return 0


if __name__=='__main__':
    try: sys.exit(main())
    except Exception as error:
        print('连接未完成：',error)
        sys.exit(1)
