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

def _valid_deb(path):
    try:
        return open(path, "rb").read(8) == b"!<arch>\n"
    except Exception:
        return False


def _fetch_url(url, out, timeout=300):
    try:
        r = subprocess.run(["curl.exe", "-sSL", "--retry", "3", "-o", out, url], timeout=timeout)
        return r.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 1000
    except Exception:
        return False

# Web 管理账号持久化文件 (随 cache/ 一起被 .gitignore 忽略, 不入库)
# 打包后 CREDS_DIR 必须指向可写目录(exe 同目录\cache), 否则部署保存凭据会写进只读 _MEIPASS
from pve_bundle import get_cache_dir as _get_cache_dir
CREDS_DIR = _get_cache_dir()
CREDS_FILE = os.path.join(CREDS_DIR, "sunshine_web_creds.txt")

def center_window(win, parent=None, width=580, height=560):
    """确保子窗口/弹窗精准在父窗口或主屏幕中央展示"""
    win.update_idletasks()
    if parent and parent.winfo_exists():
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        x = px + max(0, (pw - width) // 2)
        y = py + max(0, (ph - height) // 2)
    else:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")

def extract_deb_data_tar(deb_bytes):
    """纯 Python 解析 Debian/Ubuntu .deb 归档中的 data.tar.xz / data.tar.gz"""
    pos = 8
    while pos < len(deb_bytes):
        header = deb_bytes[pos:pos+60]
        if len(header) < 60: break
        name = header[:16].strip().decode('ascii', errors='ignore')
        size = int(header[48:58].strip().decode('ascii', errors='ignore'))
        pos += 60
        content = deb_bytes[pos:pos+size]
        pos += size
        if pos % 2 != 0: pos += 1
        if "data.tar" in name:
            return content, name
    return None, None

def run_sync_cmd(ssh_client, cmd, timeout=300):
    """同步阻塞执行远程 SSH 指令，确保每步严格顺序完成。

    ⚠️ 对 Channel closed / 超时等连接性异常做健壮兜底: 尽量读回已有输出,
    绝不因单条命令的网络抖动抛出异常把整个部署流程弄崩 (老版本会在
    recv_exit_status 处抛 SSHException: Channel closed 直接中止整条部署)。
    失败的退出码统一返回 -1 (调用方可据此判断但不至于崩溃)。
    """
    try:
        stdin, stdout, stderr = ssh_client.exec_command(cmd)
        try:
            stdout.channel.settimeout(timeout)
            exit_code = stdout.channel.recv_exit_status()
        except Exception:
            exit_code = -1
        try:
            out = stdout.read().decode('utf-8', errors='ignore').strip()
        except Exception:
            out = ""
        try:
            err = stderr.read().decode('utf-8', errors='ignore').strip()
        except Exception:
            err = ""
        if exit_code == -1 and not out and err:
            out = err
        return exit_code, out, err
    except Exception as e:
        return -1, "", f"{type(e).__name__}: {e}"


# 盒上开机弹出的 Python 测试面板源码 (纯标准库 tkinter 编写; 由 _deploy_test_panel 部署)
_TEST_PANEL_SRC = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Batocera 盒上测试面板 (纯 Python 标准库 tkinter 编写)
涵盖: 系统/网络状态 + 音频/串流链路测试。
随开机由 /userdata/system/.xinitrc 在 X 会话里弹出 (DISPLAY=:0)。
所有改动均位于持久分区 /userdata, 重启不丢。
"""
import os
import sys
import time
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, scrolledtext

PULSE_BIN = "/userdata/system/pulse/bin"
PYTHON = "/userdata/system/python/bin/python3"


def run(cmd, env=None, timeout=15):
    """执行命令返回 (stdout, stderr, rc)。"""
    full_env = dict(os.environ)
    full_env["PATH"] = PULSE_BIN + ":" + full_env.get("PATH", "")
    if "PULSE_SERVER" not in full_env:
        full_env["PULSE_SERVER"] = "unix:/var/run/pulse/native"
    full_env["LD_LIBRARY_PATH"] = "/userdata/system/pulse/lib:" + full_env.get("LD_LIBRARY_PATH", "")
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           env=full_env, timeout=timeout)
        return p.stdout.strip(), p.stderr.strip(), p.returncode
    except Exception as e:
        return "", str(e), -1


def gen_tone(path="/tmp/test_tone.wav", freq=440.0, dur=1.0, rate=44100):
    import struct, math, wave
    n = int(rate * dur)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        for i in range(n):
            v = int(32767 * 0.4 * math.sin(2 * math.pi * freq * i / rate))
            w.writeframes(struct.pack("<h", v))


class Panel(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🧪 Batocera 测试面板  (Python 自带库)")
        self.geometry("460x380")
        self.resizable(False, False)
        try:
            self.attributes("-topmost", True)
        except Exception:
            pass
        self.note = ttk.Notebook(self)
        self.note.pack(fill="both", expand=True, padx=6, pady=6)
        self.note.bind("<<NotebookTabChanged>>", lambda e: self.refresh_current())

        self.sys_text = scrolledtext.ScrolledText(self, font=("Consolas", 9), width=54, height=15)
        self.note.add(self.sys_text, text="💻 系统 / 网络")
        f1 = ttk.Frame(self); self.note.add(f1, text="🔊 音频 / 串流")
        self.audio_text = scrolledtext.ScrolledText(f1, font=("Consolas", 9), width=54, height=12)
        self.audio_text.pack(fill="both", expand=True)
        bf = ttk.Frame(f1); bf.pack(fill="x", pady=4)
        ttk.Button(bf, text="▶ 播放测试音 (440Hz)", command=self.play_tone).pack(side="left", padx=3)
        ttk.Button(bf, text="⟳ 刷新音频", command=self.refresh_audio).pack(side="left", padx=3)
        ttk.Button(bf, text="列 sink-inputs", command=self.show_sink_inputs).pack(side="left", padx=3)

        f2 = ttk.Frame(self); self.note.add(f2, text="📜 日志")
        self.log_text = scrolledtext.ScrolledText(f2, font=("Consolas", 9), width=54, height=9)
        self.log_text.pack(fill="both", expand=True)
        ttk.Button(f2, text="⟳ 刷新全部", command=self.refresh_all).pack(pady=4)

        self._tab = 0
        self.refresh_all()

    # 注意: tkinter 非线程安全, 所有控件写入必须在主线程完成, 工作线程只采集数据后用 after(0,...) 回调
    def log(self, msg):
        try:
            self.after(0, lambda: self._log_msg(msg))
        except Exception:
            pass

    def _log_msg(self, msg):
        try:
            self.log_text.insert("end", msg + "\n")
            self.log_text.see("end")
        except Exception:
            pass

    def refresh_current(self):
        self._tab = self.note.index("current")
        if self._tab == 0:
            self.refresh_sys()
        elif self._tab == 1:
            self.refresh_audio()

    def refresh_all(self):
        self.refresh_sys()
        self.refresh_audio()

    def refresh_sys(self):
        def job():
            try:
                lines = []
                out, _, _ = run(f"{PYTHON} --version 2>&1")
                lines.append(f"[Python] {out or sys.version.split()[0]}")
                out, _, _ = run("hostname")
                lines.append(f"[主机名] {out}")
                out, _, _ = run("uptime")
                lines.append(f"[uptime] {out}")
                out, _, _ = run("free -m | awk 'NR==1||NR==2'")
                lines.append(f"[内存]\n{out}")
                out, _, _ = run("df -h /userdata /boot 2>/dev/null")
                lines.append(f"[磁盘]\n{out}")
                out, _, _ = run("ip -o -4 addr show 2>/dev/null | awk '{print $2, $4}'")
                lines.append(f"[IP 地址]\n{out or '(无)'}")
                out, _, _ = run("ip route 2>/dev/null | awk '/default/{print $3}'")
                gw = out.splitlines()[0] if out else ""
                if gw:
                    t0 = time.time()
                    run(f"ping -c 1 -w 2 {gw}", timeout=4)
                    dt = round((time.time() - t0) * 1000)
                    lines.append(f"[网关 {gw}] 可达, ~{dt}ms")
                else:
                    lines.append("[网关] 未找到默认路由")
                out, _, _ = run("cat /proc/loadavg")
                lines.append(f"[负载] {out}")
                self.after(0, lambda: self._set_text(self.sys_text, "\n".join(lines) + "\n"))
            except Exception as e:
                self.after(0, lambda: self._log_msg(f"[系统刷新异常] {e}"))
        threading.Thread(target=job, daemon=True).start()

    def refresh_audio(self):
        def job():
            try:
                sections = []
                sections.append(("pactl info", run("pactl info 2>&1")[0]))
                sections.append(("sinks", run("pactl list short sinks 2>&1")[0]))
                sections.append(("Sunshine 进程", run("pgrep -a sunshine 2>&1")[0] or "(未运行)"))
                out, _, _ = run("ss -ltnp 2>/dev/null | grep -E '47989|4798' || echo '(Web/47989 未监听)'")
                sections.append(("Sunshine 端口", out))
                self.after(0, lambda: self._set_audio(sections))
            except Exception as e:
                self.after(0, lambda: self._log_msg(f"[音频刷新异常] {e}"))
        threading.Thread(target=job, daemon=True).start()

    def _set_text(self, widget, text):
        try:
            widget.delete("1.0", "end")
            widget.insert("end", text)
        except Exception:
            pass

    def _set_audio(self, sections):
        try:
            self.audio_text.delete("1.0", "end")
            for title, body in sections:
                self.audio_text.insert("end", f"=== {title} ===\n{(body or '(空)')}\n\n")
        except Exception:
            pass

    def play_tone(self):
        def job():
            try:
                self.log("[*] 生成并播放 440Hz 测试音 (经 ALSA->Pulse) ...")
                gen_tone()
                out, err, rc = run(f"aplay -D default /tmp/test_tone.wav 2>&1", timeout=10)
                self.log(f"[aplay] rc={rc} out={out} err={err}")
                si, _, _ = run("pactl list short sink-inputs 2>&1")
                self.log(f"[sink-inputs] {si or '(无)'}")
            except Exception as e:
                self.log(f"[-] 播放异常: {e}")
        threading.Thread(target=job, daemon=True).start()

    def show_sink_inputs(self):
        try:
            out, _, _ = run("pactl list short sink-inputs 2>&1")
            self.log(f"[sink-inputs]\n{out or '(无 - 可能 Sunshine 未串流连入)'}")
        except Exception as e:
            self.log(f"[-] 查询异常: {e}")


if __name__ == "__main__":
    if not os.environ.get("DISPLAY"):
        os.environ["DISPLAY"] = ":0"
    # 解析有效的 X 鉴权 cookie (Batocera 实际用 /var/lib/.Xauthority; .serverauth 多为空文件)
    if not os.environ.get("XAUTHORITY"):
        for cand in ("/var/lib/.Xauthority",):
            if os.path.exists(cand) and os.path.getsize(cand) > 0:
                os.environ["XAUTHORITY"] = cand
                break
        if not os.environ.get("XAUTHORITY"):
            import glob
            for cand in glob.glob("/userdata/system/.serverauth.*") + glob.glob("/tmp/.X11-unix/X0"):
                if os.path.exists(cand) and os.path.getsize(cand) > 0:
                    os.environ["XAUTHORITY"] = cand
                    break
    try:
        Panel().mainloop()
    except Exception as e:
        import traceback
        with open("/tmp/test_panel.log", "a") as f:
            f.write("PANEL ERROR: " + traceback.format_exc() + "\n")
'''

__all__ = [
    "CREDS_DIR",
    "CREDS_FILE",
    "_TEST_PANEL_SRC",
    "_fetch_url",
    "_valid_deb",
    "center_window",
    "extract_deb_data_tar",
    "run_sync_cmd"
]
