# -*- coding: utf-8 -*-
"""NB宗 · PVE Batocera 一键编译打包构建引擎 —— GUI 版

功能：
- tkinter 图形界面，后台线程跑 PyInstaller，实时回显日志
- 两种产物：
    * 含缓存版：把 modules/cache/* 全部打进 exe（sunshine.AppImage / glibc / va / so 等，
      免去目标机联网重下），运行时由 pve_bundle.release_all() 按需释放到 exe 同目录 cache/
    * 精简版：不带 cache（体积小），运行时 pve_deploy_bundle 会按需联网下载
- 两个版本都必然打包注入 vncviewer.exe
- 可用 --cli 参数在无界面环境一键出「精简版」
"""
import os
import sys
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

PYTHON_PATH = r"S:\python\Python38\python.exe"
ICON_PATH = os.path.join("winres", "main.ico")
VNC_PATH = "vncviewer.exe"
MAIN_SCRIPT = "pve.py"
CACHE_DIR = os.path.join("modules", "cache")
BASE_NAME = "NB宗_PVE_Batocera部署管理器"
NAME_FULL = BASE_NAME + "_含缓存版"
NAME_LITE = BASE_NAME + "_精简版"


def _cache_inventory():
    """返回 [(文件名, 字节数)]，按大小降序；目录不存在返回空。"""
    if not os.path.isdir(CACHE_DIR):
        return []
    items = []
    for f in sorted(os.listdir(CACHE_DIR)):
        p = os.path.join(CACHE_DIR, f)
        if os.path.isfile(p):
            try:
                items.append((f, os.path.getsize(p)))
            except Exception:
                pass
    items.sort(key=lambda x: -x[1])
    return items


def _resolve_python():
    if os.path.exists(PYTHON_PATH):
        return PYTHON_PATH
    return sys.executable


def _resolve_vnc():
    """确保本地存在 vncviewer.exe，必要时从常见安装位置提取。"""
    if os.path.exists(VNC_PATH) and os.path.getsize(VNC_PATH) > 0:
        return True
    common = [
        r"C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe",
        r"C:\Program Files (x86)\RealVNC\VNC Viewer\vncviewer.exe",
    ]
    import shutil
    for c in common:
        if os.path.exists(c):
            shutil.copy2(c, VNC_PATH)
            return True
    return False


