# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import paramiko
import webbrowser
import socket
import time
import subprocess
import urllib.request
import io
import tarfile
import os
import re
from concurrent.futures import ThreadPoolExecutor
import random
import string
import json
import ssl
import base64
import gzip
import shutil

from pve_bundle import get_cache_dir, get_pulse_cache_dir

from pve_common import (
    CREDS_DIR,
    CREDS_FILE,
    _TEST_PANEL_SRC,
    _fetch_url,
    _valid_deb,
    center_window,
    extract_deb_data_tar,
    run_sync_cmd
)

class _DeployBundleMixin:
    def _ensure_single_deb_libs(self, cache_dir, deb_temp_name, deb_urls, target_so_list):
        """精准下载 deb 并从实体文件解包提取指定动态库 (带 !<arch>\n 签名校验与大文件保护)"""
        all_exist = all(os.path.exists(os.path.join(cache_dir, so)) and os.path.getsize(os.path.join(cache_dir, so)) > 10000 for so in target_so_list)
        if all_exist: return True

        deb_temp = os.path.join(cache_dir, deb_temp_name)
        if os.path.exists(deb_temp) and not _valid_deb(deb_temp):
            try: os.remove(deb_temp)
            except Exception: pass

        if not os.path.exists(deb_temp):
            for u in deb_urls:
                try:
                    host_str = u.split('/')[2]
                    self.log_append(f"[*] 正在从 {host_str} 拉取 {deb_temp_name} ...")
                    r = subprocess.run(["curl.exe", "-sSL", "-o", deb_temp, u], timeout=20)
                    if r.returncode == 0 and os.path.exists(deb_temp) and _valid_deb(deb_temp):
                        break
                    elif os.path.exists(deb_temp):
                        try: os.remove(deb_temp)
                        except Exception: pass
                except Exception: continue

        if os.path.exists(deb_temp) and _valid_deb(deb_temp):
            try:
                with open(deb_temp, "rb") as f:
                    deb_bytes = f.read()
                data_tar, tar_name = extract_deb_data_tar(deb_bytes)
                if data_tar:
                    with tarfile.open(fileobj=io.BytesIO(data_tar)) as tar:
                        for target_so in target_so_list:
                            best_member = None
                            max_size = 0
                            for member in tar.getmembers():
                                if "gdb" in member.name or "doc" in member.name or member.name.endswith(".py"):
                                    continue
                                if target_so in member.name or target_so.split(".so")[0] in member.name:
                                    if (member.isreg() or not member.issym()) and member.size > max_size:
                                        max_size = member.size
                                        best_member = member

                            if best_member:
                                out_f = tar.extractfile(best_member)
                                if out_f:
                                    target_path = os.path.join(cache_dir, target_so)
                                    with open(target_path, "wb") as lf:
                                        lf.write(out_f.read())
                                    self.log_append(f"[+] 依赖库就绪: {target_so} ({os.path.getsize(target_path)} 字节)")
            except Exception as ex:
                self.log_append(f"[-] 解包异常: {ex}")

        return all(os.path.exists(os.path.join(cache_dir, so)) for so in target_so_list)

    def _ensure_all_dep_libs(self, cache_dir):
        """补齐 Batocera 缺失的宿主运行库 (C++ / DRM / Wayland / PipeWire)"""
        for f in os.listdir(cache_dir):
            if f.endswith(".deb"):
                fp = os.path.join(cache_dir, f)
                if not _valid_deb(fp):
                    try: os.remove(fp)
                    except Exception: pass

        bad_cpp = os.path.join(cache_dir, "libstdc++.so.6")
        if os.path.exists(bad_cpp) and os.path.getsize(bad_cpp) < 100000:
            try: os.remove(bad_cpp)
            except Exception: pass

        # 1. libstdc++.so.6 (Bullseye gcc-10, 1.8MB 实体)
        self._ensure_single_deb_libs(
            cache_dir=cache_dir, deb_temp_name="libstdc++_bullseye.deb",
            deb_urls=[
                "http://mirrors.aliyun.com/debian/pool/main/g/gcc-10/libstdc++6_10.2.1-6_amd64.deb",
                "http://ftp.debian.org/debian/pool/main/g/gcc-10/libstdc++6_10.2.1-6_amd64.deb"
            ],
            target_so_list=["libstdc++.so.6"]
        )
        # 2. libp11-kit.so.0
        self._ensure_single_deb_libs(
            cache_dir=cache_dir, deb_temp_name="libp11kit_bullseye.deb",
            deb_urls=[
                "http://mirrors.aliyun.com/debian/pool/main/p/p11-kit/libp11-kit0_0.23.22-1_amd64.deb",
                "http://ftp.debian.org/debian/pool/main/p/p11-kit/libp11-kit0_0.23.22-1_amd64.deb"
            ],
            target_so_list=["libp11-kit.so.0"]
        )
        # 3. libgpg-error.so.0
        self._ensure_single_deb_libs(
            cache_dir=cache_dir, deb_temp_name="libgpgerr_bullseye.deb",
            deb_urls=[
                "http://mirrors.aliyun.com/debian/pool/main/libg/libgpg-error/libgpg-error0_1.38-2_amd64.deb",
                "http://ftp.debian.org/debian/pool/main/libg/libgpg-error/libgpg-error0_1.38-2_amd64.deb"
            ],
            target_so_list=["libgpg-error.so.0"]
        )
        # 4. libdrm.so.2
        self._ensure_single_deb_libs(
            cache_dir=cache_dir, deb_temp_name="libdrm_bullseye.deb",
            deb_urls=[
                "http://mirrors.aliyun.com/debian/pool/main/libd/libdrm/libdrm2_2.4.104-1_amd64.deb",
                "http://ftp.debian.org/debian/pool/main/libd/libdrm/libdrm2_2.4.104-1_amd64.deb"
            ],
            target_so_list=["libdrm.so.2"]
        )
        # 5. Wayland 运行库 (Debian bookworm 12, wayland 1.21.0)
        #    坑: 旧用 Ubuntu focal 1.18.0, 其 libwayland-client 缺 wl_proxy_marshal_flags
        #    (该符号 1.20+ 才有; sunshine 自带 libgdk-3.so.0 硬引用它, 缺了 symbol lookup error)。
        #    bookworm 1.21.0 含该符号且仅需 glibc 2.28, 兼容盒子新 glibc 2.41。
        #    另: 若 cache 里留有过期的 libwayland-client.so.0(无该符号), _ensure_single_deb_libs
        #    会因 size>10000 直接命中短路不再重下 => 在此先按符号内容剔除过期缓存。
        wl_path = os.path.join(cache_dir, "libwayland-client.so.0")
        if os.path.exists(wl_path):
            try:
                wl_b = open(wl_path, "rb").read()
                if b"wl_proxy_marshal_flags" not in wl_b:
                    os.remove(wl_path)
                    self.log_append("[*] [wayland] 剔除过期 libwayland-client.so.0 (缺 wl_proxy_marshal_flags) 将重新下载")
            except Exception:
                pass
        self._ensure_single_deb_libs(
            cache_dir=cache_dir, deb_temp_name="libwayland_client_bookworm.deb",
            deb_urls=[
                "http://mirrors.aliyun.com/debian/pool/main/w/wayland/libwayland-client0_1.21.0-1_amd64.deb",
                "http://ftp.debian.org/debian/pool/main/w/wayland/libwayland-client0_1.21.0-1_amd64.deb"
            ],
            target_so_list=["libwayland-client.so.0"]
        )
        self._ensure_single_deb_libs(
            cache_dir=cache_dir, deb_temp_name="libwayland_cursor_bookworm.deb",
            deb_urls=[
                "http://mirrors.aliyun.com/debian/pool/main/w/wayland/libwayland-cursor0_1.21.0-1_amd64.deb",
                "http://ftp.debian.org/debian/pool/main/w/wayland/libwayland-cursor0_1.21.0-1_amd64.deb"
            ],
            target_so_list=["libwayland-cursor.so.0"]
        )
        self._ensure_single_deb_libs(
            cache_dir=cache_dir, deb_temp_name="libwayland_egl_bookworm.deb",
            deb_urls=[
                "http://mirrors.aliyun.com/debian/pool/main/w/wayland/libwayland-egl1_1.21.0-1_amd64.deb",
                "http://ftp.debian.org/debian/pool/main/w/wayland/libwayland-egl1_1.21.0-1_amd64.deb"
            ],
            target_so_list=["libwayland-egl.so.1"]
        )
        # 6. PipeWire 运行库 (Debian bullseye 官方源; 0.3.19 提供 libpipewire-0.3.so.0)
        #    历史坑: 原 Ubuntu focal 链接(0.3.4)已 404, 且 focal 新包用 data.tar.zst
        #    纯 Python 解包(tarfile)不支持 zstd => 永远解不出 libpipewire-0.3.so.0,
        #    导致运行时报 "error while loading shared libraries: libpipewire-0.3.so.0"。
        #    故改用与上方一致源的 bullseye data.tar.xz 包 (解包链路与其余依赖库相同)。
        self._ensure_single_deb_libs(
            cache_dir=cache_dir, deb_temp_name="libpipewire_bullseye.deb",
            deb_urls=[
                "http://mirrors.aliyun.com/debian/pool/main/p/pipewire/libpipewire-0.3-0_0.3.19-4_amd64.deb",
                "http://ftp.debian.org/debian/pool/main/p/pipewire/libpipewire-0.3-0_0.3.19-4_amd64.deb"
            ],
            target_so_list=["libpipewire-0.3.so.0"]
        )
        # 7. libthai & libdatrie
        self._ensure_single_deb_libs(
            cache_dir=cache_dir, deb_temp_name="libthai_bullseye.deb",
            deb_urls=[
                "http://mirrors.aliyun.com/debian/pool/main/libt/libthai/libthai0_0.1.28-3_amd64.deb",
                "http://ftp.debian.org/debian/pool/main/libt/libthai/libthai0_0.1.28-3_amd64.deb"
            ],
            target_so_list=["libthai.so.0"]
        )
        self._ensure_single_deb_libs(
            cache_dir=cache_dir, deb_temp_name="libdatrie_bullseye.deb",
            deb_urls=[
                "http://mirrors.aliyun.com/debian/pool/main/libd/libdatrie/libdatrie1_0.2.13-1_amd64.deb",
                "http://ftp.debian.org/debian/pool/main/libd/libdatrie/libdatrie1_0.2.13-1_amd64.deb"
            ],
            target_so_list=["libdatrie.so.1"]
        )

        # 8. libFLAC.so.8 (Debian 10 buster, 构建于 glibc 2.14, 兼容盒子 glibc 2.30; 勿用 bullseye 1.3.3-2, 那版需要 GLIBC_2.33 会启动报错)
        self._ensure_single_deb_libs(
            cache_dir=cache_dir, deb_temp_name="libflac8_buster.deb",
            deb_urls=[
                "http://archive.debian.org/debian/pool/main/f/flac/libflac8_1.3.2-3+deb10u2_amd64.deb"
            ],
            target_so_list=["libFLAC.so.8"]
        )

        all_so_list = [
            "libstdc++.so.6", "libp11-kit.so.0", "libgpg-error.so.0", "libdrm.so.2",
            "libwayland-client.so.0", "libwayland-cursor.so.0", "libwayland-egl.so.1",
            "libpipewire-0.3.so.0",
            "libthai.so.0", "libdatrie.so.1", "libffi.so.7", "libtasn1.so.6"
        ]
        tar_gz_path = os.path.join(cache_dir, "sunshine_libs.tar.gz")
        with tarfile.open(tar_gz_path, "w:gz") as tar:
            for so_name in all_so_list:
                f_path = os.path.join(cache_dir, so_name)
                if os.path.exists(f_path):
                    tar.add(f_path, arcname=so_name)
        return tar_gz_path

    # ---- 为最新 Sunshine(需 GLIBC_2.35+) 提供独立新版 glibc 运行时 ----
    # 盒 184 系统 glibc 仅 2.30(无 /dev/dri、无硬解), 最新 AppImage 主二进制
    # 需 GLIBC_2.35。不能替换系统 libc, 只能"平行装一套新 glibc", 用新 loader
    # 显式拉起 Sunshine:  ld-linux-x86-64.so.2 --library-path <新glibc>:<原有> sunshine
    # 来源: Debian trixie libc6 (glibc 2.41, data.tar.xz)。tarfile 支持 xz,
    # 避开 Ubuntu jammy 的 data.tar.zst 解不出的坑。glibc 2.41 同时覆盖
    # sunshine 需要的 2.35 与 libwayland-client 需要的 2.38。
    GLIBC_DEB_NAME = "libc6_trixie.deb"
    GLIBC_DEB_URLS = [
        "http://mirrors.aliyun.com/debian/pool/main/g/glibc/libc6_2.41-12%2Bdeb13u4_amd64.deb",
        "http://ftp.debian.org/debian/pool/main/g/glibc/libc6_2.41-12%2Bdeb13u4_amd64.deb",
    ]
    GLIBC_TAR = "sunshine_glibc.tar.gz"

    def _ensure_glibc_runtime(self, cache_dir):
        """下载 Debian trixie libc6 (glibc 2.41) 并打成独立运行时 tar.gz。
        解到盒子 /userdata/system/glibc 后路径为 usr/lib/x86_64-linux-gnu/。
        """
        tar_path = os.path.join(cache_dir, self.GLIBC_TAR)
        if os.path.exists(tar_path) and os.path.getsize(tar_path) > 1 * 1024 * 1024:
            self.log_append(f"[+] [glibc] 命中本地缓存: {self.GLIBC_TAR} ({os.path.getsize(tar_path)//1024//1024}MB 直传)")
            return tar_path

        stage = os.path.join(cache_dir, "glibc_stage")
        if os.path.exists(stage):
            shutil.rmtree(stage, ignore_errors=True)
        os.makedirs(stage, exist_ok=True)

        deb = os.path.join(cache_dir, self.GLIBC_DEB_NAME)
        if os.path.exists(deb) and not _valid_deb(deb):
            try: os.remove(deb)
            except Exception: pass
        if not (os.path.exists(deb) and _valid_deb(deb)):
            for u in self.GLIBC_DEB_URLS:
                try:
                    host = u.split('/')[2]
                    self.log_append(f"[*] [glibc] 拉取 {self.GLIBC_DEB_NAME} <- {host} ...")
                    r = subprocess.run(["curl.exe", "-sSL", "-o", deb, u], timeout=40)
                    if r.returncode == 0 and os.path.exists(deb) and _valid_deb(deb):
                        break
                    elif os.path.exists(deb):
                        try: os.remove(deb)
                        except Exception: pass
                except Exception: continue
        if not (os.path.exists(deb) and _valid_deb(deb)):
            self.log_append("[-] [glibc] 下载 libc6(trixie) 失败, 无法提供新版 glibc 运行时")
            return None

        try:
            with open(deb, "rb") as f:
                data, _ = extract_deb_data_tar(f.read())
            if not data:
                self.log_append("[-] [glibc] 解包失败 (非 xz? )")
                return None
            with tarfile.open(fileobj=io.BytesIO(data)) as t:
                # 只要运行态: usr/lib/x86_64-linux-gnu (含 libc/ld/nss/gconv), 丢弃 doc/lintian
                for m in t.getmembers():
                    if m.name.startswith("./usr/lib/x86_64-linux-gnu"):
                        t.extract(m, stage, numeric_owner=True)
            # 实体文件设为可执行(loader/libc), 防提取后丢执行位
            for root, _, files in os.walk(stage):
                for fl in files:
                    p = os.path.join(root, fl)
                    try:
                        os.chmod(p, 0o755)
                    except Exception: pass
            # 打包: 顶层为 usr/ (解到 /userdata/system/glibc 得到 usr/lib/x86_64-linux-gnu/...)
            with tarfile.open(tar_path, "w:gz") as out:
                usr_dir = os.path.join(stage, "usr")
                if os.path.isdir(usr_dir):
                    out.add(usr_dir, arcname="usr")
            self.log_append(f"[+] [glibc] 已生成 {self.GLIBC_TAR} (glibc 2.41 运行时, {os.path.getsize(tar_path)//1024//1024}MB)")
            return tar_path
        except Exception as ex:
            self.log_append(f"[-] [glibc] 打包异常: {ex}")
            return None

    def _ensure_va_driver_bundle(self, cache_dir):
        tar_path = os.path.join(cache_dir, "sunshine_va.tar.gz")
        if os.path.exists(tar_path) and os.path.getsize(tar_path) > 100000:
            self.log_append("[+] [VA驱动] 命中本地缓存: sunshine_va.tar.gz (0秒直传)")
            return tar_path

        debs = [
            ("libva2_2.7.0-2_amd64.deb", [
                "http://mirrors.aliyun.com/ubuntu/pool/universe/libv/libva/libva2_2.7.0-2_amd64.deb",
                "http://archive.ubuntu.com/ubuntu/pool/universe/libv/libva/libva2_2.7.0-2_amd64.deb",
            ]),
            ("libva-drm2_2.7.0-2_amd64.deb", [
                "http://mirrors.aliyun.com/ubuntu/pool/universe/libv/libva/libva-drm2_2.7.0-2_amd64.deb",
                "http://archive.ubuntu.com/ubuntu/pool/universe/libv/libva/libva-drm2_2.7.0-2_amd64.deb",
            ]),
            ("intel-media-va-driver_20.1.1+dfsg1-1_amd64.deb", [
                "http://mirrors.aliyun.com/ubuntu/pool/universe/i/intel-media-driver/intel-media-va-driver_20.1.1+dfsg1-1_amd64.deb",
                "http://archive.ubuntu.com/ubuntu/pool/universe/i/intel-media-driver/intel-media-va-driver_20.1.1+dfsg1-1_amd64.deb",
            ]),
            ("libigdgmm11_20.4.1+ds1-1_amd64.deb", [
                "http://mirrors.aliyun.com/debian/pool/main/i/intel-gmmlib/libigdgmm11_20.4.1+ds1-1_amd64.deb",
                "http://deb.debian.org/debian/pool/main/i/intel-gmmlib/libigdgmm11_20.4.1+ds1-1_amd64.deb",
            ]),
        ]

        stage = os.path.join(cache_dir, "va_stage")
        os.makedirs(stage, exist_ok=True)

        for name, urls in debs:
            dpath = os.path.join(stage, name)
            if _valid_deb(dpath): continue
            for u in urls:
                try:
                    host = u.split('/')[2]
                    self.log_append(f"[*] [VA驱动] 拉取 {name} <- {host} ...")
                    r = subprocess.run(["curl.exe", "-sSL", "-o", dpath, u], timeout=25)
                    if r.returncode == 0 and _valid_deb(dpath): break
                except Exception: continue

        wanted = ("libva.so", "libva-drm.so", "libigdgmm.so", "iHD_drv_video.so")
        src_root = os.path.join(stage, "usr", "lib", "x86_64-linux-gnu")
        if os.path.isdir(src_root):
            shutil.rmtree(src_root, ignore_errors=True)
        os.makedirs(src_root, exist_ok=True)

        for name, _ in debs:
            dpath = os.path.join(stage, name)
            if not os.path.exists(dpath): continue
            try:
                with open(dpath, "rb") as f: deb = f.read()
                data, _ = extract_deb_data_tar(deb)
                if not data: continue
                with tarfile.open(fileobj=io.BytesIO(data)) as t:
                    for m in t.getmembers():
                        if any(w in m.name for w in wanted) and "x86_64-linux-gnu" in m.name:
                            t.extract(m, stage, numeric_owner=True)
            except Exception: pass

        with tarfile.open(tar_path, "w:gz") as out:
            for root, _, files in os.walk(src_root):
                for fl in files:
                    full = os.path.join(root, fl)
                    arc = os.path.relpath(full, src_root)
                    out.add(full, arcname=arc)
        self.log_append(f"[+] [VA驱动] 已生成 sunshine_va.tar.gz ({os.path.getsize(tar_path)} 字节)")
        return tar_path

    def _ensure_local_appimage(self):
        cache_dir = get_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)
        local_glibc231 = os.path.join(cache_dir, "sunshine_glibc231.AppImage")
        local_latest = os.path.join(cache_dir, "sunshine.AppImage")

        self._ensure_all_dep_libs(cache_dir)

        if os.path.exists(local_glibc231) and os.path.getsize(local_glibc231) > 30 * 1024 * 1024:
            self.log_append(f"[+] [第1步] 命中本地 glibc2.31 兼容引擎缓存: {os.path.basename(local_glibc231)} (0秒直传)")
            return local_glibc231

        if os.path.exists(local_latest) and os.path.getsize(local_latest) > 30 * 1024 * 1024:
            self.log_append(f"[+] [第1步] 命中本地 Sunshine 引擎缓存: {os.path.basename(local_latest)} (注意: 最新版需 glibc>=2.34，老系统可能报错)")
            return local_latest

        local_bin = local_latest
        self.log_append("[*] [第1步] 正在通过高速通道下载 Sunshine 引擎 (~42MB)...")
        mirrors = [
            "https://gh-proxy.com/https://github.com/LizardByte/Sunshine/releases/latest/download/sunshine.AppImage",
            "https://githubfast.com/LizardByte/Sunshine/releases/latest/download/sunshine.AppImage",
            "https://mirror.ghproxy.com/https://github.com/LizardByte/Sunshine/releases/latest/download/sunshine.AppImage",
            "https://github.com/LizardByte/Sunshine/releases/latest/download/sunshine.AppImage"
        ]

        tmp_bin = local_bin + ".tmp"
        success = False
        for url in mirrors:
            if self.is_closed: return None
            try:
                host_label = url.split('/')[2]
                self.log_append(f"[*] 直连加速节点: {host_label} ...")
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=12) as resp, open(tmp_bin, 'wb') as out_f:
                    total_size = int(resp.headers.get('Content-Length', 44000000))
                    downloaded = 0
                    while True:
                        if self.is_closed: return None
                        chunk = resp.read(128 * 1024)
                        if not chunk: break
                        out_f.write(chunk)
                        downloaded += len(chunk)
                        pct = (downloaded / total_size) * 100
                        curr_mb = downloaded / (1024 * 1024)
                        tot_mb = total_size / (1024 * 1024)
                        self.update_progress(pct, f"📥 [正在下载引擎] {pct:.1f}% ({curr_mb:.1f} MB / {tot_mb:.1f} MB)")

                if os.path.exists(tmp_bin) and os.path.getsize(tmp_bin) > 30 * 1024 * 1024:
                    if os.path.exists(local_bin): os.remove(local_bin)
                    os.rename(tmp_bin, local_bin)
                    success = True
                    self.log_append("[+] 🎉 Sunshine 引擎下载完成并加入本地永久缓存！")
                    break
            except Exception as e:
                self.log_append(f"[-] 节点尝试提示 ({host_label}): {e}")
                if os.path.exists(tmp_bin):
                    try: os.remove(tmp_bin)
                    except Exception: pass
                continue

        if not success:
            raise Exception("所有国内加速节点连接超时，请检查外网连接！")
        return local_bin

    PULSE_DEB_NAMES = [
        "pulseaudio","pulseaudio-utils","libpulse0","libpulsedsp",
        "libsndfile1","libtdb1","libltdl7","libcap2","libdbus-1-3",
        "libice6","libsm6","libxtst6","libx11-6","libxfixes3","libffi6",
        "libpcre3","libglib2.0-0","liblz4-1","libgcrypt20","libgpg-error0",
        "libtasn1-6","libgmp10","libcap-ng0","liblzma5","zlib1g","libasound2",
        "libasound2-plugins","libasyncns0","libspeexdsp1","libjson-c3",
        "liborc-0.4-0","libsystemd0","libsoxr0","libbsd0","libssl1.1","libidn11",
        "libtirpc3","libgssapi-krb5-2","libkrb5-3","libk5crypto3","libcom-err2",
        "libkeyutils1","libkrb5support0","libwrap0",
    ]

    def _extract_deb_bytes(self, deb_bytes, bin_dir, lib_dir):
        import lzma as _lzma
        if deb_bytes[:8] != b"!<arch>\n": return
        p = 8; data = None; dname = ""
        while p < len(deb_bytes):
            name = deb_bytes[p:p+16].decode("ascii", "ignore").strip()
            size = int(deb_bytes[p+48:p+58].decode("ascii", "ignore").strip() or 0)
            p += 60
            if name.startswith("data.tar"):
                data = deb_bytes[p:p+size]; dname = name; break
            p += size + (size % 2)
        if data is None: return
        if dname.endswith(".xz"): data = _lzma.decompress(data)
        elif dname.endswith(".gz"): data = gzip.decompress(data)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for m in tar.getmembers():
                if m.isdir(): continue
                nm = m.name
                base = os.path.basename(nm)
                if ("/bin/" in nm or "/sbin/" in nm) and not nm.endswith(".so") and "/modules/" not in nm:
                    t = os.path.join(bin_dir, base)
                    ef = tar.extractfile(m)
                    if ef: open(t, "wb").write(ef.read())
                if nm.endswith(".so") or re.search(r"\.so(\.\d+)*$", nm):
                    t = os.path.join(lib_dir, base)
                    ef = tar.extractfile(m)
                    if ef: open(t, "wb").write(ef.read())

    def _ensure_pulse_bundle(self, cache_dir):
        pulse_dir = os.path.join(cache_dir, "pulse_bundle")
        files = os.path.join(pulse_dir, "files")
        bin_dir = os.path.join(files, "bin"); lib_dir = os.path.join(files, "lib")
        os.makedirs(bin_dir, exist_ok=True); os.makedirs(lib_dir, exist_ok=True)
        
        # 兼容定位根目录与 modules 目录下的 pve_res
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        stub = os.path.join(root_dir, "pve_res", "stub_libnsl.so.1")
        if not os.path.exists(stub):
            stub = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pve_res", "stub_libnsl.so.1")

        # 命中已解包缓存判断 (包含 50 个以上运行库即视为完整命中)
        if os.path.exists(os.path.join(lib_dir, "libpulse.so.0")) and len(os.listdir(lib_dir)) >= 50:
            if os.path.exists(stub):
                shutil.copy(stub, os.path.join(lib_dir, "libnsl.so.1"))
            self.log_append(f"[+] [音频运行包] 命中本地完整解包缓存 ({len(os.listdir(lib_dir))} 个动态库，0秒直传)")
            return files

        self.log_append("[*] 正在准备 PulseAudio 运行包 (Debian 10 buster, 兼容 glibc 2.30)...")
        mirror = "https://mirrors.aliyun.com/debian-archive/debian"
        idx_url = mirror + "/dists/buster/main/binary-amd64/Packages.gz"
        idx = os.path.join(pulse_dir, "Packages.gz")
        def _valid_gz(p):
            try: return open(p, "rb").read(2) == b"\x1f\x8b"
            except Exception: return False
        if not (_valid_gz(idx) and os.path.getsize(idx) > 100000):
            if not _fetch_url(idx_url, idx, timeout=120):
                raise Exception("PulseAudio 索引下载失败，请检查网络")
        pkgs = {}
        with gzip.open(idx, "rt", encoding="utf-8", errors="ignore") as f:
            for blk in f.read().split("\n\n"):
                n = re.search(r"^Package: (.+)$", blk, re.M)
                fn = re.search(r"^Filename: (.+)$", blk, re.M)
                sz = re.search(r"^Size: (\d+)$", blk, re.M)
                if n and fn:
                    pkgs.setdefault(n.group(1), (fn.group(1), int(sz.group(1)) if sz else 0))
        total_p = len(self.PULSE_DEB_NAMES)
        for p_i, pkg in enumerate(self.PULSE_DEB_NAMES):
            ent = pkgs.get(pkg)
            if not ent: continue
            fn, sz = ent
            deb = os.path.join(pulse_dir, os.path.basename(fn))
            if not _valid_deb(deb) or (sz and os.path.getsize(deb) != sz):
                if os.path.exists(deb):
                    try: os.remove(deb)
                    except Exception: pass
                self.log_append(f"[*] 下载音频依赖包 [{p_i+1}/{total_p}]: {pkg} ...")
                if not _fetch_url(mirror + "/" + fn, deb, timeout=300):
                    self.log_append(f"[-] 下载失败 {pkg}")
                    continue
            try:
                self._extract_deb_bytes(open(deb, "rb").read(), bin_dir, lib_dir)
            except Exception as ex:
                self.log_append(f"[-] 解包 {pkg} 异常: {ex}")
        if os.path.exists(stub):
            shutil.copy(stub, os.path.join(lib_dir, "libnsl.so.1"))
        else:
            self.log_append("[-] 缺少预编译 libnsl 桩 (pve_res/stub_libnsl.so.1), 音频可能无法启动")
        self.log_append(f"[+] PulseAudio 运行包就绪: {len(os.listdir(bin_dir))} 二进制 / {len(os.listdir(lib_dir))} 库")
        return files

    def _deploy_audio(self, ssh, bato_ip, force_card=False):
        """上传私有 PulseAudio。盒上已就绪则幂等跳过重传; 否则打单包走 HTTP 千兆秒传(与引擎包同路径),
        解决每次重部署都 SFTP 传 59MB + 盒端重解 200 文件的问题。"""
        cache_dir = get_pulse_cache_dir()
        files = self._ensure_pulse_bundle(cache_dir)
        run_sync_cmd(ssh, "mkdir -p /userdata/system/pulse /userdata/system/logs")

        local_bin_n = len(os.listdir(os.path.join(files, "bin")))
        local_lib_n = len(os.listdir(os.path.join(files, "lib")))
        _, probe, _ = run_sync_cmd(
            ssh,
            "b=$(ls /userdata/system/pulse/bin 2>/dev/null | wc -l); "
            "l=$(ls /userdata/system/pulse/lib 2>/dev/null | wc -l); echo \"$b/$l\"")
        have_bin = have_lib = 0
        if probe and "/" in probe:
            bb, ll = probe.strip().split("/")[:2]
            if bb.isdigit() and ll.isdigit():
                have_bin, have_lib = int(bb), int(ll)
        if have_bin >= local_bin_n and have_lib >= local_lib_n:
            self.log_append("[*] PulseAudio 运行包已就绪于盒子 (跳过重传, 直接重写 setup/system.pa)...")
        else:
            self.log_append("[*] 正在高速打包并上传 PulseAudio 运行包 (HTTP 千兆秒传)...")
            run_sync_cmd(ssh, "for p in $(pgrep -f pulseaudio); do kill -9 $p 2>/dev/null; done; sleep 1")
            tar_local = os.path.join(cache_dir, "pulse_files.tar.gz")
            # Windows 写盘的文件默认 0644 无 x 位; 打包时强制对 bin/ 命中即补执行位, 否则解到盒上 pulseaudio 无法运行。
            # 先写未压缩 tar, 再本地 gzip 压缩 (tarfile "w:gz" 与 addfile 混用会压缩失效 -> 文件仍可解但校验是 tar 非 gz)。
            tar_raw = os.path.join(cache_dir, "pulse_files.tar")
            with tarfile.open(tar_raw, "w") as t:
                for sub in ("bin", "lib"):
                    root = os.path.join(files, sub)
                    for dp, _, fns in os.walk(root):
                        for fn in fns:
                            fp = os.path.join(dp, fn)
                            try:
                                arc = os.path.join(sub, os.path.relpath(fp, root).replace(os.sep, "/"))
                                ti = t.gettarinfo(fp, arcname=arc)
                                if sub == "bin":
                                    ti.mode = (ti.mode or 0o0644) | 0o0111
                                if os.path.exists(fp):
                                    with open(fp, "rb") as _rf:
                                        t.addfile(ti, _rf)
                            except Exception:
                                pass
            with open(tar_raw, "rb") as _rf, gzip.open(tar_local, "wb") as _gz:
                shutil.copyfileobj(_rf, _gz)
            os.remove(tar_raw)
            self._http_upload_bato(tar_local, "/userdata/system/pulse/pulse_files.tar.gz", "PulseAudio 运行包", ssh, bato_ip)
            # BusyBox tar 1.31 不支持 -z; 用 gzip -dc | tar -xf - (GNU/BusyBox 通用); 解包失败不再 || true 吞错
            rc, out, _ = run_sync_cmd(ssh,
                "rm -rf /userdata/system/pulse/bin /userdata/system/pulse/lib; "
                "cd /userdata/system/pulse && gzip -dc pulse_files.tar.gz | tar -xf - && "
                "chmod 755 bin/pulseaudio bin/pactl && rm -f pulse_files.tar.gz && "
                "[ -x bin/pulseaudio ] && [ -x bin/pactl ] && ls bin | wc -l > /tmp/pb && echo EXTRACT_OK || echo EXTRACT_FAIL")
            if "EXTRACT_OK" not in out:
                self.log_append(f"[-] PulseAudio 解包校验失败: {out.strip()[-200:]}")
            else:
                self.log_append("[+] PulseAudio 运行包已秒级就绪 (210+ 二进制与库文件已解包)！")

        if force_card:
            self._no_sound_card = True
            self.log_append("[环境] 强制造卡模式: 启用 snd-dummy 虚拟声卡方案")
        else:
            _, probe, _ = run_sync_cmd(
                ssh,
                "NUM=$(cat /proc/asound/cards 2>/dev/null | grep -v -i dummy | grep -c '[0-9]'); "
                "[ \"$NUM\" -ge 1 ] 2>/dev/null && echo HAS_CARD || echo NO_CARD")
            self._no_sound_card = "NO_CARD" in probe
            self.log_append("[环境] 声卡检测: " + (
                "无硬件声卡 -> 启用 snd-dummy 虚拟声卡 + ES 前就绪 (修复音量 0 / 静电杂音)"
                if self._no_sound_card else
                "检测到硬件声卡 -> 保持 Pulse 路由"))

        sftp = ssh.open_sftp()
        # 方案2 (用户拍板): 有实体声卡 -> Pulse 先拿 hw:0, 本地声走 Pulse, 串流抓 monitor, 双路同源;
        # use_tsched=0 + fragments 修 VMWare HDA 'ALSA woke us up to write new data, nothing to write' 挂起 (POLLOUT)。
        # 无声卡(184)保持 null-sink 虚拟声卡现状, 不回归。
        if not self._no_sound_card:
            pa = (
                "load-module module-native-protocol-unix auth-anonymous=1\n"
                "load-module module-default-device-restore\n"
                "load-module module-always-sink\n"
                "load-module module-alsa-sink device=hw:0 sink_name=sink-sunshine-stereo sink_properties=device.description=SunshineSink rate=48000 channels=2 tsched=0 fragments=3 fragment_size=2048\n"
                "set-default-sink sink-sunshine-stereo\n"
                "set-default-source sink-sunshine-stereo.monitor\n"
            )
            asound_live = (
                "pcm.!default { type plug slave.pcm \"pulse\" }\n"
                "pcm.pulse { type pulse }\n"
                "ctl.!default { type pulse }\n"
                "ctl.pulse { type pulse }\n"
            )
            self.log_append("[环境] 检测到实体声卡 -> system.pa 用 alsa-sink(hw:0, tsched=0 + fragments) 本地+串流双路方案")
        else:
            pa = (
                "load-module module-native-protocol-unix auth-anonymous=1\n"
                "load-module module-default-device-restore\n"
                "load-module module-always-sink\n"
                "load-module module-null-sink sink_name=sink-sunshine-stereo sink_properties=device.description=SunshineSink rate=48000 channels=2\n"
                "set-default-sink sink-sunshine-stereo\n"
                "set-default-source sink-sunshine-stereo.monitor\n"
            )
            asound_live = "pcm.!default { type pulse }\nctl.!default { type pulse }\n"
        with sftp.file("/userdata/system/pulse/system.pa", "w") as f:
            f.write(pa)

        setup = (
            "#!/bin/sh\n"
            "if [ \"$1\" != \"force\" ]; then\n"
            "  if [ -S /var/run/pulse/native ]; then\n"
            "    LD_LIBRARY_PATH=/userdata/system/pulse/lib /userdata/system/pulse/bin/pactl --server=unix:/var/run/pulse/native info >/dev/null 2>&1 && exit 0\n"
            "  fi\n"
            "fi\n"
            "lock=/tmp/audio_setup.lock\n"
            "until mkdir $lock 2>/dev/null; do sleep 1; done\n"
            "trap 'rmdir $lock 2>/dev/null' EXIT\n"
            "grep -q '^pulse:' /etc/passwd || echo 'pulse:x:500:500:PulseAudio:/run/pulse:/bin/false' >> /etc/passwd\n"
            "grep -q '^pulse:' /etc/group || echo 'pulse:x:500:' >> /etc/group\n"
            "grep -q '^audio:' /etc/group || echo 'audio:x:29:' >> /etc/group\n"
            "sed -i 's/^audio:\\([^:]*\\):\\([0-9]*\\):.*/audio:\\1:\\2:pulse/' /etc/group 2>/dev/null\n"
            "chmod a+rw /dev/snd/* 2>/dev/null\n"
            "chmod 755 /userdata/system/pulse/bin/* 2>/dev/null\n"
            "mkdir -p /usr/lib/alsa-lib /usr/lib/x86_64-linux-gnu/alsa-lib\n"
            "cp -f /userdata/system/pulse/lib/libasound_module_pcm_pulse.so /userdata/system/pulse/lib/libasound_module_ctl_pulse.so /usr/lib/alsa-lib/ 2>/dev/null\n"
            "cp -f /userdata/system/pulse/lib/libasound_module_pcm_pulse.so /userdata/system/pulse/lib/libasound_module_ctl_pulse.so /usr/lib/x86_64-linux-gnu/alsa-lib/ 2>/dev/null\n"
            "cp -f /userdata/system/pulse/asound.conf /etc/asound.conf\n"
            "L=/userdata/system/pulse/lib; U=/usr/lib\n"
            "for so in libpulse.so.0 libpulse-simple.so.0 libpulsecommon-12.2.so libcap.so.2 libXtst.so.6 libICE.so.6 libSM.so.6 libX11-xcb.so.1 libXi.so.6 libXext.so.6 libasyncns.so.0 libsndfile.so.1 libsystemd.so.0 libwrap.so.0 libbsd.so.0 liblzma.so.5 liblz4.so.1 libgcrypt.so.20 libgpg-error.so.0 libjson-c.so.3 libltdl.so.7 libnsl.so.1; do [ -f $L/$so ] && [ ! -e $U/$so ] && cp -f $L/$so $U/ && chmod 755 $U/$so 2>/dev/null; done\n"
            "mkdir -p /run/pulse /var/run/pulse\n"
            "chown -R pulse:pulse /run/pulse /var/run/pulse 2>/dev/null\n"
            "chown -R pulse:pulse /userdata/system/pulse 2>/dev/null\n"
            "chmod -R a+rX /userdata/system/pulse\n"
            "export LD_LIBRARY_PATH=/userdata/system/pulse/lib\n"
            "export PATH=/userdata/system/pulse/bin:$PATH\n"
            "export PULSE_SERVER=unix:/var/run/pulse/native\n"
            "for p in $(pgrep -f pulseaudio); do kill -9 $p 2>/dev/null; done; sleep 1\n"
            "rm -f /var/run/pulse/pid /var/run/pulse/native\n"
            "nohup pulseaudio -n --system --file=/userdata/system/pulse/system.pa --exit-idle-time=-1 --disallow-exit --disallow-module-loading=false > /userdata/system/logs/pulse.log 2>&1 &\n"
            "i=0; while [ $i -lt 12 ]; do pactl info >/dev/null 2>&1 && break; sleep 1; i=$((i+1)); done\n"
            "pactl list short sinks 2>/dev/null | grep -q sink-sunshine-stereo || pactl load-module module-null-sink sink_name=sink-sunshine-stereo sink_properties=device.description=SunshineSink rate=48000 channels=2 2>/dev/null\n"
            "pactl set-default-sink sink-sunshine-stereo 2>/dev/null\n"
            "pactl set-default-source sink-sunshine-stereo.monitor 2>/dev/null\n"
            "pactl set-sink-volume sink-sunshine-stereo 100% 2>/dev/null\n"
            "echo AUDIO_OK\n"
        )
        with sftp.file("/userdata/system/pulse/audio_setup.sh", "w") as f:
            f.write(setup)
        sftp.chmod("/userdata/system/pulse/audio_setup.sh", 0o755)

        with sftp.file("/userdata/system/pulse/asound.conf", "w") as f:
            f.write(asound_live)
        with sftp.file("/etc/asound.conf", "w") as f:
            f.write(asound_live)

        ssh.exec_command("mkdir -p /userdata/system/.pulse")
        with sftp.file("/userdata/system/.pulse/client.conf", "w") as f:
            f.write("default-server = unix:/var/run/pulse/native\n")
        # 开机前置: custom.sh AUDIO_PREP (S99custom 守护) + .xinitrc AUDIO_PREES (X 会话内、ES 启动前先拿卡)
        self._write_custom_audio_prep(ssh, sftp, self._audio_boot_prep())
        self._install_xinitrc_prees(ssh, sftp)
        sftp.close()

        self.log_append("[*] 正在启动 PulseAudio 私有声卡...")
        code, out, _ = run_sync_cmd(ssh, "sh /userdata/system/pulse/audio_setup.sh force 2>&1 | tail -3")
        self.log_append(f"[audio] {out.strip()[:120]}")

        _, vout, _ = run_sync_cmd(ssh, "export LD_LIBRARY_PATH=/userdata/system/pulse/lib PATH=/userdata/system/pulse/bin:$PATH PULSE_SERVER=unix:/var/run/pulse/native; pactl list short sinks 2>&1")
        if "sunshine" in vout.lower():
            self.log_append("[+] 🔊 音频就绪: 已创建 Sunshine 虚拟声卡 (sink-sunshine-stereo)")

        # 缺库自愈: 老 Buildroot(如 200)系统 /usr/lib 缺 tcp-wrappers/libwrap 等, 导致 pulseaudio 起不来。
        # 用 LD_TRACE_LOADED_OBJECTS 探测缺失动态库 -> 从本地运行包 cache 匹配同名 so 补齐到盒上 pulse/lib,
        # 再 force 重启私有 Pulse + 校验 sink; 若 Sunshine 正在运行则自动 restart 让其重新连上 Pulse 音频。
        try:
            self._autofix_pulse_deps(ssh)
        except Exception as de2:
            self.log_append(f"[-] Pulse 缺库自愈异常: {de2}")

    def _autofix_pulse_deps(self, ssh):
        """探测盒上私有 Pulse 缺的动态库并自动补齐 (支持老 Buildroot 精简系统)。幂等: 无缺失即跳过, 不回归 184。"""
        import gzip as _gz
        cache_dir = get_pulse_cache_dir()
        lib_local = os.path.join(cache_dir, "pulse_bundle", "files", "lib")
        sftp = ssh.open_sftp()
        try:
            missing = set()
            for tool in ("pulseaudio", "pactl"):
                _, tr, _ = run_sync_cmd(ssh,
                    "LD_LIBRARY_PATH=/userdata/system/pulse/lib "
                    f"LD_TRACE_LOADED_OBJECTS=1 /userdata/system/pulse/bin/{tool} 2>&1 | grep -E 'not found'")
                for line in (tr or "").splitlines():
                    m = re.search(r"`?(\S+\.so[^\s`]*)`?\s*=>\s*not found", line)
                    if m:
                        missing.add(m.group(1))
            missing = {x for x in missing if x}
            if not missing:
                self.log_append("[+] Pulse 依赖完整, 无需补齐")
                return
            self.log_append(f"[*] 检出 Pulse 缺失动态库: {', '.join(sorted(missing))}, 正在从本地运行包补齐...")
            for so in sorted(missing):
                cand = None
                for f in os.listdir(lib_local):
                    b = os.path.basename(f)
                    if b == so or b.startswith(so + "."):
                        cand = os.path.join(lib_local, f)
                        break
                if not cand:
                    cand = os.path.join(lib_local, so)
                if not os.path.exists(cand):
                    self.log_append(f"[-] 本地运行包无 {so} (可在 PULSE_DEB_NAMES 补充对应 deb)")
                    continue
                # 以真实 soname 名落盘 (如 libwrap.so.0), 幂等覆盖
                sftp.put(cand, f"/userdata/system/pulse/lib/{so}")
                run_sync_cmd(ssh, f"chmod 755 /userdata/system/pulse/lib/{so} && echo OK_{so}")
                self.log_append(f"[+] 已补齐 {so}")
            # force 重启私有 Pulse 使其加载新库; 幂等脚本 socket 活即跳过, 这里 force 强制按最新 lib 重启
            try:
                _, out3, _ = run_sync_cmd(ssh, "sh /userdata/system/pulse/audio_setup.sh force 2>&1 | tail -3")
                if "AUDIO_OK" not in out3:
                    self.log_append(f"[-] Pulse 重启输出异常: {out3.strip()[:120]}")
            except Exception:
                pass
            # 校验 sink 是否已创建 (链路闭环)
            _, vout3, _ = run_sync_cmd(ssh,
                "export LD_LIBRARY_PATH=/userdata/system/pulse/lib PATH=/userdata/system/pulse/bin:$PATH "
                "PULSE_SERVER=unix:/var/run/pulse/native; pactl list short sinks 2>&1")
            if "sink-sunshine-stereo" in vout3:
                self.log_append("[+] 🔊 缺库修复后 Pulse 正常: sink-sunshine-stereo 在线")
            else:
                self.log_append(f"[-] 缺库修复后 sink 仍未出现: {vout3.strip()[:150]}")
            # Sunshine 在跑则自动重启, 让串流立刻接上音频 (pulse=true 需重启才建立 native 连接)
            _, runp, _ = run_sync_cmd(ssh, "pgrep -f 'usr/bin/sunshine' | head -1")
            if runp.strip():
                self.log_append("[*] Sunshine 正在运行, 正在自动重启以连接 Pulse 音频...")
                run_sync_cmd(ssh, "bash /userdata/system/services/sunshine restart >/dev/null 2>&1 || true")
                self.log_append("[+] Sunshine 已重启 (重新连接 Pulse 音频)")
        finally:
            sftp.close()

    def _audio_boot_prep(self):
        """开机/部署共用的 Pulse 前置片段: 用户组、/dev/snd 权限、ALSA 脉冲插件复制、asound.conf 重建、起服务(幂等)。"""
        return (
            "grep -q '^pulse:' /etc/passwd || echo 'pulse:x:500:500:PulseAudio:/run/pulse:/bin/false' >> /etc/passwd\n"
            "grep -q '^pulse:' /etc/group || echo 'pulse:x:500:' >> /etc/group\n"
            "grep -q '^audio:' /etc/group || echo 'audio:x:29:' >> /etc/group\n"
            "sed -i 's/^audio:\\([^:]*\\):\\([0-9]*\\):.*/audio:\\1:\\2:pulse/' /etc/group 2>/dev/null\n"
            "chmod a+rw /dev/snd/* 2>/dev/null\n"
            "# 实体声卡: 把 ALSA Master 拉满 100%(否则重启后 asound.state 恢复旧音量, 本地几乎无声; 串流抓 monitor 不受影响)\n"
            "amixer -c 0 set Master 100% 2>/dev/null; amixer -c 0 set Front 100% 2>/dev/null; alsactl -f /userdata/system/asound.state store 2>/dev/null\n"
            "mkdir -p /usr/lib/alsa-lib /usr/lib/x86_64-linux-gnu/alsa-lib\n"
            "cp -f /userdata/system/pulse/lib/libasound_module_pcm_pulse.so /userdata/system/pulse/lib/libasound_module_ctl_pulse.so /usr/lib/alsa-lib/ 2>/dev/null\n"
            "cp -f /userdata/system/pulse/lib/libasound_module_pcm_pulse.so /userdata/system/pulse/lib/libasound_module_ctl_pulse.so /usr/lib/x86_64-linux-gnu/alsa-lib/ 2>/dev/null\n"
            "cp -f /userdata/system/pulse/asound.conf /etc/asound.conf 2>/dev/null\n"
            "L=/userdata/system/pulse/lib; U=/usr/lib\n"
            "for so in libpulse.so.0 libpulse-simple.so.0 libpulsecommon-12.2.so libcap.so.2 libXtst.so.6 libICE.so.6 libSM.so.6 libX11-xcb.so.1 libXi.so.6 libXext.so.6 libasyncns.so.0 libsndfile.so.1 libsystemd.so.0 libwrap.so.0 libbsd.so.0 liblzma.so.5 liblz4.so.1 libgcrypt.so.20 libgpg-error.so.0 libjson-c.so.3 libltdl.so.7 libnsl.so.1; do [ -f $L/$so ] && [ ! -e $U/$so ] && cp -f $L/$so $U/ && chmod 755 $U/$so 2>/dev/null; done\n"
            "sh /userdata/system/pulse/audio_setup.sh >/dev/null 2>&1 || true\n"
        )

    def _write_custom_audio_prep(self, ssh, sftp, body):
        """以 # AUDIO_PREP begin/end 块幂等写入 custom.sh: S99custom 在 X 之后跑, 每次开机重建
        /etc/asound.conf + ALSA 脉冲插件 + 用户组/设备权限, 并调 audio_setup.sh 兜底 (幂等, 不产生双启动)。"""
        tag = "AUDIO_PREP"
        try:
            with sftp.file("/userdata/system/custom.sh", "r") as f:
                cur = f.read().decode("utf-8", "replace")
        except Exception:
            cur = ""
        cur2 = re.sub(r"(?ms)^# %s begin.*?^# %s end\s*\n" % (tag, tag), "", cur)
        block = "\n# %s begin\n%s# %s end\n" % (tag, body, tag)
        new = (cur2.rstrip("\n") + block) if cur2.strip() else block.lstrip("\n")
        with sftp.file("/userdata/system/custom.sh", "w") as f:
            f.write(new)
        self.log_append("[+] custom.sh 已写入 AUDIO_PREP 前置块 (开机重建 asound.conf/脉冲插件/音频前置)")

    def _install_xinitrc_prees(self, ssh, sftp):
        """在 /userdata/system/.xinitrc 的 openbox 启动行前注入 AUDIO_PREES, 让私有 Pulse 先于 ES 拿到 hw:0
        (本地声+串流双路闭环)。尽量以盒上库存 /etc/X11/xinit/xinitrc 为基底, 零再构风险; 已有用户 xinitrc 则仅注入块不覆盖。"""
        tag = "AUDIO_PREES"
        try:
            with sftp.file("/userdata/system/.xinitrc", "r") as f:
                cur = f.read().decode("utf-8", "replace")
        except Exception:
            try:
                with sftp.file("/etc/X11/xinit/xinitrc", "r") as f:
                    cur = f.read().decode("utf-8", "replace")
            except Exception:
                cur = ""
        body = self._audio_boot_prep() + (
            'i=0; while [ $i -lt 15 ]; do '
            '/userdata/system/pulse/bin/pactl --server=unix:/var/run/pulse/native list short sinks 2>/dev/null | '
            'grep -q sink-sunshine-stereo && break; sleep 1; i=$((i+1)); done\n'
        )
        block = "# %s begin\n%s# %s end\n" % (tag, body, tag)
        if tag in cur:
            cur = re.sub(r"(?ms)^# %s begin.*?^# %s end\s*\n" % (tag, tag), "", cur)
        if re.search(r"(?m)^\s*openbox\b", cur):
            new = re.sub(r"(?m)^(\s*openbox\b)", lambda m: block + m.group(1), cur, count=1)
        else:
            new = cur.rstrip("\n") + "\n" + block
        with sftp.file("/userdata/system/.xinitrc", "w") as f:
            f.write(new)
        sftp.chmod("/userdata/system/.xinitrc", 0o755)
        self.log_append("[+] .xinitrc 已注入 AUDIO_PREES (Pulse 先于 ES 取卡, 双路音频闭环)")

    _XINITRC_TEMPLATE = (
        "#!/bin/sh\n"
        "unclutter --noevents -b\n"
        'systemsetting="python /usr/lib/python2.7/site-packages/configgen/settings/batoceraSettings.py"\n'
        'settings_lang="`$systemsetting -command load -key system.language`"\n'
        'map_name=$(echo $settings_lang | cut -c 1-2)\n'
        "setxkbmap \"${map_name}\"\n"
        "xset -dpms\nxset s off\n"
        "export HOME=/userdata/system\n"
        "export LC_ALL=\"${settings_lang}.UTF-8\"\n"
        "export LANG=${LC_ALL}\n"
        "export PULSE_SERVER=unix:/var/run/pulse/native\n"
        "export LD_LIBRARY_PATH=/userdata/system/pulse/lib:$LD_LIBRARY_PATH\n"
        'settings_output="`$systemsetting -command load -key global.videooutput`"\n'
        "batocera-resolution setOutput \"${settings_output}\"\n"
        'settings_output="`$systemsetting -command load -key global.dpi`"\n'
        "[ ! -z \"${settings_output}\" ] && batocera-resolution setDPI \"${settings_output}\"\n"
        'settings_output="`$systemsetting -command load -key global.videomode`"\n'
        "[ ! -z \"${settings_output}\" ] && batocera-resolution setMode \"${settings_output}\"\n"
        "batocera-resolution minTomaxResolution\n"
        "ulimit -H -c unlimited\nulimit -S -c unlimited emulationstation\n"
        "cd /userdata\n"
        'openbox --config-file /etc/openbox/rc.xml --startup \"emulationstation --windowed\"\n'
    )

    def _deploy_test_panel(self, ssh):
        sftp = ssh.open_sftp()
        with sftp.open("/userdata/system/test_panel.py", "w") as f:
            f.write(_TEST_PANEL_SRC.encode("utf-8"))
        self.log_append("[*] 已上传 Python 测试面板脚本 /userdata/system/test_panel.py")
        self.log_append("[*] 正在确保盒上 Python (存在则强制覆盖)...")
        run_sync_cmd(ssh, "rm -rf /userdata/system/python")
        _, cached, _ = run_sync_cmd(ssh, "ls -l /tmp/py3.tar.gz 2>/dev/null && echo CACHED || echo NOCACHE")
        if "CACHED" not in cached:
            self.log_append("[*] 盒上无缓存的 Python 包, 正在下载便携 Python 3.11 (约40MB, 自带 tcl/tk)...")
            run_sync_cmd(ssh,
                "mkdir -p /userdata/system && cd /userdata/system && "
                "curl -L -o /tmp/py3.tar.gz 'https://github.com/astral-sh/python-build-standalone/releases/download/20260825/cpython-3.11.16+20260825-x86_64-unknown-linux-gnu-install_only.tar.gz' && echo DL_OK")
        run_sync_cmd(ssh, "cd /userdata/system && gzip -dc /tmp/py3.tar.gz | tar -xf - && echo PY_OK")
        sftp.close()

    def _fix_music_sample_rates(self, ssh):
        """扫描 /userdata/music 下所有 mp3, 将非 44100Hz 的 (会导致 ES 音频卡死/黑屏, 比如 48kHz)
        自动转码为 44100Hz/192k CBR。幂等: 采样率全为标准则跳过。走 ffmpeg 先写 .conv.mp3 再原子替换, 原文件不留。"""
        try:
            sftp = ssh.open_sftp()
            try:
                names = sftp.listdir("/userdata/music")
            except IOError:
                self.log_append("[-] /userdata/music 不存在, 跳过音频采样率修复)")
                sftp.close()
                return
            try:
                names = [n for n in names]
                mp3s = sorted(n for n in names if n.lower().endswith(".mp3"))
            except Exception:
                sftp.close()
                return
            if not mp3s:
                sftp.close()
                return
            self.log_append(f"[*] 检查 {len(mp3s)} 个 mp3 采样率 (标准: 44100Hz, 防 ES 卡死)...")
            RATES = {0: 44100, 1: 48000, 2: 32000}
            RATES2 = {0: 22050, 1: 24000, 2: 16000}

            def _probe(buf):
                start = 0
                if buf[0:3] == b"ID3":
                    sz = ((buf[6] & 0x7F) << 21) | ((buf[7] & 0x7F) << 14) | ((buf[8] & 0x7F) << 7) | (buf[9] & 0x7F)
                    start = 10 + sz
                for i in range(start, len(buf) - 4):
                    if buf[i] == 0xFF and (buf[i + 1] & 0xE0) == 0xE0 and (buf[i + 1] & 0x06) != 0:
                        br = (buf[i + 2] & 0xF0) >> 4
                        sr = (buf[i + 2] & 0x0C) >> 2
                        v = (buf[i + 1] & 0x18) >> 3
                        if br not in (0, 15) and sr != 3:
                            return {3: RATES, 2: RATES2, 0: RATES2}[v].get(sr)
                return None

            bad = []
            for n in mp3s:
                try:
                    f = sftp.open("/userdata/music/" + n, "rb")
                    f.prefetch()
                    data = f.read(1 << 20)
                    f.close()
                    hz = _probe(data)
                    if hz and hz != 44100:
                        bad.append((n, hz))
                except (IOError, OSError):
                    pass
            if not bad:
                self.log_append("[+] 所有 mp3 均为 44100Hz, 无需转码")
                sftp.close()
                return
            for n, hz in bad:
                self.log_append(f"[-] {n} 是 {hz}Hz, 正在转码 44100Hz/192k...")
                q = n.replace("'", "'\\''")
                p = "/userdata/music/" + n
                rc2, out2, _ = run_sync_cmd(ssh,
                    f"ffmpeg -nostdin -y -i '{q}' -ar 44100 -ac 2 -b:a 192k -acodec libmp3lame '{q}.conv.mp3' 2>&1 | tail -2")
                if rc2 not in (0, None):
                    self.log_append(f"[-] 转码失败: {out2.strip()}")
                    continue
                run_sync_cmd(ssh, f"mv -f '{p}.conv.mp3' '{p}'")
                self.log_append(f"[+] {n} 已替换为 44100Hz (跳过未来 ES 卡死)")
            sftp.close()
        except Exception as ex:
            self.log_append(f"[-] mp3 采样率修复异常 (非致命, 跳过): {ex}")

    def _ensure_sunshine_boot(self, ssh):
        _, custom, _ = run_sync_cmd(ssh, "cat /userdata/system/custom.sh 2>/dev/null")
        if "SUNSHINE_BOOT" not in custom:
            append = (
                "\n# SUNSHINE_BOOT begin (由部署工具添加: 开机等待 X 会话就绪后自启串流服务)\n"
                "( for i in $(seq 1 60); do [ -S /tmp/.X11-unix/X0 ] && break; sleep 1; done\n"
                "  bash /userdata/system/services/sunshine start >/userdata/system/logs/sunshine_boot.log 2>&1\n"
                ") &\n"
                "# SUNSHINE_BOOT end\n"
            )
            run_sync_cmd(ssh, f"printf '%s' '{append}' >> /userdata/system/custom.sh")
            self.log_append("[+] 已在 custom.sh 注入 Sunshine 开机自启")
