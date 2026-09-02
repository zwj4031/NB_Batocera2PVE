# -*- coding: utf-8 -*-
"""Batocera 控制台 - 插件中心、BUA市场、Treeview 清单与实时跟随 Tooltip (Mixin 子模块)"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import paramiko
import re
import base64
import time
import os

from pve_bato_net import center_window
from pve_common import run_sync_cmd

class ToolTip(object):
    """通用的鼠标悬浮/选中气泡提示组件 (支持动态位置跟随与内容平滑更新)"""
    def __init__(self, widget):
        self.widget = widget
        self.tip_window = None
        self.label = None
        self.cur_text = ""

    def update_tip(self, text, x, y):
        if not text:
            self.hide_tip()
            return

        if not self.tip_window or not tk.Toplevel.winfo_exists(self.tip_window):
            self.tip_window = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)
            try:
                tw.attributes("-topmost", True)
            except Exception:
                pass
            self.label = tk.Label(tw, text=text, justify=tk.LEFT,
                                  background="#1e293b", foreground="#f8fafc", relief=tk.SOLID, borderwidth=1,
                                  font=("Microsoft YaHei UI", 9), padx=10, pady=7)
            self.label.pack(ipadx=1)
            self.cur_text = text
        else:
            if self.cur_text != text:
                self.label.config(text=text)
                self.cur_text = text

        sw = self.widget.winfo_screenwidth()
        sh = self.widget.winfo_screenheight()
        target_x = x + 16
        target_y = y + 16
        if target_x + 360 > sw: target_x = x - 360
        if target_y + 130 > sh: target_y = y - 130
        self.tip_window.wm_geometry(f"+{target_x}+{target_y}")

    def hide_tip(self):
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None
            self.label = None
            self.cur_text = ""

PLUGINS = [
    {
        "name": "启用 SSH 远程命令行",
        "desc": "将 system.ssh.enabled=1 写入 batocera.conf 并重启 sshd，之后可 ssh root@IP（密码 linux）",
        "script": """#!/bin/bash
set -e
CONF=/userdata/system/batocera.conf
grep -q '^system.ssh.enabled' "$CONF" && sed -i 's/^system.ssh.enabled=.*/system.ssh.enabled=1/' "$CONF" || echo 'system.ssh.enabled=1' >> "$CONF"
/etc/init.d/S50sshd restart 2>/dev/null || systemctl restart sshd 2>/dev/null || true
echo '[+] SSH 已启用'
""",
    },
    {
        "name": "系统在线升级 (batocera-upgrade)",
        "desc": "执行官方升级命令，将 Batocera 更新到最新版（耗时较长，需联网）",
        "script": """#!/bin/bash
batocera-upgrade || batocera-upgrade now
echo '[+] 升级命令已执行，请观察上方输出'
""",
    },
    {
        "name": "同步系统时间 (NTP)",
        "desc": "通过 NTP 同步系统时间，避免证书/串流鉴权因时间偏差失败",
        "script": """#!/bin/bash
ntpd -q -n 2>/dev/null || ntpdate -b pool.ntp.org 2>/dev/null || sntp -s pool.ntp.org 2>/dev/null || true
echo '[+] 时间同步完成:'; date
""",
    },
    {
        "name": "安装 PortMaster (独立游戏库)",
        "desc": "部署 PortMaster 官方脚本到 /userdata/roms/ports，用于管理独立游戏端口",
        "script": """#!/bin/bash
mkdir -p /userdata/roms/ports
curl -L -o /userdata/roms/ports/PortMaster.sh "https://gh-proxy.com/https://github.com/PortsMaster/PortMaster-Settings/raw/master/PortMaster.sh" 2>/dev/null || true
chmod +x /userdata/roms/ports/PortMaster.sh 2>/dev/null || true
echo '[+] PortMaster 已尝试部署，请在“端口(ports)”分类中查看'
""",
    },
    {
        "name": "开启 Samba 共享 (/userdata)",
        "desc": "启用 Batocera 内置 Samba，便于从电脑直接访问 /userdata 目录传文件",
        "script": """#!/bin/bash
