def center_window(win, parent=None, width=560, height=540):
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

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import re
from pve_machine import normalize_pve_machine

class CreateVmDialog(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("➕ 新建虚拟机 (支持 Batocera 一键模板)")
        center_window(self, parent, 660, 580)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = tk.Frame(self, padx=15, pady=12)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="➕ 新建 PVE 虚拟机", font=("", 11, "bold"), fg="#1e90ff").pack(anchor="w", pady=(0, 6))

        # 1. 模板选择卡
        f_tpl = tk.LabelFrame(frame, text="🚀 快速预设模板选择", padx=10, pady=6)
        f_tpl.pack(fill="x", pady=4)

        self.var_tpl = tk.StringVar(value="batocera")
        tk.Radiobutton(f_tpl, text="🎮 Batocera 游戏机一键模板 (预设最佳声显与引导参数)", variable=self.var_tpl, value="batocera", font=("", 9, "bold"), fg="#28a745", command=self.apply_template).grid(row=0, column=0, sticky="w", pady=2)
        tk.Radiobutton(f_tpl, text="🛠️ 通用自定义空白虚拟机 (Linux / Windows / 其他)", variable=self.var_tpl, value="custom", command=self.apply_template).grid(row=1, column=0, sticky="w", pady=2)

        # 2. 核心硬件表单
        f_form = tk.LabelFrame(frame, text="虚拟机基础配置", padx=10, pady=8)
        f_form.pack(fill="both", expand=True, pady=6)

        # VMID 与 自动分配
        tk.Label(f_form, text="虚拟机 ID (VMID):").grid(row=0, column=0, sticky="e", pady=4)
        f_vmid = tk.Frame(f_form)
        f_vmid.grid(row=0, column=1, sticky="w", padx=5)
        self.entry_vmid = tk.Entry(f_vmid, width=8, font=("", 9, "bold"))
        self.entry_vmid.insert(0, "100")
        self.entry_vmid.pack(side="left")
        self.btn_calc_id = tk.Button(f_vmid, text="🔄 自动分配下一ID", command=self.calc_next_vmid)
        self.btn_calc_id.pack(side="left", padx=4)

        tk.Label(f_form, text="虚拟机名称:").grid(row=0, column=2, sticky="e", pady=4)
        self.entry_name = tk.Entry(f_form, width=14)
        self.entry_name.insert(0, "Batocera")
        self.entry_name.grid(row=0, column=3, sticky="w", padx=5)

        # OS 类型 与 网卡
        tk.Label(f_form, text="操作系统类型:").grid(row=1, column=0, sticky="e", pady=4)
        self.combo_ostype = ttk.Combobox(f_form, values=["l26", "win11", "win10", "other"], width=14, state="readonly")
        self.combo_ostype.set("l26")
        self.combo_ostype.grid(row=1, column=1, sticky="w", padx=5)

        tk.Label(f_form, text="网络桥接 (Bridge):").grid(row=1, column=2, sticky="e", pady=4)
        self.entry_bridge = tk.Entry(f_form, width=14)
        self.entry_bridge.insert(0, "vmbr0")
        self.entry_bridge.grid(row=1, column=3, sticky="w", padx=5)

        # CPU 配置
        tk.Label(f_form, text="CPU 插槽 (Sockets):").grid(row=2, column=0, sticky="e", pady=4)
        self.entry_sockets = tk.Entry(f_form, width=8)
        self.entry_sockets.insert(0, "1")
        self.entry_sockets.grid(row=2, column=1, sticky="w", padx=5)

        tk.Label(f_form, text="CPU 核心数 (Cores):").grid(row=2, column=2, sticky="e", pady=4)
        self.entry_cores = tk.Entry(f_form, width=14)
        self.entry_cores.insert(0, "2")
        self.entry_cores.grid(row=2, column=3, sticky="w", padx=5)

        tk.Label(f_form, text="CPU 架构类型:").grid(row=3, column=0, sticky="e", pady=4)
        self.combo_cpu = ttk.Combobox(f_form, values=["host", "kvm64", "qemu64", "max", "x86-64-v2-AES"], width=14, state="readonly")
        self.combo_cpu.set("host")
        self.combo_cpu.grid(row=3, column=1, sticky="w", padx=5)

        # 内存
        tk.Label(f_form, text="内存 (RAM MB):").grid(row=3, column=2, sticky="e", pady=4)
        self.entry_mem = tk.Entry(f_form, width=14)
        self.entry_mem.insert(0, "2048")
        self.entry_mem.grid(row=3, column=3, sticky="w", padx=5)

        # 引导与机型
        tk.Label(f_form, text="BIOS 引导模式:").grid(row=4, column=0, sticky="e", pady=4)
        self.combo_bios = ttk.Combobox(f_form, values=["ovmf", "seabios"], width=14, state="readonly")
        self.combo_bios.set("ovmf")
        self.combo_bios.grid(row=4, column=1, sticky="w", padx=5)

        tk.Label(f_form, text="主板架构机型:").grid(row=4, column=2, sticky="e", pady=4)
        self.combo_machine = ttk.Combobox(f_form, values=["q35", "i440fx"], width=14, state="readonly")
        self.combo_machine.set("q35")
        self.combo_machine.grid(row=4, column=3, sticky="w", padx=5)
        self.lbl_machine_warn = tk.Label(f_form, text="", fg="#b8860b", font=("Microsoft YaHei UI", 9))
        self.lbl_machine_warn.grid(row=5, column=0, columnspan=5, sticky="w", padx=5, pady=(2, 6))
        self.combo_machine.bind("<<ComboboxSelected>>", lambda e: self._update_machine_warn())
        self._update_machine_warn()

        # 显卡与附加参数
        tk.Label(f_form, text="显卡类型 (VGA):").grid(row=6, column=0, sticky="e", pady=4)
        self.combo_vga = ttk.Combobox(f_form, values=["virtio", "virtio-gl", "std", "none", "qxl", "vmware"], width=14, state="readonly")
        self.combo_vga.set("virtio")
        self.combo_vga.grid(row=6, column=1, sticky="w", padx=5)

        tk.Label(f_form, text="VNC底层参数 (args):").grid(row=6, column=2, sticky="e", pady=4)
        self.entry_args = tk.Entry(f_form, width=20)
        self.entry_args.insert(0, "-vnc 0.0.0.0:99")
        self.entry_args.grid(row=6, column=3, sticky="w", padx=5)

        # 状态指示与提交按钮
        self.lbl_status = tk.Label(frame, text="状态: 正在自动计算下一可用 VMID...", fg="blue")
        self.lbl_status.pack(anchor="w", pady=4)

        f_btns = tk.Frame(frame)
        f_btns.pack(fill="x", pady=4)

        self.btn_submit = tk.Button(f_btns, text="🚀 立即创建虚拟机", bg="#28a745", fg="white", font=("", 10, "bold"), command=self.create_vm_task)
        self.btn_submit.pack(side="left", fill="x", expand=True, padx=2)

        self.btn_cancel = tk.Button(f_btns, text="取消", width=10, command=self.destroy)
        self.btn_cancel.pack(side="right", padx=2)

        self.after(100, self.calc_next_vmid)

    def _update_machine_warn(self):
        val, warn = normalize_pve_machine(self.combo_machine.get())
        if val is None:
            self.lbl_machine_warn.config(text="⚠ " + warn, fg="red")
        elif warn:
            self.lbl_machine_warn.config(text="⚠ " + warn, fg="#b8860b")
        else:
            self.lbl_machine_warn.config(text="✓ 合法机型", fg="green")

    def apply_template(self):
        tpl = self.var_tpl.get()
        if tpl == "batocera":
            self.entry_name.delete(0, tk.END); self.entry_name.insert(0, "Batocera")
            self.combo_ostype.set("l26")
            self.entry_cores.delete(0, tk.END); self.entry_cores.insert(0, "2")
            self.entry_sockets.delete(0, tk.END); self.entry_sockets.insert(0, "1")
            self.combo_cpu.set("host")
            self.entry_mem.delete(0, tk.END); self.entry_mem.insert(0, "2048")
            self.combo_bios.set("ovmf")
            self.combo_machine.set("q35")
            self.combo_vga.set("virtio")
            self.entry_args.delete(0, tk.END); self.entry_args.insert(0, "-vnc 0.0.0.0:99")
            self.lbl_status.config(text="[+] 已加载 Batocera 游戏机专属调优模板！", fg="green")
        else:
            self.entry_name.delete(0, tk.END); self.entry_name.insert(0, "New-VM")
            self.combo_ostype.set("l26")
            self.entry_cores.delete(0, tk.END); self.entry_cores.insert(0, "2")
            self.entry_sockets.delete(0, tk.END); self.entry_sockets.insert(0, "1")
            self.combo_cpu.set("kvm64")
            self.entry_mem.delete(0, tk.END); self.entry_mem.insert(0, "4096")
            self.combo_bios.set("ovmf")
            self.combo_machine.set("q35")
            self.combo_vga.set("std")
            self.entry_args.delete(0, tk.END)
            self.lbl_status.config(text="[*] 已切换为通用空白虚拟机模式", fg="#555")

    def calc_next_vmid(self):
        if not self.app.ssh: return
        def task():
            try:
                out = self.app.run_ssh_cmd("qm list", ignore_error=True)
                existing_ids = set()
                for line in out.strip().split('\n')[1:]:
                    parts = line.split()
                    if parts and parts[0].isdigit():
                        existing_ids.add(int(parts[0]))
                
                # 从 100 开始寻找最小未占用的 ID
                next_id = 100
                while next_id in existing_ids:
                    next_id += 1

                def update():
                    self.entry_vmid.delete(0, tk.END)
                    self.entry_vmid.insert(0, str(next_id))
                    self.entry_args.delete(0, tk.END)
                    self.entry_args.insert(0, f"-vnc 0.0.0.0:{next_id}")
                    self.lbl_status.config(text=f"[+] 自动推荐下一可用 VMID: {next_id} (VNC 端口 5900+{next_id})", fg="green")
                self.after(0, update)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.lbl_status.config(text=f"[-] ID查询失败: {msg}", fg="red"))
        threading.Thread(target=task, daemon=True).start()

    def create_vm_task(self):
        vmid = self.entry_vmid.get().strip()
        name = self.entry_name.get().strip()
        ostype = self.combo_ostype.get()
        bridge = self.entry_bridge.get().strip() or "vmbr0"
        sockets = self.entry_sockets.get().strip() or "1"
        cores = self.entry_cores.get().strip() or "2"
        cpu = self.combo_cpu.get()
        mem = self.entry_mem.get().strip() or "2048"
        bios = self.combo_bios.get()
        machine_raw = self.combo_machine.get()
        machine, machine_warn = normalize_pve_machine(machine_raw)
        if machine is None:
            messagebox.showerror("机型非法", machine_warn)
            return
        # UEFI (OVMF) 必须搭配 q35 机型, 自动纠正为 q35
        if machine and bios == "ovmf" and not machine.startswith("q35"):
            machine = "q35"
            machine_warn = None
        if machine_warn:
            messagebox.showwarning("机型联动提示", machine_warn)
        vga = self.combo_vga.get()
        args = self.entry_args.get().strip()
        is_bato = (self.var_tpl.get() == "batocera")
        # VNC 显示号固定为 VMID => 端口 5900+VMID, 每台虚拟机独立, 双击/右键连接据此端口精准命中
        if re.search(r'-vnc', args):
            args = re.sub(r'(-vnc\s+[0-9a-zA-Z.:]+)', f'-vnc 0.0.0.0:{vmid}', args)
        else:
            args = (args + f" -vnc 0.0.0.0:{vmid}").strip()

        if not vmid or not vmid.isdigit():
            messagebox.showwarning("提示", "请输入纯数字的有效 VMID！")
            return
        if not name:
            messagebox.showwarning("提示", "请输入虚拟机名称！")
            return

        # 构建 qm create 命令
        cmd = (
            f"qm create {vmid} --name '{name}' --memory {mem} --cores {cores} "
            f"--sockets {sockets} --cpu {cpu} --bios {bios} --machine {machine} "
            f"--ostype {ostype} --net0 virtio,bridge={bridge} --vga {vga}"
        )
        if args:
            cmd += f" --args '{args}'"
        if is_bato:
            cmd += " --boot c --bootdisk sata0"

        self.btn_submit.config(state="disabled")
        self.lbl_status.config(text=f"[*] 正在 PVE 宿主机上创建虚拟机 {vmid}...", fg="blue")

        def task():
            try:
                self.app.run_ssh_cmd(cmd)
                def on_success():
                    self.lbl_status.config(text=f"[+] 🎉 虚拟机 {vmid} ({name}) 创建成功！", fg="green")
                    messagebox.showinfo("成功", f"虚拟机 {vmid} ({name}) 已成功创建！\n\n可在主界面列表中右键管理，或在【镜像与存储部署】选项卡中挂载镜像。")
                    self.app.refresh_vms()
                    self.app.entry_vmid.delete(0, tk.END)
                    self.app.entry_vmid.insert(0, vmid)
                    self.destroy()
                self.after(0, on_success)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.lbl_status.config(text=f"[-] 创建失败: {msg}", fg="red"))
            finally:
                self.after(0, lambda: self.btn_submit.config(state="normal"))

        threading.Thread(target=task, daemon=True).start()
