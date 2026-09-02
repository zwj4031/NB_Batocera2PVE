def center_window(win, parent=None, width=480, height=360):
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
import paramiko
import re
import socket
import shlex
from concurrent.futures import ThreadPoolExecutor

class BatoceraNetworkDialog(tk.Toplevel):
    def __init__(self, parent, app, vmid):
        super().__init__(parent)
        self.app = app
        self.vmid = vmid
        self.cur_bato_ip = ""
        self.title(f"🌐 Batocera 虚拟机网络配置 (VM: {vmid})")
        center_window(self, parent, 480, 360)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        frame = tk.Frame(self, padx=15, pady=15)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text=f"⚙️ 虚拟机 {vmid} 网络设置 (自动透传连接)", font=("", 11, "bold"), fg="#1e90ff").pack(anchor="w", pady=(0, 10))

        # 参数配置框 (已去除繁琐多余的重复登录框)
        f_cfg = tk.LabelFrame(frame, text="目标网络参数", padx=10, pady=8)
        f_cfg.pack(fill="x", pady=5)

        self.var_mode = tk.StringVar(value="static")
        tk.Radiobutton(f_cfg, text="静态 IP 模式 (推荐)", variable=self.var_mode, value="static", command=self.on_mode_change).grid(row=0, column=0, sticky="w", columnspan=2)
        tk.Radiobutton(f_cfg, text="DHCP 自动获取", variable=self.var_mode, value="dhcp", command=self.on_mode_change).grid(row=0, column=2, sticky="w", columnspan=2)

        tk.Label(f_cfg, text="虚拟机 IP:").grid(row=1, column=0, sticky="e", pady=4)
        self.entry_ip = tk.Entry(f_cfg, width=18)
        self.entry_ip.grid(row=1, column=1, padx=5, pady=4, sticky="w")

        tk.Label(f_cfg, text="掩码/前缀:").grid(row=1, column=2, sticky="e", pady=4)
        self.entry_mask = tk.Entry(f_cfg, width=8)
        self.entry_mask.insert(0, "24")
        self.entry_mask.grid(row=1, column=3, padx=5, pady=4, sticky="w")

        tk.Label(f_cfg, text="默认网关:").grid(row=2, column=0, sticky="e", pady=4)
        self.entry_gw = tk.Entry(f_cfg, width=18)
        self.entry_gw.grid(row=2, column=1, padx=5, pady=4, sticky="w")

        tk.Label(f_cfg, text="首选 DNS:").grid(row=3, column=0, sticky="e", pady=4)
        self.entry_dns = tk.Entry(f_cfg, width=18)
        self.entry_dns.insert(0, "223.5.5.5")
        self.entry_dns.grid(row=3, column=1, padx=5, pady=4, sticky="w")

        tk.Label(f_cfg, text="备用 DNS:").grid(row=3, column=2, sticky="e", pady=4)
        self.entry_dns2 = tk.Entry(f_cfg, width=10)
        self.entry_dns2.insert(0, "114.114.114.114")
        self.entry_dns2.grid(row=3, column=3, padx=5, pady=4, sticky="w")

        # 状态栏
        self.lbl_status = tk.Label(frame, text="状态: 正在深度探测虚拟机 IPv4 地址...", fg="blue")
        self.lbl_status.pack(anchor="w", pady=8)

        # 底部按钮
        f_btns = tk.Frame(frame)
        f_btns.pack(fill="x", pady=5)

        self.btn_ping = tk.Button(f_btns, text="📶 测试外网连通性", bg="lightblue", command=self.test_ping)
        self.btn_ping.pack(side="left", fill="x", expand=True, padx=2)

        self.btn_apply = tk.Button(f_btns, text="🚀 应用配置并热重启网卡", bg="#ff9900", fg="white", font=("", 9, "bold"), command=self.apply_network)
        self.btn_apply.pack(side="right", fill="x", expand=True, padx=2)

        self.after(100, self.auto_fill)

    def on_mode_change(self):
        state = "disabled" if self.var_mode.get() == "dhcp" else "normal"
        self.entry_ip.config(state=state)
        self.entry_mask.config(state=state)
        self.entry_gw.config(state=state)
        self.entry_dns.config(state=state)
        self.entry_dns2.config(state=state)

    def auto_fill(self):
        if not self.app.ssh: return
        def task():
            try:
                # 1. 获取网卡 MAC
                cfg = self.app.run_ssh_cmd(f"qm config {self.vmid}", ignore_error=True)
                mac_match = re.search(r"net0:[^\n]*?([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", cfg)
                target_ip = ""
                
                if mac_match:
                    mac = mac_match.group(1).lower()
                    # 2. 深度主动探针：向局域网广播 ping 刷新 PVE ARP 缓存
                    self.app.run_ssh_cmd("ping -c 1 -w 1 255.255.255.255 2>/dev/null || true", ignore_error=True)
                    
                    neigh = self.app.run_ssh_cmd("ip neigh show", ignore_error=True)
                    for line in neigh.split('\n'):
                        if mac in line.lower():
                            parts = line.split()
                            if parts and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0]):
                                target_ip = parts[0]
                                break
                
                def update(ip):
                    if ip:
                        self.cur_bato_ip = ip
                        self.entry_ip.delete(0, tk.END)
                        self.entry_ip.insert(0, ip)
                        # 自动生成匹配的网关 (如 192.168.0.1)
                        gw = ".".join(ip.split(".")[:-1]) + ".1"
                        self.entry_gw.delete(0, tk.END)
                        self.entry_gw.insert(0, gw)
                        self.lbl_status.config(text=f"[+] 自动定位到当前 IPv4: {ip}", fg="green")
                    else:
                        # 备用方案：自动带入 PVE 同网段的一个建议 IP
                        pve_ip = self.app.entry_ip.get().strip()
                        suggest_ip = ".".join(pve_ip.split(".")[:-1]) + ".150"
                        suggest_gw = ".".join(pve_ip.split(".")[:-1]) + ".1"
                        self.entry_ip.insert(0, suggest_ip)
                        self.entry_gw.insert(0, suggest_gw)
                        self.lbl_status.config(text="[*] 未检测到已分配IP，已自动填入同网段推荐静态IP", fg="#555")
                self.after(0, lambda: update(target_ip))
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.lbl_status.config(text=f"[-] 检索失败: {msg}", fg="red"))
        threading.Thread(target=task, daemon=True).start()

    def get_ssh(self):
        # 优先使用检测到的 IP 或手动输入的 IP，密码全自动取 Batocera 默认值 linux
        ip = self.cur_bato_ip or self.entry_ip.get().strip()
        if not ip:
            messagebox.showwarning("提示", "未找到有效的虚拟机 IP 地址！")
            return None
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=ip, port=22, username="root", password="linux", timeout=10, banner_timeout=30, auth_timeout=30)
        return ssh

    def test_ping(self):
        self.lbl_status.config(text="[*] 正在测试外网 (Ping 223.5.5.5 / 百度)...", fg="blue")
        def task():
            try:
                ssh = self.get_ssh()
                if not ssh: return
                stdin, stdout, stderr = ssh.exec_command("ping -c 2 223.5.5.5 && curl -I -m 3 https://www.baidu.com")
                out = stdout.read().decode('utf-8', errors='ignore')
                ssh.close()
                if "2 packets transmitted, 2 received" in out or "200 OK" in out or "HTTP/" in out:
                    self.after(0, lambda: self.lbl_status.config(text="[+] 🎉 外网连接畅通！可以正常使用 Sunshine！", fg="green"))
                else:
                    self.after(0, lambda: self.lbl_status.config(text="[-] ⚠️ 无法访问外网！请检查网关和 DNS 配置！", fg="red"))
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.lbl_status.config(text=f"[-] 测试失败: {msg}", fg="red"))
        threading.Thread(target=task, daemon=True).start()

    def apply_network(self):
        mode = self.var_mode.get()
        ip = self.entry_ip.get().strip()
        mask = self.entry_mask.get().strip()
        gw = self.entry_gw.get().strip()
        dns1 = self.entry_dns.get().strip()
        dns2 = self.entry_dns2.get().strip()

        self.lbl_status.config(text="[*] 正在写入网络配置并热重启网卡...", fg="blue")
        def task():
            try:
                ssh = self.get_ssh()
                if not ssh: return

                if mode == "dhcp":
                    cmd = "/etc/init.d/S40network restart"
                    ssh.exec_command(cmd)
                    ssh.close()
                else:
                    # 动态探测当前主网卡名称 (兜底 eth0), 兼容 virtio(enpXsY)/直通等命名
                    try:
                        _, probe_out, _ = ssh.exec_command(
                            "ip -o -4 route show to default | awk '{print $5}' | head -1")
                        nic = probe_out.read().decode("utf-8", "ignore").strip() or "eth0"
                    except Exception:
                        nic = "eth0"
                    # 组装脚本: IP/路由/resolv 应用 + custom.sh 持久化, 全部拼进复合命令。
                    # 注意: 切换静态 IP 会瞬间掐断当前 SSH 会话, 故用 nohup 放入后台,
                    # 保证即使连接断开, 网卡重启与 custom.sh 写入仍在 batocera 侧完整落地。
                    build = [
                        "mkdir -p /userdata/system",
                        "cat > /userdata/system/custom.sh <<'EOF'\n"
                        "#!/bin/bash\n"
                        f"ip route add default via {gw} dev {nic} 2>/dev/null || true\n"
                        f"echo 'nameserver {dns1}' > /etc/resolv.conf\n"
                        f"echo 'nameserver {dns2}' >> /etc/resolv.conf\n"
                        "EOF\n"
                        "chmod +x /userdata/system/custom.sh",
                        f"ip addr flush dev {nic} 2>/dev/null || true",
                        f"ip addr add {ip}/{mask} dev {nic} 2>/dev/null || true",
                        f"ip link set {nic} up 2>/dev/null || true",
                        f"ip route add default via {gw} dev {nic} 2>/dev/null || ip route change default via {gw} dev {nic} 2>/dev/null || true",
                        f"echo 'nameserver {dns1}' > /etc/resolv.conf",
                        f"echo 'nameserver {dns2}' >> /etc/resolv.conf",
                    ]
                    script = " && ".join(build)
                    # 转义后包进 nohup sh -c 后台执行, 隔离于本 SSH 会话生命周期
                    quoted = shlex.quote(script)
                    ssh.exec_command(f"nohup sh -c {quoted} >/dev/null 2>&1 &")
                    ssh.close()
                self.cur_bato_ip = ip
                self.after(0, lambda: self.lbl_status.config(text=f"[+] 网络已配置并重启！新 IP: {ip if mode == 'static' else 'DHCP'}", fg="green"))
                messagebox.showinfo("成功", "网络配置已成功应用并重启生效！")
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda msg=err_msg: self.lbl_status.config(text=f"[-] 配置失败: {msg}", fg="red"))
        threading.Thread(target=task, daemon=True).start()

