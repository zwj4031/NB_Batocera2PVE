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
import pve_bato_net
from concurrent.futures import ThreadPoolExecutor
import random
import string
import json
import ssl
import base64
import gzip
import shutil
import secrets
import http.server
import socketserver
import urllib.parse

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
import pve_bato_net

class _ReusableThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

class _BatoHTTPHandler(http.server.BaseHTTPRequestHandler):
    """单文件高速直传 Handler: 支持 HTTP/1.1、显式 Content-Length 与 64KB 平滑切片。"""
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        self.server.hits = getattr(self.server, "hits", 0) + 1
        decoded = urllib.parse.unquote(self.path)
        if decoded != self.server.allowed:
            self.send_error(404, "File not allowed")
            return
        try:
            filepath = self.server.filepath
            if not os.path.exists(filepath):
                self.send_error(404, "Local file not found")
                return
            size = os.path.getsize(filepath)
            self.send_response(200)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.server.transferred = getattr(self.server, "transferred", 0) + len(chunk)
            self.wfile.flush()
        except Exception as e:
            try:
                self.send_error(500, str(e))
            except Exception:
                pass

    def log_message(self, *args):
        pass

class _DeployInstallMixin:
    def _local_ip_to(self, remote_ip):
        """向对端 IP 建立 UDP 连接确定本机源 IP (盒子可访问的下发主机地址)。"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((remote_ip, 22))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return "127.0.0.1"

    def _http_upload_bato(self, local_file, remote_tmp, source_name, bato_ssh, bato_ip):
        """本机开临时 HTTP 服务, Batocera 盒子 curl 高速拉取 (64KB 切片流式传输), 用后即关。"""
        pc_ip = self._local_ip_to(bato_ip)
        port = 8765
        srv = None
        for p in range(8765, 8900):
            try:
                srv = _ReusableThreadingServer(("0.0.0.0", p), _BatoHTTPHandler)
                port = p
                break
            except OSError:
                continue
        if not srv:
            raise Exception("无法在本地绑定 HTTP 端口 (8765-8900 均被占用)")

        token = secrets.token_hex(8)
        basename = os.path.basename(local_file)
        srv.filepath = local_file
        srv.allowed = f"/{token}/{basename}"
        srv.hits = 0
        srv.transferred = 0

        srv_thread = threading.Thread(target=srv.serve_forever, daemon=True)
        srv_thread.start()

        quoted = urllib.parse.quote(f"/{token}/{basename}")
        url = f"http://{pc_ip}:{port}{quoted}"
        total = os.path.getsize(local_file)
        self.log_append(f"[*] 本机 HTTP 服务已就绪: http://{pc_ip}:{port}/{token}/... (千兆秒传 {source_name})")

        done = threading.Event()
        curl_res = {}

        def run_curl():
            try:
                cmd = f"curl -fSL --connect-timeout 10 --retry 2 -o '{remote_tmp}' '{url}' 2>&1 || wget -q -O '{remote_tmp}' '{url}' 2>&1"
                code, out, err = run_sync_cmd(bato_ssh, cmd)
                curl_res["code"] = code
                curl_res["out"] = out + (" " + err if err else "")
            except Exception as e:
                curl_res["exc"] = str(e)
            finally:
                done.set()

        threading.Thread(target=run_curl, daemon=True).start()

        while not done.is_set():
            sz = getattr(srv, "transferred", 0)
            pct = min(99, int(sz / total * 100)) if total else 0
            curr_mb = sz / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            self.update_progress(30 + int(pct * 0.25), f"📤 HTTP 上传 {source_name}: {pct}% ({curr_mb:.1f}/{tot_mb:.1f}MB)")
            time.sleep(0.15)

        done.wait(timeout=60)
        try:
            srv.shutdown()
            srv.server_close()
        except Exception:
            pass

        # 兼容 BusyBox / Linux 全环境的字节数精确读取
        _, final_out, _ = run_sync_cmd(bato_ssh, f"wc -c < '{remote_tmp}' 2>/dev/null || stat -c %s '{remote_tmp}' 2>/dev/null || ls -ln '{remote_tmp}' 2>/dev/null | awk '{{print $5}}' || echo 0")
        final = int((final_out or "0").strip().splitlines()[-1].strip() or 0)

        if final != total:
            detail = curl_res.get("exc") or curl_res.get("out") or ""
            raise Exception(f"HTTP 下载校验失败: 本地 {total} 字节, 盒子端 {final} 字节 [hits={getattr(srv,'hits',0)}] {detail}")

    def start_install(self):
        bato_ip = self.entry_bato_ip.get().strip()
        bato_pwd = self.entry_bato_pwd.get().strip()
        if not bato_ip:
            messagebox.showwarning("提示", "请填写 Batocera IPv4 地址！")
            return

        self.btn_start.config(state="disabled")
        self.update_progress(5, "正在启动全透明部署流程...")
        self.txt_log.delete("1.0", tk.END)

        service_script = """#!/bin/bash
export HOME=/userdata/system
mkdir -p /userdata/system/services /userdata/system/logs /userdata/system/configs/sunshine
SUNSHINE_DIR="/userdata/system/sunshine_app"
GLIBC_DIR="/userdata/system/glibc/usr/lib/x86_64-linux-gnu"

export DISPLAY=:0
XAUTH=/var/lib/.Xauthority
[ -s "$XAUTH" ] || XAUTH=$(find /userdata/system -maxdepth 1 -name '.serverauth.*' 2>/dev/null | head -n 1)
[ -s "$XAUTH" ] || XAUTH=$(find /tmp -maxdepth 2 -name '.X11-unix' -prune -o -name 'Xauthority' -print 2>/dev/null | head -n 1)
export XAUTHORITY="$XAUTH"

