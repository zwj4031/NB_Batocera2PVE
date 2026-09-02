# -*- coding: utf-8 -*-
"""Batocera 控制台 - 核心基类、生命周期、连接探针与共享日志 (Mixin 子模块)"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
import threading
import paramiko
import re
import base64
import time
import os

from pve_bato_net import center_window
from pve_common import run_sync_cmd

class _ConsoleCoreMixin(object):

    # ---------- 生命周期与窗口初始化 (门面 __init__ 入口) ----------
    def __init__(self, parent, app, vmid):
        super().__init__(parent)
        self.app = app
        self.vmid = vmid
        self.bato_ip = ""
        self.ssh_bato = None
        self.ssh_bato_ip = ""
        self._auto_connected = False
        self._reconnecting = False
        self._closing = False
        self.title(f"🔧 Batocera 控制台 (SSH) v3.0.0 - VM {vmid}")
        center_window(self, parent, 880, 720)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.resizable(True, True)
        self.minsize(840, 600)
        self._hint_chars = ""
        self._hint_job = None
        self._cmd_history = []
        self._cmd_hist_idx = -1
        self._build_top_card()

        # 引入垂直 PanedWindow 分栏: 上方卡片自适应紧凑无死白 + 下方大号终端日志区占满剩余空间
        self.paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self.paned.pack(fill="both", expand=True, padx=10, pady=(2, 6))

        f_top_pane = ttk.Frame(self.paned)
        self.paned.add(f_top_pane, weight=0)

        nb = ttk.Notebook(f_top_pane)
        nb.pack(fill="both", expand=True)
        self._build_common_tab(nb)
        self._build_plugins_tab(nb)
        self._build_tweaks_tab(nb)
        self._build_tools_tab(nb)
        self._build_system_tab(nb)

        f_bottom_pane = ttk.Frame(self.paned)
        self.paned.add(f_bottom_pane, weight=1)
        self._build_logbase(f_bottom_pane)

        self._populate_builtin_plugins()
        self.after(80, self._adjust_initial_sash)
        self.after(100, self.detect_ip)

    def _adjust_initial_sash(self):
        """精准定位上下分割线, 上方刚好容纳卡片内容无死白, 下方大号终端日志区舒展铺开"""
        try:
            if not self._closing and self.paned.winfo_exists():
                self.paned.sashpos(0, 310)
        except Exception:
            pass

    def _build_top_card(self):
        """顶部状态卡片: IP 输入 + 连接徽标 + Samba 直开 + 加载动效。"""
        f_card = tk.Frame(self, bg="#ffffff", highlightthickness=1, highlightbackground="#e5e7eb", padx=12, pady=8)
        f_card.pack(fill="x", padx=12, pady=(8, 4))
        tk.Label(f_card, text="🗂️ 虚拟机 IP:", bg="#ffffff", fg="#374151", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.entry_ip = tk.Entry(f_card, width=18, font=("Consolas", 10), relief="solid", bd=1)
        self.entry_ip.pack(side="left", padx=6, ipady=2)
        tk.Button(f_card, text="🔍 定位", bg="#dbeafe", fg="#1d4ed8", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=10, activebackground="#bfdbfe",
                  command=lambda: self.detect_ip(manual=True)).pack(side="left", padx=4)
        self.btn_conn = tk.Button(f_card, text="🔌 连接", bg="#10b981", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                                  relief="flat", padx=14, activebackground="#059669", command=self.connect_bato)
        self.btn_conn.pack(side="left", padx=4)
        # 连接状态徽标 (彩色胶囊)
        self.lbl_conn = tk.Label(f_card, text="⚪ 未连接", fg="#6b7280", bg="#f3f4f6",
                                 font=("Microsoft YaHei UI", 9, "bold"), padx=8, pady=2)
        self.lbl_conn.pack(side="left", padx=6)
        tk.Button(f_card, text="📂 打开游戏目录", bg="#0ea5e9", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=10, activebackground="#0284c7",
                  command=self.open_samba_share).pack(side="left", padx=4)
        tk.Label(f_card, text="(root/linux 自动登录)", bg="#ffffff", fg="#9ca3af", font=("Microsoft YaHei UI", 8)).pack(side="left", padx=4)
        # 加载/提示动效文字 (右侧)
        self.lbl_hint = tk.Label(f_card, text="", bg="#ffffff", fg="#6b7280", font=("Microsoft YaHei UI", 8))
        self.lbl_hint.pack(side="right")
        self._hint_chars = ""
        self._hint_job = None

    def _build_common_tab(self, nb):
        # ===== Tab 1: 常用控制 (接入安全升级与回滚向导) =====
        tab1 = ttk.Frame(nb, padding=4)
        nb.add(tab1, text="⚡ 常用控制")

        f_power = tk.LabelFrame(tab1, text="🔋 电源与维护", padx=6, pady=4)
        f_power.pack(fill="x", pady=2)
        row_p = tk.Frame(f_power); row_p.pack(fill="x", pady=1)
        tk.Button(row_p, text="⏻ 关机", bg="#ef4444", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=8, command=lambda: self.run_cmd("poweroff", "关机")).pack(side="left", padx=2, ipady=1)
        tk.Button(row_p, text="♻️ 重启", bg="#f59e0b", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=8, command=self.do_reboot).pack(side="left", padx=2, ipady=1)
        tk.Button(row_p, text="🕒 对时", bg="#3b82f6", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=8, command=lambda: self.run_cmd("ntpd -q -n 2>/dev/null; date", "同步时间")).pack(side="left", padx=2, ipady=1)
        tk.Button(row_p, text="⬆️ 系统升级与回滚", bg="#16a34a", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=8, command=self.open_upgrade_dialog).pack(side="left", padx=2, ipady=1)

        tk.Label(row_p, text="快捷:", font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(8, 2))
        self.combo_quick = ttk.Combobox(row_p, state="readonly", width=18,
                                        values=list(self.QUICK_CMDS.keys()))
        self.combo_quick.set("快速填充…")
        self.combo_quick.pack(side="left", padx=2)
        self.combo_quick.bind("<<ComboboxSelected>>", self._fill_quick_cmd)

        row_c = tk.Frame(f_power); row_c.pack(fill="x", pady=(3, 1))
        tk.Label(row_c, text="命令:", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.entry_cmd = tk.Entry(row_c, relief="solid", bd=1, font=("Consolas", 9))
        self.entry_cmd.pack(side="left", fill="x", expand=True, padx=4, ipady=1)
        self.entry_cmd.bind("<Up>", self._hist_up)
        self.entry_cmd.bind("<Down>", self._hist_down)
        tk.Button(row_c, text="▶ 执行", bg="#22c55e", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=10, command=self.run_custom).pack(side="left", ipady=1)

        f_diag = tk.LabelFrame(tab1, text="🩺 屏幕与测试", padx=6, pady=4)
        f_diag.pack(fill="x", pady=2)
        row_d = tk.Frame(f_diag); row_d.pack(fill="x", pady=1)
        tk.Button(row_d, text="🎧 音频诊断", bg="#8b5cf6", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=8, command=self.audio_diag).pack(side="left", padx=2, ipady=1)
        tk.Button(row_d, text="🧪 呼出测试面板", bg="#8b5cf6", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=8, command=self.launch_test_panel).pack(side="left", padx=2, ipady=1)
        tk.Button(row_d, text="✖ 收起面板", bg="#9ca3af", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=8, command=self.close_test_panel).pack(side="left", padx=2, ipady=1)

    def open_upgrade_dialog(self):
        """呼出系统安全升级与自动备份回滚向导"""
        import pve_bato_console_upgrade
        pve_bato_console_upgrade.SystemUpgradeDialog(self, self)

    def _build_system_tab(self, nb):
        # ===== Tab 5: 系统详情 (极简卡片) =====
        tab5 = ttk.Frame(nb, padding=4)
        nb.add(tab5, text="📋 系统详情")

        f_sysbtn = tk.Frame(tab5); f_sysbtn.pack(fill="x", pady=2)
        tk.Button(f_sysbtn, text="🔄 刷新系统信息", bg="#f59e0b", fg="white", font=("Microsoft YaHei UI", 8, "bold"),
                  relief="flat", padx=10, command=self.identify).pack(side="left", ipady=1)
        tk.Label(f_sysbtn, text="提示: 只读系统改动均需写入 /userdata (重启不丢失)", fg="#9ca3af", font=("Microsoft YaHei UI", 8)).pack(side="left", padx=6)

        f_info = tk.LabelFrame(tab5, text="🖥️ 系统属性", padx=6, pady=4)
        f_info.pack(fill="both", expand=True, pady=2)
        self.info_text = scrolledtext.ScrolledText(f_info, height=5, state="disabled", font=("Consolas", 9),
                                                   bg="#f8fafc", fg="#1e293b")
        self.info_text.pack(fill="both", expand=True)
        self.info_text.tag_configure("key", foreground="#0ea5e9")
        self.info_text.tag_configure("val", foreground="#16a34a")
        self.info_text.tag_configure("wait", foreground="#94a3b8")
        self._set_info("识别中… 连接后自动填充。", "", "")

    def _build_logbase(self, parent):
        # ---- 底部共享日志区 (各标签共用, 工具化) ----
        f_logbase = parent
        
        f_log_head = tk.Frame(f_logbase)
        f_log_head.pack(fill="x", pady=(2, 1))

        self.lbl_plug_status = tk.Label(f_log_head, text="状态: 就绪", fg="#6b7280", font=("Microsoft YaHei UI", 9, "bold"))
        self.lbl_plug_status.pack(side="left")

        tk.Button(f_log_head, text="🧹 清屏", bg="#334155", fg="white", font=("Microsoft YaHei UI", 8),
                  relief="flat", padx=8, pady=1, command=self.clear_log).pack(side="right", padx=2)
        tk.Button(f_log_head, text="📋 复制日志", bg="#0ea5e9", fg="white", font=("Microsoft YaHei UI", 8),
                  relief="flat", padx=8, pady=1, command=self.copy_log).pack(side="right", padx=2)

        self.plug_progress = ttk.Progressbar(f_logbase, orient="horizontal", mode="determinate")
        self.plug_progress.pack(fill="x", pady=(1, 2))

        # 暗色终端风日志框
        self.out_text = scrolledtext.ScrolledText(f_logbase, state="disabled", height=7,
                                                  font=("Consolas", 9), bg="#0f172a", fg="#4ade80",
                                                  insertbackground="#4ade80", relief="solid", bd=1)
        self.out_text.pack(fill="both", expand=True, pady=(1, 2))

    QUICK_CMDS = {
        "查看游戏报错日志": "find /userdata/logs /tmp -name 'es_log.txt' -o -name '*log*.txt' 2>/dev/null | head -3; tail -n 30 /userdata/logs/es_log.txt 2>/dev/null || tail -n 30 /tmp/es_log.txt 2>/dev/null || echo '(未找到游戏日志)'",
        "列出分辨率模式": "xrandr --current 2>/dev/null || cat /sys/class/drm/card0-*/modes 2>/dev/null | sort -u || echo '(未显示显示器)'; tvservice -s 2>/dev/null",
        "查看磁盘容量": "df -h 2>/dev/null; echo '---'; lsblk 2>/dev/null || cat /proc/partitions",
        "扫描缺少BIOS": "ls /userdata/bios /userdata/system/.config/batocera/bios 2>/dev/null | head -20; echo '--- 已找齐(可能缺失): 请自行与官方 BIOS 清单比对 ---'",
        "查看显卡信息": "lspci 2>/dev/null | grep -i -E 'vga|3d|display' || cat /proc/fb 2>/dev/null || echo '(未检测到独显)'; echo '--- DRM ---'; ls /dev/dri 2>/dev/null || echo '(无 /dev/dri, 属软解)'",
    }
    _QUICK_KEY_MAP = {}

    def _set_ip(self, ip):
        """清空后写入 IP, 避免重复/拼接 (自动调用与手动点击不会叠加)。"""
        self.entry_ip.delete(0, tk.END)
        self.entry_ip.insert(0, ip)

    def detect_ip(self, manual=False):
        if not self.app.ssh:
            if manual:
                messagebox.showwarning("提示", "请先连接 PVE SSH 服务器！")
            else:
                self._log("[*] PVE 未连接, 跳过自动定位 IP; 请手动填写或先连接 PVE 服务器。")
            return
        # 优先复用内存与持久化特征库 IP (0 延迟直连)
        import pve_net_config
        cached_info = pve_net_config.ConfigManager.get_vm_info(self.vmid)
        cached = cached_info.get("ip") or getattr(self.app, "vm_ip_info", {}).get(str(self.vmid), "")
        if cached:
            self.bato_ip = cached
            self._set_ip(cached)
            self._log(f"[+] 命中虚拟机持久化特征 IP: {cached} (直接就绪)")
            self.after(0, self.refresh_addon_list)
            self.after(0, self._auto_connect)
            return
        self._log("[*] 正在通过 PVE / QEMU Guest Agent 定位虚拟机 IPv4 ...")

        def task():
            target_ip = ""
            try:
                # 1) QEMU Guest Agent 直查 (最可靠: 直接取虚拟机内网卡 IPv4)
                try:
                    out = self.app.run_ssh_cmd(f"qm guest cmd {self.vmid} network-get-interfaces", ignore_error=True) or ""
                    for m in re.finditer(r'"addr":\s*"(\d+\.\d+\.\d+\.\d+)"', out):
                        a = m.group(1)
                        if a != "127.0.0.1" and not a.startswith("169.254."):
                            target_ip = a
                            break
                except Exception:
                    pass
                # 2) ARP 兜底: 按 net0 MAC 反查 PVE 邻居表
                if not target_ip:
                    cfg = self.app.run_ssh_cmd(f"qm config {self.vmid}", ignore_error=True)
                    mac_match = re.search(r"net0:[^\n]*?([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", cfg)
                    if mac_match:
                        mac = mac_match.group(1).lower()
                        neigh = self.app.run_ssh_cmd("ip neigh show", ignore_error=True)
                        for line in neigh.split('\n'):
                            if mac in line.lower():
                                parts = line.split()
                                if parts and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0]):
                                    target_ip = parts[0]
                                    break
            except Exception as e:
                self._log(f"[-] IP 定位失败: {e}")
                return
            if target_ip:
                self.bato_ip = target_ip
                self._set_ip(target_ip)
                self._log(f"[+] 自动定位到虚拟机 IP: {target_ip}")
                self.after(0, self.refresh_addon_list)
                self.after(0, self._auto_connect)
            else:
                # 不臆造 IP: 交给用户手动填写
                self._log("[*] 未能自动发现 IP (Guest Agent 未启用或 ARP 无记录)，请在上方手动填写虚拟机 IPv4")
        threading.Thread(target=task, daemon=True).start()

    def connect_bato(self):
        """🔌 建立持久 SSH 连接：兼容老版 Batocera 指令"""
        self._log(f"[*] 正在连接 {self.entry_ip.get().strip() or self.bato_ip or ''} ...")
        self._start_hint("正在连接")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._stop_hint()
                    return
                # 兼容老版: batocera-version 缺失时读 /etc/batocera.version 或 /usr/share/batocera/BATOCERA
                out = self._run(
                    "echo '==SYS=='; uname -a; "
                    "echo '==BV=='; (cat /etc/batocera.version 2>/dev/null || batocera-version 2>/dev/null | head -1 || cat /usr/share/batocera/BATOCERA 2>/dev/null); "
                    "echo '==UP=='; (uptime -p 2>/dev/null || uptime 2>/dev/null | awk -F', ' '{print $1}')"
                )
                self._set_conn_state(True)
                self._stop_hint(f"✅ 已连接 {self.entry_ip.get().strip() or self.bato_ip or ''}")
                self.after(0, lambda o=out: self._log(f"[+] 已连接到 {self.entry_ip.get().strip() or self.bato_ip or ''}\n{o or '(无输出)'}"))
                self.after(0, self.load_resolutions)
                self.after(150, self.load_audio_devices)
                self.after(300, self.load_batocera_conf)
            except Exception as e:
                self._set_conn_state(False)
                self._stop_hint("⚠️ 连接失败")
                self._log(f"[-] 连接失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def _set_conn_state(self, connected=True):
        """更新顶部连接状态标签；可能从后台线程触发, 一律回主线程更新。"""
        try:
            if self._closing:
                return
            self.after(0, lambda c=connected: self._apply_conn_state(c))
        except (tk.TclError, RuntimeError):
            pass

    def _apply_conn_state(self, connected):
        try:
            if self._closing or not self.lbl_conn.winfo_exists():
                return
            if connected:
                self.lbl_conn.config(text="🟢 已连接", fg="#ffffff", bg="#16a34a")
            else:
                self.lbl_conn.config(text="🔴 未连接", fg="#ffffff", bg="#dc2626")
        except (tk.TclError, RuntimeError):
            pass

    def _start_hint(self, text):
        """在顶部状态卡右侧显示循环的加载动效文字。"""
        self._hint_chars = text
        self._stop_hint()
        self.after(0, self._hint_tick)

    def _hint_tick(self):
        try:
            if self._closing or not self.lbl_hint.winfo_exists():
                return
            dots = "." * ((len(self._hint_chars) % 3) + 1)
            self.lbl_hint.config(text=self._hint_chars + dots)
            self._hint_chars = self._hint_chars[:-1] if dots == "...." else self._hint_chars
        except (tk.TclError, RuntimeError):
            return
        try:
            self._hint_job = self.after(400, self._hint_tick)
        except (tk.TclError, RuntimeError):
            pass

    def _stop_hint(self, text=""):
        if self._hint_job is not None:
            try:
                self.after_cancel(self._hint_job)
            except Exception:
                pass
            self._hint_job = None
        try:
            if not self._closing and self.lbl_hint.winfo_exists():
                self.lbl_hint.config(text=text)
        except (tk.TclError, RuntimeError):
            pass

    def _get_ssh(self):
        """获取持久 SSH 连接: 优先复用已建立连接; 手动输入框的 IP 优先于自动定位结果。
        换 IP / 连接失效时才重建, 避免旧连接(连到自动定位的其它机器)覆盖用户手动输入。"""
        if getattr(self, "_closing", False) or not self.winfo_exists():
            return None
        ip = self.entry_ip.get().strip() or self.bato_ip or ""
        if not ip:
            if threading.current_thread() is threading.main_thread():
                messagebox.showwarning("提示", "请先填写或自动定位虚拟机 IP！")
            else:
                self._log("[-] 未填写或未定位到虚拟机 IP, 无法连接")
            return None
        if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
            self._log(f"[-] 无效的 IP 地址: {ip!r}，请手动填写正确的虚拟机 IPv4")
            return None
        # 复用已有连接: 仅当目标 IP 未变且传输仍活跃才复用
        if self.ssh_bato is not None and self.ssh_bato_ip == ip:
            try:
                if self.ssh_bato.get_transport() and self.ssh_bato.get_transport().is_active():
                    return self.ssh_bato
            except Exception:
                pass
            try:
                self.ssh_bato.close()
            except Exception:
                pass
            self.ssh_bato = None
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=ip, port=22, username="root", password="linux", timeout=10, banner_timeout=30, auth_timeout=30)
            self.ssh_bato = ssh
            self.ssh_bato_ip = ip
            self._set_conn_state(True)
            return ssh
        except Exception as e:
            self.ssh_bato = None
            self.ssh_bato_ip = ""
            self._set_conn_state(False)
            self._log(f"[-] SSH 连接失败 ({ip}): {e}")
            return None

    def _run(self, cmd):
        if getattr(self, "_closing", False) or not self.winfo_exists():
            return None
        ssh = self._get_ssh()
        if not ssh:
            return None
        try:
            stdin, stdout, stderr = ssh.exec_command(cmd, timeout=600)
            out = stdout.read().decode("utf-8", "ignore") + stderr.read().decode("utf-8", "ignore")
            return out
        except Exception as e:
            # 连接可能中途失效(盒重启/超时), 清除后让下一命令重连
            try:
                ssh.close()
            except Exception:
                pass
            self.ssh_bato = None
            self.ssh_bato_ip = ""
            self._set_conn_state(False)
            self._log(f"[-] 命令执行失败: {e} (连接已释放, 请重新连接)")
            return None

    def identify(self):
        self._log("[*] 正在通过 SSH 识别 Batocera / Linux 版本 ...")
        def task():
            try:
                out = self._run(
                    "echo '==BV=='; (cat /etc/batocera.version 2>/dev/null || batocera-version 2>/dev/null | head -1 || cat /usr/share/batocera/BATOCERA 2>/dev/null || cat /etc/issue 2>/dev/null | head -1); "
                    "echo '==KR=='; uname -r; "
                    "echo '==OS=='; (. /etc/os-release 2>/dev/null; echo $PRETTY_NAME); "
                    "echo '==HN=='; hostname; "
                    "echo '==UP=='; (uptime -p 2>/dev/null || uptime 2>/dev/null | awk -F', ' '{print $1}')"
                )
                info = {"bv": "?", "kr": "?", "os": "?", "hn": "?", "up": "?"}
                section = None
                for line in (out or "").splitlines():
                    sline = line.strip()
                    if sline in ("==BV==", "==KR==", "==OS==", "==HN==", "==UP=="):
                        section = sline[2:-2].lower()
                    elif sline.startswith("=="):
                        section = None
                    elif section and section in info and sline:
                        info[section] = (info[section] + "\n" + sline).strip() if info[section] not in ("?", "") else sline

                bv = info.get("bv", "?")
                kr = info.get("kr", "?")
                os_val = info.get("os", "?")
                hn = info.get("hn", "?")
                up = info.get("up", "?")

                text = (
                    f"🟢 Batocera 版本 : {bv}\n"
                    f"🐧 Linux 内核   : {kr}\n"
                    f"📦 发行版       : {os_val}\n"
                    f"🖥️ 主机名       : {hn}\n"
                    f"⏱️ 运行时长     : {up}"
                )
                self.after(0, lambda t=text, b=bv, k=kr: self._set_info(t, b, k))
            except Exception as e:
                self._log(f"[-] 识别失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def _set_info(self, text, bver, kernel):
        # 结构化展示: 标题与取值用不同颜色区分 (仪表盘风)
        try:
            if self._closing or not self.info_text.winfo_exists():
                return
            self.info_text.config(state="normal")
            self.info_text.delete("1.0", tk.END)
            if text.startswith("🟢"):
                for line in text.splitlines():
                    if ":" in line:
                        k, v = line.split(":", 1)
                        self.info_text.insert(tk.END, k.strip() + ": ", "key")
                        self.info_text.insert(tk.END, v.strip() + "\n", "val")
                    else:
                        self.info_text.insert(tk.END, line + "\n")
            else:
                self.info_text.insert(tk.END, text, "wait")
            self.info_text.config(state="disabled")
        except (tk.TclError, RuntimeError):
            return
        # 回填到主界面虚拟机列表的“系统/版本”列
        if bver and bver != "?" and hasattr(self.app, "set_vm_os_info"):
            self.app.set_vm_os_info(self.vmid, f"{bver} / {kernel}")

    def audio_diag(self):
        """🎧 音频链路诊断: 通过 SSH 拉取 PulseAudio / Sunshine / Batocera 全链路状态,
        输出到下方执行面板, 用于定位『串流无声音』与『音量滑块掉回 0』。"""
        if not self.app.ssh:
            messagebox.showwarning("提示", "请先连接 PVE SSH 服务器！")
            return
        self._log("[*] 开始音频链路诊断 (PulseAudio / Sunshine / Batocera) ...")
        cmds = [
            ("batocera.conf audio.*", "grep -i audio /userdata/system/batocera.conf 2>/dev/null || echo '(无 audio 配置)'"),
            ("pulse 进程", "ps | grep -i pulse | grep -v grep || echo '(pulse 未运行)'"),
            ("pulse socket", "ls -l /var/run/pulse/native 2>&1"),
            ("pulse sinks", "PULSE_LIB=/userdata/system/pulse/lib; LD_LIBRARY_PATH=$PULSE_LIB /userdata/system/pulse/bin/pactl --server=unix:/var/run/pulse/native list short sinks 2>&1"),
            ("pulse sources", "PULSE_LIB=/userdata/system/pulse/lib; LD_LIBRARY_PATH=$PULSE_LIB /userdata/system/pulse/bin/pactl --server=unix:/var/run/pulse/native list short sources 2>&1"),
            ("pulse 客户端(是否含 sunshine)", "PULSE_LIB=/userdata/system/pulse/lib; LD_LIBRARY_PATH=$PULSE_LIB /userdata/system/pulse/bin/pactl --server=unix:/var/run/pulse/native list short clients 2>&1"),
            ("amixer Master", "PULSE_SERVER=unix:/var/run/pulse/native amixer sget Master 2>&1"),
            ("实时 sunshine.conf", "echo '--- .config/sunshine/sunshine.conf ---'; cat /userdata/system/.config/sunshine/sunshine.conf 2>/dev/null; echo '(end)'"),
            ("PULSE_CTL_LIBS", "ls -l /usr/lib/libcap.so.2 /usr/lib/libXtst.so.6 /usr/lib/libsystemd.so.0 /usr/lib/libwrap.so.0 /usr/lib/libasyncns.so.0 /usr/lib/libnsl.so.1 2>&1"),
        ]
        for title, cmd in cmds:
            self.run_cmd(cmd, "音频诊断·" + title)
        self._log("[*] 诊断已提交。重点排查: ① pulse 客户端是否出现 sunshine; ② sinks 是否为 auto_null; ③ amixer Master 是否 0%。")

    def run_cmd(self, cmd, name):
        self._log(f"[*] 执行【{name}】...")
        def task():
            try:
                out = self._run(cmd)
                self.after(0, lambda o=out: self._log(o if o else "(无输出)"))
            except Exception as e:
                self.after(0, lambda e=e: self._log(f"[-] 执行失败: {e}"))
        threading.Thread(target=task, daemon=True).start()

    def run_custom(self):
        cmd = self.entry_cmd.get().strip()
        if not cmd:
            return
        self._record_history(cmd)
        self.run_cmd(cmd, "自定义命令")

    def _fill_quick_cmd(self, event):
        sel = self.combo_quick.get()
        if not sel or sel == "快速填充…":
            return
        cmd = self.QUICK_CMDS.get(sel, "")
        if cmd:
            self.entry_cmd.delete(0, tk.END)
            self.entry_cmd.insert(0, cmd)
            self.entry_cmd.focus_set()

    def _record_history(self, cmd):
        if not cmd:
            return
        if not self._cmd_history or self._cmd_history[-1] != cmd:
            self._cmd_history.append(cmd)
        self._cmd_hist_idx = len(self._cmd_history)

    def _hist_up(self, event):
        if not self._cmd_history:
            return "break"
        if self._cmd_hist_idx > 0:
            self._cmd_hist_idx -= 1
            self.entry_cmd.delete(0, tk.END)
            self.entry_cmd.insert(0, self._cmd_history[self._cmd_hist_idx])
        return "break"

    def _hist_down(self, event):
        if not self._cmd_history:
            return "break"
        if self._cmd_hist_idx < len(self._cmd_history) - 1:
            self._cmd_hist_idx += 1
            self.entry_cmd.delete(0, tk.END)
            self.entry_cmd.insert(0, self._cmd_history[self._cmd_hist_idx])
        elif self._cmd_hist_idx == len(self._cmd_history) - 1:
            self._cmd_hist_idx = len(self._cmd_history)
            self.entry_cmd.delete(0, tk.END)
        return "break"

    def open_samba_share(self):
        ip = self.entry_ip.get().strip() or self.bato_ip or ""
        if not ip:
            messagebox.showwarning("提示", "请先填写或自动定位虚拟机 IP！")
            return
        try:
            os.startfile(f"\\\\{ip}\\share")
            self._log(f"[+] 已在本地资源管理器打开 Samba 共享: \\\\{ip}\\share")
        except Exception as e:
            self._log(f"[-] 打开 Samba 共享失败: {e}")
            messagebox.showerror("错误", f"无法打开共享文件夹 \\\\{ip}\\share\n{e}")

    def _auto_connect(self):
        """已知 IP 后自动在后台建立 SSH 连接并识别系统 (无需手动点连接)。"""
        if getattr(self, "_auto_connected", False) or self._closing:
            return
        self._auto_connected = True
        self.connect_bato()
        self.after(1500, self.identify)

    def do_reboot(self):
        """♻️ 重启: 先发重启指令, 状态切为『⏳ 重启中...』, 后台轮询探针, 系统恢复后自动重连。"""
        ip = self.entry_ip.get().strip() or self.bato_ip or ""
        self._log(f"[*] 正在重启 {ip} (发送 reboot)...")
        self._set_rebooting_state(True)
        def task():
            try:
                ssh = self._get_ssh()
                if ssh:
                    try:
                        ssh.exec_command("reboot")
                    except Exception:
                        pass
                self.after(0, lambda: self._log("[*] reboot 指令已发送, 等待系统重启..."))
            except Exception as e:
                self._log(f"[-] 重启指令发送失败: {e}")
        threading.Thread(target=task, daemon=True).start()
        threading.Thread(target=self._reconnect_probe, daemon=True).start()

    def _set_rebooting_state(self, on):
        try:
            if self._closing:
                return
            state = "⏳ 重启中..." if on else None
            if on:
                self.after(0, lambda: self.lbl_conn.config(text=state, fg="#ffffff", bg="#f59e0b")
                           if self.lbl_conn.winfo_exists() else None)
        except (tk.TclError, RuntimeError):
            pass

    def _reconnect_probe(self):
        """重启后轮询可达性与 SSH 恢复, 恢复后自动重连+识别。"""
        ip = self.entry_ip.get().strip() or self.bato_ip or ""
        waited = 0
        while not self._closing:
            time.sleep(3)
            waited += 3
            # 先探 SSH 端口, 若通则尝试重连
            if self._port_open(ip, 22):
                if self._try_reconnect_after_reboot(ip):
                    return
                # 刚恢复但 SSH 未完全就绪, 继续等到就绪
            elif waited % 30 == 0:
                self._log(f"[*] 重启中... 已等待 {waited}s (目标 {ip})")
            # 最多等 240s, 超时放弃
            if waited >= 240:
                self._log("[-] 等待重启恢复超时 (240s), 若系统已起来请手动点【🔌 连接】")
                self.after(0, lambda: self.lbl_conn.config(text="🔴 未连接", fg="#ffffff", bg="#dc2626")
                           if self.lbl_conn.winfo_exists() else None)
                self._reconnecting = False
                return

    def _port_open(self, host, port, timeout=2):
        import socket as _s
        try:
            s = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
            s.settimeout(timeout)
            r = s.connect_ex((host, port))
            s.close()
            return r == 0
        except Exception:
            return False

    def _try_reconnect_after_reboot(self, ip):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname=ip, port=22, username="root", password="linux", timeout=8, banner_timeout=15, auth_timeout=15)
            self.ssh_bato = ssh
            self.ssh_bato_ip = ip
            self._set_conn_state(True)
            self._reconnecting = False
            self.after(0, lambda: self._log(f"[+] 系统重启完成, 已自动重新连接 {ip}"))
            self.after(300, self.identify)
            self.after(500, self.load_resolutions)
            self.after(700, self.load_audio_devices)
            self.after(900, self.load_batocera_conf)
            return True
        except Exception:
            return False

    def launch_test_panel(self):
        """从本工具远程呼出 Batocera 屏幕上的 Python 测试面板 (盒上需已部署 python + test_panel.py)。"""
        # 先按脚本路径精确杀掉旧实例(BusyBox 无可靠 pkill, 改用 ps|grep 取 PID), 再拉起
        cmd = (
            "PIDS=$(ps | grep -v grep | grep '/userdata/system/test_panel.py' | awk '{print $1}'); "
            "for p in $PIDS; do kill $p 2>/dev/null; done; sleep 1; "
            "DISPLAY=:0 XAUTHORITY=/var/lib/.Xauthority nohup "
            "/userdata/system/python/bin/python3 /userdata/system/test_panel.py "
            ">/tmp/test_panel.log 2>&1 & echo LAUNCHED")
        self.run_cmd(cmd, "呼出测试面板")

    def close_test_panel(self):
        """从本工具远程收起(关闭) Batocera 屏幕上的测试面板。"""
        cmd = (
            "PIDS=$(ps | grep -v grep | grep '/userdata/system/test_panel.py' | awk '{print $1}'); "
            "for p in $PIDS; do kill $p 2>/dev/null; done; sleep 1; echo CLOSED")
        self.run_cmd(cmd, "收起测试面板")

    def clear_log(self):
        """清空底部输出日志框。"""
        try:
            if self._closing or not self.out_text.winfo_exists():
                return
            self.out_text.config(state="normal")
            self.out_text.delete("1.0", tk.END)
            self.out_text.config(state="disabled")
        except (tk.TclError, RuntimeError):
            pass

    def copy_log(self):
        """复制底部输出日志内容到剪贴板。"""
        try:
            if self._closing or not self.out_text.winfo_exists():
                return
            content = self.out_text.get("1.0", "end-1c")
            if not content.strip():
                content = "(日志为空)"
            self.clipboard_clear()
            self.clipboard_append(content)
            self.lbl_plug_status.config(text="📋 日志已复制", fg="#0ea5e9")
            self.after(2500, lambda: self.lbl_plug_status.config(text="状态: 就绪", fg="#6b7280"))
        except (tk.TclError, RuntimeError):
            pass

    def on_closing(self):
        # 用户关闭对话框: 标记关闭, 让后台线程不再触碰已销毁的控件
        self._closing = True
        self._stop_hint()
        if self.ssh_bato is not None:
            try:
                self.ssh_bato.close()
            except Exception:
                pass
            self.ssh_bato = None
        self.destroy()

    def _log(self, msg):
        if getattr(self, "_closing", False):
            return
        if threading.current_thread() is not threading.main_thread():
            try:
                self.after(0, lambda m=msg: self._log_r(m))
            except (tk.TclError, RuntimeError):
                pass
            return
        self._log_r(msg)

    def _log_r(self, msg):
        try:
            if getattr(self, "_closing", False) or not self.out_text.winfo_exists():
                return
            self.out_text.config(state="normal")
            self.out_text.insert(tk.END, msg + "\n")
            self.out_text.see(tk.END)
            self.out_text.config(state="disabled")
        except (tk.TclError, RuntimeError):
            pass
