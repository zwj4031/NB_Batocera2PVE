import re

# PVE `qm set --machine` 合法值: pc / q35 / pc-i440fx-<ver> / q35-<ver> 等
# 用户友好的 "i440fx" 不是合法机型, 需映射为 "pc" (PVE 中 pc 即 i440fx 标准机型)
_PVE_MACHINE_RE = re.compile(r'^(pc|q35|pc-i440fx|pc-q35)([-.][0-9]+(\.[0-9]+)?)?$')

_FRIENDLY_MAP = {
    "i440fx": "pc",
    "pc": "pc",
    "q35": "q35",
}


def normalize_pve_machine(raw):
    """返回 (提交值, 警告文本或None)
    - 已是合法 PVE 机型: 原样返回, 无警告
    - 友好别名 (i440fx): 映射为 pc, 返回提示
    - 非法: (None, 错误提示)
    """
    raw = (raw or "").strip()
    if not raw:
        return None, "机型未选择"
    if _PVE_MACHINE_RE.match(raw):
        return raw, None
    mapped = _FRIENDLY_MAP.get(raw.lower())
    if mapped and _PVE_MACHINE_RE.match(mapped):
        if mapped != raw:
            return mapped, "“%s” 不是 PVE 合法机型，将自动映射为 “%s” 提交" % (raw, mapped)
        return mapped, None
    return None, "“%s” 不是合法 PVE 机型（应为 pc / q35 / pc-i440fx-<版本> / q35-<版本>）" % raw