PULSE_SOCK=$(find /tmp/ -name "native" 2>/dev/null | head -n 1)
[ -n "$PULSE_SOCK" ] && export PULSE_SERVER="unix:$PULSE_SOCK"

export LD_LIBRARY_PATH="$SUNSHINE_DIR/usr/lib:$SUNSHINE_DIR/usr/lib/x86_64-linux-gnu:$SUNSHINE_DIR/lib:$SUNSHINE_DIR/lib/x86_64-linux-gnu:/userdata/system/va/lib:/userdata/system/pulse/lib:/usr/lib:/lib:$LD_LIBRARY_PATH"
export SUNSHINE_CONFIG_DIR="/userdata/system/configs/sunshine"
export PULSE_SERVER="unix:/var/run/pulse/native"
export LIBVA_DRIVER_NAME=iHD
export LIBVA_DRIVERS_PATH=/userdata/system/va/lib/dri
# 使用系统 gdk-pixbuf 的 PNG/JPEG loader 目录(含 libpixbufloader-png.so)，加载器缓存也指向系统。
# 原因：sunshine 自带 gdk-pixbuf 2.42.8 内置 PNG 解码在本环境不可用(实测解码返回 NULL ->
# "Unrecognized image file format" -> gtkiconhelper Bail out)，而系统 /usr/lib/libgdk_pixbuf-2.0.so.0
# (2.36.10) + /usr/lib/gdk-pixbuf-2.0/2.10.0/loaders 可正常解码 PNG。二者 ABI 兼容，故在
# _sun_launch 里用 env LD_PRELOAD 把系统 gdk-pixbuf 顶到最前(bundled gtk 照常链接它)。
# 注意：LD_PRELOAD 绝不能全局 export，否则会污染同 shell 里其它命令(实测 nohup 加载 bundled glib
# 报 GLIBC_2.33 not found)。只允许在拉起 sunshine 的那一行里以 env LD_PRELOAD=... 注入。
export GDK_BACKEND=x11
export XDG_DATA_DIRS=/usr/share:/usr/local/share

kill_sunshine() {
    for pid in $(ls /proc 2>/dev/null | grep -E '^[0-9]+$'); do
        if grep -q 'usr/bin/sunshine' /proc/$pid/cmdline 2>/dev/null; then
            kill -9 $pid 2>/dev/null
        fi
    done
    pkill -9 -f 'usr/bin/sunshine' 2>/dev/null || true
    pkill -9 -f AppRun 2>/dev/null || true
    fuser -k 47990/tcp 2>/dev/null || true
    fuser -k 48010/tcp 2>/dev/null || true
}

