# 安卓随身小屏源码与本地构建

此公开仓库只提供源码，不分发 APK、签名文件或 DroidCam。原笔记本已安装的小屏可继续使用，不必重新构建或覆盖安装。

## 构建准备

- Windows、Python 3.11 和 JDK 21。
- Android SDK：Build Tools 36.0.0、Android 35 Platform；首次安装这些工具需要网络。
- 设置 `ANDROID_SDK_ROOT` 指向 SDK 根目录，`JAVA_HOME` 指向 JDK 根目录。

在仓库根目录执行：

```powershell
py -3.11 android\build_apk.py
```

脚本调用 aapt、javac、D8、zipalign 与 apksigner，生成本机 `android/LabGuard-Pocket.apk`。它在忽略目录 `android/build/` 创建本地演示签名；APK、构建产物和签名不提交到 GitHub。普通本地演示可使用该签名，正式发行应由维护者另行管理签名。重新生成的签名与原笔记本安装版可能不同：覆盖安装提示签名不一致时，使用原有授权签名，或在备份配对信息后卸载旧版再安装；不要删除正在使用的原签名文件。

## 安装与连接

1. 手机上另行安装官方 DroidCam，授权相机，选择单个后置主摄 Camera 0、1×。
2. 将本地生成的 APK 传到手机安装。若采用 USB 自动安装和配对，需准备 Android SDK Platform Tools，并先启动电脑程序。
3. 电脑连接手机热点，按[完整操作手册](../docs/完整操作手册.md)中的 Wi-Fi 配对方法填写电脑地址、端口与配对码。
4. 小屏点“连接 Wi-Fi 摄像头”，等电脑收到画面后返回小屏，手机 USB 可拔掉；外置 USB 全景相机保持连接。

小屏本身不打开 Camera API，通过已安装 DroidCam 的启动入口和视频接口协作。签名、配对码和手机设置不属于公开源码。
