# -*- coding: utf-8 -*-
"""VNC 客户端定位与呼出。

主程序名与品牌映射：
  * vncviewer.exe —— RealVNC 经典 Viewer / TigerVNC / UltraVNC 共用文件名
  * tvnviewer.exe —— TightVNC
  * rvncconnect.exe —— RealVNC Connect Viewer 8.x (新版, Flutter 打包, 依赖同目录 dll)

定位链：当前路径(内置/自动下载) -> 注册表 Uninstall 键(系统已装) -> 常见安装路径
       -> 官方源自动下载 -> 手动提示。
"""
import subprocess
import os
import sys
import shutil
import tempfile
import zipfile
import threading
import urllib.request

try:
    import winreg
except ImportError:  # 非 Windows
    winreg = None

VNC_DOWNLOAD_URL = ("https://downloads.realvnc.com/download/file/realvnc-connect-viewer/"
                    "RealVNC-Connect-Viewer-8.5.0-Windows.msi.zip")
_download_lock = threading.Lock()

# 品牌 -> (描述, 可执行文件名集合)
KIND_EXE = {
    "realvnc":   ("vncviewer.exe",),
    "connect":   ("rvncconnect.exe",),
    "tigervnc":  ("vncviewer.exe",),
    "tightvnc":  ("tvnviewer.exe", "tvnviewer64.exe"),
    "ultravnc":  ("vncviewer.exe",),
}
# 注册表 DisplayName 模式 -> kind
KIND_PATTERNS = (
    ("connect",  ("RealVNC Connect",)),
    ("realvnc",  ("RealVNC", "VNC Viewer", "VNCViewer")),
    ("tigervnc", ("TigerVNC",)),
    ("tightvnc", ("TightVNC",)),
    ("ultravnc", ("UltraVNC",)),
)


def _guess_kind_from_path(path):
    base = os.path.basename(path).lower()
    low = path.lower()
    if base == "rvncconnect.exe":
        return "connect"
    if "tightvnc" in low or base.startswith("tvnviewer"):
        return "tightvnc"
    if "tigervnc" in low:
        return "tigervnc"
    if "ultravnc" in low:
        return "ultravnc"
    return "realvnc"