# 台账: 打包自带全套 lib (AppImage 自洽栈) 是否互斥禁用?
# 旧逻辑：总是禁用打包 libgdk_pixbuf/libva/EGL/gbm, 强制走盒上系统库。
#   在新盒(200, 老 Batocera 38)上, 系统库旧版本缺所需符号 -> symbol lookup error 启动崩。
#   实测用 sunshine 自带全套 lib(libgdk_pixbuf+libva+自己 glib)可正常启动(自洽栈)。
# 为避免影响其它 PVE 盒(如 184), 采用「检测后回退」：
#   ① 先用自带自洽栈启动; ② 若 sunshine 存活(进程+端口)就保持; ③ 否则自动退回旧的
#   "禁用打包 lib 走系统栈" 行为(与历史完全一致), 绝不影响既有用例。
_sun_alive() {
    pgrep -f 'usr/bin/sunshine' >/dev/null 2>&1 || pgrep -f 'AppRun' >/dev/null 2>&1 || return 1
    # 确认配置端口已监听 (busybox 用 /dev/tcp 探测)
    for p in 47984 47989 47990 48010; do
        (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null && { exec 3>&- 3<&-; return 0; }
    done
    return 0
}
_sun_launch() {
    # 优先用系统 gdk-pixbuf(可解码 PNG)顶替 bundled 内置解码(实测 bundled 2.42.8 内建 PNG 在此环境返回 NULL -> Gtk crash)。
    # 只在能定位系统 gdk-pixbuf 时才注入 LD_PRELOAD; 找不到则按旧行为运行(bundled 自洽栈, 不回归 184)。
    # 注意: 一定要用单层 env LD_PRELOAD=... 传递, 绝不能把 LD_PRELOAD 全局 export(会污染同 shell 里
    # nohup/env 等命令: 它们先于 glibc loader 启动, bundled glib/vendor lib 会在系统 glibc 2.30 下被加载 -> GLIBC_2.3x not found)。
    SYS_GDK=""
    for cand in /usr/lib/libgdk_pixbuf-2.0.so.0 /usr/lib/x86_64-linux-gnu/libgdk_pixbuf-2.0.so.0 /lib/libgdk_pixbuf-2.0.so.0; do
        [ -e "$cand" ] && { SYS_GDK="$cand"; break; }
    done
    if [ -n "$SYS_GDK" ]; then
        if [ -d /usr/lib/gdk-pixbuf-2.0/2.10.0/loaders ] && [ -e /usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache ]; then
            export GDK_PIXBUF_MODULEDIR=/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders
            export GDK_PIXBUF_MODULE_FILE=/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache
        fi
        SUN_PRELOAD="$SYS_GDK"
    else
        SUN_PRELOAD=""
    fi
    if [ -f "$SUNSHINE_DIR/usr/bin/sunshine" ]; then
        if [ -x "$GLIBC_DIR/ld-linux-x86-64.so.2" ]; then
            nohup env LD_PRELOAD="$SUN_PRELOAD" LD_LIBRARY_PATH="$LD_LIBRARY_PATH" "$GLIBC_DIR/ld-linux-x86-64.so.2" --library-path "$GLIBC_DIR:$LD_LIBRARY_PATH" "$SUNSHINE_DIR/usr/bin/sunshine" >> /userdata/system/logs/sunshine.log 2>&1 &
        else
            nohup env LD_PRELOAD="$SUN_PRELOAD" LD_LIBRARY_PATH="$LD_LIBRARY_PATH" "$SUNSHINE_DIR/usr/bin/sunshine" >> /userdata/system/logs/sunshine.log 2>&1 &
        fi
    elif [ -f "$SUNSHINE_DIR/AppRun" ]; then
        nohup env LD_PRELOAD="$SUN_PRELOAD" LD_LIBRARY_PATH="$LD_LIBRARY_PATH" "$SUNSHINE_DIR/AppRun" >> /userdata/system/logs/sunshine.log 2>&1 &
    fi
}
_sun_mode_legacy() {
    # 历史行为: 禁用打包 lib, 走盒上系统栈
    for pat in libgdk_pixbuf-2.0.so.0 libva.so libva-drm.so libva-x11.so libva-glx.so libEGL.so libgbm.so; do
        for f in $(find "$SUNSHINE_DIR" -name "${pat}*" 2>/dev/null); do
            [ -e "$f.disabled" ] || mv -f "$f" "$f.disabled" 2>/dev/null
        done
    done
}
_sun_mode_bundled() {
    # 恢复打包自带 lib, 用自洽栈
    for f in $(find "$SUNSHINE_DIR" -name '*.disabled' 2>/dev/null); do
        cp -f "$f" "${f%.disabled}" 2>/dev/null
    done
}

case "$1" in
    start)
        kill_sunshine; sleep 1
        sh /userdata/system/pulse/audio_setup.sh > /userdata/system/logs/pulse_boot.log 2>&1 || true
        cd "$SUNSHINE_DIR" 2>/dev/null || cd /userdata/system
        if [ ! -e /dev/dri/renderD128 ]; then
            modprobe i915 force_probe=9a70 2>/dev/null || true
            sleep 1
        fi

        # ① 先用打包自洽栈
        _sun_mode_bundled
        echo "[+] 启动 Sunshine (打包自洽栈)..." > /userdata/system/logs/sunshine.log
        _sun_launch
        sleep 6
        if _sun_alive; then
            echo "[+] Sunshine 运行正常 (打包自洽栈)." >> /userdata/system/logs/sunshine.log
        else
            # ② 自带栈失败(符号缺失/库冲突), 自动退回旧系统栈, 不影响既有盒子
            echo "[-] 打包自洽栈启动未就绪, 自动回退系统栈..." >> /userdata/system/logs/sunshine.log
            kill_sunshine; sleep 1
            _sun_mode_legacy
            echo "[+] 回退启动 Sunshine (系统栈, 禁用打包 lib)..." >> /userdata/system/logs/sunshine.log
            _sun_launch
            sleep 6
        fi
        ;;
    stop)
        kill_sunshine
        ;;
    restart)
        $0 stop
        sleep 1
        $0 start
        ;;
    status)
        pgrep -f sunshine >/dev/null && echo "running" || echo "stopped"
        ;;
