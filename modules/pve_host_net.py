def center_window(win, parent=None, width=560, height=520):
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

class PveHostNetworkDialog(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("🌐 PVE 宿主机全局网络配置 (高危)")
        center_window(self, parent, 560, 520)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = tk.Frame(self, padx=12, pady=12)
        frame.pack(fill="both", expand=True)

        # 1. 醒目的高危警示横幅
        f_warn = tk.Frame(frame, bg="#fff3cd", relief="solid", bd=1, padx=10, pady=8)
        f_warn.pack(fill="x", pady=(0, 10))
        tk.Label(f_warn, text="⚠️ 高危操作警告与免责声明", font=("", 10, "bold"), fg="#856404", bg="#fff3cd").pack(anchor="w")
        tk.Label(f_warn, text="修改 PVE 宿主机全局网桥、IP、子网掩码或网关可能导致 PVE 宿主机彻底断网、SSH 连接中断以及 Web 管理后台无法打开！\n保存时工具将自动为您在 PVE 服务器上创建备份文件。",
                 font=("", 8), fg="#856404", bg="#fff3cd", justify="left", wraplength=520).pack(anchor="w", pady=(2, 0))

        # 2. 网络参数表单
        f_form = tk.LabelFrame(frame, text="PVE 宿主机网络接口配置 (/etc/network/interfaces)", padx=10, pady=8)
        f_form.pack(fill="both", expand=True, pady=5)

        # 网桥名称
        tk.Label(f_form, text="管理网桥:").grid(row=0, column=0, sticky="e", pady=4)
        self.entry_iface = tk.Entry(f_form, width=20)
        self.entry_iface.insert(0, "vmbr0")
        self.entry_iface.grid(row=0, column=1, sticky="w", padx=5)

        # IP/掩码
        tk.Label(f_form, text="PVE 宿主机 IPv4/CIDR:").grid(row=1, column=0, sticky="e", pady=4)
        self.entry_ip = tk.Entry(f_form, width=20)
        self.entry_ip.grid(row=1, column=1, sticky="w", padx=5)
        tk.Label(f_form, text="(如: 192.168.0.222/24)", fg="gray").grid(row=1, column=2, sticky="w")

        # 默认网关
        tk.Label(f_form, text="默认网关 (Gateway):").grid(row=2, column=0, sticky="e", pady=4)
        self.entry_gw = tk.Entry(f_form, width=20)
        self.entry_gw.grid(row=2, column=1, sticky="w", padx=5)
        tk.Label(f_form, text="(如: 192.168.0.1)", fg="gray").grid(row=2, column=2, sticky="w")

        # 绑定物理网卡
        tk.Label(f_form, text="绑定的物理网卡端口:").grid(row=3, column=0, sticky="e", pady=4)
        self.entry_ports = tk.Entry(f_form, width=20)
        self.entry_ports.grid(row=3, column=1, sticky="w", padx=5)
        tk.Label(f_form, text="(如: eth0, enp3s0)", fg="gray").grid(row=3, column=2, sticky="w")

        # DNS 1
        tk.Label(f_form, text="宿主机首选 DNS:").grid(row=4, column=0, sticky="e", pady=4)
        self.entry_dns1 = tk.Entry(f_form, width=20)
        self.entry_dns1.insert(0, "223.5.5.5")
        self.entry_dns1.grid(row=4, column=1, sticky="w", padx=5)

        # DNS 2
        tk.Label(f_form, text="宿主机备用 DNS:").grid(row=5, column=0, sticky="e", pady=4)
        self.entry_dns2 = tk.Entry(f_form, width=20)
        self.entry_dns2.insert(0, "114.114.114.114")
        self.entry_dns2.grid(row=5, column=1, sticky="w", padx=5)

        # 状态指示
        self.lbl_status = tk.Label(frame, text="状态: 正在读取宿主机当前网络配置...", fg="blue")
        self.lbl_status.pack(anchor="w", pady=4)

        # 底部按钮
        f_btns = tk.Frame(frame)
        f_btns.pack(fill="x", pady=6)

        self.btn_reload = tk.Button(f_btns, text="🔄 重新拉取当前配置", bg="lightblue", command=self.load_host_network)
        self.btn_reload.pack(side="left", padx=2)

        self.btn_apply = tk.Button(f_btns, text="🚨 确认无误，写入并应用网络 (高危)", bg="#dc3545", fg="white", font=("", 9, "bold"), command=self.apply_host_network)
        self.btn_apply.pack(side="right", padx=2)

        self.after(100, self.load_host_network)

    def load_host_network(self):
        if not self.app.ssh:
            self.lbl_status.config(text="[-] PVE SSH 未连接！", fg="red")
            return
        
        self.lbl_status.config(text="[*] 正在解析 PVE /etc/network/interfaces 及 DNS...", fg="blue")
        def task():
            try:
                # 读取 interfaces 文件
                net_cfg = self.app.run_ssh_cmd("cat /etc/network/interfaces", ignore_error=True)
                dns_cfg = self.app.run_ssh_cmd("cat /etc/resolv.conf", ignore_error=True)

                # 解析 vmbr0
                ip_match = re.search(r"iface\s+vmbr0\s+inet\s+static[^\n]*?\n(?:[^\n]*?\n)*?\s+address\s+([^\n\s]+)", net_cfg)
                gw_match = re.search(r"iface\s+vmbr0\s+inet\s+static[^\n]*?\n(?:[^\n]*?\n)*?\s+gateway\s+([^\n\s]+)", net_cfg)
                ports_match = re.search(r"bridge-ports\s+([^\n]+)", net_cfg)
                
                # 解析 DNS
                dns_matches = re.findall(r"nameserver\s+([^\n\s]+)", dns_cfg)

                def update():
                    if ip_match:
                        self.entry_ip.delete(0, tk.END)
                        self.entry_ip.insert(0, ip_match.group(1).strip())
                    if gw_match:
                        self.entry_gw.delete(0, tk.END)
                        self.entry_gw.insert(0, gw_match.group(1).strip())
                    if ports_match:
                        self.entry_ports.delete(0, tk.END)
                        self.entry_ports.insert(0, ports_match.group(1).strip())
                    if dns_matches:
                        self.entry_dns1.delete(0, tk.END)
                        self.entry_dns1.insert(0, dns_matches[0].strip())
                        if len(dns_matches) > 1:
                            self.entry_dns2.delete(0, tk.END)
                            self.entry_dns2.insert(0, dns_matches[1].strip())
                    self.lbl_status.config(text="[+] 成功解析 PVE 宿主机当前网络配置！", fg="green")

                self.after(0, update)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.lbl_status.config(text=f"[-] 解析失败: {msg}", fg="red"))

        threading.Thread(target=task, daemon=True).start()

    def apply_host_network(self):
        iface = self.entry_iface.get().strip()
        ip = self.entry_ip.get().strip()
        gw = self.entry_gw.get().strip()
        ports = self.entry_ports.get().strip()
        dns1 = self.entry_dns1.get().strip()
        dns2 = self.entry_dns2.get().strip()

        if not ip or not gw:
            messagebox.showwarning("提示", "IP 地址和网关不能为空！")
            return

        # 二次强风险确认
        warn_text = (
            f"您即将修改 PVE 宿主机全局网络配置！\n\n"
            f"目标接口: {iface}\n"
            f"新 IP/CIDR: {ip}\n"
            f"新网关: {gw}\n"
            f"绑定物理网卡: {ports}\n\n"
            f"⚠️ 请再次确认配置是否正确，如果填写错误可能导致 PVE 宿主机永久失联！\n"
            f"是否继续应用？"
        )
        if not messagebox.askyesno("🚨 最终高危确认", warn_text, icon="warning"):
            return

        self.btn_apply.config(state="disabled")
        self.lbl_status.config(text="[*] 正在自动创建备份并应用新网络配置...", fg="blue")

        def task():
            try:
                # 1. 创建自动备份
                self.app.run_ssh_cmd("cp /etc/network/interfaces /etc/network/interfaces.bak_$(date +%Y%m%d_%H%M%S)")
                
                # 2. 生成新的 interfaces 配置文件内容
                new_interfaces = f"""auto lo
iface lo inet loopback

iface {ports} inet manual

auto {iface}
iface {iface} inet static
	address {ip}
	gateway {gw}
	bridge-ports {ports}
	bridge-stp off
	bridge-fd 0
"""
                # 3. 写入文件
                sftp = self.app.ssh.open_sftp()
                with sftp.file("/etc/network/interfaces", "w") as f:
                    f.write(new_interfaces)
                sftp.close()

                # 4. 更新 DNS
                dns_content = f"nameserver {dns1}\nnameserver {dns2}\n" if dns2 else f"nameserver {dns1}\n"
                sftp = self.app.ssh.open_sftp()
                with sftp.file("/etc/resolv.conf", "w") as f:
                    f.write(dns_content)
                sftp.close()

                # 4.1 同步更新 /etc/hosts: PVE 的管理地址(IP)来自 hostname->IP 映射,
                # 仅改 interfaces 不改 hosts 会导致重启后盒子实际 IP 已变, 但 hostname 仍解析到旧 IP,
                # 从而 Web 界面显示的地址仍是旧 IP。
                host_ip = ip.split("/")[0]
                host_name = (self.app.run_ssh_cmd("hostname", ignore_error=True) or "pve").strip().splitlines()[0] or "pve"
                self.app.run_ssh_cmd("cp /etc/hosts /etc/hosts.bak_$(date +%Y%m%d_%H%M%S)")
                hosts_content = (
                    "127.0.0.1 localhost.localdomain localhost\n"
                    f"{host_ip} {host_name}.local {host_name}\n"
                )
                sftp = self.app.ssh.open_sftp()
                with sftp.file("/etc/hosts", "w") as f:
                    f.write(hosts_content)
                sftp.close()

                # 5. 重载网络
                self.app.run_ssh_cmd("ifreload -a || systemctl restart networking 2>/dev/null || true", ignore_error=True)
                
                self.after(0, lambda: self.lbl_status.config(text="[+] 🎉 PVE 宿主机网络已更新并重载！", fg="green"))
                self.after(0, lambda: messagebox.showinfo("完成", f"PVE 网络配置已更新！\n若更改了 IP，请使用新 IP ({ip.split('/')[0]}) 重新连接 PVE。"))
                self.after(0, self.destroy)
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.lbl_status.config(text=f"[-] 应用失败: {msg}", fg="red"))
            finally:
                self.after(0, lambda: self.btn_apply.config(state="normal"))

        threading.Thread(target=task, daemon=True).start()
