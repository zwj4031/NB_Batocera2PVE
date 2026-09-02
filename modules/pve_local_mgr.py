import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import os
import posixpath
import stat
import json
import time
import re
import socket
import secrets
import http.server
import socketserver
import urllib.parse
import pve_disk_mount

class _OneFileHTTPHandler(http.server.BaseHTTPRequestHandler):
    """仅对外提供单个指定文件一次 (通过 URL 中的 token 鉴权)。"""
    def do_GET(self):
        # curl 会对非 ASCII/特殊字符做 URL 编码 (如 %E4%B8...), 需先 unquote 再白名单比对
        decoded = urllib.parse.unquote(self.path)
        if decoded != self.server.allowed:
            self.send_error(404)
            return
        try:
            filepath = self.server.filepath
            size = os.path.getsize(filepath)
            self.send_response(200)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except Exception:
            try:
                self.send_error(500)
            except Exception:
                pass

    def log_message(self, *args):
        pass

class LocalManagerTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.current_pve_path = "/var/lib/vz/template/iso"
        self.active_src_idx = 0
        self.is_task_running = False
        self.abort_requested = False

        # --- 1. 顶部公共区域: 目标虚拟机与存储池设置 (防裁剪舒展排版) ---
        f_top = tk.LabelFrame(self, text="💽 目标虚拟机与 PVE 存储池设置", padx=8, pady=4)
        f_top.pack(fill="x", side="top", padx=8, pady=2)

        # Row 0: 核心部署参数 (紧凑清晰)
        f_top_r0 = tk.Frame(f_top)
        f_top_r0.pack(fill="x", pady=1)

        tk.Label(f_top_r0, text="目标存储:").pack(side="left")
        self.combo_storage = ttk.Combobox(f_top_r0, state="readonly", width=14)
        self.combo_storage.pack(side="left", padx=2)
        self.combo_storage.set("local-lvm")
        self.combo_storage.bind("<<ComboboxSelected>>", lambda e: self.update_storage_capacity())

        tk.Label(f_top_r0, text="VMID:").pack(side="left", padx=(6, 1))
        self.entry_vmid = tk.Entry(f_top_r0, width=5, font=("Consolas", 9, "bold"))
        self.entry_vmid.insert(0, "100")
        self.entry_vmid.pack(side="left", padx=1)

        tk.Label(f_top_r0, text="VM名称:").pack(side="left", padx=(6, 1))
        self.entry_vm_name = tk.Entry(f_top_r0, width=18, font=("", 9, "bold"), fg="#0066cc")
        self.entry_vm_name.insert(0, "Batocera")
        self.entry_vm_name.pack(side="left", padx=2)

        tk.Button(f_top_r0, text="🔍 扫存储池", bg="lightblue", font=("", 8), command=self.scan_storage).pack(side="left", padx=4)
        
        self.lbl_storage_info = tk.Label(f_top_r0, text=" (请先连接SSH)", fg="gray", font=("", 8))
        self.lbl_storage_info.pack(side="left", padx=2)

        # Row 1: 自定义磁盘后缀名称与 ISO 极速挂载开关
        f_top_r1 = tk.Frame(f_top)
        f_top_r1.pack(fill="x", pady=1)

        tk.Label(f_top_r1, text="💾 磁盘后缀:").pack(side="left")
        self.entry_custom_disk_suffix = tk.Entry(f_top_r1, width=14, font=("Consolas", 9), fg="#d97706")
        self.entry_custom_disk_suffix.insert(0, "disk-0")
        self.entry_custom_disk_suffix.pack(side="left", padx=2)

        self.var_iso_cdrom = tk.IntVar(value=1)
        tk.Checkbutton(f_top_r1, text="📀 .iso 优先光驱极速挂载 (0秒免转换)", variable=self.var_iso_cdrom).pack(side="left", padx=8)

        # --- 2. 4 大彩色卡片导航栏 ---
        f_nav_bar = tk.Frame(self, padx=8, pady=2)
        f_nav_bar.pack(fill="x", side="top")

        self.tab_colors = [
            ("#0d6efd", "#e7f1ff", "#0d6efd"),
            ("#7c3aed", "#f3e8ff", "#7c3aed"),
            ("#198754", "#e8f5e9", "#198754"),
            ("#d97706", "#fef3c7", "#d97706"),
        ]

        self.tab_buttons = []
        tab_titles = [
            "📁 1. 宿主机镜像",
            "💽 2. 物理硬盘提取",
            "💻 3. 电脑本地上传",
            "💾 4. 闲置磁盘溯源",
        ]

        for i, title in enumerate(tab_titles):
            btn = tk.Button(
                f_nav_bar, text=title, padx=4, pady=3, bd=1, cursor="hand2",
                command=lambda idx=i: self.switch_src_tab(idx)
            )
            btn.pack(side="left", fill="x", expand=True, padx=2)
            self.tab_buttons.append(btn)

        # --- 3. 底部公共区域: 实时进度条与控制按钮组 ---
        f_bottom = tk.Frame(self, padx=8, pady=4)
        f_bottom.pack(fill="x", side="bottom")

        f_status_line = tk.Frame(f_bottom)
        f_status_line.pack(fill="x", pady=(0, 2))

        self.lbl_deploy_progress = tk.Label(f_status_line, text="任务状态: 就绪等待开始", fg="#0066cc", font=("", 9, "bold"))
        self.lbl_deploy_progress.pack(side="left")

        self.btn_check_active = tk.Button(f_status_line, text="🔍 检测并接管后台任务", font=("", 8), command=self.check_and_attach_active_task)
        self.btn_check_active.pack(side="right", padx=2)

        self.progress_deploy = ttk.Progressbar(f_bottom, orient="horizontal", mode="determinate")
        self.progress_deploy.pack(fill="x", pady=(0, 4))

        f_action_btns = tk.Frame(f_bottom)
        f_action_btns.pack(fill="x")

        self.btn_deploy = tk.Button(f_action_btns, text="🚀 开始一键配置并导入部署虚拟机 (支持自定义磁盘名/自动关机防冲突)", bg="#ff9900", fg="white", font=("", 10, "bold"), command=self.start_unified_deploy)
        self.btn_deploy.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_stop_task = tk.Button(f_action_btns, text="⏹️ 停止/取消任务", bg="#dc3545", fg="white", font=("", 10, "bold"), state="disabled", command=self.stop_current_task)
        self.btn_stop_task.pack(side="right", padx=(0, 0))

        # --- 4. 中部内容容器 ---
        self.f_content = tk.Frame(self, padx=8, pady=2)
        self.f_content.pack(fill="both", expand=True)

        self.tab_pve_img = tk.Frame(self.f_content)
        self._init_pve_browser_tab(self.tab_pve_img)

        self.tab_phy_disk = pve_disk_mount.PhysicalDiskMountTab(self.f_content, self.app, self)

        self.tab_local_img = tk.Frame(self.f_content)
        self._init_local_upload_tab(self.tab_local_img)

        self.tab_unused_img = tk.Frame(self.f_content)
        self._init_unused_tab(self.tab_unused_img)

        self.src_frames = [
            self.tab_pve_img,
            self.tab_phy_disk,
            self.tab_local_img,
            self.tab_unused_img
        ]

        self.switch_src_tab(0)
        self.after(200, self.sync_vmid_from_app)

    def switch_src_tab(self, idx):
        self.active_src_idx = idx
        for i, btn in enumerate(self.tab_buttons):
            act_bg, inact_bg, theme_fg = self.tab_colors[i]
            if i == idx:
                btn.config(bg=act_bg, fg="white", font=("", 9, "bold"), relief="sunken")
            else:
                btn.config(bg=inact_bg, fg=theme_fg, font=("", 9), relief="groove")

        for i, frame in enumerate(self.src_frames):
            if i == idx:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        if not self.app.ssh: return
        if idx == 0:
            self.refresh_pve_files()
        elif idx == 1:
            self.tab_phy_disk.scan_disks()
        elif idx == 3:
            self.scan_unused_disks()

    def sync_vmid_from_app(self):
        vmid = self.app.entry_vmid.get().strip()
        if vmid:
            self.entry_vmid.delete(0, tk.END)
            self.entry_vmid.insert(0, vmid)

    def set_smart_vm_name(self, filename):
        clean_name = os.path.basename(filename)
        for ext in [".img.gz", ".tar.gz", ".iso", ".img", ".qcow2", ".raw", ".gz"]:
            if clean_name.lower().endswith(ext):
                clean_name = clean_name[:-len(ext)]
                break
        clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", clean_name)
        if clean_name:
            self.entry_vm_name.delete(0, tk.END)
            self.entry_vm_name.insert(0, clean_name)
            self.entry_custom_disk_suffix.delete(0, tk.END)
            self.entry_custom_disk_suffix.insert(0, clean_name.lower()[:18])

    def update_progress_ui(self, percentage, status_text):
        def _update():
            if hasattr(self, 'progress_deploy') and hasattr(self, 'lbl_deploy_progress'):
                self.progress_deploy['value'] = percentage
                self.lbl_deploy_progress.config(text=status_text)
        self.after(0, _update)

    def _notify(self, msg, ok=True):
        """结果提示: 仅写入状态栏 + 日志, 不再弹窗。"""
        prefix = "[+] " if ok else "[-] "
        self.app.log(prefix + msg)
        if hasattr(self, 'lbl_deploy_progress'):
            self.lbl_deploy_progress.config(text=("✅ " if ok else "❌ ") + msg,
                                            fg="#198754" if ok else "#dc3545")

    def check_and_attach_active_task(self):
        if not self.app.ssh:
            self._notify("请先连接 PVE SSH！", ok=False)
            return
        if hasattr(self, 'lbl_deploy_progress'):
            self.lbl_deploy_progress.config(text="[*] 正在检索 PVE 后台是否有未完成的导入任务...")
        
        def task():
            try:
                ps_out = self.app.run_ssh_cmd("ps -ef | grep -E 'qm importdisk|qemu-img convert' | grep -v grep || true", ignore_error=True)
                if "importdisk" in ps_out or "qemu-img" in ps_out:
                    self.app.log(f"[+] 侦测到正在运行的后台导入任务: {ps_out.strip().splitlines()[0]}")
                    self.after(0, lambda: self.btn_stop_task.config(state="normal"))
                    self.after(0, lambda: self.btn_deploy.config(state="disabled"))
                    self.is_task_running = True
                    self.abort_requested = False
                    
                    vmid = self.entry_vmid.get().strip()
                    self.after(0, lambda: self._notify("已成功检测并接管后台正在运行的磁盘导入任务，正在恢复实时进度监听..."))
                    self._monitor_external_task(vmid)
                else:
                    self.after(0, lambda: hasattr(self, 'lbl_deploy_progress') and self.lbl_deploy_progress.config(text="[+] 当前没有正在运行的后台导入任务。"))
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: hasattr(self, 'lbl_deploy_progress') and self.lbl_deploy_progress.config(text=f"[-] 检测失败: {msg}"))
        threading.Thread(target=task, daemon=True).start()

    def _monitor_external_task(self, vmid):
        for _ in range(300):
            if self.abort_requested: break
            time.sleep(2)
            
            ps_check = self.app.run_ssh_cmd("ps -ef | grep -E 'qm importdisk|qemu-img convert' | grep -v grep || true", ignore_error=True)
            if not ("importdisk" in ps_check or "qemu-img" in ps_check):
                self.update_progress_ui(100, f"🎉 后台导入任务已全部完成！")
                self.app.log("[+] 🎉 后台导入任务已顺利完成！")
                self.app.refresh_vms()
                break

            task_log = self.app.run_ssh_cmd("grep -rn 'transferred' /var/log/pve/tasks/ 2>/dev/null | tail -n 1 || true", ignore_error=True)
            m = re.search(r"transferred\s+([0-9\.]+\s+[KMGTPE]?i?B)\s+of\s+([0-9\.]+\s+[KMGTPE]?i?B)\s+\(([0-9\.]+)%\)", task_log)
            if m:
                curr, total, pct_str = m.groups()
                pct = float(pct_str)
                self.update_progress_ui(pct, f"🚀 [接管中] 正在导入磁盘: {curr} / {total} ({pct:.1f}%)")

        self.after(0, lambda: self.btn_deploy.config(state="normal"))
        self.after(0, lambda: self.btn_stop_task.config(state="disabled"))
        self.is_task_running = False

    def stop_current_task(self):
        if not messagebox.askyesno("确认终止", "您确定要强制停止/取消当前正在执行的导入与部署任务吗？\n此操作将终止后台转换进程并清除锁定。"):
            return
        
        self.abort_requested = True
        if hasattr(self, 'lbl_deploy_progress'):
            self.lbl_deploy_progress.config(text="[*] 正在向 PVE 发送强制终止信号...")

        def task():
            try:
                vmid = self.entry_vmid.get().strip() or self.app.entry_vmid.get().strip()
                self.app.run_ssh_cmd("pkill -9 -f 'qm importdisk' || true; pkill -9 -f 'qemu-img convert' || true", ignore_error=True)
                if vmid:
                    self.app.run_ssh_cmd(f"qm unlock {vmid} 2>/dev/null || true", ignore_error=True)
                    self.app.run_ssh_cmd(f"rm -f /var/lock/qemu-server/lock-{vmid}.conf 2>/dev/null || true", ignore_error=True)
                
                self.app.log("[-] 🛑 导入任务已成功被用户强制终止。")
                self.update_progress_ui(0, "[-] 任务已手动终止取消。")
                self.after(0, lambda: self.btn_deploy.config(state="normal"))
                self.after(0, lambda: self.btn_stop_task.config(state="disabled"))
                self.is_task_running = False
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 终止任务异常: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    # ------------------ 子视图 1: PVE 远端文件浏览器 ------------------
    def _init_pve_browser_tab(self, parent):
        f_path = tk.Frame(parent)
        f_path.pack(fill="x", pady=2)

        self.lbl_cur_path = tk.Label(f_path, text=f"当前路径: {self.current_pve_path}", fg="#0066cc", font=("", 9, "bold"))
        self.lbl_cur_path.pack(side="left")

        tk.Button(f_path, text="🔄 刷新", command=self.refresh_pve_files).pack(side="right", padx=2)
        tk.Button(f_path, text="⬆️ 上一级", command=self.pve_go_up).pack(side="right", padx=2)

        # 快捷跳转 + 上传 (镜像库 / 模板库 均可一键上传至此)
        f_quick = tk.Frame(parent)
        f_quick.pack(fill="x", pady=1)
        tk.Button(f_quick, text="📀 ISO 镜像库", command=lambda: self.pve_jump("/var/lib/vz/template/iso")).pack(side="left", padx=2)
        tk.Button(f_quick, text="📚 CT 模板库", command=lambda: self.pve_jump("/var/lib/vz/template/cache")).pack(side="left", padx=2)
        tk.Button(f_quick, text="📤 上传文件到此处", bg="#198754", fg="white", font=("", 9, "bold"), command=self.upload_to_pve_path).pack(side="left", padx=2)

        f_tree = tk.Frame(parent)
        f_tree.pack(fill="both", expand=True, pady=2)

        self.tree_pve = ttk.Treeview(f_tree, columns=("size", "type"), show="tree headings", height=5)
        self.tree_pve.heading("#0", text="文件名 (单击自动同步名称 / 双击文件夹进入)")
        self.tree_pve.heading("size", text="文件大小")
        self.tree_pve.heading("type", text="类型")
        self.tree_pve.column("#0", width=420)
        self.tree_pve.column("size", width=90, anchor="e")
        self.tree_pve.column("type", width=80, anchor="center")

        scroll_pve = ttk.Scrollbar(f_tree, orient=tk.VERTICAL, command=self.tree_pve.yview)
        self.tree_pve.configure(yscrollcommand=scroll_pve.set)
        self.tree_pve.pack(side="left", fill="both", expand=True)
        scroll_pve.pack(side="right", fill="y")

        self.tree_pve.bind("<Double-1>", self.on_pve_file_double_click)
        self.tree_pve.bind("<<TreeviewSelect>>", self.on_pve_file_select)

        f_sel = tk.Frame(parent)
        f_sel.pack(fill="x", pady=1)
        tk.Label(f_sel, text="已选 PVE 镜像:").pack(side="left")
        self.entry_selected_pve_img = tk.Entry(f_sel, state="readonly", fg="blue")
        self.entry_selected_pve_img.pack(side="left", fill="x", expand=True, padx=4)

    def refresh_pve_files(self):
        if not self.app.sftp: return
        def task():
            try:
                files = self.app.sftp.listdir_attr(self.current_pve_path)
                folders = [f for f in files if stat.S_ISDIR(f.st_mode)]
                images = [f for f in files if not stat.S_ISDIR(f.st_mode) and f.filename.endswith(('.img', '.qcow2', '.raw', '.gz', '.iso'))]
                folders.sort(key=lambda x: x.filename.lower())
                images.sort(key=lambda x: x.filename.lower())

                def update():
                    if hasattr(self, 'lbl_cur_path'):
                        self.lbl_cur_path.config(text=f"当前路径: {self.current_pve_path}")
                    if hasattr(self, 'tree_pve'):
                        self.tree_pve.delete(*self.tree_pve.get_children())
                        if self.current_pve_path != "/":
                            self.tree_pve.insert("", "end", text="📁 .. (返回上一级)", values=("", "目录"))
                        for d in folders:
                            self.tree_pve.insert("", "end", text=f"📁 {d.filename}", values=("", "目录"))
                        for img in images:
                            size_mb = img.st_size / (1024 * 1024)
                            self.tree_pve.insert("", "end", text=f"📄 {img.filename}", values=(f"{size_mb:.1f} MB", "镜像文件"))
                self.after(0, update)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 读取 PVE 目录失败: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    def pve_go_up(self):
        if self.current_pve_path != "/":
            self.current_pve_path = posixpath.dirname(self.current_pve_path)
            self.refresh_pve_files()

    def pve_jump(self, path):
        if not self.app.sftp:
            self._notify("请先连接 PVE SSH！", ok=False)
            return
        self.current_pve_path = path
        self.refresh_pve_files()

    def upload_to_pve_path(self):
        if not self.app.sftp:
            self._notify("请先连接 PVE SSH！", ok=False)
            return
        filepath = filedialog.askopenfilename(
            title="选择要上传到 PVE 当前目录的文件",
            filetypes=[("镜像/模板文件", "*.iso *.img *.qcow2 *.raw *.gz *.tar.gz *.vma"), ("所有文件", "*.*")]
        )
        if not filepath:
            return
        filename = os.path.basename(filepath)
        remote_path = posixpath.join(self.current_pve_path, filename)
        self.update_progress_ui(0, f"[*] 正在上传 {filename} 到 {self.current_pve_path} ...")
        self.btn_deploy.config(state="disabled")
        self.btn_stop_task.config(state="normal")
        self.is_task_running = True
        self.abort_requested = False

        def task():
            try:
                def cb(transferred, total):
                    if self.abort_requested:
                        return
                    pct = int((transferred / total) * 100) if total else 0
                    self.update_progress_ui(pct, f"📤 上传 {filename}: {pct}% ({transferred/1024/1024:.1f}/{total/1024/1024:.1f}MB)")

                self.app.sftp.put(filepath, remote_path, callback=cb)
                self.app.log(f"[+] 文件已成功上传至 PVE: {remote_path}")
                self.update_progress_ui(100, f"[+] 上传完成: {filename}")
                self.after(0, self.refresh_pve_files)
                self.after(0, lambda: self._notify(f"文件已上传到 PVE: {remote_path} (ISO/模板刷新后将在库中出现)"))
            except Exception as e:
                err = str(e)
                self.app.log(f"[-] 上传失败: {err}")
                self.update_progress_ui(0, f"[-] 上传失败: {err[:40]}")
                self.after(0, lambda m=err: self._notify(f"上传失败: {m}", ok=False))
            finally:
                self.is_task_running = False
                self.after(0, lambda: self.btn_deploy.config(state="normal"))
                self.after(0, lambda: self.btn_stop_task.config(state="disabled"))
        threading.Thread(target=task, daemon=True).start()

    def on_pve_file_double_click(self, event):
        item_id = self.tree_pve.focus()
        if not item_id: return
        item_text = self.tree_pve.item(item_id, "text")
        item_type = self.tree_pve.item(item_id, "values")[1] if self.tree_pve.item(item_id, "values") else ""
        if item_type == "目录":
            if "(返回上一级)" in item_text:
                self.current_pve_path = posixpath.dirname(self.current_pve_path)
            else:
                folder_name = item_text.replace("📁 ", "").strip()
                self.current_pve_path = posixpath.join(self.current_pve_path, folder_name)
            self.refresh_pve_files()
        else:
            self.on_pve_file_select(event)

    def on_pve_file_select(self, event):
        item_id = self.tree_pve.focus()
        if not item_id: return
        vals = self.tree_pve.item(item_id, "values")
        if vals and vals[1] == "镜像文件":
            file_name = self.tree_pve.item(item_id, "text").replace("📄 ", "").strip()
            full_path = posixpath.join(self.current_pve_path, file_name)
            self.entry_selected_pve_img.config(state="normal")
            self.entry_selected_pve_img.delete(0, tk.END)
            self.entry_selected_pve_img.insert(0, full_path)
            self.entry_selected_pve_img.config(state="readonly")
            self.set_smart_vm_name(file_name)

    # ------------------ 子视图 3: 本地电脑上传 ------------------
    def _init_local_upload_tab(self, parent):
        f_local_file = tk.Frame(parent)
        f_local_file.pack(fill="x", pady=6)

        tk.Label(f_local_file, text="本地镜像文件:").pack(side="left")
        self.entry_local_file = tk.Entry(f_local_file, state="readonly", fg="blue")
        self.entry_local_file.pack(side="left", fill="x", expand=True, padx=4)
        tk.Button(f_local_file, text="📂 浏览电脑硬盘...", bg="lightblue", command=self.browse_local_file).pack(side="left")

        # 已选本地镜像清单 (清晰列出文件名/大小/状态)
        f_local_list = tk.LabelFrame(parent, text="📋 已选定待上传镜像清单", padx=6, pady=4)
        f_local_list.pack(fill="x", pady=4)

        self.lbl_local_sel = tk.Label(f_local_list, text="（尚未选择本地镜像文件）", fg="gray", anchor="w", justify="left")
        self.lbl_local_sel.pack(fill="x", pady=2)

        tk.Label(f_local_list, text="💡 提示: 上传采用『本机开 HTTP 服务 + PVE 端 curl 拉取』，比 SFTP 快数倍；上传前会校验目标存储池剩余容量。",
                 fg="#888", font=("", 8), anchor="w", justify="left").pack(fill="x", pady=(2, 0))

    def _refresh_local_sel_label(self):
        fp = self.entry_local_file.get().strip()
        if not fp:
            self.lbl_local_sel.config(text="（尚未选择本地镜像文件）", fg="gray")
            return
        try:
            sz = os.path.getsize(fp)
        except OSError:
            sz = 0
        if sz >= 1024 * 1024 * 1024:
            sz_txt = f"{sz / 1024 / 1024 / 1024:.2f} GiB"
        else:
            sz_txt = f"{sz / 1024 / 1024:.1f} MiB"
        self.lbl_local_sel.config(
            text=f"✅ 已选定部署来源:\n📄 文件: {os.path.basename(fp)}\n📏 大小: {sz_txt}\n📂 路径: {fp}",
            fg="#198754")

    def browse_local_file(self):
        filepath = filedialog.askopenfilename(
            title="选择本地 Batocera 镜像文件",
            filetypes=[("镜像文件", "*.img *.img.gz *.qcow2 *.raw *.gz"), ("所有文件", "*.*")]
        )
        if filepath:
            self.entry_local_file.config(state="normal")
            self.entry_local_file.delete(0, tk.END)
            self.entry_local_file.insert(0, filepath)
            self.entry_local_file.config(state="readonly")
            self._refresh_local_sel_label()
            self.set_smart_vm_name(filepath)

    def _local_ip_to(self, pve_ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((pve_ip, 22))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            try:
                return socket.gethostbyname(socket.gethostname())
            except Exception:
                return "127.0.0.1"

    def _http_upload(self, local_file, remote_tmp, source_name):
        """本机开临时 HTTP 服务, PVE 端 curl 拉取 (比 SFTP 快很多), 用后即关。"""
        pve_ip = self.app.entry_ip.get().strip() or "192.168.11.88"
        pc_ip = self._local_ip_to(pve_ip)
        port = 8765
        while port <= 8900:
            try:
                srv = socketserver.ThreadingTCPServer(("0.0.0.0", port), _OneFileHTTPHandler)
                break
            except OSError:
                port += 1
        else:
            raise Exception("无法在本地绑定 HTTP 端口 (8765-8900 均被占用)")

        token = secrets.token_hex(8)
        basename = os.path.basename(local_file)
        srv.filepath = local_file
        srv.allowed = f"/{token}/{basename}"
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        # 规范 URL 编码, 保证任意中文字符/空格/特殊符号在 curl 端正确请求
        quoted = urllib.parse.quote(f"/{token}/{basename}")
        url = f"http://{pc_ip}:{port}{quoted}"
        total = os.path.getsize(local_file)
        self.app.log(f"[*] 本地 HTTP 服务已启动: {url}  (PVE 将从此拉取, 传输完成后自动关闭)")

        done = threading.Event()

        def run_curl():
            try:
                self.app.run_ssh_cmd(
                    f"curl -sL -o '{remote_tmp}' '{url}' || wget -q -O '{remote_tmp}' '{url}'")
            finally:
                done.set()

        ct = threading.Thread(target=run_curl, daemon=True)
        ct.start()
        while not done.is_set():
            if self.abort_requested:
                self.app.run_ssh_cmd(f"pkill -f '{remote_tmp}' 2>/dev/null || true", ignore_error=True)
                break
            try:
                sz = int(self.app.run_ssh_cmd(f"wc -c < '{remote_tmp}' 2>/dev/null || echo 0", ignore_error=True).strip() or 0)
            except Exception:
                sz = 0
            pct = min(99, int(sz / total * 100)) if total else 0
            self.update_progress_ui(pct, f"📤 HTTP 上传 {source_name}: {pct}% ({sz/1024/1024:.0f}/{total/1024/1024:.0f}MB)")
            time.sleep(0.5)
        ct.join(timeout=5)
        srv.shutdown()
        if self.abort_requested:
            raise Exception("用户取消上传")
        final = int(self.app.run_ssh_cmd(f"wc -c < '{remote_tmp}' 2>/dev/null || echo 0", ignore_error=True).strip() or 0)
        if final != total:
            raise Exception(f"HTTP 下载大小校验失败: 本地 {total} 字节, PVE 端仅 {final} 字节")

    # ------------------ 子视图 4: 扫描 PVE 闲置磁盘 ------------------
    def _init_unused_tab(self, parent):
        f_top_un = tk.Frame(parent)
        f_top_un.pack(fill="x", pady=2)
        tk.Button(f_top_un, text="🔍 深度扫描闲置磁盘 (自动去重 + 来源智能溯源)", bg="lightblue", command=self.scan_unused_disks).pack(side="left")
        tk.Label(f_top_un, text=" (穿透底层存储池直接比对容量与任务日志)", fg="gray").pack(side="left", padx=5)

        f_tree = tk.Frame(parent)
        f_tree.pack(fill="both", expand=True, pady=2)

        self.tree_unused = ttk.Treeview(f_tree, columns=("vmid", "key", "size", "source", "volid"), show="headings", height=5)
        self.tree_unused.heading("vmid", text="所属 VMID")
        self.tree_unused.heading("key", text="闲置标签")
        self.tree_unused.heading("size", text="磁盘容量")
        self.tree_unused.heading("source", text="💡 推测/关联来源镜像")
        self.tree_unused.heading("volid", text="磁盘路径 (VolID)")

        self.tree_unused.column("vmid", width=70, anchor="center")
        self.tree_unused.column("key", width=80, anchor="center")
        self.tree_unused.column("size", width=80, anchor="e")
        self.tree_unused.column("source", width=180, anchor="w")
        self.tree_unused.column("volid", width=220, anchor="w")

        scroll_u = ttk.Scrollbar(f_tree, orient=tk.VERTICAL, command=self.tree_unused.yview)
        self.tree_unused.configure(yscrollcommand=scroll_u.set)
        self.tree_unused.pack(side="left", fill="both", expand=True)
        scroll_u.pack(side="right", fill="y")
        self.tree_unused.bind("<<TreeviewSelect>>", self.on_unused_select)
        self.tree_unused.bind("<Button-3>", self.on_unused_right_click)

    def scan_unused_disks(self):
        if not self.app.ssh: return
        def task():
            try:
                cmd = "grep -H -E '^(unused[0-9]+|#unused[0-9]+):' /etc/pve/qemu-server/*.conf /etc/pve/nodes/*/qemu-server/*.conf /etc/pve/local/qemu-server/*.conf 2>/dev/null || true"
                out = self.app.run_ssh_cmd(cmd, ignore_error=True)
                
                hist_raw = self.app.run_ssh_cmd("cat /etc/pve/nb_pve_history.json 2>/dev/null || true", ignore_error=True)
                hist_map = {}
                try:
                    if "{" in hist_raw: hist_map = json.loads(hist_raw)
                except Exception: pass

                # 动态枚举所有活动存储池, 逐个 pvesm list 收集卷容量
                # pvesm list 输出列: Volid Format Type Size VMID -> 容量在索引3
                vol_size_map = {}
                stor_raw = self.app.run_ssh_cmd("pvesm status 2>/dev/null || true", ignore_error=True)
                stor_names = []
                for line in stor_raw.strip().split('\n'):
                    parts = line.split()
                    if len(parts) >= 3 and parts[2] == "active":
                        stor_names.append(parts[0])
                if not stor_names:
                    stor_names = ["local-lvm", "local"]
                for line in out.strip().split('\n') or []:
                    mm = re.search(r"/(\d+)\.conf:(#?unused\d+):\s*(.+)", line)
                    if mm:
                        raw_volid = mm.group(3).split(',')[0].strip()
                        vol_prefix = re.sub(r"^unused\d+:", "", raw_volid)
                        if ":" in vol_prefix:
                            stor_prefix = vol_prefix.split(':')[0].strip()
                            if stor_prefix and stor_prefix not in stor_names:
                                stor_names.append(stor_prefix)
                for st in stor_names:
                    list_raw = self.app.run_ssh_cmd(f"pvesm list {st} 2>/dev/null || true", ignore_error=True)
                    for l in list_raw.split('\n'):
                        p = l.split()
                        if len(p) >= 4 and ":" in p[0] and p[3].isdigit():
                            bytes_sz = int(p[3])
                            if bytes_sz > 1024*1024*1024:
                                vol_size_map[p[0]] = f"{bytes_sz/(1024*1024*1024):.1f} GB"
                            else:
                                vol_size_map[p[0]] = f"{bytes_sz/(1024*1024):.1f} MB"

                task_log_raw = self.app.run_ssh_cmd("grep -rn 'importdisk' /var/log/pve/tasks/ 2>/dev/null | tail -n 30 || true", ignore_error=True)
                task_src_map = {}
                for l in task_log_raw.split('\n'):
                    m = re.search(r"importdisk\s+(\d+)\s+(\S+)", l)
                    if m:
                        v_id = m.group(1)
                        s_path = m.group(2).strip("'\"")
                        task_src_map[v_id] = os.path.basename(s_path)

                iso_files = self.app.run_ssh_cmd("ls -lh /var/lib/vz/template/iso/ 2>/dev/null || true", ignore_error=True)
                iso_size_map = {}
                for l in iso_files.split('\n'):
                    p = l.split()
                    if len(p) >= 9 and p[-1].endswith(('.iso', '.img', '.qcow2', '.raw', '.gz')):
                        iso_size_map[p[-1]] = p[4]

                def update():
                    if not hasattr(self, 'tree_unused'): return
                    self.tree_unused.delete(*self.tree_unused.get_children())
                    seen_volids = set()
                    count = 0

                    for line in out.strip().split('\n'):
                        if not line: continue
                        match = re.search(r"/(\d+)\.conf:(#?unused\d+):\s*(.+)", line)
                        if match:
                            vmid, key, val = match.groups()
                            key = key.replace("#", "")
                            raw_volid = val.split(',')[0].strip()
                            volid = re.sub(r"^unused\d+:", "", raw_volid)

                            if volid in seen_volids: continue
                            seen_volids.add(volid)

                            disk_size_display = vol_size_map.get(volid, "-")
                            if disk_size_display == "-":
                                size_match = re.search(r"size=([^,\s]+)", val)
                                if size_match: disk_size_display = size_match.group(1)

                            matched_src = "未知来源"
                            if volid in hist_map:
                                matched_src = f"📌 {hist_map[volid]}"
                            elif vmid in task_src_map:
                                matched_src = f"📜 任务记录: {task_src_map[vmid]}"
                            else:
                                for iso_name, iso_sz in iso_size_map.items():
                                    if disk_size_display != "-" and (disk_size_display.replace(" ","").lower() in iso_sz.lower() or iso_sz.lower() in disk_size_display.replace(" ","").lower()):
                                        matched_src = f"💡 匹配: {iso_name}"
                                        break
                                if matched_src == "未知来源" and "disk-0" in volid:
                                    matched_src = "💡 Batocera 基础盘"

                            self.tree_unused.insert("", "end", values=(vmid, key, disk_size_display, matched_src, volid))
                            count += 1

                    if count > 0:
                        self.app.log(f"[+] 闲置磁盘扫描完成，共找到 {count} 个未绑定磁盘。")
                    else:
                        self.app.log("[*] 当前 PVE 系统上未发现任何闲置未绑定的磁盘。")
                self.after(0, update)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 扫描闲置磁盘失败: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    def on_unused_select(self, event):
        selected = self.tree_unused.focus()
        if not selected: return
        vmid_src, _, _, src_info, volid = self.tree_unused.item(selected, "values")
        
        self.entry_vmid.delete(0, tk.END)
        self.entry_vmid.insert(0, vmid_src)
        self.app.entry_vmid.delete(0, tk.END)
        self.app.entry_vmid.insert(0, vmid_src)

        if "匹配:" in src_info or "📌" in src_info or "任务记录:" in src_info:
            clean_name = src_info.replace("💡 匹配:", "").replace("📌", "").replace("📜 任务记录:", "").split("(")[0].strip()
            self.set_smart_vm_name(clean_name)
        else:
            self.entry_vm_name.delete(0, tk.END)
            self.entry_vm_name.insert(0, f"Batocera-{vmid_src}")

    def on_unused_right_click(self, event):
        sel = self.tree_unused.identify_row(event.y)
        if not sel:
            return
        self.tree_unused.selection_set(sel)
        self.tree_unused.focus(sel)
        menu = tk.Menu(self.tree_unused, tearoff=0)
        menu.add_command(label="🗑 彻底删除此闲置磁盘", command=self._delete_unused_disk)
        menu.tk_popup(event.x_root, event.y_root)

    def _delete_unused_disk(self):
        if not self.app.ssh:
            return
        sel = self.tree_unused.focus()
        if not sel:
            return
        vmid, key, size, _src, volid = self.tree_unused.item(sel, "values")
        if not messagebox.askyesno("⚠️ 高危警告",
                f"确定彻底销毁并删除闲置磁盘吗？\n\n"
                f"  VMID: {vmid}\n  标签: {key}\n  容量: {size}\n  VolID: {volid}\n\n"
                f"此操作不可逆，数据将永久丢失！"):
            return

        def task():
            try:
                self.app.log(f"[*] 正在彻底销毁并删除闲置磁盘: {volid} ...")
                self.app.run_ssh_cmd(f"qm set {vmid} --delete {key}", ignore_error=True)
                if ":" in volid:
                    self.app.run_ssh_cmd(f"pvesm free '{volid}'", ignore_error=True)
                self.app.log(f"[+] 闲置磁盘 {volid} 已彻底删除。")
                self.after(0, self.scan_unused_disks)
            except Exception as e:
                self.app.log(f"[-] 删除闲置磁盘失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    # ------------------ 公共存储池扫描与一键部署逻辑 ------------------
    def scan_storage(self):
        if not self.app.ssh: return
        def task():
            try:
                out = self.app.run_ssh_cmd("pvesm status", ignore_error=True)
                storages = []
                self.storage_caps = {}
                for line in out.strip().split('\n')[1:]:
                    parts = line.split()
                    # 列: Name Type Status Total Used Available %
                    if len(parts) >= 7 and parts[2] == "active":
                        storages.append(parts[0])
                        try:
                            total_mb = float(parts[3]); used_mb = float(parts[4]); avail_mb = float(parts[5])
                        except ValueError:
                            total_mb = used_mb = avail_mb = 0
                        self.storage_caps[parts[0]] = (total_mb, used_mb, avail_mb, parts[6] if len(parts) > 6 else "?")
                def update():
                    if storages:
                        self.combo_storage['values'] = storages
                        if "local-lvm" in storages: self.combo_storage.set("local-lvm")
                        elif "local" in storages: self.combo_storage.set("local")
                        else: self.combo_storage.set(storages[0])
                        if hasattr(self, 'lbl_storage_info'):
                            self.lbl_storage_info.config(text=f"[+] 识别到 {len(storages)} 个可用存储池", fg="green")
                        self.update_storage_capacity()
                self.after(0, update)
                self.refresh_pve_files()
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 扫描存储失败: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    @staticmethod
    def _mb_to_human(mb):
        mb = float(mb)
        if mb >= 1024 * 1024:
            return f"{mb / 1024 / 1024:.1f} TiB"
        if mb >= 1024:
            return f"{mb / 1024:.1f} GiB"
        return f"{mb:.0f} MiB"

    def update_storage_capacity(self):
        if not hasattr(self, "storage_caps"):
            return
        name = self.combo_storage.get().strip()
        cap = self.storage_caps.get(name)
        if not cap or not hasattr(self, "lbl_storage_info"):
            return
        total_mb, used_mb, avail_mb, pct = cap
        self.lbl_storage_info.config(
            text=f" {name}: 共 {self._mb_to_human(total_mb)} | 已用 {self._mb_to_human(used_mb)} | 剩余 {self._mb_to_human(avail_mb)} ({pct})",
            fg="#0d6efd")
        # 同步暴露给上传前的容量校验使用
        self._current_avail_bytes = int(avail_mb * 1024 * 1024)

    def run_importdisk_with_streaming_progress(self, vmid, img_path, storage):
        cmd = f"qm importdisk {vmid} '{img_path}' {storage}"
        self.app.log(f"> {cmd}")
        stdin, stdout, stderr = self.app.ssh.exec_command(cmd)
        
        full_output = []
        for line in iter(stdout.readline, ""):
            if self.abort_requested: break
            full_output.append(line)
            self.app.log(f"[导入] {line.strip()}")
            
            m = re.search(r"transferred\s+([0-9\.]+\s+[KMGTPE]?i?B)\s+of\s+([0-9\.]+\s+[KMGTPE]?i?B)\s+\(([0-9\.]+)%\)", line)
            if m:
                curr, total, pct_str = m.groups()
                try:
                    pct = float(pct_str)
                    self.update_progress_ui(pct, f"🚀 正在导入磁盘: {curr} / {total} ({pct:.1f}%)")
                except Exception:
                    pass

        exit_code = stdout.channel.recv_exit_status()
        full_out_str = "".join(full_output)
        
        if exit_code != 0 and not self.abort_requested:
            err = stderr.read().decode('utf-8', errors='ignore')
            raise Exception(f"qm importdisk 失败 (状态码 {exit_code}): {err}")
            
        return full_out_str

    def start_unified_deploy(self):
        if not self.app.ssh:
            self._notify("请先连接 PVE SSH 服务器！", ok=False)
            return

        vmid = self.entry_vmid.get().strip() or self.app.entry_vmid.get().strip()
        vm_name = self.entry_vm_name.get().strip() or f"Batocera-{vmid}"
        custom_disk_suffix = self.entry_custom_disk_suffix.get().strip()
        storage = self.combo_storage.get().strip() or "local-lvm"
        src_tab_idx = self.active_src_idx

        if not vmid:
            self._notify("请输入目标虚拟机 ID (VMID)！", ok=False)
            return

        # 本地上传前先做存储池容量风险预判 (主线程弹窗安全)
        if src_tab_idx == 2:
            local_file = self.entry_local_file.get().strip()
            if local_file and os.path.exists(local_file):
                try:
                    local_size = os.path.getsize(local_file)
                    avail = getattr(self, "_current_avail_bytes", 0)
                    if avail and local_size * 1.2 > avail:
                        if not messagebox.askyesno("⚠️ 容量风险",
                            f"本地镜像约 {local_size/1024/1024/1024:.2f} GiB，可能超过目标存储池剩余容量 "
                            f"{avail/1024/1024/1024:.2f} GiB（镜像导入为磁盘后体积可能更大，存在写满风险）。\n仍要继续吗？"):
                            return
                except Exception:
                    pass

        self.btn_deploy.config(state="disabled")
        self.btn_stop_task.config(state="normal")
        self.is_task_running = True
        self.abort_requested = False
        self.update_progress_ui(2, f"[*] 正在准备虚拟机 {vmid} [{vm_name}] ...")

        def deploy_task():
            try:
                self.app.log(f"\n[🚀 部署任务] 目标虚拟机: {vmid} ({vm_name}) | 目标存储池: {storage}")

                # 用 qm list 精确判断 VMID 是否已存在, 绝不对已有 VMID 执行 qm create
                existing_ids = set()
                list_out = self.app.run_ssh_cmd("qm list", ignore_error=True)
                for line in list_out.strip().split('\n')[1:]:
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        existing_ids.add(int(parts[0]))

                if vmid.isdigit() and int(vmid) in existing_ids:
                    self.app.log(f"[*] VMID {vmid} 已存在，将复用该虚拟机并更新配置 (不会新建重复 VMID)")
                    vm_status = self.app.run_ssh_cmd(f"qm status {vmid}", ignore_error=True)
                    if "status: running" in vm_status:
                        self.update_progress_ui(5, "正在安全关机以避免磁盘热插拔冲突...")
                        self.app.log(f"[*] 发现虚拟机 {vmid} 处于开机状态，正在自动安全关机以避免磁盘热插拔冲突...")
                        self.app.run_ssh_cmd(f"qm stop {vmid}", ignore_error=True)
                        time.sleep(1)
                    self.update_progress_ui(8, "正在更新虚拟机引导配置...")
                    self.app.log(f"[*] 虚拟机 {vmid} 已存在，正在更新名称与引导配置为 [{vm_name}] ...")
                    self.app.run_ssh_cmd(f"qm set {vmid} --name '{vm_name}' --memory 2048 --cores 2 --cpu host --net0 virtio,bridge=vmbr0 --vga virtio --bios seabios")
                else:
                    self.update_progress_ui(8, "正在创建全新虚拟机...")
                    self.app.log(f"[*] 虚拟机 {vmid} 不存在，正在创建全新虚拟机 [{vm_name}] ...")
                    self.app.run_ssh_cmd(f"qm create {vmid} --name '{vm_name}' --memory 2048 --cores 2 --cpu host --net0 virtio,bridge=vmbr0 --vga virtio --bios seabios")

                target_volid = ""
                source_image_name = ""
                is_cdrom_mode = False

                # --- 来源 0 (PVE已有镜像) 或 来源 1 (物理硬盘挂载镜像) ---
                if src_tab_idx == 0 or src_tab_idx == 1:
                    remote_img = self.entry_selected_pve_img.get().strip()
                    if not remote_img:
                        raise Exception("请在上方列表中选择一个镜像文件！")
                    
                    source_image_name = os.path.basename(remote_img)

                    if remote_img.lower().endswith(".iso") and self.var_iso_cdrom.get() == 1:
                        is_cdrom_mode = True
                        self.update_progress_ui(60, "0秒极速 CD-ROM 光驱挂载中...")
                        self.app.log(f"[*] 检测到 .iso 光盘镜像，采用【0秒极速 CD-ROM 光驱挂载模式】...")
                        if "/var/lib/vz/template/iso/" in remote_img:
                            iso_vol = f"local:iso/{source_image_name}"
                        else:
                            iso_vol = remote_img
                        self.app.run_ssh_cmd(f"qm set {vmid} --cdrom '{iso_vol}' --boot order='ide2;sata0'")
                        target_volid = f"CD-ROM ({iso_vol})"
                    else:
                        if remote_img.endswith(".gz"):
                            self.update_progress_ui(15, "正在远程解压 .gz 压缩镜像...")
                            self.app.log(f"[*] 检测到 .gz 压缩包，正在远端解压: {remote_img} ...")
                            self.app.run_ssh_cmd(f"gunzip -f '{remote_img}'")
                            remote_img = remote_img[:-3]

                        import_out = self.run_importdisk_with_streaming_progress(vmid, remote_img, storage)
                        
                        match = re.search(r"imported disk as\s+(\S+)", import_out)
                        raw_vol = match.group(1).strip("'\"") if match else f"{storage}:vm-{vmid}-disk-0"
                        target_volid = re.sub(r"^unused\d+:", "", raw_vol)
                        if ":" not in target_volid: target_volid = f"{storage}:{target_volid}"

                # --- 来源 2: 本地电脑硬盘上传 ---
                elif src_tab_idx == 2:
                    local_file = self.entry_local_file.get().strip()
                    if not local_file or not os.path.exists(local_file):
                        raise Exception("请先选择电脑上的有效本地镜像文件！")

                    source_image_name = os.path.basename(local_file)
                    ext = ".img"
                    if local_file.lower().endswith(".gz"): ext = ".img.gz"
                    elif local_file.lower().endswith(".qcow2"): ext = ".qcow2"
                    elif local_file.lower().endswith(".raw"): ext = ".raw"
                    remote_tmp = f"/var/tmp/deploy_vm{vmid}{ext}"

                    self.app.log(f"[*] 正在上传本地文件 [{source_image_name}] 至 PVE: {remote_tmp} ...")
                    try:
                        self._http_upload(local_file, remote_tmp, source_image_name)
                        self.app.log("[+] 本地镜像上传完成 (HTTP 加速模式)！")
                    except Exception as up_e:
                        self.app.log(f"[-] HTTP 加速上传失败 ({up_e})，自动回退到 SFTP 慢速上传...")
                        def progress_cb(t, total):
                            if self.abort_requested: return
                            pct = int((t / total) * 100)
                            self.update_progress_ui(pct, f"📤 正在上传本地文件(SFTP): {pct}% ({t/1024/1024:.1f}MB / {total/1024/1024:.1f}MB)")

                        self.app.sftp.put(local_file, remote_tmp, callback=progress_cb)
                        self.app.log("[+] 本地镜像上传完成 (SFTP 回退)！")

                    if remote_tmp.endswith(".gz"):
                        self.update_progress_ui(50, "正在解压 .gz 镜像...")
                        self.app.log("[*] 正在解压 .gz 镜像...")
                        self.app.run_ssh_cmd(f"gunzip -f '{remote_tmp}'")
                        remote_tmp = remote_tmp[:-3]

                    import_out = self.run_importdisk_with_streaming_progress(vmid, remote_tmp, storage)
                    
                    match = re.search(r"imported disk as\s+(\S+)", import_out)
                    raw_vol = match.group(1).strip("'\"") if match else f"{storage}:vm-{vmid}-disk-0"
                    target_volid = re.sub(r"^unused\d+:", "", raw_vol)
                    if ":" not in target_volid: target_volid = f"{storage}:{target_volid}"

                    self.app.run_ssh_cmd(f"rm -f '{remote_tmp}'", ignore_error=True)

                # --- 来源 3: 直接挂载已有闲置磁盘 (Unused) ---
                elif src_tab_idx == 3:
                    sel = self.tree_unused.focus()
                    if not sel: raise Exception("请在闲置磁盘列表中选中一个磁盘！")
                    _, _, _, _, raw_volid = self.tree_unused.item(sel, "values")
                    target_volid = re.sub(r"^unused\d+:", "", raw_volid)

                if self.abort_requested: return

                if not is_cdrom_mode and ":" in target_volid:
                    # 注意: PVE 8.x 的 pvesm 没有 rename 子命令, 无法自定义磁盘卷名;
                    # 直接沿用 qm importdisk 实际生成的卷名 (vm-<vmid>-disk-<N>), 自定义名仅作来源记录。
                    if custom_disk_suffix:
                        self.app.log(f"[*] 本 PVE 不支持 pvesm rename, 磁盘卷名保持为 {target_volid} (自定义名 '{custom_disk_suffix}' 仅作记录)")
                    # 挂载前校验目标卷确实存在, 避免把不存在的卷名写进启动配置
                    # 注意: 卷实际所在存储以 volid 前缀为准 (如 nvme:vm-101-disk-0 -> nvme),
                    #     不能用界面 combo 选中的存储, 否则跨存储闲置盘会误报 MISSING。
                    vol_storage = target_volid.split(':')[0].strip() or storage
                    vol_exists = self.app.run_ssh_cmd(
                        f"pvesm list '{vol_storage}' 2>/dev/null | grep -qw '{target_volid.split(':')[-1]}' && echo EXISTS || echo MISSING",
                        ignore_error=True)
                    if "MISSING" in vol_exists:
                        raise Exception(f"导入后的磁盘卷 {target_volid} 不存在，无法挂载 (importdisk 可能未真正完成)")

                if source_image_name and target_volid and not is_cdrom_mode:
                    hist_save_cmd = f"python3 -c \"import json, os; p='/etc/pve/nb_pve_history.json'; d=json.load(open(p)) if os.path.exists(p) else {{}}; d['{target_volid}']='{source_image_name}'; json.dump(d, open(p,'w'))\" 2>/dev/null || true"
                    self.app.run_ssh_cmd(hist_save_cmd, ignore_error=True)

                if not is_cdrom_mode:
                    self.update_progress_ui(96, "正在挂载 SATA0 磁盘并配置第一启动项...")
                    self.app.log(f"[*] 正在挂载磁盘 {target_volid} 到 sata0 并配置启动顺序...")
                    self.app.run_ssh_cmd(f"qm set {vmid} --sata0 '{target_volid}'")
                    self.app.run_ssh_cmd(f"qm set {vmid} --boot c --bootdisk sata0")
                
                self.app.run_ssh_cmd(f"qm set {vmid} --args '-vnc 0.0.0.0:{vmid}'")

                self.update_progress_ui(100, f"🎉 虚拟机 {vmid} [{vm_name}] 部署全部就绪！")
                self.app.log(f"\n[+] 🎉 虚拟机 {vmid} [{vm_name}] 部署全部就绪！可在管理中心右键开机或直连 VNC！")
                self.after(0, lambda: self._notify(f"部署成功！VM {vmid} [{vm_name}] 挂载状态: {target_volid}"))
                self.app.refresh_vms()

            except Exception as e:
                if not self.abort_requested:
                    err_msg = str(e)
                    self.update_progress_ui(0, f"[-] 部署任务失败: {err_msg[:40]}")
                    self.app.log(f"[-] 部署任务失败: {err_msg}")
                    self.after(0, lambda msg=err_msg: self._notify(f"部署失败: {msg}", ok=False))
            finally:
                self.after(0, lambda: self.btn_deploy.config(state="normal"))
                self.after(0, lambda: self.btn_stop_task.config(state="disabled"))
                self.is_task_running = False

        threading.Thread(target=deploy_task, daemon=True).start()
