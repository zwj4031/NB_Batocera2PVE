#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""184 Batocera Sunshine 视频捕获诊断: SSH 拉取 Sunshine 日志/配置/DRM/X11 关键状态,
帮助定位串流端「failed to initialize video capture」的根因.

用法:
    python diag_sunshine_capture_184.py [IP] [密码]
"""
import sys
import paramiko

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.11.184"
PWD = sys.argv[2] if len(sys.argv) > 2 else "linux"

CHECKS = [
    ("sunshine 进程与命令行", "echo '== ps =='; ps -eo pid,args | grep -i sunshine | grep -v grep || echo '(sunshine 未运行)'; echo '== env(DISPLAY等) =='; for pid in $(pgrep -x sunshine | head -1); do tr '\\0' '\\n' < /proc/$pid/environ 2>/dev/null | grep -iE 'DISPLAY|XAUTH|LIBGL|GALLIUM|MESA|SDL' ; done"),
    ("sunshine 日志文件", "echo '== /tmp logs =='; ls -lt /tmp/sunshine*.log 2>/dev/null | head -5; echo '== ~/.config/sunshine =='; ls -l /userdata/system/.config/sunshine/ 2>/dev/null"),
    ("sunshine 最近日志: 错误/捕获/编码", "for f in $(ls -t /tmp/sunshine*.log 2>/dev/null | head -2); do echo \"===== $f =====\"; grep -inE 'failed|error|warn|capture|video|encoder|kms|drm|v4l2|egl|xshm|x11|glx|avcodec|pipeline' \"$f\" | tail -40; done"),
    ("sunshine conf 关键项", "for f in $(find /userdata/system -name 'sunshine.conf' 2>/dev/null); do echo \"--- $f ---\"; grep -inE 'encoder|capture|video|adapter|output|display|ffmpeg|bitrate|fps|codec' \"$f\" 2>/dev/null; done; echo '(end)'"),
    ("DRM 设备 (/dev/dri)", "echo '== /dev/dri =='; ls -l /dev/dri/ 2>&1; echo '== drm 内核驱动 =='; lsmod 2>/dev/null | grep -iE 'virtio_gpu|drm|virgl|vmwgfx' || echo '(无相关模块信息)'; echo '== drmInfo =='; (drm_info 2>&1 | head -20) || echo '(无 drm_info)'"),
    ("显卡内核日志", "echo '== dmesg drm/virtio =='; dmesg 2>/dev/null | grep -iE 'drm|virtio_gpu|virgl|modeset' | tail -20 || echo '(dmesg 不可用)'"),
    ("X11 会话与屏幕", "echo '== X =='; ls -l /tmp/.X11-unix/ 2>&1; XAUTHORITY=/var/lib/.Xauthority DISPLAY=:0 xdpyinfo 2>&1 | grep -E 'dimensions|depth of root' | head -3 || echo '(xdpyinfo 不可用)'"),
    ("GPU 渲染库 (GL/EGL)", "echo '== glxinfo =='; DISPLAY=:0 glxinfo 2>&1 | grep -iE 'renderer|direct rendering|OpenGL version' | head -5 || echo '(glxinfo 不可用)'"),
    ("ffmpeg/libx264 软解能力", "echo '== libx264 =='; ffmpeg -version 2>/dev/null | head -1 || echo '(ffmpeg 不在 PATH)'"),
    ("Sunshine 服务状态", "echo '== services/sunshine status =='; bash /userdata/system/services/sunshine status 2>&1 | head -8"),
]


def run(ssh, cmd, timeout=25):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    return (out + err).strip()


def main():
    print(f"[*] 连接 {IP} ...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(IP, 22, "root", PWD, timeout=12, look_for_keys=False, allow_agent=False)
    print("[+] 已连接\n")
    for title, cmd in CHECKS:
        print("=" * 60)
        print(f"# {title}")
        print("-" * 60)
        try:
            print(run(ssh, cmd))
        except Exception as e:
            print(f"[!] 检查失败: {e}")
        print()
    ssh.close()
    print("=" * 60)
    print("[*] 诊断结束")
    print("提示: 关注 sunshine 日志里的 capture backend(如 KMS/DRM/EGL/XShm) 与具体失败行;")
    print("      virtio-gpu + virgl 不受宿主支持时, DRM/KMS 捕获常失败, 应回退 X11/XShm 帧抓取。")


if __name__ == "__main__":
    main()