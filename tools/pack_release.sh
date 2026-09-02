#!/usr/bin/env bash
# =============================================================================
# NB_Batocera2PVE 一键打包脚本 (Linux / macOS / Git Bash)
#
# 用法:
#   ./pack_release.sh           # 产出 .tar.gz (7z 可用则额外产出 .7z)
#   ./pack_release.sh 7z        # 强制用 7z 打包 (需已安装 7z/7za)
#   ./pack_release.sh tgz       # 强制用 tar.gz
#
# 策略: 白名单复制到临时目录 -> 清理黑名单 -> 归档到 release/
#   * 包含: 源码 / LICENSE / README / 空模板 config.json.example / test / tools /
#           modules 全部业务模块 + cache(55MB) + pulse_cache(59MB) / pve_res / winres /
#           .github (CI workflow)
#   * 排除: config.json(真实密码/MAC/IP) AGENTS.md(内网凭据) vncviewer.exe(RealVNC专有)
#           .git/ bak/ Ai_Work/ build/ dist/ __pycache__/ *.pyc tools/_diag_boot_vol.py ai_studio_code.py
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="NB_Batocera2PVE"
VER="$(date +%Y%m%d-%H%M%S)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
OUTDIR="$ROOT/release"
DEST="$STAGE/$NAME"

echo "[*] 项目根 : $ROOT"
echo "[*] 暂存目录: $STAGE"

# ------------------------- 白名单复制 -------------------------
mkdir -p "$DEST/modules" "$DEST/pve_res" "$DEST/winres" "$DEST/test" "$DEST/tools" "$DEST/.github/workflows" "$OUTDIR"

# 根目录白名单文件 (不含 config.json / AGENTS.md / vncviewer.exe / ai_studio_code.py)
for f in pve.py build.py README.md LICENSE requirements.txt .gitignore config.json.example; do
    [ -f "$ROOT/$f" ] && cp "$f" "$DEST/" && echo "  [+] $f"
done

# modules 全套 (含 cache + pulse_cache), 之后统一清 __pycache__
cp -r "$ROOT/modules/." "$DEST/modules/"
echo "  [+] modules/ (含 cache + pulse_cache)"

cp -r "$ROOT/pve_res/." "$DEST/pve_res/"; echo "  [+] pve_res/ (GPL自写 stub)"
cp -r "$ROOT/winres/." "$DEST/winres/";   echo "  [+] winres/ (图标)"
cp -r "$ROOT/test/."  "$DEST/test/";      echo "  [+] test/ (模块自检)"

# tools/ 全量复制后剔除坏文件
cp -r "$ROOT/tools/." "$DEST/tools/"
rm -f "$DEST/tools/_diag_boot_vol.py"
echo "  [+] tools/ (已剔除 _diag_boot_vol.py)"

# .github (CI workflow)
cp -r "$ROOT/.github/." "$DEST/.github/"
echo "  [+] .github/ (CI workflow)"

# ------------------------- 清理黑名单 -------------------------
find "$DEST" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "$DEST" -name '*.pyc' -delete 2>/dev/null || true
rm -rf "$DEST/modules/vnc_auto" "$DEST/AGENTS.md" "$DEST/config.json" "$DEST/vncviewer.exe" "$DEST/ai_studio_code.py"
echo "[-] 已清理 __pycache__ / *.pyc / AGENTS.md / config.json / vncviewer.exe / modules/vnc_auto / ai_studio_code.py"

# ------------------------- 归档 -------------------------
cd "$STAGE"

want_7z=no
if [ "${1:-}" = "7z" ]; then want_7z=yes; fi

SEVENZ=""
command -v 7z   >/dev/null 2>&1 && SEVENZ="$(command -v 7z)"
[ -z "$SEVENZ" ] && command -v 7za >/dev/null 2>&1 && SEVENZ="$(command -v 7za)"
[ -z "$SEVENZ" ] && [ -x "/c/Program Files/7-Zip/7z.exe" ] && SEVENZ="/c/Program Files/7-Zip/7z.exe"

TARGZ="$OUTDIR/$NAME-$VER.tar.gz"

if [ "${1:-}" = "zip" ]; then
    echo "[*] zip 打包: $OUTDIR/$NAME-$VER.zip ..."
    tar -a -cf "$OUTDIR/$NAME-$VER.zip" "$NAME"
    echo "[+] ✅ 完成: $OUTDIR/$NAME-$VER.zip"
    exit 0
fi

if [ "$want_7z" = "yes" ] && [ -n "$SEVENZ" ]; then
    echo "[*] 7z 打包: $TARGZ (.7z) ..."
    "$SEVENZ" a -t7z "$OUTDIR/$NAME-$VER.7z" "$NAME" >/dev/null
elif [ "${1:-}" = "tgz" ] || [ -z "$SEVENZ" ] || [ "$want_7z" != "yes" ]; then
    echo "[*] tar.gz 打包: $TARGZ ..."
    tar --owner=0 --group=0 -czf "$TARGZ" "$NAME"
    if [ "$want_7z" = "yes" ]; then
        echo "[-] 7z 不可用, 仅产出 tar.gz"
    fi
fi

[ -f "$TARGZ" ] && echo "[+] ✅ 完成: $TARGZ"
[ -f "$OUTDIR/$NAME-$VER.7z" ] && echo "[+] ✅ 完成: $OUTDIR/$NAME-$VER.7z"

# 校验清单
echo "[*] 包内文件总数: $(tar -tzf "$TARGZ" 2>/dev/null | wc -l)"
echo "[*] 包内最大文件:"
tar -tzvf "$TARGZ" 2>/dev/null | sort -k4 -rn | head -5 || true