def _app_dir():
    """源码模式返回 modules/，frozen 返回 exe 同目录（与 get_bundled_vnc_path 一致）。"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _find_extracted_vnc_exe(root):
    """在 root 下递归查找任一款 VNC 客户端主程序，返回 (exe_path, kind)。"""
    for name in ("rvncconnect.exe", "vncviewer.exe", "tvnviewer.exe", "tvnviewer64.exe"):
        for dirpath, _dirnames, filenames in os.walk(root):
            cand = os.path.join(dirpath, name)
            if os.path.isfile(cand) and os.path.getsize(cand) > 0:
                return cand, _guess_kind_from_path(cand)
    return None


def _extract_msi(msi, out_dir):
    """msiexec /a 管理安装解包 msi 到 out_dir，成功返回 True。"""
    if not msi or not os.path.isfile(msi):
        return False
    os.makedirs(out_dir, exist_ok=True)
    args = ["msiexec", "/a", msi, "/qn", "TARGETDIR=" + out_dir]
    try:
        subprocess.run(args, timeout=180,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return False
    return _find_extracted_vnc_exe(out_dir) is not None


def auto_fetch_vncviewer():
    """从 RealVNC 官方源自动下载并解包 VNC 客户端（仅运行时获取，不随项目再分发）。

    解包产物分两种：
      * vncviewer.exe   (经典/旧版) -> 拷贝单文件到 app 目录 vncviewer.exe
      * rvncconnect.exe (Connect 8.x, Flutter 打包, 依赖同目录 dll)
        -> 整体拷贝解包目录到 app 目录 vnc_auto/ 以保留依赖

    所下载软件受 RealVNC 自家许可约束，与本项目 GPL-3.0 许可无关。
    """
    app_dir = _app_dir()
    classic_target = os.path.join(app_dir, "vncviewer.exe")
    auto_dir = os.path.join(app_dir, "vnc_auto")
    auto_exe = os.path.join(auto_dir, "rvncconnect.exe")
    if os.path.exists(classic_target) and os.path.getsize(classic_target) > 0:
        return classic_target
    if os.path.exists(auto_exe) and os.path.getsize(auto_exe) > 0:
        return auto_exe

    with _download_lock:
        if os.path.exists(classic_target) and os.path.getsize(classic_target) > 0:
            return classic_target
        if os.path.exists(auto_exe) and os.path.getsize(auto_exe) > 0:
            return auto_exe
        tmp = tempfile.mkdtemp(prefix="vnc_fetch_")
        try:
            zip_path = os.path.join(tmp, "viewer.zip")
            print("[*] 下载 VNC Viewer (RealVNC 官方): " + VNC_DOWNLOAD_URL)
            urllib.request.urlretrieve(VNC_DOWNLOAD_URL, zip_path)
            size = os.path.getsize(zip_path)
            if size < 100000:
                print("[-] 下载异常: 文件过小 (%d B)" % size)
                return None
            msi = None
            with zipfile.ZipFile(zip_path) as zf:
                for name in zf.namelist():
                    if name.lower().endswith(".msi"):
                        zf.extract(name, tmp)
                        msi = os.path.join(tmp, name)
                        break
            msi_out = os.path.join(tmp, "msi_out")
            if msi:
                _extract_msi(msi, msi_out)
            found = _find_extracted_vnc_exe(tmp)
            if not found:
                print("[-] 未能从下载包中提取 VNC 客户端，请手动安装。")
                return None

            extracted, kind = found
            if kind == "connect":
                src_dir = os.path.dirname(extracted)
                if not (os.path.exists(auto_exe) and os.path.getsize(auto_exe) > 0):
                    os.makedirs(auto_dir, exist_ok=True)
                    try:
                        for f in os.listdir(src_dir):
                            s = os.path.join(src_dir, f)
                            d = os.path.join(auto_dir, f)
                            if os.path.isdir(s):
                                shutil.copytree(s, d, dirs_exist_ok=True)
                            else:
                                if not (os.path.exists(d) and os.path.getsize(d) == os.path.getsize(s)):
                                    shutil.copy2(s, d)
                    except Exception as e:
                        print("[-] 拷贝 VNC 客户端目录失败: %s" % e)
                if os.path.exists(auto_exe) and os.path.getsize(auto_exe) > 0:
                    print("[+] RealVNC Connect Viewer 就绪: %s" % auto_exe)
                    return auto_exe
            else:
                if not (os.path.exists(classic_target)
                        and os.path.getsize(classic_target) > 0):
                    try:
                        shutil.copy2(extracted, classic_target)
                    except Exception:
                        pass
                if os.path.exists(classic_target) and os.path.getsize(classic_target) > 0:
                    print("[+] VNC Viewer 就绪: %s" % classic_target)
                    return classic_target
            print("[-] 未能准备好 VNC 客户端，请手动安装。")
            return None
        except Exception as e:
            print("[-] 自动获取 VNC Viewer 失败: %s" % e)
            return None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def get_bundled_vnc_path():
    """检测并提取打包内置的 vncviewer.exe (若目标已存在则绝不重复释放)。"""
    app_dir = _app_dir()
    target_vnc = os.path.join(app_dir, "vncviewer.exe")

    if os.path.exists(target_vnc) and os.path.getsize(target_vnc) > 0:
        return target_vnc

    bundled_src = ""
    if hasattr(sys, '_MEIPASS'):
        bundled_src = os.path.join(sys._MEIPASS, "vncviewer.exe")
    elif os.path.exists(os.path.join(app_dir, "vncviewer.exe")):
        bundled_src = os.path.join(app_dir, "vncviewer.exe")

    if bundled_src and os.path.exists(bundled_src):
        try:
            shutil.copy2(bundled_src, target_vnc)
            return target_vnc
        except Exception:
            temp_vnc = os.path.join(tempfile.gettempdir(), "vncviewer.exe")
            if not os.path.exists(temp_vnc) or os.path.getsize(temp_vnc) == 0:
                try:
                    shutil.copy2(bundled_src, temp_vnc)
                except Exception:
                    pass
            return temp_vnc

    return target_vnc


def _registry_vnc_probe():
    """扫描注册表 Uninstall 键，返回 [(exe_path, kind), ...]（已存在过滤）。"""
    if winreg is None:
        return []
    roots = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    uninstall_paths = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    )
    found = []

    def _subkey_values(hive, path):
        try:
            with winreg.OpenKey(hive, path) as k:
                i = 0
                while True:
                    try:
                        sub = winreg.EnumKey(k, i)
                        i += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(k, sub) as sk:
                            yield sub, sk
                    except OSError:
                        continue
        except OSError:
            return

    def _read(key, name):
        try:
            v, _ = winreg.QueryValueEx(key, name)
            return v if isinstance(v, str) else ""
        except OSError:
            return ""

    for hive in roots:
        for view in views:
            for path in uninstall_paths:
                for sub, sk in _subkey_values(hive, path):
                    del sub
                    dname = _read(sk, "DisplayName")
                    kind = None
                    for k, pats in KIND_PATTERNS:
                        if any(p.lower() in dname.lower() for p in pats):
                            kind = k
                            break
                    if not kind:
                        continue
                    exe = _exe_from_uninstall(sk, kind)
                    if exe and os.path.isfile(exe) and os.path.getsize(exe) > 0:
                        found.append((exe, kind))
                        continue
                    # Uninstall 键可能缺 DisplayIcon/InstallLocation：回退该 kind 的默认安装路径
                    for _k, _p in VncLauncher.COMMON_PATHS:
                        if _k == kind and os.path.isfile(_p) and os.path.getsize(_p) > 0:
                            found.append((_p, kind))
                            break
    return found


def _exe_from_uninstall(sk, kind):
    """从 Uninstall 子键提取可执行文件路径：DisplayIcon > InstallLocation + 已知文件名。"""
    icon = ""
    try:
        v, _ = winreg.QueryValueEx(sk, "DisplayIcon")
        icon = v if isinstance(v, str) else ""
    except OSError:
        pass
    if icon:
        cand = icon.split(",")[0].strip().strip('"')
        if cand.lower().endswith(".exe") and os.path.isfile(cand):
            return cand

    loc = ""
    try:
        v, _ = winreg.QueryValueEx(sk, "InstallLocation")
        loc = v if isinstance(v, str) else ""
    except OSError:
        pass
    if loc:
        for name in KIND_EXE.get(kind, ()):
            cand = os.path.join(loc, name)
            if os.path.isfile(cand) and os.path.getsize(cand) > 0:
                return cand
    return None


class VncLauncher:
    # 精准对齐的 VNC 分辨率预设
    RESOLUTIONS = [
        ("🖥 1280x720 (720P 舒适推荐)", "1280x720"),
        ("🖥 1920x1080 (1080P 全高清标准)", "1920x1080"),
        ("🖥 1024x768 (4:3 经典标清小窗)", "1024x768"),
        ("🖥 1600x900 (16:9 高清大窗)", "1600x900"),
        ("🖥 800x600 (4:3 迷你小窗)", "800x600"),
        ("🖥 2560x1440 (2K 超清大屏)", "2560x1440"),
        ("🖥 自适应等比窗口 (AspectFit)", "AspectFit"),
        ("🖥 自动铺满窗口 (FitAutoAspect)", "FitAutoAspect"),
        ("🖥 纯净直连 (5999端口)", "direct")
    ]

    # kind -> 候选绝对路径（不进行 PATH 查找，仅存在性）
    COMMON_PATHS = [
        ("realvnc",  r"C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe"),
        ("realvnc",  r"C:\Program Files (x86)\RealVNC\VNC Viewer\vncviewer.exe"),
        ("connect",  r"C:\Program Files\RealVNC\RealVNC Connect\rvncconnect.exe"),
        ("connect",  r"C:\Program Files (x86)\RealVNC\RealVNC Connect\rvncconnect.exe"),
        ("connect",  r"C:\Program Files\RealVNC\VNC Connect\rvncconnect.exe"),
        ("tigervnc", r"C:\Program Files\TigerVNC\vncviewer.exe"),
        ("tightvnc", r"C:\Program Files\TightVNC\tvnviewer.exe"),
        ("tightvnc", r"C:\Program Files (x86)\TightVNC\tvnviewer.exe"),
        ("ultravnc", r"C:\Program Files\UltraVNC\vncviewer.exe"),
    ]

    @classmethod
    def _local_candidates(cls):
        """"当前路径"候选：app 目录内置/自动下载产物。返回 [(path, kind)]。"""
        app_dir = _app_dir()
        cands = []
        classic = os.path.join(app_dir, "vncviewer.exe")
        if os.path.isfile(classic) and os.path.getsize(classic) > 0:
            cands.append((classic, "realvnc"))
        auto = os.path.join(app_dir, "vnc_auto", "rvncconnect.exe")
        if os.path.isfile(auto) and os.path.getsize(auto) > 0:
            cands.append((auto, "connect"))
        if hasattr(sys, '_MEIPASS'):
            b = os.path.join(sys._MEIPASS, "vncviewer.exe")
            if os.path.isfile(b) and os.path.getsize(b) > 0:
                cands.append((b, "realvnc"))
        # tb 环境: 模块目录旁可能是已解压产物
        for cand in (classic, auto):
            if cand not in (p for p, _ in cands):
                if os.path.isfile(cand) and os.path.getsize(cand) > 0:
                    cands.append((cand, _guess_kind_from_path(cand)))
        return cands

    @classmethod
    def _system_candidates(cls):
        """系统已装候选：注册表扫描 + 常见安装路径。返回 [(path, kind)]。"""
        cands = []
        seen = set()
        for exe, kind in _registry_vnc_probe():
            key = os.path.normcase(exe)
            if key not in seen:
                seen.add(key)
                cands.append((exe, kind))
        for kind, path in cls.COMMON_PATHS:
            key = os.path.normcase(path)
            if key not in seen and os.path.isfile(path) and os.path.getsize(path) > 0:
                seen.add(key)
                cands.append((path, kind))
        return cands

    @classmethod
    def find_vncviewer(cls, try_download=True):
        """定位 VNC 客户端，返回 (path, kind)；找不到返回 None。

        优先级：当前路径(内置/自动下载) -> 系统注册表/常见路径 -> 官方源自动下载。
        """
        for path, kind in cls._local_candidates():
            return path, kind
        for path, kind in cls._system_candidates():
            return path, kind
        if try_download:
            fetched = auto_fetch_vncviewer()
            if fetched and os.path.isfile(fetched) and os.path.getsize(fetched) > 0:
                return fetched, _guess_kind_from_path(fetched)
        return None

    @classmethod
    def launch(cls, ip, port=5999, res_mode="1280x720"):
        found = cls.find_vncviewer()
        target = f"{ip}:{port}"

        if not found:
            return False, f"找不到本地 VNC 客户端，请手动连接: {target}"
        vnc_bin, kind = found

        scaling_val = res_mode if res_mode != "direct" else "AspectFit"
        temp_vnc = os.path.join(tempfile.gettempdir(), f"pve_vm_{port}.vnc")
        vnc_content = f"""[Connection]
Host={target}
Scaling={scaling_val}
FullScreen=0
AutoReconnect=1
"""
        try:
            with open(temp_vnc, "w", encoding="utf-8") as f:
                f.write(vnc_content)
        except Exception:
            temp_vnc = None

        # 按品牌选择 argv：RealVNC/TightVNC 支持 -config；其余优先 host:port 直连
        if kind in ("tigervnc", "ultravnc", "connect"):
            attempts = [[vnc_bin, target]]
            if temp_vnc:
                attempts.append([vnc_bin, "-config", temp_vnc])
            attempts.append([vnc_bin, "-connect", target])
        else:
            attempts = []
            if temp_vnc:
                attempts.append([vnc_bin, "-config", temp_vnc])
                attempts.append([vnc_bin, temp_vnc])
            attempts.append([vnc_bin, target])

        last_err = None
        for argv in attempts:
            try:
                subprocess.Popen(argv)
                return True, f"已呼出 VNC 窗口 ({res_mode} / {kind}): {target}"
            except Exception as ex:
                last_err = ex
        return False, f"呼出 VNC 失败: {last_err} | 请手动连接: {target}"