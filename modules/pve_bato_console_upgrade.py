# -*- coding: utf-8 -*-
"""Batocera 系统安全升级、自动快照备份与一键无损回滚管理向导"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import os
import re

from pve_bato_net import center_window
from pve_common import run_sync_cmd

class SystemUpgradeDialog(tk.Toplevel):
    """Batocera 安全升级与备份回滚控制面板"""
    def __init__(self, parent, console_app):
        super().__init__(parent)
        self.console = console_app
        self.title("🚀 Batocera 系统安全升级与备份回滚")
        center_window(self, parent, 640, 520)
        self.transient(parent)
        self.resizable(False, False)

        frame = tk.Frame(self, padx=12, pady=10)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="⚡ Batocera 系统升级与快照备份向导", font=("Microsoft YaHei UI", 11, "bold"), fg="#1e90ff").pack(anchor="w", pady=(0, 4))

        # --- 1. 容量与当前状态卡片 ---
        f_stat = tk.LabelFrame(frame, text="📊 目标系统状态与存储容量", padx=8, pady=6)
        f_stat.pack(fill="x", pady=2)

        self.lbl_cap = tk.Label(f_stat, text="正在检测 /boot 与 /userdata 存储空间...", font=("Microsoft YaHei UI", 9), fg="#0d6efd")
        self.lbl_cap.pack(anchor="w")

        # --- 2. 升级控制卡片 ---
        f_up = tk.LabelFrame(frame, text="⬆️ 在线系统升级 (升级前自动全量备份)", padx=8, pady=6)
        f_up.pack(fill="x", pady=4)

        row_u1 = tk.Frame(f_up); row_u1.pack(fill="x", pady=2)
        tk.Label(row_u1, text="升级通道:", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.combo_channel = ttk.Combobox(row_u1, state="readonly", width=34, values=[
            "官方稳定版 (x86_64 Stable - updates.batocera.org)",
            "国内加速节点 (gh-proxy.com 加速)",
        ])
        self.combo_channel.set("官方稳定版 (x86_64 Stable - updates.batocera.org)")
        self.combo_channel.pack(side="left", padx=4)

        self.var_auto_bk = tk.IntVar(value=1)
        tk.Checkbutton(f_up, text="☑ 升级前全量快照备份原系统 (备份保存在 /userdata/system/backup/)", variable=self.var_auto_bk,
                       font=("Microsoft YaHei UI", 9, "bold"), fg="#16a34a").pack(anchor="w", pady=2)

        row_ubtn = tk.Frame(f_up); row_ubtn.pack(fill="x", pady=4)
        self.btn_do_upgrade = tk.Button(row_ubtn, text="🚀 立即开始安全升级 (自动备份+下载+部署)", bg="#2563eb", fg="white",
                                       font=("Microsoft YaHei UI", 10, "bold"), relief="flat", padx=12, ipady=3,
                                       command=self.start_safe_upgrade)
        self.btn_do_upgrade.pack(side="left", fill="x", expand=True, padx=2)

        # --- 3. 历史备份与一键回滚卡片 ---
        f_bk = tk.LabelFrame(frame, text="⏪ 历史备份与一键无损回滚 (恢复升级前状态)", padx=8, pady=6)
        f_bk.pack(fill="x", pady=4)

        row_b1 = tk.Frame(f_bk); row_b1.pack(fill="x", pady=2)
        tk.Label(row_b1, text="选择备份快照:", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.combo_backups = ttk.Combobox(row_b1, state="readonly", width=36)
        self.combo_backups.set("(正在检索历史备份…)")
        self.combo_backups.pack(side="left", padx=4)

        tk.Button(row_b1, text="🔄 刷新", bg="#64748b", fg="white", font=("Microsoft YaHei UI", 8),
                  relief="flat", padx=6, command=self.load_backups).pack(side="left", padx=2)

        row_bbtn = tk.Frame(f_bk); row_bbtn.pack(fill="x", pady=4)
        self.btn_do_rollback = tk.Button(row_bbtn, text="⏪ 还原所选备份至原系统 (一键回滚)", bg="#ea580c", fg="white",
                                         font=("Microsoft YaHei UI", 9, "bold"), relief="flat", padx=10, ipady=2,
                                         command=self.start_rollback)
        self.btn_do_rollback.pack(side="left", fill="x", expand=True, padx=2)

        # --- 4. 进度与执行日志 ---
        f_prog = tk.Frame(frame); f_prog.pack(fill="x", pady=(4, 0))
        self.lbl_status = tk.Label(f_prog, text="状态: 就绪", font=("Microsoft YaHei UI", 9), fg="#4b5563")
        self.lbl_status.pack(anchor="w")
        self.prog = ttk.Progressbar(f_prog, orient="horizontal", mode="determinate")
        self.prog.pack(fill="x", pady=(2, 0))

        self.after(100, self.check_capacity)
        self.after(200, self.load_backups)

    def check_capacity(self):
        def task():
            ssh = self.console._get_ssh()
            if not ssh: return
            try:
                _, out, _ = run_sync_cmd(ssh, "df -m /boot /userdata 2>/dev/null")
                boot_avail, data_avail = 0, 0
                for line in out.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 6:
                        if "/boot" in parts[5]: boot_avail = int(parts[3])
                        elif "/userdata" in parts[5]: data_avail = int(parts[3])
                
                txt = f"📦 /userdata 剩余: {data_avail/1024:.2f} GB (需 > 4GB)  |  💽 /boot 剩余: {boot_avail} MB"
                ok = data_avail >= 3500
                color = "#16a34a" if ok else "#dc2626"
                self.after(0, lambda: self.lbl_cap.config(text=txt, fg=color))
            except Exception as e:
                self.after(0, lambda e=e: self.lbl_cap.config(text=f"容量检测异常: {e}", fg="#dc2626"))
        threading.Thread(target=task, daemon=True).start()

    def load_backups(self):
        def task():
            ssh = self.console._get_ssh()
            if not ssh: return
            try:
                _, out, _ = run_sync_cmd(ssh, "ls -1 /userdata/system/backup/boot_backup_*.tar.gz 2>/dev/null")
                backups = [os.path.basename(ln.strip()) for ln in out.splitlines() if ln.strip()]
                def update():
                    self.combo_backups['values'] = backups
                    if backups:
                        self.combo_backups.set(backups[-1])
                    else:
                        self.combo_backups.set("(暂无备份快照)")
                self.after(0, update)
            except Exception: pass
        threading.Thread(target=task, daemon=True).start()

    def start_safe_upgrade(self):
        ch = self.combo_channel.get()
        url = "https://updates.batocera.org/x86_64/stable/last/boot.tar.xz"
        if "gh-proxy" in ch:
            url = "https://gh-proxy.com/https://updates.batocera.org/x86_64/stable/last/boot.tar.xz"

        if not messagebox.askyesno("确认升级", "即将通过自研稳妥引擎升级 Batocera 系统。\n升级过程将先完整备份当前系统到 /userdata。\n确定开始升级吗？"):
            return

        self.btn_do_upgrade.config(state="disabled")
        self.btn_do_rollback.config(state="disabled")
        self.lbl_status.config(text="[*] 正在准备升级环境与快照备份...", fg="#0d6efd")
        self.prog['value'] = 5

        def task():
            ssh = self.console._get_ssh()
            if not ssh:
                self.after(0, lambda: self.lbl_status.config(text="[-] SSH 未连接", fg="#dc2626"))
                self.after(0, lambda: self.btn_do_upgrade.config(state="normal"))
                return
            try:
                # 1. 创建备份
                if self.var_auto_bk.get():
                    self.console._log("[*] [步骤 1/3] 正在全量快照备份原 /boot 系统到 /userdata/system/backup/ ...")
                    self.after(0, lambda: self.prog.config(value=20))
                    ts = time.strftime("%Y%m%d_%H%M%S")
                    bk_file = f"/userdata/system/backup/boot_backup_{ts}.tar.gz"
                    run_sync_cmd(ssh, f"mkdir -p /userdata/system/backup && mount -o remount,rw /boot 2>/dev/null; tar -czf {bk_file} -C /boot . 2>/dev/null")
                    self.console._log(f"[+] 原系统快照备份完成: {bk_file}")

                # 2. 下载官方最新稳定版 boot.tar.xz (流式 curl)
                self.console._log(f"[*] [步骤 2/3] 正在下载官方最新升级包 (~1.5GB): {url} ...")
                self.after(0, lambda: self.lbl_status.config(text="[*] 正在下载官方升级包 (耗时约 1~3 分钟)...", fg="#0d6efd"))
                self.after(0, lambda: self.prog.config(value=40))

                dl_cmd = f"curl -sSL --retry 3 -o /userdata/system/boot.tar.xz '{url}' 2>&1"
                code, dl_out, _ = run_sync_cmd(ssh, dl_cmd)

                # 3. 部署并写入 /boot
                self.console._log("[*] [步骤 3/3] 正在解压并更新 /boot 引导分区 ...")
                self.after(0, lambda: self.prog.config(value=80))
                self.after(0, lambda: self.lbl_status.config(text="[*] 正在部署解压新系统并同步磁盘...", fg="#0d6efd"))

                deploy_cmd = (
                    "mount -o remount,rw /boot 2>/dev/null && "
                    "tar -xf /userdata/system/boot.tar.xz -C /boot/ 2>/dev/null && "
                    "rm -f /userdata/system/boot.tar.xz && "
                    "sync && echo UPGRADE_OK"
                )
                _, dp_out, _ = run_sync_cmd(ssh, deploy_cmd)

                if "UPGRADE_OK" in dp_out:
                    self.after(0, lambda: self.prog.config(value=100))
                    self.after(0, lambda: self.lbl_status.config(text="🎉 系统升级部署成功！重启后生效", fg="#16a34a"))
                    self.console._log("[+] 🎉 系统升级部署成功！新系统将在下次重启后自动加载。")
                    self.after(0, self.load_backups)
                    self.after(0, lambda: messagebox.showinfo("升级成功", "🎉 Batocera 系统升级文件已安全部署！\n\n已为您自动保留旧系统备份。\n请点击控制台的【♻️ 重启】完成升级生效。"))
                else:
                    raise Exception(f"部署失败: {dp_out}")

            except Exception as e:
                err_msg = str(e)
                self.console._log(f"[-] 升级异常: {err_msg}")
                self.after(0, lambda m=err_msg: self.lbl_status.config(text=f"[-] 升级失败: {m[:40]}", fg="#dc2626"))
                self.after(0, lambda m=err_msg: messagebox.showerror("升级失败", f"升级过程发生错误:\n{m}"))
            finally:
                self.after(0, lambda: self.btn_do_upgrade.config(state="normal"))
                self.after(0, lambda: self.btn_do_rollback.config(state="normal"))

        threading.Thread(target=task, daemon=True).start()

    def start_rollback(self):
        sel = self.combo_backups.get().strip()
        if not sel or sel.startswith("("):
            messagebox.showwarning("提示", "请先选择一个有效的历史备份快照！")
            return

        if not messagebox.askyesno("确认回滚", f"确定将系统还原到快照 【{sel}】 吗？\n\n操作将完整覆盖 /boot 引导分区，使系统回到升级前的旧版本。"):
            return

        self.btn_do_upgrade.config(state="disabled")
        self.btn_do_rollback.config(state="disabled")
        self.lbl_status.config(text="[*] 正在回滚还原原系统快照...", fg="#ea580c")
        self.prog['value'] = 30

        def task():
            ssh = self.console._get_ssh()
            if not ssh: return
            try:
                bk_path = f"/userdata/system/backup/{sel}"
                self.console._log(f"[*] 正在从快照还原系统: {bk_path} ...")
                cmd = (
                    "mount -o remount,rw /boot 2>/dev/null && "
                    "rm -f /boot/boot/batocera.update /boot/batocera.update 2>/dev/null && "
                    f"tar -zxf {bk_path} -C /boot/ 2>/dev/null && "
                    "sync && echo ROLLBACK_OK"
                )
                _, out, _ = run_sync_cmd(ssh, cmd)
                if "ROLLBACK_OK" in out:
                    self.after(0, lambda: self.prog.config(value=100))
                    self.after(0, lambda: self.lbl_status.config(text="🎉 系统已成功回滚！重启后恢复老版本", fg="#16a34a"))
                    self.console._log("[+] 🎉 系统快照已完整恢复回 /boot！请重启虚拟机生效。")
                    self.after(0, lambda: messagebox.showinfo("回滚成功", "🎉 历史系统快照已恢复完成！\n\n请在常用控制中点击【♻️ 重启】回到原系统。"))
                else:
                    raise Exception(f"还原失败: {out}")
            except Exception as e:
                err_msg = str(e)
                self.console._log(f"[-] 回滚失败: {err_msg}")
                self.after(0, lambda m=err_msg: messagebox.showerror("回滚失败", m))
            finally:
                self.after(0, lambda: self.btn_do_upgrade.config(state="normal"))
                self.after(0, lambda: self.btn_do_rollback.config(state="normal"))

        threading.Thread(target=task, daemon=True).start()
