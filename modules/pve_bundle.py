# -*- coding: utf-8 -*-
"""编译打包后的运行时资源路径解析与「按需释放」。

背景
----
PyInstaller 单文件打包会把内置资源 (cache 缓存文件 / vncviewer.exe) 放进
只读的临时解包目录 ``sys._MEIPASS``；而部署/凭据逻辑需要**可写**目录来落盘、
下载与长期保存。因此统一约定：

- 打包后(app frozen)  一切可写运行时目录 = **exe 同目录**
- 脚本运行(未 frozen) 一切可写运行时目录 = **项目根/仓库对应子目录** (与旧版一致)

对外提供：
- ``get_cache_dir()``        Sunshine 引擎与依赖缓存目录 (打包内置资源的释放目标)
- ``get_pulse_cache_dir()``  PulseAudio 本地运行包目录
- ``release_bundled_cache()`` 把打包内置的 cache 文件按需释放(已存在同大小则跳过)
- ``release_all()``         启动时一次性释放内置资源 (缓存 + vncviewer)

本模块只用标准库 os/sys/shutil, 无第三方依赖, 保证可被最先 import。
"""
import os
import sys
import shutil

CACHE_DIRNAME = "cache"
PULSE_CACHE_DIRNAME = "pulse_cache"

_APP_DIR = None


def app_dir():
    """应用运行时根目录: 打包后 = exe 同目录; 脚本运行 = 项目根(modules 上一级)。"""
    global _APP_DIR
    if _APP_DIR is None:
        if getattr(sys, "frozen", False):
            _APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
        else:
            _APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return _APP_DIR


def get_cache_dir():
    """Sunshine 引擎 + 依赖 so 缓存目录。
    打包后 = exe 同目录\\cache(可写/便携/可手动预置)；脚本运行 = modules\\cache(与旧版一致，
    直接命中开发者已铺好的缓存，免重下)。
    """
    if getattr(sys, "frozen", False):
        return os.path.join(app_dir(), CACHE_DIRNAME)
    return os.path.join(app_dir(), "modules", CACHE_DIRNAME)


def get_pulse_cache_dir():
    """PulseAudio 本地运行包目录。
    打包后 = exe 同目录\\pulse_cache(可写)；脚本运行 = modules\\pulse_cache。
    """
    if getattr(sys, "frozen", False):
        return os.path.join(app_dir(), PULSE_CACHE_DIRNAME)
    return os.path.join(app_dir(), "modules", PULSE_CACHE_DIRNAME)


def bundled_cache_src():
    """打包内置的缓存文件清单: 返回 [(src_绝对路径, 文件名)]。

    脚本运行(无 _MEIPASS)时返回空列表 —— 此时直接用开发者目录里的 modules/cache,
    无需释放。打包时用 `--add-data=...;cache/` 把文件放进 sys._MEIPASS/cache。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return []
    src_dir = os.path.join(meipass, CACHE_DIRNAME)
    if not os.path.isdir(src_dir):
        return []
    out = []
    for name in sorted(os.listdir(src_dir)):
        p = os.path.join(src_dir, name)
        if os.path.isfile(p):
            out.append((p, name))
    return out


def release_bundled_cache(progress=None):
    """按需把打包内置的 cache 文件释放到 exe 同目录 cache/。

    目标已存在且大小一致则跳过(绝不重复释放)。progress(i, total, name) 可选回调。
    返回本次实际释放的文件数。
    """
    src_files = bundled_cache_src()
    if not src_files:
        return 0
    target = get_cache_dir()
    os.makedirs(target, exist_ok=True)
    released = 0
    total = len(src_files)
    for i, (src, name) in enumerate(src_files):
        dst = os.path.join(target, name)
        try:
            if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
                pass
            else:
                shutil.copy2(src, dst)
                released += 1
        except Exception:
            pass
        if progress:
            try:
                progress(i + 1, total, name)
            except Exception:
                pass
    return released


def release_all(progress=None):
    """启动时一次性释放全部内置资源 (缓存 + vncviewer)。返回 (缓存释放数, vnc 是否就绪)。"""
    n = release_bundled_cache(progress)
    vnc_ready = False
    try:
        from pve_vnc import get_bundled_vnc_path
        p = get_bundled_vnc_path()
        vnc_ready = bool(p and os.path.exists(p) and os.path.getsize(p) > 0)
    except Exception:
        vnc_ready = False
    return n, vnc_ready