def detect_vm_ip(app, vmid):
    """按 net0 MAC 反查虚拟机 IPv4。四级策略, 返回 IP 字符串或空串:
    1) 优先读取持久化特征库; 2) 命中主界面 vm_ip_info; 3) PVE ARP 表; 4) 子网 22 端口指纹探针。"""
    vmid = str(vmid)
    try:
        import pve_net_config
        c_info = pve_net_config.ConfigManager.get_vm_info(vmid)
        if c_info.get("ip"):
            return c_info["ip"]
    except Exception:
        pass
    if not app.ssh:
        return ""
    # 2) 复用主界面 VM 列表已解析结果
    try:
        cached = getattr(app, "vm_ip_info", None)
        if cached and cached.get(vmid):
            return cached[vmid]
    except Exception:
        pass
    # 2) PVE ARP: 取 net0 MAC, 对 PVE 各网口子网发定向广播 ping 刷新后再匹配
    try:
        cfg = app.run_ssh_cmd(f"qm config {vmid}", ignore_error=True)
        mac_match = re.search(r"net\d+:\s*[^\s,]*,?.*?([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})", cfg)
        if mac_match:
            mac = mac_match.group(1).lower()
            pve_ips = re.findall(r"(\d+\.\d+\.\d+\.\d+)",
                                 app.run_ssh_cmd("hostname -I 2>/dev/null", ignore_error=True))
            for ip in pve_ips:
                sub = ".".join(ip.split(".")[:3]) + ".255"
                app.run_ssh_cmd(f"ping -b -c 2 -w 2 {sub} >/dev/null 2>&1; true", ignore_error=True)
            neigh = app.run_ssh_cmd("ip neigh show", ignore_error=True)
            for line in neigh.split('\n'):
                if mac in line.lower():
                    parts = line.split()
                    if parts and re.match(r"^\d+\.\d+\.\d+\.\d+$", parts[0]):
                        return parts[0]
    except Exception:
        pass
    # 3) 兜底: 以 PVE 宿主子网扫 22 端口 (与部署对话框 auto_detect_ip 同款, 已稳定可用)
    return _scan_subnet_for_bato(app)

def _scan_subnet_for_bato(app):
    """子网 22 端口扫描: 找到 Batocera(root/linux) 即返回其 IP, 找不到返回空串。"""
    pve_ip = ""
    try:
        pve_ip = app.entry_ip.get().strip()
    except Exception:
        pass
    if not pve_ip:
        m = re.findall(r"(\d+\.\d+\.\d+\.\d+)",
                       app.run_ssh_cmd("hostname -I 2>/dev/null", ignore_error=True))
        pve_ip = m[0] if m else ""
    if not pve_ip:
        return ""
    subnet = ".".join(pve_ip.split('.')[:-1])
    found = []

    def test_ip(i):
        ip = f"{subnet}.{i}"
        if ip == pve_ip:
            return
        try:
            with socket.create_connection((ip, 22), timeout=0.2):
                t = paramiko.Transport((ip, 22))
                t.banner_timeout = 8
                t.auth_timeout = 8
                t.connect(username="root", password="linux")
                t.close()
                found.append(ip)
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=50) as ex:
        for i in range(1, 255):
            ex.submit(test_ip, i)
    return found[0] if found else ""
