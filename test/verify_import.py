# -*- coding: utf-8 -*-
"""验证整合: 把 modules/ 插入 sys.path 后, 根目录仅 pve.py 也能 import 全部业务模块。
用法: S:\Python\Python38\python.exe test\verify_import.py
"""
import os, sys, ast

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(ROOT, "modules")
sys.path.insert(0, MOD)
sys.path.insert(0, ROOT)

# 1. 语法检查 modules/ 下全部 .py
print("== 1. modules/ 语法检查 ==")
bad = []
for f in sorted(os.listdir(MOD)):
    if f.endswith(".py"):
        try:
            ast.parse(open(os.path.join(MOD, f), encoding="utf-8").read(), filename=f)
        except Exception as e:
            bad.append((f, str(e)))
print("  parsed %d files -> %s" % (len([f for f in os.listdir(MOD) if f.endswith('.py')]),
                                   "ALL OK" if not bad else repr(bad)))

# 2. 尝试实际 import pve.py 依赖的全部模块
print("== 2. 实际 import 业务模块 ==")
mods = ["pve_net_config", "pve_stream", "pve_ui_dialogs", "pve_local_mgr", "pve_vnc",
        "pve_bato_net", "pve_bato_console", "pve_host_net", "pve_create_vm"]
ok, fail = [], []
for m in mods:
    try:
        __import__(m)
        ok.append(m)
    except Exception as e:
        fail.append((m, "%s: %s" % (type(e).__name__, e)))
print("  imported: %s" % ", ".join(ok))
print("  FAILED  : %s" % (repr(fail) if fail else "(none)"))

# 3. 关键符号存在性
print("== 3. 关键符号检查 ==")
checks = [
    ("pve_stream", "SunshineInstallerDialog"),
    ("pve_ui_dialogs", "HardwareConfigDialog"),
    ("pve_ui_dialogs", "PciPassthroughDialog"),
    ("pve_bato_console", "BatoceraConsoleDialog"),
    ("pve_bato_net", "detect_vm_ip"),
    ("pve_vnc", "VncLauncher"),
    ("pve_local_mgr", "LocalManagerTab"),
    ("pve_host_net", "PveHostNetworkDialog"),
    ("pve_create_vm", "CreateVmDialog"),
    ("pve_net_config", "ConfigManager"),
]
miss = []
for mod, sym in checks:
    m = sys.modules.get(mod)
    if m is None or not hasattr(m, sym):
        miss.append("%s.%s" % (mod, sym))
print("  missing: %s" % (repr(miss) if miss else "(none)"))
print("\n[RESULT]", "PASS" if not bad and not fail and not miss else "FAIL")