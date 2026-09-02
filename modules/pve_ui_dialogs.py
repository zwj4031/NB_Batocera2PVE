import tkinter as tk
from tkinter import ttk, messagebox
import threading
import posixpath
import stat
import os
import re
from pve_machine import normalize_pve_machine

# PVE 合法 vga 枚举 (来自 /usr/share/perl5/PVE/QemuServer.pm vga enum)
_G_VGA_CHOICES = ("cirrus", "qxl", "qxl2", "qxl3", "qxl4", "none", "serial0",
                  "serial1", "serial2", "serial3", "std", "virtio", "virtio-gl", "vmware")

class RemoteFilePickerDialog(tk.Toplevel):
    """PVE 宿主机与物理挂载盘文件选择器"""
    def __init__(self, parent, app, callback, initial_dir="/var/lib/vz/template/iso"):
        super().__init__(parent)
        self.app = app
        self.callback = callback
        self.current_path = initial_dir if os.path.exists(initial_dir) else "/var/lib/vz/template/iso"
        self.title("📁 选择 PVE 宿主机或物理挂载盘上的镜像文件")
        self.geometry("520x420")
        self.transient(parent)
        self.grab_set()

        frame = tk.Frame(self, padx=10, pady=10)
        frame.pack(fill="both", expand=True)

        f_path = tk.Frame(frame)
        f_path.pack(fill="x", pady=2)
        self.lbl_path = tk.Label(f_path, text=f"路径: {self.current_path}", fg="#0066cc", font=("", 9, "bold"))
        self.lbl_path.pack(side="left")

        tk.Button(f_path, text="🔄 刷新", command=self.refresh_list).pack(side="right", padx=2)
        tk.Button(f_path, text="⬆️ 上一级", command=self.go_up).pack(side="right", padx=2)

        # 快捷目录跳转
        f_quick = tk.Frame(frame)
        f_quick.pack(fill="x", pady=2)
        tk.Label(f_quick, text="快捷直达:").pack(side="left")
        tk.Button(f_quick, text="ISO模板库", command=lambda: self.jump_to("/var/lib/vz/template/iso")).pack(side="left", padx=2)
        tk.Button(f_quick, text="物理挂载盘 (/mnt/pve_mount)", command=lambda: self.jump_to("/mnt/pve_mount")).pack(side="left", padx=2)
        tk.Button(f_quick, text="根目录 (/)", command=lambda: self.jump_to("/")).pack(side="left", padx=2)

        f_tree = tk.Frame(frame)
        f_tree.pack(fill="both", expand=True, pady=4)

        self.tree = ttk.Treeview(f_tree, columns=("size", "type"), show="tree headings")
        self.tree.heading("#0", text="文件名 (双击进入目录 / 选中镜像)")
        self.tree.heading("size", text="大小")
        self.tree.heading("type", text="类型")
        self.tree.column("#0", width=340)
        self.tree.column("size", width=80, anchor="e")
        self.tree.column("type", width=70, anchor="center")

        scroll = ttk.Scrollbar(f_tree, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.tree.bind("<Double-1>", self.on_double_click)

        f_btn = tk.Frame(frame)
        f_btn.pack(fill="x", pady=(4, 0))
        tk.Button(f_btn, text="✅ 确认选择此镜像", bg="#28a745", fg="white", font=("", 9, "bold"), command=self.confirm_selection).pack(side="right", padx=2)
        tk.Button(f_btn, text="取消", command=self.destroy).pack(side="right", padx=2)

        self.after(100, self.refresh_list)

    def jump_to(self, target_dir):
        self.current_path = target_dir
        self.refresh_list()

    def go_up(self):
        if self.current_path != "/":
            self.current_path = posixpath.dirname(self.current_path)
            self.refresh_list()

    def refresh_list(self):
        if not self.app.sftp: return
        def task():
            try:
                files = self.app.sftp.listdir_attr(self.current_path)
                folders = [f for f in files if stat.S_ISDIR(f.st_mode)]
                images = [f for f in files if not stat.S_ISDIR(f.st_mode) and f.filename.endswith(('.img', '.qcow2', '.raw', '.gz', '.iso', '.vmdk'))]
                folders.sort(key=lambda x: x.filename.lower())
                images.sort(key=lambda x: x.filename.lower())

                def update():
                    self.lbl_path.config(text=f"路径: {self.current_path}")
                    self.tree.delete(*self.tree.get_children())
                    if self.current_path != "/":
                        self.tree.insert("", "end", text="📁 .. (返回上一级)", values=("", "目录"))
                    for d in folders:
                        self.tree.insert("", "end", text=f"📁 {d.filename}", values=("", "目录"))
                    for img in images:
                        sz_mb = img.st_size / (1024 * 1024)
                        self.tree.insert("", "end", text=f"📄 {img.filename}", values=(f"{sz_mb:.1f} MB", "镜像文件"))
                self.after(0, update)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: messagebox.showerror("错误", f"无法读取目录: {msg}"))
        threading.Thread(target=task, daemon=True).start()

    def on_double_click(self, event):
        item_id = self.tree.focus()
        if not item_id: return
        text = self.tree.item(item_id, "text")
        vals = self.tree.item(item_id, "values")
        if vals and vals[1] == "目录":
            if "(返回上一级)" in text:
                self.current_path = posixpath.dirname(self.current_path)
            else:
                folder_name = text.replace("📁 ", "").strip()
                self.current_path = posixpath.join(self.current_path, folder_name)
            self.refresh_list()
        else:
            self.confirm_selection()

    def confirm_selection(self):
        item_id = self.tree.focus()
        if not item_id: return
        vals = self.tree.item(item_id, "values")
        if vals and vals[1] == "镜像文件":
            file_name = self.tree.item(item_id, "text").replace("📄 ", "").strip()
            full_path = posixpath.join(self.current_path, file_name)
            self.callback(full_path)
            self.destroy()

