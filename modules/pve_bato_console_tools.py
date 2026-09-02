# -*- coding: utf-8 -*-
"""Batocera 控制台 - 音画控制、存档备份还原、报错与BIOS排障 (Mixin 子模块 - 无弹窗纯净版)"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
import paramiko
import re
import base64
import time
import os

from pve_common import run_sync_cmd

class GameCrashFixDialog(tk.Toplevel):
    """游戏闪退一键自愈交互勾选对话框"""
    def __init__(self, parent, console_mixin):
        tk.Toplevel.__init__(self, parent)
        self.console = console_mixin
        self.title("🚑 游戏闪退自愈")
        self.resizable(False, False)
        self.transient(parent)

        win_w, win_h = 460, 290
        try:
            self.update_idletasks()
            pw = parent.winfo_width()
            ph = parent.winfo_height()
            px = parent.winfo_rootx()
            py = parent.winfo_rooty()
            x = px + max(0, (pw - win_w) // 2)
            y = py + max(0, (ph - win_h) // 2)
            self.geometry(f"{win_w}x{win_h}+{x}+{y}")
        except Exception:
            self.geometry(f"{win_w}x{win_h}")

        try:
            self.grab_set()
        except Exception:
            pass

        frame = tk.Frame(self, padx=12, pady=10)
        frame.pack(fill="both", expand=True)

        # 底部按钮栏
        f_btn = tk.Frame(frame)
        f_btn.pack(side="bottom", fill="x", pady=(6, 0))

        tk.Button(f_btn, text="🚀 立即执行修复", bg="#16a34a", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=12, pady=2, command=self.do_fix).pack(side="left", fill="x", expand=True, padx=2)
        tk.Button(f_btn, text="取消", font=("Microsoft YaHei UI", 9), width=8, command=self.destroy).pack(side="right", padx=2)

        # 选项列表
        tk.Label(frame, text="请勾选自愈项 (默认推荐全选):", font=("Microsoft YaHei UI", 9, "bold"), fg="#16a34a").pack(anchor="w", pady=(0, 4))

        f_box = tk.LabelFrame(frame, text="修复项目", padx=8, pady=4)
        f_box.pack(side="top", fill="both", expand=True)

        self.v_audio = tk.IntVar(value=1)
        self.v_utf8 = tk.IntVar(value=1)
        self.v_shader = tk.IntVar(value=1)
        self.v_bezel = tk.IntVar(value=1)
        self.v_core = tk.IntVar(value=1)
        self.v_thread = tk.IntVar(value=1)

        items = [
            (self.v_audio, "☑ SDL2 音频驱动 (PVE无声卡防除零崩溃)"),
            (self.v_utf8, "☑ Python2 UTF-8 编码 (解决中文游戏名闪退)"),
            (self.v_shader, "☑ 重置着色器滤镜 (none)"),
            (self.v_bezel, "☑ 重置边框装饰 (none)"),
            (self.v_core, "☑ 自动匹配可用模拟器核心"),
            (self.v_thread, "☑ 开启多线程视频渲染 (threaded)"),
        ]

        for var, title in items:
            cb = tk.Checkbutton(f_box, text=title, variable=var, font=("Microsoft YaHei UI", 9), anchor="w")
            cb.pack(fill="x", pady=1)

    def do_fix(self):
        do_audio = bool(self.v_audio.get())
        do_utf8 = bool(self.v_utf8.get())
        do_shader = bool(self.v_shader.get())
        do_bezel = bool(self.v_bezel.get())
        do_core = bool(self.v_core.get())
        do_thread = bool(self.v_thread.get())

        self.destroy()
        self.console._execute_game_crash_fix(do_audio, do_utf8, do_shader, do_bezel, do_core, do_thread)

class _ConsoleToolsMixin(object):

    def _build_tools_tab(self, nb):
        tab4 = ttk.Frame(nb, padding=4)
        nb.add(tab4, text="💾 存档备份与排障")

        # --- 卡片 1: 音画输出控制 ---
        f_av = tk.LabelFrame(tab4, text="🖥️ 分辨率与音频", padx=6, pady=4)
        f_av.pack(fill="x", pady=2)

        row_res = tk.Frame(f_av); row_res.pack(fill="x", pady=1)
        tk.Label(row_res, text="分辨率:", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.combo_res = ttk.Combobox(row_res, width=18, state="readonly")
        self.combo_res.set("(加载中…)")
        self.combo_res.pack(side="left", padx=4)
        tk.Button(row_res, text="🔄 刷新", bg="#0ea5e9", fg="white", font=("Microsoft YaHei UI", 8),
                  relief="flat", padx=6, command=self.load_resolutions).pack(side="left", padx=2)
        tk.Button(row_res, text="✅ 应用", bg="#22c55e", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=8, command=self.apply_resolution).pack(side="left", padx=2)

        tk.Label(row_res, text="声卡:", font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(10, 0))
        self.combo_audio = ttk.Combobox(row_res, width=18, state="readonly")
        self.combo_audio.set("(加载中…)")
        self.combo_audio.pack(side="left", padx=4)
        tk.Button(row_res, text="🔄 刷新", bg="#0ea5e9", fg="white", font=("Microsoft YaHei UI", 8),
                  relief="flat", padx=6, command=self.load_audio_devices).pack(side="left", padx=2)
        tk.Button(row_res, text="✅ 应用", bg="#22c55e", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=8, command=self.apply_audio_device).pack(side="left", padx=2)

        row_vol = tk.Frame(f_av); row_vol.pack(fill="x", pady=(2, 0))
        tk.Label(row_vol, text="音量:", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.lbl_vol = tk.Label(row_vol, text="100%", fg="#0ea5e9", font=("Microsoft YaHei UI", 9, "bold"), width=5)
        self.lbl_vol.pack(side="left")
        self.scale_vol = ttk.Scale(row_vol, from_=0, to=100, orient="horizontal", command=self._on_vol_change)
        self.scale_vol.set(100)
        self.scale_vol.pack(side="left", fill="x", expand=True, padx=6)
        # 松开滑块即应用到盒子(SSH 线程内), 不必再点『设音量』; 拖动中仅实时更新百分比标签
        self.scale_vol.bind("<ButtonRelease-1>", lambda e: self.apply_volume())
        tk.Button(row_vol, text="🖥️ 设音量", bg="#f59e0b", fg="white", font=("Microsoft YaHei UI", 8),
                  relief="flat", padx=8, command=self.apply_volume).pack(side="left", padx=2)
        tk.Button(row_vol, text="🔔 测试音", bg="#8b5cf6", fg="white", font=("Microsoft YaHei UI", 8),
                  relief="flat", padx=8, command=self.play_test_tone).pack(side="left", padx=2)

        # --- 卡片 2: 游戏存档与配置备份 ---
        f_backup = tk.LabelFrame(tab4, text="💾 游戏存档管理 (/userdata/saves & configs)", padx=6, pady=4)
        f_backup.pack(fill="x", pady=2)

        row_bk = tk.Frame(f_backup); row_bk.pack(fill="x", pady=2)
        tk.Button(row_bk, text="📦 打包导出存档至电脑", bg="#0284c7", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=10, command=self.backup_saves_to_pc).pack(side="left", fill="x", expand=True, padx=4, ipady=2)
        tk.Button(row_bk, text="📥 恢复本地存档到盒子", bg="#ea580c", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=10, command=self.restore_saves_from_pc).pack(side="left", fill="x", expand=True, padx=4, ipady=2)

        # --- 卡片 3: 模拟器排障与自愈 ---
        f_diag2 = tk.LabelFrame(tab4, text="🩺 模拟器排障与自愈", padx=6, pady=4)
        f_diag2.pack(fill="x", pady=2)

        row_d2 = tk.Frame(f_diag2); row_d2.pack(fill="x", pady=1)
        tk.Button(row_d2, text="🩺 诊断游戏报错", bg="#7c3aed", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=8, command=self.diag_last_game_error).pack(side="left", padx=2, ipady=1)
        tk.Button(row_d2, text="🚑 一键修复游戏闪退", bg="#10b981", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=8, command=self.open_game_crash_dialog).pack(side="left", padx=2, ipady=1)
        tk.Button(row_d2, text="🔍 扫描缺失 BIOS", bg="#d97706", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=8, command=self.scan_missing_bios).pack(side="left", padx=2, ipady=1)

    def open_game_crash_dialog(self):
        GameCrashFixDialog(self, self)

    def _execute_game_crash_fix(self, do_audio, do_utf8, do_shader, do_bezel, do_core, do_thread):
        self._log("[*] 正在执行自愈修复...")
        self._start_hint("执行自愈")
        def task():
            ssh = self._get_ssh()
            if not ssh:
                self._stop_hint("⚠️ 未连接")
                return
            try:
                cmd_parts = []
                log_items = []

                if do_audio:
                    cmd_parts.append(
                        "sed -i '/^global.retroarch.audio_driver=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "echo 'global.retroarch.audio_driver=sdl2' >> /userdata/system/batocera.conf; "
                        "sed -i '/^audio_driver/d' /userdata/system/configs/retroarch/retroarchcustom.cfg 2>/dev/null || true; "
                        "echo 'audio_driver = \"sdl2\"' >> /userdata/system/configs/retroarch/retroarchcustom.cfg 2>/dev/null || true"
                    )
                    log_items.append("SDL2 音频驱动 [PVE无声卡专用]")

                if do_utf8:
                    site_code = "import sys\nsys.setdefaultencoding('utf-8')\n"
                    b64_site = base64.b64encode(site_code.encode('utf-8')).decode('ascii')
                    cmd_parts.append(
                        f"echo '{b64_site}' | base64 -d > /userdata/system/sitecustomize.py && "
                        "cp -f /userdata/system/sitecustomize.py /usr/lib/python2.7/sitecustomize.py 2>/dev/null || true; "
                        "grep -q 'PYTHON2_UTF8' /userdata/system/custom.sh 2>/dev/null || "
                        "printf '\\n# PYTHON2_UTF8 begin\\ncp -f /userdata/system/sitecustomize.py /usr/lib/python2.7/sitecustomize.py 2>/dev/null\\n# PYTHON2_UTF8 end\\n' >> /userdata/system/custom.sh"
                    )
                    log_items.append("Python2 UTF-8 编码")

                if do_shader:
                    cmd_parts.append(
                        "sed -i '/^global.shaderset=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "sed -i '/\\.shaderset=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "echo 'global.shaderset=none' >> /userdata/system/batocera.conf"
                    )
                    log_items.append("重置着色器滤镜")

                if do_bezel:
                    cmd_parts.append(
                        "sed -i '/^global.bezel=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "sed -i '/\\.bezel=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "echo 'global.bezel=none' >> /userdata/system/batocera.conf"
                    )
                    log_items.append("重置边框装饰")

                if do_core:
                    _, core_probe, _ = run_sync_cmd(
                        ssh,
                        "ls -1 /usr/lib/libretro/*mednafen*psx*.so /usr/lib/libretro/*pcsx_rearmed*.so /usr/lib/libretro/*duckstation*.so 2>/dev/null | head -n 1"
                    )
                    core_file = core_probe.strip()
                    if core_file:
                        c_base = os.path.basename(core_file).replace("_libretro.so", "")
                        c_name = "mednafen_psx" if "mednafen" in c_base else c_base
                        cmd_parts.append(
                            f"sed -i '/^psx.core=/d' /userdata/system/batocera.conf 2>/dev/null; echo 'psx.core={c_name}' >> /userdata/system/batocera.conf"
                        )
                        log_items.append(f"核心适配 ({c_name})")
                    else:
                        cmd_parts.append("sed -i '/^psx.core=/d' /userdata/system/batocera.conf 2>/dev/null")
                        log_items.append("恢复系统默认核心")

                if do_thread:
                    cmd_parts.append(
                        "sed -i '/^global.retroarch.video_threaded=/d' /userdata/system/batocera.conf 2>/dev/null; "
                        "echo 'global.retroarch.video_threaded=true' >> /userdata/system/batocera.conf"
                    )
                    log_items.append("开启多线程渲染")

                if cmd_parts:
                    full_cmd = " && ".join(cmd_parts) + " && echo FIX_ALL_DONE"
                    run_sync_cmd(ssh, full_cmd)

                result_text = "、".join(log_items) if log_items else "无"
                self._stop_hint("✅ 自愈完成")
                self._log(f"[+] 🎉 游戏闪退自愈执行完成: {result_text}\n    👉 现在可直接重新启动游戏！")
            except Exception as e:
                self._stop_hint("⚠️ 失败")
                self._log(f"[-] 自愈异常: {e}")
        threading.Thread(target=task, daemon=True).start()

    def diag_last_game_error(self):
        self._log("[*] 抓取最后游戏报错日志 (末35行)...")
        def task():
            ssh = self._get_ssh()
            if not ssh: return
            try:
                cmd = "tail -n 35 /userdata/system/logs/es_launch_stderr.log 2>/dev/null || tail -n 35 /userdata/system/logs/es_log.txt 2>/dev/null || echo '(无报错日志)'"
                _, so, _ = ssh.exec_command(cmd, timeout=15)
                out = so.read().decode("utf-8", "ignore")
                self.after(0, lambda o=out: self._log(f"[最后游戏运行日志]:\n{o or '(无输出)'}"))

                if "Period size: 0 frames" in out or "status -11" in out or "double free" in out or "status -6" in out:
                    self._log("\n💡 【诊断分析】: 虚拟声卡 0 帧缓冲崩溃！点击上方的【🚑 一键修复游戏闪退】勾选 SDL2 即可自愈。\n")
                elif "init_libretro_symbols" in out or "Cannot continue" in out:
                    self._log("\n💡 【诊断分析】: 核心文件不存在！点击上方的【🚑 一键修复游戏闪退】勾选核心适配即可自愈。\n")
                elif "UnicodeDecodeError" in out or "writeBezelConfig" in out:
                    self._log("\n💡 【诊断分析】: 中文文件名编码冲突！点击上方的【🚑 一键修复游戏闪退】注入 UTF-8 即可自愈。\n")
            except Exception as e:
                self._log(f"[-] 诊断失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def scan_missing_bios(self):
        self._log("[*] 扫描缺少 BIOS 固件...")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh: return
                cmd = "command -v batocera-check-bioses >/dev/null 2>&1 && batocera-check-bioses 2>&1 || (echo '=== /userdata/bios 目录固件列表 ==='; ls -lh /userdata/bios 2>/dev/null || echo '(目录为空)')"
                _, so, _ = ssh.exec_command(cmd, timeout=30)
                out = so.read().decode("utf-8", "ignore")
                self.after(0, lambda o=out: self._log(f"[BIOS 固件扫描结果]:\n{o or '(无输出)'}"))
            except Exception as e:
                self._log(f"[-] 扫描失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def load_resolutions(self):
        ip = self.entry_ip.get().strip() or self.bato_ip or ""
        self._start_hint("加载分辨率")
        def task():
            modes = []
            ssh = self._get_ssh()
            if not ssh:
                self._stop_hint()
                return
            try:
                _, so, _ = ssh.exec_command("DISPLAY=:0 XAUTHORITY=/var/lib/.Xauthority batocera-resolution listModes 2>/dev/null || xrandr 2>/dev/null | grep -E '^[ ]+[0-9]+x[0-9]+' | awk '{print $1}'")
                raw = so.read().decode("utf-8", "ignore").splitlines()
                modes = [m.strip() for m in raw if m.strip() and "display" not in m.lower() and "error" not in m.lower()]
            except Exception: pass

            if not modes:
                modes = ["1920x1080", "1280x720", "1024x768", "1600x900", "800x600", "640x480"]
            self.after(0, lambda: self._populate_res_list(modes))
        threading.Thread(target=task, daemon=True).start()

    def _populate_res_list(self, modes):
        try:
            if self._closing or not self.combo_res.winfo_exists(): return
            self.combo_res['values'] = modes
            default = "1920x1080" if "1920x1080" in modes else (modes[0] if modes else "1280x720")
            self.combo_res.set(default)
            self._stop_hint()
        except (tk.TclError, RuntimeError): pass

    def apply_resolution(self):
        sel = self.combo_res.get()
        if not sel: return
        self._start_hint("应用分辨率")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._stop_hint()
                    return
                ssh.exec_command(f"sed -i /^global.videomode=/d /userdata/system/batocera.conf; echo 'global.videomode={sel}' >> /userdata/system/batocera.conf")
                ssh.exec_command(f"DISPLAY=:0 XAUTHORITY=/var/lib/.Xauthority batocera-resolution setMode {sel} 2>&1")
                self._stop_hint(f"✅ 已设 {sel}")
                self.after(0, lambda: self._log(f"[+] 分辨率已写入 global.videomode={sel} 并应用"))
            except Exception as e:
                self._stop_hint("⚠️ 失败")
                self._log(f"[-] 应用分辨率失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def load_audio_devices(self):
        self._start_hint("加载声卡")
        def task():
            devs = []
            ssh = self._get_ssh()
            if not ssh:
                self._stop_hint()
                return
            try:
                _, so, _ = ssh.exec_command("command -v batocera-audio >/dev/null 2>&1 && batocera-audio list 2>/dev/null || aplay -l 2>/dev/null | grep '^card' | awk '{print $1,$2,$3}' || echo 'default (默认)'")
                devs = [m.strip() for m in so.read().decode("utf-8", "ignore").splitlines() if m.strip()]
            except Exception: pass
            if not devs: devs = ["default (默认)"]
            self.after(0, lambda: self._populate_audio_list(devs))
        threading.Thread(target=task, daemon=True).start()

    def _populate_audio_list(self, devs):
        try:
            if self._closing or not self.combo_audio.winfo_exists(): return
            self.combo_audio['values'] = devs
            self.combo_audio.set(devs[0] if devs else "default")
            self._stop_hint()
        except (tk.TclError, RuntimeError): pass

    def apply_audio_device(self):
        sel = self.combo_audio.get()
        if not sel: return
        dev_id = sel.split()[0].strip()
        self._start_hint("设置声卡")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._stop_hint()
                    return
                ssh.exec_command(f"command -v batocera-audio >/dev/null 2>&1 && batocera-audio set {dev_id} 2>&1 || true")
                ssh.exec_command(f"sed -i /^audio.device=/d /userdata/system/batocera.conf; echo 'audio.device={dev_id}' >> /userdata/system/batocera.conf")
                self._stop_hint(f"✅ 已设 {dev_id}")
                self.after(0, lambda: self._log(f"[+] 声卡已设为: {dev_id}"))
            except Exception as e:
                self._stop_hint("⚠️ 失败")
                self._log(f"[-] 切换声卡失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def _on_vol_change(self, val):
        try:
            if self._closing or not self.lbl_vol.winfo_exists(): return
            self.lbl_vol.config(text=f"{int(float(val))}%")
        except (tk.TclError, RuntimeError): pass

    def apply_volume(self):
        val = int(self.scale_vol.get())
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh: return
                ssh.exec_command(f"PULSE_SERVER=unix:/var/run/pulse/native amixer set Master {val}% >/dev/null 2>&1; amixer set Master {val}% >/dev/null 2>&1 || true; sed -i /^audio.volume=/d /userdata/system/batocera.conf; echo 'audio.volume={val}' >> /userdata/system/batocera.conf")
                self.after(0, lambda: self._log(f"[+] 系统音量已设为 {val}%"))
            except Exception as e:
                self._log(f"[-] 设置音量失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def play_test_tone(self):
        self._log("[*] 正在播放测试音 (440Hz)...")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh: return
                cmd = "if command -v speaker-test >/dev/null 2>&1; then timeout 1 speaker-test -t sine -f 440 2>&1 | tail -2; else aplay -D default /tmp/test_tone.wav 2>/dev/null || echo '(已发测试音)'; fi"
                ssh.exec_command(cmd)
                self.after(0, lambda: self._log("[+] 测试音指令已执行 (请听声)"))
            except Exception as e:
                self._log(f"[-] 测试音异常: {e}")
        threading.Thread(target=task, daemon=True).start()

    def backup_saves_to_pc(self):
        ip = self.entry_ip.get().strip() or self.bato_ip or ""
        if not ip: return
        default_name = time.strftime("bato_saves_%Y%m%d.tar.gz")
        save_path = filedialog.asksaveasfilename(title="保存存档备份", defaultextension=".tar.gz",
                                                 initialfile=default_name, filetypes=[("压缩包", "*.tar.gz")])
        if not save_path: return
        self._log(f"[*] 打包导出存档至: {save_path}")
        self._start_hint("备份存档")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._stop_hint()
                    return
                self._run("tar -czf /tmp/bato_bk.tar.gz -C /userdata saves system/configs 2>/dev/null")
                sftp = ssh.open_sftp()
                sftp.get("/tmp/bato_bk.tar.gz", save_path)
                sftp.close()
                self._run("rm -f /tmp/bato_bk.tar.gz")
                self._stop_hint("✅ 备份完成")
                self.after(0, lambda: self._log(f"[+] ✅ 存档与配置已保存到: {save_path}"))
            except Exception as e:
                self._stop_hint("⚠️ 失败")
                self._log(f"[-] 导出失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def restore_saves_from_pc(self):
        ip = self.entry_ip.get().strip() or self.bato_ip or ""
        if not ip: return
        if not messagebox.askyesno("确认", "还原将覆盖盒子上现有存档与配置，确定继续？"): return
        file_path = filedialog.askopenfilename(title="选择备份包", filetypes=[("压缩包", "*.tar.gz")])
        if not file_path: return
        self._log(f"[*] 上传并还原备份: {file_path}")
        self._start_hint("还原存档")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._stop_hint()
                    return
                sftp = ssh.open_sftp()
                sftp.put(file_path, "/tmp/rst.tar.gz")
                sftp.close()
                self._run("tar -zxf /tmp/rst.tar.gz -C /userdata/ && rm -f /tmp/rst.tar.gz")
                self._run("batocera-es-swissknife --restart 2>/dev/null || true")
                self._stop_hint("✅ 还原完成")
                self.after(0, lambda: self._log("[+] 🎉 游戏存档与配置已成功还原并刷新菜单！"))
            except Exception as e:
                self._stop_hint("⚠️ 失败")
                self._log(f"[-] 还原失败: {e}")
        threading.Thread(target=task, daemon=True).start()
