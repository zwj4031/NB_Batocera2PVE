#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只给已在运行 Sunshine 的 Batocera 盒 (默认 192.168.11.184) 补部署音频链,
复用 pve_stream 里已验证过的 _deploy_audio, 不重传 46MB 引擎, 部署完重启 Sunshine 使其捕获 SunshineSink。

用法:
    python deploy_audio_184.py [IP] [密码]
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modules"))
import paramiko
import pve_stream as P

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def safe_print(*a):
    s = " ".join(str(x) for x in a)
    try:
        sys.stdout.buffer.write((s + "\n").encode("utf-8"))
    except Exception:
        print(s.encode("gbk", "ignore").decode("gbk"))


class _Log(P.SunshineInstallerDialog.__bases__[1]):
    def log_append(self, m):
        safe_print(m)


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.11.184"
    pwd = sys.argv[2] if len(sys.argv) > 2 else "linux"

    print(f"[*] SSH -> root@{ip}:22")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ip, port=22, username="root", password=pwd, timeout=12,
                look_for_keys=False, allow_agent=False)
    print("[+] 已连接")

    obj = _Log()
    # 绑定 pve_stream 里的实例方法到本轻量对象 (其仅依赖 self.log_append / self._extract_deb_bytes)
    obj._ensure_pulse_bundle = P.SunshineInstallerDialog._ensure_pulse_bundle.__get__(obj)
    obj._extract_deb_bytes = P.SunshineInstallerDialog._extract_deb_bytes.__get__(obj)
    obj._deploy_audio = P.SunshineInstallerDialog._deploy_audio.__get__(obj)

    print("[*] 部署私有 PulseAudio + SunshineSink 虚拟声卡...")
    obj._deploy_audio(ssh, ip)

    print("[*] 重启 Sunshine, 使其捕获新的 SunshineSink 监听源...")
    P.run_sync_cmd(ssh, "bash /userdata/system/services/sunshine restart > /dev/null 2>&1 || true")

    # 核验
    code, out, _ = P.run_sync_cmd(
        ssh,
        "export LD_LIBRARY_PATH=/userdata/system/pulse/lib PATH=/userdata/system/pulse/bin:$PATH "
        "PULSE_SERVER=unix:/var/run/pulse/native; pactl list short sinks 2>&1; echo '---sources---'; "
        "pactl list short sources 2>&1")
    print("[核验 sinks/sources]\n" + out)

    ssh.close()
    print("[+] 音频补部署完成。请用 Moonlight / 浏览器重新串流测试声音。")


if __name__ == "__main__":
    main()
