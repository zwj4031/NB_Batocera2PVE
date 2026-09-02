#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""184 Batocera 音频链路诊断: SSH 拉取 PulseAudio / ALSA / Batocera / Sunshine 全链路状态,
帮助定位「串流无声音」与「ES 音量滑块掉回 0」的根因。

用法:
    python audio_diag_184.py [IP] [密码]
"""
import sys
import paramiko

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.11.184"
PWD = sys.argv[2] if len(sys.argv) > 2 else "linux"

CHECKS = [
    ("batocera-audio get/list", "echo '== batocera-audio =='; batocera-audio get 2>&1; echo '---'; batocera-audio list 2>&1"),
    ("batocera.conf audio.*", "echo '== batocera.conf audio =='; grep -i audio /userdata/system/batocera.conf 2>/dev/null || echo '(无 audio 配置)'"),
    ("pulse socket", "echo '== pulse socket =='; ls -l /var/run/pulse/native 2>&1"),
    ("pulse process", "echo '== ps pulse =='; ps | grep -i pulse | grep -v grep || echo '(pulse 未运行)'"),
    ("pulse sinks", "echo '== sinks =='; PULSE_LIB=/userdata/system/pulse/lib; LD_LIBRARY_PATH=$PULSE_LIB /userdata/system/pulse/bin/pactl --server=unix:/var/run/pulse/native list short sinks 2>&1"),
    ("pulse sources", "echo '== sources =='; PULSE_LIB=/userdata/system/pulse/lib; LD_LIBRARY_PATH=$PULSE_LIB /userdata/system/pulse/bin/pactl --server=unix:/var/run/pulse/native list short sources 2>&1"),
    ("pulse default sink/source", "echo '== default =='; PULSE_LIB=/userdata/system/pulse/lib; LD_LIBRARY_PATH=$PULSE_LIB /userdata/system/pulse/bin/pactl --server=unix:/var/run/pulse/native get-default-sink 2>&1; PULSE_LIB=/userdata/system/pulse/lib; LD_LIBRARY_PATH=$PULSE_LIB /userdata/system/pulse/bin/pactl --server=unix:/var/run/pulse/native get-default-source 2>&1"),
    ("amixer Master (ctl=pulse)", "echo '== amixer Master =='; PULSE_SERVER=unix:/var/run/pulse/native amixer sget Master 2>&1"),
    ("PULSE_CTL_LIBS in /usr/lib", "echo '== /usr/lib 关键库 =='; ls -l /usr/lib/libcap.so.2 /usr/lib/libXtst.so.6 /usr/lib/libsystemd.so.0 /usr/lib/libwrap.so.0 /usr/lib/libasyncns.so.0 /usr/lib/libnsl.so.1 2>&1"),
    ("system.pa 内容", "echo '== system.pa =='; cat /userdata/system/pulse/system.pa 2>&1"),
    ("custom.sh 块标记", "echo '== custom.sh 块 =='; grep -n 'PULSE_CTL_LIBS\\|EXPOSE_PULSE_PLUGIN\\|AUDIO_PULSE_SETUP\\|SUNSHINE_BOOT' /userdata/system/custom.sh 2>&1"),
    ("ES volume 设置", "echo '== es_settings 音量 =='; grep -i -a 'volume\\|audio' /userdata/system/.emulationstation/es_settings.cfg 2>/dev/null || echo '(无 volume 设置)'"),
    ("RetroArch 音频设置", "echo '== retroarch audio =='; grep -i -a 'audio_' /userdata/system/.config/retroarch/retroarch.cfg 2>/dev/null | head -20 || echo '(无 retroarch.cfg)'"),
    ("Sunshine 状态", "echo '== sunshine =='; bash /userdata/system/services/sunshine status 2>&1 | head -5"),
    ("Sunshine conf 音频", "echo '== sunshine conf =='; for f in $(find /userdata/system -name 'sunshine.conf' 2>/dev/null); do echo \"--- $f ---\"; grep -i -a 'pulse\\|audio\\|sink\\|source' $f 2>/dev/null | head -20; done; echo '(end)'"),
    ("asound.conf", "echo '== asound.conf =='; cat /userdata/system/pulse/asound.conf 2>/dev/null || cat /etc/asound.conf 2>/dev/null || echo '(无 asound.conf)'"),
]


def run(ssh, cmd, timeout=20):
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


if __name__ == "__main__":
    main()
