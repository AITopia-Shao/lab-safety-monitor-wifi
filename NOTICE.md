# 来源说明

本比赛改造版发布于 AITopia-Shao/lab-safety-monitor-wifi，基于原作者 SSSSSmilewei 的 [lab-safety-monitor](https://github.com/SSSSSmilewei/lab-safety-monitor) 仓库改造。基础提交为 `83aa8eada7800679f60571e5085a4be57e1e9444`。本公开仓库采用独立的源码提交，不携带上游历史中的模型、图片与文档附件，当前仓库不替代原作者完整版本。

本版主要改动包括移除嵌入式功能、使用外置 USB 全景相机、接入官方 DroidCam Wi-Fi 台面视频、实现安卓随身小屏、整理比赛入口、修复实时预览回跳，并新增完整操作手册与回归测试。

本机使用的 `labguard/models/ppe_best.pt` 和 `chem_best.pt` 沿用上游权重，未在本次重新训练。根据发布者选择，公开仓库只含源码与文字文档，不包含这两份模型、演示样本、任何截图、字体二进制文件、APK 或 Word/PDF 附件。相关资料仍保留在原笔记本本地，未因发布而删除。

DroidCam 由 DEV47APPS 提供，需另行安装官方应用。本仓库小屏通过其视频接口与启动入口协作，不包含或声称拥有 DroidCam 程序源码。

第三方组件、字体、既有代码、模型与资料遵循其各自许可及权利归属。本次未为上游内容添加新的许可授权，也未将其声明为本账号原创。
