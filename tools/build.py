import os
import sys
import subprocess
import shutil

PYTHON_PATH = r"S:\python\Python38\python.exe"
ICON_PATH = os.path.join("winres", "main.ico")
VNC_PATH = "vncviewer.exe"
MAIN_SCRIPT = "pve.py"
APP_NAME = "NB宗_PVE_Batocera部署管理器"

def build():
    print("=" * 65)
    print("⚡ NB宗 · PVE Batocera 一键编译打包构建引擎 (2026终极神教版)")
    print("=" * 65)

    # 1. 锁定 Python 解释器
    if os.path.exists(PYTHON_PATH):
        py_bin = PYTHON_PATH
        print(f"[+] 锁定指定 Python 环境: {py_bin}")
    else:
        py_bin = sys.executable
        print(f"[*] 未在 {PYTHON_PATH} 找到环境，使用当前解释器: {py_bin}")

    # 2. 检查并安装 PyInstaller
    print("[*] 正在检查 PyInstaller 打包套件...")
    try:
        subprocess.run([py_bin, "-m", "pip", "show", "pyinstaller"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("[*] 正在通过清华镜像源安装 PyInstaller...")
        subprocess.run([py_bin, "-m", "pip", "install", "pyinstaller", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"], check=True)

    # 3. 构建参数
    cmd = [
        py_bin, "-m", "PyInstaller",
        "--noconsole",
        "--onefile",
        f"--name={APP_NAME}",
        "--clean",
        "--noconfirm",
    ]

    # 4. 挂载图标
    if os.path.exists(ICON_PATH):
        cmd.append(f"--icon={ICON_PATH}")
        print(f"[+] 挂载应用程序图标: {ICON_PATH}")
    else:
        print(f"[-] 提示: 未在 {ICON_PATH} 检测到图标文件，将使用默认图标。")

    # 5. 打包注入 vncviewer.exe
    if os.path.exists(VNC_PATH):
        cmd.append(f"--add-data={VNC_PATH};.")
        print(f"[+] 成功将 [{VNC_PATH}] 注入单文件内置资源！")
    else:
        common_vnc = r"C:\Program Files\RealVNC\VNC Viewer\vncviewer.exe"
        if os.path.exists(common_vnc):
            shutil.copy2(common_vnc, VNC_PATH)
            cmd.append(f"--add-data={VNC_PATH};.")
            print(f"[+] 自动从系统中提取并注入: {common_vnc}")
        else:
            print(f"[-] 警告: 未在当前目录找到 {VNC_PATH}，请确保放置后再打包以获得最佳开箱即用体验！")

    cmd.append(MAIN_SCRIPT)

    # 6. 开始编译打包
    print(f"[*] 正在全速编译打包 ({MAIN_SCRIPT} ➡️ dist/{APP_NAME}.exe) ...")
    res = subprocess.run(cmd)

    if res.returncode == 0:
        dist_exe = os.path.join("dist", f"{APP_NAME}.exe")
        print("\n" + "=" * 65)
        print("🎉 恭喜！NB宗 独立单文件版构建全部成功！")
        print(f"📦 单文件 EXE 位置: {os.path.abspath(dist_exe)}")
        print("💡 运行时将全自动检测并释放 vncviewer.exe (文件若已存在则绝不重复释放)！")
        print("=" * 65)
    else:
        print("[-] 编译构建失败，请查看上方详细日志。")

if __name__ == "__main__":
    build()