def build_one(py_bin, out_name, include_cache, log):
    """同步构建一个版本，每条进度写进 log(text 可调用接收 str)。"""
    log("\n" + "=" * 64)
    log(f"▶ 构建产物: {out_name}  (缓存:{'含缓存' if include_cache else '不含缓存'})")

    cmd = [py_bin, "-m", "PyInstaller",
           "--noconsole", "--onefile", "--clean", "--noconfirm",
           f"--name={out_name}",
           # 关键: pve.py 靠运行时 sys.path.insert + 裸 import pve_* 加载业务模块,
           # 必须让 PyInstaller 静态分析找到 modules/, 否则 exe 内不含任何 pve_* 模块
           # -> 冻结后裸 import 报 ModuleNotFoundError
           "--paths=modules"]

    # 显式打包全部业务模块 (含互引/动态加载缺口, 保证冻结后裸 import 全能命中)
    _mods_dir = "modules"
    if os.path.isdir(_mods_dir):
        for _f in sorted(os.listdir(_mods_dir)):
            if _f.endswith(".py") and not _f.startswith("_"):
                cmd.append(f"--hidden-import={_f[:-3]}")

    if os.path.exists(ICON_PATH):
        cmd.append(f"--icon={ICON_PATH}")
        log(f"[+] 图标: {ICON_PATH}")

    # vncviewer 必打
    if os.path.exists(VNC_PATH):
        cmd.append(f"--add-data={VNC_PATH};.")
        log(f"[+] 注入 vncviewer.exe  ({os.path.getsize(VNC_PATH)//1024} KB)")
    else:
        log("[-] 未找到 vncviewer.exe，产物不含内置 VNC 客户端。")

    # 缓存按需打入
    if include_cache:
        items = _cache_inventory()
        if not items:
            log("[-] modules/cache/ 为空！含缓存版将退化为精简版（仅 vncviewer）。")
        # 注意: dest 必须带尾部斜杠 (cache/) 才会被看作“目录”并把源文件按原名拷进去;
        # 若写成 cache/{name}(无尾部斜杠) PyInstaller 会把它当“目录名”为每个文件建一个
        # 空目录再拷进里面 -> 运行时 _MEIPASS/cache 里全是 size=0 的空目录, 释放函数读到 0 文件。
        for name, size in items:
            cmd.append(f"--add-data={os.path.join(CACHE_DIR, name)};cache/")
        total = sum(s for _, s in items)
        log(f"[+] 注入 {len(items)} 个缓存文件，合计 {total//1024//1024} MB (target: {out_name}.exe)")
    else:
        log("[*] 精简版：不注入缓存，运行时按需联网下载。")

    cmd.append(MAIN_SCRIPT)

    log("[*] 开始编译打包 ...")
    env = dict(os.environ)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace",
                                env=env, bufsize=1)
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log(line)
        proc.wait()
    except Exception as e:
        log(f"[-] 构建进程异常: {e}")
        return False

    dist_exe = os.path.join("dist", f"{out_name}.exe")
    if proc.returncode == 0 and os.path.exists(dist_exe):
        mb = os.path.getsize(dist_exe) // 1024 // 1024
        log(f"[+] ✅ 构建成功: {os.path.abspath(dist_exe)}  ({mb} MB)")
        return True
    log("[-] 构建失败，请查看上方日志。")
    return False


class BuildGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("⚡ NB宗 · PVE 编译打包构建引擎 (GUI)")
        self.geometry("760x560")
        self.minsize(680, 480)

        self._building = False

        self._build_top()
        self._build_mid()
        self._build_log()

        self._refresh_cache_display()

    def _build_top(self):
        f = tk.Frame(self, padx=12, pady=8)
        f.pack(fill="x")
        tk.Label(f, text="🧰 选择要构建的版本", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")

        self.var_full = tk.BooleanVar(value=True)
        self.var_lite = tk.BooleanVar(value=True)
        c = tk.Checkbutton(f, text="含缓存版（打进全部 cache，目标机免重下，体积大）",
                           variable=self.var_full, font=("Microsoft YaHei UI", 10))
        c.pack(anchor="w", pady=2)
        c2 = tk.Checkbutton(f, text="精简版（不带缓存，体积小，运行时在线下载）",
                            variable=self.var_lite, font=("Microsoft YaHei UI", 10))
        c2.pack(anchor="w")

        f2 = tk.Frame(f)
        f2.pack(fill="x", pady=(8, 0))
        tk.Label(f2, text="Python:", font=("Microsoft YaHei UI", 9, "bold")).pack(side="left")
        tk.Label(f2, text=_resolve_python(), fg="#2563eb", font=("Consolas", 9)).pack(side="left", padx=4)
        self.btn_go = tk.Button(f2, text="🚀 开始构建", font=("Microsoft YaHei UI", 11, "bold"),
                                bg="#2563eb", fg="white", bd=0, padx=20, pady=4, cursor="hand2",
                                command=self.start_build)
        self.btn_go.pack(side="right")

    def _build_mid(self):
        f = tk.LabelFrame(self, text="📦 缓存清单 (将打进“含缓存版”)", padx=8, pady=4)
        f.pack(fill="x", padx=12)
        col = tk.Frame(f)
        col.pack(fill="x")
        self.cache_lbl = tk.Label(col, text="", justify="left", anchor="w",
                                  font=("Consolas", 9), fg="#374151")
        self.cache_lbl.pack(side="left", fill="x", expand=True)
        self.total_lbl = tk.Label(col, text="", font=("Microsoft YaHei UI", 10, "bold"),
                                  fg="#1e40af")
        self.total_lbl.pack(side="right", anchor="n", padx=(8, 0))

    def _build_log(self):
        f = tk.LabelFrame(self, text="📜 构建日志", padx=6, pady=4)
        f.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self.log = scrolledtext.ScrolledText(f, height=14, font=("Consolas", 9),
                                             state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)

    def _refresh_cache_display(self):
        items = _cache_inventory()
        if items:
            lines = []
            for name, size in items:
                kb = size // 1024
                lines.append(f"{name:34s} {kb//1024 if kb>1024 else 0:>3d} MB" if kb > 1024
                             else f"{name:34s} {kb:>6d} KB")
            self.cache_lbl.config(text="\n".join(lines))
            total = sum(s for _, s in items)
            self.total_lbl.config(text=f"共 {len(items)} 个 / {total//1024//1024} MB")
        else:
            self.cache_lbl.config(text="(空) modules/cache/ 下暂无缓存文件")
            self.total_lbl.config(text="0 个")

    # ---------- 日志 ----------
    def append_log(self, text):
        self.log.config(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.config(state="disabled")
        self.update_idletasks()

    def start_build(self):
        if self._building:
            return
        if not (self.var_full.get() or self.var_lite.get()):
            self.append_log("[-] 请至少勾选一个版本。")
            return
        if os.path.exists(VNC_PATH) or _resolve_vnc():
            pass
        else:
            self.append_log("[-] 未找到 vncviewer.exe（且未能自动提取），产物将不含内置 VNC。")

        py_bin = _resolve_python()

        # 确保 pyinstaller 就绪
        self.append_log("[*] 检查 PyInstaller ...")
        try:
            subprocess.run([py_bin, "-m", "pip", "show", "pyinstaller"],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.append_log("[+] PyInstaller 已就绪")
        except subprocess.CalledProcessError:
            self.append_log("[*] 正在安装 PyInstaller (清华镜像)...")
            subprocess.run([py_bin, "-m", "pip", "install", "pyinstaller",
                            "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"], check=True)
            self.append_log("[+] PyInstaller 安装完成")

        self._building = True
        self.btn_go.config(state="disabled", bg="#9ca3af", text="⏳ 构建中...")

        def worker():
            try:
                if self.var_full.get():
                    build_one(py_bin, NAME_FULL, True, self.append_log)
                if self.var_lite.get():
                    build_one(py_bin, NAME_LITE, False, self.append_log)
                self.append_log("\n🎉 全部构建结束，产物在 dist/ 目录。")
            except Exception as e:
                self.append_log(f"[-] 构建异常: {e}")
            finally:
                self.after(0, self._build_done)

        threading.Thread(target=worker, daemon=True).start()

    def _build_done(self):
        self._building = False
        self.btn_go.config(state="normal", bg="#2563eb", text="🚀 开始构建")


if __name__ == "__main__":
    # 无界面参数: --cli 直接出"精简版"；--cli full 出"含缓存版"
    if "--cli" in sys.argv:
        # 控制台 GBK 编码, emoji/▶ 等无法写入 print -> 走 buffer 用 gbk+replace 硬编码
        def _cli_log(msg):
            try:
                if not sys.stdout.buffer.closed:
                    sys.stdout.buffer.write((msg + "\n").encode("gbk", "replace"))
                    sys.stdout.buffer.flush()
            except Exception:
                print(msg)
        which = sys.argv[sys.argv.index("--cli") + 1] if len(sys.argv) > sys.argv.index("--cli") + 1 else "lite"
        mode = "full" if which == "full" else "lite"
        out = NAME_FULL if mode == "full" else NAME_LITE
        ok = build_one(_resolve_python(), out, mode == "full", _cli_log)
        sys.exit(0 if ok else 1)
    app = BuildGui()
    app.mainloop()
