#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nb_pve 音频链路自动修补脚本 (Windows 11 运行, 仅需 git + 标准库)

功能:
  1) 精准修复 modules/pve_deploy_bundle.py 与 modules/pve_deploy_install.py 的音频链路:
     - pve_deploy_bundle.py: system.pa 显式创建 sink-sunshine-stereo 虚拟声卡并设为默认
       sink/source (原实现依赖 Sunshine 自动创建, 实测其不会创建, 导致仅有 auto_null 且无声);
       audio_setup.sh 增加 set-sink-volume 100% 防静音。
     - pve_deploy_install.py: batocera.conf 缺失/为 0 时补 audio.volume=100, 修复 ES 音量滑块弹回 0。
  2) 清除目标文件中"多余连续空行"(>=2 合并为 1, 且不破坏三引号字符串内容), 报告清理行数。
  3) 自动 py_compile 校验, 然后 git add 指定文件并 commit。

幂等性: 已修复(存在新标记)则跳过对应修补; 可反复运行。
注意:
  - 本脚本只改本地代码, 不触碰 184 盒; 盒上重新部署请另跑 tools/deploy_audio_184.py。
  - 若仓库位于云同步盘(如 OneDrive/坚果云), git 的索引原子 rename 会被同步软件拦截
    (fatal: Unable to write new index file)。脚本会自动改用本地临时索引完成提交, 并回写 .git/index。

用法:
    python tools/fix_audio_chain.py