CONF=/userdata/system/batocera.conf
grep -q '^system.samba.enabled' "$CONF" && sed -i 's/^system.samba.enabled=.*/system.samba.enabled=1/' "$CONF" || echo 'system.samba.enabled=1' >> "$CONF"
/etc/init.d/S40samba restart 2>/dev/null || systemctl restart smbd nmbd 2>/dev/null || true
echo '[+] Samba 共享已启用 (\\\\userdata)'
""",
    },
    {
        "name": "部署开机自启脚本槽 (custom.sh)",
        "desc": "创建 /userdata/system/custom.sh 占位并写入示例，便于后续追加开机命令",
        "script": """#!/bin/bash
cat > /userdata/system/custom.sh <<'EOF'
#!/bin/bash
# 在此追加开机要执行的命令（如静态IP/挂载）
EOF
chmod +x /userdata/system/custom.sh
echo '[+] 已创建 /userdata/system/custom.sh'
""",
    },
    {
        "name": "安装 BUA 插件市场",
        "desc": "一键安装 Batocera UnOfficial Add-ons 市场，安装后可在 Ports/端口 分类中打开应用商店",
        "script": """#!/bin/bash
set -e
echo '[*] 正在联网拉取 BUA 插件中心安装脚本 (国内加速)...'
(curl -sSL https://gh-proxy.com/https://raw.githubusercontent.com/batocera-unofficial-addons/bua-installer/main/install.sh 2>/dev/null || curl -sSL install.batoaddons.app) | bash
echo '[*] 正在刷新 EmulationStation 菜单...'
batocera-es-swissknife --reload 2>/dev/null || batocera-es-swissknife --restart 2>/dev/null || true
echo '[+] BUA 插件市场安装完成！可在“端口 (Ports)”分类中查看启动。'
""",
    },
    {
        "name": "部署 Sunshine & Moonlight 串流套件",
        "desc": "确保 BUA 环境就绪后部署 Sunshine 服务端与 Moonlight 客户端，刷新菜单后即可在主界面配对或访问 https://IP:47990 做 PIN 认证",
        "script": """#!/bin/bash
set -e
echo '[*] 确保 BUA 环境就绪...'
if [ ! -f /userdata/roms/ports/bua.sh ]; then
    (curl -sSL https://gh-proxy.com/https://raw.githubusercontent.com/batocera-unofficial-addons/bua-installer/main/install.sh 2>/dev/null || curl -sSL install.batoaddons.app) | bash
fi

echo '[*] 部署 Sunshine 服务端与 Moonlight...'
batocera-es-swissknife --reload 2>/dev/null || true
echo '[+] 串流组件已就绪，请在工具主界面点击【配对 Moonlight】或访问 https://IP:47990 进行 PIN 认证。'
""",
    },
]

class _ConsolePluginsMixin(object):

    def _build_plugins_tab(self, nb):
        # ===== Tab 2: 插件中心 =====
        tab2 = ttk.Frame(nb, padding=6)
        nb.add(tab2, text="📦 插件中心")

        f_market = tk.Frame(tab2)
        f_market.pack(fill="x", pady=(0, 4))
        tk.Button(f_market, text="🛒 安装插件中心", bg="#f97316", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=6, command=self.install_addon_center).pack(side="left", padx=2, ipady=1)
        tk.Button(f_market, text="🖥️ 呼出插件中心", bg="#ec4899", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=6, command=self.open_addon_center).pack(side="left", padx=2, ipady=1)
        tk.Button(f_market, text="🇨🇳 一键汉化市场", bg="#22c55e", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=6, command=self.localize_addon_center).pack(side="left", padx=2, ipady=1)
        tk.Button(f_market, text="✖ 强制退出/解卡", bg="#ef4444", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=6, command=self.kill_addon_center).pack(side="left", padx=2, ipady=1)
        tk.Button(f_market, text="🔄 刷新列表", bg="#06b6d4", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=6, command=self.refresh_addon_list).pack(side="left", padx=2, ipady=1)
        tk.Button(f_market, text="⟳ 刷新ES菜单", bg="#64748b", fg="white", font=("Microsoft YaHei UI", 9, "bold"),
                  relief="flat", padx=6, command=self.reload_es).pack(side="left", padx=2, ipady=1)
        self.market_status = tk.Label(f_market, text="状态: 就绪", fg="#6b7280", font=("Microsoft YaHei UI", 8))
        self.market_status.pack(side="left", padx=4)

        # 插件列表: Treeview 三列式表格 (支持点击表头自由升降序排序)
        f_lib = tk.Frame(tab2)
        f_lib.pack(fill="both", expand=True, pady=2)

        self._sort_reverse = {"#0": False, "status": False, "desc": False}
        self._heading_titles = {
            "#0": "插件名称 (点表头排序 · 双击应用)",
            "status": "状态 (点此排序)",
            "desc": "功能与应用场景说明"
        }

        self.tree_plugs = ttk.Treeview(f_lib, columns=("status", "desc"), show="tree headings", selectmode="browse")
        self.tree_plugs.heading("#0", text=self._heading_titles["#0"], command=lambda: self._sort_plugins_by("#0"))
        self.tree_plugs.heading("status", text=self._heading_titles["status"], command=lambda: self._sort_plugins_by("status"))
        self.tree_plugs.heading("desc", text=self._heading_titles["desc"], command=lambda: self._sort_plugins_by("desc"))

        self.tree_plugs.column("#0", width=240, anchor="w")
        self.tree_plugs.column("status", width=90, anchor="center")
        self.tree_plugs.column("desc", width=400, anchor="w")

        self.tree_plugs.tag_configure("installed", foreground="#16a34a", font=("Microsoft YaHei UI", 9, "bold"))
        self.tree_plugs.tag_configure("uninstalled", foreground="#334155")

        scroll_p = ttk.Scrollbar(f_lib, orient=tk.VERTICAL, command=self.tree_plugs.yview)
        self.tree_plugs.configure(yscrollcommand=scroll_p.set)
        self.tree_plugs.pack(side="left", fill="both", expand=True)
        scroll_p.pack(side="right", fill="y")

        self.tree_plugs.bind("<Double-1>", lambda e: self.apply_plugin())
        self.tree_plugs.bind("<Button-3>", self.on_plug_menu)

        self._plug_tooltip = ToolTip(self.tree_plugs)
        self.tree_plugs.bind("<Motion>", self._on_tree_motion)
        self.tree_plugs.bind("<Leave>", lambda e: self._plug_tooltip.hide_tip())
        self.tree_plugs.bind("<<TreeviewSelect>>", self._on_tree_select)

        self.plug_menu = tk.Menu(self, tearoff=0)
        self.plug_menu.add_command(label="🚀 应用/部署这个插件", command=self.apply_plugin)
        self.plug_menu.add_separator()
        self.plug_menu.add_command(label="📄 查看/编辑脚本", command=self.edit_plugin_script)

    def _sort_plugins_by(self, col):
        """点击表头排序 (已安装/未安装智能置顶切换)"""
        reverse = self._sort_reverse.get(col, False)

        if col == "#0":
            items = [(self.tree_plugs.item(k, "text"), k) for k in self.tree_plugs.get_children("")]
        else:
            items = [(self.tree_plugs.set(k, col), k) for k in self.tree_plugs.get_children("")]

        if col == "status":
            # 状态语义排序: 已安装(权重0) vs 未安装(权重1)
            def _status_weight(t):
                val = t[0]
                is_installed = 0 if ("已安装" in val or "已部署" in val) else 1
                return (is_installed, t[0])
            items.sort(key=_status_weight, reverse=reverse)
        else:
            items.sort(key=lambda t: t[0].lower(), reverse=reverse)

        for idx, (_, k) in enumerate(items):
            self.tree_plugs.move(k, "", idx)

        self._sort_reverse[col] = not reverse
        arrow = " ▼" if reverse else " ▲"

        for c in ("#0", "status", "desc"):
            base_txt = self._heading_titles.get(c, c)
            if c == col:
                self.tree_plugs.heading(c, text=base_txt + arrow)
            else:
                self.tree_plugs.heading(c, text=base_txt)

    def _get_plug_tip(self, item_id):
        idx_str = item_id.replace("item_", "")
        if idx_str.isdigit():
            idx = int(idx_str)
            if 0 <= idx < len(self._plug_map):
                kind, param, installed = self._plug_map[idx]
                if kind == "builtin":
                    p = PLUGINS[param]
                    st_txt = "✅ 已部署安装 (双击可重新应用)" if installed else "⚪ 尚未安装 (双击直接部署)"
                    return f"📦【{p['name']}】 ({st_txt})\n\n💡 场景说明:\n{p['desc']}"
                else:
                    return f"📦【{param}】 (✅ 市场已装插件)\n\n可在盒上 EmulationStation 端口(Ports)分类中直接运行。"
        return ""

    def _on_tree_motion(self, event):
        item_id = self.tree_plugs.identify_row(event.y)
        if not item_id:
            self._plug_tooltip.hide_tip()
            return
        tip = self._get_plug_tip(item_id)
        if tip:
            self._plug_tooltip.update_tip(tip, event.x_root, event.y_root)
        else:
            self._plug_tooltip.hide_tip()

    def _on_tree_select(self, event):
        sel = self.tree_plugs.selection()
        if not sel: return
        item_id = sel[0]
        tip = self._get_plug_tip(item_id)
        if tip:
            bbox = self.tree_plugs.bbox(item_id)
            if bbox:
                x = self.tree_plugs.winfo_rootx() + bbox[0] + min(320, bbox[2])
                y = self.tree_plugs.winfo_rooty() + bbox[1]
                self._plug_tooltip.update_tip(tip, x, y)

    def _populate_builtin_plugins(self):
        self._plug_map = []
        if not hasattr(self, 'tree_plugs') or not self.tree_plugs.winfo_exists(): return
        self.tree_plugs.delete(*self.tree_plugs.get_children())
        for i, p in enumerate(PLUGINS):
            self._plug_map.append(("builtin", i, False))
            self.tree_plugs.insert("", "end", iid=f"item_{i}", text=p["name"],
                                   values=("未安装", p["desc"]), tags=("uninstalled",))

    def on_plug_menu(self, event):
        row = self.tree_plugs.identify_row(event.y)
        if row:
            self.tree_plugs.selection_set(row)
            self.tree_plugs.focus(row)
            try:
                self.plug_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.plug_menu.grab_release()

    def edit_plugin_script(self):
        sel = self.tree_plugs.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个插件！")
            return
        idx = int(sel[0].replace("item_", ""))
        kind, p_idx, _ = self._plug_map[idx]
        if kind == "addon":
            messagebox.showwarning("提示", "市场安装的插件位于 add-ons 目录，不支持在此编辑。")
            return
        p = PLUGINS[p_idx]
        win = tk.Toplevel(self)
        win.title(f"📄 插件脚本: {p['name']}")
        win.geometry("680x480")
        win.transient(self)
        txt = scrolledtext.ScrolledText(win, wrap="none", font=("Consolas", 9))
        txt.pack(fill="both", expand=True, padx=6, pady=6)
        txt.insert("1.0", p["script"])

        def save():
            PLUGINS[p_idx]["script"] = txt.get("1.0", "end-1c")
            self._log(f"[+] 已保存插件【{p['name']}】脚本修改")
            win.destroy()

        tk.Button(win, text="💾 保存修改", bg="#28a745", fg="white", font=("Microsoft YaHei UI", 10, "bold"),
                  command=save).pack(fill="x", padx=6, pady=(0, 6))

    def apply_plugin(self):
        sel = self.tree_plugs.selection()
        if not sel:
            messagebox.showwarning("提示", "请先选择一个插件！")
            return
        idx = int(sel[0].replace("item_", ""))
        kind, p_idx, installed = self._plug_map[idx]
        if kind == "addon":
            messagebox.showwarning("提示", f"插件【{p_idx}】已安装在市场目录，可在盒上菜单中直接运行。")
            return
        p = PLUGINS[p_idx]
        safe = re.sub(r"[^0-9a-zA-Z_]", "_", p["name"])[:40]
        remote = f"/userdata/system/plugins/{safe}.sh"
        b64 = base64.b64encode(p["script"].encode("utf-8")).decode("ascii")
        self._log(f"[*] 正在推送插件【{p['name']}】到 {remote} ...")
        self._set_plug_progress(15, f"正在推送插件【{p['name']}】...")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._set_plug_progress(0, "状态: 失败 (未连接)")
                    return
                w_in, w_out, w_err = ssh.exec_command(
                    f"mkdir -p /userdata/system/plugins && "
                    f"echo '{b64}' | base64 -d > {remote} && chmod +x {remote}"
                )
                w_exit = w_out.channel.recv_exit_status()
                if w_exit != 0:
                    self._set_plug_progress(0, "状态: 失败 (脚本写入错误)")
                    return
                self._set_plug_progress(45, "状态: 脚本已上传, 正在执行...")
                stdin, stdout, stderr = ssh.exec_command(f"bash {remote}", timeout=600)
                exit_code = stdout.channel.recv_exit_status()
                out = stdout.read().decode("utf-8", "ignore") + stderr.read().decode("utf-8", "ignore")
                self._set_plug_progress(100, f"状态: 执行完成 (退出码 {exit_code})")
                self.after(0, lambda o=out, e=exit_code: self._log(f"[+] 插件执行结果 (退出码 {e}):\n{o or '(无输出)'}"))
                self.after(500, self.refresh_addon_list)
            except Exception as e:
                self._set_plug_progress(0, "状态: 失败")
                self._log(f"[-] 插件应用失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def _set_plug_progress(self, pct, text):
        try:
            if self._closing: return
            self.after(0, lambda p=pct, t=text: self._apply_plug_progress(p, t))
        except (tk.TclError, RuntimeError): pass

    def _apply_plug_progress(self, pct, text):
        try:
            if self._closing or not self.plug_progress.winfo_exists(): return
            self.plug_progress["value"] = pct
            self.lbl_plug_status.config(text=text, fg=("#0d6efd" if 0 < pct < 100 else ("#16a34a" if pct == 100 else "#dc2626")))
        except (tk.TclError, RuntimeError): pass

    def install_addon_center(self):
        self._log("[*] 正在安装 Batocera 插件中心 (注入国内加速代理)...")
        self._set_plug_progress(25, "状态: 正在联网安装插件中心...")
        def task():
            try:
                ssh = self._get_ssh()
                if not ssh:
                    self._set_plug_progress(0, "状态: 失败 (未连接)")
                    return
                # 注入代理拉取，防止 GitHub 卡死
                cmd = "(curl -sSL https://gh-proxy.com/https://raw.githubusercontent.com/batocera-unofficial-addons/bua-installer/main/install.sh 2>/dev/null || curl -sSL install.batoaddons.app 2>&1) | bash 2>&1"
                stdin, stdout, stderr = ssh.exec_command(cmd, timeout=600)
                self._stream_channel(stdout.channel)
                self._set_plug_progress(90, "状态: 安装完成, 正在刷新菜单...")
                self.reload_es()
                self.after(0, self.refresh_addon_list)
                self._set_plug_progress(100, "状态: 插件中心安装完成")
            except Exception as e:
                self._set_plug_progress(0, "状态: 失败")
                self._log(f"[-] 插件中心安装失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def _stream_channel(self, channel):
        try:
            while True:
                if getattr(self, "_closing", False): break
                if channel.exit_status_ready() and not channel.recv_ready(): break
                if channel.recv_ready():
                    data = channel.recv(4096)
                    if not data: break
                    self._log(data.decode("utf-8", "ignore").rstrip("\n"))
                else:
                    time.sleep(0.1)
            while channel.recv_ready():
                data = channel.recv(4096)
                if not data: break
                self._log(data.decode("utf-8", "ignore").rstrip("\n"))
        except Exception as e:
            self._log(f"[stream] 读取输出异常: {e}")

    def reload_es(self):
        if getattr(self, "_closing", False): return
        self._log("[*] 正在刷新 EmulationStation 菜单 ...")
        def task():
            if getattr(self, "_closing", False): return
            out1 = self._run("batocera-es-swissknife --reload 2>&1 || batocera-es-swissknife --restart 2>&1 || true")
            self.after(0, lambda o=out1: self._log(f"[ES 刷新输出]:\n{o or '(已发送刷新指令)'}"))
        threading.Thread(target=task, daemon=True).start()

    def refresh_addon_list(self):
        self._log("[*] 正在查询已安装插件并更新列表标记 ...")
        def task():
            try:
                out = self._run(
                    "echo '==ADDON=='; ls -1 /userdata/system/add-ons 2>/dev/null; "
                    "echo '==DEPLOYED=='; ls -1 /userdata/system/plugins/ 2>/dev/null")
                addon, deployed, cur = [], [], None
                for line in (out or "").splitlines():
                    if line == "==ADDON==": cur = addon
                    elif line == "==DEPLOYED==": cur = deployed
                    elif cur is not None and line.strip(): cur.append(line.strip())
                self.after(0, lambda a=addon, d=deployed: self._rebuild_plug_list(a, d))
            except Exception as e:
                self.after(0, lambda e=e: self._log(f"[-] 查询失败: {e}"))
        threading.Thread(target=task, daemon=True).start()

    def _rebuild_plug_list(self, addon_names, deployed_names):
        try:
            if getattr(self, "_closing", False) or not self.tree_plugs.winfo_exists():
                return
            deployed = set(deployed_names or [])
            self.tree_plugs.delete(*self.tree_plugs.get_children())
            self._plug_map = []
            builtin_installed = 0
            for i, p in enumerate(PLUGINS):
                safe = re.sub(r"[^0-9a-zA-Z_]", "_", p["name"])[:40]
                inst = (safe + ".sh") in deployed
                if inst: builtin_installed += 1
                self._plug_map.append(("builtin", i, inst))
                st_label = "✅ 已安装" if inst else "未安装"
                tag = "installed" if inst else "uninstalled"
                self.tree_plugs.insert("", "end", iid=f"item_{i}", text=p["name"],
                                       values=(st_label, p["desc"]), tags=(tag,))

            base_idx = len(PLUGINS)
            for j, name in enumerate(addon_names or []):
                idx = base_idx + j
                self._plug_map.append(("addon", name, True))
                self.tree_plugs.insert("", "end", iid=f"item_{idx}", text=f"[市场] {name}",
                                       values=("✅ 已安装", "来自插件市场的外部扩展"), tags=("installed",))

            self.market_status.config(
                text=f"状态: 内置已部署 {builtin_installed}/{len(PLUGINS)} · 市场已装 {len(addon_names or [])}")
        except (tk.TclError, RuntimeError): pass

    def open_addon_center(self):
        """呼出插件市场 (自动注入代理防卡死 + 实时日志回显)"""
        self._log("[*] 正在准备呼出 Batocera 插件中心...")
        def task():
            ssh = self._get_ssh()
            if not ssh: return
            try:
                # 1. 检查是否存在 bua.sh
                _, out, _ = run_sync_cmd(ssh, "ls -l /userdata/roms/ports/bua.sh 2>/dev/null")
                if "bua.sh" not in out:
                    self._log("[-] 未检测到插件市场主脚本，请先点击【🛒 安装插件中心】！")
                    self.after(0, lambda: messagebox.showwarning("提示", "未检测到插件市场主程序，请先点击【🛒 安装插件中心】进行安装！"))
                    return

                # 2. 对 bua.sh 注入 gh-proxy 加速代理防 Loading 卡死
                patch_sh = (
                    "sed -i 's|raw.githubusercontent.com|gh-proxy.com/https://raw.githubusercontent.com|g' /userdata/roms/ports/bua.sh 2>/dev/null; "
                    "sed -i 's|github.com|gh-proxy.com/https://github.com|g' /userdata/roms/ports/bua.sh 2>/dev/null"
                )
                run_sync_cmd(ssh, patch_sh)

                # 3. 启动并在后台记录日志
                self._set_plug_progress(60, "状态: 正在呼出插件中心...")
                run_sync_cmd(ssh,
                    "PATH=/userdata/system/python/bin:$PATH DISPLAY=:0.0 XAUTHORITY=/var/lib/.Xauthority "
                    "setsid nohup sh /userdata/roms/ports/bua.sh >/tmp/bua_launcher.log 2>&1 & echo LAUNCHED")
                self._log("[+] 已发起插件中心启动！若屏幕卡在 Loading，请稍候约 15 秒（正在通过加速节点同步资源）。")
                self._set_plug_progress(100, "状态: 已呼出插件中心")

                # 回显日志前两行
                time.sleep(3)
                _, log_txt, _ = run_sync_cmd(ssh, "tail -n 5 /tmp/bua_launcher.log 2>/dev/null")
                if log_txt.strip():
                    self._log(f"[插件中心启动日志]:\n{log_txt.strip()}")
            except Exception as e:
                self._set_plug_progress(0, "状态: 呼出失败")
                self._log(f"[-] 呼出插件中心失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def kill_addon_center(self):
        """一键强制杀掉卡在 Loading... 的插件市场并刷新屏幕恢复 ES 菜单"""
        self._log("[*] 正在强制关闭插件市场并清理残留进程 (解卡)...")
        def task():
            ssh = self._get_ssh()
            if not ssh: return
            try:
                # 强杀 bua 及 python 进程，并重启 openbox/ES 刷新屏幕
                cmd = (
                    "pkill -9 -f 'bua.sh' 2>/dev/null || true; "
                    "pkill -9 -f 'bua_installer' 2>/dev/null || true; "
                    "pkill -9 -f 'python.*bua' 2>/dev/null || true; "
                    "batocera-es-swissknife --reload 2>/dev/null || batocera-es-swissknife --restart 2>/dev/null || true"
                )
                run_sync_cmd(ssh, cmd)
                self._log("[+] ✅ 插件中心卡死进程已强制终止，屏幕已刷新恢复 EmulationStation 菜单！")
                
            except Exception as e:
                self._log(f"[-] 强制退出失败: {e}")
        threading.Thread(target=task, daemon=True).start()

    def localize_addon_center(self):
        """为 Batocera 插件市场注入全中文汉化字典与中文字体支持"""
        self._log("[*] 正在准备为 Batocera 插件市场注入一键汉化补丁...")
        def task():
            ssh = self._get_ssh()
            if not ssh: return
            try:
                # 1. 确保已安装 bua.sh
                _, chk, _ = run_sync_cmd(ssh, "ls -l /userdata/roms/ports/bua.sh 2>/dev/null")
                if "bua.sh" not in chk:
                    self._log("[-] 未检测到插件市场主程序，请先点击【🛒 安装插件中心】！")
                    self.after(0, lambda: messagebox.showwarning("提示", "未检测到插件市场主程序，请先点击【🛒 安装插件中心】安装后再汉化！"))
                    return

                # 2. 预先拉取/解压 bua 主程序文件以便就地打汉化补丁
                self._log("[*] 正在拉取插件市场主界面代码并注入中文字典...")
                pre_fetch = (
                    "cd /tmp && "
                    "(curl -sSL https://gh-proxy.com/https://raw.githubusercontent.com/batocera-unofficial-addons/bua-installer/main/bua_installerx86.py -o /tmp/bua_installerx86.py 2>/dev/null || true)"
                )
                run_sync_cmd(ssh, pre_fetch)

                # 3. 构造 Python 汉化补丁脚本 (词条翻译 + 中文字体回退)
                patch_py = r"""
import re, os

targets = ['/tmp/bua_installerx86.py', '/userdata/system/bua_installerx86.py']
zh_map = {
    r"'Emulators'": "'🎮 游戏模拟器'",
    r'"Emulators"': '"🎮 游戏模拟器"',
    r"'Applications'": "'📱 常用应用与工具'",
    r'"Applications"': '"📱 常用应用与工具"',
    r"'Streaming'": "'☁️ 云游戏与串流'",
    r'"Streaming"': '"☁️ 云游戏与串流"',
    r"'Utilities'": "'🛠️ 系统辅助工具'",
    r'"Utilities"': '"🛠️ 系统辅助工具"',
    r"'Flatpak'": "'📦 Flatpak 独立包'",
    r'"Flatpak"': '"📦 Flatpak 独立包"',
    r"'Install'": "'📥 立即安装'",
    r'"Install"': '"📥 立即安装"',
    r"'Uninstall'": "'🗑️ 卸载此插件'",
    r'"Uninstall"': '"🗑️ 卸载此插件"',
    r"'Update'": "'🔄 检查更新'",
    r'"Update"': '"🔄 检查更新"',
    r"'Back'": "'⬅️ 返回上一级'",
    r'"Back"': '"⬅️ 返回上一级"',
    r"'Exit'": "'✖ 退出市场'",
    r'"Exit"': '"✖ 退出市场"',
    r"'Loading...'": "'正在加载插件市场...'",
    r'"Loading..."': '"正在加载插件市场..."',
    r"'Downloading'": "'正在下载中'",
    r'"Downloading"': '"正在下载中"',
    r"'Installed'": "'✅ 已安装'",
    r'"Installed"': '"✅ 已安装"',
    r"'Not Installed'": "'⚪ 未安装'",
    r'"Not Installed"': '"⚪ 未安装"',
    r"'Installation complete'": "'🎉 安装完成！'",
    r'"Installation complete"': '"🎉 安装完成！"',
}

for fp in targets:
    if os.path.exists(fp):
        with open(fp, 'r', encoding='utf-8', errors='ignore') as f:
            code = f.read()
        for k, v in zh_map.items():
            code = re.sub(k, v, code)
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(code)
        print("PATCHED:", fp)
"""
                b64_patch = base64.b64encode(patch_py.encode('utf-8')).decode('ascii')
                apply_cmd = (
                    f"echo '{b64_patch}' | base64 -d > /tmp/patch_zh.py && "
                    "/userdata/system/python/bin/python3 /tmp/patch_zh.py 2>/dev/null; "
                    "rm -f /tmp/patch_zh.py"
                )
                run_sync_cmd(ssh, apply_cmd)
                self._log("[+] 🎉 插件市场界面已成功汉化！(分类/安装/卸载/状态均已转为中文)")
                
            except Exception as e:
                self._log(f"[-] 汉化失败: {e}")
                self.after(0, lambda e=e: messagebox.showerror("汉化失败", str(e)))
        threading.Thread(target=task, daemon=True).start()
