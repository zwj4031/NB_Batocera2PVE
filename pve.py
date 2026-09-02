import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import paramiko
import threading
import subprocess
import webbrowser
import os
import time
import re
import sys

# 根目录仅保留 pve.py 入口, 所有业务模块统一在 modules/ 子目录, 以裸模块名互相引用
_MODULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules")
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)

import pve_net_config
import pve_stream
import pve_ui_dialogs
import pve_local_mgr
import pve_vnc
import pve_bato_net
import pve_bato_console
import pve_host_net
import pve_create_vm
import pve_bundle

# ---- 打包版(windowed, 无控制台)会静默吞掉所有未捕获异常 ----
# 冻结时把 Traceback 写到 exe 同目录 pve_error.txt, 否则报错无从查起
if getattr(sys, "frozen", False):
    _OLD_EXCEPTHOOK = sys.excepthook
    def _pve_excepthook(etype, evalue, tb):
        try:
            import traceback
            logp = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "pve_error.txt")
            with open(logp, "a", encoding="utf-8") as _f:
                _f.write("=" * 60 + "\n")
                _f.write("".join(traceback.format_exception(etype, evalue, tb)))
        except Exception:
            pass
        _OLD_EXCEPTHOOK(etype, evalue, tb)
    sys.excepthook = _pve_excepthook

APP_VERSION = "v3.0.0"

class PveManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"⚡ NB宗 · PVE Batocera 圣堂级一键部署神器 ({APP_VERSION} · 2026终极神教版)")
        self.root.geometry("920x660")
        self.root.resizable(True, True)
        
        self.ssh = None
        self.sftp = None
        self.pve_node = "pve"
        
        self.cmd_history = []
        self.cmd_history_idx = -1

        # --- 全局 ttk 字体与行距大号化样式配置 ---
        style = ttk.Style()
        style.configure("Treeview", font=("Microsoft YaHei UI", 10), rowheight=28)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 10, "bold"), padding=[16, 6])
        style.configure("TCombobox", font=("Microsoft YaHei UI", 10))

        # --- 自定义窗口图标 (移除默认羽毛图标) ---
        try:
            _icon = tk.PhotoImage(data="R0lGODlhIAAgAIAAACVj6////wAAACwAAAAAIAAgAAAAAAAIAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQA7")
            self.root.iconphoto(True, _icon)
        except Exception:
            pass

        # --- 1. 顶部全新重构: 现代双层大号仪表卡片 ---
        f_header = tk.Frame(root, bg="#ffffff", padx=12, pady=8, relief="solid", bd=1)
        f_header.pack(fill="x", padx=8, pady=(6, 4))

        # Row 1: 服务器地址、密码与连接控制 (大号字体)
        f_row1 = tk.Frame(f_header, bg="#ffffff")
        f_row1.pack(fill="x", pady=(0, 6))

        tk.Label(f_row1, text="🖥️ PVE 服务器:", font=("Microsoft YaHei UI", 10, "bold"), bg="#ffffff", fg="#333333").pack(side="left")
        self.entry_ip = tk.Entry(f_row1, width=15, font=("Consolas", 10, "bold"), bd=1, relief="solid")
        self.entry_ip.insert(0, "192.168.1.100")
        self.entry_ip.pack(side="left", padx=(4, 2))

        tk.Label(f_row1, text=":", bg="#ffffff", fg="#666666", font=("Consolas", 10, "bold")).pack(side="left")
        self.entry_port = tk.Entry(f_row1, width=4, font=("Consolas", 10, "bold"), bd=1, relief="solid")
        self.entry_port.insert(0, "22")
        self.entry_port.pack(side="left", padx=(2, 10))

        tk.Label(f_row1, text="🔑 Root 密码:", font=("Microsoft YaHei UI", 10, "bold"), bg="#ffffff", fg="#333333").pack(side="left")
        self.entry_pwd = tk.Entry(f_row1, show="*", width=12, font=("Consolas", 10, "bold"), bd=1, relief="solid")
        self.entry_pwd.pack(side="left", padx=(4, 10))

        self.btn_scan = tk.Button(f_row1, text="🔍 扫局域网", font=("Microsoft YaHei UI", 9, "bold"), bg="#f3f4f6", fg="#374151", bd=1, relief="solid", padx=8, pady=2, cursor="hand2", command=self.start_scan_pve)
        self.btn_scan.pack(side="left", padx=2)

        self.btn_connect = tk.Button(f_row1, text="⚡ 建立连接", font=("Microsoft YaHei UI", 10, "bold"), bg="#2563eb", fg="white", bd=0, padx=14, pady=3, cursor="hand2", command=self.start_connect_thread)
        self.btn_connect.pack(side="left", padx=4)

        self.btn_save = tk.Button(f_row1, text="💾 记住凭据", font=("Microsoft YaHei UI", 9, "bold"), bg="#f3f4f6", fg="#374151", bd=1, relief="solid", padx=8, pady=2, cursor="hand2", command=self.save_current_config)
        self.btn_save.pack(side="left", padx=2)

        # Row 2: 状态指示灯、当前全局 VMID 与快捷工具栏 (大号字体)
        f_row2 = tk.Frame(f_header, bg="#ffffff")
        f_row2.pack(fill="x", pady=(2, 0))

        self.lbl_conn_status = tk.Label(f_row2, text="⚪ 未连接 PVE 服务器", font=("Microsoft YaHei UI", 9, "bold"), bg="#ffffff", fg="#6b7280")
        self.lbl_conn_status.pack(side="left", padx=(2, 14))

        tk.Label(f_row2, text="🎯 当前全局 VMID:", font=("Microsoft YaHei UI", 10, "bold"), bg="#ffffff", fg="#1e40af").pack(side="left")
        self.entry_vmid = tk.Entry(f_row2, width=6, font=("Consolas", 10, "bold"), bd=1, relief="solid", justify="center")
        self.entry_vmid.insert(0, "100")
        self.entry_vmid.pack(side="left", padx=(4, 10))

        self.btn_about = tk.Button(f_row2, text="⚡ 关于 NB宗", bg="#8b5cf6", fg="white", font=("Microsoft YaHei UI", 9, "bold"), bd=0, padx=12, pady=2, cursor="hand2", command=self.show_about_dialog)
        self.btn_about.pack(side="right", padx=2)

        self.btn_host_net = tk.Button(f_row2, text="🌐 宿主机网络 (高危)", bg="#f59e0b", fg="white", font=("Microsoft YaHei UI", 9, "bold"), bd=0, padx=12, pady=2, cursor="hand2", command=self.open_host_net_dialog)
        self.btn_host_net.pack(side="right", padx=4)

        self.btn_stream_standalone = tk.Button(f_row2, text="🎮 直连Batocera串流", bg="#1e90ff", fg="white", font=("Microsoft YaHei UI", 9, "bold"), bd=0, padx=12, pady=2, cursor="hand2", command=self.open_stream_dialog_standalone)
        self.btn_stream_standalone.pack(side="right", padx=4)

        # --- 2. 核心工作区 ---
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=5)
        self.notebook.bind("<<NotebookTabChanged>>", self.on_main_tab_changed)

        # 选项卡 1: 虚拟机总览与管理
        self.tab_vm = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_vm, text="🕹️ 虚拟机管理中心 (右键呼出菜单)")
        self._init_vm_center_tab(self.tab_vm)

        # 选项卡 2: 镜像与存储部署
        self.tab_deploy = pve_local_mgr.LocalManagerTab(self.notebook, self)
        self.notebook.add(self.tab_deploy, text="🚀 镜像与存储部署")

        # 选项卡 3: 独立交互式终端与实时日志
        self.tab_log = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_log, text="📜 终端控制台与实时日志")
        self._init_log_tab(self.tab_log)

        self.root.after(150, self.load_current_config)

        self._start_bundle_release()

    def _start_bundle_release(self):
        """打包版启动时在后台按需释放内置缓存与 vncviewer 到 exe 同目录 (脚本运行则跳过)。"""
        if not getattr(sys, "_MEIPASS", None):
            return
        def _worker():
            try:
                pve_bundle.release_all()
            except Exception:
                try:
                    import traceback
                    logp = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "pve_error.txt")
                    with open(logp, "a", encoding="utf-8") as _f:
                        _f.write("=" * 60 + "\n[release]\n" + traceback.format_exc())
                except Exception:
                    pass
        try:
            threading.Thread(target=_worker, daemon=True).start()
        except Exception:
            pass
    def show_about_dialog(self):
        """NB宗门 专属关于弹窗 (大号易读版)"""
        about_win = tk.Toplevel(self.root)
        about_win.title("⚡ 关于 NB宗")
        about_win.geometry("540x480")
        about_win.resizable(False, False)
        about_win.transient(self.root)
        about_win.grab_set()

        f = tk.Frame(about_win, padx=20, pady=18, bg="#1a1a2e")
        f.pack(fill="both", expand=True)

        tk.Label(f, text="⚡ NB宗 · PVE 终极游戏布道神器 ⚡", font=("Microsoft YaHei UI", 14, "bold"), fg="#e94560", bg="#1a1a2e").pack(pady=(0, 2))
        tk.Label(f, text="—— 专治各种黑屏、死锁、报错与不服 ——", font=("Microsoft YaHei UI", 10, "italic"), fg="#4ecca3", bg="#1a1a2e").pack(pady=(0, 10))

        msg = (
            "【核心作者】\n"
            "👑 架构总师 · 宗门巨擘：江南一根葱\n\n"
            "【NB宗 · 独门绝技】\n"
            "• 🚀 0秒 ISO 光驱直挂：免漫长转换，即点即玩\n"
            "• 🕵️ 50线程指纹探针：秒抓 Batocera 真实 IPv4\n"
            "• 🕹️ RealVNC / noVNC 双控：多分辨率窗口秒连\n"
            "• 🚑 启动冲突智能自愈：秒解 SPICE 音频与死锁\n"
            "• 💽 物理硬盘直接挂载：免命令直接提取大镜像\n"
            "• 🎮 Sunshine 4K 串流：免 Flatpak 独立绿色即开\n\n"
            "【宗门信条】\n"
            "NB宗出品 · 必属精品 · 极简好用！"
        )
        lbl = tk.Label(f, text=msg, justify="left", font=("Microsoft YaHei UI", 11), fg="#f5f5f5", bg="#16213e", padx=16, pady=14, relief="groove")
        lbl.pack(fill="both", expand=True)

        btn_close = tk.Button(f, text="🔥 领悟葱爷心法，即刻开搞！", bg="#e94560", fg="white", font=("Microsoft YaHei UI", 11, "bold"), cursor="hand2", command=about_win.destroy)
        btn_close.pack(fill="x", pady=(12, 0))

    def on_main_tab_changed(self, event):
        if not self.ssh: return
        idx = self.notebook.index(self.notebook.select())
        if idx == 0:
            self.refresh_vms()
        elif idx == 1:
            self.tab_deploy.scan_storage()

    def _init_vm_center_tab(self, parent):
        f_bar = tk.Frame(parent, pady=4)
        f_bar.pack(fill="x", padx=5)

        tk.Button(f_bar, text="🔄 刷新列表", bg="lightblue", font=("Microsoft YaHei UI", 9, "bold"), command=lambda: self.refresh_vms(force=True)).pack(side="left", padx=2)
        tk.Button(f_bar, text="➕ 创建虚拟机", bg="#28a745", fg="white", font=("Microsoft YaHei UI", 9, "bold"), command=self.open_create_vm_dialog).pack(side="left", padx=4)
        
        # 醒目的双击与右键提示
        tk.Label(f_bar, text="💡 提示: 鼠标双击直接呼出 VNC 窗口；右键呼出开机/关机/自愈/全量硬件编辑菜单", fg="#0066cc", font=("Microsoft YaHei UI", 9, "bold")).pack(side="left", padx=8)

        f_tree = tk.Frame(parent)
        f_tree.pack(fill="both", expand=True, padx=5, pady=3)

        self.tree_vms = ttk.Treeview(f_tree, columns=("vmid", "name", "ip", "status", "mem", "pid", "os"), show="headings")
        self.tree_vms.heading("vmid", text="VM ID")
        self.tree_vms.heading("name", text="虚拟机名称")
        self.tree_vms.heading("ip", text="IPv4")
        self.tree_vms.heading("status", text="运行状态")
        self.tree_vms.heading("mem", text="内存 (MB)")
        self.tree_vms.heading("pid", text="进程 PID")
        self.tree_vms.heading("os", text="系统 / 版本")

        self.tree_vms.column("vmid", width=70, anchor="center")
        self.tree_vms.column("name", width=170, anchor="w")
        self.tree_vms.column("ip", width=120, anchor="w")
        self.tree_vms.column("status", width=90, anchor="center")
        self.tree_vms.column("mem", width=90, anchor="e")
        self.tree_vms.column("pid", width=90, anchor="center")
        self.tree_vms.column("os", width=200, anchor="w")

        self.vm_os_info = {}
        self.vm_ip_info = {}

        scroll = ttk.Scrollbar(f_tree, orient=tk.VERTICAL, command=self.tree_vms.yview)
        self.tree_vms.configure(yscrollcommand=scroll.set)
        self.tree_vms.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # 绑定双击与超链接交互
        self.tree_vms.tag_configure("bato_link", foreground="#16a34a", font=("Microsoft YaHei UI", 10, "bold"))
        self.tree_vms.tag_configure("normal", foreground="#333333")

        self.tree_vms.bind("<<TreeviewSelect>>", self.on_vm_select)
        self.tree_vms.bind("<Double-1>", lambda e: self.start_vnc_with_res("1280x720"))
        self.tree_vms.bind("<Button-3>", self.show_context_menu)
        self.tree_vms.bind("<Button-2>", self.show_context_menu)
        self.tree_vms.bind("<Motion>", self._on_tree_motion)
        self.tree_vms.bind("<ButtonRelease-1>", self._on_tree_click)

        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="➕ 新建虚拟机 (支持Batocera模板/自定义)", command=self.open_create_vm_dialog)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="▶ 开机 (Start)", command=lambda: self.run_vm_action("start"))
        self.context_menu.add_command(label="⏹ 正常关机 (Shutdown)", command=lambda: self.run_vm_action("shutdown"))
        self.context_menu.add_command(label="⚡ 强制拔电 (Stop)", command=lambda: self.run_vm_action("stop"))
        self.context_menu.add_command(label="🔄 重启 (Reboot)", command=lambda: self.run_vm_action("reboot"))
        self.context_menu.add_command(label="🔌 强制重启 (拔电后重开)", command=self.force_power_cycle)
        self.context_menu.add_command(label="🚑 一键诊断与修复开机故障 (自愈音频/死锁/引导)", command=self.auto_heal_vm)
        self.context_menu.add_separator()
        
        self.context_menu.add_command(label="🌐 打开 noVNC 网页控制台 (PVE原生, 自动进入画面)", font=("Microsoft YaHei UI", 9, "bold"), command=self.open_novnc_browser)
        self.context_menu.add_command(label="🌙 用 Moonlight 串流连接 (自动查找本机客户端)", command=self.open_moonlight_stream)

        # 本地 RealVNC / TightVNC 等客户端直连 (走 PVE 宿主机的 5900+VMID 端口, 多分辨率窗口)
        vnc_submenu = tk.Menu(self.context_menu, tearoff=0)
        for label, res in pve_vnc.VncLauncher.RESOLUTIONS:
            vnc_submenu.add_command(label=label, command=lambda r=res: self.start_vnc_with_res(r))
        self.context_menu.add_cascade(label="🕹 用 vncviewer.exe 直连 (多分辨率预设)", menu=vnc_submenu)
        
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🛠 编辑虚拟机 (全量配置/引导修复/Batocera调优)", command=self.open_hw_config)
        self.context_menu.add_command(label="⚡ 配置 PCI 硬件直通与显卡", command=self.open_pci_dialog)
        self.context_menu.add_command(label="🌐 配置虚拟机网络 (静态IP/DNS/重启网卡)", command=self.open_net_dialog)
        self.context_menu.add_command(label="🔧 Batocera 控制台 (版本/内核/SSH指令/插件库)", command=self.open_bato_console)
        self.context_menu.add_command(label="🎮 开启 Sunshine 游戏串流服务 (4K/低延迟/带声音)", command=self.open_stream_dialog)
        self.context_menu.add_command(label="🌐 直连其它 Batocera 安装串流 (无需 PVE 虚拟机)", command=self.open_stream_dialog_standalone)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="🗑 彻底销毁(删除)该虚拟机", command=self.destroy_selected_vm)

    def _init_log_tab(self, parent):
        f_bar = tk.Frame(parent, pady=4)
        f_bar.pack(fill="x", padx=6)
        
        tk.Button(f_bar, text="🧹 清空屏幕", font=("Microsoft YaHei UI", 9), bg="#f8f9fa", command=self.clear_log).pack(side="left", padx=2)
        tk.Button(f_bar, text="📋 复制全部日志", font=("Microsoft YaHei UI", 9), bg="#f8f9fa", command=self.copy_all_log).pack(side="left", padx=4)
        tk.Button(f_bar, text="⏻ 强制关机 PVE", font=("Microsoft YaHei UI", 9, "bold"), bg="#dc3545", fg="white", command=self.force_poweroff_pve).pack(side="left", padx=2)
        tk.Label(f_bar, text="💡 提示: 底部为交互式命令行，可直接输入 PVE/Linux 命令执行 (支持 ↑/↓ 历史命令)", font=("Microsoft YaHei UI", 9), fg="#0066cc").pack(side="left", padx=10)

        self.log_text = scrolledtext.ScrolledText(parent, state='disabled', bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True, padx=6, pady=2)

        f_cmd = tk.Frame(parent, padx=6, pady=4, bg="#f5f5f5")
        f_cmd.pack(fill="x", side="bottom")

        tk.Label(f_cmd, text="PVE 终端 >", font=("Consolas", 10, "bold"), fg="#1e90ff", bg="#f5f5f5").pack(side="left", padx=(2, 4))
        self.entry_cmd = tk.Entry(f_cmd, font=("Consolas", 10))
        self.entry_cmd.pack(side="left", fill="x", expand=True, padx=4)

        self.entry_cmd.bind("<Return>", lambda e: self.exec_custom_cmd())
        self.entry_cmd.bind("<Up>", self.on_cmd_history_up)
        self.entry_cmd.bind("<Down>", self.on_cmd_history_down)

        btn_run = tk.Button(f_cmd, text="🚀 执行命令 (Enter)", bg="#28a745", fg="white", font=("Microsoft YaHei UI", 9, "bold"), command=self.exec_custom_cmd)
        btn_run.pack(side="right", padx=2)

    def exec_custom_cmd(self):
        cmd = self.entry_cmd.get().strip()
        if not cmd: return
        if not self.ssh:
            self.log("[-] 错误: PVE SSH 尚未连接，无法执行命令！")
            return
            
        self.cmd_history.append(cmd)
        self.cmd_history_idx = len(self.cmd_history)
        self.entry_cmd.delete(0, tk.END)
        
        def task():
            try:
                self.run_ssh_cmd(cmd, ignore_error=True)
            except Exception as e:
                self.log(f"[-] 命令执行异常: {e}")
        threading.Thread(target=task, daemon=True).start()

    def on_cmd_history_up(self, event):
        if not self.cmd_history: return "break"
        if self.cmd_history_idx > 0:
            self.cmd_history_idx -= 1
            self.entry_cmd.delete(0, tk.END)
            self.entry_cmd.insert(0, self.cmd_history[self.cmd_history_idx])
        return "break"

    def on_cmd_history_down(self, event):
        if not self.cmd_history: return "break"
        if self.cmd_history_idx < len(self.cmd_history) - 1:
            self.cmd_history_idx += 1
            self.entry_cmd.delete(0, tk.END)
            self.entry_cmd.insert(0, self.cmd_history[self.cmd_history_idx])
        else:
            self.cmd_history_idx = len(self.cmd_history)
            self.entry_cmd.delete(0, tk.END)
        return "break"

    def clear_log(self):
        self.log_text.config(state='normal')
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state='disabled')

    def copy_all_log(self):
        text = self.log_text.get("1.0", tk.END).strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            messagebox.showinfo("提示", "已将全部日志复制到剪贴板！")

    def force_poweroff_pve(self):
        """⏻ 强制关机 PVE 宿主机: 执行 poweroff -f (跳过优雅关闭, 立即断电, 慎用)。"""
        if not self.ssh:
            self.log("[-] 错误: PVE SSH 尚未连接，无法执行命令！")
            return
        if not messagebox.askyesno("强制关机 PVE", "确认要强制关机 PVE 宿主机吗？\n\npoweroff -f 会跳过优雅关闭，立即断电。\n所有虚拟机与未保存数据都将丢失！\n物理机将直接断电，需手动开机。", parent=self.root):
            return
        self.log("[*] 已发送强制关机指令: poweroff -f ...")
        def task():
            try:
                self.run_ssh_cmd("poweroff -f", ignore_error=True)
            except Exception as e:
                self.log(f"[-] 强制关机执行异常: {e}")
        threading.Thread(target=task, daemon=True).start()

    def show_context_menu(self, event):
        row_id = self.tree_vms.identify_row(event.y)
        if row_id:
            self.tree_vms.selection_set(row_id)
            self.tree_vms.focus(row_id)
            vmid = self.tree_vms.item(row_id, "values")[0]
            self.entry_vmid.delete(0, tk.END)
            self.entry_vmid.insert(0, vmid)
        self.context_menu.post(event.x_root, event.y_root)

    def log(self, message):
        def append():
            self.log_text.config(state='normal')
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')
        self.root.after(0, append)

    def run_ssh_cmd(self, cmd, ignore_error=False):
        self.log(f"> {cmd}")
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='ignore').strip()
        err = stderr.read().decode('utf-8', errors='ignore').strip()
        if out: self.log(f"[输出] {out}")
        if err: self.log(f"[提示] {err}")
        if exit_code != 0 and not ignore_error:
            raise Exception(f"命令执行失败 (状态码 {exit_code}): {err}")
        return out + "\n" + err

    def start_connect_thread(self):
        self.btn_connect.config(state="disabled", text="连接中...")
        self.lbl_conn_status.config(text="⏳ 正在建立 SSH 连接...", fg="#2563eb")
        threading.Thread(target=self.connect_task, daemon=True).start()

    def connect_task(self):
        try:
            self.log("[*] 正在建立 SSH 连接...")
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh.connect(
                hostname=self.entry_ip.get().strip(), port=int(self.entry_port.get().strip()),
                username="root", password=self.entry_pwd.get().strip(),
                timeout=10, banner_timeout=30, auth_timeout=30
            )
            self.sftp = self.ssh.open_sftp()
            
            node_out = self.run_ssh_cmd("hostname", ignore_error=True).strip().split('\n')[0]
            self.pve_node = node_out if node_out else "pve"
            
            self.log(f"[+] 连接 PVE 成功！(节点名称: {self.pve_node})")
            self.root.after(0, lambda: self.lbl_conn_status.config(text=f"🟢 已连接 PVE 宿主机 (节点: {self.pve_node})", fg="#16a34a"))
            self.refresh_vms()
        except Exception as e:
            err = str(e)
            self.log(f"[-] 连接失败: {err}")
            self.ssh = None
            if "banner" in err.lower() or "timeout" in err.lower():
                self.log("[-] 提示: SSH 握手超时/无响应，请确认 IP/端口正确、网络可达、且目标已开启 SSH 服务。")
            self.root.after(0, lambda e=err: self.lbl_conn_status.config(text=f"🔴 连接失败: {e[:30]}", fg="#dc2626"))
        finally:
            self.root.after(0, lambda: self.btn_connect.config(state="normal", text="⚡ 建立连接"))

    def refresh_vms(self, force=False):
        """刷新虚拟机列表 (force=True 时穿透旧缓存，强制重新解析 IP 与系统指纹)"""
        if not self.ssh: return
        def task():
            try:
                if force:
                    self.log("[*] 正在重新扫描并深度解析各虚拟机 IP 与系统版本...")
                out = self.run_ssh_cmd("qm list", ignore_error=True)
                rows = []
                for line in out.strip().split('\n')[1:]:
                    parts = line.split()
                    if len(parts) >= 3 and parts[0].isdigit():
                        vmid, name, status = parts[0], parts[1], parts[2]
                        mem = parts[3] if len(parts) > 3 else ""
                        pid = parts[5] if len(parts) > 5 and parts[5] != "0" else "-"
                        rows.append((vmid, name, status, mem, pid))

                self.root.after(0, lambda rows=rows: self._populate_vm_rows(rows))

                running = [r for r in rows if r[2] == "running"]
                if running:
                    vmids = [r[0] for r in running]
                    ips = self.discover_vm_ips(vmids, force=force)
                    for vmid, ip in ips.items():
                        self.vm_ip_info[str(vmid)] = ip
                        self.root.after(0, lambda v=vmid, ip=ip: self._update_row(v, ip=ip))

                    for r in running:
                        vmid = str(r[0])
                        ip = ips.get(vmid) or self.vm_ip_info.get(vmid)
                        cur_os = self.vm_os_info.get(vmid, "")
                        # 触发重新探测: force=True、无OS信息、或包含旧缓存(Buildroot/未知/无超链接)
                        if ip and (force or not cur_os or "buildroot" in cur_os.lower() or "未知" in cur_os or "🔗" not in cur_os):
                            threading.Thread(target=self._probe_os, args=(vmid, ip), daemon=True).start()
            except Exception as e:
                self.log(f"[-] 刷新列表失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def discover_vm_ips(self, vmids, force=False):
        """四级梯队 IP 发现引擎 (支持 force 穿透刷新)"""
        try:
            result = {}
            unresolved = []

            # 非强制刷新时优先读缓存
            if not force:
                for vmid in vmids:
                    v_str = str(vmid)
                    c_info = pve_net_config.ConfigManager.get_vm_info(v_str)
                    cached_ip = c_info.get("ip")
                    cached_os = c_info.get("os", "")
                    if cached_ip:
                        result[v_str] = cached_ip
                        if cached_os and "buildroot" not in cached_os.lower():
                            self.vm_os_info[v_str] = cached_os
                            self.root.after(0, lambda v=v_str, t=cached_os: self._update_row(v, os=t))

            vm_macs = {}
            for vmid in vmids:
                v_str = str(vmid)
                cfg = self.run_ssh_cmd(f"qm config {v_str}", ignore_error=True)
                found = re.findall(r"net\d+:\s*[^\n]*?([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", cfg)
                if found:
                    vm_macs[v_str] = [m.lower() for m in found]

            # 1. QGA 直查
            for vmid in vmids:
                v_str = str(vmid)
                if v_str in result and not force: continue
                try:
                    qga_out = self.run_ssh_cmd(f"qm guest cmd {v_str} network-get-interfaces", ignore_error=True)
                    if qga_out and "error" not in qga_out.lower():
                        ips = re.findall(r'"ip-address":\s*"([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)"', qga_out)
                        valid_ips = [ip for ip in ips if ip != "127.0.0.1" and not ip.startswith("169.254.")]
                        if valid_ips:
                            result[v_str] = valid_ips[0]
                            pve_net_config.ConfigManager.save_vm_info(v_str, ip=valid_ips[0], macs=vm_macs.get(v_str))
                            continue
                except Exception: pass
                unresolved.append(v_str)

            # 2. 宿主机 ip neigh 表提取
            if unresolved:
                neigh = self.run_ssh_cmd("ip -4 neigh show", ignore_error=True)
                mac_ip = {}
                for line in neigh.splitlines():
                    parts = line.split()
                    if len(parts) >= 5 and parts[1] == "dev" and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0]):
                        mac_ip[parts[4].lower()] = parts[0]

                for vmid in list(unresolved):
                    for mac in vm_macs.get(vmid, []):
                        if mac in mac_ip:
                            ip_found = mac_ip[mac]
                            result[vmid] = ip_found
                            pve_net_config.ConfigManager.save_vm_info(vmid, ip=ip_found, macs=vm_macs.get(vmid))
                            unresolved.remove(vmid)
                            break

            # 3. Batocera 专属 50 线程局域网指纹探针
            if unresolved or force:
                pve_ip = self.entry_ip.get().strip()
                if pve_ip:
                    sub = ".".join(pve_ip.split(".")[:3])
                    from concurrent.futures import ThreadPoolExecutor

                    def scan_bato_target(i):
                        target_ip = f"{sub}.{i}"
                        if target_ip == pve_ip: return
                        try:
                            import socket as _sock
                            with _sock.create_connection((target_ip, 22), timeout=0.25):
                                ssh_t = paramiko.SSHClient()
                                ssh_t.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                                ssh_t.connect(hostname=target_ip, port=22, username="root", password="linux", timeout=2, banner_timeout=4, auth_timeout=4)
                                _, o, _ = ssh_t.exec_command(
                                    "echo '==MAC=='; cat /sys/class/net/*/address 2>/dev/null; "
                                    "echo '==BV=='; (cat /usr/share/batocera/BATOCERA 2>/dev/null || cat /etc/batocera.version 2>/dev/null || batocera-version 2>/dev/null | head -1 || cat /recalbox/recalbox.version 2>/dev/null || grep -i -oP 'batocera[^\n]+' /etc/issue 2>/dev/null); "
                                    "echo '==PLUS=='; ([ -f /userdata/system/batocera.plus ] || grep -qi 'plus' /etc/issue 2>/dev/null && echo 'PLUS'); "
                                    "echo '==KR=='; uname -r; "
                                    "echo '==OS=='; (. /etc/os-release 2>/dev/null; echo $PRETTY_NAME)", timeout=4)
                                info_out = o.read().decode("utf-8", "ignore")
                                ssh_t.close()

                                host_macs, bver, is_plus, kr, os_name = [], "", False, "", ""
                                sec = None
                                for line in info_out.splitlines():
                                    if line in ("==MAC==", "==BV==", "==PLUS==", "==KR==", "==OS=="):
                                        sec = line[2:-2]
                                    elif sec == "MAC" and re.match(r"^[0-9a-fA-F:]{17}$", line.strip()):
                                        host_macs.append(line.strip().lower())
                                    elif sec == "BV" and line.strip(): bver = line.strip().split()[0]
                                    elif sec == "PLUS" and "PLUS" in line: is_plus = True
                                    elif sec == "KR" and line.strip(): kr = line.strip()
                                    elif sec == "OS" and line.strip(): os_name = line.strip()

                                for vmid in vmids:
                                    v_str = str(vmid)
                                    for vmac in vm_macs.get(v_str, []):
                                        if vmac in host_macs:
                                            result[v_str] = target_ip
                                            if is_plus:
                                                os_txt = f"🔗 Batocera.PLUS / {kr}" if kr else "🔗 Batocera.PLUS"
                                            elif bver and bver != "?":
                                                os_txt = f"🔗 Batocera {bver} / {kr}" if kr else f"🔗 Batocera {bver}"
                                            elif "batocera" in os_name.lower() or "buildroot" in os_name.lower():
                                                os_txt = f"🔗 Batocera / {kr}" if kr else "🔗 Batocera"
                                            else:
                                                os_txt = f"{os_name} / {kr}" if os_name else f"Linux {kr}"

                                            self.vm_os_info[v_str] = os_txt
                                            pve_net_config.ConfigManager.save_vm_info(v_str, ip=target_ip, macs=host_macs, os_info=os_txt)
                                            self.root.after(0, lambda v=v_str, ip=target_ip, t=os_txt: self._update_row(v, ip=ip, os=t))
                                            break
                        except Exception: pass

                    with ThreadPoolExecutor(max_workers=50) as ex:
                        for i in range(1, 255):
                            ex.submit(scan_bato_target, i)

            return result
        except Exception as e:
            self.log(f"[-] 探测引擎异常: {e}")
            return {}

    def _probe_os(self, vmid, ip):
        """智能系统与版本识别 (优先纠偏 Batocera 版本)"""
        try:
            # 1. QGA 原生读取操作系统信息 (Windows/DSM 免密直出)
            try:
                qga_os = self.run_ssh_cmd(f"qm guest cmd {vmid} get-osinfo", ignore_error=True)
                if qga_os and "error" not in qga_os.lower():
                    m_name = re.search(r'"pretty-name":\s*"([^"]+)"', qga_os)
                    m_ver = re.search(r'"version":\s*"([^"]+)"', qga_os)
                    if m_name:
                        os_disp = m_name.group(1)
                        if m_ver and m_ver.group(1) not in os_disp:
                            os_disp += f" {m_ver.group(1)}"
                        self.vm_os_info[str(vmid)] = os_disp
                        pve_net_config.ConfigManager.save_vm_info(vmid, os_info=os_disp)
                        self.root.after(0, lambda v=vmid, t=os_disp: self._update_row(v, os=t))
                        return
            except Exception: pass

            # 2. SSH 特征探测 (深度提取 /usr/share/batocera/BATOCERA 消除 Buildroot 误判)
            if ip:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(hostname=ip, port=22, username="root", password="linux", timeout=3, banner_timeout=6, auth_timeout=6)
                _, o, _ = ssh.exec_command(
                    "echo '==BV=='; (cat /usr/share/batocera/BATOCERA 2>/dev/null || cat /etc/batocera.version 2>/dev/null || batocera-version 2>/dev/null | head -1 || cat /recalbox/recalbox.version 2>/dev/null || grep -i -oP 'batocera[^\n]+' /etc/issue 2>/dev/null); "
                    "echo '==PLUS=='; ([ -f /userdata/system/batocera.plus ] || grep -qi 'plus' /etc/issue 2>/dev/null && echo 'PLUS'); "
                    "echo '==KR=='; uname -r; "
                    "echo '==OS=='; (. /etc/os-release 2>/dev/null; echo $PRETTY_NAME)", timeout=6)
                out = o.read().decode("utf-8", "ignore")
                ssh.close()

                bver, is_plus, kr, os_name = "", False, "", ""
                sec = None
                for line in out.splitlines():
                    if line in ("==BV==", "==PLUS==", "==KR==", "==OS=="): sec = line[2:-2]
                    elif sec == "BV" and line.strip(): bver = line.strip().split()[0]
                    elif sec == "PLUS" and "PLUS" in line: is_plus = True
                    elif sec == "KR" and line.strip(): kr = line.strip()
                    elif sec == "OS" and line.strip(): os_name = line.strip()

                if is_plus:
                    text = f"🔗 Batocera.PLUS / {kr}" if kr else "🔗 Batocera.PLUS"
                elif bver and bver != "?":
                    text = f"🔗 Batocera {bver} / {kr}" if kr else f"🔗 Batocera {bver}"
                elif "batocera" in os_name.lower() or "buildroot" in os_name.lower():
                    text = f"🔗 Batocera / {kr}" if kr else "🔗 Batocera"
                elif os_name:
                    text = f"{os_name} / {kr}" if kr else os_name
                elif kr:
                    text = f"Linux {kr}"
                else:
                    text = "Linux"

                self.vm_os_info[str(vmid)] = text
                pve_net_config.ConfigManager.save_vm_info(vmid, ip=ip, os_info=text)
                self.root.after(0, lambda v=vmid, t=text: self._update_row(v, os=t))
                return
        except Exception: pass

        # 3. 语义推断兜底
        row_name = ""
        for item in self.tree_vms.get_children():
            vals = self.tree_vms.item(item, "values")
            if vals and str(vals[0]) == str(vmid):
                row_name = str(vals[1]).lower()
                break

        if "bato" in row_name:
            fallback = "🔗 Batocera"
        elif "qunhui" in row_name or "dsm" in row_name or "nas" in row_name:
            fallback = "Synology DSM / Linux"
        elif "win" in row_name:
            fallback = "Windows"
        elif "openwrt" in row_name or "ikuai" in row_name or "router" in row_name:
            fallback = "路由网关系统"
        else:
            fallback = "Linux / 自定义系统"

        self.vm_os_info[str(vmid)] = fallback
        pve_net_config.ConfigManager.save_vm_info(vmid, os_info=fallback)
        self.root.after(0, lambda v=vmid, t=fallback: self._update_row(v, os=t))

    def on_vm_select(self, event):
        selected = self.tree_vms.focus()
        if not selected: return
        vmid = self.tree_vms.item(selected, "values")[0]
        self.entry_vmid.delete(0, tk.END)
        self.entry_vmid.insert(0, vmid)

    def set_vm_os_info(self, vmid, text):
        """Batocera 控制台识别后回填“系统/版本”列并持久化缓存"""
        self.vm_os_info[str(vmid)] = text
        pve_net_config.ConfigManager.save_vm_info(vmid, os_info=text)
        self._update_row(vmid, os=text)

    def _on_tree_motion(self, event):
        """鼠标悬停在 Batocera 超链接上时，自动切换为手型光标 (hand2)"""
        region = self.tree_vms.identify_region(event.x, event.y)
        col = self.tree_vms.identify_column(event.x)
        row_id = self.tree_vms.identify_row(event.y)
        if region == "cell" and col == "#7" and row_id:
            vals = self.tree_vms.item(row_id, "values")
            if vals and len(vals) > 6 and "batocera" in str(vals[6]).lower():
                self.tree_vms.config(cursor="hand2")
                return
        self.tree_vms.config(cursor="")

    def _on_tree_click(self, event):
        """单击系统版本列超链接，直接呼出 Batocera 控制中心"""
        region = self.tree_vms.identify_region(event.x, event.y)
        col = self.tree_vms.identify_column(event.x)
        row_id = self.tree_vms.identify_row(event.y)
        if region == "cell" and col == "#7" and row_id:
            vals = self.tree_vms.item(row_id, "values")
            if vals and len(vals) > 6 and "batocera" in str(vals[6]).lower():
                vmid = vals[0]
                self.entry_vmid.delete(0, tk.END)
                self.entry_vmid.insert(0, str(vmid))
                self.open_bato_console()

    def _populate_vm_rows(self, rows):
        self.tree_vms.delete(*self.tree_vms.get_children())
        for vmid, name, status, mem, pid in rows:
            ip = self.vm_ip_info.get(str(vmid), "")
            os_info = self.vm_os_info.get(str(vmid), "")
            tag = "bato_link" if "batocera" in os_info.lower() else "normal"
            self.tree_vms.insert("", "end", values=(vmid, name, ip, status, mem, pid, os_info), tags=(tag,))

    def _update_row(self, vmid, ip=None, os=None):
        for item in self.tree_vms.get_children():
            vals = list(self.tree_vms.item(item, "values"))
            if vals and str(vals[0]) == str(vmid):
                if ip is not None:
                    vals[2] = ip
                if os is not None:
                    vals[6] = os
                tag = "bato_link" if "batocera" in str(vals[6]).lower() else "normal"
                self.tree_vms.item(item, values=tuple(vals), tags=(tag,))
                break

    def get_selected_vmid(self):
        vmid = self.entry_vmid.get().strip()
        if not vmid:
            messagebox.showwarning("提示", "请先在上方列表点选一个虚拟机！")
            return None
        return vmid

    def run_vm_action(self, action):
        vmid = self.get_selected_vmid()
        if not vmid or not self.ssh: return
        graceful = action in ("shutdown", "reboot")
        def task():
            try:
                self.log(f"[*] 正在对 VM {vmid} 发送 {action} 指令...")
                # 优雅关机/重启对未响应 ACPI 的来宾(如 Batocera)会静默超时, 故缩短等待并回退硬操作
                cmd = f"qm {action} {vmid}"
                if graceful:
                    cmd += " --timeout 15"
                out = self.run_ssh_cmd(cmd, ignore_error=True)

                if graceful:
                    st = self.run_ssh_cmd(f"qm status {vmid}", ignore_error=True)
                    still_on = "status: running" in st
                    if action == "shutdown" and still_on:
                        self.log("[!] 优雅关机无响应(来宾未处理 ACPI 电源键), 回退硬断电 qm stop ...")
                        self.run_ssh_cmd(f"qm stop {vmid}", ignore_error=True)
                    elif action == "reboot" and still_on:
                        self.log("[!] 优雅重启无响应(来宾未处理 ACPI 电源键), 回退强制拔电重启 qm stop + start ...")
                        self._power_cycle(vmid)

                if "Could not init `spice' audio driver" in out or "can't lock file" in out or "QEMU exited with code 1" in out:
                    self.log("[!] ⚠️ 侦测到 QEMU 启动冲突，正在自动启动【自愈修复引擎】...")
                    self.perform_auto_heal(vmid)
                else:
                    self.log(f"[+] 指令 {action} 执行完成！")
                    time.sleep(1)
                    self.refresh_vms()
            except Exception as e:
                self.log(f"[-] 执行 {action} 失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def force_power_cycle(self):
        """右键【🔌 强制重启(拔电后重开)】。等效物理拔电: 强制断电 qm stop (本身就是硬杀) -> 等待完全停止 -> 上电 qm start。"""
        vmid = self.get_selected_vmid()
        if not vmid or not self.ssh: return
        threading.Thread(target=lambda: self._power_cycle(vmid), daemon=True).start()

    def _power_cycle(self, vmid):
        """执行一次强制断电重启 (qm stop + qm start), 等同拔电后开机。返回 True 表示已成功重新开机。
        注意: PVE 8.2 的 qm stop 不带 --forceStop(那是 qm shutdown 专属参数), 对 status/stop 加它会报
        Unknown option: forcestop。qm stop 本身就是立即强杀("akin to pulling the power plug")。"""
        try:
            self.log(f"⚡ [强制拔电重启] 正在对 VM {vmid} 执行断电开电...")
            self.run_ssh_cmd(f"qm stop {vmid}", ignore_error=True)
            import time as _t
            stopped = False
            for _ in range(30):  # 最多等 60s 完全断电
                _t.sleep(2)
                st = self.run_ssh_cmd(f"qm status {vmid}", ignore_error=True)
                if "status: stopped" in st:
                    stopped = True
                    break
            if not stopped:
                self.log("[!] 等待断电完成超时, 但继续尝试上电...")
            else:
                self.log("[✓] VM 已完全断电 (status: stopped), 准备重新上电...")
            self.run_ssh_cmd(f"qm unlock {vmid}", ignore_error=True)  # 防残留锁阻止开机
            start_out = self.run_ssh_cmd(f"qm start {vmid}", ignore_error=True)
            time.sleep(2)
            st2 = self.run_ssh_cmd(f"qm status {vmid}", ignore_error=True)
            if "status: running" in st2:
                self.log(f"[+] VM {vmid} 已重新上电成功 (拔电重启完成)！")
            else:
                self.log(f"[-] 拔电重启后状态未确认: {st2} / {start_out}")
            self.refresh_vms()
        except Exception as e:
            self.log(f"[-] 强制拔电重启失败: {e}")
        finally:
            return True

    def auto_heal_vm(self):
        vmid = self.get_selected_vmid()
        if not vmid or not self.ssh: return
        threading.Thread(target=lambda: self.perform_auto_heal(vmid, interactive=True), daemon=True).start()

    def perform_auto_heal(self, vmid, interactive=False):
        try:
            self.log(f"\n[🚑 智能自愈排障] 正在对 VM {vmid} 进行全套开机故障诊断修复...")

            # 先读取配置: 检测是否有 PCI 直通 / OVMF, 自愈不能破坏直通引导
            cfg_out = self.run_ssh_cmd(f"qm config {vmid}", ignore_error=True)
            has_hostpci = False
            cur_bios = None
            for line in cfg_out.split('\n'):
                if ':' in line:
                    k, v = line.split(':', 1)
                    k, v = k.strip(), v.strip()
                    if k.startswith("hostpci"): has_hostpci = True
                    if k == "bios": cur_bios = v

            self.log("[1/4] 清除潜在音频驱动冲突 (--delete audio0)...")
            self.run_ssh_cmd(f"qm set {vmid} --delete audio0", ignore_error=True)

            self.log("[2/4] 解除死锁状态 (qm unlock & 清理残留锁)...")
            self.run_ssh_cmd(f"qm unlock {vmid}", ignore_error=True)
            self.run_ssh_cmd(f"rm -f /var/lock/qemu-server/lock-{vmid}.conf 2>/dev/null || true", ignore_error=True)

            self.log("[3/4] 纠正引导模式 (bootdisk sata0 优先)...")
            if has_hostpci:
                # 直通 VM: 必须保持 q35+OVMF, 绝不能切 seabios (会把 UEFI 引导打坏), 也不注入 -vnc args
                self.log("[✓] 检测到 PCI 直通, 保持当前 q35/OVMF 引导, 仅锁定 sata0 启动盘。")
                self.run_ssh_cmd(f"qm set {vmid} --boot c --bootdisk sata0", ignore_error=True)
            else:
                self.run_ssh_cmd(f"qm set {vmid} --boot c --bootdisk sata0 --bios seabios --args '-vnc 0.0.0.0:{vmid}'", ignore_error=True)

            self.log("[4/4] 正在尝试重新拉起开机 (qm start)...")
            start_out = self.run_ssh_cmd(f"qm start {vmid}", ignore_error=True)
            
            self.refresh_vms()
            
            if "already running" in start_out or "exit code 0" in start_out or "status: running" in start_out or not "exit status" in start_out:
                self.log(f"[+] 🎉 虚拟机 {vmid} 故障已彻底自愈排障完毕，现已成功顺利开机！")
                if interactive:
                    self.root.after(0, lambda: messagebox.showinfo("自愈成功", f"虚拟机 {vmid} 故障已成功修复并顺利开机！\n\n已自动清除 SPICE 声卡冲突并解除死锁。"))
            else:
                self.log(f"[*] 自愈流程已执行完毕。状态详情: {start_out}")
                
        except Exception as e:
            self.log(f"[-] 自愈过程出现异常: {e}")

    def get_selected_vm_name(self):
        """从列表选中行读取虚拟机名称 (供 noVNC 链接的 vmname 参数使用)。"""
        try:
            sel = self.tree_vms.focus()
            if not sel:
                sels = self.tree_vms.selection()
                if sels:
                    sel = sels[0]
            if sel:
                vals = self.tree_vms.item(sel, "values")
                if len(vals) > 1:
                    return str(vals[1])
        except Exception:
            pass
        return ""

    def _build_novnc_url(self, vmid, vmname=""):
        """构造与 PVE Web 一致的 noVNC 直连 URL (含 vmname/resize=off/cmd=, 浏览器打开即自动进入控制台)。"""
        import urllib.parse
        host = self.entry_ip.get().strip()
        node = getattr(self, "pve_node", "pve")
        vmname_q = urllib.parse.quote(vmname) if vmname else ""
        return (f"https://{host}:8006/?console=kvm&novnc=1&vmid={vmid}"
                f"&vmname={vmname_q}&node={node}&resize=off&cmd=")

    def open_novnc_browser(self):
        vmid = self.get_selected_vmid()
        if not vmid: return
        if self.ssh:
            self.run_ssh_cmd(f"qm start {vmid}", ignore_error=True)
        novnc_url = self._build_novnc_url(vmid, self.get_selected_vm_name())
        self.log(f"[*] 正在通过默认浏览器呼出 noVNC 网页控制台: {novnc_url}")
        webbrowser.open(novnc_url)

    def destroy_selected_vm(self):
        vmid = self.get_selected_vmid()
        if not vmid or not self.ssh: return
        if not messagebox.askyesno("⚠️ 高危警告", f"确定删除虚拟机 {vmid} 吗？\n虚拟机配置将被移除，但磁盘会自动【分离保留】(转为闲置盘，数据不丢失)，可稍后在磁盘管理中重新挂载。"): return
        def task():
            try:
                self.run_ssh_cmd(f"qm stop {vmid}", ignore_error=True)
                self.run_ssh_cmd(f"qm destroy {vmid} --keep-disks")
                self.log(f"[+] 🗑 虚拟机 {vmid} 配置已删除，磁盘已自动分离保留为闲置盘 (数据不丢)！")
                self.refresh_vms()
            except Exception as e:
                self.log(f"[-] 销毁失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def open_create_vm_dialog(self):
        if self.ssh:
            pve_create_vm.CreateVmDialog(self.root, self)
        else:
            messagebox.showwarning("提示", "请先连接 PVE SSH 服务器！")

    def open_host_net_dialog(self):
        if self.ssh:
            pve_host_net.PveHostNetworkDialog(self.root, self)
        else:
            messagebox.showwarning("提示", "请先连接 PVE SSH 服务器！")

    def open_hw_config(self):
        vmid = self.get_selected_vmid()
        if vmid and self.ssh:
            pve_ui_dialogs.HardwareConfigDialog(self.root, self, vmid)

    def open_pci_dialog(self):
        vmid = self.get_selected_vmid()
        if vmid and self.ssh:
            pve_ui_dialogs.PciPassthroughDialog(self.root, self, vmid)

    def open_net_dialog(self):
        vmid = self.get_selected_vmid()
        if vmid:
            pve_bato_net.BatoceraNetworkDialog(self.root, self, vmid)

    def open_bato_console(self):
        vmid = self.get_selected_vmid()
        if vmid:
            pve_bato_console.BatoceraConsoleDialog(self.root, self, vmid)

    def find_moonlight(self):
        """在本机自动查找已安装的 Moonlight 客户端可执行文件。"""
        import shutil
        cands = []
        p = shutil.which("Moonlight.exe") or shutil.which("moonlight")
        if p:
            cands.append(p)
        for base in (r"C:\Program Files\Moonlight", r"C:\Program Files (x86)\Moonlight"):
            c = os.path.join(base, "Moonlight.exe")
            if os.path.exists(c):
                cands.append(c)
        ad = os.environ.get("LOCALAPPDATA")
        if ad:
            c = os.path.join(ad, "Moonlight", "Moonlight.exe")
            if os.path.exists(c):
                cands.append(c)
        return cands[0] if cands else None

    def open_moonlight_stream(self):
        vmid = self.get_selected_vmid()
        if not vmid or not self.ssh:
            return
        self.log(f"[*] 正在为 VM {vmid} 定位 IP 并发起 Moonlight 串流...")
        def task():
            ip = pve_bato_net.detect_vm_ip(self, vmid)
            if not ip:
                self.root.after(0, lambda: messagebox.showwarning(
                    "无法定位 IP",
                    "无法通过 PVE ARP 表自动找到该虚拟机的 IPv4。\n请确认虚拟机已开机并已分配到 IP（可在网络配置里查看）。"))
                return
            exe = self.find_moonlight()
            if not exe:
                self.root.after(0, lambda: messagebox.showinfo(
                    "未找到 Moonlight",
                    "本机未检测到 Moonlight 客户端。\n请前往 https://moonlight-stream.org 下载安装，"
                    "或在 Microsoft Store 搜索 Moonlight 安装后重试。"))
                return
            try:
                subprocess.Popen([exe, ip])
                self.root.after(0, lambda i=ip, e=exe: self.log(f"[+] 已用 Moonlight 串流连接: {e} -> {i}"))
            except Exception as e:
                self.root.after(0, lambda err=str(e): self.log(f"[-] 启动 Moonlight 失败: {err}"))
        threading.Thread(target=task, daemon=True).start()

    def open_stream_dialog(self):
        vmid = self.get_selected_vmid()
        if vmid:
            pve_stream.SunshineInstallerDialog(self.root, self, vmid)

    def open_stream_dialog_standalone(self):
        """直连模式: 不依赖 PVE 虚拟机, 可对任意 Batocera 地址安装串流"""
        pve_stream.SunshineInstallerDialog(self.root, self, None)

    def start_vnc_with_res(self, res="1280x720"):
        """用本机 vncviewer.exe 直连 PVE 宿主机的 5900+VMID 端口 (每台虚拟机端口独立)。"""
        vmid = self.get_selected_vmid()
        if not vmid or not self.ssh: return
        ip = self.entry_ip.get().strip()
        try:
            vnc_port = 5900 + int(vmid)
        except ValueError:
            vnc_port = 5999

        def task():
            try:
                # Batocera VM 显卡防护: vmware/std/cirrus 无 DRI(无 /dev/dri/renderD128),
                # 会让 GLX 走不上渲染、RetroArch 游戏启动即 SIGSEGV(-11); 仅警告不干预。
                sel = self.tree_vms.focus()
                row_name = (self.tree_vms.item(sel, "values")[1] or "").lower() if sel else ""
                if "batocera" in row_name or "batocera" in (self.vm_os_info.get(str(vmid), "") or "").lower():
                    vga_line = self.run_ssh_cmd(f"qm config {vmid} | grep -i '^vga:'", ignore_error=True)
                    vga_val = vga_line.split(":")[-1].strip() if ":" in vga_line else ""
                    if vga_val and not vga_val.startswith("virtio"):
                        self.log(f"[!] 提示: 该 Batocera VM 的显卡为 '{vga_val}'（无 DRI），"
                                 f"进游戏可能黑屏/闪退。建议在硬件编辑里改为 'virtio'。")
                self.log(f"[*] 正在确认虚拟机 {vmid} 运行状态...")
                status = self.run_ssh_cmd(f"qm status {vmid}", ignore_error=True)
                if "status: running" not in status:
                    self.log(f"[*] 虚拟机 {vmid} 未运行，正在自动开机...")
                    self.run_ssh_cmd(f"qm start {vmid}", ignore_error=True)
                    for _ in range(40):
                        st = self.run_ssh_cmd(f"qm status {vmid}", ignore_error=True)
                        if "status: running" in st:
                            break
                        time.sleep(1)
                    else:
                        self.log("[-] 等待虚拟机开机超时，仍尝试连接 VNC...")
                    self.refresh_vms()
                else:
                    self.log(f"[*] 虚拟机 {vmid} 已在运行，直接连接 VNC。")

                self.log(f"[*] 正在等待 VNC 端口 {vnc_port} (显示 :{vmid}) 就绪...")
                import socket

                def _probe():
                    try:
                        s = socket.create_connection((ip, vnc_port), timeout=2)
                        s.close()
                        return True
                    except Exception:
                        return False

                ready = False
                for _ in range(20):
                    if _probe():
                        ready = True
                        break
                    time.sleep(1)

                if not ready:
                    # config 里 args=-vnc 0.0.0.0:VMID 但运行中的 QEMU 还是老命令行(仍挂 unix socket)
                    # 这是改配置后未重启的表现; 仅在 config 确实带 TCP VNC 时自动断电重启让参数生效。
                    cfg_vnc = self.run_ssh_cmd(f"qm config {vmid} | grep -o 'vnc 0.0.0.0:[0-9]*'", ignore_error=True)
                    expect = f"vnc 0.0.0.0:{vmid}"
                    if expect in cfg_vnc and "status: running" in self.run_ssh_cmd(f"qm status {vmid}", ignore_error=True):
                        self.log(f"[!] VNC 端口 {vnc_port} 未就绪（配置含 '{expect}' 但运行进程未生效）"
                                 f"，执行一次断电重启让参数生效...")
                        self.run_ssh_cmd(f"qm stop {vmid} --skiplock", ignore_error=True)
                        for _ in range(15):
                            time.sleep(2)
                            if "stopped" in self.run_ssh_cmd(f"qm status {vmid}", ignore_error=True):
                                break
                        self.run_ssh_cmd(f"qm start {vmid}", ignore_error=True)
                        self.refresh_vms()
                        for _ in range(30):
                            time.sleep(2)
                            if _probe():
                                ready = True
                                break
                    else:
                        self.log(f"[!] VNC 端口 {vnc_port} 未就绪，且配置中未找到 '{expect}'。请确认 VM 已配置 TCP VNC。")

                if not ready:
                    self.log(f"[-] VNC 端口 {vnc_port} 仍不可达，请确认 VM {vmid} 已配置 -vnc 0.0.0.0:{vmid} 且端口未被占用。")

                success, msg = pve_vnc.VncLauncher.launch(ip, vnc_port, res)
                if success:
                    self.log(f"[+] {msg}")
                else:
                    self.log(f"[-] {msg}")
            except Exception as e:
                self.log(f"[-] 打开 VNC 客户端异常: {e}")

        threading.Thread(target=task, daemon=True).start()

    def load_current_config(self):
        config = pve_net_config.ConfigManager.load()
        if config:
            if "ip" in config and config["ip"]:
                self.entry_ip.delete(0, tk.END); self.entry_ip.insert(0, config["ip"])
            if "port" in config and config["port"]:
                self.entry_port.delete(0, tk.END); self.entry_port.insert(0, config["port"])
            if "pwd" in config and config["pwd"]:
                self.entry_pwd.delete(0, tk.END); self.entry_pwd.insert(0, config["pwd"])
            if "vmid" in config and config["vmid"]:
                self.entry_vmid.delete(0, tk.END); self.entry_vmid.insert(0, config["vmid"])
            # 预载历史虚拟机特征指纹库
            vm_cache = config.get("vm_cache", {})
            for v, ent in vm_cache.items():
                if ent.get("ip"): self.vm_ip_info[v] = ent["ip"]
                if ent.get("os"): self.vm_os_info[v] = ent["os"]
            self.log(f"[+] 已自动加载历史配置与 {len(vm_cache)} 条虚拟机特征指纹库。")

            if config.get("ip") and config.get("pwd"):
                self.log("[*] 检测到已保存的凭据，正在全自动发起 PVE SSH 连接...")
                self.start_connect_thread()

    def save_current_config(self):
        config = {
            "ip": self.entry_ip.get().strip(),
            "port": self.entry_port.get().strip(),
            "pwd": self.entry_pwd.get().strip(),
            "vmid": self.entry_vmid.get().strip()
        }
        pve_net_config.ConfigManager.save(config)
        self.log("[+] 配置已保存！下次打开将自动连接。")

    def start_scan_pve(self):
        self.btn_scan.config(state="disabled", text="扫中...")
        self.log("[*] 正在扫描 PVE...")
        def cb(ips):
            self.root.after(0, lambda: self.btn_scan.config(state="normal", text="🔍 扫局域网"))
            if ips:
                self.entry_ip.delete(0, tk.END)
                self.entry_ip.insert(0, ips[0])
                self.log(f"[+] 发现 PVE 主机: {ips[0]}")
        threading.Thread(target=pve_net_config.PveScanner.scan_network, args=(cb,), daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    app = PveManagerApp(root)
    root.mainloop()
