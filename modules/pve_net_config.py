import json
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor

CONFIG_FILE = "config.json"

class ConfigManager:
    @staticmethod
    def save(data):
        try:
            cur = ConfigManager.load() or {}
            cur.update(data)
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(cur, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"[-] 保存配置失败: {e}")

    @staticmethod
    def load():
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"[-] 读取配置失败: {e}")
        return {}

    @staticmethod
    def get_vm_info(vmid):
        cfg = ConfigManager.load() or {}
        return (cfg.get("vm_cache") or {}).get(str(vmid), {})

    @staticmethod
    def save_vm_info(vmid, ip=None, macs=None, os_info=None):
        try:
            cfg = ConfigManager.load() or {}
            vm_cache = cfg.setdefault("vm_cache", {})
            ent = vm_cache.setdefault(str(vmid), {})
            if ip: ent["ip"] = ip
            if macs: ent["macs"] = list(macs) if isinstance(macs, (list, set)) else [macs]
            if os_info: ent["os"] = os_info
            ent["updated_at"] = int(time.time())
            ConfigManager.save({"vm_cache": vm_cache})
        except Exception as e:
            print(f"[-] 缓存 VM 信息失败: {e}")

class PveScanner:
    @staticmethod
    def get_local_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "192.168.1.1"

    @staticmethod
    def check_port(ip, port=8006, timeout=0.8):
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return ip
        except Exception:
            return None

    @staticmethod
    def scan_network(callback):
        local_ip = PveScanner.get_local_ip()
        subnet = ".".join(local_ip.split('.')[:-1])
        found_ips = []

        def scan_task(i):
            target = f"{subnet}.{i}"
            if PveScanner.check_port(target):
                found_ips.append(target)

        with ThreadPoolExecutor(max_workers=50) as executor:
            for i in range(1, 255):
                executor.submit(scan_task, i)

        found_ips.sort(key=lambda x: int(x.split('.')[-1]))
        callback(found_ips)