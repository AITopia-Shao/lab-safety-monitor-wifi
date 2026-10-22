"""
统一配置加载
src/config.py

读取项目根目录的 config.yaml，与内置默认值深度合并。
找不到文件或缺少 PyYAML 时，全部使用默认值，程序照常运行。
用法：
    from src.config import cfg
    cfg("vision.imgsz")              -> 416
    cfg("camera.pano", 0)
"""
import os
import sys
import copy
import threading
from typing import Any

DEFAULTS = {
    "camera": {"pano": 0, "pano_name": "Web Camera", "pano_fps": 30,
               "desk": "droidcam://camera", "width": 640, "height": 480,
               "fourcc": "YUY2", "capture_fps": 24},
    "vision": {"prefer_format": ["pt"], "imgsz": 416, "conf": 0.35, "iou": 0.45, "device": "cpu"},
    "presence": {"absent_seconds": 15.0, "recover_seconds": 1.0},
    "voting": {"window_s": 3.0, "on_ratio": 0.6, "off_ratio": 0.2, "min_frames": 4},
    "sleep": {"head_y_ratio": 0.60, "still_seconds": 10.0, "max_motion": 0.03},
    "desk": {"edge_line": [[0.0, 0.92], [1.0, 0.92]], "edge_margin": 0.06},
    "events": {"reminder_s": 30.0, "retrigger_s": 10.0, "db": "runtime/events.db",
               "snapshot_dir": "runtime/snapshots"},
    "ui": {"wave_fps": 12},
    "web": {"host": "0.0.0.0", "port": 8080, "token": "", "stream_fps": 24,
            "stream_width": 640},
    "droidcam": {"host": "", "port": 4747, "rotation": 0, "enabled": True},
    "phone": {"stale_seconds": 2.5, "max_jpeg_bytes": 1500000, "target_fps": 24},
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_lock = threading.Lock()
_config = None
_config_path = None


def _candidate_paths():
    env_path = os.environ.get("LAB_SAFETY_CONFIG")
    if env_path:
        yield env_path
    meipass = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False):
        yield os.path.join(os.path.dirname(sys.executable), "config.yaml")
    yield os.path.join(PROJECT_ROOT, "config.yaml")
    if meipass:
        yield os.path.join(meipass, "config.yaml")
    yield os.path.join(os.getcwd(), "config.yaml")


def _deep_merge(base: dict, override: dict) -> dict:
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load(force: bool = False) -> dict:
    global _config, _config_path
    with _lock:
        if _config is not None and not force:
            return _config
        merged = copy.deepcopy(DEFAULTS)
        _config_path = None
        for path in _candidate_paths():
            if path and os.path.isfile(path):
                try:
                    import yaml
                    with open(path, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    _deep_merge(merged, data)
                    _config_path = path
                    print(f"[config] 已加载配置文件: {path}")
                except Exception as e:
                    print(f"[config] 配置文件 {path} 读取失败，使用默认值: {e}")
                break
        # 运行时修改（Web 总后台调参）保存在 runtime/config_override.yaml，重启后仍生效
        ov = _read_overrides()
        if ov:
            _deep_merge(merged, ov)
        _config = merged
        return _config


def _override_path() -> str:
    return resolve_path(os.path.join("runtime", "config_override.yaml"))


def _read_overrides() -> dict:
    path = _override_path()
    if not os.path.isfile(path):
        return {}
    try:
        import yaml
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"[config] 运行时覆盖文件读取失败，已忽略: {e}")
        return {}


def set_value(path: str, value: Any, persist: bool = True):
    """运行时修改一项配置（调用方负责校验取值范围），并写入覆盖文件"""
    load()
    keys = path.split(".")
    with _lock:
        node = _config
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
    if not persist:
        return
    ov = _read_overrides()
    node = ov
    for k in keys[:-1]:
        node = node.setdefault(k, {})
    node[keys[-1]] = value
    try:
        import yaml
        path_ = _override_path()
        os.makedirs(os.path.dirname(path_), exist_ok=True)
        with open(path_, "w", encoding="utf-8") as f:
            yaml.safe_dump(ov, f, allow_unicode=True, sort_keys=False)
    except Exception as e:
        print(f"[config] 运行时覆盖文件写入失败（本次修改仅内存生效）: {e}")


def cfg(path: str, default: Any = None) -> Any:
    node = load()
    for key in path.split("."):
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return default
    return node


def resolve_path(p: str) -> str:
    """把配置里的相对路径解析为相对项目根目录（打包后相对 exe 目录）"""
    if os.path.isabs(p):
        return p
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else PROJECT_ROOT
    return os.path.join(base, p)


def config_path():
    load()
    return _config_path