class HardwareConfigDialog(tk.Toplevel):
    def __init__(self, parent, app, vmid):
        super().__init__(parent)
        self.app = app
        self.vmid = vmid
        self.title(f"🛠️ 编辑虚拟机 {vmid} (全量配置/磁盘管理/引导修复/Batocera调优)")
        self.geometry("840x580")
        self.minsize(800, 540)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        frame = tk.Frame(self, padx=12, pady=10)
        frame.pack(fill="both", expand=True)

        f_bottom = tk.Frame(frame)
        f_bottom.pack(side="bottom", fill="x")
        f_main = tk.Frame(frame)
        f_main.pack(side="top", fill="both", expand=True)

        tk.Label(f_main, text=f"🖥️ 虚拟机 {vmid} 编辑与调优控制台", font=("", 11, "bold"), fg="#1e90ff").pack(anchor="w", pady=(0, 6))

        nb = ttk.Notebook(f_main)
        nb.pack(fill="both", expand=True, pady=4)

        # Tab 1: 基础系统与引导修复
        tab_sys = ttk.Frame(nb, padding=10)
        nb.add(tab_sys, text="⚙️ 系统与引导")

        tk.Label(tab_sys, text="虚拟机名称:").grid(row=0, column=0, sticky="e", pady=4)
        self.entry_name = tk.Entry(tab_sys, width=18)
        self.entry_name.grid(row=0, column=1, sticky="w", padx=5)

        tk.Label(tab_sys, text="操作系统类型:").grid(row=0, column=2, sticky="e", pady=4)
        self.combo_ostype = ttk.Combobox(tab_sys, values=["l26", "win11", "win10", "other"], width=10, state="readonly")
        self.combo_ostype.set("l26")
        self.combo_ostype.grid(row=0, column=3, sticky="w", padx=5)

        tk.Label(tab_sys, text="BIOS 引导模式:").grid(row=1, column=0, sticky="e", pady=4)
        self.combo_bios = ttk.Combobox(tab_sys, values=["ovmf", "seabios"], width=16, state="readonly")
        self.combo_bios.set("seabios")
        self.combo_bios.grid(row=1, column=1, sticky="w", padx=5)
        # 标记是否已成功读取过线上 config (未读取时 combo_bios 默认 seabios, 防止误把 OVMF 盒保存成 seabios / 反过来乱建 efidisk)
        self._config_loaded = False

        tk.Label(tab_sys, text="主板机型架构:").grid(row=1, column=2, sticky="e", pady=4)
        self.combo_machine = ttk.Combobox(tab_sys, values=["i440fx", "q35"], width=10, state="readonly")
        self.combo_machine.set("i440fx")
        self.combo_machine.grid(row=1, column=3, sticky="w", padx=5)
        self.lbl_machine_warn = tk.Label(tab_sys, text="", fg="#b8860b", font=("Microsoft YaHei UI", 9), wraplength=240, justify="left")
        self.lbl_machine_warn.grid(row=1, column=4, sticky="w", padx=5)
        self.combo_machine.bind("<<ComboboxSelected>>", lambda e: self._update_machine_warn())
        self._update_machine_warn()

        self.var_onboot = tk.IntVar(value=0)
        tk.Checkbutton(tab_sys, text="🔌 随宿主机开机自启", variable=self.var_onboot).grid(row=2, column=0, columnspan=2, sticky="w", pady=4)

        self.var_agent = tk.IntVar(value=1)
        tk.Checkbutton(tab_sys, text="🤖 启用 Guest Agent 代理", variable=self.var_agent).grid(row=2, column=2, columnspan=2, sticky="w", pady=4)

        self.var_tablet = tk.IntVar(value=0)
        tk.Checkbutton(tab_sys, text="🖱️ USB 平板指针 (Batocera建议关闭防摇杆漂移)", variable=self.var_tablet).grid(row=3, column=0, columnspan=4, sticky="w", pady=4)

        f_boot = tk.LabelFrame(tab_sys, text="🔧 启动引导诊断与修复专区", padx=8, pady=6)
        f_boot.grid(row=4, column=0, columnspan=4, sticky="we", pady=(10, 0))

        tk.Label(f_boot, text="第一引导盘设置:").pack(side="left")
        self.combo_boot = ttk.Combobox(f_boot, values=["sata0", "scsi0", "virtio0", "ide2 (光驱)", "net0 (网络PXE)"], width=14, state="readonly")
        self.combo_boot.set("sata0")
        self.combo_boot.pack(side="left", padx=4)

        tk.Button(f_boot, text="⚡ 修复引导=sata0", bg="#ffc107", font=("", 9, "bold"), command=self.quick_fix_boot).pack(side="left", padx=6)

        # Tab 2: 💾 磁盘管理与镜像直接导入 (重磅新增功能)
        tab_disk = ttk.Frame(nb, padding=8)
        nb.add(tab_disk, text="💾 磁盘管理与镜像")
        self._init_disk_mgmt_tab(tab_disk)

        # Tab 3: CPU 与 内存
        tab_cpu = ttk.Frame(nb, padding=10)
        nb.add(tab_cpu, text="⚡ CPU与内存")

        tk.Label(tab_cpu, text="CPU 插槽数 (Sockets):").grid(row=0, column=0, sticky="e", pady=4)
        self.entry_sockets = tk.Entry(tab_cpu, width=12)
        self.entry_sockets.insert(0, "1")
        self.entry_sockets.grid(row=0, column=1, sticky="w", padx=5)

        tk.Label(tab_cpu, text="CPU 核心数 (Cores):").grid(row=0, column=2, sticky="e", pady=4)
        self.entry_cores = tk.Entry(tab_cpu, width=12)
        self.entry_cores.insert(0, "2")
        self.entry_cores.grid(row=0, column=3, sticky="w", padx=5)

        tk.Label(tab_cpu, text="CPU 架构类型:").grid(row=1, column=0, sticky="e", pady=4)
        self.combo_cpu = ttk.Combobox(tab_cpu, values=["host", "kvm64", "qemu64", "max", "x86-64-v2-AES", "EPYC"], width=14, state="readonly")
        self.combo_cpu.set("host")
        self.combo_cpu.grid(row=1, column=1, sticky="w", padx=5)

        self.var_numa = tk.IntVar(value=0)
        tk.Checkbutton(tab_cpu, text="启用 NUMA 硬件加速", variable=self.var_numa).grid(row=1, column=2, columnspan=2, sticky="w", padx=5)

        tk.Label(tab_cpu, text="内存大小 (RAM MB):").grid(row=2, column=0, sticky="e", pady=6)
        self.entry_mem = tk.Entry(tab_cpu, width=12)
        self.entry_mem.insert(0, "2048")
        self.entry_mem.grid(row=2, column=1, sticky="w", padx=5)

        tk.Label(tab_cpu, text="气球内存 (Balloon MB):").grid(row=2, column=2, sticky="e", pady=6)
        self.entry_balloon = tk.Entry(tab_cpu, width=12)
        self.entry_balloon.insert(0, "0")
        self.entry_balloon.grid(row=2, column=3, sticky="w", padx=5)

        # Tab 4: 显卡与外设控制器
        tab_vga = ttk.Frame(nb, padding=10)
        nb.add(tab_vga, text="🖥️ 显卡与外设")

        tk.Label(tab_vga, text="显卡类型 (Display/VGA):").grid(row=0, column=0, sticky="e", pady=6)
        _VGA_CHOICES = [
            "std (标准兼容VGA)",
            "vmware (VMware兼容)",
            "cirrus (Cirrus兼容旧驱动)",
            "qxl (Spice 高性能显卡)",
            "qxl2 (多屏 qxl2)",
            "qxl3 (多屏 qxl3)",
            "qxl4 (多屏 qxl4)",
            "virtio (VirtIO加速)",
            "virtio-gl (VirGL 3D加速)",
            "serial0 (串口终端)",
            "serial1 (串口终端2)",
            "serial2 (串口终端3)",
            "serial3 (串口终端4)",
            "none (无显卡 - 硬件直通必选)"
        ]
        self.combo_vga = ttk.Combobox(tab_vga, values=_VGA_CHOICES, width=28)
        self.combo_vga.set("std (标准兼容VGA)")
        self.combo_vga.grid(row=0, column=1, sticky="w", padx=5)

        tk.Label(tab_vga, text="PCI 硬件直通 (hostpci):").grid(row=2, column=0, sticky="e", pady=6)
        f_hp = tk.Frame(tab_vga)
        f_hp.grid(row=2, column=1, sticky="w", padx=5)
        self.entry_hostpci = tk.Entry(f_hp, width=30)
        self.entry_hostpci.pack(side="left")
        btn_sel_hp = tk.Button(f_hp, text="🧭 直通选择器…", bg="#e6f3ff", fg="#0b60a4",
                               command=lambda: PciPassthroughDialog(self, self.app, self.vmid,
                                                                    fill_target=self.entry_hostpci,
                                                                    fill_vga=self.combo_vga,
                                                                    fill_audio=self.combo_audio))
        btn_sel_hp.pack(side="left", padx=4)
        tk.Label(tab_vga, text="(留空=不使用直通; 点【直通选择器】扫描后自动填, 多槽用分号分隔)", fg="gray", font=("", 8)).grid(row=3, column=1, sticky="w", padx=5)

        tk.Label(tab_vga, text="SCSI 控制器类型:").grid(row=4, column=0, sticky="e", pady=6)
        self.combo_scsi = ttk.Combobox(tab_vga, values=["virtio-scsi-single", "virtio-scsi-pci", "lsi", "megaraid"], width=28, state="readonly")
        self.combo_scsi.set("virtio-scsi-single")
        self.combo_scsi.grid(row=4, column=1, sticky="w", padx=5)

        tk.Label(tab_vga, text="虚拟声卡设备 (Audio):").grid(row=5, column=0, sticky="e", pady=6)
        self.combo_audio = ttk.Combobox(tab_vga, values=["none (关闭, 最稳)", "ich9-intel-hda", "intel-hda", "AC97"], width=28, state="readonly")
        self.combo_audio.set("none (关闭, 最稳)")
        self.combo_audio.grid(row=5, column=1, sticky="w", padx=5)

        # Tab 5: 🎮 Batocera 专属兼容性一键调优
        tab_bato = ttk.Frame(nb, padding=10)
        nb.add(tab_bato, text="🎮 Batocera调优")

        # 让每个选项卡标签左右留足内边距，避免 emoji + 中文被截断
        for _t in nb.tabs():
            nb.tab(_t, padding=(8, 4))

        tk.Label(tab_bato, text="🚀 Batocera 游戏机专属全套兼容性预设", font=("", 10, "bold"), fg="#28a745").pack(anchor="w", pady=(0, 6))
        tk.Label(tab_bato, text="此功能将一键为虚拟机注入 Batocera 最佳游戏调优参数：\n• CPU 直通物理指令集 (host) 获得最高模拟器帧率\n• 锁定 SeaBIOS 传统引导，彻底杜绝黑屏\n• 禁用 USB 平板指针 (tablet=0) 彻底解决手柄/摇杆方向漂移\n• 移除易崩溃的 SPICE 虚拟声卡冲突参数\n• 绑定 SATA0 第一启动盘与 VNC 5999 端口", 
                 justify="left", fg="#555", wraplength=580).pack(anchor="w", pady=(0, 10))

        f_presets = tk.Frame(tab_bato)
        f_presets.pack(fill="x", pady=6)

        tk.Button(f_presets, text="🎮 Batocera 标准模式", bg="#28a745", fg="white", font=("", 9, "bold"), command=lambda: self.apply_batocera_preset("std")).pack(fill="x", pady=3)
        tk.Button(f_presets, text="⚡ 显卡直通模式 (VGA=none)", bg="#ff9900", fg="white", font=("", 9, "bold"), command=lambda: self.apply_batocera_preset("none")).pack(fill="x", pady=3)

        # 状态指示与保存按钮
        self.lbl_status = tk.Label(f_bottom, text="状态: 正在拉取虚拟机配置详情...", fg="blue")
        self.lbl_status.pack(anchor="w", pady=4)

        self.btn_save = tk.Button(f_bottom, text="💾 保存全部修改", bg="#1e90ff", fg="white", font=("", 10, "bold"), command=self.save_config)
        self.btn_save.pack(fill="x", pady=(2, 0))

        self.load_config()

    # ------------------ Tab 2: 磁盘全生命周期管理视图 ------------------
    def _init_disk_mgmt_tab(self, parent):
        # 1. 现有磁盘清单
        f_tree_frame = tk.LabelFrame(parent, text="📋 当前虚拟机已挂载/闲置磁盘列表", padx=6, pady=4)
        f_tree_frame.pack(fill="both", expand=True, pady=2)

        self.tree_disks = ttk.Treeview(f_tree_frame, columns=("slot", "size", "volid"), show="headings", height=4)
        self.tree_disks.heading("slot", text="接口/插槽")
        self.tree_disks.heading("size", text="容量大小")
        self.tree_disks.heading("volid", text="存储路径 / VolID")
        self.tree_disks.column("slot", width=90, anchor="center")
        self.tree_disks.column("size", width=80, anchor="e")
        self.tree_disks.column("volid", width=380, anchor="w")

        scroll_d = ttk.Scrollbar(f_tree_frame, orient=tk.VERTICAL, command=self.tree_disks.yview)
        self.tree_disks.configure(yscrollcommand=scroll_d.set)
        self.tree_disks.pack(side="left", fill="both", expand=True)
        scroll_d.pack(side="right", fill="y")

        # 磁盘操作栏
        f_disk_acts = tk.Frame(parent)
        f_disk_acts.pack(fill="x", pady=2)
        tk.Button(f_disk_acts, text="🔄 刷新磁盘", command=self.load_disks_only).pack(side="left", padx=2)
        tk.Button(f_disk_acts, text="⏏️ 分离磁盘", command=self.detach_selected_disk).pack(side="left", padx=4)
        tk.Button(f_disk_acts, text="🗑️ 彻底删除选中磁盘", bg="#dc3545", fg="white", command=self.delete_selected_disk).pack(side="left", padx=2)
        tk.Label(f_disk_acts, text="目标插槽:").pack(side="left", padx=(10, 2))
        self.combo_move_slot = ttk.Combobox(f_disk_acts, values=["sata0", "sata1", "sata2", "scsi0", "scsi1", "virtio0", "virtio1"], width=9, state="readonly")
        self.combo_move_slot.set("sata0")
        self.combo_move_slot.pack(side="left", padx=2)
        tk.Button(f_disk_acts, text="🔗 挂载/移动到插槽", bg="#17a2b8", fg="white", command=self.mount_selected_disk).pack(side="left", padx=2)

        # 2. 🚀 直接导入镜像为新磁盘
        f_import_box = tk.LabelFrame(parent, text="🚀 直接导入镜像为新磁盘 (从宿主机/挂载物理硬盘提取)", padx=6, pady=4)
        f_import_box.pack(fill="x", pady=4)

        f_imp_r0 = tk.Frame(f_import_box)
        f_imp_r0.pack(fill="x", pady=2)
        tk.Label(f_imp_r0, text="镜像文件:").pack(side="left")
        self.entry_import_file = tk.Entry(f_imp_r0, fg="blue")
        self.entry_import_file.pack(side="left", fill="x", expand=True, padx=4)
        tk.Button(f_imp_r0, text="📂 浏览镜像...", bg="lightblue", command=self.pick_import_image).pack(side="left")

        f_imp_r1 = tk.Frame(f_import_box)
        f_imp_r1.pack(fill="x", pady=2)
        tk.Label(f_imp_r1, text="绑定接口:").pack(side="left")
        self.combo_import_slot = ttk.Combobox(f_imp_r1, values=["sata0", "sata1", "sata2", "scsi0", "scsi1", "virtio0"], width=8, state="readonly")
        self.combo_import_slot.set("sata0")
        self.combo_import_slot.pack(side="left", padx=4)

        tk.Label(f_imp_r1, text="目标存储:").pack(side="left", padx=(10, 2))
        self.combo_import_storage = ttk.Combobox(f_imp_r1, values=["local-lvm", "local"], width=12)
        self.combo_import_storage.set("local-lvm")
        self.combo_import_storage.pack(side="left", padx=2)

        self.btn_do_import = tk.Button(f_imp_r1, text="⚡ 导入并挂载为新磁盘", bg="#ff9900", fg="white", font=("", 9, "bold"), command=self.execute_import_disk)
        self.btn_do_import.pack(side="right", padx=2)

        # 3. ➕ 创建全新空白磁盘
        f_blank_box = tk.LabelFrame(parent, text="➕ 创建并挂载全新空白数据盘", padx=6, pady=4)
        f_blank_box.pack(fill="x", pady=2)

        f_blk = tk.Frame(f_blank_box)
        f_blk.pack(fill="x")
        tk.Label(f_blk, text="接口:").pack(side="left")
        self.combo_blank_slot = ttk.Combobox(f_blk, values=["sata1", "sata2", "scsi1", "virtio1"], width=8, state="readonly")
        self.combo_blank_slot.set("sata1")
        self.combo_blank_slot.pack(side="left", padx=2)

        tk.Label(f_blk, text="存储:").pack(side="left", padx=(10, 2))
        self.combo_blank_storage = ttk.Combobox(f_blk, values=["local-lvm", "local"], width=10)
        self.combo_blank_storage.set("local-lvm")
        self.combo_blank_storage.pack(side="left", padx=2)

        tk.Label(f_blk, text="容量(GB):").pack(side="left", padx=(10, 2))
        self.entry_blank_size = tk.Entry(f_blk, width=6)
        self.entry_blank_size.insert(0, "32")
        self.entry_blank_size.pack(side="left", padx=2)

        tk.Button(f_blk, text="➕ 创建空白盘", bg="#28a745", fg="white", command=self.create_blank_disk).pack(side="right", padx=2)

        # 4. 📦 从存储导入闲置磁盘 (可随时修改所属 VMID)
        f_idle_box = tk.LabelFrame(parent, text="📦 从存储导入闲置磁盘 (可随时修改所属 VMID)", padx=6, pady=4)
        f_idle_box.pack(fill="x", pady=4)
        f_idle_r0 = tk.Frame(f_idle_box)
        f_idle_r0.pack(fill="x", pady=2)
        tk.Button(f_idle_r0, text="🔄 扫描存储闲置盘", command=self.refresh_idle_disks).pack(side="left", padx=2)
        tk.Label(f_idle_r0, text="闲置盘:").pack(side="left", padx=(6, 2))
        self.combo_idle = ttk.Combobox(f_idle_r0, width=40, state="readonly")
        self.combo_idle.pack(side="left", fill="x", expand=True, padx=4)
        f_idle_r1 = tk.Frame(f_idle_box)
        f_idle_r1.pack(fill="x", pady=2)
        tk.Label(f_idle_r1, text="目标 VMID:").pack(side="left")
        self.entry_idle_vmid = tk.Entry(f_idle_r1, width=8)
        self.entry_idle_vmid.insert(0, str(self.vmid))
        self.entry_idle_vmid.pack(side="left", padx=2)
        tk.Label(f_idle_r1, text="目标插槽:").pack(side="left", padx=(8, 2))
        self.combo_idle_slot = ttk.Combobox(f_idle_r1, values=["sata0", "sata1", "sata2", "scsi0", "scsi1", "virtio0", "virtio1"], width=9, state="readonly")
        self.combo_idle_slot.set("sata1")
        self.combo_idle_slot.pack(side="left", padx=2)
        tk.Button(f_idle_r1, text="🔗 导入到目标VM", bg="#6f42c1", fg="white", command=self.import_idle_disk).pack(side="left", padx=4)

    def pick_import_image(self):
        RemoteFilePickerDialog(self, self.app, lambda path: self.entry_import_file.delete(0, tk.END) or self.entry_import_file.insert(0, path))

    def load_disks_only(self):
        def task():
            try:
                out = self.app.run_ssh_cmd(f"qm config {self.vmid}", ignore_error=True)
                def update():
                    try:
                        if not self.winfo_exists(): return
                        self.tree_disks.delete(*self.tree_disks.get_children())
                        for line in out.strip().split('\n'):
                            if ':' in line:
                                k, v = line.split(':', 1)
                                k, v = k.strip(), v.strip()
                                if any(k.startswith(p) for p in ["sata", "scsi", "virtio", "ide", "unused", "efidisk"]):
                                    volid = v.split(',')[0].strip()
                                    sz_match = re.search(r"size=([^,\s]+)", v)
                                    sz = sz_match.group(1) if sz_match else "-"
                                    self.tree_disks.insert("", "end", values=(k, sz, volid))
                    except Exception:
                        pass
                self.after(0, update)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 读取磁盘列表失败: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    def detach_selected_disk(self):
        sel = self.tree_disks.focus()
        if not sel:
            messagebox.showwarning("提示", "请在上方列表中选中一个要分离的磁盘！")
            return
        slot, _, volid = self.tree_disks.item(sel, "values")
        if slot.startswith("unused"):
            self.lbl_status.config(text="[!] 该磁盘已经是闲置状态，无需分离。", fg="#b8860b")
            return
        if not messagebox.askyesno("确认", f"确定要从插槽 [{slot}] 分离磁盘吗？\n(磁盘将转为闲置 unused 状态，数据不会丢失)"): return

        def task():
            try:
                self.app.log(f"[*] 正在从 VM {self.vmid} 分离磁盘 {slot} ...")
                self.app.run_ssh_cmd(f"qm unlink {self.vmid} --idlist {slot}")
                self.after(0, self.load_disks_only)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 分离失败: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    def delete_selected_disk(self):
        sel = self.tree_disks.focus()
        if not sel:
            messagebox.showwarning("提示", "请先选中一个磁盘！")
            return
        slot, _, volid = self.tree_disks.item(sel, "values")
        if not messagebox.askyesno("⚠️ 高危警告", f"确定彻底销毁并删除磁盘 [{slot} : {volid}] 吗？\n此操作不可逆，数据将永久丢失！"): return

        def task():
            try:
                self.app.log(f"[*] 正在彻底销毁并删除磁盘 {volid} ...")
                self.app.run_ssh_cmd(f"qm set {self.vmid} --delete {slot}", ignore_error=True)
                if ":" in volid:
                    self.app.run_ssh_cmd(f"pvesm free '{volid}'", ignore_error=True)
                self.after(0, self.load_disks_only)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 删除失败: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    def execute_import_disk(self):
        img_path = self.entry_import_file.get().strip()
        slot = self.combo_import_slot.get().strip()
        storage = self.combo_import_storage.get().strip() or "local-lvm"

        if not img_path:
            messagebox.showwarning("提示", "请先选择镜像文件路径！")
            return

        self.btn_do_import.config(state="disabled")
        self.lbl_status.config(text=f"[*] 正在导入 [{os.path.basename(img_path)}] 并挂载到 {slot}...", fg="blue")

        def task():
            try:
                # 若替换启动盘 sata0 且虚拟机正在运行，先安全关机防冲突
                vm_status = self.app.run_ssh_cmd(f"qm status {self.vmid}", ignore_error=True)
                if slot == "sata0" and "status: running" in vm_status:
                    self.app.log(f"[*] 正在安全停止 VM {self.vmid} 准备替换引导盘...")
                    self.app.run_ssh_cmd(f"qm stop {self.vmid}", ignore_error=True)

                self.app.log(f"[*] 正在导入磁盘镜像: {img_path} 到存储池 {storage} ...")
                import_out = self.app.run_ssh_cmd(f"qm importdisk {self.vmid} '{img_path}' {storage}")

                match = re.search(r"imported disk as '?(?:unused\d+:)?([^'\s]+)'?", import_out)
                target_volid = match.group(1).strip() if match else f"{storage}:vm-{self.vmid}-disk-0"
                target_volid = re.sub(r"^unused\d+:", "", target_volid)
                if ":" not in target_volid: target_volid = f"{storage}:{target_volid}"

                self.app.log(f"[*] 正在将磁盘挂载到插槽 {slot} ...")
                self.app.run_ssh_cmd(f"qm set {self.vmid} --{slot} '{target_volid}'")
                if slot == "sata0":
                    self.app.run_ssh_cmd(f"qm set {self.vmid} --boot c --bootdisk sata0")

                self.after(0, lambda: self.lbl_status.config(text=f"[+] 镜像已成功导入并挂载至 {slot}！", fg="green"))
                self.after(0, self.load_disks_only)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.lbl_status.config(text=f"[-] 导入失败: {msg}", fg="red"))
            finally:
                self.after(0, lambda: self.btn_do_import.config(state="normal"))

        threading.Thread(target=task, daemon=True).start()

    def create_blank_disk(self):
        slot = self.combo_blank_slot.get().strip()
        storage = self.combo_blank_storage.get().strip() or "local-lvm"
        size = self.entry_blank_size.get().strip() or "32"

        def task():
            try:
                self.app.log(f"[*] 正在创建全新空白磁盘 {slot}: {storage}:{size}G ...")
                self.app.run_ssh_cmd(f"qm set {self.vmid} --{slot} {storage}:{size}")
                self.after(0, lambda s=slot, sz=size: self.lbl_status.config(text=f"[+] 已创建并挂载空白磁盘 {s} ({sz} GB)！", fg="green"))
                self.after(0, self.load_disks_only)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 创建失败: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    def mount_selected_disk(self):
        sel = self.tree_disks.focus()
        if not sel:
            messagebox.showwarning("提示", "请先在磁盘列表中选中一个磁盘！")
            return
        slot, _, volid = self.tree_disks.item(sel, "values")
        target = self.combo_move_slot.get().strip()
        if slot == target:
            self.lbl_status.config(text="[!] 目标插槽与当前相同，无需移动。", fg="#b8860b")
            return

        def task():
            try:
                self.app.log(f"[*] 正在将磁盘 {volid} 挂载/移动到插槽 {target} ...")
                self.app.run_ssh_cmd(f"qm set {self.vmid} --{target} '{volid}'")
                if target == "sata0":
                    self.app.run_ssh_cmd(f"qm set {self.vmid} --boot c --bootdisk sata0")
                self.after(0, lambda t=target: self.lbl_status.config(text=f"[+] 磁盘已挂载到 {t}！", fg="green"))
                self.after(0, self.load_disks_only)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 挂载失败: {err_msg}")
                self.after(0, lambda m=err_msg: messagebox.showerror("失败", f"挂载失败: {m}"))

        threading.Thread(target=task, daemon=True).start()

    def refresh_idle_disks(self):
        storage = self.combo_import_storage.get().strip() or "local-lvm"

        def task():
            try:
                cfg = self.app.run_ssh_cmd(f"qm config {self.vmid}", ignore_error=True)
                used_vols = set()
                for line in cfg.strip().split("\n"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        if any(k.startswith(p) for p in ["sata", "scsi", "virtio", "ide", "unused", "efidisk"]):
                            used_vols.add(v.strip().split(",")[0].strip())
                out = self.app.run_ssh_cmd(f"pvesm list {storage} 2>/dev/null", ignore_error=True)
                size_map = {}
                for line in out.strip().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) >= 4 and ":" in parts[0] and parts[2].isdigit():
                        b = int(parts[2])
                        size_map[parts[0]] = f"{b/1024/1024/1024:.1f}G" if b >= 1024**3 else f"{b/1024/1024:.0f}M"
                # 映射 volid -> 挂载点 (所属 VM / unused 插槽)
                slot_map = {}
                grep_out = self.app.run_ssh_cmd(
                    "grep -H -E '^(unused[0-9]+):' /etc/pve/qemu-server/*.conf 2>/dev/null || true", ignore_error=True)
                for line in grep_out.strip().split("\n"):
                    mm = re.search(r"/(\d+)\.conf:unused(\d+):\s*(\S+)", line)
                    if mm:
                        v, n, raw = mm.groups()
                        rv = re.sub(r"^unused\d+:", "", raw.split(",")[0].strip())
                        slot_map[rv] = f"VM{v}/unused{n}"
                idle = []
                for line in out.strip().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    vol = parts[0]
                    if vol in used_vols:
                        continue
                    m = re.match(r"vm-(\d+)-disk-(\d+)", vol)
                    owner = m.group(1) if m else "?"
                    sz = size_map.get(vol, "?")
                    mp = slot_map.get(vol, "游离(未挂载)")
                    idle.append(f"{storage}:{vol} | {sz} | 属VM {owner} | 挂载:{mp}")

                def update():
                    self.combo_idle["values"] = idle
                    if idle:
                        self.combo_idle.set(idle[0])

                self.after(0, update)
            except Exception as e:
                self.app.log(f"[-] 扫描闲置盘失败: {e}")

        threading.Thread(target=task, daemon=True).start()

    def import_idle_disk(self):
        val = self.combo_idle.get().strip()
        if not val:
            messagebox.showwarning("提示", "请先扫描并选择一枚闲置盘！")
            return
        try:
            target_vmid = int(self.entry_idle_vmid.get().strip())
        except Exception:
            messagebox.showwarning("提示", "目标 VMID 必须为数字！")
            return
        target = self.combo_idle_slot.get().strip()
        volid = val.split(" ")[0]
        owner = re.search(r"属VM (\d+)", val)
        owner = owner.group(1) if owner else None
        if owner and owner != str(target_vmid):
            if not messagebox.askyesno("⚠️ 注意", f"该磁盘当前属于 VM {owner}，挂载到 VM {target_vmid} 会使其从原 VM 卸下并归属 VM {target_vmid}。\n确定继续吗？"):
                return

        def task():
            try:
                self.app.log(f"[*] 正在将闲置盘 {volid} 导入并挂载到 VM {target_vmid} 插槽 {target} ...")
                self.app.run_ssh_cmd(f"qm set {target_vmid} --{target} '{volid}'")
                if target == "sata0":
                    self.app.run_ssh_cmd(f"qm set {target_vmid} --boot c --bootdisk sata0")
                self.after(0, lambda tv=target_vmid, t=target: self.lbl_status.config(text=f"[+] 闲置盘已挂载到 VM {tv} 的 {t}！", fg="green"))
                self.after(0, self.load_disks_only)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 导入失败: {err_msg}")
                self.after(0, lambda m=err_msg: messagebox.showerror("失败", f"导入失败: {m}"))

        threading.Thread(target=task, daemon=True).start()

    def quick_fix_boot(self):
        boot_dev = self.combo_boot.get().split()[0]
        def task():
            try:
                self.app.log(f"[*] 正在修复虚拟机 {self.vmid} 启动引导并清除声卡冲突...")
                # 先读当前配置: 有 PCI 直通时严禁切 seabios/删 EFI 盘 (会把 UEFI 直通引导打坏)
                cfg_out = self.app.run_ssh_cmd(f"qm config {self.vmid}", ignore_error=True)
                has_hostpci = any(line.strip().startswith("hostpci") for line in cfg_out.split("\n"))
                if has_hostpci:
                    self.app.log("[✓] 检测到 PCI 直通, 保持 q35/OVMF 引导, 仅锁定引导盘。")
                    self.app.run_ssh_cmd(f"qm set {self.vmid} --boot c --bootdisk {boot_dev}", ignore_error=True)
                else:
                    self.app.run_ssh_cmd(
                        f"qm set {self.vmid} --boot c --bootdisk {boot_dev} --bios seabios --delete audio0 --delete efidisk0"
                    )
                self.after(0, lambda: self.lbl_status.config(text="[+] 引导已修复为 %s！%s" % (boot_dev, "" if has_hostpci else " (已移出声卡冲突参数)"), fg="green"))
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.lbl_status.config(text=f"[-] 引导修复失败: {msg}", fg="red"))
        threading.Thread(target=task, daemon=True).start()

    def apply_batocera_preset(self, vga_mode="std"):
        self.combo_ostype.set("l26")
        self.combo_cpu.set("host")
        self.var_tablet.set(0)
        self.combo_boot.set("sata0")
        self.combo_audio.set("none (关闭, 最稳)")
        
        if vga_mode == "none":
            # 硬件直通模式: 必须 q35 机型 (hostpci + pcie=1 强制要求), vga=none
            self.combo_bios.set("ovmf")
            self.combo_machine.set("q35")
            self.combo_vga.set("none (无显卡 - 硬件直通必选)")
        else:
            self.combo_bios.set("seabios")
            self.combo_machine.set("i440fx")
            self.combo_vga.set("std (标准兼容VGA)")
            
        self.lbl_status.config(text="[+] 已载入 Batocera 最佳兼容性参数，点击下方【保存并应用】生效！", fg="green")

    def load_config(self):
        def task():
            try:
                out = self.app.run_ssh_cmd(f"qm config {self.vmid}", ignore_error=True)
                cfg = {}
                for line in out.strip().split('\n'):
                    if ':' in line:
                        k, v = line.split(':', 1)
                        cfg[k.strip()] = v.strip()
                
                def update():
                    self.entry_name.delete(0, tk.END)
                    self.entry_name.insert(0, cfg.get("name", ""))
                    
                    self.combo_ostype.set(cfg.get("ostype", "l26"))
                    self.combo_bios.set(cfg.get("bios", "seabios"))
                    _cfg_machine = cfg.get("machine", "") or "pc"
                    _mval, _mwarn = normalize_pve_machine(_cfg_machine)
                    # 统一回显为友好名 (pc 即 i440fx), readonly combobox 只接受列表内值
                    if _mval and "q35" in _mval:
                        self.combo_machine.set("q35")
                    else:
                        self.combo_machine.set("i440fx")
                    self._update_machine_warn()
                    self.var_onboot.set(1 if cfg.get("onboot") == "1" else 0)
                    self.var_agent.set(1 if "1" in cfg.get("agent", "1") else 0)
                    self.var_tablet.set(1 if cfg.get("tablet") == "1" else 0)

                    boot_val = cfg.get("bootdisk", "") or cfg.get("boot", "")
                    if "scsi" in boot_val: self.combo_boot.set("scsi0")
                    elif "ide" in boot_val: self.combo_boot.set("ide2 (光驱)")
                    elif "virtio" in boot_val: self.combo_boot.set("virtio0")
                    else: self.combo_boot.set("sata0")

                    self.entry_sockets.delete(0, tk.END)
                    self.entry_sockets.insert(0, cfg.get("sockets", "1"))
                    self.entry_cores.delete(0, tk.END)
                    self.entry_cores.insert(0, cfg.get("cores", "2"))
                    self.combo_cpu.set(cfg.get("cpu", "host"))
                    self.var_numa.set(1 if cfg.get("numa") == "1" else 0)

                    self.entry_mem.delete(0, tk.END)
                    self.entry_mem.insert(0, cfg.get("memory", "2048"))
                    self.entry_balloon.delete(0, tk.END)
                    self.entry_balloon.insert(0, cfg.get("balloon", "0"))

                    vga_val = cfg.get("vga", "std")
                    for opt in self.combo_vga['values']:
                        if opt.startswith(vga_val):
                            self.combo_vga.set(opt)
                            break

                    self.combo_scsi.set(cfg.get("scsihw", "virtio-scsi-single"))

                    # 回填 PCI 直通: 把现有 hostpci0/1/... 合并显示
                    hp_start = []
                    for hk in sorted(k for k in cfg if k.startswith("hostpci")):
                        hp_start.append(cfg[hk])
                    self.entry_hostpci.delete(0, tk.END)
                    if hp_start:
                        self.entry_hostpci.insert(0, "; ".join(hp_start))
                    
                    audio_val = cfg.get("audio0", "")
                    if "ich9" in audio_val: self.combo_audio.set("ich9-intel-hda")
                    elif "intel-hda" in audio_val: self.combo_audio.set("intel-hda")
                    elif "ac97" in audio_val.lower(): self.combo_audio.set("AC97")
                    else: self.combo_audio.set("none (关闭, 最稳)")

                    self.lbl_status.config(text="[+] 成功读取虚拟机完整参数！", fg="green")
                    self._config_loaded = True
                self.after(0, update)
                self.after(0, self.load_disks_only)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.lbl_status.config(text=f"[-] 读取配置失败: {msg}", fg="red"))
        threading.Thread(target=task, daemon=True).start()

    def _update_machine_warn(self):
        val, warn = normalize_pve_machine(self.combo_machine.get())
        if val is None:
            self.lbl_machine_warn.config(text="⚠ " + warn, fg="red")
        elif warn:
            self.lbl_machine_warn.config(text="⚠ " + warn, fg="#b8860b")
        else:
            self.lbl_machine_warn.config(text="✓ 合法机型", fg="green")

    def save_config(self):
        name = self.entry_name.get().strip()
        ostype = self.combo_ostype.get()
        bios = self.combo_bios.get()
        machine_raw = self.combo_machine.get()
        machine, machine_warn = normalize_pve_machine(machine_raw)
        if machine is None:
            messagebox.showerror("机型非法", machine_warn)
            return

        _vga_raw = self.combo_vga.get().strip()
        # 兼容两种输入: "std (标准兼容VGA)" 预置文案取首词 或 用户手输原始值(std/virtio-gl/..., 可带逗号传 vga 参数)
        vga_raw = _vga_raw.split()[0] if " " in _vga_raw or _vga_raw in _G_VGA_CHOICES else _vga_raw
        audio_choice = self.combo_audio.get().split()[0]
        hostpci_manual = self.entry_hostpci.get().strip()

        # ── 直通联动防护: 读取现有配置, 记录已有 hostpci 槽位 ──
        had_hostpci = []
        cur_bios = None
        cur_machine = None
        has_efidisk = False
        cfg_all = {}
        try:
            cfg_out = self.app.run_ssh_cmd(f"qm config {self.vmid}", ignore_error=True)
            for line in cfg_out.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    k, v = k.strip(), v.strip()
                    cfg_all[k] = v
                    if k.startswith("hostpci"):
                        had_hostpci.append(k)
                    if k == "bios": cur_bios = v
                    if k == "machine": cur_machine = v
                    if k.startswith("efidisk"): has_efidisk = True
        except Exception:
            pass

        # 保存后是否仍有直通: 输入框非空 = 保有直通; 为空 = 未配置/显式移除
        # (load_config 会自动回填现有 hostpci, 因此输入框被清空即用户明确要求移除直通)
        has_hostpci = bool(hostpci_manual)

        if not self._config_loaded and cur_bios in ("ovmf", "seabios"):
            # 构造时默认 seabios, load_config 是异步的: 若用户没等它读完就保存, 必须用线上真实 BIOS 兜底,
            # 否则会把 OVMF 盒误存成 seabios / 给 seabios 盒乱建 efidisk0
            bios = cur_bios
            try: self.combo_bios.set(bios)
            except Exception: pass

        # PCI 直通仅要求 q35 机型 (hostpci 带 pcie=1 需 q35), BIOS 保持用户选择 (seabios 亦可,
        # 不再强制 ovmf, 否则每次直通都会把 seabios 盒改成 UEFI 并自动补一块 efidisk0)

        # UEFI (OVMF) 必须搭配 q35 机型, 自动纠正为 q35
        if machine and bios == "ovmf" and not machine.startswith("q35"):
            machine = "q35"
            machine_warn = None
        # PCI 直通 (hostpci 带 pcie=1) 同样必须 q35, 但不动 BIOS
        elif has_hostpci and machine and not machine.startswith("q35"):
            machine = "q35"
            machine_warn = None
        if machine_warn:
            messagebox.showwarning("机型联动提示", machine_warn)

        onboot = self.var_onboot.get()
        agent = 1 if self.var_agent.get() else 0
        tablet = self.var_tablet.get()
        boot_dev = self.combo_boot.get().split()[0]

        sockets = self.entry_sockets.get().strip() or "1"
        cores = self.entry_cores.get().strip() or "2"
        cpu = self.combo_cpu.get()
        numa = self.var_numa.get()
        mem = self.entry_mem.get().strip() or "2048"
        balloon = self.entry_balloon.get().strip() or "0"

        scsi = self.combo_scsi.get()

        # OVMF + 直通场景禁止注入 -vnc args: 它会跟直通显卡/真实显示抢占
        vnc_args = "" if (vga_raw == "none" or has_hostpci) else f"--args '-vnc 0.0.0.0:{self.vmid}'"

        cmd = (
            f"qm set {self.vmid} --name '{name}' --ostype {ostype} --bios {bios} --machine {machine} "
            f"--onboot {onboot} --agent {agent} --tablet {tablet} --sockets {sockets} --cores {cores} "
            f"--cpu {cpu} --numa {numa} --memory {mem} --balloon {balloon} --vga {vga_raw} --scsihw {scsi} "
            f"--boot c --bootdisk {boot_dev} {vnc_args}"
        ).strip()

        # 切回传统 BIOS (SeaBIOS) 时必须移除 EFI 磁盘, 否则 PVE 报错 "efidisk0 can only be used with OVMF"
        if bios == "seabios":
            cmd += " --delete efidisk0"

        if audio_choice != "none":
            # QXL 显示走 SPICE 音频驱动; 其余显示(STD/VIRTIO/VNC)无需 driver,
            # 仅向客户机提供虚拟声卡硬件, 由 Sunshine 从客户机内采集音频, 避免 QEMU spice 音频崩溃。
            if "qxl" in vga_raw:
                cmd += f" --audio0 device={audio_choice},driver=spice"
            else:
                cmd += f" --audio0 device={audio_choice}"
        else:
            cmd += " --delete audio0"

        # ── PCI 手工直通: 解析 entry_hostpci 生成 hostpci0/1/... 槽位 ──
        # 分隔符: 分号/换行 = 多个设备各占一个槽位; 逗号 = 同一槽位多功能 (00:00.0,00:00.1)
        # 例: "00:02.0,pcie=1" → hostpci0;  "00:02.0; 03:00.0,pcie=1" → hostpci0+hostpci1
        if hostpci_manual:
            slots = [s.strip() for s in re.split(r";|\n", hostpci_manual) if s.strip()]
            # 先清掉所有旧直通槽位 (避免 set 与 delete 同命令冲突), 再逐个写入新槽位
            old_slots = sorted(had_hostpci)
            for oldk in old_slots:
                cmd += f" --delete {oldk}"
            for idx, slot in enumerate(slots):
                slot = slot.replace(", ", ",")
                cmd += f" --hostpci{idx} '{slot}'"
        elif had_hostpci:
            # 输入框已清空且原有直通: 显式移除全部直通槽位
            for oldk in sorted(had_hostpci):
                cmd += f" --delete {oldk}"

        self.btn_save.config(state="disabled")
        self.lbl_status.config(text="[*] 正在向 PVE 灌入配置...", fg="blue")

        def task():
            try:
                self.app.run_ssh_cmd(cmd)
                # 不再自动补建 efidisk0: 用户反复反馈编辑保存后莫名多出 efidisk0。
                # 需要 EFI 盘(直通 UEFI)时由用户或 PVE 手动管理, 工具只负责提示, 绝不擅自建盘。
                if bios == "ovmf" and machine.startswith("q35") and not has_efidisk:
                    self.app.log("[!] 已选择 OVMF 但当前无 efidisk0。若确需 UEFI 引导请在 PVE 侧手动创建 efidisk0 (工具不再自动创建)。")
                self.after(0, lambda: self.lbl_status.config(text="[+] 全量配置修改成功！", fg="green"))
                self.app.refresh_vms()
                self.after(0, self.destroy)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.lbl_status.config(text=f"[-] 保存失败: {msg}", fg="red"))
            finally:
                def _reenable():
                    try:
                        if getattr(self, 'btn_save', None) and self.btn_save.winfo_exists():
                            self.btn_save.config(state="normal")
                    except Exception:
                        pass
                self.after(0, _reenable)
        threading.Thread(target=task, daemon=True).start()

