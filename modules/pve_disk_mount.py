import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import os
import posixpath
import stat
import json
import re
import time
import socket
import secrets
import http.server
import socketserver
import urllib.parse


class _OneFileHTTPHandler(http.server.BaseHTTPRequestHandler):
    """仅对外提供单个指定文件一次 (通过 URL 中的 token 鉴权), 供 PVE/盒端 curl 拉取。"""
    def do_GET(self):
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
                    chunk = f.read(1024 * 256)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except Exception:
            pass

    def log_message(self, *args):
        pass

class PhysicalDiskMountTab(ttk.Frame):
    def __init__(self, parent, app, deploy_hub):
        super().__init__(parent)
        self.app = app
        self.deploy_hub = deploy_hub
        self.current_mount_path = ""

        # --- 顶部: 物理硬盘与分区列表 (紧凑 3 行，留足空间给下方文件列表) ---
        f_top = tk.Frame(self)
        f_top.pack(fill="x", pady=(0, 2))
        
        tk.Button(f_top, text="🔍 扫描宿主机物理硬盘/分区 (lsblk)", bg="lightblue", font=("", 8), command=self.scan_disks).pack(side="left", padx=2)
        tk.Label(f_top, text="(支持 NTFS / EXT4 / exFAT / FAT32 分区一键挂载)", fg="gray", font=("", 8)).pack(side="left", padx=4)

        # 物理分区列表树 (高度设为 3，腾出纵向空间)
        f_tree = tk.Frame(self)
        f_tree.pack(fill="x", pady=1)

        self.tree_devs = ttk.Treeview(f_tree, columns=("name", "size", "fstype", "mountpoint", "label"), show="headings", height=3)
        self.tree_devs.heading("name", text="设备分区名")
        self.tree_devs.heading("size", text="容量大小")
        self.tree_devs.heading("fstype", text="文件系统")
        self.tree_devs.heading("mountpoint", text="当前挂载状态")
        self.tree_devs.heading("label", text="磁盘标签/型号")

        self.tree_devs.column("name", width=105, anchor="center")
        self.tree_devs.column("size", width=75, anchor="e")
        self.tree_devs.column("fstype", width=85, anchor="center")
        self.tree_devs.column("mountpoint", width=180, anchor="w")
        self.tree_devs.column("label", width=160, anchor="w")

        # 核心亮点：配置挂载状态高亮标签
        self.tree_devs.tag_configure("mounted", background="#e8f5e9", foreground="#1b5e20")
        self.tree_devs.tag_configure("unmounted", background="#ffffff", foreground="#333333")

        scroll_dev = ttk.Scrollbar(f_tree, orient=tk.VERTICAL, command=self.tree_devs.yview)
        self.tree_devs.configure(yscrollcommand=scroll_dev.set)
        self.tree_devs.pack(side="left", fill="x", expand=True)
        scroll_dev.pack(side="right", fill="y")
        self.tree_devs.bind("<<TreeviewSelect>>", self.on_dev_select)

        # 挂载控制栏
        f_ctrl = tk.Frame(self, pady=2)
        f_ctrl.pack(fill="x")

        self.lbl_sel_dev = tk.Label(f_ctrl, text="已选: 未选择", fg="#0066cc", font=("", 9, "bold"))
        self.lbl_sel_dev.pack(side="left", padx=2)

        self.btn_mount = tk.Button(f_ctrl, text="🔌 挂载此分区", bg="#28a745", fg="white", font=("", 9, "bold"), padx=6, command=self.mount_partition)
        self.btn_mount.pack(side="left", padx=6)

        self.btn_umount = tk.Button(f_ctrl, text="⏏️ 卸载分区", font=("", 8), command=self.umount_partition)
        self.btn_umount.pack(side="left", padx=2)

        # --- 底部: 已挂载分区内的文件树 (扩大到 5~6 行高度，确保至少看清 3~5 个文件) ---
        f_files = tk.LabelFrame(self, text="📁 已挂载分区内的镜像文件浏览 (双击或点选即可用于部署)", padx=6, pady=2)
        f_files.pack(fill="both", expand=True, pady=2)

        f_files_head = tk.Frame(f_files)
        f_files_head.pack(fill="x", pady=(0, 2))
        tk.Button(f_files_head, text="📤 上传本地文件到此处 (HTTP极速)", bg="#198754", fg="white",
                  font=("", 9, "bold"), command=self.upload_to_mount_path).pack(side="left", padx=2)
        self.lbl_upload_status = tk.Label(f_files_head, text="(需先挂载分区，将把本地文件上传到当前目录)",
                                          fg="#888", font=("", 8), anchor="w")
        self.lbl_upload_status.pack(side="left", padx=8, fill="x", expand=True)

        self.tree_mounted_files = ttk.Treeview(f_files, columns=("size", "type"), show="tree headings", height=5)
        self.tree_mounted_files.heading("#0", text="文件名 (双击进入目录/选中镜像)")
        self.tree_mounted_files.heading("size", text="大小")
        self.tree_mounted_files.heading("type", text="类型")
        self.tree_mounted_files.column("#0", width=360)
        self.tree_mounted_files.column("size", width=80, anchor="e")
        self.tree_mounted_files.column("type", width=70, anchor="center")

        scroll_f = ttk.Scrollbar(f_files, orient=tk.VERTICAL, command=self.tree_mounted_files.yview)
        self.tree_mounted_files.configure(yscrollcommand=scroll_f.set)
        self.tree_mounted_files.pack(side="left", fill="both", expand=True)
        scroll_f.pack(side="right", fill="y")
        self.tree_mounted_files.bind("<Double-1>", self.on_mounted_file_double_click)
        self.tree_mounted_files.bind("<<TreeviewSelect>>", self.on_mounted_file_select)

    def scan_disks(self):
        if not self.app.ssh: return
        def task():
            try:
                cmd = "lsblk -J -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,LABEL,MODEL 2>/dev/null"
                out = self.app.run_ssh_cmd(cmd, ignore_error=True)

                def add_block_device(dev):
                    name = dev.get("name", "")
                    dev_path = f"/dev/{name}" if not name.startswith("/dev/") else name
                    size = dev.get("size", "-")
                    fstype = dev.get("fstype") or "-"
                    raw_mp = dev.get("mountpoint")
                    label = dev.get("label") or dev.get("model") or ""
                    label = label.replace("\x20", " ").strip()

                    # 彩色高亮挂载状态判断
                    is_mounted = bool(raw_mp and raw_mp != "[未挂载]")
                    tag = "mounted" if is_mounted else "unmounted"
                    mountpoint_display = f"🟢 {raw_mp}" if is_mounted else "⚪ [未挂载]"

                    self.tree_devs.insert("", "end", values=(dev_path, size, fstype, mountpoint_display, label), tags=(tag,))

                    for child in dev.get("children", []):
                        add_block_device(child)

                def update():
                    self.tree_devs.delete(*self.tree_devs.get_children())
                    try:
                        data = json.loads(out)
                        for d in data.get("blockdevices", []):
                            add_block_device(d)
                    except Exception:
                        pass
                self.after(0, update)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 扫描物理磁盘失败: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    def on_dev_select(self, event):
        selected = self.tree_devs.focus()
        if not selected: return
        dev_name, size, fstype, mountpoint, _ = self.tree_devs.item(selected, "values")
        self.lbl_sel_dev.config(text=f"已选: {dev_name} ({size}, {fstype})")
        if "🟢" in mountpoint:
            clean_mp = mountpoint.replace("🟢", "").strip()
            self.current_mount_path = clean_mp
            self.refresh_mounted_files()

    def mount_partition(self):
        selected = self.tree_devs.focus()
        if not selected:
            messagebox.showwarning("提示", "请先在上方列表中选择一个物理分区！")
            return
        dev_name, _, fstype, mountpoint, _ = self.tree_devs.item(selected, "values")
        if "🟢" in mountpoint:
            clean_mp = mountpoint.replace("🟢", "").strip()
            self.current_mount_path = clean_mp
            self.refresh_mounted_files()
            return

        clean_dev = os.path.basename(dev_name)
        target_dir = f"/mnt/pve_mount/{clean_dev}"

        def task():
            try:
                self.app.run_ssh_cmd(f"mkdir -p '{target_dir}'")
                self.app.run_ssh_cmd(f"mount '{dev_name}' '{target_dir}' 2>/dev/null || mount -o ro '{dev_name}' '{target_dir}'")
                self.current_mount_path = target_dir
                self.app.log(f"[+] 物理分区 {dev_name} 已成功挂载至 {target_dir}！")
                self.after(0, self.scan_disks)
                self.after(0, self.refresh_mounted_files)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 挂载失败: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    def umount_partition(self):
        selected = self.tree_devs.focus()
        if not selected: return
        dev_name, _, _, mountpoint, _ = self.tree_devs.item(selected, "values")
        if "未挂载" in mountpoint: return
        clean_mp = mountpoint.replace("🟢", "").strip()

        def task():
            try:
                self.app.run_ssh_cmd(f"umount '{clean_mp}' || umount '{dev_name}'")
                self.app.log(f"[+] 分区 {dev_name} 已安全卸载。")
                self.current_mount_path = ""
                self.after(0, lambda: self.tree_mounted_files.delete(*self.tree_mounted_files.get_children()))
                self.after(0, self.scan_disks)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 卸载失败: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    def refresh_mounted_files(self):
        if not self.current_mount_path or not self.app.sftp: return
        def task():
            try:
                files = self.app.sftp.listdir_attr(self.current_mount_path)
                folders = [f for f in files if stat.S_ISDIR(f.st_mode)]
                images = [f for f in files if not stat.S_ISDIR(f.st_mode) and f.filename.endswith(('.img', '.qcow2', '.raw', '.gz', '.iso'))]
                folders.sort(key=lambda x: x.filename.lower())
                images.sort(key=lambda x: x.filename.lower())

                def update():
                    self.tree_mounted_files.delete(*self.tree_mounted_files.get_children())
                    if self.current_mount_path != "/":
                        self.tree_mounted_files.insert("", "end", text="📁 .. (返回上一级)", values=("", "目录"))
                    for d in folders:
                        self.tree_mounted_files.insert("", "end", text=f"📁 {d.filename}", values=("", "目录"))
                    for img in images:
                        size_mb = img.st_size / (1024 * 1024)
                        self.tree_mounted_files.insert("", "end", text=f"📄 {img.filename}", values=(f"{size_mb:.1f} MB", "镜像文件"))
                self.after(0, update)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 遍历挂载目录失败: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    def on_mounted_file_double_click(self, event):
        item_id = self.tree_mounted_files.focus()
        if not item_id: return
        item_text = self.tree_mounted_files.item(item_id, "text")
        vals = self.tree_mounted_files.item(item_id, "values")
        if vals and vals[1] == "目录":
            if "(返回上一级)" in item_text:
                self.current_mount_path = posixpath.dirname(self.current_mount_path)
            else:
                f_name = item_text.replace("📁 ", "").strip()
                self.current_mount_path = posixpath.join(self.current_mount_path, f_name)
            self.refresh_mounted_files()
        else:
            self.on_mounted_file_select(event)

    def on_mounted_file_select(self, event):
        item_id = self.tree_mounted_files.focus()
        if not item_id: return
        vals = self.tree_mounted_files.item(item_id, "values")
        if vals and vals[1] == "镜像文件":
            file_name = self.tree_mounted_files.item(item_id, "text").replace("📄 ", "").strip()
            full_path = posixpath.join(self.current_mount_path, file_name)
            self.deploy_hub.entry_selected_pve_img.config(state="normal")
            self.deploy_hub.entry_selected_pve_img.delete(0, tk.END)
            self.deploy_hub.entry_selected_pve_img.insert(0, full_path)
            self.deploy_hub.entry_selected_pve_img.config(state="readonly")
            self.deploy_hub.set_smart_vm_name(file_name)
            self.app.log(f"[*] 已从物理硬盘中提取镜像: {full_path}")

    # ------------------ 上传本地文件到当前挂载目录 (HTTP 极速) ------------------
    def upload_to_mount_path(self):
        if not self.app.ssh:
            messagebox.showwarning("提示", "请先连接 PVE SSH！")
            return
        if not self.current_mount_path:
            messagebox.showwarning("提示", "请先在上方挂载一个物理分区，再上传文件到该目录。")
            return
        filepath = filedialog.askopenfilename(
            title="选择要上传到当前挂载目录的本地文件",
            filetypes=[("镜像文件", "*.img *.img.gz *.qcow2 *.raw *.gz *.iso"), ("所有文件", "*.*")]
        )
        if not filepath:
            return

        def task():
            try:
                self.after(0, lambda: self.lbl_upload_status.config(
                    text=f"[*] 正在上传 {os.path.basename(filepath)} ...", fg="#0066cc"))
                self._http_upload(filepath)
                self.after(0, self.refresh_mounted_files)
                self.after(0, lambda: self.lbl_upload_status.config(
                    text=f"[+] 上传完成: {os.path.basename(filepath)} 已写入 {self.current_mount_path}", fg="#198754"))
                self.app.log(f"[+] 文件已上传至物理盘挂载目录: {self.current_mount_path}")
            except Exception as e:
                self.app.log(f"[-] 上传失败: {e}")
                self.after(0, lambda m=str(e): self.lbl_upload_status.config(text=f"[-] 上传失败: {m[:40]}", fg="#dc3545"))
        threading.Thread(target=task, daemon=True).start()

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

    def _http_upload(self, local_file):
        """本机开临时 HTTP 服务, PVE 端 curl 拉取到当前挂载目录, 用后即关。"""
        pve_ip = self.app.entry_ip.get().strip() or "192.168.11.2"
        pc_ip = self._local_ip_to(pve_ip)
        port = 8865
        while port <= 9000:
            try:
                srv = socketserver.ThreadingTCPServer(("0.0.0.0", port), _OneFileHTTPHandler)
                break
            except OSError:
                port += 1
        else:
            raise Exception("无法在本地绑定 HTTP 端口 (8865-9000 均被占用)")

        token = secrets.token_hex(8)
        basename = os.path.basename(local_file)
        srv.filepath = local_file
        srv.allowed = f"/{token}/{basename}"
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        quoted = urllib.parse.quote(f"/{token}/{basename}")
        url = f"http://{pc_ip}:{port}{quoted}"
        total = os.path.getsize(local_file)
        self.app.log(f"[*] 本地 HTTP 服务已启动: {url} (PVE 将从此处拉取)")

        remote_tmp = posixpath.join(self.current_mount_path, basename)
        done = threading.Event()

        def run_curl():
            try:
                self.app.run_ssh_cmd(f"curl -sL -o '{remote_tmp}' '{url}' || wget -q -O '{remote_tmp}' '{url}'")
            finally:
                done.set()

        ct = threading.Thread(target=run_curl, daemon=True)
        ct.start()
        while not done.is_set():
            try:
                sz = int(self.app.run_ssh_cmd(f"wc -c < '{remote_tmp}' 2>/dev/null || echo 0", ignore_error=True).strip() or 0)
            except Exception:
                sz = 0
            pct = min(99, int(sz / total * 100)) if total else 0
            self.after(0, lambda p=pct, s=sz: self.lbl_upload_status.config(
                text=f"📤 HTTP 上传 {basename}: {p}% ({s/1024/1024:.0f}/{total/1024/1024:.0f}MB)", fg="#0066cc"))
            time.sleep(0.5)
        ct.join(timeout=5)
        srv.shutdown()
        final = int(self.app.run_ssh_cmd(f"wc -c < '{remote_tmp}' 2>/dev/null || echo 0", ignore_error=True).strip() or 0)
        if final != total:
            raise Exception(f"HTTP 下载大小校验失败: 本地 {total} 字节, PVE 端仅 {final} 字节")
