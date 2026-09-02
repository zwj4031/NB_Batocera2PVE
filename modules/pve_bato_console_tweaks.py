# -*- coding: utf-8 -*-
"""Batocera 控制台 - batocera.conf 系统调优、键位预设、ROM盘切换 (Mixin 子模块)"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
import paramiko
import re
import base64
import time
import os
import json

from pve_bato_net import center_window
from pve_common import run_sync_cmd

class _ConsoleTweaksMixin(object):

    def _build_tweaks_tab(self, nb):
        # ===== Tab 3: 游戏与系统调优 (紧凑网格化排版 + 可滚动, 防底部操作栏被挤出可视区) =====
        tab3 = ttk.Frame(nb, padding=4)
        nb.add(tab3, text="🎮 游戏与系统调优")

        # --- 可滚动容器: 页面较高, 直接塞进 tab 会把底部的「保存调优并刷新 ES」挤出可视区 ---
        canvas = tk.Canvas(tab3, highlightthickness=0, bd=0)
        vbar = ttk.Scrollbar(tab3, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas)
        _win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_canvas_cfg(_e):
            try:
                canvas.itemconfigure(_win, width=canvas.winfo_width())
                canvas.configure(scrollregion=canvas.bbox("all"))
            except Exception:
                pass
        canvas.bind("<Configure>", _on_canvas_cfg)

        def _on_wheel(_e):
            try:
                if _e.delta:
                    canvas.yview_scroll(int(-_e.delta / 120), "units")
                else:
                    canvas.yview_scroll(-1 if _e.num == 4 else 1, "units")
            except Exception:
                pass
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        self._tweaks_canvas = canvas

        # --- 卡片 1: 本地化与网络服务 ---
        f_loc = tk.LabelFrame(inner, text="🌍 本地化与网络服务", padx=6, pady=4)
        f_loc.pack(fill="x", pady=2)
        self._lang_map = {"简体中文 (zh_CN)": "zh_CN", "繁体中文 (zh_TW)": "zh_TW", "English (en_US)": "en_US", "日本語 (ja_JP)": "ja_JP"}
        self._tz_map = {"Asia/Shanghai (中国上海标准时)": "Asia/Shanghai", "UTC": "UTC"}
        row_loc1 = tk.Frame(f_loc); row_loc1.pack(fill="x", pady=1)
        tk.Label(row_loc1, text="系统语言:", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.combo_lang = ttk.Combobox(row_loc1, state="readonly", width=22, values=list(self._lang_map.keys()))
        self.combo_lang.set("简体中文 (zh_CN)")
        self.combo_lang.pack(side="left", padx=4)
        tk.Label(row_loc1, text="系统时区:", font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(10, 0))
        self.combo_tz = ttk.Combobox(row_loc1, state="readonly", width=26, values=list(self._tz_map.keys()))
        self.combo_tz.set("Asia/Shanghai (中国上海标准时)")
        self.combo_tz.pack(side="left", padx=4)

        row_loc2 = tk.Frame(f_loc); row_loc2.pack(fill="x", pady=(2, 0))
        self.var_samba = tk.IntVar(value=0)
        # SSH 默认勾上: 防止未先『重新拉取配置』就点『保存调优并刷新 ES』时, 把所有开关按
        # 默认 0 写回去把 SSH 误关掉(一旦误关就再也没法远程连回了)
        self.var_ssh = tk.IntVar(value=1)
        self.var_web = tk.IntVar(value=0)
        self.var_syncthing = tk.IntVar(value=0)
        tk.Checkbutton(row_loc2, text="☑ Samba共享", variable=self.var_samba, font=("Microsoft YaHei UI", 9)).pack(side="left", padx=2)
        tk.Checkbutton(row_loc2, text="☑ SSH远程", variable=self.var_ssh, font=("Microsoft YaHei UI", 9)).pack(side="left", padx=4)
        tk.Checkbutton(row_loc2, text="☑ Web控制台", variable=self.var_web, font=("Microsoft YaHei UI", 9)).pack(side="left", padx=4)
        tk.Checkbutton(row_loc2, text="☑ Syncthing", variable=self.var_syncthing, font=("Microsoft YaHei UI", 9)).pack(side="left", padx=4)

        # --- 卡片 2: 画质与游玩黑科技 ---
        f_play = tk.LabelFrame(inner, text="📺 画质与游玩黑科技", padx=6, pady=4)
        f_play.pack(fill="x", pady=2)
        self._ratio_map = {"自动 (auto)": "auto", "4:3 (4/3)": "4/3", "16:9 (16/9)": "16/9"}
        self._shader_map = {"关闭滤镜 (none - 最稳)": "none", "CRT扫描线 (scanlines)": "scanlines", "复古色彩 (retro)": "retro"}
        row_pl1 = tk.Frame(f_play); row_pl1.pack(fill="x", pady=1)
        tk.Label(row_pl1, text="画面比例:", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.combo_ratio = ttk.Combobox(row_pl1, state="readonly", width=18, values=list(self._ratio_map.keys()))
        self.combo_ratio.set("自动 (auto)")
        self.combo_ratio.pack(side="left", padx=4)
        tk.Label(row_pl1, text="复古滤镜:", font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(10, 0))
        self.combo_shader = ttk.Combobox(row_pl1, state="readonly", width=22, values=list(self._shader_map.keys()))
        self.combo_shader.set("关闭 (none)")
        self.combo_shader.pack(side="left", padx=4)

        row_pl2 = tk.Frame(f_play); row_pl2.pack(fill="x", pady=(2, 0))
        self.var_show_fps = tk.IntVar(value=0)
        self.var_rewind = tk.IntVar(value=0)
        self.var_autosave = tk.IntVar(value=0)
        self.var_ai = tk.IntVar(value=0)
        self.var_bgmusic = tk.IntVar(value=0)
        self.var_bezel = tk.IntVar(value=0)
        ple = [
            ("☑ 显示FPS", self.var_show_fps),
            ("☑ 游戏倒带", self.var_rewind),
            ("☑ 自动存档", self.var_autosave),
            ("☑ AI翻译", self.var_ai),
            ("☑ 背景音乐", self.var_bgmusic),
            ("☑ 边框装饰", self.var_bezel),
        ]
        for i, (label, var) in enumerate(ple):
            r, c = divmod(i, 3)
            tk.Checkbutton(row_pl2, text=label, variable=var, font=("Microsoft YaHei UI", 9),
                           anchor="w").grid(row=r, column=c, sticky="w", padx=6, pady=1)

        # --- 卡片 3: 手柄与键盘键位习惯 ---
        f_pad = tk.LabelFrame(inner, text="🎮 手柄与键盘键位习惯预设", padx=6, pady=4)
        f_pad.pack(fill="x", pady=2)
        row_pd1 = tk.Frame(f_pad); row_pd1.pack(fill="x", pady=1)
        self.combo_kbd = ttk.Combobox(row_pd1, state="readonly", width=44, values=[
            "🕹️ 街机 J打击/K跳 (WASD + J打击/K跳/U/I + Enter开始/RShift投币)",
            "🕹️ 街机格斗标准 (WASD方向 + J/K/U/I动作 + Enter开始/RShift投币)",
            "🎮 经典模拟器标准 (方向键 + Z/X/A/S + Enter开始/RShift投币)",
            "👾 复古街机标准 (方向键 + K/J/I/U + Enter开始/Space投币)",
            "🔥 动作冒险 (WASD + J/K/X空格 + Enter开始)",
            "🔫 射击/飞行 (方向键 + Z/X/C/V + Space开火)",
            "🧹 恢复默认 (清空键盘映射, 回到手柄)",
        ] + ["📌 自定义 · %s" % n for n in self._load_custom_kbd_presets().keys()])
        self.combo_kbd.set("🕹️ 街机 J打击/K跳 (WASD + J打击/K跳/U/I + Enter开始/RShift投币)")
        self.combo_kbd.pack(side="left", padx=4)
        tk.Button(row_pd1, text="⚡ 套用键盘预设", bg="#7c3aed", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=8, command=self.apply_kbd_preset).pack(side="left", padx=4)
        tk.Button(row_pd1, text="⚡ 修复标准热键 (Hotkey+Start退出)", bg="#ea580c", fg="white",
                  font=("Microsoft YaHei UI", 9, "bold"), relief="flat", padx=8, command=self.fix_hotkeys).pack(side="left", padx=2)
        tk.Button(row_pd1, text="✏️ 自定义键位…", bg="#6d28d9", fg="white",
                  font=("Microsoft YaHei UI", 9, "bold"), relief="flat", padx=8, command=self.open_custom_kbd).pack(side="left", padx=2)

        # --- 底部配置操作栏 ---
        f_tweak_ops = tk.Frame(inner)
        f_tweak_ops.pack(fill="x", pady=(4, 0))
        tk.Button(f_tweak_ops, text="🔄 重新拉取配置", bg="#64748b", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=10, command=self.load_batocera_conf).pack(side="left", padx=4)
        tk.Button(f_tweak_ops, text="💾 保存调优并刷新 ES", bg="#16a34a", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=12, command=self.save_batocera_conf).pack(side="left", padx=4)

        self._conf_keys = [
            ("system.samba.enabled", self.var_samba),
            ("system.ssh.enabled", self.var_ssh),
            ("system.web.enabled", self.var_web),
            ("system.syncthing.enabled", self.var_syncthing),
            ("global.showFPS", self.var_show_fps),
            ("global.rewind", self.var_rewind),
            ("global.autosave", self.var_autosave),
            ("global.ai_service_enabled", self.var_ai),
            ("audio.bgmusic", self.var_bgmusic),
            ("global.bezel", self.var_bezel),
        ]
        self._conf_strs = [
            ("system.language", self.combo_lang, self._lang_map),
            ("system.timezone", self.combo_tz, self._tz_map),
            ("global.ratio", self.combo_ratio, self._ratio_map),
            ("global.shaderset", self.combo_shader, self._shader_map),
        ]

    def load_batocera_conf(self):
        """⚙️ 读取 /userdata/system/batocera.conf, 解析常用调优开关回填到勾选框。"""
        self._log("[*] 正在拉取 batocera.conf 常用调优配置...")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    return
                _, stdout, _ = ssh.exec_command("cat /userdata/system/batocera.conf 2>/dev/null")
                out = stdout.read().decode("utf-8", "ignore")
                self.after(0, lambda conf=out: self._apply_conf_to_vars(conf))
            except Exception as e:
                self._log(f"[-] 拉取 batocera.conf 失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def _apply_conf_to_vars(self, conf):
        """解析 conf 文本并回填调优勾选框与下拉框 (语言/时区/比例/着色器)。"""
        try:
            if self._closing:
                return
            values = {}
            for line in (conf or "").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, _, v = s.partition("=")
                values[k.strip()] = v.strip().lower()
            for key, var in self._conf_keys:
                val = values.get(key, "")
                var.set(1 if val in ("1", "true", "yes", "on", "enable", "enabled") else 0)
            # 回填字符串型下拉框
            for key, combo, mapping in self._conf_strs:
                cur = values.get(key, "")
                if cur:
                    for label, val in mapping.items():
                        if val == cur or val.lower() == cur:
                            combo.set(label)
                            break
                    else:
                        combo.set(list(mapping.keys())[0] if mapping else "")
            self._log("[+] 已加载 batocera.conf 调优开关与下拉配置状态")
        except (tk.TclError, RuntimeError):
            pass

    def _write_conf_lines(self, ssh, key, val):
        """幂等写一条 batocera.conf: 先精确删除该 key 的全部旧行, 再追加唯一一条, 绝不产生重复项。

        只锚定 ^key= 的那几行(精确到该项), 不会误伤同前缀的其它项
        (如调 input_player1_a 不会影响 input_player1_b)。之前用『exists+sed 替换首行』
        会在已有多行该 key 时只替换第一行, 导致 conf 里重复项越攒越多。
        """
        pat = re.escape(key)
        _, st, _ = ssh.exec_command(
            f"sed -i '/^{pat}=/d' /userdata/system/batocera.conf; "
            f"echo '{key}={val}' >> /userdata/system/batocera.conf"
        )
        st.channel.recv_exit_status()

    def save_batocera_conf(self):
        """💾 将勾选框与下拉框状态写回 batocera.conf 并自动刷新 ES 菜单。"""
        ip = self.entry_ip.get().strip() or self.bato_ip or ""
        self._log(f"[*] 正在保存调优配置并刷新 ES 菜单...")
        self._start_hint("保存配置")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._stop_hint()
                    return
                # 勾选框: 写入 1/0
                for key, var in self._conf_keys:
                    self._write_conf_lines(ssh, key.strip(), "1" if var.get() else "0")
                # 下拉框: 按当前显示项反向映射到配置值
                for key, combo, mapping in self._conf_strs:
                    cur = combo.get()
                    val = mapping.get(cur, "")
                    if val:
                        self._write_conf_lines(ssh, key.strip(), val)
                # 刷新 ES 菜单 (184 不支持 --reload, 只用 --restart)
                _, stx, _ = ssh.exec_command("batocera-es-swissknife --restart 2>/dev/null || true")
                stx.channel.recv_exit_status()
                self._stop_hint("✅ 已保存")
                self.after(0, lambda: self._log("[+] batocera.conf 调优配置已保存并刷新 ES 菜单 (生效) "))
            except Exception as e:
                self._stop_hint("⚠️ 保存失败")
                self._log(f"[-] 保存 batocera.conf 失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def apply_kbd_preset(self):
        """⚡ 将所选键盘预设写入 global.retroarch.input_player1_* 并重载。"""
        sel = self.combo_kbd.get()
        if sel.startswith("🧹"):
            self._log("[*] 正在恢复默认按键 (清空 global.retroarch.input_player1_* 键盘映射, 回到 ES 手柄)...")
            self._start_hint("恢复默认")
            def clear_task():
                try:
                    ssh = self._get_ssh()
                    if not ssh:
                        self._stop_hint()
                        return
                    _, so, _ = ssh.exec_command(
                        "sed -i '/^global.retroarch.input_player1_/d' /userdata/system/batocera.conf; "
                        "sed -i '/^global.retroarch.input_.*_plus=/d' /userdata/system/batocera.conf; "
                        "sed -i '/^global.retroarch.input_.*_minus=/d' /userdata/system/batocera.conf; "
                        "echo done")
                    so.channel.recv_exit_status()
                    self._stop_hint("✅ 已恢复")
                    self.after(0, lambda: self._log("[+] 已清空键盘映射，手柄恢复可用（下次进游戏生效，重进游戏即可）"))
                except Exception as e:
                    self._stop_hint("⚠️ 失败")
                    self._log(f"[-] 恢复默认失败: {e}")
            threading.Thread(target=clear_task, daemon=True).start()
            return
        # 自定义按钮：路径是保存时拼的 "📌 自定义 · <名称>"
        if sel.startswith("📌 自定义 ·"):
            self._apply_custom_kbd_preset(sel)
            return
        # Batocera 官方建议: 设 input_player1_* 键盘映射会把输入设备锁成键盘,
        # 会暂时禁用 ES 配置的手柄。故:
        # 1) D-pad / Face / Shoulder 都给合法键名;
        # 2) 左/右摇杆、L3/R3、L2/R2 一律显式 =nul (避免残留设备映射抢输入);
        # 3) 提供"恢复默认"项回退到 ES 手柄。
        mapping = {
            "🕹️ 街机 J打击/K跳 (WASD + J打击/K跳/U/I + Enter开始/RShift投币)": {
                "global.retroarch.input_player1_up": "w", "global.retroarch.input_player1_down": "s",
                "global.retroarch.input_player1_left": "a", "global.retroarch.input_player1_right": "d",
                # 实测(惩罚者/FBNeo): 跳=RetroPad B, 打击=RetroPad Y, RetroPad A 无效
                "global.retroarch.input_player1_b": "k", "global.retroarch.input_player1_y": "j",
                "global.retroarch.input_player1_a": "i", "global.retroarch.input_player1_x": "u",
                "global.retroarch.input_player1_l": "q", "global.retroarch.input_player1_r": "e",
                "global.retroarch.input_player1_l2": "nul", "global.retroarch.input_player1_r2": "nul",
                "global.retroarch.input_player1_start": "enter", "global.retroarch.input_player1_select": "rshift",
                "global.retroarch.input_player1_l_x_plus": "nul", "global.retroarch.input_player1_l_x_minus": "nul",
                "global.retroarch.input_player1_l_y_plus": "nul", "global.retroarch.input_player1_l_y_minus": "nul",
                "global.retroarch.input_player1_r_x_plus": "nul", "global.retroarch.input_player1_r_x_minus": "nul",
                "global.retroarch.input_player1_r_y_plus": "nul", "global.retroarch.input_player1_r_y_minus": "nul",
                "global.retroarch.input_player1_l3": "nul", "global.retroarch.input_player1_r3": "nul",
            },
            "🕹️ 街机格斗标准 (WASD方向 + J/K/U/I动作 + Enter开始/RShift投币)": {
                "global.retroarch.input_player1_up": "w", "global.retroarch.input_player1_down": "s",
                "global.retroarch.input_player1_left": "a", "global.retroarch.input_player1_right": "d",
                "global.retroarch.input_player1_a": "k", "global.retroarch.input_player1_b": "j",
                "global.retroarch.input_player1_x": "i", "global.retroarch.input_player1_y": "u",
                "global.retroarch.input_player1_l": "q", "global.retroarch.input_player1_r": "e",
                "global.retroarch.input_player1_l2": "nul", "global.retroarch.input_player1_r2": "nul",
                "global.retroarch.input_player1_start": "enter", "global.retroarch.input_player1_select": "rshift",
                "global.retroarch.input_player1_l_x_plus": "nul", "global.retroarch.input_player1_l_x_minus": "nul",
                "global.retroarch.input_player1_l_y_plus": "nul", "global.retroarch.input_player1_l_y_minus": "nul",
                "global.retroarch.input_player1_r_x_plus": "nul", "global.retroarch.input_player1_r_x_minus": "nul",
                "global.retroarch.input_player1_r_y_plus": "nul", "global.retroarch.input_player1_r_y_minus": "nul",
                "global.retroarch.input_player1_l3": "nul", "global.retroarch.input_player1_r3": "nul",
            },
            "🎮 经典模拟器标准 (方向键 + Z/X/A/S + Enter开始/RShift投币)": {
                "global.retroarch.input_player1_up": "up", "global.retroarch.input_player1_down": "down",
                "global.retroarch.input_player1_left": "left", "global.retroarch.input_player1_right": "right",
                "global.retroarch.input_player1_a": "s", "global.retroarch.input_player1_b": "a",
                "global.retroarch.input_player1_x": "x", "global.retroarch.input_player1_y": "z",
                "global.retroarch.input_player1_l": "q", "global.retroarch.input_player1_r": "w",
                "global.retroarch.input_player1_l2": "nul", "global.retroarch.input_player1_r2": "nul",
                "global.retroarch.input_player1_start": "enter", "global.retroarch.input_player1_select": "rshift",
                "global.retroarch.input_player1_l_x_plus": "nul", "global.retroarch.input_player1_l_x_minus": "nul",
                "global.retroarch.input_player1_l_y_plus": "nul", "global.retroarch.input_player1_l_y_minus": "nul",
                "global.retroarch.input_player1_r_x_plus": "nul", "global.retroarch.input_player1_r_x_minus": "nul",
                "global.retroarch.input_player1_r_y_plus": "nul", "global.retroarch.input_player1_r_y_minus": "nul",
                "global.retroarch.input_player1_l3": "nul", "global.retroarch.input_player1_r3": "nul",
            },
            "👾 复古街机标准 (方向键 + K/J/I/U + Enter开始/Space投币)": {
                "global.retroarch.input_player1_up": "up", "global.retroarch.input_player1_down": "down",
                "global.retroarch.input_player1_left": "left", "global.retroarch.input_player1_right": "right",
                "global.retroarch.input_player1_a": "k", "global.retroarch.input_player1_b": "j",
                "global.retroarch.input_player1_x": "i", "global.retroarch.input_player1_y": "u",
                "global.retroarch.input_player1_l": "q", "global.retroarch.input_player1_r": "e",
                "global.retroarch.input_player1_l2": "nul", "global.retroarch.input_player1_r2": "nul",
                "global.retroarch.input_player1_start": "enter", "global.retroarch.input_player1_select": "space",
                "global.retroarch.input_player1_l_x_plus": "nul", "global.retroarch.input_player1_l_x_minus": "nul",
                "global.retroarch.input_player1_l_y_plus": "nul", "global.retroarch.input_player1_l_y_minus": "nul",
                "global.retroarch.input_player1_r_x_plus": "nul", "global.retroarch.input_player1_r_x_minus": "nul",
                "global.retroarch.input_player1_r_y_plus": "nul", "global.retroarch.input_player1_r_y_minus": "nul",
                "global.retroarch.input_player1_l3": "nul", "global.retroarch.input_player1_r3": "nul",
            },
            "🔥 动作冒险 (WASD + J/K/X空格 + Enter开始)": {
                "global.retroarch.input_player1_up": "w", "global.retroarch.input_player1_down": "s",
                "global.retroarch.input_player1_left": "a", "global.retroarch.input_player1_right": "d",
                "global.retroarch.input_player1_a": "j", "global.retroarch.input_player1_b": "k",
                "global.retroarch.input_player1_x": "x", "global.retroarch.input_player1_y": "space",
                "global.retroarch.input_player1_l": "q", "global.retroarch.input_player1_r": "e",
                "global.retroarch.input_player1_l2": "nul", "global.retroarch.input_player1_r2": "nul",
                "global.retroarch.input_player1_start": "enter", "global.retroarch.input_player1_select": "rshift",
                "global.retroarch.input_player1_l_x_plus": "nul", "global.retroarch.input_player1_l_x_minus": "nul",
                "global.retroarch.input_player1_l_y_plus": "nul", "global.retroarch.input_player1_l_y_minus": "nul",
                "global.retroarch.input_player1_r_x_plus": "nul", "global.retroarch.input_player1_r_x_minus": "nul",
                "global.retroarch.input_player1_r_y_plus": "nul", "global.retroarch.input_player1_r_y_minus": "nul",
                "global.retroarch.input_player1_l3": "nul", "global.retroarch.input_player1_r3": "nul",
            },
            "🔫 射击/飞行 (方向键 + Z/X/C/V + Space开火)": {
                "global.retroarch.input_player1_up": "up", "global.retroarch.input_player1_down": "down",
                "global.retroarch.input_player1_left": "left", "global.retroarch.input_player1_right": "right",
                "global.retroarch.input_player1_a": "z", "global.retroarch.input_player1_b": "x",
                "global.retroarch.input_player1_x": "c", "global.retroarch.input_player1_y": "v",
                "global.retroarch.input_player1_l": "space", "global.retroarch.input_player1_r": "nul",
                "global.retroarch.input_player1_l2": "nul", "global.retroarch.input_player1_r2": "nul",
                "global.retroarch.input_player1_start": "enter", "global.retroarch.input_player1_select": "rshift",
                "global.retroarch.input_player1_l_x_plus": "nul", "global.retroarch.input_player1_l_x_minus": "nul",
                "global.retroarch.input_player1_l_y_plus": "nul", "global.retroarch.input_player1_l_y_minus": "nul",
                "global.retroarch.input_player1_r_x_plus": "nul", "global.retroarch.input_player1_r_x_minus": "nul",
                "global.retroarch.input_player1_r_y_plus": "nul", "global.retroarch.input_player1_r_y_minus": "nul",
                "global.retroarch.input_player1_l3": "nul", "global.retroarch.input_player1_r3": "nul",
            },
        }
        kbd = mapping.get(sel)
        if not kbd:
            self._log("[-] 请先选择键盘预设")
            return
        self._log(f"[*] 正在套用键盘预设: {sel}")
        self._start_hint("套用键盘预设")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._stop_hint()
                    return
                for key, val in kbd.items():
                    self._write_conf_lines(ssh, key, val)
                self._stop_hint("✅ 已套用")
                # 键位明细写日志, 方便查看投币/开始等
                detail = []
                for _label, _k in [("↑","up"),("↓","down"),("←","left"),("→","right"),("A","a"),("B","b"),("X","x"),("Y","y"),("L1","l"),("R1","r"),("Start","start"),("投币/Select","select")]:
                    v = kbd.get("global.retroarch.input_player1_%s" % _k)
                    if v:
                        detail.append("%s=%s" % (_label, v))
                self.after(0, lambda: self._log("[+] %s\n    键位: %s" % (sel, "  ".join(detail))))
                self.after(0, lambda: self._log("[+] 已写入 batocera.conf，下次进游戏即生效（游戏内需先退出重进；键盘映射会暂时关闭手柄，不套用即恢复）"))
            except Exception as e:
                self._stop_hint("⚠️ 失败")
                self._log(f"[-] 套用键盘预设失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    # ---- 可映射键名(动作标签 -> retroarch key) ----
    _KBD_ITEM_LABELS = [
        ("↑ 上", "up"), ("↓ 下", "down"), ("← 左", "left"), ("→ 右", "right"),
        ("A 键 (动作1)", "a"), ("B 键 (动作2)", "b"), ("X 键 (动作3)", "x"), ("Y 键 (动作4)", "y"),
        ("L1", "l"), ("R1", "r"), ("Start (开始)", "start"), ("Select (投币/选择)", "select"),
        ("L2", "l2"), ("R2", "r2"), ("L3", "l3"), ("R3", "r3"),
        ("左摇杆X+", "l_x_plus"), ("左摇杆X-", "l_x_minus"), ("左摇杆Y+", "l_y_plus"), ("左摇杆Y-", "l_y_minus"),
        ("右摇杆X+", "r_x_plus"), ("右摇杆X-", "r_x_minus"), ("右摇杆Y+", "r_y_plus"), ("右摇杆Y-", "r_y_minus"),
    ]
    _CUSTOM_KBD_FILE = os.path.join(os.path.expanduser("~"), ".pve_bato_custom_kbd.json")

    def _load_custom_kbd_presets(self):
        """读取本地自定义键位预设文件 (返回 {名称: {retroarch_key: 键名}})。"""
        try:
            if os.path.exists(self._CUSTOM_KBD_FILE):
                with open(self._CUSTOM_KBD_FILE, "r", encoding="utf-8") as f:
                    return json.load(f) or {}
        except Exception:
            pass
        return {}

    def _save_custom_kbd_presets(self, presets):
        """把自定义键位预设持久化到本地文件。"""
        try:
            with open(self._CUSTOM_KBD_FILE, "w", encoding="utf-8") as f:
                json.dump(presets, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    # ---- 键盘按下检测 (Tk keysym -> RetroArch SDL 键名) ----
    _KEYMAP = {
        "Up": "up", "Down": "down", "Left": "left", "Right": "right",
        "Return": "enter", "KP_Enter": "kp_enter", "space": "space", "Tab": "tab",
        "Shift_L": "lshift", "Shift_R": "rshift",
        "Control_L": "lctrl", "Control_R": "rctrl",
        "Alt_L": "lalt", "Alt_R": "ralt",
        "Escape": "escape", "BackSpace": "backspace", "Delete": "delete",
        "Home": "home", "End": "end", "Prior": "pageup", "Next": "pagedown",
        "Insert": "insert", "Pause": "pause", "Caps_Lock": "capslock",
        "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4", "F5": "f5", "F6": "f6",
        "F7": "f7", "F8": "f8", "F9": "f9", "F10": "f10", "F11": "f11", "F12": "f12",
    }
    _UNCAPTURABLE = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R"}

    def _keysym_to_retroarch(self, keysym):
        """把 Tk keysym 转成 RetroArch/SDL 键名, 不支持返回 None。"""
        k = (keysym or "").strip()
        if k in self._KEYMAP:
            return self._KEYMAP[k]
        if len(k) == 1:  # 字母/数字 直接小写
            if k.isalnum():
                return k.lower()
        return None

    def _start_capture(self, key):
        """进入捕获模式: 高亮按钮并提示用户按键。"""
        if getattr(self, "_capturing_key", None):
            self._end_capture()  # 先结束上一个
        self._capturing_key = key
        var = self._custom_entries.get(key)
        self._custom_capture_prev = {key: var.get() if var else "nul"}
        if var:
            var.set("⏳ 请按键…")  # textvariable 覆盖 text, 状态经 var 显示
        btn = self._custom_capture_btns.get(key)
        if btn:
            btn.config(bg="#fde68a", fg="#92400e")
        dlg = getattr(self, "_custom_dlg", None)
        if dlg:
            try:
                dlg.focus_set()
            except Exception:
                pass

    def _end_capture(self, cancel=False):
        """结束捕获模式。cancel=True 时还原为捕获前的键位, 否则保留新值。"""
        key = getattr(self, "_capturing_key", None)
        if not key:
            return
        var = self._custom_entries.get(key)
        prev = getattr(self, "_custom_capture_prev", {}).get(key)
        if cancel and var is not None and prev is not None:
            var.set(prev)
        btn = self._custom_capture_btns.get(key)
        if btn:
            btn.config(bg="#eef2ff", fg="#3730a3")
        self._capturing_key = None
        self._custom_capture_prev = {}

    def _on_capture_key(self, event):
        """捕获态按键回调: 写入当前动作并结束捕获。"""
        key = getattr(self, "_capturing_key", None)
        if not key:
            return
        keysym = getattr(event, "keysym", "")
        mapped = self._keysym_to_retroarch(keysym)
        if mapped is None:
            # 修饰键或不可映射, 忽略继续等待
            if keysym in self._UNCAPTURABLE:
                return "break"
            return
        var = self._custom_entries.get(key)
        if var:
            var.set(mapped)
        self._end_capture(cancel=False)
        return "break"

    def _on_capture_click_elsewhere(self, event):
        """捕获态下点击非捕获按钮处 -> 取消捕获(还原)。点捕获按钮本身不取消。"""
        w = getattr(event, "widget", None)
        if w in getattr(self, "_custom_capture_btns", {}).values():
            return None  # 点击捕获按钮自身, 由按钮 command 开启新捕获
        if getattr(self, "_capturing_key", None):
            self._end_capture(cancel=True)
        return None

    def open_custom_kbd(self):
        """✏️ 呼出自定义键位编辑器: 弹出对话框配置每个动作的键盘键, 可存为预设或立即套用。"""
        dlg = tk.Toplevel(self)
        dlg.title("✏️ 自定义键盘键位映射")
        dlg.transient(self)
        dlg.grab_set()
        dlg.configure(bg="#f8fafc")
        center_window(dlg, width=480, height=560)

        # 命名输入框
        f_name = tk.Frame(dlg, bg="#f8fafc"); f_name.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(f_name, text="预设名称:", bg="#f8fafc", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self._custom_name = tk.Entry(f_name, font=("Microsoft YaHei UI", 9), relief="solid", bd=1)
        self._custom_name.pack(side="left", fill="x", expand=True, padx=6, ipady=2)
        self._custom_name.insert(0, "我的自定义键位")

        # 带滚动条的键位网格
        f_canvas_wrap = tk.Frame(dlg, bg="#f8fafc"); f_canvas_wrap.pack(fill="both", expand=True, padx=10, pady=2)
        canvas = tk.Canvas(f_canvas_wrap, bg="#ffffff", highlightthickness=0)
        vsb = ttk.Scrollbar(f_canvas_wrap, orient="vertical", command=canvas.yview)
        f_grid = tk.Frame(canvas, bg="#ffffff")
        f_grid.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=f_grid, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        # 滚轮
        def _wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _wheel)
        dlg._custom_canvas_bind = _wheel

        self._custom_entries = {}  # retroarch key -> StringVar
        self._custom_capture_btns = {}  # retroarch key -> Button
        self._capturing_key = None  # 当前正在捕获的动作键名(None=未捕获)
        for i, (label, key) in enumerate(self._KBD_ITEM_LABELS):
            r, col = divmod(i, 2)
            cell = tk.Frame(f_grid, bg="#ffffff"); cell.grid(row=r, column=col, sticky="w", padx=8, pady=2)
            tk.Label(cell, text=label, width=15, anchor="w", bg="#ffffff",
                     font=("Microsoft YaHei UI", 9)).grid(row=0, column=0)
            var = tk.StringVar(value="nul")
            btn = tk.Button(cell, textvariable=var, width=13, font=("Consolas", 9, "bold"),
                            relief="groove", bd=1, bg="#eef2ff", fg="#3730a3", cursor="hand2",
                            command=lambda k=key: self._start_capture(k))
            btn.grid(row=0, column=1)
            self._custom_entries[key] = var
            self._custom_capture_btns[key] = btn

        # 提示
        tk.Label(f_grid, text="💡 点动作右侧按钮 → 键盘上按下想用的键 → 自动填入",
                 bg="#ffffff", fg="#64748b", font=("Microsoft YaHei UI", 8),
                 anchor="w").grid(row=99, column=0, columnspan=2, sticky="w", padx=8, pady=(4, 0))

        # 全局按键捕获: 捕获态时任意按键写入当前动作
        self._custom_capture_after_id = dlg.bind("<Key>", self._on_capture_key, add="+")
        # 鼠标点别处时若正捕获则取消
        self._custom_capture_btn_id = dlg.bind("<Button-1>", self._on_capture_click_elsewhere, add="+")
        dlg.focus_set()

        # 底部按钮
        f_btns = tk.Frame(dlg, bg="#f8fafc"); f_btns.pack(fill="x", padx=10, pady=8)
        tk.Button(f_btns, text="💾 保存为预设", bg="#7c3aed", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=10, command=self._save_custom_kbd).pack(side="left", padx=2)
        tk.Button(f_btns, text="⚡ 保存并立即套用", bg="#16a34a", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=10, command=lambda: self._save_custom_kbd(apply_now=True)).pack(side="left", padx=2)
        tk.Button(f_btns, text="🧹 恢复默认", bg="#64748b", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=10, command=self._reset_custom_kbd_entries).pack(side="left", padx=2)
        tk.Button(f_btns, text="✕ 关闭", bg="#9ca3af", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=10, command=dlg.destroy).pack(side="right", padx=2)
        self._custom_dlg = dlg
        # 关闭时清理滚轮绑定
        def _on_close():
            try:
                canvas.unbind_all("<MouseWheel>")
            except Exception:
                pass
            try:
                dlg.unbind("<Key>", getattr(self, "_custom_capture_after_id", None))
            except Exception:
                pass
            try:
                dlg.unbind("<Button-1>", getattr(self, "_custom_capture_btn_id", None))
            except Exception:
                pass
            self._capturing_key = None
            dlg.destroy()
        dlg.protocol("WM_DELETE_WINDOW", _on_close)

        # 预填: 若当前有已保存的同名预设则填之; 否则预填最近套用的键位(取自 batocera.conf 已生效值)
        self._prefill_custom_kbd()

    def _current_bato_kbd(self):
        """从盒上 batocera.conf 读当前生效的 input_player1_* 键位(map: key->value)。"""
        res = {}
        try:
            ssh = self._get_ssh()
            if not ssh:
                return res
            _, so, _ = ssh.exec_command("cat /userdata/system/batocera.conf 2>/dev/null")
            conf = so.read().decode("utf-8", "ignore")
            for line in (conf or "").splitlines():
                s = line.strip()
                if s.startswith("#") or "=" not in s:
                    continue
                k, _, v = s.partition("=")
                k = k.strip()
                if k.startswith("global.retroarch.input_player1_") and not k.endswith("_btn"):
                    res[k.replace("global.retroarch.input_player1_", "")] = v.strip()
        except Exception:
            pass
        return res

    def _prefill_custom_kbd(self):
        """对话框打开时预填: 优先同名预设, 其次盒上当前生效键位。"""
        try:
            name = self._custom_name.get().strip()
            presets = self._load_custom_kbd_presets()
            cur = presets.get(name)
            if not cur:
                cur = self._current_bato_kbd()
            for key, var in self._custom_entries.items():
                v = cur.get(key, "nul")
                var.set(v)
        except (tk.TclError, RuntimeError):
            pass

    def _collect_custom_kbd(self):
        """收集对话框当前填写的全部键位 (retroarch key -> 键名字符, 空视为 nul)。"""
        out = {}
        for key, var in self._custom_entries.items():
            v = var.get().strip()
            out["global.retroarch.input_player1_%s" % key] = v if v else "nul"
        return out

    def _reset_custom_kbd_entries(self):
        """把对话框所有键位清回 nul (摇杆/肩键等) 并给方向/主键留空待填。"""
        # 主键给常用默认, 冗余键设 nul
        defaults = {"up": "up", "down": "down", "left": "left", "right": "right",
                    "a": "j", "b": "k", "x": "x", "y": "space",
                    "l": "q", "r": "e", "start": "enter", "select": "rshift"}
        for key, var in self._custom_entries.items():
            var.set(defaults.get(key, "nul"))
        for key, btn in getattr(self, "_custom_capture_btns", {}).items():
            var = self._custom_entries.get(key)
            btn.config(text=var.get() if var else key, bg="#eef2ff", fg="#3730a3")
        self._capturing_key = None
        self._log("[*] 自定义键位已重置为常用默认，可点按钮后按键修改")

    def _write_custom_kbd_to_box(self, col):
        """把收集到的键位写入盒上 batocera.conf (后台线程)。"""
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._stop_hint()
                    return
                for key, val in col.items():
                    self._write_conf_lines(ssh, key, val)
                self._stop_hint("✅ 已套用")
                detail = []
                for label, k in self._KBD_ITEM_LABELS:
                    v = col.get("global.retroarch.input_player1_%s" % k)
                    if v and v != "nul":
                        detail.append("%s=%s" % (label, v))
                self.after(0, lambda: self._log("[+] 已套用自定义键位\n    %s" % "  ".join(detail)))
                self.after(0, lambda: self._log("[+] 已写入 batocera.conf，下次进游戏即生效（游戏内需先退出重进）"))
            except Exception as e:
                self._stop_hint("⚠️ 失败")
                self._log(f"[-] 套用自定义键位失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def _save_custom_kbd(self, apply_now=False):
        """保存对话框当前填写的键位为自定义预设; apply_now=True 时立即写入盒上并套用。"""
        name = self._custom_name.get().strip()
        if not name:
            messagebox.showwarning("提示", "请先填写预设名称！", parent=self._custom_dlg)
            return
        col = self._collect_custom_kbd()
        # 持久化
        presets = self._load_custom_kbd_presets()
        presets[name] = {k.replace("global.retroarch.input_player1_", ""): v for k, v in col.items()}
        ok = self._save_custom_kbd_presets(presets)
        # 加入下拉框可选
        try:
            vals = list(self.combo_kbd["values"])
            entry = "📌 自定义 · %s" % name
            if entry not in vals:
                self.combo_kbd["values"] = vals + [entry]
            self.combo_kbd.set(entry)
        except (tk.TclError, RuntimeError):
            pass
        status = "已保存为自定义预设" if ok else "保存本地失败(仍可套用)"
        if apply_now:
            self._start_hint("套用自定义")
            self._log(f"[*] 正在套用自定义键位: {name} ...")
            self._write_custom_kbd_to_box(col)
            msg = f"[+] 自定义键位「{name}」{status} 并已写入盒子"
        else:
            msg = f"[+] 自定义键位「{name}」{status}，可在下拉框『📌 自定义 · {name}』选用"
        # 关闭弹窗并回主线程写日志
        try:
            self._custom_dlg.destroy()
        except Exception:
            pass
        self.after(0, lambda: self._log(msg))
        return col

    # ---- 自定义预设套用 (从下拉框选"📌 自定义"项时) ----
    def _apply_custom_kbd_preset(self, sel):
        """从下拉框套用自定义键位预设 (sel 形如 '📌 自定义 · <名称>')。"""
        name = sel.replace("📌 自定义 · ", "", 1)
        presets = self._load_custom_kbd_presets()
        kbd = presets.get(name)
        if not kbd:
            self._log(f"[-] 未找到自定义预设「{name}」，可能已被删除")
            return
        col = {"global.retroarch.input_player1_%s" % k: v for k, v in kbd.items()}
        self._start_hint("套用自定义")
        self._log(f"[*] 正在套用自定义键位预设: {name} ...")
        self._write_custom_kbd_to_box(col)

    def fix_hotkeys(self):
        """⚡ 修复并写入标准热键 (Hotkey+Start退出 / X菜单 / Y存A读)。"""
        self._log("[*] 正在修复标准热键 (Hotkey+Start退出 / X菜单 / Y存A读)...")
        self._start_hint("修复热键")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._stop_hint()
                    return
                hotkeys = {
                    "global.retroarch.input_hotkey_btn": "8",       # Hotkey (Select)
                    "global.retroarch.input_exit_emulator_btn": "3",  # Start
                    "global.retroarch.input_menu_toggle_btn": "2",   # X
                    "global.retroarch.input_save_state": "y",        # 键位 Y 存
                    "global.retroarch.input_load_state": "a",        # 键位 A 读
                }
                for key, val in hotkeys.items():
                    self._write_conf_lines(ssh, key, val)
                self._reload_es()
                self._stop_hint("✅ 已修复")
                self.after(0, lambda: self._log("[+] 标准热键已写入 global.retroarch.input_*_btn 并重载"))
            except Exception as e:
                self._stop_hint("⚠️ 失败")
                self._log(f"[-] 修复热键失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def _reload_es(self, restart=True):
        """后台刷新 ES (已有连接时调用, 不抛错)。

        注意: 184 的 batocera-es-swissknife 只支持 --restart, 不支持 --reload
        (--reload 会打印帮助直接退出, 等于什么都没刷新)。故默认 `restart=True`
        用 --restart 真实重启 ES -> 重扫 batocera.conf -> 下次进游戏重载 RetroArch 输入。
        """
        try:
            ssh = self._get_ssh()
            if not ssh:
                return
            if restart:
                _, stx, _ = ssh.exec_command("batocera-es-swissknife --restart 2>/dev/null || true")
            else:
                _, stx, _ = ssh.exec_command("batocera-es-swissknife --reload 2>/dev/null || true")
            stx.channel.recv_exit_status()
        except Exception:
            pass

    def scan_storage_devices(self):
        """🔄 扫描盒上可用存储设备列表并识别当前生效存储。"""
        ip = self.entry_ip.get().strip() or self.bato_ip or ""
        self._log(f"[*] 正在扫描 {ip} 可用存储设备 (storage.device)...")
        self._start_hint("扫描存储")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._stop_hint()
                    return
                list_out = self._run("batocera-config storage list 2>/dev/null || echo INTERNAL")
                cur_out = self._run("batocera-config storage current 2>/dev/null || echo INTERNAL")
                devs = [ln.strip() for ln in (list_out or "").splitlines() if ln.strip()]
                current = (cur_out or "").strip()
                self.after(0, lambda d=devs, c=current: self._apply_storage_scan(d, c))
            except Exception as e:
                self._stop_hint("⚠️ 扫描失败")
                self._log(f"[-] 扫描存储设备失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def _apply_storage_scan(self, devs, current):
        """回主线程更新下拉框与当前存储标签。"""
        try:
            if self._closing or not self.combo_storage_dev.winfo_exists():
                return
            if not devs:
                self.combo_storage_dev.set("(未发现存储设备)")
                self.lbl_storage_cur.config(text=f"当前生效存储: {current or '(未知)'}")
                self._log("[*] 未扫描到任何可用存储设备")
                return
            self.combo_storage_dev["values"] = devs
            if current and current in devs:
                self.combo_storage_dev.set(current)
            elif devs:
                self.combo_storage_dev.set(devs[0])
            self.lbl_storage_cur.config(text=f"当前生效存储: {current or '(未知)'}")
            dev_list = ", ".join(devs)
            self._log(f"[+] 扫描到存储设备: {dev_list} | 当前生效: {current or '(未知)'}")
            self._stop_hint("✅ 已扫描")
        except (tk.TclError, RuntimeError):
            pass

    def apply_storage_device(self):
        """💾 将下拉框选中的设备写为 storage.device 并提示需重启生效。"""
        ip = self.entry_ip.get().strip() or self.bato_ip or ""
        sel = self.combo_storage_dev.get()
        if not sel or sel.startswith("("):
            messagebox.showwarning("提示", "请先扫描并选择目标存储设备！")
            return
        self._log(f"[*] 正在将存储设备切换为: {sel}")
        self._start_hint("切换存储")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._stop_hint()
                    return
                self._write_conf_lines(ssh, "storage.device", sel)
                _, st, _ = ssh.exec_command(f"batocera-config storage set {sel} 2>/dev/null || true")
                st.channel.recv_exit_status()
                self._stop_hint("✅ 已设置")
                self.after(0, lambda s=sel: self._log(
                    f"[+] storage.device 已设置为 {s} (需重启虚拟机生效)"))
                self.after(0, lambda s=sel: messagebox.showinfo(
                    "存储切换成功",
                    f"存储位置已成功切换为 {s}！\n\n请在常用控制中重启虚拟机使新存储生效。"))
            except Exception as e:
                self._stop_hint("⚠️ 切换失败")
                self._log(f"[-] 切换存储设备失败: {e}")
        threading.Thread(target=task, daemon=True).start()