"""
import os
import re
import sys
import subprocess

ROOT = os.path.dirname(os.path.abspath(__file__))          # .../nb_pve/tools
REPO = os.path.dirname(ROOT)                                # .../nb_pve
BUNDLE = os.path.join(REPO, "modules", "pve_deploy_bundle.py")
INSTALL = os.path.join(REPO, "modules", "pve_deploy_install.py")
DEPLOY184 = os.path.join(REPO, "tools", "deploy_audio_184.py")
SELF = os.path.abspath(__file__)

PY38 = "S:/Python/Python38/python.exe"
PY = PY38 if os.path.exists(PY38) else sys.executable


def log(msg):
    try:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8"))
    except Exception:
        print(msg)


# --------------------------------------------------------------------------
# 1) 精准修复
# --------------------------------------------------------------------------
def fix_bundle(content):
    changed = False
    if "sink_name=sink-sunshine-stereo" not in content:
        pat = re.compile(r"(        pa = \(.*?\n        \)\n)", re.DOTALL)
        new_block = (
            "        pa = (\n"
            "            \"load-module module-native-protocol-unix auth-anonymous=1\\n\"\n"
            "            \"# 显式创建 Sunshine 专用虚拟声卡(不再依赖 Sunshine 自动创建, 实测其不会创建)。\\n\"\n"
            "            \"# 所有应用音频默认路由到此 sink, Sunshine 捕获其监听源 sink-sunshine-stereo.monitor 推向 Moonlight。\\n\"\n"
            "            # 必须禁用 suspend-on-idle, 否则空闲时 monitor 挂起 -> Sunshine 抓不到音频轨 -> Moonlight 画面快进/无声。\n"
            "            \"load-module module-default-device-restore\\n\"\n"
            "            \"load-module module-always-sink\\n\"\n"
            "            \"load-module module-null-sink sink_name=sink-sunshine-stereo sink_properties=device.description=SunshineSink rate=48000 channels=2\\n\"\n"
            "            \"set-default-sink sink-sunshine-stereo\\n\"\n"
            "            \"set-default-source sink-sunshine-stereo.monitor\\n\"\n"
            "        )\n"
        )
        new_content, n = pat.subn(new_block, content, count=1)
        if n:
            content = new_content
            changed = True
            log("[fix] pve_deploy_bundle.py: system.pa 已显式创建 sink-sunshine-stereo")
        else:
            log("[!] pve_deploy_bundle.py: 未匹配到 pa = (...) 块, 跳过")
    else:
        log("[skip] pve_deploy_bundle.py: sink-sunshine-stereo 已存在, 无需修补")

    if "pactl set-sink-volume sink-sunshine-stereo 100%" not in content:
        old = "            \"pactl set-default-source sink-sunshine-stereo.monitor 2>/dev/null\\n\"\n"
        new = old + "            \"pactl set-sink-volume sink-sunshine-stereo 100% 2>/dev/null\\n\"\n"
        if old in content:
            content = content.replace(old, new, 1)
            changed = True
            log("[fix] pve_deploy_bundle.py: audio_setup.sh 增加 set-sink-volume 100%")
        else:
            log("[!] pve_deploy_bundle.py: 未匹配 audio_setup.sh 默认源行, 跳过音量加固")
    else:
        log("[skip] pve_deploy_bundle.py: set-sink-volume 已存在, 无需修补")
    return content, changed


def fix_install(content):
    changed = False
    if "6.0.2" not in content:
        anchor = (
            "                run_sync_cmd(\n"
            "                    bato_ssh,\n"
            "                    \"grep -q '^audio.device=' /userdata/system/batocera.conf && \"\n"
            "                    \"sed -i 's/^audio.device=.*/audio.device=default/' /userdata/system/batocera.conf || \"\n"
            "                    \"echo 'audio.device=default' >> /userdata/system/batocera.conf\"\n"
            "                )\n"
        )
        block = anchor + (
            "                # 6.0.2 修复 ES 音量滑块弹回 0: batocera.conf 的 audio.volume 缺失或被置 0 时, ES 读回 0 并弹回。\n"
            "                # 仅当缺失或等于 0 时补成 100, 不覆盖用户已设置的正常值。\n"
            "                run_sync_cmd(\n"
            "                    bato_ssh,\n"
            "                    \"grep -q '^audio.volume=' /userdata/system/batocera.conf || echo 'audio.volume=100' >> /userdata/system/batocera.conf; \"\n"
            "                    \"grep -q '^audio.volume=0' /userdata/system/batocera.conf && sed -i 's/^audio.volume=0/audio.volume=100/' /userdata/system/batocera.conf\"\n"
            "                )\n"
        )
        if anchor in content:
            content = content.replace(anchor, block, 1)
            changed = True
            log("[fix] pve_deploy_install.py: 增加 audio.volume=100 修补 (修复 ES 滑块弹回 0)")
        else:
            log("[!] pve_deploy_install.py: 未匹配 audio.device 锚点, 跳过 audio.volume 修补")
    else:
        log("[skip] pve_deploy_install.py: 6.0.2 已存在, 无需修补")
    return content, changed


# --------------------------------------------------------------------------
# 2) 清除多余连续空行 (字符串感知, 不破坏三引号内文本)
# --------------------------------------------------------------------------
def clean_blank_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    out = []
    blank_run = 0
    in_str = None
    removed = 0

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if '"""' in line and line.count('"""') % 2 == 1:
            in_str = None if in_str == '"""' else '"""'
        elif "'''" in line and line.count("'''") % 2 == 1:
            in_str = None if in_str == "'''" else "'''"

        is_blank = (stripped == "")
        if is_blank and in_str is None:
            blank_run += 1
            if blank_run >= 2:
                removed += 1
                i += 1
                continue
        else:
            blank_run = 0
        out.append(line)
        i += 1

    if removed:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(out)
    return removed


# --------------------------------------------------------------------------
# 3) 校验 + 提交 (兼容云同步盘索引写入失败)
# --------------------------------------------------------------------------
def py_compile_check(path):
    r = subprocess.run([PY, "-m", "py_compile", path],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        log("[!] py_compile 失败: " + path)
        log(r.stderr.decode("utf-8", "ignore"))
        return False
    return True


def git_commit(files, msg):
    """优先常规提交; 若同步盘拦截索引写入, 改用本地临时索引 + 回写 .git/index。"""
    # 常规尝试
    r = subprocess.run(["git", "add", *files], cwd=REPO,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if b"Unable to write new index file" not in r.stderr:
        rc = subprocess.run(["git", "commit", "-m", msg], cwd=REPO,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = rc.stdout.decode("utf-8", "ignore") + rc.stderr.decode("utf-8", "ignore")
        log(out.strip())
        if "nothing to commit" in out or rc.returncode == 0:
            return 0
        return rc.returncode

    # 回退: 本地临时索引
    log("[*] 检测到同步盘拦截索引写入, 改用本地临时索引提交...")
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "nb_pve_git_index")
    env = dict(os.environ, GIT_INDEX_FILE=tmp)
    if os.path.exists(tmp):
        os.remove(tmp)
    subprocess.run(["git", "read-tree", "HEAD"], cwd=REPO, env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    subprocess.run(["git", "add", *files], cwd=REPO, env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    rc = subprocess.run(["git", "commit", "-m", msg], cwd=REPO, env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = rc.stdout.decode("utf-8", "ignore") + rc.stderr.decode("utf-8", "ignore")
    log(out.strip())
    if "nothing to commit" in out:
        return 0
    # 回写 .git/index 保持仓库一致
    try:
        with open(tmp, "rb") as f:
            data = f.read()
        with open(os.path.join(REPO, ".git", "index"), "wb") as f:
            f.write(data)
        log("[*] 已回写 .git/index")
    except Exception as e:
        log("[!] 回写 .git/index 失败(可忽略, 提交已完成): " + str(e))
    return rc.returncode


def main():
    log("=== nb_pve 音频链路自动修补 ===")

    targets = [BUNDLE, INSTALL]
    total_removed = 0
    any_changed = False

    for path in targets:
        if not os.path.exists(path):
            log("[!] 找不到: " + path)
            continue
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        if path == BUNDLE:
            content, ch = fix_bundle(content)
        else:
            content, ch = fix_install(content)
        any_changed = any_changed or ch

        if ch:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

        removed = clean_blank_lines(path)
        total_removed += removed
        log("[clean] %s: 清除多余空行 %d 行" % (os.path.relpath(path, REPO), removed))

    log("[clean] 共清除多余空行 %d 行" % total_removed)

    ok = True
    for path in targets:
        if not py_compile_check(path):
            ok = False
    if not ok:
        log("[!] 校验未通过, 已中止提交 (请人工检查)")
        sys.exit(1)

    msg = (
        "fix(audio): 显式创建 sink-sunshine-stereo 虚拟声卡并修复 ES 音量弹回 0\n\n"
        "- pve_deploy_bundle: system.pa 显式建 sink-sunshine-stereo 并设为默认 sink/source; "
        "audio_setup.sh 加固 set-sink-volume 100%\n"
        "- pve_deploy_install: batocera.conf 缺失/为0时补 audio.volume=100 (修复滑块弹回0)\n"
        "- tools/deploy_audio_184.py 改用 _DeployBundleMixin 基类以继承 PULSE_DEB_NAMES 等常量\n"
        "- 新增 tools/fix_audio_chain.py 自动修补脚本\n"
        "- 清理多余空行 " + str(total_removed) + " 行"
    )

    log("=== git 提交 ===")
    rc = git_commit(
        [os.path.relpath(BUNDLE, REPO), os.path.relpath(INSTALL, REPO),
         os.path.relpath(DEPLOY184, REPO), os.path.relpath(SELF, REPO)],
        msg,
    )
    if rc != 0:
        log("[!] git commit 返回非零, 请检查")
        sys.exit(1)
    log("=== 完成 ===")


if __name__ == "__main__":
    main()