esac
"""

        def task():
            try:
                local_appimage = self._ensure_local_appimage()
                if not local_appimage: return

                cache_dir = os.path.dirname(local_appimage)
                local_tar_gz = self._ensure_all_dep_libs(cache_dir)
                # 最新 Sunshine 需 GLIBC_2.35+, 盒子系统 glibc 2.30 不够 => 打包独立新版 glibc 运行时
                local_glibc = self._ensure_glibc_runtime(cache_dir)

                self.log_append(f"[*] [第2步] 正在连接 Batocera SSH ({bato_ip}:22)...")
                bato_ssh = paramiko.SSHClient()
                bato_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                bato_ssh.connect(hostname=bato_ip, port=22, username="root", password=bato_pwd, timeout=10, banner_timeout=30, auth_timeout=30)
                self.log_append("[+] SSH 连接成功！")

                try:
                    _, ver_out, _ = run_sync_cmd(bato_ssh,
                        "cat /etc/batocera.version 2>/dev/null; "
                        "command -v batocera-version >/dev/null && batocera-version 2>/dev/null | head -1; "
                        "cat /usr/share/batocera/BATOCERA 2>/dev/null; "
                        "echo '---ARCH---'; uname -m; "
                        "echo '---OS---'; grep -E '^(NAME|VERSION)=' /etc/os-release 2>/dev/null")
                    vlines = [l.strip() for l in ver_out.splitlines() if l.strip()]
                    arch = "未知"; osname = ""
                    for i, l in enumerate(vlines):
                        if l == "---ARCH---" and i + 1 < len(vlines):
                            arch = vlines[i + 1]
                        if l == "---OS---" and i + 1 < len(vlines):
                            osname = vlines[i + 1]
                    bver = next((l for l in vlines if l not in ("---ARCH---", "---OS---")), "未知")
                    if bver == "未知" and osname:
                        bver = osname
                    self.log_append(f"[+] Batocera 版本: {bver} | 架构: {arch} | {osname}")
                    self.bato_version = bver
                    self.bato_arch = arch
                except Exception as ve:
                    self.log_append(f"[-] Batocera 版本识别失败: {ve}")

                _, run_out, _ = run_sync_cmd(bato_ssh,
                    "if [ -x /userdata/system/sunshine_app/usr/bin/sunshine ] && pgrep -f 'sunshine_app/usr/bin/sunshine' >/dev/null 2>&1; then echo RUNNING; "
                    "elif [ -x /userdata/system/sunshine/usr/bin/sunshine ] && pgrep -f 'sunshine/usr/bin/sunshine' >/dev/null 2>&1; then echo RUNNING; "
                    "else echo STOPPED; fi")
                if (run_out or "").strip().upper().startswith("RUNNING"):
                    self.log_append("[!] 检测到盒上 Sunshine 已在运行, 弹出处理选项...")
                    choice = self._ask_running_choice()
                    if choice == "cancel":
                        self.log_append("[*] 用户取消, 终止部署。")
                        bato_ssh.close()
                        self.update_progress(100, "已取消")
                        self.btn_start.config(state="normal")
                        return
                    if choice == "web":
                        self.log_append("[*] 用户选择直接访问 WEB 后台, 浏览器打开中...")
                        web_url = f"https://{bato_ip}:47990/"
                        try:
                            webbrowser.open(web_url)
                        except Exception:
                            pass
                        self.after(0, lambda u=web_url: self._open_web_creds_window(
                            self._load_creds().get("username", "admin"),
                            self._load_creds().get("password", ""),
                            bato_ip))
                        bato_ssh.close()
                        self.update_progress(100, "🌐 已在浏览器打开 WEB 后台")
                        self.btn_start.config(state="normal")
                        return
                    if choice == "restart":
                        self.log_append("[*] 用户选择杀掉并重启 Sunshine (保留现有部署)...")
                        self._restart_sunshine(bato_ssh, bato_ip)
                        bato_ssh.close()
                        self.update_progress(100, "🔄 Sunshine 已重启")
                        self.btn_start.config(state="normal")
                        return
                    if choice == "reset":
                        self.log_append("[*] 用户选择仅重置 Web 密码, 跳过重装...")
                        import random as _rnd, string as _str
                        fixed_pwd = self.entry_web_pwd.get().strip()
                        new_pwd = fixed_pwd if fixed_pwd else ''.join(_rnd.choices(_str.ascii_letters + _str.digits, k=12))
                        try:
                            self.entry_web_pwd.delete(0, tk.END)
                            self.entry_web_pwd.insert(0, new_pwd)
                        except Exception:
                            pass
                        code = self._apply_web_creds(bato_ssh, bato_ip, new_pwd)
                        bato_ssh.close()
                        self.update_progress(100, "✅ Web 密码已重置")
                        self.after(0, lambda c=code: self._open_web_creds_window("admin", new_pwd, bato_ip, verify_code=c))
                        self.btn_start.config(state="normal")
                        return
                    self.log_append("[*] 用户选择重新注入, 继续完整部署流程...")

                run_sync_cmd(bato_ssh, "for pid in $(ls /proc 2>/dev/null | grep -E '^[0-9]+$'); do if grep -q 'usr/bin/sunshine' /proc/$pid/cmdline 2>/dev/null; then kill -9 $pid 2>/dev/null; fi; done; pkill -9 -f 'usr/bin/sunshine' 2>/dev/null || true; pkill -9 -f AppRun 2>/dev/null || true; fuser -k 47990/tcp 2>/dev/null || true; rm -rf /userdata/system/sunshine_app /userdata/system/sunshine.AppImage /userdata/system/squashfs-root")

                self.log_append("[*] [第3步] 正在通过千兆局域网秒传 Sunshine 引擎与全量依赖包...")
                remote_appimage = "/userdata/system/sunshine.AppImage"
                remote_libs_tar = "/userdata/system/sunshine_libs.tar.gz"
                run_sync_cmd(bato_ssh, "mkdir -p /userdata/system/services /userdata/system/logs /userdata/system/configs/sunshine /userdata/system/va/lib/dri")

                self.log_append("[*] [第3.1步] 正在准备 Intel VAAPI 驱动栈 (libva 2.7.0 + iHD)...")
                local_va = self._ensure_va_driver_bundle(cache_dir)
                remote_va_tar = "/userdata/system/va.tar.gz"

                transfer_items = [
                    (local_appimage, remote_appimage, "Sunshine 引擎"),
                    (local_tar_gz, remote_libs_tar, "依赖库包"),
                ]
                if local_va and os.path.exists(local_va) and os.path.getsize(local_va) > 100000:
                    transfer_items.append((local_va, remote_va_tar, "VAAPI 驱动栈"))
                if local_glibc and os.path.exists(local_glibc) and os.path.getsize(local_glibc) > 1 * 1024 * 1024:
                    transfer_items.append((local_glibc, "/userdata/system/sunshine_glibc.tar.gz", "新版 glibc 运行时"))
                sftp = None
                for local_f, remote_f, label in transfer_items:
                    if not os.path.exists(local_f) or os.path.getsize(local_f) <= 0:
                        continue
                    try:
                        self._http_upload_bato(local_f, remote_f, label, bato_ssh, bato_ip)
                    except Exception as http_e:
                        if sftp is None:
                            sftp = bato_ssh.open_sftp()
                        self.log_append(f"[-] HTTP 上传 {label} 失败 ({http_e}), 回退 SFTP...")
                        sftp.put(local_f, remote_f)
                self.log_append("[+] 引擎与全量依赖包直推完成！")

                self.update_progress(75, "正在虚拟机内原地展开独立运行环境...")
                self.log_append("[*] [第4步] 正在展开独立运行目录 (AppImage extract 同步解包)...")
                extract_cmd = (
                    "chmod +x /userdata/system/sunshine.AppImage && "
                    "cd /userdata/system && "
                    "rm -rf squashfs-root sunshine_app && "
                    "./sunshine.AppImage --appimage-extract >/dev/null 2>&1 && "
                    "mv squashfs-root sunshine_app && "
                    "chmod +x sunshine_app/AppRun sunshine_app/usr/bin/sunshine 2>/dev/null && "
                    "rm -f sunshine.AppImage"
                )
                code, _, err = run_sync_cmd(bato_ssh, extract_cmd)
                if code != 0:
                    self.log_append(f"[-] AppImage 解包提示: {err}")

                self.update_progress(88, "正在精准注入 Batocera 缺失的宿主运行库...")
                self.log_append("[*] [第5步] 正在注入 Batocera 缺失的宿主运行库 (libstdc++/libp11-kit/libgpg-error/libdrm/Wayland/PipeWire)...")

                run_sync_cmd(bato_ssh, "mkdir -p /userdata/system/sunshine_app/usr/lib /userdata/system/sunshine_app/usr/lib/x86_64-linux-gnu /userdata/system/sunshine_app/lib")

                if sftp is None:
                    sftp = bato_ssh.open_sftp()
                all_so_list = [
                    "libstdc++.so.6", "libp11-kit.so.0", "libgpg-error.so.0", "libdrm.so.2",
                    "libwayland-client.so.0", "libwayland-cursor.so.0", "libwayland-egl.so.1",
                    "libpipewire-0.3.so.0", "libFLAC.so.8",
                    "libthai.so.0", "libdatrie.so.1",
                    "libffi.so.7", "libtasn1.so.6"
                ]
                for so_name in all_so_list:
                    local_f = os.path.join(cache_dir, so_name)
                    if os.path.exists(local_f) and os.path.getsize(local_f) > 0:
                        try:
                            sftp.put(local_f, f"/userdata/system/sunshine_app/usr/lib/{so_name}")
                            sftp.put(local_f, f"/userdata/system/sunshine_app/usr/lib/x86_64-linux-gnu/{so_name}")
                        except Exception: pass
                sftp.close()

                inject_cmd = (
                    "cd /userdata/system/sunshine_app/usr/lib && tar -zxf /userdata/system/sunshine_libs.tar.gz 2>/dev/null || true && "
                    "cd /userdata/system/sunshine_app/usr/lib/x86_64-linux-gnu && tar -zxf /userdata/system/sunshine_libs.tar.gz 2>/dev/null || true && "
                    "cd /userdata/system/sunshine_app/lib && tar -zxf /userdata/system/sunshine_libs.tar.gz 2>/dev/null || true && "
                    "cp -f /userdata/system/sunshine_app/usr/lib/*.so* /userdata/system/sunshine_app/usr/lib/x86_64-linux-gnu/ 2>/dev/null || true && "
                    "cp -f /userdata/system/sunshine_app/usr/lib/*.so* /userdata/system/sunshine_app/lib/ 2>/dev/null || true && "
                    "chmod 755 /userdata/system/sunshine_app/usr/lib/* /userdata/system/sunshine_app/usr/lib/x86_64-linux-gnu/* /userdata/system/sunshine_app/lib/* 2>/dev/null || true && "
                    "rm -f /userdata/system/sunshine_libs.tar.gz"
                )
                run_sync_cmd(bato_ssh, inject_cmd)

                self.update_progress(90, "正在部署 Intel VAAPI 驱动栈 (集显硬编码)...")
                self.log_append("[*] [第5.4步] 正在解包 Intel VAAPI 驱动栈 (libva 2.7.0 + iHD) ...")
                run_sync_cmd(bato_ssh, "mkdir -p /userdata/system/va/lib/dri && gzip -dc /userdata/system/va.tar.gz | tar -xf - -C /userdata/system/va/lib && chmod 755 /userdata/system/va/lib/* /userdata/system/va/lib/dri/* 2>/dev/null; rm -f /userdata/system/va.tar.gz")
                _, va_out, _ = run_sync_cmd(bato_ssh, "ls -lh /userdata/system/va/lib/ /userdata/system/va/lib/dri/ 2>/dev/null")
                self.log_append(f"[VAAPI 驱动栈状态]\n{va_out.strip()}")

                self.update_progress(92, "正在部署新版 glibc 运行时 + 修复 libva/Wayland 配套...")
                self.log_append("[*] [第5.6步] 解包新版 glibc 2.41 运行时, 用新 loader 拉起最新 Sunshine (主程序需 GLIBC_2.35)")
                glibc_cmd = (
                    "mkdir -p /userdata/system/glibc && "
                    "rm -rf /userdata/system/glibc/* && "
                    "cd /userdata/system/glibc && "
                    "gzip -dc /userdata/system/sunshine_glibc.tar.gz | tar xf - 2>/dev/null; "
                    "chmod 755 /userdata/system/glibc/usr/lib/x86_64-linux-gnu/*.so* 2>/dev/null; "
                    "chmod 755 /userdata/system/glibc/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2 2>/dev/null; "
                    "rm -f /userdata/system/sunshine_glibc.tar.gz"
                )
                run_sync_cmd(bato_ssh, glibc_cmd)
                _, gl_ver, _ = run_sync_cmd(bato_ssh, "/userdata/system/glibc/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2 --version 2>&1 | head -1")
                self.log_append(f"[新版 glibc loader] {gl_ver.strip()}")

                # 新版 libva: sunshine 自带 Ubuntu 22.04 版含 vaSyncBuffer(主程序硬引用),
                # 必须覆盖 va/lib 里 focal 2.7.0 旧版(缺该符号会 symbol lookup error)
                self.log_append("[*] 用 Sunshine 自带新版 libva(含 vaSyncBuffer) 覆盖 va/lib 旧版")
                libva_fix = (
                    "S=/userdata/system/sunshine_app; "
                    "if [ -f $S/usr/lib/libva.so.2 ]; then "
                    "cp -a $S/usr/lib/libva.so.2 /userdata/system/va/lib/libva.so.2.700.0 && "
                    "chmod 755 /userdata/system/va/lib/libva.so.2.700.0 && echo VA_OK; "
                    "else echo VA_NO_SRC; fi"
                )
                _, va_fix, _ = run_sync_cmd(bato_ssh, libva_fix)
                self.log_append(f"[libva 覆写] {va_fix.strip()}")

                # wayland: 确保 sunshine 三处 lib 目录的 libwayland-client 是含
                # wl_proxy_marshal_flags 的新版(1.18+), 否则 libgdk-3 绑定失败
                self.log_append("[*] 校验 sunshine 内置 libwayland-client 含 wl_proxy_marshal_flags")
                _, wl_check, _ = run_sync_cmd(bato_ssh,
                    "for d in /userdata/system/sunshine_app/usr/lib /userdata/system/sunshine_app/usr/lib/x86_64-linux-gnu /userdata/system/sunshine_app/lib; do "
                    "c=$(strings $d/libwayland-client.so.0 2>/dev/null | grep -c wl_proxy_marshal_flags); echo \"$d: count=$c\"; done")
                self.log_append(f"[wayland 校验]\n{wl_check.strip()}")

                auto_lib_sh = (
                    "#!/bin/sh\n"
                    "# 谨慎补链: 新版 Sunshine 用独立 glibc loader(--library-path)解析依赖,\n"
                    "# 系统 ldd(老 glibc)对这款二进制的 'not found' 大多是假阳性(由 loader 处理)。\n"
                    "# 因此只在少量已知目录内 find, 绝不 find / 全盘(老盒子会扫到 sshd 超时断链), 找不到就跳过。\n"
                    "cd /userdata/system/sunshine_app\n"
                    "BIN=./usr/bin/sunshine\n"
                    "SEARCH_DIRS='/usr/lib /usr/lib/x86_64-linux-gnu /lib /lib/x86_64-linux-gnu /usr/local/lib /userdata/system'\n"
                    "for i in 1 2 3 4 5; do\n"
                    "  miss=$(ldd \"$BIN\" 2>/dev/null | awk -F' => ' '/not found/{print $1}' | tr -d '\\t' | sort -u)\n"
                    "  [ -z \"$miss\" ] && break\n"
                    "  for L in $miss; do\n"
                    "    [ -z \"$L\" ] && continue\n"
                    "    fp=$(find $SEARCH_DIRS -maxdepth 4 -name \"${L}*\" 2>/dev/null | grep -v '/userdata/system/sunshine_app/' | head -1)\n"
                    "    if [ -n \"$fp\" ]; then\n"
                    "      cp -aL \"$fp\" ./usr/lib/ 2>/dev/null && echo \"[auto] 补链: $L <- $fp\"\n"
                    "    else\n"
                    "      echo \"[auto][跳过] $L (由 glibc loader 在运行期解析)\"\n"
                    "    fi\n"
                    "  done\n"
                    "done\n"
                    "ldconfig 2>/dev/null || true\n"
                )
                sftp_auto = bato_ssh.open_sftp()
                with sftp_auto.file("/userdata/system/sunshine_app/_autolib.sh", "w") as af:
                    af.write(auto_lib_sh)
                sftp_auto.close()
                run_sync_cmd(bato_ssh, "sh /userdata/system/sunshine_app/_autolib.sh; rm -f /userdata/system/sunshine_app/_autolib.sh")

                import random, string
                fixed_pwd = self.entry_web_pwd.get().strip()
                if fixed_pwd:
                    sunshine_pwd = fixed_pwd
                    self.log_append("[*] 使用固定 Web 管理密码 (用户在界面指定)")
                else:
                    sunshine_pwd = "batocera"

                try:
                    self.entry_web_pwd.delete(0, tk.END)
                    self.entry_web_pwd.insert(0, sunshine_pwd)
                except Exception:
                    pass
                creds_cmd = (
                    "export SUNSHINE_DIR=/userdata/system/sunshine_app; "
                    "export HOME=/userdata/system; "
                    "GLIBC_DIR=/userdata/system/glibc/usr/lib/x86_64-linux-gnu; "
                    "export LD_LIBRARY_PATH=\"$GLIBC_DIR:$SUNSHINE_DIR/usr/lib:$SUNSHINE_DIR/usr/lib/x86_64-linux-gnu:$SUNSHINE_DIR/lib:$SUNSHINE_DIR/lib/x86_64-linux-gnu:/usr/lib:/lib\"; "
                    "export SUNSHINE_CONFIG_DIR=/userdata/system/configs/sunshine; "
                    "rm -f /userdata/system/.config/sunshine/sunshine_state.json /root/.config/sunshine/sunshine_state.json 2>/dev/null; "
                    "cd /userdata/system/sunshine_app && "
                    "if [ -x \"$GLIBC_DIR/ld-linux-x86-64.so.2\" ]; then "
                    f"\"$GLIBC_DIR/ld-linux-x86-64.so.2\" --library-path \"$GLIBC_DIR:$LD_LIBRARY_PATH\" ./usr/bin/sunshine --creds admin {sunshine_pwd} 2>&1 || true; "
                    "else "
                    f"./usr/bin/sunshine --creds admin {sunshine_pwd} 2>&1 || true; "
                    "fi"
                )
                run_sync_cmd(bato_ssh, creds_cmd)
                self.save_web_creds("admin", sunshine_pwd, bato_ip)
                self.log_append(f"[+] [Web 管理账号] 用户名: admin   密码: {sunshine_pwd}   (已本地保存, 可点【🔑 显示 Web 密码】重现)")

                _, check_out, _ = run_sync_cmd(bato_ssh, "ls -lh /userdata/system/sunshine_app/usr/lib/libstdc++* /userdata/system/sunshine_app/usr/lib/libp11-kit* /userdata/system/sunshine_app/usr/lib/libdrm* /userdata/system/sunshine_app/usr/lib/libgpg-error* /userdata/system/sunshine_app/usr/lib/libpipewire* /userdata/system/sunshine_app/usr/lib/libwayland* /userdata/system/sunshine_app/usr/lib/libthai* /userdata/system/sunshine_app/usr/lib/libdatrie* 2>/dev/null")
                if not check_out:
                    _, check_out, _ = run_sync_cmd(bato_ssh, "ls -lh /userdata/system/sunshine_app/usr/lib/ 2>/dev/null")
                self.log_append(f"[运行库状态核验] \n{check_out.strip()}")
                _, miss_out, _ = run_sync_cmd(bato_ssh, "cd /userdata/system/sunshine_app && ldd ./usr/bin/sunshine 2>/dev/null | awk -F' => ' '/not found/{print $1}' | tr -d '\\t ' | sort -u")
                if miss_out.strip():
                    self.log_append(f"[!] 仍有缺失库 (需补充): {miss_out.strip()}")
                else:
                    self.log_append("[+] [ldd 核验] 全部共享库已解析, 无缺失")

                self.log_append("[*] [第6步] 写入守护脚本与开机自启配置...")
                sftp_serv = bato_ssh.open_sftp()
                with sftp_serv.file("/userdata/system/services/sunshine", "w") as f:
                    f.write(service_script)
                sftp_serv.close()

                run_sync_cmd(bato_ssh, "chmod +x /userdata/system/services/sunshine")
                try:
                    self._ensure_sunshine_boot(bato_ssh)
                except Exception as se:
                    self.log_append(f"[-] 开机自启注入异常: {se}")
                run_sync_cmd(
                    bato_ssh,
                    "grep -q 'system.sunshine.enabled' /userdata/system/batocera.conf && "
                    "sed -i 's/system.sunshine.enabled=.*/system.sunshine.enabled=0/' /userdata/system/batocera.conf || "
                    "echo 'system.sunshine.enabled=0' >> /userdata/system/batocera.conf"
                )
                run_sync_cmd(
                    bato_ssh,
                    "grep -q '^audio.device=' /userdata/system/batocera.conf && "
                    "sed -i 's/^audio.device=.*/audio.device=default/' /userdata/system/batocera.conf || "
                    "echo 'audio.device=default' >> /userdata/system/batocera.conf"
                )
                run_sync_cmd(
                    bato_ssh,
                    "grep -q '^audio.volume=' /userdata/system/batocera.conf || echo 'audio.volume=100' >> /userdata/system/batocera.conf; "
                    "grep -q '^audio.volume=0' /userdata/system/batocera.conf && sed -i 's/^audio.volume=0/audio.volume=100/' /userdata/system/batocera.conf"
                )

                self.log_append("[*] [第6.0.3步] 正在检测虚拟环境并全自动执行游戏防闪退加固...")
                try:
                    site_code = "import sys\nsys.setdefaultencoding('utf-8')\n"
                    b64_site = base64.b64encode(site_code.encode('utf-8')).decode('ascii')

                    _, core_probe, _ = run_sync_cmd(
                        bato_ssh,
                        "ls -1 /usr/lib/libretro/*mednafen*psx*.so /usr/lib/libretro/*pcsx_rearmed*.so /usr/lib/libretro/*duckstation*.so 2>/dev/null | head -n 1"
                    )
                    core_file = core_probe.strip()
                    core_cmd = ""
                    if core_file:
                        c_base = os.path.basename(core_file).replace("_libretro.so", "")
                        c_name = "mednafen_psx" if "mednafen" in c_base else c_base
                        core_cmd = f"echo 'psx.core={c_name}' >> /userdata/system/batocera.conf; "

                    auto_heal_cmd = (
                        f"echo '{b64_site}' | base64 -d > /userdata/system/sitecustomize.py && "
                        "cp -f /userdata/system/sitecustomize.py /usr/lib/python2.7/sitecustomize.py 2>/dev/null || true; "
                        "sed -i '/^global.shaderset=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "sed -i '/\\.shaderset=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "sed -i '/^global.bezel=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "sed -i '/\\.bezel=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "sed -i '/^psx.core=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "sed -i '/^global.retroarch.video_threaded=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "sed -i '/^global.retroarch.audio_driver=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "echo 'global.shaderset=none' >> /userdata/system/batocera.conf; "
                        "echo 'global.bezel=none' >> /userdata/system/batocera.conf; "
                        "echo 'global.retroarch.video_threaded=true' >> /userdata/system/batocera.conf; "
                        "echo 'global.retroarch.audio_driver=sdl2' >> /userdata/system/batocera.conf; "
                        f"{core_cmd}"
                        "grep -q 'PYTHON2_UTF8' /userdata/system/custom.sh 2>/dev/null || "
                        "printf '\\n# PYTHON2_UTF8 begin\\ncp -f /userdata/system/sitecustomize.py /usr/lib/python2.7/sitecustomize.py 2>/dev/null\\n# PYTHON2_UTF8 end\\n' >> /userdata/system/custom.sh; "
                        "echo AUTO_HEAL_DONE"
                    )
                    run_sync_cmd(bato_ssh, auto_heal_cmd)
                    self.log_append("[+] [自动加固] 已全自动完成游戏防闪退加固:\n    • 音频加固: global.retroarch.audio_driver=sdl2 (PVE无声卡0帧防崩溃)\n    • 编码加固: Python2 UTF-8 引擎就绪 (中文 ROM 名不再崩溃)\n    • 画质加固: 滤镜与边框重置为 none，开启多线程渲染")
                except Exception as he:
                    self.log_append(f"[-] 自动加固提示: {he}")

                sunshine_conf = (
                    "start-desktop = /usr/bin/emulationstation\n"
                    "minimize_to_tray = false\n"
                    "output_name = 0\n"
                    "pulse = true\n"
                )
                sftp_conf = bato_ssh.open_sftp()
                with sftp_conf.file("/userdata/system/configs/sunshine/sunshine.conf", "w") as cf:
                    cf.write(sunshine_conf)
                sftp_conf.close()
                self.log_append("[*] 已写入 sunshine.conf (start-desktop / 关闭托盘图标)")

                try:
                    self._deploy_audio(bato_ssh, bato_ip)
                except Exception as ae:
                    self.log_append(f"[-] 音频部署异常: {ae}")

                try:
                    self._fix_music_sample_rates(bato_ssh)
                except Exception as me:
                    self.log_append(f"[-] mp3 采样率检查异常: {me}")

                if getattr(self, "var_install_python", None) and self.var_install_python.get():
                    try:
                        self._deploy_test_panel(bato_ssh)
                    except Exception as te:
                        self.log_append(f"[-] 测试面板部署异常: {te}")
                else:
                    self.log_append("[-] 已跳过测试用 Python/测试面板 (未勾选可选项)")

                self.update_progress(95, "正在后台启动 Sunshine 串流服务...")
                self.log_append("[*] 正在后台拉起 Sunshine 串流守护进程...")
                run_sync_cmd(bato_ssh, "nohup /userdata/system/services/sunshine start > /userdata/system/logs/sunshine_boot.log 2>&1 &")

                started = False
                for sec in range(25):
                    if self.is_closed: break
                    time.sleep(1)
                    if self.is_port_open(bato_ip, 47990):
                        started = True
                        break
                    
                    if sec % 3 == 0:
                        try:
                            _, stdout_txt, _ = run_sync_cmd(bato_ssh, "tail -n 2 /userdata/system/logs/sunshine.log 2>/dev/null || true")
                            if stdout_txt:
                                self.log_append(f"[{sec}s] {stdout_txt.splitlines()[-1]}")
                        except Exception: pass

                if started and not self.is_closed:
                    code = self._verify_web_pwd_on_box(bato_ssh, sunshine_pwd)
                    if code == "200":
                        self.log_append("[+] [密码核验] Web 账号已生效, 可正常登录")
                    else:
                        self.log_append(f"[!] [密码核验] 返回 {code}, 若登录失败请点【🔄 重置 Web 密码】强制重设")

                bato_ssh.close()

                if started and not self.is_closed:
                    self.update_progress(100, "🎉 Sunshine 47990 端口已就绪！")
                    self.log_append("[+] 🎉 47990 端口监听成功！服务已完美就绪！")
                    url = f"https://{bato_ip}:47990/"
                    info = (
                        f"🎉 Sunshine 游戏串流服务已完全启动就绪！\n\n"
                        f"后台管理地址:\n{url}\n\n"
                        f"🔑 Web 管理账号:\n    用户名: admin\n    密码:   {sunshine_pwd}\n\n"
                        f"💡 关键提示:\n"
                        f"浏览器首次打开时若提示'您的连接不是私密连接/不安全'，"
                        f"请点击页面上的【高级】->【继续前往 (不安全)】即可顺利进入后台；\n"
                        f"随后在弹出的账号密码框中输入上述 admin 账号即可。\n\n"
                        f"是否立刻打开？"
                    )
                    if messagebox.askyesno("成功就绪", info):
                        webbrowser.open(url)
                elif not self.is_closed:
                    self.update_progress(100, "服务拉起完毕，请点击右下角测试进入")
                    self.log_append("[*] 已完成启动指令下发。可直接点击【🔄 刷新/进入后台】测试。")

            except Exception as e:
                err_msg = str(e)
                if not self.is_closed:
                    self.update_progress(0, f"[-] 部署失败: {err_msg[:30]}")
                    self.log_append(f"[-] 发生错误: {err_msg}")
            finally:
                if not self.is_closed:
                    try:
                        if self.winfo_exists(): self.after(0, lambda: self.btn_start.config(state="normal"))
                    except Exception: pass

        threading.Thread(target=task, daemon=True).start()
