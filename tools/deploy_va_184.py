import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modules"))
import paramiko, pve_stream as P

ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.11.184"
pwd = sys.argv[2] if len(sys.argv) > 2 else "linux"
cache = r"M:\同步\顶点home\2026研究PE专用\AI项目\nb_pve\cache\sunshine_va.tar.gz"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(ip, 22, "root", pwd, timeout=12, look_for_keys=False, allow_agent=False)
print("[+] connected")

# 1) 上传修正后的 VAAPI 驱动包
sftp = ssh.open_sftp()
print("[*] 上传 sunshine_va.tar.gz ...")
sftp.put(cache, "/userdata/system/va.tar.gz")
sftp.close()

# 2) 解包到 /userdata/system/va/lib (与正式部署第5.4步一致)
code, out, _ = P.run_sync_cmd(
    ssh,
    "mkdir -p /userdata/system/va/lib/dri && gzip -dc /userdata/system/va.tar.gz | tar -xf - -C /userdata/system/va/lib "
    "&& chmod 755 /userdata/system/va/lib/* /userdata/system/va/lib/dri/* 2>/dev/null; rm -f /userdata/system/va.tar.gz")
_, lsout, _ = P.run_sync_cmd(ssh, "ls -lh /userdata/system/va/lib/ /userdata/system/va/lib/dri/ 2>/dev/null")
print("[va/lib]\n" + lsout.strip())

# 3) 重启 Sunshine 使其加载 iHD 硬解
P.run_sync_cmd(ssh, "bash /userdata/system/services/sunshine restart > /dev/null 2>&1 || true")
_, sstat, _ = P.run_sync_cmd(ssh, "pgrep -af usr/bin/sunshine | head -1")
print("[sunshine]", sstat.strip())

# 4) 核验 iHD 能被 VA 识别 (若盒上有 vainfo 则做一次探测)
_, vout, _ = P.run_sync_cmd(ssh, "export LD_LIBRARY_PATH=/userdata/system/va/lib:/userdata/system/pulse/lib:$LD_LIBRARY_PATH; export LIBVA_DRIVER_NAME=iHD; which vainfo >/dev/null 2>&1 && vainfo 2>&1 | head -8 || echo '(vainfo 未安装, 跳过探测)'")
print("[vainfo]\n" + vout.strip())
ssh.close()
print("[+] VAAPI 驱动包已更新并重启 Sunshine。")
