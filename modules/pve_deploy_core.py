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
import shlex
import pve_bato_net
from concurrent.futures import ThreadPoolExecutor
import random
import string
import json
import ssl
import base64
import gzip
import shutil

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

class _DeployCoreMixin:
    def __init__(self, parent, app, vmid=None):
        super().__init__(parent)
        self.app = app
        self.vmid = vmid
        self.is_closed = False
        self.has_auto_started = False
        self.title(f"🎮 Batocera Sunshine 串流部署 ({('GLIBC免冲突终极版 - VM: '+str(vmid)) if vmid else '直连模式 - 任意 Batocera 地址'})")
        
        center_window(self, parent, 650, 620)
        self.minsize(620, 560)
        self.resizable(True, True)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

        frame = tk.Frame(self, padx=16, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="🚀 Batocera Sunshine 游戏串流全透明直推部署 (全库直补)", font=("Microsoft YaHei UI", 11, "bold"), fg="#1e90ff").pack(anchor="w", pady=(0, 6))

        # IP 自动解析框
        f_ip = tk.Frame(frame)
        f_ip.pack(fill="x", pady=3)
        tk.Label(f_ip, text="Batocera IPv4:", font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        self.entry_bato_ip = tk.Entry(f_ip, width=15, font=("Consolas", 10, "bold"), relief="solid", bd=1)
        self.entry_bato_ip.pack(side="left", padx=(4, 6))
        
        self.btn_auto_ip = tk.Button(f_ip, text="🔍 重新反查", font=("Microsoft YaHei UI", 9), padx=6, pady=1, command=self.auto_detect_ip)
        self.btn_auto_ip.pack(side="left", padx=2)

        if vmid is not None:
            self.btn_net = tk.Button(f_ip, text="🌐 配置网络/修复断网", bg="#e0f2fe", fg="#0369a1", font=("Microsoft YaHei UI", 9, "bold"), padx=6, pady=1, command=self.open_network_dialog)
            self.btn_net.pack(side="left", padx=4)

        # SSH 密码 与 Web 管理密码: 左右并排双列, 紧凑省纵向空间
        f_pwds = tk.Frame(frame)
        f_pwds.pack(fill="x", pady=3)

        f_pwd = tk.Frame(f_pwds)
        f_pwd.pack(side="left", fill="x", expand=True)
        tk.Label(f_pwd, text="Batocera 密码:", font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        self.entry_bato_pwd = tk.Entry(f_pwd, width=12, font=("Consolas", 10), relief="solid", bd=1)
        self.entry_bato_pwd.insert(0, "linux")
        self.entry_bato_pwd.pack(side="left", padx=(4, 4))

        f_webpwd = tk.Frame(f_pwds)
        f_webpwd.pack(side="left", fill="x", expand=True, padx=(6, 0))
        tk.Label(f_webpwd, text="Web 管理密码:", font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        self.entry_web_pwd = tk.Entry(f_webpwd, width=14, font=("Consolas", 10), relief="solid", bd=1, show="*")
        self.entry_web_pwd.pack(side="left", padx=(4, 4))
        tk.Label(f_webpwd, text="(默认 linux, 留空随机)", fg="gray", font=("Microsoft YaHei UI", 8)).pack(side="left")

        # 测试用 Python (tkinter 测试面板) 可选项: 仅调试测试时才需要, 默认不装
        f_optpy = tk.Frame(frame)
        f_optpy.pack(fill="x", pady=1)
        self.var_install_python = tk.IntVar(value=0)
        tk.Checkbutton(f_optpy, text="📦 同时安装测试用 Python", variable=self.var_install_python,
                       font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        tk.Label(f_optpy, text="(测试面板/插件中心 GUI 需要, 含 tkinter, 约40MB; 纯串流无需)",
                 fg="gray", font=("Microsoft YaHei UI", 8)).pack(side="left", padx=4)

        # 可视化平滑进度条
        f_prog = tk.Frame(frame, pady=4)
        f_prog.pack(fill="x")
        
        self.lbl_progress_status = tk.Label(f_prog, text="进度状态: 正在自动探测 Batocera 连通性...", font=("Microsoft YaHei UI", 9, "bold"), fg="#0d6efd")
        self.lbl_progress_status.pack(anchor="w", pady=(2, 2))

        self.progress = ttk.Progressbar(f_prog, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", pady=(0, 2))

        # 实时日志显示框
        tk.Label(frame, text="全阶段透明执行日志 (可在后台并行运行):", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(4, 2))
        self.txt_log = scrolledtext.ScrolledText(frame, height=9, bg="#1e1e1e", fg="#00ff00", font=("Consolas", 8))
        self.txt_log.pack(fill="both", expand=True, pady=2)

        # 底部按钮组: 聚合卡片化, 三级分层消除堆叠压迫
        f_btns = tk.Frame(frame)
        f_btns.pack(fill="x", pady=6)

        self.btn_start = tk.Button(f_btns, text="⚡ 极速直推 Sunshine (全量补齐所有缺失依赖)", bg="#ff9900", fg="white", font=("Microsoft YaHei UI", 10, "bold"), command=self.start_install)
        self.btn_start.pack(fill="x", padx=2, pady=(0, 4))

        # 高频使用栏: 并排 3 按钮
        f_btns2 = tk.Frame(frame)
        f_btns2.pack(fill="x", pady=(0, 4))

        self.btn_pair = tk.Button(f_btns2, text="📱 配对 Moonlight", bg="#9b59b6", fg="white", font=("Microsoft YaHei UI", 9, "bold"), command=self.open_pair_dialog)
        self.btn_pair.pack(side="left", fill="x", expand=True, padx=2)

        self.btn_show_pwd = tk.Button(f_btns2, text="🔑 显示 Web 密码", bg="#17a2b8", fg="white", font=("Microsoft YaHei UI", 9, "bold"), command=self.show_web_creds)
        self.btn_show_pwd.pack(side="left", fill="x", expand=True, padx=2)

        self.btn_check = tk.Button(f_btns2, text="🌐 刷新/进入后台", bg="#28a745", fg="white", font=("Microsoft YaHei UI", 9, "bold"), command=self.check_and_open)
        self.btn_check.pack(side="left", fill="x", expand=True, padx=2)

        # 低频维护工具栏: 并排 2 辅助按钮
        f_btns3 = tk.Frame(frame)
        f_btns3.pack(fill="x")

        self.btn_reset_pwd = tk.Button(f_btns3, text="🔄 重置密码", bg="#6c757d", fg="white", font=("Microsoft YaHei UI", 9), command=self.reset_web_creds)
        self.btn_reset_pwd.pack(side="left", fill="x", expand=True, padx=2)

        self.btn_force_card = tk.Button(f_btns3, text="🔧 强制重建声卡", bg="#e67e22", fg="white", font=("Microsoft YaHei UI", 9), command=self.force_card_rebuild)
        self.btn_force_card.pack(side="left", fill="x", expand=True, padx=2)

        self.after(100, self.auto_detect_ip)

    def on_close(self):
        self.is_closed = True
        self.destroy()

    def log_append(self, msg):
        if self.is_closed: return
        def _append():
            try:
                if self.winfo_exists():
                    self.txt_log.insert(tk.END, msg + "\n")
                    self.txt_log.see(tk.END)
            except Exception: pass
        self.after(0, _append)

    def update_progress(self, pct, status_text):
        if self.is_closed: return
        def _update():
            try:
                if self.winfo_exists():
                    self.progress['value'] = pct
                    self.lbl_progress_status.config(text=status_text)
            except Exception: pass
        self.after(0, _update)

    def force_card_rebuild(self):
        bato_ip = self.entry_bato_ip.get().strip()
        bato_pwd = self.entry_bato_pwd.get().strip() or "linux"
        if not bato_ip:
            messagebox.showwarning("提示", "请填写 Batocera IPv4 地址！")
            return
        self.btn_force_card.config(state="disabled")
        self.txt_log.delete("1.0", tk.END)
        self.log_append(f"[*] 强制造卡重部署: {bato_ip} (忽略声卡检测, 强制 snd-dummy 方案)")

        def task():
            try:
                bato_ssh = paramiko.SSHClient()
                bato_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                bato_ssh.connect(bato_ip, port=22, username="root", password=bato_pwd,
                                 timeout=15, look_for_keys=False, allow_agent=False)
                self.log_append(f"[+] 已连接 {bato_ip}:22")
                try:
                    self._deploy_audio(bato_ssh, bato_ip, force_card=True)
                except Exception as ae:
                    self.log_append(f"[-] 音频重部署异常: {ae}")
                # 立即在当前会话就绪 Dummy 卡并置 100%, 无需等重启
                _, o, _ = run_sync_cmd(bato_ssh,
                    "modprobe snd-dummy index=0 2>/dev/null || modprobe snd-dummy 2>/dev/null; "
                    "sleep 1; amixer -c 0 sset Master 100% 2>/dev/null; amixer -c 0 sset PCM 100% 2>/dev/null; "
                    "cat /proc/asound/cards 2>/dev/null")
                self.log_append(f"[+] 已即时加载 Dummy 卡:\n{o.strip() or '(无输出)'}")
                # 按最新 system.pa 重启私有 PulseAudio (幂等脚本 force 参数)
                run_sync_cmd(bato_ssh, "sh /userdata/system/pulse/audio_setup.sh force > /userdata/system/logs/pulse_boot.log 2>&1 || true")
                run_sync_cmd(bato_ssh, "bash /userdata/system/services/sunshine restart >/dev/null 2>&1 || true")
                self.log_append("[+] 完成。当前会话音量滑块若要立刻生效, 建议整机重启一次(确保 .xinitrc 的造卡先于 ES)。")
                bato_ssh.close()
            except Exception as ex:
                self.log_append(f"[-] 强制造卡失败: {ex}")
            finally:
                if not self.is_closed:
                    try:
                        if self.winfo_exists(): self.after(0, lambda: self.btn_force_card.config(state="normal"))
                    except Exception: pass

        threading.Thread(target=task, daemon=True).start()

    def open_network_dialog(self):
        if self.vmid:
            pve_bato_net.BatoceraNetworkDialog(self, self.app, self.vmid)
        else:
            messagebox.showinfo("直连模式", "网络配置/修复断网需在 PVE 虚拟机上下文中进行。\n直连模式下请直接在上方填写 Batocera 的 IPv4 与密码，再点击【⚡ 极速直推】部署串流。")

    def auto_detect_ip(self):
        # 优先读取持久化特征库中的 IP
        if self.vmid:
            import pve_net_config
            c_info = pve_net_config.ConfigManager.get_vm_info(self.vmid)
            if c_info.get("ip"):
                c_ip = c_info["ip"]
                self.entry_bato_ip.delete(0, tk.END)
                self.entry_bato_ip.insert(0, c_ip)
                self.lbl_progress_status.config(text=f"[+] 命中持久化特征 IP: {c_ip} (已就绪)", fg="green")
                self.log_append(f"[+] 命中虚拟机 {self.vmid} 持久化特征 IP: {c_ip}")
                return

        self.lbl_progress_status.config(text="[*] 正在反查 Batocera IPv4 并握手...")
        def task():
            target_ip = ""
            try:
                if self.vmid and self.app.ssh:
                    cfg = self.app.run_ssh_cmd(f"qm config {self.vmid}", ignore_error=True)
                    mac_match = re.search(r"net0:[^\n]*?([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", cfg)
                    if mac_match:
                        mac = mac_match.group(1).lower()
                        self.app.run_ssh_cmd("ping -c 1 -w 1 255.255.255.255 2>/dev/null || true", ignore_error=True)
                        neigh = self.app.run_ssh_cmd("ip neigh show", ignore_error=True)
                        for line in neigh.split('\n'):
                            if mac in line.lower():
                                parts = line.split()
                                if parts and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0]):
                                    target_ip = parts[0]
                                    break
            except Exception: pass

            if not target_ip:
                pve_ip = self.app.entry_ip.get().strip()
                if pve_ip:
                    subnet = ".".join(pve_ip.split('.')[:-1])
                    found = []
                    def test_ip(i):
                        ip = f"{subnet}.{i}"
                        if ip == pve_ip: return
                        try:
                            with socket.create_connection((ip, 22), timeout=0.2):
                                t = paramiko.Transport((ip, 22))
                                t.banner_timeout = 8
                                t.auth_timeout = 8
                                t.connect(username="root", password="linux")
                                t.close()
                                found.append(ip)
                        except Exception: pass

                    with ThreadPoolExecutor(max_workers=50) as ex:
                        for i in range(1, 255):
                            ex.submit(test_ip, i)

                    if found: target_ip = found[0]

            def update(ip):
                if self.is_closed: return
                if ip:
                    self.entry_bato_ip.delete(0, tk.END)
                    self.entry_bato_ip.insert(0, ip)
                    if self.vmid:
                        self.lbl_progress_status.config(text=f"[+] 识别到 Batocera IPv4: {ip} (已自动开始极速部署)", fg="green")
                        self.log_append(f"[+] 识别到 Batocera 目标虚拟机: {ip}，正在全自动拉起极速部署...")
                        if not self.has_auto_started:
                            self.has_auto_started = True
                            self.after(500, self.start_install)
                    else:
                        self.lbl_progress_status.config(text=f"[+] 识别到 Batocera IPv4: {ip} (直连模式, 请手动点击部署)", fg="green")
                        self.log_append(f"[+] 识别到 Batocera 目标: {ip}（直连模式，请手动点击【⚡ 极速直推】）")
                else:
                    self.lbl_progress_status.config(text="[-] 未能匹配到 IPv4，请手动输入" + ("" if self.vmid else " (直连模式)"), fg="red")
            
            try:
                if self.winfo_exists(): self.after(0, lambda: update(target_ip))
            except Exception: pass

        threading.Thread(target=task, daemon=True).start()

    def is_port_open(self, ip, port=47990):
        try:
            with socket.create_connection((ip, port), timeout=0.8):
                return True
        except Exception:
            return False

    def check_and_open(self):
        bato_ip = self.entry_bato_ip.get().strip()
        if not bato_ip:
            messagebox.showwarning("提示", "请先输入 IP！")
            return

        if self.is_port_open(bato_ip, 47990):
            user, pwd = "admin", ""
            try:
                if os.path.exists(CREDS_FILE):
                    for line in open(CREDS_FILE, encoding="utf-8"):
                        if "=" in line:
                            k, v = line.strip().split("=", 1)
                            if k == "username": user = v
                            elif k == "password": pwd = v
            except Exception:
                pass
            # 将账号密码嵌入 URL, 浏览器打开时自动填充 Basic 鉴权框
            url = f"https://{bato_ip}:47990/"
            if pwd:
                url = f"https://{user}:{pwd}@{bato_ip}:47990/"
            info = (
                f"🎉 Sunshine 串流服务正常运行中！\n\n"
                f"后台管理地址:\n{url}\n\n"
                f"💡 关键提示:\n"
                f"浏览器首次打开时若提示'您的连接不是私密连接/不安全'，"
                f"请点击页面上的【高级】->【继续前往 (不安全)】即可顺利进入后台！\n"
                f"账号密码已自动填入链接，多数浏览器会直接免输进入。\n\n"
                f"是否立刻打开？"
            )
            if messagebox.askyesno("服务就绪", info):
                webbrowser.open(url)
        else:
            self.log_append("[-] 47990 端口尚未就绪...")
            messagebox.showwarning("提示", "47990 端口尚未开放，请点击'极速直推'部署！")

    def open_pair_dialog(self):
        """在工具界面内完成 Moonlight PIN 配对, 不必打开浏览器。"""
        bato_ip = self.entry_bato_ip.get().strip()
        if not bato_ip:
            messagebox.showwarning("提示", "请先填写 Batocera IP！")
            return
        if not self.is_port_open(bato_ip, 47990):
            messagebox.showwarning("提示", "47990 端口未开放，请先部署/启动串流服务！")
            return
        user, pwd = "admin", ""
        try:
            if os.path.exists(CREDS_FILE):
                for line in open(CREDS_FILE, encoding="utf-8"):
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        if k == "username": user = v
                        elif k == "password": pwd = v
        except Exception:
            pass
        top = tk.Toplevel(self)
        top.title("📱 Moonlight 配对")
        center_window(top, self, 460, 340)
        top.transient(self)
        tk.Label(top, text="① 先在 Moonlight 客户端里点击此主机 (BATOCERA) 发起配对\n② Moonlight 会显示一个 4~6 位配对码 (PIN)",
                  font=("Microsoft YaHei UI", 9), justify="left", wraplength=420).pack(anchor="w", padx=10, pady=(8, 2))
        f_auto = tk.Frame(top)
        f_auto.pack(fill="x", padx=10, pady=2)
        tk.Button(f_auto, text="🔍 自动读取盒上日志配对码", command=lambda: self._pair_autofill(top, bato_ip, pin_entry)).pack(side="left", padx=2)
        tk.Label(f_auto, text="(读不到就手动填)", fg="gray", font=("Microsoft YaHei UI", 8)).pack(side="left")
        f_pin = tk.Frame(top)
        f_pin.pack(fill="x", padx=10, pady=4)
        tk.Label(f_pin, text="配对码 PIN:").pack(side="left")
        pin_entry = tk.Entry(f_pin, font=("Consolas", 14), width=12, relief="solid", bd=1)
        pin_entry.pack(side="left", padx=6)
        self._pair_status = tk.Label(top, text="", font=("Microsoft YaHei UI", 9), fg="#0d6efd", wraplength=420)
        self._pair_status.pack(anchor="w", padx=10, pady=4)
        f_ok = tk.Frame(top)
        f_ok.pack(fill="x", padx=10, pady=6)
        tk.Button(f_ok, text="✅ 提交配对", bg="#28a745", fg="white", font=("Microsoft YaHei UI", 10, "bold"),
                  command=lambda: self._pair_submit(top, bato_ip, user, pwd, pin_entry)).pack(side="left", fill="x", expand=True, padx=2)
        tk.Button(f_ok, text="❌ 取消", command=top.destroy).pack(side="left", fill="x", expand=True, padx=2)
        pin_entry.focus_set()

    def _pair_autofill(self, top, bato_ip, pin_entry):
        bato_pwd = self.entry_bato_pwd.get().strip() or "linux"
        self._pair_status.config(text="[*] 正在 SSH 读取盒上 Sunshine 日志寻找配对码...")
        def task():
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(hostname=bato_ip, port=22, username="root", password=bato_pwd, timeout=15, banner_timeout=30, auth_timeout=30)
                _, out, _ = run_sync_cmd(ssh, "tail -n 60 /userdata/system/logs/sunshine.log 2>/dev/null; tail -n 60 /tmp/sun_*.log 2>/dev/null")
                ssh.close()
                m = re.search(r"\b(\d{4,6})\b", out or "")
                if m:
                    pin = m.group(1)
                    top.after(0, lambda: (pin_entry.delete(0, tk.END), pin_entry.insert(0, pin),
                                           self._pair_status.config(text=f"[+] 自动读到配对码: {pin}，请点【提交配对】")))
                else:
                    top.after(0, lambda: self._pair_status.config(text="[-] 日志里没找到配对码，请手动填入 Moonlight 显示的 PIN"))
            except Exception as e:
                err_msg = str(e)
                top.after(0, lambda m=err_msg: self._pair_status.config(text=f"[-] 读取日志失败: {m}"))
        threading.Thread(target=task, daemon=True).start()

    def _pair_submit(self, top, bato_ip, user, pwd, pin_entry):
        pin = pin_entry.get().strip()
        if not re.fullmatch(r"\d{4,6}", pin):
            messagebox.showwarning("提示", "请输入 4~6 位数字配对码")
            return
        self._pair_status.config(text="[*] 正在通过 Sunshine API 提交配对码...")
        def task():
            try:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                req = urllib.request.Request(
                    f"https://{bato_ip}:47990/api/pin",
                    data=json.dumps({"pin": pin, "name": "Moonlight"}).encode("utf-8"),
                    method="POST")
                req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode())
                req.add_header("Content-Type", "application/json")
                with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                    body = r.read().decode("utf-8", "ignore")
                    code = r.status
                top.after(0, lambda: self._pair_status.config(
                    text=f"[+] 提交成功 (HTTP {code})！Moonlight 现在可直接串流，无需再开浏览器。\n返回: {body[:120]}", fg="green"))
                top.after(0, lambda: messagebox.showinfo("配对成功", "🎉 Moonlight 配对完成，现在可直接串流！"))
            except urllib.error.HTTPError as e:
                code = e.code
                detail = e.read().decode("utf-8", "ignore")[:160]
                top.after(0, lambda c=code, d=detail: self._pair_status.config(
                    text=f"[-] 配对失败 (HTTP {c}): {d}", fg="red"))
            except Exception as e:
                err_msg = str(e)
                top.after(0, lambda m=err_msg: self._pair_status.config(text=f"[-] 配对失败: {m}", fg="red"))
        threading.Thread(target=task, daemon=True).start()

    def save_web_creds(self, username, password, bato_ip):
        """将 Web 管理账号持久化到本地, 供【🔑 显示 Web 密码】随时重现查看"""
        try:
            os.makedirs(CREDS_DIR, exist_ok=True)
            with open(CREDS_FILE, "w", encoding="utf-8") as f:
                f.write(f"username={username}\npassword={password}\nbox_ip={bato_ip}\n")
        except Exception:
            pass

    def _verify_web_pwd_on_box(self, ssh, pwd):
        """在盒子上用 admin:pwd 访问 / 核验密码是否真的生效。
        若返回非 200 (说明旧实例仍在占用端口), 强杀旧进程并重启, 再核验一次。
        返回最终 HTTP 状态码字符串 ('200' 表示生效)。
        """
        import base64
        auth = base64.b64encode(f"admin:{pwd}".encode()).decode()
        check = (
            f"curl -sk -m 5 -H 'Authorization: Basic {auth}' https://127.0.0.1:47990/ "
            f"-o /dev/null -w '%{{http_code}}' 2>/dev/null || echo 000"
        )
        _, out, _ = run_sync_cmd(ssh, check)
        code = (out or "").strip().splitlines()[-1].strip() or "000"
        if code == "200":
            return code
        # 旧实例未退 -> 强杀后重启再验证
        self.log_append(f"[!] 密码核验返回 {code}, 疑似旧实例仍占用端口, 正在强杀重启...")
        try:
            ssh.exec_command("bash /userdata/system/services/sunshine restart > /dev/null 2>&1 || true", timeout=10)
        except Exception:
            pass
        time.sleep(6)
        _, out2, _ = run_sync_cmd(ssh, check)
        return (out2 or "").strip().splitlines()[-1].strip() or "000"

    def show_web_creds(self):
        """重现显示已保存的 Sunshine Web 管理账号 (可一键复制)"""
        try:
            if not os.path.exists(CREDS_FILE):
                messagebox.showinfo(
                    "Web 管理账号",
                    "尚未保存任何凭据。\n\n请先执行一次【⚡ 极速直推 Sunshine】部署，"
                    "或点击右侧【🔄 重置 Web 密码】生成一组新凭据。"
                )
                return
            data = {}
            for line in open(CREDS_FILE, encoding="utf-8"):
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    data[k] = v
            self._open_web_creds_window(
                data.get("username", "admin"),
                data.get("password", ""),
                data.get("box_ip", "")
            )
        except Exception as e:
            messagebox.showerror("读取失败", str(e)[:200])

    def _open_web_creds_window(self, username, password, box_ip, verify_code=None):
        """可复制凭据的小窗口; verify_code 为盒上核验结果 ('200' 表示生效)"""
        win = tk.Toplevel(self)
        win.title("🔑 Sunshine Web 管理账号")
        win.resizable(False, False)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        f = tk.Frame(win, padx=16, pady=14)
        f.pack()

        tk.Label(f, text="🌟 Sunshine Web 管理账号 (本地已保存)", font=("Microsoft YaHei UI", 10, "bold")).pack(anchor="w", pady=(0, 8))

        def row(label, value):
            rf = tk.Frame(f)
            rf.pack(fill="x", pady=2)
            tk.Label(rf, text=label, width=10, anchor="e").pack(side="left")
            tk.Entry(rf, textvariable=tk.StringVar(value=value), width=36, font=("Consolas", 10), state="readonly").pack(side="left", padx=4)

        row("用户名", username)
        row("密码", password)
        row("后台地址", f"https://{box_ip}:47990/")

        if verify_code is not None:
            ok = (verify_code == "200")
            status_txt = "✅ 已核验: 此密码在盒子上真实生效, 可直接登录" if ok else f"⚠ 核验返回 {verify_code}: 盒子可能仍有旧实例, 请重试或重新部署"
            tk.Label(f, text=status_txt, font=("Microsoft YaHei UI", 8, "bold"), fg=("green" if ok else "red")).pack(pady=(2, 0))

        def copy_pwd():
            self.clipboard_clear()
            self.clipboard_append(password)
            self.update_idletasks()
            btn_copy.config(text="✅ 已复制!", fg="green")
            win.after(1200, lambda: btn_copy.config(text="📋 复制密码", fg="#0369a1"))

        btn_copy = tk.Button(f, text="📋 复制密码", fg="#0369a1", font=("Microsoft YaHei UI", 9, "bold"), command=copy_pwd)
        btn_copy.pack(pady=(8, 2))
        tk.Label(f, text="浏览器接受“不安全”证书后，账号框输入以上信息即可进入。", font=("Microsoft YaHei UI", 8), fg="gray").pack()

    def _gui_alive(self):
        """主线程/after 回调里判断对话框是否仍存活, 防后台线程回填到已销毁控件。"""
        try:
            return bool(self.winfo_exists())
        except tk.TclError:
            return False

    def _safe_open_creds(self, username, password, box_ip, verify_code=None):
        """安全地打开凭据小窗口: 对话框若已被用户关闭则静默跳过, 不再抛 TclError。"""
        if not self._gui_alive():
            return
        try:
            self._open_web_creds_window(username, password, box_ip, verify_code=verify_code)
        except tk.TclError:
            pass

    def _safe_error(self, title, msg):
        """安全地弹错误框: 主根窗口存活才弹, 已关闭则静默。"""
        if not self._gui_alive():
            return
        try:
            messagebox.showerror(title, msg, parent=self)
        except tk.TclError:
            pass

    def reset_web_creds(self):
        """连盒子重新生成 Web 密码并回显/持久化 (可随时重现)"""
        bato_ip = self.entry_bato_ip.get().strip()
        bato_pwd = self.entry_bato_pwd.get().strip()
        if not bato_ip or not bato_pwd:
            messagebox.showwarning("提示", "请先填写 Batocera IP 与密码！")
            return

        fixed_pwd = self.entry_web_pwd.get().strip()
        new_pwd = fixed_pwd if fixed_pwd else "batocera"

        def task():
            try:
                self.log_append("[*] 正在连接 Batocera 重置 Web 管理密码...")
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(hostname=bato_ip, port=22, username="root", password=bato_pwd, timeout=10, banner_timeout=30, auth_timeout=30)

                # 强杀旧实例 + 清空 state + 预置凭据 + 重启 + 盒上核验
                code = self._apply_web_creds(ssh, bato_ip, new_pwd)
                ssh.close()

                self.save_web_creds("admin", new_pwd, bato_ip)
                # 后台线程不能直接碰控件; 经 after(0) 回主线程。回调前必须确认对话框还活着,
                # 否则用户中途关闭对话框后会抛 'bad window path name' TclError 崩掉主界面。
                self.after(0, lambda c=code, p=new_pwd: self._safe_open_creds("admin", p, bato_ip, verify_code=c))
                self.log_append(f"[+] [Web 密码已重置] 用户名: admin  密码: {new_pwd}  核验: {code}")
            except Exception as e:
                err_msg = str(e)[:200]
                self.after(0, lambda m=err_msg: self._safe_error("重置失败", m))

        threading.Thread(target=task, daemon=True).start()

    def _ask_running_choice(self):
        """盒上已检测到 Sunshine 在运行时, 弹窗让用户选择: 重置密码 / 重新注入 / 取消。
        在子线程中调用, 通过 Event 等待主线程对话框结果。"""
        import threading as _th
        evt = _th.Event()
        res = {"v": "cancel"}
        def show():
            try:
                dlg = tk.Toplevel(self)
                dlg.title("检测到 Sunshine 正在运行")
                dlg.resizable(False, False)
                try:
                    dlg.attributes("-topmost", True)
                except Exception:
                    pass
                dlg.grab_set()
                f = tk.Frame(dlg, padx=18, pady=14)
                f.pack()
                tk.Label(f, text="盒上已检测到 Sunshine 串流进程在运行。\n请选择如何处理：",
                         font=("Microsoft YaHei UI", 10, "bold"), justify="left").pack(anchor="w", pady=(0, 10))
                def choose(v):
                    res["v"] = v
                    evt.set()
                    dlg.destroy()
                tk.Button(f, text="🌐 直接访问 WEB 管理后台 (浏览器打开)", bg="#0d6efd", fg="white",
                          font=("Microsoft YaHei UI", 9, "bold"), width=28,
                          command=lambda: choose("web")).pack(pady=3, fill="x")
                tk.Button(f, text="🔄 杀掉并重启 Sunshine (保留现有部署)", bg="#fd7e14", fg="white",
                          font=("Microsoft YaHei UI", 9, "bold"), width=28,
                          command=lambda: choose("restart")).pack(pady=3, fill="x")
                tk.Button(f, text="🔑 仅重置 Web 密码", bg="#17a2b8", fg="white",
                          font=("Microsoft YaHei UI", 9, "bold"), width=28,
                          command=lambda: choose("reset")).pack(pady=3, fill="x")
                tk.Button(f, text="⚡ 重新注入 (覆盖重装)", bg="#28a745", fg="white",
                          font=("Microsoft YaHei UI", 9, "bold"), width=28,
                          command=lambda: choose("reinject")).pack(pady=3, fill="x")
                tk.Button(f, text="✖ 取消", bg="#6c757d", fg="white",
                          font=("Microsoft YaHei UI", 9), width=28,
                          command=lambda: choose("cancel")).pack(pady=3, fill="x")
                dlg.protocol("WM_DELETE_WINDOW", lambda: choose("cancel"))
            except Exception:
                evt.set()
        self.after(0, show)
        evt.wait(120)
        return res["v"]

    def _load_creds(self):
        """读取本地已保存的 Sunshine Web 凭据 (username/password/box_ip)。"""
        data = {}
        try:
            if os.path.exists(CREDS_FILE):
                for line in open(CREDS_FILE, encoding="utf-8"):
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        data[k] = v
        except Exception:
            pass
        return data

    def _restart_sunshine(self, ssh, bato_ip):
        """杀掉并重启盒上已有的 Sunshine 实例 (带实时进度流与日志回显，彻底杜绝静默假死)"""
        self.log_append("[*] 正在停止并重新拉起 Sunshine 守护进程...")
        self.update_progress(20, "正在重启 Sunshine 串流服务...")
        try:
            # 异步非阻塞发送重启指令
            run_sync_cmd(ssh, "nohup bash /userdata/system/services/sunshine restart > /userdata/system/logs/sunshine_boot.log 2>&1 &")
        except Exception as e:
            self.log_append(f"[-] 重启指令发送异常: {e}")

        ok = False
        for sec in range(15):
            if self.is_closed: break
            time.sleep(1.5)
            pct = min(95, 20 + sec * 5)
            self.update_progress(pct, f"⏳ 正在等待 Sunshine 47990 端口就绪 ({sec+1}/15)...")

            if self.is_port_open(bato_ip, 47990):
                ok = True
                break

            if sec % 2 == 0:
                try:
                    _, log_tail, _ = run_sync_cmd(ssh, "tail -n 2 /userdata/system/logs/sunshine.log 2>/dev/null || true")
                    if log_tail.strip():
                        self.log_append(f"[{sec+1}s] {log_tail.splitlines()[-1]}")
                except Exception: pass

        if ok:
            self.update_progress(100, "🎉 Sunshine 服务已成功重启！")
            self.log_append("[+] 🎉 47990 端口已就绪！Sunshine 串流正常运行中。")
            web_url = f"https://{bato_ip}:47990/"
            try: webbrowser.open(web_url)
            except Exception: pass
            creds = self._load_creds()
            self.after(0, lambda u=web_url: self._open_web_creds_window(
                creds.get("username", "admin"), creds.get("password", ""), bato_ip))
        else:
            self.update_progress(0, "[-] Sunshine 启动超时，请查看下方日志")
            self.log_append("[-] 47990 端口未在预期时间内开启！正在抓取盒上详细崩溃日志...")
            try:
                _, full_err, _ = run_sync_cmd(ssh, "tail -n 15 /userdata/system/logs/sunshine.log 2>/dev/null || tail -n 15 /userdata/system/logs/sunshine_boot.log 2>/dev/null")
                if full_err.strip():
                    self.log_append(f"\n===== 盒上 Sunshine 崩溃日志 =====\n{full_err.strip()}\n================================")
                self.log_append("\n💡 【排查指引】: 若因缺少 GLIBC 导致旧引擎无法运行，请再次点击【⚡ 极速直推 Sunshine】，在弹窗中改选【⚡ 重新注入 (覆盖重装)】以全量补齐依赖库。\n")
            except Exception: pass

    def _apply_web_creds(self, ssh, bato_ip, new_pwd):
        """复用已有 SSH 连接: 强杀旧实例 + 清空 state + 预置凭据 + 重启 + 盒上核验。返回核验码。"""
        ssh.exec_command("bash /userdata/system/services/sunshine stop > /dev/null 2>&1 || true", timeout=10)
        ssh.exec_command("rm -f /userdata/system/configs/sunshine/sunshine_state.json", timeout=10)
        # 动态定位 Sunshine 二进制 (兼容 AppImage 解压目录 / 直跑 AppImage / 其它安装路径)
        detect = (
            "SUNBIN=''; SUNDIR=''; "
            "for p in /userdata/system/sunshine_app/usr/bin/sunshine /userdata/system/sunshine/usr/bin/sunshine; do "
            "  if [ -x \"$p\" ]; then SUNBIN=\"$p\"; SUNDIR=$(dirname $(dirname \"$p\")); break; fi; "
            "done; "
            "if [ -z \"$SUNBIN\" ]; then "
            "  pid=$(pgrep -f 'usr/bin/sunshine' | head -1); "
            "  if [ -n \"$pid\" ]; then SUNBIN=$(tr '\\0' ' ' < /proc/$pid/cmdline | awk '{print $1}'); SUNDIR=$(dirname $(dirname \"$SUNBIN\")); fi; "
            "fi; "
            "if [ -z \"$SUNBIN\" ]; then "
            "  ai=$(ls /userdata/system/sunshine.AppImage 2>/dev/null | head -1); "
            "  if [ -n \"$ai\" ]; then SUNBIN=\"$ai\"; SUNDIR=''; fi; "
            "fi; "
            "echo \"$SUNBIN|$SUNDIR\""
        )
        stdin, stdout, _ = ssh.exec_command(detect, timeout=15)
        line = stdout.read().decode("utf-8", "ignore").strip()
        sunbin, sundir = (line.split("|", 1) + ["", ""])[:2] if "|" in line else ("", "")
        if not sunbin:
            self.log_append("[-] 未找到 Sunshine 二进制, 无法重置 Web 密码 (请改选『重装 Sunshine』)")
            ssh.exec_command("bash /userdata/system/services/sunshine restart > /dev/null 2>&1 || true", timeout=10)
            return "000000"
        ld = (f"{sundir}/usr/lib:{sundir}/usr/lib/x86_64-linux-gnu:{sundir}/lib:{sundir}/lib/x86_64-linux-gnu:/usr/lib:/lib"
              if sundir else "/usr/lib:/lib")
        cd = f"cd '{sundir}' && " if sundir else ""
        # 严格转义动态参数, 防止密码/路径含单引号或 $ 等破坏外层 Shell 字符串
        q_pwd = shlex.quote(new_pwd)
        q_bin = shlex.quote(sunbin)
        creds_cmd = (
            f"export HOME=/userdata/system; "  # Sunshine 启动时的 HOME=/userdata/system, state.json 落在此处 .config/sunshine, 必须与之一致
            f"export LD_LIBRARY_PATH={ld}; "
            f"export SUNSHINE_CONFIG_DIR=/userdata/system/configs/sunshine; "
            f"{cd} {q_bin} --creds admin {q_pwd} 2>&1 || true"
        )
        stdin, stdout, stderr = ssh.exec_command(creds_cmd, timeout=25)
        stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", "ignore") + stderr.read().decode("utf-8", "ignore")
        self.log_append(f"[creds] {out.strip()[:200]}")
        ssh.exec_command("bash /userdata/system/services/sunshine restart > /dev/null 2>&1 || true", timeout=10)
        time.sleep(5)
        code = self._verify_web_pwd_on_box(ssh, new_pwd)
        self.save_web_creds("admin", new_pwd, bato_ip)
        return code