class PciPassthroughDialog(tk.Toplevel):
    def __init__(self, parent, app, vmid, fill_target=None, fill_vga=None, fill_audio=None):
        super().__init__(parent)
        self.app = app
        self.vmid = vmid
        # fill 模式: 从「硬件编辑」对话框呼出, 选取结果只回填其 hostpci 输入框(和显卡/声卡下拉),
        # 不直接改 VM; standalone 模式(右键菜单)仍直接 qm set 应用。
        self.fill_target = fill_target
        self.fill_vga = fill_vga
        self.fill_audio = fill_audio
        if fill_target is not None:
            self.title(f"🧭 直通选择 (回填到硬件编辑) - VM {vmid}")
        else:
            self.title(f"⚡ PCI 硬件直通与显卡设置 - VM {vmid}")
        self.geometry("680x480")
        self.minsize(640, 420)
        self.resizable(True, True)
        self.transient(parent)
        if fill_target is None:
            self.grab_set()

        frame = tk.Frame(self, padx=10, pady=10)
        frame.pack(fill="both", expand=True)

        f_top = tk.Frame(frame)
        f_top.pack(fill="x", pady=5)
        self.var_autostart = tk.IntVar()
        tk.Checkbutton(f_top, text="🔌 随PVE宿主机开机自启", variable=self.var_autostart).pack(side="left")

        tk.Label(f_top, text="🖥️ 显卡类型:").pack(side="left", padx=(15, 2))
        self.combo_vga = ttk.Combobox(f_top, values=["none", "std", "vmware", "cirrus", "qxl", "qxl2", "qxl3", "qxl4", "virtio", "virtio-gl", "serial0", "serial1", "serial2", "serial3"], width=14, state="readonly")
        self.combo_vga.set("none")
        self.combo_vga.pack(side="left")

        f_scan = tk.Frame(frame)
        f_scan.pack(fill="x", pady=5)
        tk.Button(f_scan, text="🔍 扫描 PCI 设备", bg="lightblue", command=self.scan_pci).pack(side="left")
        tk.Label(f_scan, text="(多选: Ctrl/Shift; 同 IOMMU 组自动绑定)", fg="gray").pack(side="left", padx=5)

        f_tree = tk.Frame(frame)
        f_tree.pack(fill="both", expand=True, pady=5)
        self.tree = ttk.Treeview(f_tree, columns=("pci_id", "type", "desc"), show="headings", height=8, selectmode="extended")
        self.tree.heading("pci_id", text="PCI 地址")
        self.tree.heading("type", text="类型")
        self.tree.heading("desc", text="硬件设备描述")
        self.tree.column("pci_id", width=80, anchor="center")
        self.tree.column("type", width=56, anchor="center")
        self.tree.column("desc", width=380, anchor="w")
        
        scroll = ttk.Scrollbar(f_tree, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # 硬件类型列色彩 Tag: 显卡=紫 / 声卡=绿 / 网卡=蓝 / 存储=橙, 提升辨识度
        self.tree.tag_configure("显卡", foreground="#8b5cf6")
        self.tree.tag_configure("声卡", foreground="#16a34a")
        self.tree.tag_configure("网卡", foreground="#0ea5e9")
        self.tree.tag_configure("存储", foreground="#ea580c")
        self.tree.tag_configure("USB", foreground="#6d28d9")
        self.tree.tag_configure("其它", foreground="#6b7280")

        if self.fill_target is not None:
            self.btn_apply = tk.Button(frame, text="✅ 填回硬件编辑 (含同IOMMU组)", bg="#ff9900", fg="white", font=("", 10, "bold"), command=self.apply_all)
        else:
            self.btn_apply = tk.Button(frame, text="🚀 应用直通+显卡配置", bg="#ff9900", fg="white", font=("", 10, "bold"), command=self.apply_all)
        self.btn_apply.pack(fill="x", pady=10)

        self.scan_pci()

    @staticmethod
    def _classify(desc):
        d = (desc or "").lower()
        # 存储设备优先判断 (SATA/NVMe/RAID 等即使含 display 关键词也应归存储)
        if "sata" in d or "nvme" in d or "raid" in d or "ahci" in d or "ide" in d or "storage" in d:
            return "存储"
        if "audio" in d or "sound" in d:
            return "声卡"
        if "usb" in d:
            return "USB"
        if "network" in d or "ethernet" in d or "wi-fi" in d or "wireless" in d:
            return "网卡"
        if "vga" in d or "3d" in d or "display" in d:
            return "显卡"
        return "其它"

    def scan_pci(self):
        def task():
            try:
                out = self.app.run_ssh_cmd("lspci -nn", ignore_error=True)
                # 采集 IOMMU 分组: 设备 -> 组号, 组号 -> 同组全部设备
                grp_cmd = ("for d in /sys/bus/pci/devices/*; do "
                           "a=$(basename $d); g=$(readlink $d/iommu_group 2>/dev/null | xargs basename 2>/dev/null); "
                           "echo \"$a $g\"; done")
                grp_out = self.app.run_ssh_cmd(grp_cmd, ignore_error=True)
                self.addr_group = {}
                self.group_members = {}
                for line in grp_out.strip().split('\n'):
                    parts = line.split()
                    if len(parts) == 2:
                        addr_full, g = parts
                        addr = addr_full[5:] if addr_full.startswith("0000:") else addr_full
                        self.addr_group[addr] = g
                        self.group_members.setdefault(g, set()).add(addr)
                # 采集每个设备当前绑定驱动 (宿主占用检测: 需 vfio-pci/unbound 才能直通)
                drv_cmd = ("for d in /sys/bus/pci/devices/*; do "
                           "a=$(basename $d); "
                           "drv=$(basename $(readlink $d/driver 2>/dev/null) 2>/dev/null || echo unbound); "
                           "echo \"$a $drv\"; done")
                drv_out = self.app.run_ssh_cmd(drv_cmd, ignore_error=True)
                self.addr_driver = {}
                for line in drv_out.strip().split('\n'):
                    parts = line.split()
                    if len(parts) == 2:
                        addr_full, drv = parts
                        addr = addr_full[5:] if addr_full.startswith("0000:") else addr_full
                        self.addr_driver[addr] = drv
                self.after(0, lambda: self.tree.delete(*self.tree.get_children()))
                for line in out.strip().split('\n'):
                    match = re.match(r"^([\da-fA-F]{2}:[\da-fA-F]{2}\.\d)\s+(.*)", line)
                    if match:
                        pci_id, desc = match.groups()
                        drv = self.addr_driver.get(pci_id, "")
                        suffix = f"  [宿主占用:{drv}]" if drv and drv != "unbound" else ""
                        self.after(0, lambda p=pci_id, d=desc, s=suffix: self.tree.insert("", "end", values=(p, self._classify(d), d + s), tags=(self._classify(d),)))
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 扫描失败: {err_msg}")
        threading.Thread(target=task, daemon=True).start()

    def _apply_fill(self, text, vga, audio):
        """fill 模式: 把直通选取(IOMMU 组归并结果)写回硬件编辑对话框的输入框, 然后关闭自身"""
        try:
            self.fill_target.delete(0, tk.END)
            self.fill_target.insert(0, text)
            if self.fill_vga is not None and vga:
                for opt in self.fill_vga['values']:
                    if opt.startswith(vga):
                        self.fill_vga.set(opt)
                        break
            if self.fill_audio is not None and audio:
                for opt in self.fill_audio['values']:
                    if opt.startswith(audio):
                        self.fill_audio.set(opt)
                        break
            self.app.log(f"[+] 已把直通选取填入硬件编辑: {text}" + (f" | 显卡自动置 {vga}" if vga else "") + (f" | 声卡自动置 {audio}" if audio else ""))
        except Exception as e:
            self.app.log(f"[-] 回填失败: {e}")
        finally:
            try:
                if self.winfo_exists():
                    self.destroy()
            except Exception:
                pass

    def apply_all(self):
        vga = self.combo_vga.get() or "none"
        autostart = 1 if self.var_autostart.get() else 0
        selected = [self.tree.item(i, "values")[0] for i in self.tree.selection()]
        if not selected:
            self.app.log("[-] 未选择任何 PCI 设备, 请先扫描并勾选要直通的硬件。")
            messagebox.showwarning("提示", "请先在上方列表中选择要直通的 PCI 设备！")
            return

        # ── fill 模式: 只回填硬件编辑的输入框, 不直接改 VM (让硬件编辑保存时统一处理 q35/OVMF) ──
        if self.fill_target is not None:
            self.btn_apply.config(state="disabled")
            is_gpu = any(self.tree.item(i, "values")[1] == "显卡" for i in self.tree.selection())
            is_audio = any(self.tree.item(i, "values")[1] == "声卡" for i in self.tree.selection())
            vga_sel = "none" if is_gpu else (vga if not vga.startswith("none") else "none")
            audio_sel = "none" if is_audio else None
            def fill_task():
                try:
                    addr_group = getattr(self, "addr_group", {})
                    group_members = getattr(self, "group_members", {})
                    if not addr_group or not selected:
                        raise Exception("PCI 设备未成功扫描, 请点击【扫描宿主机 PCI 设备】后再选。")
                    groups = {}
                    for addr in selected:
                        g = addr_group.get(addr)
                        if not g:
                            groups.setdefault(addr, set([addr]))
                        else:
                            groups.setdefault(g, set())
                            for m in group_members.get(g, [addr]):
                                groups[g].add(m)
                    slot_vals = []
                    for addrs in groups.values():
                        slot_vals.append(",".join(sorted(addrs)) + ",pcie=1")
                    self.after(0, lambda t="; ".join(slot_vals), v=vga_sel, a=audio_sel: self._apply_fill(t, v, a))
                except Exception as e:
                    self.after(0, lambda m=str(e): messagebox.showerror("直通选择失败", m))
            threading.Thread(target=fill_task, daemon=True).start()
            return

        self.btn_apply.config(state="disabled")
        def task():
            try:
                # 0. 读取当前配置, 判断机器模型 / BIOS / 运行状态 / 是否已有 efidisk
                cfg_out = self.app.run_ssh_cmd(f"qm config {self.vmid}", ignore_error=True)
                cfg = {}
                for line in cfg_out.split("\n"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        cfg[k.strip()] = v.strip()
                cur_machine = cfg.get("machine", "pc")
                cur_bios = cfg.get("bios", "seabios")
                is_q35 = "q35" in cur_machine
                has_efidisk = any(k.startswith("efidisk") for k in cfg)
                running = "status: running" in self.app.run_ssh_cmd(f"qm status {self.vmid}", ignore_error=True)

                # 1. 直通硬约束: 显卡/声卡带 pcie=1 必须 q35 机型 (PVE: "q35 machine model is not enabled")
                #    -> 若当前非 q35, 必须先切 q35 (改机型需停机, 若运行中则阻止并提示先关机)。
                #    另: 显式输出类型为"显卡"的设备必须配合 vga=none, 否则启动黑屏/资源冲突。
                is_gpu = any(self.tree.item(i, "values")[1] == "显卡" for i in self.tree.selection())
                if not is_q35:
                    if running:
                        raise Exception("当前机型非 q35, 改机型必须在关机状态下进行。请先对虚拟机执行【安全关机】后再应用直通。")
                    self.app.log(f"[*] 检测到机型 {cur_machine}, 自动升级为 q35 (PCIe 直通必需)...")
                    self.app.run_ssh_cmd(f"qm set {self.vmid} --machine q35")
                    cur_machine = "q35"
                    is_q35 = True
                if is_q35 and cur_bios != "ovmf":
                    self.app.log(f"[*] 检测到 BIOS 为 {cur_bios}, 直通建议配合 OVMF(UEFI)。非必需, 保持现状即可。")

                # 2. 显卡直通: 强制 vga=none, 否则 PVE 保留虚拟 VGA 会与直通显卡抢占
                if is_gpu and vga != "none":
                    self.app.log("[*] 检测到显卡直通, 自动将虚拟显卡设为 none (避免显示冲突)...")
                    vga = "none"

                # 3. 按 IOMMU 组归并: 选中一个设备即把整组(显卡+声卡等)一起直通, 满足 PVE 要求
                groups = {}
                for addr in selected:
                    g = self.addr_group.get(addr)
                    if not g:
                        groups.setdefault(addr, set([addr]))
                    else:
                        groups.setdefault(g, set())
                        for m in self.group_members.get(g, [addr]):
                            groups[g].add(m)

                # 3.5 宿主占用检查: 被宿主驱动绑定的设备需先解绑并绑定 vfio-pci 才能直通
                occupied = []
                for addrs in groups.values():
                    for a in addrs:
                        drv = getattr(self, "addr_driver", {}).get(a, "")
                        if drv and drv != "vfio-pci":
                            occupied.append(f"{a}({drv})")
                if occupied:
                    raise Exception(
                        "以下设备仍被宿主机驱动占用, 无法直通:\n"
                        + "\n".join(occupied)
                        + "\n\n需先在宿主机执行: echo '<vendor:devid>' > /sys/bus/pci/drivers/vfio-pci/new_id\n"
                          "或 GRUB 内核参数加入 vfio-pci.ids=<vendor:devid> 后重启宿主。"
                    )

                # 4. 先清空旧 hostpci 槽位, 再逐个写入 (OVMF 下需停机才能改 hostpci)
                if running and groups:
                    self.app.log("[!] VM 正在运行: hostpci 配置已写入, 需重启虚拟机(OVMF 建议完全断电重启)后才生效。")
                self.app.run_ssh_cmd(f"qm set {self.vmid} --onboot {autostart}")
                for i in range(0, 6):
                    self.app.run_ssh_cmd(f"qm set {self.vmid} --delete hostpci{i}", ignore_error=True)
                idx = 0
                for _, addrs in groups.items():
                    val = ",".join(sorted(addrs)) + ",pcie=1"
                    self.app.run_ssh_cmd(f"qm set {self.vmid} --hostpci{idx} '{val}'")
                    idx += 1
                if vga: self.app.run_ssh_cmd(f"qm set {self.vmid} --vga {vga}")

                # 5. 仅当用户确实选了音频控制器才移除虚拟声卡, 避免冲突; 否则保留 audio0
                has_audio = any(self.tree.item(i, "values")[1] == "声卡" for i in self.tree.selection())
                if has_audio:
                    self.app.run_ssh_cmd(f"qm set {self.vmid} --delete audio0", ignore_error=True)

                # 6. OVMF 下若尚无 efidisk0, 自动创建一个, 消除 "no efidisk configured" 警告/临时启动盘
                if is_q35 and cur_bios == "ovmf" and not has_efidisk:
                    stor = "local-lvm"
                    out_s = self.app.run_ssh_cmd("pvesm status", ignore_error=True)
                    if "local-lvm" not in out_s:
                        stor = "local"
                    self.app.log(f"[*] 检测到 OVMF 但无 EFI 磁盘, 自动创建 efidisk0 ({stor}:1,efitype=4m)...")
                    self.app.run_ssh_cmd(f"qm set {self.vmid} --efidisk0 {stor}:1,efitype=4m,pre-enrolled-keys=1", ignore_error=True)

                self.app.log(f"[+] VM {self.vmid} 直通配置应用成功 (共 {idx} 个 IOMMU 组)! 显卡直通请完全关机后再开机。")
                self.after(0, self.destroy)
            except Exception as e:
                err_msg = str(e)
                self.app.log(f"[-] 配置失败: {err_msg}")
                try:
                    if self.winfo_exists():
                        self.after(0, lambda m=err_msg: messagebox.showerror("直通配置失败", m))
                except Exception:
                    pass
            finally:
                # 任务可能已自毁对话框(destroy), 此回调不能再碰已释放的控件, 否则 TclError
                try:
                    if self.winfo_exists():
                        self.after(0, lambda: self.btn_apply.config(state="normal"))
                except Exception:
                    pass
        threading.Thread(target=task, daemon=True).start()
