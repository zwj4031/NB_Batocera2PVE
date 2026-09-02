#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""方案2: 202(实体声卡 HDA) 双路音频补部署 —— Pulse 先拿 hw:0 (本地+串流同源) + use_tsched=0/fragments 修 POLLOUT。
复用 pve_deploy_bundle 的 _deploy_audio, 不重传 46MB 引擎, 部署完需重启盒子让 .xinitrc AUDIO_PREES 生效。

用法:
    python deploy_audio_202.py [IP] [密码]
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modules"))
import paramiko
import pve_deploy_bundle as B
import pve_deploy_install as I

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


class _Log(B._DeployBundleMixin, I._DeployInstallMixin, object):
    def log_append(self, m):
        print(m)

    def update_progress(self, *a, **k):
        pass


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.11.202"
    pwd = sys.argv[2] if len(sys.argv) > 2 else "linux"

    print(f"[*] SSH -> root@{ip}:22")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(ip, port=22, username="root", password=pwd, timeout=12,
                look_for_keys=False, allow_agent=False)
    print("[+] 已连接")

    obj = _Log()
    obj._deploy_audio(ssh, ip)

    # 核验落盘
    code, out, _ = B.run_sync_cmd(ssh, "ls -l /userdata/system/.xinitrc; grep -n 'AUDIO_PREES' /userdata/system/.xinitrc | head; grep -n 'AUDIO_PREP' /userdata/system/custom.sh | head; echo ---asound---; cat /etc/asound.conf; echo ---plugins---; ls -l /usr/lib/alsa-lib/ 2>/dev/null; ls -l /usr/lib/x86_64-linux-gnu/alsa-lib/ 2>/dev/null")
    print("[核验落盘]\n" + out)

    code, sink, _ = B.run_sync_cmd(ssh,
        "export LD_LIBRARY_PATH=/userdata/system/pulse/lib PATH=/userdata/system/pulse/bin:$PATH "
        "PULSE_SERVER=unix:/var/run/pulse/native; pactl list short sinks 2>&1; echo '---sources---'; "
        "pactl list short sources 2>&1")
    print("[核验 sinks/sources]\n" + sink)

    ssh.close()
    print("\n[+] 音频补部署完成。请重启盒子 (reboot), 让 .xinitrc AUDIO_PREES 在 ES 启动前先把 Pulse 拉起拿到 hw:0。")


if __name__ == "__main__":
    main()