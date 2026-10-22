# 实验室安全视觉监测 · 外置 USB 全景 + DroidCam Wi-Fi 台面

Windows 电脑进行双路视觉识别，安卓手机兼作台面摄像头和随身小屏。适用于无需单片机的本地比赛演示。

**公开范围：仅源码与文字文档。** 模型、APK、演示样本、截图、字体二进制文件、Word 手册及本机运行环境均不上传。原笔记本已配置的完整比赛版继续照常使用；仅克隆此仓库还不能直接完成识别或运行样本回放。

基于 [GitHub 上游 83aa8ea](https://github.com/SSSSSmilewei/lab-safety-monitor/commit/83aa8eada7800679f60571e5085a4be57e1e9444)，保留模型、时间投票、事件记录、抓拍与专家复核；已移除嵌入式、温度、烟雾和设备供电控制。

## 这台电脑直接使用

1. 插好外置 **Web Camera**，手机开启热点，电脑连接该热点。
2. 双击 **启动双摄实拍.bat**。全景锁定外置 USB 相机；台面只接 DroidCam Wi-Fi。
3. 手机打开 **实验台随身小屏**。点 **启动 / 设置 DroidCam**，选择后置主摄 **Camera 0、1×**，等电脑接到画面，再返回小屏。
4. 小屏显示守护、画面、事件，右侧可连接或停止 DroidCam，并显示电脑实际接收帧率。手机 USB 数据线可以拔掉。

本机已安装和配对。首次安装或热点地址改变时，USB 连接已授权手机，双击 **连接安卓手机.bat** 自动安装与重新配对；脚本不建立 USB 视频或状态隧道。也可从电脑菜单 **比赛演示 → 安卓小屏 Wi-Fi 配对信息**，在手机 **配对 / 网络设置** 手动填写。

**启动比赛版.bat** 保留真实样本回放入口；实拍时可从“比赛演示”菜单切换。无需单片机，无需云端推理或互联网。手机需保留已安装的官方 DroidCam，并保持小屏亮屏。

- [完整操作手册（文字版）](docs/完整操作手册.md)
- [比赛版快速使用说明](docs/比赛版使用说明.md)
- [本机验收记录](docs/验收记录.md)
- [版本对比与改动](docs/版本对比与改动.md)
- [安卓小屏源码与构建说明](android/README.md)

开发入口为 `labguard/.runtime/python/python.exe labguard/run_app.py`；依赖与模型已经放在本机项目目录，复制项目需包含 `.runtime`。运行数据在 `labguard/runtime/`，不入库。

## 从 GitHub 源码部署到另一台 Windows 电脑

仓库只包含源码与文字文档，不包含模型、APK、演示样本、截图、字体、Word/PDF、本机 `.runtime` 环境、配对码、密钥、事件库和日志。先安装 Python 3.11，在仓库根目录执行：

```powershell
py -3.11 -m venv labguard\.venv
labguard\.venv\Scripts\python.exe -m pip install --upgrade pip
labguard\.venv\Scripts\python.exe -m pip install `
  --extra-index-url https://download.pytorch.org/whl/cpu `
  -r labguard\requirements-competition.txt
```

然后由有权使用资料的人另行准备兼容模型，放置为 `labguard/models/ppe_best.pt` 与 `labguard/models/chem_best.pt`；本仓库不会自动下载或公开模型。按 [安卓构建说明](android/README.md) 在本地生成小屏 APK 并安装，官方 DroidCam 需单独安装。准备好模型后启动：

```powershell
labguard\.venv\Scripts\python.exe labguard\run_app.py
```

首次依赖安装需要互联网；后续视觉推理可在本地运行。当前批处理入口针对原笔记本的 `.runtime`，新环境请使用上述 Python 命令。按手册进行 Wi-Fi 手动配对。外置摄像头名称不同时，修改 `labguard/config.yaml` 的 `camera.pano_name`。演示样本未公开，源码部署优先使用实拍模式或导入自己有权使用的媒体。未提供自定义字体时使用系统字体，外观可能略有不同。

## 验证与运行边界

本机已通过 45 项后端与接口回归、6 项原生界面检查、14 项真实 Wi-Fi 双摄验收。手机拔 USB 后持续 30.67 秒平均实收 **23.996 FPS**；视频接收帧率与 CPU 模型帧率分别统计。完整依据见验收记录，不能将功能演示当作独立模型准确率评估。

程序提供软件视觉提醒、抓拍和人工复核；桌边参考线需要按实际手机机位标定。界面“准确率”和总分来自人工复核，不是独立测试集指标或官方比赛评分。

## 来源与第三方组件

本仓库是面向电脑与安卓小屏的比赛改造版，原作者代码、模型和既有资料来源见 [NOTICE.md](NOTICE.md)。官方 DroidCam 是需单独安装的第三方应用，本仓库未重新打包其专有程序。
